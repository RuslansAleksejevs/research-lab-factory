#!/usr/bin/env python3
"""Executable Phase-A checks for source-only dependency snapshots."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


MODULE = Path(__file__).resolve().parents[1]
SCRIPTS = MODULE / "scripts"
IMPORTER = SCRIPTS / "import_lean_dependency_snapshot.py"
VALIDATOR = SCRIPTS / "validate_lean_dependency_snapshot.py"


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "lean_room_v2_snapshot_validator", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load dependency snapshot validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LeanDependencySnapshotPhaseATests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="lean-room-v2-phase-a-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git = shutil.which("git", path="/usr/bin:/bin:/usr/local/bin")
        self.assertIsNotNone(self.git, "Phase-A tests require local Git")
        self.env = dict(os.environ)
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env["PYTHONPYCACHEPREFIX"] = str(self.root / "pycache")

    def run_command(self, command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=str(cwd or self.root),
            env=self.env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def git_command(self, checkout: Path, *arguments: str) -> str:
        result = self.run_command([str(self.git), "-C", str(checkout), *arguments])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout.strip()

    def _package_manifest(self, name: str) -> dict[str, Any]:
        return {
            "version": "1.1.0",
            "packagesDir": ".lake/packages",
            "packages": [],
            "name": name,
            "lakeDir": ".lake",
        }

    def make_workspace(
        self,
        label: str,
        *,
        manifest_version: str = "1.1.0",
        fixed_toolchain: bool | None = None,
    ) -> tuple[Path, Path]:
        workspace = self.root / label
        package = workspace / ".lake/packages/Pkg"
        package.mkdir(parents=True)
        (package / ".gitignore").write_text(".lake/\n", encoding="utf-8")
        (package / "lakefile.toml").write_text(
            'name = "Pkg"\nversion = "0.1.0"\n\n[[lean_lib]]\nname = "Pkg"\n',
            encoding="utf-8",
        )
        (package / "lake-manifest.json").write_text(
            json.dumps(self._package_manifest("Pkg"), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        (package / "lean-toolchain").write_text(
            "leanprover/lean4:v4.32.0\n", encoding="utf-8"
        )
        (package / "Pkg.lean").write_text(
            "namespace Pkg\n\ntheorem tiny : True := True.intro\n\nend Pkg\n",
            encoding="utf-8",
        )
        self.git_command(package, "init", "-q")
        self.git_command(package, "config", "user.email", "lean-room@example.invalid")
        self.git_command(package, "config", "user.name", "Lean Room Eval")
        self.git_command(package, "add", "--all")
        self.git_command(package, "commit", "-q", "-m", "fixture")
        revision = self.git_command(package, "rev-parse", "HEAD")
        root_manifest: dict[str, Any] = {
            "version": manifest_version,
            "packagesDir": ".lake/packages",
            "packages": [
                {
                    "url": "https://example.invalid/Pkg",
                    "type": "git",
                    "subDir": None,
                    # Official Lake manifests use "" for direct unscoped
                    # dependencies (including the root Mathlib entry).
                    "scope": "",
                    "rev": revision,
                    "name": "Pkg",
                    "manifestFile": "lake-manifest.json",
                    "inputRev": "main",
                    "inherited": False,
                    "configFile": "lakefile.toml",
                }
            ],
            "name": "RootFixture",
            "lakeDir": ".lake",
        }
        if fixed_toolchain is not None:
            root_manifest["fixedToolchain"] = fixed_toolchain
        self.write_root_manifest(workspace, root_manifest)
        return workspace, package

    def write_root_manifest(self, workspace: Path, value: dict[str, Any]) -> None:
        (workspace / "lake-manifest.json").write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def read_root_manifest(self, workspace: Path) -> dict[str, Any]:
        return json.loads((workspace / "lake-manifest.json").read_text(encoding="utf-8"))

    def commit_and_rebind(self, workspace: Path, package: Path, message: str) -> None:
        self.git_command(package, "add", "--all")
        self.git_command(package, "commit", "-q", "-m", message)
        manifest = self.read_root_manifest(workspace)
        manifest["packages"][0]["rev"] = self.git_command(package, "rev-parse", "HEAD")
        self.write_root_manifest(workspace, manifest)

    def add_official_symlink_shape(self, workspace: Path, package: Path) -> None:
        scripts = package / "scripts/bench/size"
        scripts.mkdir(parents=True)
        for name in ("run", "lean"):
            target = scripts / name
            target.write_bytes(f"#!/bin/sh\nprintf '%s\\n' {name}\n".encode("utf-8"))
            target.chmod(0o755)
            (scripts / f"{name}.py").symlink_to(name)
        docs = package / "docs"
        docs.mkdir()
        (package / "README.md").write_text("# Package fixture\n", encoding="utf-8")
        (docs / "README.md").symlink_to("../README.md")
        self.commit_and_rebind(workspace, package, "add official tracked internal symlinks")

    def add_uninitialized_gitlink(
        self, workspace: Path, package: Path, relative: str = "lean_packages/std"
    ) -> str:
        commit_oid = self.git_command(package, "rev-parse", "HEAD")
        path = package.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.mkdir()
        self.git_command(
            package,
            "update-index",
            "--add",
            "--cacheinfo",
            "160000",
            commit_oid,
            relative,
        )
        self.git_command(package, "commit", "-q", "-m", "add uninitialized gitlink")
        manifest = self.read_root_manifest(workspace)
        manifest["packages"][0]["rev"] = self.git_command(package, "rev-parse", "HEAD")
        self.write_root_manifest(workspace, manifest)
        return commit_oid

    def import_snapshot(
        self, workspace: Path, destination: Path, snapshot_id: str = "SNAP-EVAL"
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            [
                sys.executable,
                str(IMPORTER),
                str(workspace),
                str(destination),
                "--snapshot-id",
                snapshot_id,
                "--actor",
                "phase-a-eval",
                "--json",
            ]
        )

    def validate(self, snapshot: Path) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            [sys.executable, str(VALIDATOR), str(snapshot), "--json"]
        )

    def assert_rejected(self, result: subprocess.CompletedProcess[str], *fragments: str) -> None:
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        rendered = (result.stdout + result.stderr).casefold()
        self.assertTrue(
            any(fragment.casefold() in rendered for fragment in fragments),
            f"none of {fragments!r} found in:\n{result.stdout}{result.stderr}",
        )

    def test_positive_lake_1_1_snapshot_is_portable_source_only_and_bound(self) -> None:
        workspace, _package = self.make_workspace("positive-1-1")
        destination = self.root / "snapshot-1-1"
        imported = self.import_snapshot(workspace, destination)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        payload = json.loads(imported.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["published"])
        self.assertFalse(payload["network_used"])
        self.assertEqual(payload["lake_manifest_version"], "1.1.0")
        self.assertEqual(payload["packages"], ["Pkg"])
        validated = self.validate(destination)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

        manifest = json.loads(
            (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        )
        serialized = (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        self.assertFalse(manifest["source_workspace_recorded"])
        self.assertNotIn(str(workspace), serialized)
        self.assertIsNone(manifest["lake_manifest"]["fixed_toolchain"])
        package_binding = manifest["packages"][0]
        self.assertRegex(package_binding["source_tree_sha256"], r"^[0-9a-f]{64}$")
        inventory = json.loads(
            (destination / package_binding["source_inventory"]).read_text(encoding="utf-8")
        )
        self.assertTrue(all(set(item) == {"path", "mode", "size", "sha256"} for item in inventory))
        self.assertFalse(any(path.name in {".git", ".lake"} for path in destination.rglob("*")))

    def test_positive_lake_1_2_binds_fixed_toolchain_and_ignores_root_package_cache(self) -> None:
        workspace, package = self.make_workspace(
            "positive-1-2", manifest_version="1.2.0", fixed_toolchain=True
        )
        package_cache = package / ".lake/build/lib/lean"
        package_cache.mkdir(parents=True)
        (package_cache / "Cached.olean").write_bytes(b"must-not-be-imported")
        destination = self.root / "snapshot-1-2"
        imported = self.import_snapshot(workspace, destination, "SNAP-V432")
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        manifest = json.loads(
            (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["lake_manifest"]["version"], "1.2.0")
        self.assertIs(manifest["lake_manifest"]["fixed_toolchain"], True)
        self.assertFalse((destination / "packages/Pkg/.lake").exists())
        self.assertEqual(self.validate(destination).returncode, 0)

    def test_inert_tracked_binary_asset_is_accepted_and_hash_bound(self) -> None:
        workspace, package = self.make_workspace("inert-binary-asset")
        assets = package / "doc"
        assets.mkdir()
        payload = b"\x89PNG\r\n\x1a\nphase-a-inert-fixture"
        (assets / "diagram.png").write_bytes(payload)
        self.commit_and_rebind(workspace, package, "add inert tracked PNG asset")
        destination = self.root / "snapshot-inert-binary-asset"
        imported = self.import_snapshot(workspace, destination)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        self.assertEqual(self.validate(destination).returncode, 0)
        copied = destination / "packages/Pkg/doc/diagram.png"
        self.assertEqual(copied.read_bytes(), payload)
        inventory = json.loads(
            (destination / "inventories/Pkg.json").read_text(encoding="utf-8")
        )
        entry = next(item for item in inventory if item["path"] == "doc/diagram.png")
        self.assertEqual(entry["sha256"], hashlib.sha256(payload).hexdigest())

    def test_tracked_internal_symlinks_are_bound_and_materialized_as_regular_files(self) -> None:
        workspace, package = self.make_workspace("official-symlink-shape")
        self.add_official_symlink_shape(workspace, package)
        destination = self.root / "snapshot-official-symlink-shape"
        imported = self.import_snapshot(workspace, destination)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        validated = self.validate(destination)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

        manifest = json.loads(
            (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        )
        binding = manifest["packages"][0]
        normalizations = binding["symlink_normalizations"]
        self.assertEqual(
            [item["source_path"] for item in normalizations],
            [
                "docs/README.md",
                "scripts/bench/size/lean.py",
                "scripts/bench/size/run.py",
            ],
        )
        self.assertEqual(normalizations[0]["link_text"], "../README.md")
        self.assertEqual(normalizations[0]["resolved_tracked_path"], "README.md")
        for item in normalizations:
            source = destination / "packages/Pkg" / item["source_path"]
            target = destination / "packages/Pkg" / item["resolved_tracked_path"]
            self.assertTrue(source.is_file())
            self.assertFalse(source.is_symlink())
            self.assertEqual(source.read_bytes(), target.read_bytes())
            self.assertEqual(
                stat.S_IMODE(source.stat().st_mode), stat.S_IMODE(target.stat().st_mode)
            )
            self.assertEqual(item["target_sha256"], hashlib.sha256(target.read_bytes()).hexdigest())
            self.assertEqual(item["materialized_mode"], format(stat.S_IMODE(target.stat().st_mode), "04o"))

    def test_uninitialized_gitlink_is_bound_as_unavailable_empty_directory(self) -> None:
        workspace, package = self.make_workspace("official-gitlink-shape")
        commit_oid = self.add_uninitialized_gitlink(workspace, package)
        destination = self.root / "snapshot-official-gitlink-shape"
        imported = self.import_snapshot(workspace, destination)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        validated = self.validate(destination)
        self.assertEqual(validated.returncode, 0, validated.stdout + validated.stderr)

        materialized = destination / "packages/Pkg/lean_packages/std"
        self.assertTrue(materialized.is_dir())
        self.assertFalse(materialized.is_symlink())
        self.assertEqual(list(materialized.iterdir()), [])
        manifest = json.loads(
            (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        )
        binding = manifest["packages"][0]
        self.assertEqual(
            binding["gitlink_omissions"],
            [
                {
                    "path": "lean_packages/std",
                    "commit_oid": commit_oid,
                    "materialized_as": "empty_directory",
                    "source_available": False,
                }
            ],
        )
        self.assertRegex(binding["gitlink_omissions_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            binding["source_tree_profile"],
            "lean-room-dependency-tree-v2-files-gitlink-omissions-sha256",
        )

    def test_gitlink_populated_initialized_missing_special_symlink_and_unbound_empty_reject(self) -> None:
        def populated(path: Path) -> None:
            (path / "unexpected.txt").write_text("unavailable source appeared\n", encoding="utf-8")

        def initialized(path: Path) -> None:
            (path / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

        def missing(path: Path) -> None:
            path.rmdir()

        def special(path: Path) -> None:
            path.rmdir()
            os.mkfifo(path)

        def linked(path: Path) -> None:
            path.rmdir()
            path.symlink_to("../../Pkg.lean")

        fixtures = {
            "populated": populated,
            "initialized": initialized,
            "missing": missing,
            "special": special,
            "symlink": linked,
        }
        for label, mutate in fixtures.items():
            with self.subTest(label=label):
                workspace, package = self.make_workspace(f"gitlink-{label}")
                self.add_uninitialized_gitlink(workspace, package)
                mutate(package / "lean_packages/std")
                destination = self.root / f"snapshot-gitlink-{label}"
                result = self.import_snapshot(workspace, destination)
                self.assert_rejected(
                    result,
                    "gitlink",
                    "empty",
                    "dirty",
                    ".git",
                    "special",
                    "symlink",
                    "tracked git tree",
                    "submodule",
                )
                self.assertFalse(destination.exists())

        workspace, package = self.make_workspace("unbound-empty-directory")
        (package / "untracked-empty").mkdir()
        result = self.import_snapshot(workspace, self.root / "snapshot-unbound-empty")
        self.assert_rejected(result, "untracked_empty", "gitlink", "empty")

    def test_gitlink_snapshot_contents_link_missing_and_record_tamper_reject(self) -> None:
        def mutate_contents(snapshot: Path) -> None:
            (snapshot / "packages/Pkg/lean_packages/std/unexpected").write_text(
                "tamper\n", encoding="utf-8"
            )

        def mutate_link(snapshot: Path) -> None:
            path = snapshot / "packages/Pkg/lean_packages/std"
            path.rmdir()
            path.symlink_to("../../Pkg.lean")

        def mutate_missing(snapshot: Path) -> None:
            (snapshot / "packages/Pkg/lean_packages/std").rmdir()

        for label, mutate in {
            "contents": mutate_contents,
            "link": mutate_link,
            "missing": mutate_missing,
        }.items():
            with self.subTest(label=label):
                workspace, package = self.make_workspace(f"gitlink-snapshot-{label}")
                self.add_uninitialized_gitlink(workspace, package)
                snapshot = self.root / f"snapshot-gitlink-tamper-{label}"
                imported = self.import_snapshot(workspace, snapshot)
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
                mutate(snapshot)
                self.assert_rejected(
                    self.validate(snapshot), "gitlink", "empty", "inventory", "symlink", "missing"
                )

        workspace, package = self.make_workspace("gitlink-record-tamper")
        self.add_uninitialized_gitlink(workspace, package)
        snapshot = self.root / "snapshot-gitlink-record-tamper"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        manifest_path = snapshot / "dependency-snapshot.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packages"][0]["gitlink_omissions"][0]["commit_oid"] = "0" * 40
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assert_rejected(self.validate(snapshot), "gitlink omission", "sha-256")

    def test_tracked_symlink_escape_dangling_and_loop_are_rejected(self) -> None:
        fixtures = {
            "escape": lambda package: (
                (package / "docs").mkdir(),
                (package / "docs/escape").symlink_to("../../outside"),
            ),
            "dangling": lambda package: (package / "dangling").symlink_to("missing"),
            "loop": lambda package: (
                (package / "link-a").symlink_to("link-b"),
                (package / "link-b").symlink_to("link-a"),
            ),
        }
        for label, create_fixture in fixtures.items():
            with self.subTest(label=label):
                workspace, package = self.make_workspace(f"tracked-link-{label}")
                create_fixture(package)
                self.commit_and_rebind(workspace, package, f"add {label} symlink")
                destination = self.root / f"snapshot-tracked-link-{label}"
                result = self.import_snapshot(workspace, destination)
                self.assert_rejected(result, "escape", "tracked regular", "loop", "symlink")
                self.assertFalse(destination.exists())

    def test_symlink_normalization_and_materialized_link_tamper_are_rejected(self) -> None:
        workspace, package = self.make_workspace("normalization-tamper")
        self.add_official_symlink_shape(workspace, package)
        snapshot = self.root / "snapshot-normalization-tamper"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        manifest_path = snapshot / "dependency-snapshot.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packages"][0]["symlink_normalizations"][0]["target_sha256"] = "0" * 64
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        self.assert_rejected(self.validate(snapshot), "symlink normalization", "sha-256")

        workspace, package = self.make_workspace("materialized-link-tamper")
        self.add_official_symlink_shape(workspace, package)
        snapshot = self.root / "snapshot-materialized-link-tamper"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        materialized = snapshot / "packages/Pkg/docs/README.md"
        materialized.unlink()
        materialized.symlink_to("../README.md")
        self.assert_rejected(self.validate(snapshot), "symlink", "forbidden")

    def test_executable_package_configuration_is_hash_bound_and_review_required(self) -> None:
        workspace, package = self.make_workspace(
            "executable-config", manifest_version="1.2.0", fixed_toolchain=False
        )
        (package / "lakefile.toml").unlink()
        (package / "lakefile.lean").write_text(
            "import Lake\nopen Lake DSL\npackage Pkg\nlean_lib Pkg\n",
            encoding="utf-8",
        )
        self.commit_and_rebind(workspace, package, "use executable package config")
        root_manifest = self.read_root_manifest(workspace)
        root_manifest["packages"][0]["configFile"] = "lakefile.lean"
        self.write_root_manifest(workspace, root_manifest)
        destination = self.root / "snapshot-executable-config"
        imported = self.import_snapshot(workspace, destination)
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        manifest = json.loads(
            (destination / "dependency-snapshot.json").read_text(encoding="utf-8")
        )
        package_binding = manifest["packages"][0]
        self.assertTrue(package_binding["executable_config"])
        self.assertTrue(package_binding["review_required"])
        self.assertEqual(package_binding["config_file"], "lakefile.lean")
        self.assertEqual(
            package_binding["config_sha256"],
            hashlib.sha256(
                (destination / "packages/Pkg/lakefile.lean").read_bytes()
            ).hexdigest(),
        )

    def test_atomic_publication_refuses_existing_destination_without_mutation(self) -> None:
        workspace, _package = self.make_workspace("no-overwrite")
        destination = self.root / "snapshot-existing"
        first = self.import_snapshot(workspace, destination)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = hashlib.sha256(
            (destination / "dependency-snapshot.json").read_bytes()
        ).hexdigest()
        second = self.import_snapshot(workspace, destination)
        self.assert_rejected(second, "already exists", "exists")
        after = hashlib.sha256(
            (destination / "dependency-snapshot.json").read_bytes()
        ).hexdigest()
        self.assertEqual(before, after)

    def test_unknown_versions_fields_floating_revisions_and_bad_fixed_toolchain_fail(self) -> None:
        mutations = {
            "unknown-version": lambda m: m.update(version="1.3.0"),
            "unknown-field": lambda m: m.update(attackerField=True),
            "floating-revision": lambda m: m["packages"][0].update(rev="main"),
            "bad-fixed-toolchain": lambda m: (
                m.update(version="1.2.0"),
                m.update(fixedToolchain="yes"),
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                workspace, _package = self.make_workspace(f"reject-{label}")
                manifest = self.read_root_manifest(workspace)
                mutate(manifest)
                self.write_root_manifest(workspace, manifest)
                destination = self.root / f"snapshot-{label}"
                result = self.import_snapshot(workspace, destination)
                self.assert_rejected(result, "manifest", "revision", "fixedtoolchain", "version")
                self.assertFalse(destination.exists())

    def test_case_colliding_package_names_and_checkout_revision_mismatch_fail(self) -> None:
        workspace, _package = self.make_workspace("collision")
        manifest = self.read_root_manifest(workspace)
        duplicate = dict(manifest["packages"][0])
        duplicate["name"] = "pkg"
        manifest["packages"].append(duplicate)
        self.write_root_manifest(workspace, manifest)
        collision = self.import_snapshot(workspace, self.root / "snapshot-collision")
        self.assert_rejected(collision, "collision", "package names")

        workspace, _package = self.make_workspace("revision-mismatch")
        manifest = self.read_root_manifest(workspace)
        manifest["packages"][0]["rev"] = "0" * 40
        self.write_root_manifest(workspace, manifest)
        mismatch = self.import_snapshot(workspace, self.root / "snapshot-mismatch")
        self.assert_rejected(mismatch, "does not equal manifest rev", "head")

    def test_import_rejects_metadata_links_special_precompiled_lfs_and_submodules(self) -> None:
        hazards = {
            "nested-git": lambda package: (package / "docs/.git").mkdir(parents=True),
            "nested-lake": lambda package: (package / "docs/.lake").mkdir(parents=True),
            "symlink": lambda package: (package / "escape-link").symlink_to("Pkg.lean"),
            "fifo": lambda package: os.mkfifo(package / "named-pipe"),
            "precompiled": lambda package: (package / "Injected.olean").write_bytes(b"opaque"),
            "lfs": lambda package: (package / "large.bin").write_bytes(
                b"version https://git-lfs.github.com/spec/v1\n"
                b"oid sha256:" + b"0" * 64 + b"\nsize 1\n"
            ),
            "submodule": lambda package: (package / ".gitmodules").write_text(
                '[submodule "x"]\npath = x\nurl = https://example.invalid/x\n',
                encoding="utf-8",
            ),
            "hardlink": lambda package: os.link(
                package / "Pkg.lean", package / "Pkg-hardlink.lean"
            ),
        }
        for label, create_hazard in hazards.items():
            with self.subTest(label=label):
                workspace, package = self.make_workspace(f"hazard-{label}")
                create_hazard(package)
                destination = self.root / f"snapshot-hazard-{label}"
                result = self.import_snapshot(workspace, destination)
                self.assert_rejected(
                    result,
                    ".git",
                    ".lake",
                    "symlink",
                    "special",
                    "precompiled",
                    "lfs",
                    "submodule",
                    "hard-link",
                    "dirty",
                    "untracked",
                )
                self.assertFalse(destination.exists())
                self.assertEqual(
                    list(destination.parent.glob(f".{destination.name}.stage-*")), []
                )

    def test_import_rejects_dirty_or_untracked_checkout_even_without_known_hazard(self) -> None:
        workspace, package = self.make_workspace("dirty-checkout")
        (package / "notes.txt").write_text("untracked\n", encoding="utf-8")
        result = self.import_snapshot(workspace, self.root / "snapshot-dirty")
        self.assert_rejected(result, "dirty", "tracked git tree", "untracked")

    def test_snapshot_validator_detects_byte_mode_metadata_and_cache_tamper(self) -> None:
        workspace, _package = self.make_workspace("tamper-bytes")
        snapshot = self.root / "snapshot-tamper-bytes"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        source = snapshot / "packages/Pkg/Pkg.lean"
        source.write_text(source.read_text(encoding="utf-8") + "\n-- tamper\n", encoding="utf-8")
        self.assert_rejected(self.validate(snapshot), "inventory", "sha-256", "mismatch")

        workspace, _package = self.make_workspace("tamper-mode")
        snapshot = self.root / "snapshot-tamper-mode"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        source = snapshot / "packages/Pkg/Pkg.lean"
        os.chmod(source, stat.S_IMODE(source.stat().st_mode) ^ stat.S_IXUSR)
        self.assert_rejected(self.validate(snapshot), "inventory", "mode", "mismatch")

        workspace, _package = self.make_workspace("tamper-metadata")
        snapshot = self.root / "snapshot-tamper-metadata"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        (snapshot / "packages/Pkg/.git").mkdir()
        self.assert_rejected(self.validate(snapshot), ".git", "metadata")

        workspace, _package = self.make_workspace("tamper-cache")
        snapshot = self.root / "snapshot-tamper-cache"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        (snapshot / "packages/Pkg/.lake").mkdir()
        self.assert_rejected(self.validate(snapshot), ".lake", "cache")

    def test_snapshot_manifest_graph_closure_and_fixed_toolchain_are_tamper_evident(self) -> None:
        fields = (
            ("dependency_graph_sha256", "0" * 64),
            ("dependency_closure_sha256", "1" * 64),
        )
        for field, replacement in fields:
            with self.subTest(field=field):
                workspace, _package = self.make_workspace(f"manifest-tamper-{field}")
                snapshot = self.root / f"snapshot-{field}"
                self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
                path = snapshot / "dependency-snapshot.json"
                manifest = json.loads(path.read_text(encoding="utf-8"))
                manifest[field] = replacement
                path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
                self.assert_rejected(self.validate(snapshot), "graph", "closure", "mismatch")

        workspace, _package = self.make_workspace(
            "fixed-tamper", manifest_version="1.2.0", fixed_toolchain=True
        )
        snapshot = self.root / "snapshot-fixed-tamper"
        self.assertEqual(self.import_snapshot(workspace, snapshot).returncode, 0)
        path = snapshot / "dependency-snapshot.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["lake_manifest"]["fixed_toolchain"] = False
        path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        self.assert_rejected(self.validate(snapshot), "fixedtoolchain", "binding mismatch")

    def test_importer_does_not_execute_caller_lake_curl_or_network_helpers(self) -> None:
        workspace, _package = self.make_workspace("no-network-tools")
        fake_bin = self.root / "fake-bin"
        fake_bin.mkdir()
        marker = self.root / "forbidden-helper-executed"
        for name in ("lake", "lean", "curl", "wget", "ssh"):
            helper = fake_bin / name
            helper.write_text(
                f"#!/bin/sh\nprintf executed > '{marker}'\nexit 99\n",
                encoding="utf-8",
            )
            helper.chmod(0o755)
        prior_path = self.env.get("PATH", "")
        self.env["PATH"] = str(fake_bin) + os.pathsep + prior_path
        destination = self.root / "snapshot-no-network-tools"
        result = self.import_snapshot(workspace, destination)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(marker.exists())

    def test_collision_key_covers_case_and_unicode_normalization(self) -> None:
        validator = _load_validator()
        self.assertEqual(validator._collision_key("A/Mathlib.lean"), validator._collision_key("a/mathlib.lean"))
        self.assertEqual(validator._collision_key("é.lean"), validator._collision_key("e\u0301.lean"))

    def test_templates_are_json_compatible_and_phase_a_noncertifying(self) -> None:
        manifest_template = json.loads(
            (MODULE / "templates/lean_room/dependency_snapshot_manifest.yaml").read_text(
                encoding="utf-8"
            )
        )
        review_template = json.loads(
            (MODULE / "templates/lean_room/dependency_snapshot_review.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest_template["record_type"], "lean_dependency_snapshot_v2")
        self.assertTrue(
            manifest_template["policies"][
                "uninitialized_gitlinks_materialized_as_unavailable_empty_directories"
            ]
        )
        self.assertTrue(
            manifest_template["policies"][
                "tracked_internal_symlinks_materialized_as_regular_files"
            ]
        )
        self.assertIn("gitlink_omissions", manifest_template["packages"][0])
        self.assertEqual(review_template["verdict"], "PENDING")
        checks = review_template["checks"]
        self.assertIn("no_unbound_symlink_special_or_hardlinked_input", checks)
        self.assertIn(
            "tracked_symlink_normalizations_reviewed_and_accepted_per_package",
            checks,
        )
        self.assertIn("no_precompiled_or_executable_binary_input", checks)
        self.assertIn("no_git_directory_or_lake_cache_metadata_in_snapshot", checks)
        self.assertIn(
            "no_lfs_pointer_or_populated_gitlink_input", checks
        )
        self.assertIn(
            "gitlink_omissions_reviewed_and_accepted_per_package",
            checks,
        )
        for semantically_false_legacy_key in (
            "no_symlink_special_or_hardlinked_input",
            "no_precompiled_or_binary_input",
            "no_git_or_lake_metadata_in_snapshot",
        ):
            self.assertNotIn(semantically_false_legacy_key, checks)
        residual = " ".join(review_template["residual_risks"]).casefold()
        self.assertIn("not with its original symlink filesystem", residual)
        self.assertIn("inert tracked binary assets", residual)
        self.assertIn("unavailable submodule source", residual)
        self.assertIn("fail closed", residual)
        self.assertFalse(review_template["phase_b_execution_authorized"])
        self.assertFalse(review_template["certificate_eligible"])
        self.assertFalse(review_template["automatic_math_status_change"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
