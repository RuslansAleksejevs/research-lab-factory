#!/usr/bin/env python3
"""Bounded orchestration and safety tests for the non-certifying Phase-B pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Callable, Mapping


MODULE = Path(__file__).resolve().parents[1]
SCRIPTS = MODULE / "scripts"
IMPORTER = SCRIPTS / "import_lean_dependency_snapshot.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import verify_lean_dependency_pilot as pilot  # noqa: E402
from lean_room import RoomDisabledError, ValidationError  # noqa: E402
from validate_lean_dependency_snapshot import (  # noqa: E402
    dependency_tree_sha256,
    scan_source_tree,
)
from verify_lean_case import CommandResult  # noqa: E402


TOOLCHAIN = "leanprover/lean4:v4.32.0"
OLD_PACKAGE_TOOLCHAIN = "leanprover/lean4:v4.27.0-rc1"


class LeanDependencyPilotTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lean-dependency-pilot-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin")
        self.assertIsNotNone(self.git)
        self.env = dict(os.environ)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONPYCACHEPREFIX"] = str(self.root / "pycache")
        self._write_room_state("enabled")
        self.project, self.snapshot = self._make_two_package_fixture()
        self.review = self._write_review(authorized=True)
        self.runtime = self._make_runtime(with_leanchecker=True)
        self.commands: list[list[str]] = []
        self.environments: list[dict[str, str]] = []
        self.profiles: list[str] = []
        self.command_cwds: list[Path] = []

    def _write_room_state(self, state: str) -> None:
        path = self.root / "research/formalization/lean_room_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "state": state,
                    "sequence": 1,
                    "updated_at_utc": "2026-07-15T00:00:00Z",
                    "actor": "phase-b-test",
                    "reason": "bounded test fixture",
                },
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _run(self, command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=str(cwd or self.root),
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=30,
        )

    def _git(self, checkout: Path, *arguments: str) -> str:
        result = self._run([str(self.git), "-C", str(checkout), *arguments])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    @staticmethod
    def _package_entry(name: str, revision: str) -> dict[str, Any]:
        return {
            "url": f"https://example.invalid/{name}",
            "type": "git",
            "subDir": None,
            "scope": "pilot",
            "rev": revision,
            "name": name,
            "manifestFile": "lake-manifest.json",
            "inputRev": "main",
            "inherited": False,
            "configFile": "lakefile.toml",
        }

    @staticmethod
    def _manifest(name: str, packages: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "version": "1.2.0",
            "packagesDir": ".lake/packages",
            "packages": packages,
            "name": name,
            "lakeDir": ".lake",
            "fixedToolchain": True,
        }

    def _commit_package(
        self,
        package: Path,
        name: str,
        dependencies: list[dict[str, Any]],
        package_toolchain: str = TOOLCHAIN,
        with_tracked_symlink: bool = False,
        with_source_hash_trace: bool = False,
    ) -> str:
        package.mkdir(parents=True)
        lakefile = [
            f'name = "{name}"',
            'version = "0.1.0"',
            "",
            "[[lean_lib]]",
            f'name = "{name}"',
        ]
        for dependency in dependencies:
            lakefile.extend(
                [
                    "",
                    "[[require]]",
                    f'name = "{dependency["name"]}"',
                    f'git = "{dependency["url"]}"',
                    f'rev = "{dependency["rev"]}"',
                ]
            )
        (package / "lakefile.toml").write_text("\n".join(lakefile) + "\n", encoding="utf-8")
        (package / "lake-manifest.json").write_text(
            json.dumps(self._manifest(name, dependencies), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (package / "lean-toolchain").write_text(
            package_toolchain + "\n", encoding="utf-8"
        )
        source = (
            f"namespace {name}\n\n"
            f"theorem tiny : True := True.intro\n\n"
            f"end {name}\n"
        )
        if dependencies:
            source = f'import {dependencies[0]["name"]}\n\n' + source
        (package / f"{name}.lean").write_text(source, encoding="utf-8")
        if with_tracked_symlink:
            (package / f"{name}Alias.lean").symlink_to(f"{name}.lean")
        if with_source_hash_trace:
            widget = package / "widget"
            widget.mkdir()
            (widget / "package-lock.json").write_text(
                '{"lockfileVersion": 3}\n', encoding="utf-8"
            )
            (widget / "package-lock.json.trace").write_text(
                "reviewed Lake replay trace\n", encoding="utf-8"
            )
        (package / ".gitignore").write_text(".lake/\n", encoding="utf-8")
        self._git(package, "init", "-q")
        self._git(package, "config", "user.email", "pilot@example.invalid")
        self._git(package, "config", "user.name", "Phase B Test")
        self._git(package, "add", "--all")
        self._git(package, "commit", "-q", "-m", "fixture")
        return self._git(package, "rev-parse", "HEAD")

    def _make_two_package_fixture(self) -> tuple[Path, Path]:
        workspace = self.root / "import-workspace"
        packages = workspace / ".lake/packages"
        package_b = packages / "PkgB"
        revision_b = self._commit_package(
            package_b,
            "PkgB",
            [],
            with_source_hash_trace=True,
        )
        entry_b = self._package_entry("PkgB", revision_b)
        package_a = packages / "PkgA"
        revision_a = self._commit_package(
            package_a,
            "PkgA",
            [entry_b],
            package_toolchain=OLD_PACKAGE_TOOLCHAIN,
            with_tracked_symlink=True,
        )
        entry_a = self._package_entry("PkgA", revision_a)
        root_manifest = self._manifest("PilotRoot", [entry_a, entry_b])
        (workspace / "lake-manifest.json").write_text(
            json.dumps(root_manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        snapshot = self.root / "pilot/snapshot"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        imported = self._run(
            [
                sys.executable,
                str(IMPORTER),
                str(workspace),
                str(snapshot),
                "--snapshot-id",
                "SNAP-PILOT-TWO-PACKAGE",
                "--actor",
                "phase-b-test",
                "--json",
            ]
        )
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)

        project = self.root / "pilot/project"
        project.mkdir(parents=True)
        shutil.copyfile(snapshot / "lake-manifest.json", project / "lake-manifest.json")
        (project / "lean-toolchain").write_text(TOOLCHAIN + "\n", encoding="utf-8")
        (project / "lakefile.toml").write_text(
            '\n'.join(
                [
                    'name = "PilotRoot"',
                    'version = "0.1.0"',
                    'defaultTargets = ["LeanRoomCase"]',
                    "",
                    "[[lean_lib]]",
                    'name = "LeanRoomCase"',
                    'globs = ["LeanRoomCase"]',
                    "",
                    "[[require]]",
                    'name = "PkgA"',
                    f'git = "{entry_a["url"]}"',
                    f'rev = "{entry_a["rev"]}"',
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (project / "LeanRoomCase.lean").write_text(
            "import PkgA\n\n"
            "namespace LeanRoomCase\n\n"
            "theorem answer : True := True.intro\n\n"
            "end LeanRoomCase\n",
            encoding="utf-8",
        )
        return project, snapshot

    def _review_value(
        self,
        authorized: bool,
        derived_sidecars: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        metadata_path = self.snapshot / "dependency-snapshot.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        checks = {name: authorized for name in pilot.REVIEW_CHECK_KEYS}
        return {
            "schema_version": 1,
            "record_type": pilot.REVIEW_RECORD_TYPE,
            "protocol_version": metadata["protocol_version"],
            "review_id": "REVIEW-PILOT-1",
            "reviewed_at": "2026-07-15T00:00:00Z",
            "reviewed_by": "phase-b-test",
            "snapshot_binding": {
                "artifact": "pilot/snapshot/dependency-snapshot.json",
                "sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
                "snapshot_id": metadata["snapshot_id"],
                "dependency_graph_sha256": metadata["dependency_graph_sha256"],
                "dependency_closure_sha256": metadata["dependency_closure_sha256"],
            },
            "verdict": pilot.REVIEW_VERDICT if authorized else "PENDING",
            "checks": checks,
            "package_configuration_reviews": [
                {
                    "name": package["name"],
                    "config_file": package["config_file"],
                    "config_sha256": package["config_sha256"],
                    "executable_config": package["executable_config"],
                    "gitlink_omissions_sha256": package["gitlink_omissions_sha256"],
                    "gitlink_omissions_reviewed": authorized,
                    "symlink_normalizations_sha256": package[
                        "symlink_normalizations_sha256"
                    ],
                    "symlink_normalizations_reviewed": authorized,
                    "toolchain": package["toolchain"],
                    "root_toolchain_compatibility_reviewed": authorized,
                    "reviewed": authorized,
                    "verdict": "APPROVED" if authorized else "PENDING",
                }
                for package in metadata["packages"]
            ],
            "derived_source_hash_sidecars": list(derived_sidecars or []),
            "open_issues": [] if authorized else ["review incomplete"],
            "residual_risks": [
                "Reviewed package configuration and elaborator code remain an expanded trust boundary.",
                (
                    "Package PkgA toolchain leanprover/lean4:v4.27.0-rc1 differs from "
                    "root toolchain leanprover/lean4:v4.32.0; compatibility was explicitly reviewed."
                ),
                (
                    "Package PkgA tracked symlink normalization was explicitly reviewed and "
                    "accepted as copied target bytes rather than original filesystem semantics."
                ),
                *(
                    [
                        "Package PkgB derived sidecar widget/package-lock.json.hash is a "
                        "literal writable exception; tracked source files remain read-only, "
                        "and this sidecar is not a snapshot input."
                    ]
                    if derived_sidecars
                    else []
                ),
            ],
            "phase_b_execution_authorized": authorized,
            "certificate_eligible": False,
            "automatic_math_status_change": False,
        }

    def _write_review(
        self,
        authorized: bool,
        derived_sidecars: list[dict[str, Any]] | None = None,
    ) -> Path:
        path = self.root / "pilot/review.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                self._review_value(authorized, derived_sidecars),
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    @staticmethod
    def _derived_sidecar_review() -> dict[str, Any]:
        return {
            "package": "PkgB",
            "source_artifact": "widget/package-lock.json",
            "trace_artifact": "widget/package-lock.json.trace",
            "reason_code": pilot.DERIVED_SOURCE_HASH_SIDECAR_REASON,
            "justification": (
                "Lake rehash uses the tracked trace to refresh this reviewed derived sidecar."
            ),
            "reviewed": True,
        }

    def _make_runtime(self, with_leanchecker: bool) -> pilot.ToolchainRuntime:
        toolchain_root = self.root / "tools/toolchain"
        bin_dir = toolchain_root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        lean = bin_dir / "lean"
        lake = bin_dir / "lake"
        sandbox = self.root / "tools/sandbox-exec"
        for path in (lean, lake, sandbox):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            path.chmod(0o755)
        leanchecker: Path | None = None
        if with_leanchecker:
            leanchecker = bin_dir / "leanchecker"
            leanchecker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            leanchecker.chmod(0o755)
        paths = {"lean": lean, "lake": lake, "sandbox-exec": sandbox}
        if leanchecker is not None:
            paths["leanchecker"] = leanchecker
        bindings: dict[str, dict[str, Any]] = {}
        for name, path in paths.items():
            bindings[name] = {
                "artifact": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "size": path.stat().st_size,
            }
        return pilot.ToolchainRuntime(
            TOOLCHAIN,
            toolchain_root,
            self.root / "tools/elan",
            lean,
            lake,
            sandbox,
            leanchecker,
            bindings,
        )

    def _args(
        self,
        run_id: str,
        *,
        require_leanchecker: bool = False,
        permitted_axioms: list[str] | None = None,
    ) -> argparse.Namespace:
        return argparse.Namespace(
            root=str(self.root),
            pilot_id="PILOT-TEST",
            runner_id="phase-b-test-runner",
            project="pilot/project",
            snapshot="pilot/snapshot",
            review="pilot/review.json",
            declaration="LeanRoomCase.answer",
            exact_type="True",
            permitted_axiom=list(permitted_axioms or []),
            run_id=run_id,
            timeout=5.0,
            require_leanchecker=require_leanchecker,
            json=True,
        )

    def _wrapper(self, profile: str, logical: list[str]) -> list[str]:
        self.profiles.append(profile)
        return ["sandbox", *logical]

    def _runner(
        self,
        _guard: Any,
        logical: list[str],
        _wrapped: list[str],
        _cwd: Path,
        environment: Mapping[str, str],
        _timeout: float,
    ) -> CommandResult:
        self.commands.append(list(logical))
        self.environments.append(dict(environment))
        self.command_cwds.append(_cwd)
        if "build" in logical:
            for sidecar in sorted((_cwd.parent / "packages").rglob("*.hash")):
                sidecar.write_bytes(b"0123456789abcdef")
            output_dir = _cwd / ".lake/build/lib/lean"
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "LeanRoomCase.olean").write_bytes(b"fake-kernel-object\n")
            (output_dir / "LeanRoomCase.ilean").write_bytes(b"fake-interface\n")
        if logical[-1] == "--version":
            name = Path(logical[0]).name
            output = (
                b"Lean (version 4.32.0)\n"
                if name == "lean"
                else b"Lake version 5.0.0-src+4.32.0\n"
            )
        elif "declaration_audit.lean" in logical[-1]:
            output = b"declaration does not depend on any axioms\n"
        else:
            output = b"ok\n"
        return CommandResult(
            list(logical),
            ["sandbox", *logical],
            "2026-07-15T00:00:00Z",
            "2026-07-15T00:00:01Z",
            0,
            output,
        )

    def _verify(
        self,
        run_id: str,
        *,
        require_leanchecker: bool = False,
        permitted_axioms: list[str] | None = None,
        runner: Callable[..., CommandResult] | None = None,
        runtime: pilot.ToolchainRuntime | None = None,
    ) -> pilot.PilotOutcome:
        return pilot.verify_pilot(
            self._args(
                run_id,
                require_leanchecker=require_leanchecker,
                permitted_axioms=permitted_axioms,
            ),
            runner=runner or self._runner,
            resolver=lambda _toolchain: runtime or self.runtime,
            wrapper=self._wrapper,
        )

    def test_success_uses_all_transitive_overrides_offline_build_and_noncertifying_status(self) -> None:
        outcome = self._verify("RUN-SUCCESS")
        self.assertEqual(outcome.status, pilot.SUCCESS_STATUS)
        self.assertEqual(outcome.exit_code, 0)
        self.assertIsNotNone(outcome.evidence_path)
        assert outcome.evidence_path is not None
        manifest = json.loads(
            (outcome.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        self.assertFalse(manifest["certificate_eligible"])
        self.assertEqual(manifest["lr_gates_claimed"], [])
        self.assertFalse(manifest["formal_correspondence_established"])
        self.assertTrue(manifest["inputs"]["review"]["phase_b_execution_authorized"])
        self.assertEqual(
            manifest["inputs"]["package_toolchain_mismatches"],
            [
                {
                    "package": "PkgA",
                    "package_toolchain": OLD_PACKAGE_TOOLCHAIN,
                    "root_toolchain": TOOLCHAIN,
                }
            ],
        )
        self.assertTrue(
            manifest["inputs"]["package_toolchain_mismatches_explicitly_reviewed"]
        )
        self.assertEqual(manifest["path_overrides"]["packages"], ["PkgA", "PkgB"])
        build_inventory_path = outcome.evidence_path / "build_artifact_inventory.json"
        self.assertTrue(build_inventory_path.is_file())
        self.assertEqual(
            hashlib.sha256(build_inventory_path.read_bytes()).hexdigest(),
            manifest["build_artifacts"]["inventory_sha256"],
        )
        self.assertEqual(
            (outcome.evidence_path / "dependency_snapshot_review.json").read_bytes(),
            self.review.read_bytes(),
        )
        override_document = json.loads(
            (outcome.evidence_path / "package-overrides.json").read_text(encoding="utf-8")
        )
        self.assertEqual(override_document["schemaVersion"], "1.2.0")
        overrides = override_document["packages"]
        self.assertEqual([item["name"] for item in overrides], ["PkgA", "PkgB"])
        self.assertTrue(all(item["type"] == "path" for item in overrides))
        self.assertTrue(all(item["dir"].startswith("../packages/") for item in overrides))

        build = next(command for command in self.commands if "build" in command)
        self.assertEqual(
            build[-6:],
            ["--rehash", "--reconfigure", "--keep-toolchain", "--no-cache", "build", "LeanRoomCase"],
        )
        rendered = "\n".join(" ".join(command) for command in self.commands)
        self.assertNotIn(" fetch ", f" {rendered} ")
        self.assertNotIn(" update ", f" {rendered} ")
        self.assertNotIn("try-cache", rendered)
        self.assertTrue(self.profiles)
        self.assertTrue(all("(deny default)" in profile for profile in self.profiles))
        self.assertTrue(all("(deny network*)" in profile for profile in self.profiles))
        write_line = next(
            line
            for line in self.profiles[0].splitlines()
            if line.startswith("(allow file-write*")
        )
        project_copy = self.command_cwds[0]
        build_root = project_copy.parent
        override_path = Path(next(item for item in build if item.startswith("--packages=")).split("=", 1)[1])
        self.assertNotIn(f'(subpath "{build_root}")', write_line)
        self.assertNotIn(f'(subpath "{project_copy}")', write_line)
        self.assertNotIn(f'(subpath "{override_path.parent}")', write_line)
        project_output = project_copy / ".lake"
        self.assertIn(f'(subpath "{project_output}")', write_line)
        post_write_line = next(
            line
            for line in self.profiles[-1].splitlines()
            if line.startswith("(allow file-write*")
        )
        self.assertNotIn(f'(subpath "{project_output}")', post_write_line)
        self.assertNotIn("/.lake\")", post_write_line)
        post_executable_line = next(
            line
            for line in self.profiles[-1].splitlines()
            if line.startswith("(allow file-map-executable")
        )
        self.assertNotIn(f'(subpath "{build_root}")', post_executable_line)
        self.assertNotIn(f'(subpath "{project_copy}")', post_executable_line)
        self.assertTrue(all(env["GIT_ALLOW_PROTOCOL"] == "file" for env in self.environments))
        self.assertTrue(all(env["MATHLIB_NO_CACHE_ON_UPDATE"] == "1" for env in self.environments))

    def test_reviewed_derived_hash_sidecar_is_literal_writable_and_evidence_bound(self) -> None:
        self.review = self._write_review(
            authorized=True,
            derived_sidecars=[self._derived_sidecar_review()],
        )
        outcome = self._verify("RUN-DERIVED-SIDECAR")
        self.assertEqual(outcome.status, pilot.SUCCESS_STATUS)
        assert outcome.evidence_path is not None
        inventory_path = (
            outcome.evidence_path / "derived_source_hash_sidecar_inventory.json"
        )
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        self.assertEqual(len(inventory), 1)
        item = inventory[0]
        self.assertEqual(item["package"], "PkgB")
        self.assertEqual(item["source_artifact"], "widget/package-lock.json")
        self.assertEqual(item["trace_artifact"], "widget/package-lock.json.trace")
        self.assertEqual(item["artifact"], "widget/package-lock.json.hash")
        self.assertEqual(item["size"], 16)
        self.assertEqual(item["mode"], "0444")
        self.assertEqual(item["nlink"], 1)
        self.assertTrue(item["same_inode_as_precreated"])
        self.assertEqual(item["precreated_inode"], item["final_inode"])
        manifest = json.loads(
            (outcome.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        summary = manifest["derived_source_hash_sidecars"]
        self.assertEqual(summary["artifact_count"], 1)
        self.assertEqual(
            summary["inventory_sha256"],
            hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["evidence_artifacts"][
                "derived_source_hash_sidecar_inventory"
            ]["sha256"],
            hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        )

        build_index = next(
            index for index, command in enumerate(self.commands) if "build" in command
        )
        build_profile = self.profiles[build_index]
        sidecar = (
            self.command_cwds[build_index].parent
            / "packages/PkgB/widget/package-lock.json.hash"
        )
        write_line = next(
            line
            for line in build_profile.splitlines()
            if line.startswith("(allow file-write*")
        )
        self.assertNotIn(f'(literal "{sidecar}")', write_line)
        self.assertNotIn(f'(subpath "{sidecar.parent}")', write_line)
        data_write_line = next(
            line
            for line in build_profile.splitlines()
            if line.startswith("(allow file-write-data")
        )
        self.assertIn(f'(literal "{sidecar}")', data_write_line)
        self.assertNotIn(f'(subpath "{sidecar.parent}")', data_write_line)
        post_write_line = next(
            line
            for line in self.profiles[-1].splitlines()
            if line.startswith("(allow file-write*")
        )
        self.assertNotIn(f'(literal "{sidecar}")', post_write_line)
        self.assertNotIn(f'(subpath "{sidecar.parent}")', post_write_line)
        self.assertFalse(
            any(
                line.startswith("(allow file-write-data")
                for line in self.profiles[-1].splitlines()
            )
        )

    def test_derived_hash_sidecar_review_fails_closed_on_unreviewed_bad_or_unbound_input(self) -> None:
        cases: list[tuple[str, dict[str, Any], str]] = []
        unreviewed = self._derived_sidecar_review()
        unreviewed["reviewed"] = False
        cases.append(("UNREVIEWED", unreviewed, "not explicitly reviewed"))

        bad_path = self._derived_sidecar_review()
        bad_path["source_artifact"] = "../widget/package-lock.json"
        bad_path["trace_artifact"] = "../widget/package-lock.json.trace"
        cases.append(("BAD-PATH", bad_path, "canonical relative POSIX path"))

        missing_trace = self._derived_sidecar_review()
        missing_trace["source_artifact"] = "PkgB.lean"
        missing_trace["trace_artifact"] = "PkgB.lean.trace"
        cases.append(("MISSING-TRACE", missing_trace, "trace is not snapshot-bound"))

        gibberish = self._derived_sidecar_review()
        gibberish["justification"] = (
            "alphaalpha betaalpha gammaalpha deltaalpha epsilonalph"
        )
        cases.append(("GIBBERISH", gibberish, "substantive justification"))

        bad_reason = self._derived_sidecar_review()
        bad_reason["reason_code"] = "GENERIC_BUILD_CACHE"
        cases.append(("BAD-REASON", bad_reason, "reason_code must exactly equal"))

        for suffix, reviewed, message in cases:
            with self.subTest(suffix=suffix):
                self.review = self._write_review(
                    authorized=True,
                    derived_sidecars=[reviewed],
                )
                with self.assertRaisesRegex(ValidationError, message):
                    self._verify(f"RUN-DERIVED-{suffix}")

        incomplete = self._review_value(
            authorized=True,
            derived_sidecars=[self._derived_sidecar_review()],
        )
        incomplete["checks"]["reviewed_source_adjacent_hash_sidecars"] = False
        self.review.write_text(
            json.dumps(incomplete, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "unapproved checks"):
            self._verify("RUN-DERIVED-CHECK-UNREVIEWED")

        bare_residual = self._review_value(
            authorized=True,
            derived_sidecars=[self._derived_sidecar_review()],
        )
        bare_residual["residual_risks"][-1] = (
            "PkgB widget/package-lock.json.hash"
        )
        self.review.write_text(
            json.dumps(bare_residual, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "literal writable exception"):
            self._verify("RUN-DERIVED-BARE-RESIDUAL")
        self.assertEqual(self.commands, [])

    def test_derived_hash_sidecar_bad_size_bytes_and_extra_source_mutation_fail_closed(self) -> None:
        self.review = self._write_review(
            authorized=True,
            derived_sidecars=[self._derived_sidecar_review()],
        )

        def wrong_bytes(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            if "build" in runner_args[1]:
                sidecar = (
                    runner_args[3].parent
                    / "packages/PkgB/widget/package-lock.json.hash"
                )
                sidecar.write_bytes(b"ABCDEF0123456789")
            return result

        with self.assertRaisesRegex(ValidationError, "16 lowercase hex"):
            self._verify("RUN-DERIVED-WRONG-BYTES", runner=wrong_bytes)
        self.assertFalse(
            (
                self.root
                / "research/formalization/dependency_pilots/PILOT-TEST/evidence/runs/RUN-DERIVED-WRONG-BYTES"
            ).exists()
        )

        def oversized(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            if "build" in runner_args[1]:
                sidecar = (
                    runner_args[3].parent
                    / "packages/PkgB/widget/package-lock.json.hash"
                )
                sidecar.write_bytes(b"a" * (1024 * 1024))
            return result

        with self.assertRaisesRegex(ValidationError, "exactly 16 bytes"):
            self._verify("RUN-DERIVED-OVERSIZED", runner=oversized)
        self.assertFalse(
            (
                self.root
                / "research/formalization/dependency_pilots/PILOT-TEST/evidence/runs/RUN-DERIVED-OVERSIZED"
            ).exists()
        )

        def mutate_source(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            if "build" in runner_args[1]:
                source = (
                    runner_args[3].parent
                    / "packages/PkgB/widget/package-lock.json"
                )
                source.write_bytes(source.read_bytes() + b"\n")
            return result

        with self.assertRaisesRegex(ValidationError, "package-copy:PkgB.*changed"):
            self._verify("RUN-DERIVED-SOURCE-MUTATION", runner=mutate_source)
        self.assertFalse(
            (
                self.root
                / "research/formalization/dependency_pilots/PILOT-TEST/evidence/runs/RUN-DERIVED-SOURCE-MUTATION"
            ).exists()
        )

    def test_generated_override_and_audit_controls_are_mutation_checked(self) -> None:
        def tamper_override(*runner_args: Any) -> CommandResult:
            logical = runner_args[1]
            if "build" in logical:
                override = Path(
                    next(item for item in logical if item.startswith("--packages=")).split(
                        "=", 1
                    )[1]
                )
                override.write_text("{}\n", encoding="utf-8")
            return self._runner(*runner_args)

        with self.assertRaisesRegex(ValidationError, "generated pilot control changed"):
            self._verify("RUN-OVERRIDE-TAMPER", runner=tamper_override)
        self.assertFalse(
            (
                self.root
                / "research/formalization/dependency_pilots/PILOT-TEST/evidence/runs/RUN-OVERRIDE-TAMPER"
            ).exists()
        )

        def tamper_audit(*runner_args: Any) -> CommandResult:
            logical = runner_args[1]
            if "build" in logical:
                override = Path(
                    next(item for item in logical if item.startswith("--packages=")).split(
                        "=", 1
                    )[1]
                )
                (override.parent / "declaration_audit.lean").write_text(
                    "#check True\n", encoding="utf-8"
                )
            return self._runner(*runner_args)

        with self.assertRaisesRegex(ValidationError, "generated pilot control changed"):
            self._verify("RUN-AUDIT-TAMPER", runner=tamper_audit)

    def test_post_build_audit_cannot_replace_bound_kernel_artifact(self) -> None:
        def tamper_olean(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            logical = runner_args[1]
            if logical and logical[-1].endswith("declaration_audit.lean"):
                cwd = runner_args[3]
                (cwd / ".lake/build/lib/lean/LeanRoomCase.olean").write_bytes(
                    b"substituted-after-build\n"
                )
            return result

        with self.assertRaisesRegex(ValidationError, "build artifacts changed"):
            self._verify("RUN-OLEAN-TAMPER", runner=tamper_olean)

    def test_build_output_symlink_and_hardlink_aliases_are_rejected(self) -> None:
        hardlink_project = self.root / "hardlink-output-project"
        hardlink_dir = hardlink_project / ".lake/build/lib/lean"
        hardlink_dir.mkdir(parents=True)
        artifact = hardlink_dir / "LeanRoomCase.olean"
        artifact.write_bytes(b"kernel-object\n")
        os.link(artifact, self.root / "writable-alias.olean")
        with self.assertRaisesRegex(ValidationError, "hard-linked"):
            pilot._build_artifact_inventory(hardlink_project, {})

        symlink_project = self.root / "symlink-output-project"
        build = symlink_project / ".lake/build"
        build.mkdir(parents=True)
        outside = self.root / "writable-search-path/lean"
        outside.mkdir(parents=True)
        (outside / "LeanRoomCase.olean").write_bytes(b"substituted\n")
        (build / "lib").symlink_to(outside.parent)
        with self.assertRaisesRegex(ValidationError, "symlink"):
            pilot._build_artifact_inventory(symlink_project, {})

    def test_review_is_mandatory_and_checked_before_tool_resolution_or_execution(self) -> None:
        self._write_review(authorized=False)
        called = False

        def resolver(_toolchain: str) -> pilot.ToolchainRuntime:
            nonlocal called
            called = True
            return self.runtime

        with self.assertRaisesRegex(ValidationError, "verdict|authorized|open issues"):
            pilot.verify_pilot(
                self._args("RUN-UNAUTHORIZED"),
                runner=self._runner,
                resolver=resolver,
                wrapper=self._wrapper,
            )
        self.assertFalse(called)
        self.assertEqual(self.commands, [])

    def test_snapshot_and_exact_manifest_byte_tamper_fail_before_execution(self) -> None:
        source = self.snapshot / "packages/PkgB/PkgB.lean"
        source.write_text(source.read_text(encoding="utf-8") + "-- tamper\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "Phase-A|mismatch"):
            self._verify("RUN-SNAPSHOT-TAMPER")
        self.assertEqual(self.commands, [])

        shutil.rmtree(self.root / "import-workspace")
        shutil.rmtree(self.root / "pilot")
        self.project, self.snapshot = self._make_two_package_fixture()
        self.review = self._write_review(authorized=True)
        project_manifest = self.project / "lake-manifest.json"
        project_manifest.write_bytes(project_manifest.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValidationError, "exactly equal"):
            self._verify("RUN-MANIFEST-TAMPER")

    def test_toolchain_mismatch_requires_exact_package_binding_and_explicit_review(self) -> None:
        value = json.loads(self.review.read_text(encoding="utf-8"))
        package_review = next(
            item
            for item in value["package_configuration_reviews"]
            if item["name"] == "PkgA"
        )
        package_review["root_toolchain_compatibility_reviewed"] = False
        self.review.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValidationError, "binding mismatch"):
            self._verify("RUN-TOOLCHAIN-UNREVIEWED")
        self.assertEqual(self.commands, [])

        self.review = self._write_review(authorized=True)
        value = json.loads(self.review.read_text(encoding="utf-8"))
        package_review = next(
            item
            for item in value["package_configuration_reviews"]
            if item["name"] == "PkgA"
        )
        package_review["toolchain"] = None
        self.review.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValidationError, "binding mismatch"):
            self._verify("RUN-TOOLCHAIN-STALE")
        self.assertEqual(self.commands, [])

        self.review = self._write_review(authorized=True)
        value = json.loads(self.review.read_text(encoding="utf-8"))
        package_review = next(
            item
            for item in value["package_configuration_reviews"]
            if item["name"] == "PkgA"
        )
        package_review["symlink_normalizations_reviewed"] = False
        self.review.write_text(
            json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(ValidationError, "binding mismatch"):
            self._verify("RUN-SYMLINK-NORMALIZATION-UNREVIEWED")
        self.assertEqual(self.commands, [])

    def test_original_input_mutation_during_build_prevents_evidence_publication(self) -> None:
        mutated = False

        def runner(*runner_args: Any) -> CommandResult:
            nonlocal mutated
            logical = runner_args[1]
            if "build" in logical and not mutated:
                mutated = True
                path = self.project / "LeanRoomCase.lean"
                path.write_text(path.read_text(encoding="utf-8") + "\n-- concurrent mutation\n")
            return self._runner(*runner_args)

        with self.assertRaisesRegex(ValidationError, "changed"):
            self._verify("RUN-MUTATION", runner=runner)
        target = (
            self.root
            / "research/formalization/dependency_pilots/PILOT-TEST/evidence/runs/RUN-MUTATION"
        )
        self.assertFalse(target.exists())

    def test_disabled_room_is_a_kill_switch_before_any_execution(self) -> None:
        self._write_room_state("disabled")
        with self.assertRaises(RoomDisabledError):
            self._verify("RUN-DISABLED")
        self.assertEqual(self.commands, [])

    def test_final_publication_state_change_emits_minimal_abort_tombstone(self) -> None:
        with mock.patch.object(
            pilot,
            "_publish_evidence",
            side_effect=RoomDisabledError("state changed before publication"),
        ):
            outcome = self._verify("RUN-FINAL-STATE-CHANGE")
        self.assertEqual(outcome.status, pilot.ABORT_STATUS)
        self.assertEqual(outcome.exit_code, 3)
        assert outcome.evidence_path is not None
        files = sorted(
            path.relative_to(outcome.evidence_path).as_posix()
            for path in outcome.evidence_path.rglob("*")
            if path.is_file()
        )
        self.assertEqual(files, ["pilot_manifest.json"])
        tombstone = json.loads(
            (outcome.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(tombstone["status"], pilot.ABORT_STATUS)
        self.assertFalse(tombstone["certificate_eligible"])

    def test_mid_build_kill_switch_emits_minimal_abort_tombstone(self) -> None:
        def aborting_runner(*runner_args: Any) -> CommandResult:
            logical = runner_args[1]
            if "build" not in logical:
                return self._runner(*runner_args)
            self._write_room_state("disabled")
            return CommandResult(
                list(logical),
                ["sandbox", *logical],
                "2026-07-15T00:00:00Z",
                "2026-07-15T00:00:01Z",
                3,
                b"room disabled during build\n",
                aborted_room_state=True,
            )

        outcome = self._verify("RUN-MID-BUILD-DISABLE", runner=aborting_runner)
        self.assertEqual(outcome.status, pilot.ABORT_STATUS)
        assert outcome.evidence_path is not None
        files = [
            path.name
            for path in outcome.evidence_path.iterdir()
            if path.is_file()
        ]
        self.assertEqual(files, ["pilot_manifest.json"])

    def test_nonfinite_timeout_is_rejected_before_state_or_execution(self) -> None:
        args = self._args("RUN-NAN-TIMEOUT")
        args.timeout = float("nan")
        called = False

        def resolver(_toolchain: str) -> pilot.ToolchainRuntime:
            nonlocal called
            called = True
            return self.runtime

        with self.assertRaisesRegex(ValidationError, "finite number"):
            pilot.verify_pilot(
                args,
                runner=self._runner,
                resolver=resolver,
                wrapper=self._wrapper,
            )
        self.assertFalse(called)
        self.assertEqual(self.commands, [])

    def test_required_leanchecker_is_bound_and_run_or_fails_closed_when_absent(self) -> None:
        outcome = self._verify("RUN-LEANCHECKER", require_leanchecker=True)
        self.assertEqual(outcome.status, pilot.SUCCESS_STATUS)
        checker_commands = [
            command for command in self.commands if any("leanchecker" in item for item in command)
        ]
        self.assertEqual(len(checker_commands), 2)
        lake_checker = next(
            command for command in checker_commands if Path(command[0]).name == "lake"
        )
        direct_checker = next(
            command
            for command in checker_commands
            if Path(command[0]).name == "leanchecker"
        )
        self.assertTrue(lake_checker[1].startswith("--packages="))
        self.assertEqual(lake_checker[-3], "env")
        self.assertEqual(lake_checker[-1], "LeanRoomCase")
        self.assertEqual(direct_checker[-1], "LeanRoomCase")
        assert outcome.evidence_path is not None
        checker_manifest = json.loads(
            (outcome.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )["leanchecker"]
        self.assertTrue(checker_manifest["executed"])
        self.assertTrue(checker_manifest["lake_environment_command_executed"])
        self.assertTrue(checker_manifest["deterministic_path_direct_command_executed"])

        self.commands.clear()
        self.environments.clear()
        self.profiles.clear()
        self.command_cwds.clear()

        def failing_checker(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            if Path(runner_args[1][0]).name == "leanchecker":
                result.exit_code = 9
                result.output = b"leanchecker rejected module\n"
            return result

        failed = self._verify(
            "RUN-LEANCHECKER-FAILS",
            require_leanchecker=True,
            runner=failing_checker,
        )
        self.assertEqual(failed.status, pilot.FAILURE_STATUS)
        assert failed.evidence_path is not None
        failed_manifest = json.loads(
            (failed.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(failed_manifest["failure_class"], "LEANCHECKER_FAILED")

        self.commands.clear()
        absent = self._make_runtime(with_leanchecker=False)
        with self.assertRaisesRegex(ValidationError, "no regular executable leanchecker"):
            self._verify("RUN-NO-LEANCHECKER", require_leanchecker=True, runtime=absent)
        self.assertEqual(self.commands, [])

    def test_axioms_require_explicit_per_run_allowance_below_hard_ceiling(self) -> None:
        def axiom_runner(*runner_args: Any) -> CommandResult:
            result = self._runner(*runner_args)
            if "declaration_audit.lean" in runner_args[1][-1]:
                result.output = b"declaration depends on axioms: [propext]\n"
            return result

        denied = self._verify("RUN-AXIOM-DENIED", runner=axiom_runner)
        self.assertEqual(denied.status, pilot.FAILURE_STATUS)
        self.assertNotEqual(denied.exit_code, 0)
        assert denied.evidence_path is not None
        denied_manifest = json.loads(
            (denied.evidence_path / "pilot_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(denied_manifest["permitted_axioms"], [])
        self.assertEqual(denied_manifest["reported_axioms"], ["propext"])

        allowed = self._verify(
            "RUN-AXIOM-ALLOWED",
            runner=axiom_runner,
            permitted_axioms=["propext"],
        )
        self.assertEqual(allowed.status, pilot.SUCCESS_STATUS)
        with self.assertRaisesRegex(ValidationError, "hard standard ceiling"):
            self._verify(
                "RUN-AXIOM-UNSAFE",
                permitted_axioms=["Classical.choice", "evilAxiom"],
            )

    def test_append_only_atomic_run_id_refuses_reuse_without_mutating_first_evidence(self) -> None:
        first = self._verify("RUN-APPEND-ONLY")
        assert first.evidence_path is not None
        manifest_path = first.evidence_path / "pilot_manifest.json"
        before = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        command_count = len(self.commands)
        with self.assertRaisesRegex(ValidationError, "already exists"):
            self._verify("RUN-APPEND-ONLY")
        after = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(len(self.commands), command_count)

    def test_root_admissions_and_executable_lakefile_are_rejected(self) -> None:
        source = self.project / "LeanRoomCase.lean"
        source.write_text(
            "import PkgA\n\nnamespace LeanRoomCase\n"
            "theorem answer : True := by sorry\nend LeanRoomCase\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "forbidden sorry"):
            self._verify("RUN-SORRY")
        source.write_text(
            "import PkgA\n\nnamespace LeanRoomCase\n"
            "theorem answer : True := True.intro\nend LeanRoomCase\n",
            encoding="utf-8",
        )
        (self.project / "lakefile.lean").write_text("package PilotRoot\n", encoding="utf-8")
        with self.assertRaisesRegex(ValidationError, "lakefile.lean"):
            self._verify("RUN-LAKEFILE-LEAN")

    def test_root_library_source_substitution_is_rejected_before_execution(self) -> None:
        lakefile = self.project / "lakefile.toml"
        canonical = lakefile.read_text(encoding="utf-8")
        lakefile.write_text(
            canonical.replace(
                'globs = ["LeanRoomCase"]',
                'srcDir = "../packages/PkgA"\nglobs = ["LeanRoomCase"]',
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "srcDir is forbidden"):
            self._verify("RUN-SRCDIR-SUBSTITUTION")
        self.assertEqual(self.commands, [])

        lakefile.write_text(
            canonical.replace(
                'globs = ["LeanRoomCase"]', 'globs = ["PkgA", "LeanRoomCase"]'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "canonical"):
            self._verify("RUN-GLOBS-SUBSTITUTION")
        self.assertEqual(self.commands, [])

    def test_requested_declaration_must_be_in_canonical_root_module(self) -> None:
        (self.project / "LeanRoomCase.lean").write_text(
            "import PkgA\n\nnamespace LeanRoomCase\n"
            "theorem other : True := True.intro\nend LeanRoomCase\n",
            encoding="utf-8",
        )
        (self.project / "Unused.lean").write_text(
            "namespace LeanRoomCase\n"
            "theorem answer : True := True.intro\n"
            "end LeanRoomCase\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValidationError, "specifically in canonical"):
            self._verify("RUN-OUT-OF-GLOB-DECLARATION")
        self.assertEqual(self.commands, [])

    def test_gitlink_omission_is_recreated_empty_and_population_fails_closed(self) -> None:
        source = self.root / "omission-source"
        (source / "vendor/Unavailable").mkdir(parents=True)
        (source / "Pkg.lean").write_text("theorem ok : True := True.intro\n", encoding="utf-8")
        inventory = scan_source_tree(source)
        omissions = [
            {
                "path": "vendor/Unavailable",
                "commit_oid": "0" * 40,
                "materialized_as": "empty_directory",
                "source_available": False,
            }
        ]
        digest = dependency_tree_sha256(source, inventory, omissions)
        target = self.root / "omission-copy"
        pilot._copy_inventory(source, target, inventory, omissions, digest)
        self.assertTrue((target / "vendor/Unavailable").is_dir())
        self.assertEqual(
            pilot._copy_mutations(target, inventory, "package-copy:fixture", omissions),
            [],
        )
        (target / "vendor/Unavailable/injected.txt").write_text("unexpected\n", encoding="utf-8")
        mutations = pilot._copy_mutations(
            target, inventory, "package-copy:fixture", omissions
        )
        self.assertTrue(any("populated" in item for item in mutations))


if __name__ == "__main__":
    unittest.main(verbosity=2)
