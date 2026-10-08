#!/usr/bin/env python3
"""Adversarial integration tests for the laboratory Lean Room.

Every mutating command uses ``--root`` with a fresh temporary laboratory.  The
canonical ``research/formalization/lean_room_state.json`` is read as an outer
kill-switch binding, but is never mutated by this module.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, Iterable, Optional
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
FIXTURES = REPO_ROOT / "evals/lean_room/fixtures"
TEMPLATES = REPO_ROOT / "templates/lean_room"


def tree_digest(root: Path) -> str:
    """Return a deterministic byte digest for all non-symlink files below root."""

    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    """Hash a possibly large toolchain artifact without loading it all at once."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_installed_lean_toolchain_after_enable(audit) -> Optional[str]:
    """Select an installed exact pin offline, after the caller enables its temp room.

    Floating ``elan show`` may consult the network even with update checks off.
    Use the production audit's canonical-account binary checks instead; no
    command, installation, download or user toolchain setting is changed.
    """
    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    if not account_home.is_absolute() or account_home.is_symlink():
        return None
    toolchains = account_home / ".elan/toolchains"
    try:
        audit.reject_symlink_components(toolchains, account_home)
        installed = list(toolchains.iterdir())
    except (audit.ValidationError, OSError):
        return None
    candidates = []
    for path in installed:
        match = re.fullmatch(r"leanprover--lean4---v(\d+)\.(\d+)\.(\d+)", path.name)
        if match:
            candidates.append((tuple(int(part) for part in match.groups()),
                               "leanprover/lean4:v" + ".".join(match.groups())))
    for _, toolchain in sorted(candidates, reverse=True):
        try:
            audit._canonical_binary_paths(toolchain)
        except (audit.ValidationError, OSError):
            continue
        return toolchain
    return None


class LeanRoomIntegrationTests(unittest.TestCase):
    maxDiff = None

    @classmethod
    def setUpClass(cls) -> None:
        required = (
            "lean_room.py",
            "new_lean_case.py",
            "freeze_lean_case.py",
            "validate_lean_case.py",
            "verify_lean_case.py",
            "record_lean_audit.py",
            "issue_lean_certificate.py",
        )
        missing = [name for name in required if not (SCRIPTS / name).is_file()]
        if missing:
            raise AssertionError(f"Lean Room implementation scripts missing: {missing}")
        if not TEMPLATES.is_dir():
            raise AssertionError(f"Lean Room templates missing: {TEMPLATES}")
        canonical_status = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "lean_room.py"),
                "--root",
                str(REPO_ROOT),
                "status",
                "--json",
            ],
            cwd=str(REPO_ROOT),
            text=True,
            capture_output=True,
            timeout=20,
        )
        if canonical_status.returncode != 0:
            raise unittest.SkipTest(
                "canonical Lean Room is disabled or invalid; executable room evals are fail-closed"
            )

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="lean-room-eval-")
        self.root = Path(self.temp.name)
        (self.root / "scripts").mkdir(parents=True)
        for name in (
            "lean_room.py",
            "new_lean_case.py",
            "freeze_lean_case.py",
            "validate_lean_case.py",
            "verify_lean_case.py",
            "record_lean_audit.py",
            "issue_lean_certificate.py",
        ):
            shutil.copy2(SCRIPTS / name, self.root / "scripts" / name)
        shutil.copytree(TEMPLATES, self.root / "templates/lean_room")
        self.env: Dict[str, str] = {
            **os.environ,
            "ELAN_NO_UPDATE_CHECK": "1",
            # If an implementation accidentally tries ordinary HTTP, fail fast.
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "",
            # A verifier in an isolated temp lab must still obey the user's
            # canonical one-sentence kill switch for this laboratory.
            "LEAN_ROOM_CONTROL_ROOT": str(REPO_ROOT),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_script(self, name: str, *args: str, timeout: int = 90) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.root / "scripts" / name), "--root", str(self.root), *args],
            cwd=str(self.root),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=self.env,
        )

    def load_script_module(self, filename: str):
        """Load a production script for a temp-root race test, without executing main."""

        module_name = f"_lean_room_eval_{Path(filename).stem}_{time.time_ns()}"
        spec = importlib.util.spec_from_file_location(module_name, SCRIPTS / filename)
        if spec is None or spec.loader is None:
            self.fail(f"cannot load script module: {filename}")
        sys.path.insert(0, str(SCRIPTS))
        try:
            module = importlib.util.module_from_spec(spec)
            # Python 3.9 dataclasses resolve postponed annotations through the
            # defining module while the class body is executed.
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
            sys.modules.pop(module_name, None)
        return module

    def assert_failed(self, result: subprocess.CompletedProcess[str], *fragments: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        output = (result.stdout + result.stderr).lower()
        if fragments:
            self.assertTrue(
                any(fragment.lower() in output for fragment in fragments),
                f"none of {fragments!r} found in:\n{result.stdout}{result.stderr}",
            )

    def command_diagnostic(self, result: subprocess.CompletedProcess[str]) -> str:
        details = result.stdout + result.stderr
        try:
            payload = json.loads(result.stdout)
            evidence = Path(payload["evidence"])
        except (json.JSONDecodeError, KeyError, TypeError):
            return details
        for name in ("build.log", "build_manifest.yaml"):
            path = evidence / name
            if path.is_file():
                details += f"\n===== {name} =====\n" + path.read_text(
                    encoding="utf-8", errors="replace"
                )
        return details

    def enable(self) -> None:
        result = self.run_script(
            "lean_room.py",
            "enable",
            "--actor",
            "lean-room-eval",
            "--reason",
            "isolated test setup",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def require_installed_toolchain(self) -> str:
        status = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertEqual(json.loads(status.stdout)["effective_state"], "enabled")
        audit = self.load_script_module("record_lean_audit.py")
        toolchain = find_installed_lean_toolchain_after_enable(audit)
        if toolchain is None:
            self.skipTest("requires an already-installed elan Lean toolchain and lake")
        return toolchain

    def test_offline_toolchain_discovery_uses_only_safe_canonical_installations(self) -> None:
        self.enable()
        audit = self.load_script_module("record_lean_audit.py")
        account = self.root / "synthetic-account"
        elan = account / ".elan"
        (elan / "bin").mkdir(parents=True)
        (elan / "bin/elan").write_bytes(b"synthetic executable, never run")
        (elan / "bin/elan").chmod(0o755)
        for version in ("4.9.0", "4.10.0"):
            directory = elan / "toolchains" / ("leanprover--lean4---v" + version) / "bin"
            directory.mkdir(parents=True)
            for name in ("lean", "lake"):
                (directory / name).write_bytes(b"synthetic executable, never run")
                (directory / name).chmod(0o755)
        toolchains = elan / "toolchains"
        (toolchains / "leanprover--lean4---stable").mkdir()
        (toolchains / "leanprover--lean4---v999.0.0").symlink_to(
            toolchains / "leanprover--lean4---v4.10.0", target_is_directory=True)
        with patch.object(pwd, "getpwuid", return_value=SimpleNamespace(pw_dir=str(account))), \
                patch.object(subprocess, "run", side_effect=AssertionError("Discovery must stay offline")), \
                patch.object(shutil, "which", side_effect=AssertionError("Do not trust PATH shims")):
            self.assertEqual(find_installed_lean_toolchain_after_enable(audit), "leanprover/lean4:v4.10.0")
            newest = toolchains / "leanprover--lean4---v4.10.0/bin/lean"
            newest.unlink()
            newest.symlink_to(toolchains / "leanprover--lean4---v4.9.0/bin/lean")
            self.assertEqual(find_installed_lean_toolchain_after_enable(audit), "leanprover/lean4:v4.9.0")
            oldest = toolchains / "leanprover--lean4---v4.9.0/bin/lake"
            oldest.chmod(0o644)
            self.assertIsNone(find_installed_lean_toolchain_after_enable(audit))
            oldest.chmod(0o755)
            (elan / "bin/elan").unlink()
            self.assertIsNone(find_installed_lean_toolchain_after_enable(audit))
            (elan / "bin/elan").write_bytes(b"synthetic executable, never run")
            (elan / "bin/elan").chmod(0o755)
            relocated = account / "relocated-elan"
            elan.rename(relocated)
            elan.symlink_to(relocated, target_is_directory=True)
            self.assertIsNone(find_installed_lean_toolchain_after_enable(audit))

    def require_verification_backend(self) -> None:
        status = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        sandbox = shutil.which("sandbox-exec")
        if sys.platform != "darwin" or sandbox is None:
            self.skipTest("requires the mandatory macOS sandbox-exec backend")
        probe = subprocess.run(
            [sandbox, "-p", "(version 1)\n(allow default)\n", "/usr/bin/true"],
            text=True,
            capture_output=True,
            timeout=10,
            env=self.env,
        )
        if probe.returncode != 0:
            self.skipTest(
                "mandatory sandbox-exec backend cannot be applied in this outer environment: "
                + (probe.stdout + probe.stderr).strip()
            )

    def problem_dir(self, problem_id: str = "eval-problem") -> Path:
        target = self.root / "problems/active" / problem_id
        target.mkdir(parents=True, exist_ok=True)
        (target / "problem.md").write_text(
            "# Evaluation problem\n\nThe natural-number equality 1 + 1 = 2 holds.\n",
            encoding="utf-8",
        )
        (target / "proof_obligations.md").write_text(
            "# Proof obligations\n\n- `EVAL-OB-1`: Prove 1 + 1 = 2 in the natural numbers.\n",
            encoding="utf-8",
        )
        return target

    def create_case(
        self,
        case_id: str,
        *,
        problem_id: str = "eval-problem",
        theorem: str = "lean_room_expected",
        source_fixture: Optional[str] = None,
        toolchain: Optional[str] = None,
        exact_type: str = "1 + 1 = 2",
        complete_readiness: bool = True,
    ) -> Path:
        self.problem_dir(problem_id)
        toolchain = toolchain or "leanprover/lean4:v4.31.0"
        result = self.run_script(
            "new_lean_case.py",
            problem_id,
            case_id,
            "--informal-statement",
            "The natural-number equality 1 + 1 = 2 holds.",
            "--theorem",
            theorem,
            "--toolchain",
            toolchain,
            "--target-id",
            "EVAL-TARGET-1",
            "--target-artifact",
            f"problems/active/{problem_id}/problem.md",
            "--obligation-artifact",
            f"problems/active/{problem_id}/proof_obligations.md",
            "--obligation-id",
            "EVAL-OB-1",
            "--exact-formal-type",
            exact_type,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        case = self.root / "problems/active" / problem_id / "formalization/cases" / case_id
        self.assertTrue(case.is_dir(), f"case was not created: {case}")
        if complete_readiness:
            contract_path = case / "formalization_contract.yaml"
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["informal_claim"]["conclusion"] = (
                "The natural-number equality 1 + 1 = 2 holds."
            )
            contract["informal_claim"].update(
                {
                    "quantifiers": ["No quantified variables; this is a closed proposition."],
                    "hypotheses": ["No hypotheses."],
                    "ambient_objects_and_types": ["Natural numbers, represented by Lean Nat."],
                    "parameters_and_domains": ["Numerals 1 and 2 in Nat."],
                    "conventions": ["Lean addition and equality on Nat."],
                    "edge_cases": ["No parameters or degenerate cases."],
                    "anti_targets": [
                        "The analogous equality in a different numeric type or a different proposition."
                    ],
                }
            )
            contract["encoding"].update(
                {
                    "objects": ["Informal natural numbers map to Lean Nat."],
                    "relations_and_predicates": ["Informal equality maps to Lean Eq on Nat."],
                    "maps": ["Identity interpretation; no auxiliary map is used."],
                    "parameters": ["No parameters."],
                    "normalizations": ["Lean numeral notation for 1 and 2."],
                    "bridge_lemmas": ["No bridge lemma is needed because the formal type is exact."],
                    "known_loss_or_strengthening": ["None."],
                }
            )
            contract["trusted_boundary"].update(
                {
                    "authorized_exceptions": ["N/A — no authorized exceptions."],
                    "trusted_dependencies": ["N/A — dependency-free Lean core project."],
                    "residual_risks": [
                        "The pinned Lean kernel/toolchain and independent semantic attestation remain trusted."
                    ],
                }
            )
            acceptance = contract["acceptance_criterion"]
            acceptance["certificate_scope"] = (
                "Only EVAL-OB-1: the exact natural-number equality 1 + 1 = 2."
            )
            acceptance["explicit_nonclaims"] = [
                "No novelty, open-status, priority, or automatic dossier-status claim."
            ]
            intended_attestations = {
                "informal_target_complete",
                "formal_target_exact",
                "encoding_reviewed",
                "trust_boundary_reviewed",
                "lineage_and_exposure_recorded",
                "correspondence_plan_complete",
                "certificate_scope_and_nonclaims_complete",
                "stop_conditions_complete",
            }
            existing = acceptance.get("lr0_readiness_attestations")
            if isinstance(existing, dict):
                intended_attestations.update(existing)
            acceptance["lr0_readiness_attestations"] = {
                key: True for key in sorted(intended_attestations)
            }
            contract["lineage"]["coordinator_run_ids"] = ["EVAL-SETUP-RUN"]
            contract["lineage"]["prohibited_decisive_auditor_run_ids"] = [
                "EVAL-SETUP-RUN"
            ]
            contract["stop_conditions"] = [
                "Stop and supersede the case if the target, exact type, encoding, or trust boundary changes."
            ]
            contract_path.write_text(
                json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
        if source_fixture is not None:
            shutil.copy2(FIXTURES / source_fixture / "Main.lean", case / "project/Main.lean")
        return case

    def freeze_case(self, case_id: str, problem_id: str = "eval-problem") -> Path:
        lr0 = self.run_script(
            "freeze_lean_case.py",
            problem_id,
            case_id,
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(lr0.returncode, 0, lr0.stdout + lr0.stderr)
        after_lr0 = json.loads(
            (
                self.root
                / "problems/active"
                / problem_id
                / "formalization/cases"
                / case_id
                / "formalization_contract.yaml"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(after_lr0["status"], "DRAFT")
        self.assertTrue(after_lr0["freeze"]["lr0_contract_frozen"])
        self.assertFalse(after_lr0["freeze"]["lr1_sources_frozen"])
        lr1 = self.run_script(
            "freeze_lean_case.py",
            problem_id,
            case_id,
            "--gate",
            "LR1",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(lr1.returncode, 0, lr1.stdout + lr1.stderr)
        ready = self.run_script(
            "validate_lean_case.py", problem_id, case_id, "--verification-ready", "--json"
        )
        self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
        return self.root / "problems/active" / problem_id / "formalization/cases" / case_id

    def guarded_verify(
        self,
        case_id: str,
        *,
        runner_id: str,
        run_kind: str = "candidate",
        problem_id: str = "eval-problem",
    ) -> tuple[subprocess.CompletedProcess[str], Optional[str]]:
        result = self.run_script(
            "verify_lean_case.py",
            problem_id,
            case_id,
            "--runner-id",
            runner_id,
            "--run-kind",
            run_kind,
            "--json",
        )
        try:
            evidence = Path(json.loads(result.stdout)["evidence"])
            run_id: Optional[str] = evidence.name
        except (json.JSONDecodeError, KeyError, TypeError):
            run_id = None
        return result, run_id

    def write_positive_correspondence(
        self,
        case: Path,
        *,
        candidate_run_id: str,
        independent_run_id: str,
        auditor_id: str,
        auditor_run_id: str,
    ) -> None:
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        scope = contract["acceptance_criterion"]["certificate_scope"]
        report = """# Exact formal correspondence

Status: PASS

## Frozen informal target

The frozen informal target states the natural-number equality 1 + 1 = 2.

## Exact formal declaration

The audited Lean declaration has the exact type `1 + 1 = 2`; Lean elaborates
these numerals in `Nat` and the no-coercion kernel-definitional equality probe
passed.

## Object and type map

The informal natural numbers are exactly Lean `Nat`; addition and equality are
the standard `Nat` operations and `Eq`. No auxiliary representation is used.

## Quantifier and hypothesis audit

This is a closed proposition with no binders or hypotheses, so order, domains,
implicit instances, nonemptiness, and hypothesis use are all vacuous in the
literal no-parameter sense and do not weaken the target.

## Conclusion audit

The conclusion is exactly the same natural-number equality, not a stronger or
weaker neighboring proposition. The kernel-checked declaration directly proves
the bound obligation.

## Direction back to the target

No bridge lemma is needed: the frozen target and the checked Lean type are the
same proposition under the recorded `Nat` interpretation.

## Anti-target checks

The declaration is not polymorphic over another numeric type, not `True`, and
not an equality with a changed numeral or operation.

## Adversarial objections

All required attacks were checked against the exact frozen declaration and
found no weakening, hidden hypothesis, vacuity, domain change, implicit
instance change, or namespace substitution.

## Correspondence verdict

- Verdict: PASS
"""
        (case / "formal_correspondence.md").write_text(report, encoding="utf-8")
        verdict = json.loads(
            (self.root / "templates/lean_room/correspondence_verdict.yaml").read_text(
                encoding="utf-8"
            )
        )
        verdict.update(
            {
                "problem_id": contract["problem_id"],
                "case_id": contract["case_id"],
                "auditor_id": auditor_id,
                "auditor_run_id": auditor_run_id,
                "attested_at": "2000-01-01T00:00:00Z",
                "open_correspondence_obligations": [],
                "unresolved_objections": [],
                "highest_gap_class": "GS0",
                "exact_certificate_scope": scope,
                "explicit_nonclaims": list(
                    contract["acceptance_criterion"]["explicit_nonclaims"]
                ),
                "verdict": "PASS",
            }
        )
        verdict["bindings"].update(
            {
                "contract_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                "target_sha256": contract["target_binding"]["artifact_sha256"],
                "source_tree_sha256": contract["freeze"]["frozen_source_tree_sha256"],
                "candidate_run_id": candidate_run_id,
                "independent_run_id": independent_run_id,
            }
        )
        for key in verdict["checks"]:
            verdict["checks"][key] = True
        verdict["adversarial_checks"] = [
            {
                "attack_class": attack_class,
                "outcome": "PASS",
                "evidence": (
                    "Checked directly against the exact Nat equality, frozen contract, "
                    "and independently rebuilt declaration."
                ),
            }
            for attack_class in verdict["required_attack_classes"]
        ]
        (case / "correspondence_verdict.yaml").write_text(
            json.dumps(verdict, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

    def prepare_real_build_pair(
        self,
        case_id: str,
        *,
        candidate_runner: str,
        independent_runner: str,
    ) -> tuple[Path, str, str]:
        """Create, freeze, and guard-build one candidate/independent pair."""

        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case(case_id, source_fixture="valid", toolchain=toolchain)
        self.freeze_case(case_id)
        candidate, candidate_id = self.guarded_verify(
            case_id, runner_id=candidate_runner, run_kind="candidate"
        )
        independent, independent_id = self.guarded_verify(
            case_id, runner_id=independent_runner, run_kind="independent"
        )
        self.assertEqual(candidate.returncode, 0, self.command_diagnostic(candidate))
        self.assertEqual(independent.returncode, 0, self.command_diagnostic(independent))
        self.assertIsNotNone(candidate_id)
        self.assertIsNotNone(independent_id)
        self.assertNotEqual(candidate_id, independent_id)
        candidate_id = str(candidate_id)
        independent_id = str(independent_id)
        candidate_dir = case / "evidence/runs" / candidate_id
        independent_dir = case / "evidence/runs" / independent_id
        candidate_manifest_path = candidate_dir / "build_manifest.yaml"
        independent_manifest_path = independent_dir / "build_manifest.yaml"
        candidate_manifest = json.loads(
            candidate_manifest_path.read_text(encoding="utf-8")
        )
        independent_manifest = json.loads(
            independent_manifest_path.read_text(encoding="utf-8")
        )
        self.assertEqual(candidate_manifest["run_id"], candidate_id)
        self.assertEqual(candidate_manifest["run_kind"], "candidate")
        self.assertEqual(candidate_manifest["runner_id"], candidate_runner)
        self.assertEqual(independent_manifest["run_id"], independent_id)
        self.assertEqual(independent_manifest["run_kind"], "independent")
        self.assertEqual(independent_manifest["runner_id"], independent_runner)
        contract = json.loads(
            (case / "formalization_contract.yaml").read_text(encoding="utf-8")
        )
        frozen_source_digest = contract["freeze"]["frozen_source_tree_sha256"]
        for build_manifest in (candidate_manifest, independent_manifest):
            self.assertEqual(build_manifest["result"], "PASS")
            self.assertEqual(build_manifest["gates"], {"LR2": "PASS", "LR3": "PASS"})
            self.assertEqual(
                build_manifest["input_bindings"]["source_tree_sha256_before"],
                frozen_source_digest,
            )
            self.assertEqual(
                build_manifest["output_bindings"]["source_tree_sha256_after"],
                frozen_source_digest,
            )
            self.assertTrue(
                build_manifest["output_bindings"]["source_tree_unchanged"]
            )
        return case, str(candidate_id), str(independent_id)

    def record_positive_audit(
        self,
        case: Path,
        case_id: str,
        *,
        candidate_run_id: str,
        independent_run_id: str,
        auditor_id: str,
        audit_id: str,
    ) -> Path:
        """Write a complete PASS correspondence verdict and record its bound audit."""

        self.write_positive_correspondence(
            case,
            candidate_run_id=candidate_run_id,
            independent_run_id=independent_run_id,
            auditor_id=auditor_id,
            auditor_run_id=independent_run_id,
        )
        result = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            case_id,
            "--audit-id",
            audit_id,
            "--auditor-id",
            auditor_id,
            "--auditor-run-id",
            independent_run_id,
            "--candidate-run-id",
            candidate_run_id,
            "--independent-run-id",
            independent_run_id,
            "--verdict",
            "PASS",
            "--attest-exact-correspondence",
            "--highest-gap-class",
            "GS0",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        audit = case / "audits" / audit_id
        self.assertTrue((audit / "formal_audit_manifest.yaml").is_file())
        return audit

    def state_path(self) -> Path:
        return self.root / "research/formalization/lean_room_state.json"

    def event_path(self) -> Path:
        return self.root / "research/formalization/lean_room_events.jsonl"

    def read_events(self) -> Iterable[dict]:
        path = self.event_path()
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]

    def test_missing_malformed_and_unknown_state_fail_closed(self) -> None:
        missing = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(missing.returncode, 3, missing.stdout + missing.stderr)
        self.assert_failed(missing, "disabled", "missing", "invalid")

        self.problem_dir()
        blocked = self.run_script(
            "new_lean_case.py",
            "eval-problem",
            "must-not-exist",
            "--informal-statement",
            "Blocked.",
            "--theorem",
            "blocked",
        )
        self.assertEqual(blocked.returncode, 3, blocked.stdout + blocked.stderr)
        self.assertFalse(
            (self.root / "problems/active/eval-problem/formalization/cases/must-not-exist").exists()
        )

        self.state_path().parent.mkdir(parents=True, exist_ok=True)
        for invalid in (
            b"{not-json\n",
            json.dumps(
                {
                    "schema_version": 999,
                    "state": "enabled",
                    "sequence": 1,
                    "updated_at_utc": "2000-01-01T00:00:00Z",
                    "actor": "attacker",
                    "reason": "unknown schema must not enable",
                }
            ).encode("utf-8"),
        ):
            with self.subTest(invalid=invalid[:30]):
                self.state_path().write_bytes(invalid)
                result = self.run_script("lean_room.py", "status", "--json")
                self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                self.assert_failed(result, "disabled", "invalid", "schema")

    def test_symlinked_state_parent_is_fail_closed_and_transitions_refuse(self) -> None:
        self.enable()
        control = self.root / "research/formalization"
        escaped_control = self.root / "escaped-control"
        shutil.copytree(control, escaped_control)
        shutil.rmtree(control)
        control.symlink_to(escaped_control, target_is_directory=True)
        before = tree_digest(escaped_control)

        status = self.run_script("lean_room.py", "status", "--json")
        disable = self.run_script(
            "lean_room.py",
            "disable",
            "--actor",
            "attacker",
            "--reason",
            "must not follow state-parent symlink",
            "--json",
        )
        reenable = self.run_script(
            "lean_room.py",
            "enable",
            "--actor",
            "attacker",
            "--reason",
            "must not follow state-parent symlink",
            "--json",
        )
        self.assertEqual(status.returncode, 3, status.stdout + status.stderr)
        self.assert_failed(status, "symlink", "unsafe", "disabled", "invalid")
        self.assertNotEqual(disable.returncode, 0, disable.stdout + disable.stderr)
        self.assertNotEqual(reenable.returncode, 0, reenable.stdout + reenable.stderr)
        self.assertEqual(tree_digest(escaped_control), before)

    def test_staged_new_case_rejects_disable_then_enable_binding_change(self) -> None:
        self.enable()
        self.problem_dir()
        module = self.load_script_module("new_lean_case.py")
        args = module.build_parser().parse_args(
            [
                "--root",
                str(self.root),
                "eval-problem",
                "stale-new-case",
                "--informal-statement",
                "The natural-number equality 1 + 1 = 2 holds.",
                "--theorem",
                "lean_room_expected",
                "--exact-formal-type",
                "1 + 1 = 2",
                "--target-id",
                "EVAL-TARGET-1",
                "--target-artifact",
                "problems/active/eval-problem/problem.md",
                "--obligation-artifact",
                "problems/active/eval-problem/proof_obligations.md",
                "--obligation-id",
                "EVAL-OB-1",
            ]
        )
        original_render = module._render_correspondence

        def render_then_cycle_state(root: Path, values: dict[str, str]) -> str:
            rendered = original_render(root, values)
            disabled = self.run_script("lean_room.py", "disable", "--json")
            enabled = self.run_script("lean_room.py", "enable", "--json")
            self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
            self.assertEqual(enabled.returncode, 0, enabled.stdout + enabled.stderr)
            return rendered

        module._render_correspondence = render_then_cycle_state
        try:
            with self.assertRaises(module.LeanRoomError) as caught:
                module.create_case(args)
        finally:
            module._render_correspondence = original_render
        self.assertIn("stale publication", str(caught.exception).lower())
        target = self.root / "problems/active/eval-problem/formalization/cases/stale-new-case"
        self.assertFalse(target.exists() or target.is_symlink())
        self.assertEqual(
            list(target.parent.glob(".stale-new-case.stage-*")),
            [],
            "stale staging directory survived",
        )
        status = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)

    def test_staged_freeze_rejects_disable_then_enable_binding_change(self) -> None:
        self.enable()
        case = self.create_case("stale-freeze", source_fixture="valid")
        contract_path = case / "formalization_contract.yaml"
        before_contract = contract_path.read_bytes()
        module = self.load_script_module("freeze_lean_case.py")
        original_snapshot_stage = module._snapshot_stage

        def stage_then_cycle_state(*args, **kwargs):
            stage_and_target = original_snapshot_stage(*args, **kwargs)
            disabled = self.run_script("lean_room.py", "disable", "--json")
            enabled = self.run_script("lean_room.py", "enable", "--json")
            self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
            self.assertEqual(enabled.returncode, 0, enabled.stdout + enabled.stderr)
            return stage_and_target

        module._snapshot_stage = stage_then_cycle_state
        try:
            with self.assertRaises(module.LeanRoomError) as caught:
                module.freeze_lr0(
                    self.root.resolve(),
                    "eval-problem",
                    "stale-freeze",
                    "lean-room-eval",
                )
        finally:
            module._snapshot_stage = original_snapshot_stage
        self.assertIn("stale publication", str(caught.exception).lower())
        self.assertEqual(contract_path.read_bytes(), before_contract)
        freezes = case / "evidence/freezes"
        self.assertEqual(list(freezes.iterdir()), [], "stale freeze artifact survived")
        status = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)

    def test_disable_is_immediate_idempotent_and_preserves_artifacts(self) -> None:
        self.enable()
        case = self.create_case("preservation", source_fixture="valid")
        sentinel = case / "evidence/preexisting-certificate.txt"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("immutable prior artifact\n", encoding="utf-8")

        first = self.run_script(
            "lean_room.py", "disable", "--actor", "user", "--reason", "canonical kill switch"
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        disabled_state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.assertEqual(disabled_state["state"], "disabled")
        before = tree_digest(case)
        events_before_second = list(self.read_events())

        read_only_validation = self.run_script(
            "validate_lean_case.py", "eval-problem", "preservation", "--json"
        )
        self.assertEqual(
            read_only_validation.returncode,
            0,
            read_only_validation.stdout + read_only_validation.stderr,
        )
        self.assertEqual(tree_digest(case), before)
        build = self.run_script("verify_lean_case.py", "eval-problem", "preservation", "--json")
        self.assertEqual(build.returncode, 3, build.stdout + build.stderr)
        blocked_freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "preservation",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(blocked_freeze.returncode, 3, blocked_freeze.stdout + blocked_freeze.stderr)
        blocked_create = self.run_script(
            "new_lean_case.py",
            "eval-problem",
            "blocked-after-disable",
            "--informal-statement",
            "Must remain absent.",
            "--theorem",
            "blocked",
        )
        self.assertEqual(blocked_create.returncode, 3, blocked_create.stdout + blocked_create.stderr)
        self.assertFalse(
            (self.root / "problems/active/eval-problem/formalization/cases/blocked-after-disable").exists()
        )
        self.assertEqual(tree_digest(case), before)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutable prior artifact\n")

        second = self.run_script(
            "lean_room.py", "disable", "--actor", "user", "--reason", "repeat kill switch"
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        second_state = json.loads(self.state_path().read_text(encoding="utf-8"))
        self.assertEqual(second_state["state"], "disabled")
        self.assertEqual(second_state["sequence"], disabled_state["sequence"])
        events_after_second = list(self.read_events())
        self.assertEqual(len(events_after_second), len(events_before_second) + 1)
        self.assertFalse(events_after_second[-1]["changed"])
        self.assertEqual(tree_digest(case), before)

    def test_explicit_reenable_restores_creation_and_preserves_old_case(self) -> None:
        self.enable()
        old_case = self.create_case("before-disable", source_fixture="valid")
        old_digest = tree_digest(old_case)
        self.assertEqual(self.run_script("lean_room.py", "disable").returncode, 0)
        reenable = self.run_script(
            "lean_room.py", "enable", "--actor", "user", "--reason", "explicit room enable"
        )
        self.assertEqual(reenable.returncode, 0, reenable.stdout + reenable.stderr)
        status = self.run_script("lean_room.py", "status", "--json")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        self.assertEqual(json.loads(status.stdout)["effective_state"], "enabled")
        self.create_case("after-enable", source_fixture="valid")
        self.assertEqual(tree_digest(old_case), old_digest)

    def test_path_traversal_absolute_backslash_and_symlink_escape_rejected(self) -> None:
        self.enable()
        self.problem_dir()
        outside = self.root.parent / f"{self.root.name}-outside"
        outside.mkdir(exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        (self.root / "problems/active/symlink-problem").symlink_to(outside, target_is_directory=True)

        attacks = (
            ("../escape", "case"),
            ("eval-problem", "../../escape"),
            (str(outside), "case"),
            ("eval-problem", "..\\escape"),
            ("symlink-problem", "case"),
        )
        for problem_id, case_id in attacks:
            with self.subTest(problem_id=problem_id, case_id=case_id):
                result = self.run_script(
                    "new_lean_case.py",
                    problem_id,
                    case_id,
                    "--informal-statement",
                    "Traversal must fail.",
                    "--theorem",
                    "blocked",
                )
                self.assert_failed(result, "invalid", "unsafe", "escape", "path")
        self.assertEqual(list(outside.iterdir()), [])

    def test_static_trust_boundary_rejects_holes_axioms_and_native_decide(self) -> None:
        self.enable()
        expectations = {
            "sorry": ("sorry",),
            "admit": ("admit",),
            "custom_axiom": ("axiom",),
            "native_decide": ("native_decide", "native decide"),
            "auto_implicit": ("autoimplicit", "auto implicit"),
            "meta_elaborator": (
                "elaborator",
                "metaprogramming",
                "command_elab",
            ),
        }
        for fixture, fragments in expectations.items():
            with self.subTest(fixture=fixture):
                case_id = f"reject-{fixture.replace('_', '-')}"
                self.create_case(case_id, source_fixture=fixture)
                result = self.run_script(
                    "validate_lean_case.py", "eval-problem", case_id, "--json"
                )
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assert_failed(result, *fragments)

    def test_static_trust_boundary_rejects_notation_and_unbound_file_input(self) -> None:
        self.enable()
        attacks = {
            "notation-spoof": (
                'notation "LeanRoomSpoofedNat" => Bool\n\n'
                "theorem lean_room_expected : 1 + 1 = 2 := by decide\n",
                ("custom notation", "notation"),
            ),
            "include-str": (
                'def hostBytes : String := include_str "/private/etc/hosts"\n\n'
                "theorem lean_room_expected : 1 + 1 = 2 := by decide\n",
                ("unbound elaboration", "include_str"),
            ),
            "private-import-search-path": (
                "module\n"
                "private import Lean.Util.SearchPath\n"
                "def captured : System.SearchPath := compile_time_search_path%\n"
                "theorem lean_room_expected : 1 + 1 = 2 := by decide\n",
                ("module header", "local imports", "compile_time_search_path"),
            ),
            "external-stdlib-import": (
                "import Std\n\n"
                "theorem lean_room_expected : 1 + 1 = 2 := by decide\n",
                ("frozen project", "import must resolve"),
            ),
            "quoted-lean-import": (
                "import «Lean».Util.SearchPath\n"
                "theorem lean_room_expected : 1 + 1 = 2 := by decide\n",
                ("canonical unmodified local imports", "local imports"),
            ),
            "external-bv-certificate": (
                'theorem lean_room_expected : 1 + 1 = 2 := by bv_check "/private/etc/hosts"\n',
                ("bit-vector", "bv_check"),
            ),
            "external-bv-solver": (
                "theorem lean_room_expected : 1 + 1 = 2 := by bv_decide\n",
                ("bit-vector", "bv_decide"),
            ),
        }
        for case_id, (source, fragments) in attacks.items():
            with self.subTest(case_id=case_id):
                case = self.create_case(case_id, source_fixture="valid")
                (case / "project/Main.lean").write_text(source, encoding="utf-8")
                result = self.run_script(
                    "validate_lean_case.py", "eval-problem", case_id, "--json"
                )
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assert_failed(result, *fragments)

    def test_lr0_rejects_contract_axiom_outside_hard_v1_allowlist(self) -> None:
        self.enable()
        case = self.create_case("arbitrary-permitted-axiom", source_fixture="valid")
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["trusted_boundary"]["permitted_axioms"] = ["sorryAx"]
        contract["trusted_boundary"]["permitted_axiom_rationales"] = {
            "sorryAx": "An attacker-supplied rationale must not extend the hard v1 allowlist."
        }
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "arbitrary-permitted-axiom",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze.returncode, 5, freeze.stdout + freeze.stderr)
        self.assert_failed(freeze, "hard allowlist", "forbids axioms", "sorryax")

    def test_lr0_requires_exact_rationale_map_for_allowed_axioms(self) -> None:
        self.enable()
        case = self.create_case("axiom-rationale", source_fixture="valid")
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["trusted_boundary"]["permitted_axioms"] = ["Classical.choice"]
        contract["trusted_boundary"]["permitted_axiom_rationales"] = {}
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        missing = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "axiom-rationale",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(missing.returncode, 5, missing.stdout + missing.stderr)
        self.assert_failed(missing, "rationales", "classical.choice")

        contract["trusted_boundary"]["permitted_axiom_rationales"] = {
            "Classical.choice": (
                "This case explicitly relies on Lean's standard classical choice axiom."
            )
        }
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        accepted = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "axiom-rationale",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(accepted.returncode, 0, accepted.stdout + accepted.stderr)

    def test_nested_git_metadata_is_rejected_not_excluded_from_digest(self) -> None:
        self.enable()
        case = self.create_case("nested-git", source_fixture="valid")
        git_dir = case / "project/.git"
        git_dir.mkdir()
        (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")
        result = self.run_script("validate_lean_case.py", "eval-problem", "nested-git", "--json")
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assert_failed(result, ".git", "git metadata", "forbidden")

    def test_dependency_bearing_case_is_rejected_by_v1_before_freeze(self) -> None:
        self.enable()
        case = self.create_case("dependency-bearing", source_fixture="valid")
        manifest_path = case / "project/lake-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["packages"] = [
            {
                "name": "PinnedButUnsupportedDependency",
                "type": "git",
                "url": "https://example.invalid/pinned-dependency",
                "rev": "1" * 40,
                "inputRev": "1" * 40,
            }
        ]
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        contract["environment"]["dependency_free"] = False
        contract["environment"]["dependencies"] = [
            {
                "name": "PinnedButUnsupportedDependency",
                "type": "git",
                "revision": "1" * 40,
            }
        ]
        contract["environment"]["lake_manifest_sha256"] = hashlib.sha256(
            manifest_path.read_bytes()
        ).hexdigest()
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        validation = self.run_script(
            "validate_lean_case.py", "eval-problem", "dependency-bearing", "--json"
        )
        self.assertEqual(validation.returncode, 5, validation.stdout + validation.stderr)
        self.assertIn(
            "dependency-bearing cases are not certifiable by Lean Room v1",
            validation.stdout + validation.stderr,
        )
        freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "dependency-bearing",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze.returncode, 5, freeze.stdout + freeze.stderr)
        self.assertIn(
            "dependency-bearing cases are not certifiable by Lean Room v1",
            freeze.stdout + freeze.stderr,
        )
        after_freeze = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertFalse(after_freeze["freeze"]["lr0_contract_frozen"])
        self.assertEqual(list((case / "evidence/freezes").iterdir()), [])

    def test_placeholder_exact_type_cannot_cross_lr0(self) -> None:
        self.enable()
        self.create_case("placeholder-type", source_fixture="valid", exact_type="_")
        freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "placeholder-type",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze.returncode, 5, freeze.stdout + freeze.stderr)
        self.assert_failed(freeze, "exact_type", "placeholder", "wildcard", "exact type")

    def test_default_draft_cannot_cross_lr0_without_readiness_attestations(self) -> None:
        self.enable()
        self.create_case(
            "unattested-draft",
            source_fixture="valid",
            complete_readiness=False,
        )
        freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "unattested-draft",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze.returncode, 5, freeze.stdout + freeze.stderr)
        self.assert_failed(freeze, "attestation", "readiness", "conclusion", "scope")

    def test_true_attestations_cannot_hide_empty_semantic_contract_arrays(self) -> None:
        self.enable()
        case = self.create_case("empty-semantics", source_fixture="valid")
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        for key, value in contract["informal_claim"].items():
            if isinstance(value, list):
                contract["informal_claim"][key] = []
        for key, value in contract["encoding"].items():
            if isinstance(value, list):
                contract["encoding"][key] = []
        contract_path.write_text(
            json.dumps(contract, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        freeze = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "empty-semantics",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze.returncode, 5, freeze.stdout + freeze.stderr)
        self.assert_failed(freeze, "semantic", "informal_claim", "encoding", "empty")

    def test_valid_static_case_passes_and_keeps_correspondence_pending(self) -> None:
        self.enable()
        case = self.create_case("valid-static", source_fixture="valid")
        result = self.run_script("validate_lean_case.py", "eval-problem", "valid-static", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        contract = json.loads((case / "formalization_contract.yaml").read_text(encoding="utf-8"))
        self.assertEqual(contract["record_type"], "lean_formalization_contract")
        self.assertEqual(contract["status"], "DRAFT")
        self.assertFalse(contract["freeze"]["lr0_contract_frozen"])
        self.assertFalse(contract["freeze"]["lr1_sources_frozen"])
        self.assertFalse(any((case / "audits").glob("*/formal_audit_manifest.yaml")))
        self.assertFalse(any((case / "certificates").glob("*/formal_certificate_manifest.yaml")))

    def test_lr0_semantic_or_target_tamper_blocks_lr1(self) -> None:
        self.enable()
        case = self.create_case("lr0-tamper", source_fixture="valid")
        lr0 = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "lr0-tamper",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(lr0.returncode, 0, lr0.stdout + lr0.stderr)
        contract_path = case / "formalization_contract.yaml"
        frozen_lr0_bytes = contract_path.read_bytes()
        contract = json.loads(frozen_lr0_bytes.decode("utf-8"))
        self.assertEqual(contract["status"], "DRAFT")
        self.assertTrue(contract["freeze"]["lr0_contract_frozen"])

        contract["formal_target"]["exact_type"] = "True"
        contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        semantic_tamper = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "lr0-tamper",
            "--gate",
            "LR1",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(semantic_tamper.returncode, 5, semantic_tamper.stdout + semantic_tamper.stderr)
        self.assert_failed(semantic_tamper, "lr0", "digest", "changed", "tamper")
        self.assertFalse(json.loads(contract_path.read_text(encoding="utf-8"))["freeze"]["lr1_sources_frozen"])

        contract_path.write_bytes(frozen_lr0_bytes)
        target = self.root / "problems/active/eval-problem/problem.md"
        target.write_text(target.read_text(encoding="utf-8") + "\nPost-LR0 target mutation.\n", encoding="utf-8")
        target_tamper = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "lr0-tamper",
            "--gate",
            "LR1",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(target_tamper.returncode, 5, target_tamper.stdout + target_tamper.stderr)
        self.assert_failed(target_tamper, "target", "digest", "hash", "changed")
        restored_contract = json.loads(contract_path.read_text(encoding="utf-8"))
        self.assertEqual(restored_contract["status"], "DRAFT")
        self.assertFalse(restored_contract["freeze"]["lr1_sources_frozen"])

    def test_state_guard_terminates_inflight_process_without_corrupting_prior_artifacts(self) -> None:
        self.enable()
        case = self.create_case("inflight-disable", source_fixture="valid")
        self.freeze_case("inflight-disable")
        prior_files = {
            path.relative_to(case).as_posix(): path.read_bytes()
            for path in case.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        marker = self.root / "guarded-command-started"
        sleeper = self.root / "guarded_sleeper.py"
        sleeper.write_text(
            "from pathlib import Path\n"
            "import sys\n"
            "import time\n"
            "Path(sys.argv[1]).write_text('started\\n', encoding='utf-8')\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        harness = r"""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import lean_room
import verify_lean_case
root = Path(sys.argv[2])
status = lean_room.require_room_enabled(root, "state-guard integration evaluation")
guard = verify_lean_case._state_guard(root, status)
wrapped = [sys.executable, sys.argv[3], sys.argv[4]]
result = verify_lean_case.run_guarded(
    guard,
    ["guarded-sleeper"],
    wrapped,
    root,
    dict(os.environ),
    60.0,
)
print(json.dumps({
    "exit_code": result.exit_code,
    "aborted_room_state": result.aborted_room_state,
    "timed_out": result.timed_out,
    "output": result.output.decode("utf-8", errors="replace"),
}))
"""
        command = [
            sys.executable,
            "-c",
            harness,
            str(self.root / "scripts"),
            str(self.root),
            str(sleeper),
            str(marker),
        ]
        started = time.monotonic()
        process = subprocess.Popen(
            command,
            cwd=str(self.root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self.env,
        )
        deadline = time.monotonic() + 5
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not marker.exists():
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            self.fail(f"guarded process never started:\n{stdout}{stderr}")

        disabled = self.run_script(
            "lean_room.py",
            "disable",
            "--actor",
            "user",
            "--reason",
            "in-flight kill-switch evaluation",
            "--json",
        )
        self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate(timeout=2)
            self.fail(f"state guard ignored disabled state while command slept:\n{stdout}{stderr}")
        self.assertEqual(process.returncode, 0, stdout + stderr)
        self.assertLess(time.monotonic() - started, 8)
        result = json.loads(stdout)
        self.assertTrue(result["aborted_room_state"], result)
        self.assertFalse(result["timed_out"], result)
        self.assertEqual(result["exit_code"], 3, result)
        self.assertIn("process group terminated", result["output"])

        for relative, prior_bytes in prior_files.items():
            path = case / relative
            self.assertTrue(path.is_file(), f"prior artifact disappeared: {relative}")
            self.assertEqual(path.read_bytes(), prior_bytes, f"prior artifact mutated: {relative}")

    def test_certificate_cannot_issue_without_certificate_eligible_pass_audit(self) -> None:
        self.enable()
        case = self.create_case("no-pass-audit", source_fixture="valid")
        self.freeze_case("no-pass-audit")
        audit_id = "AUD-FAIL-EVAL"
        audit_dir = case / "audits" / audit_id
        audit_dir.mkdir(parents=True)
        (audit_dir / "formal_audit_manifest.yaml").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "record_type": "lean_formal_audit",
                    "problem_id": "eval-problem",
                    "case_id": "no-pass-audit",
                    "audit_id": audit_id,
                    "verdict": "FAIL",
                    "certificate_eligible": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        result = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "no-pass-audit",
            "--audit-id",
            audit_id,
            "--issued-by",
            "lean-room-eval",
            "--certificate-id",
            "CERT-MUST-NOT-EXIST",
            "--json",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assert_failed(result, "pass audit", "certificate-eligible", "lr6")
        self.assertFalse((case / "certificates/CERT-MUST-NOT-EXIST").exists())

    def test_forged_minimal_pass_manifests_cannot_form_audit_or_certificate(self) -> None:
        """Regression: labels and copied hashes are not genuine build evidence."""

        self.enable()
        case = self.create_case("forged-evidence", source_fixture="valid")
        self.freeze_case("forged-evidence")
        contract_path = case / "formalization_contract.yaml"
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        source_sha = contract["freeze"]["frozen_source_tree_sha256"]
        contract_sha = hashlib.sha256(contract_path.read_bytes()).hexdigest()
        toolchain = contract["environment"]["lean_toolchain"]
        runs = case / "evidence/runs"
        runs.mkdir(parents=True, exist_ok=True)
        for run_id, run_kind, runner_id in (
            ("RUN-FORGED-C", "candidate", "forged-candidate"),
            ("RUN-FORGED-I", "independent", "forged-auditor"),
        ):
            run = runs / run_id
            run.mkdir()
            manifest = {
                "schema_version": 1,
                "record_type": "lean_build_run",
                "problem_id": "eval-problem",
                "case_id": "forged-evidence",
                "run_id": run_id,
                "run_kind": run_kind,
                "runner_id": runner_id,
                "result": "PASS",
                "contract": {"sha256": contract_sha},
                "environment": {"lean_toolchain": toolchain},
                "input_bindings": {"source_tree_sha256_before": source_sha},
                "output_bindings": {
                    "source_tree_sha256_after": source_sha,
                    "source_tree_unchanged": True,
                },
                "gates": {"LR2": "PASS", "LR3": "PASS"},
            }
            (run / "build_manifest.yaml").write_text(
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                encoding="utf-8",
            )
            (run / "source_tree.sha256").write_text(source_sha + "\n", encoding="utf-8")
            (run / "axioms.txt").write_text(
                "'lean_room_expected' does not depend on any axioms\n",
                encoding="utf-8",
            )

        audit = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "forged-evidence",
            "--audit-id",
            "AUD-FORGED",
            "--auditor-id",
            "forged-auditor",
            "--auditor-run-id",
            "RUN-FORGED-I",
            "--candidate-run-id",
            "RUN-FORGED-C",
            "--independent-run-id",
            "RUN-FORGED-I",
            "--verdict",
            "FAIL",
            "--json",
        )
        self.assertEqual(audit.returncode, 5, audit.stdout + audit.stderr)
        self.assert_failed(
            audit,
            "evidence",
            "manifest",
            "integrity",
            "missing",
            "provenance",
            "state binding",
            "not pass",
        )
        self.assertFalse((case / "audits/AUD-FORGED").exists())

        certificate = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "forged-evidence",
            "--audit-id",
            "AUD-FORGED",
            "--issued-by",
            "forged-issuer",
            "--certificate-id",
            "CERT-FORGED",
            "--json",
        )
        self.assertEqual(certificate.returncode, 5, certificate.stdout + certificate.stderr)
        self.assertFalse((case / "certificates/CERT-FORGED").exists())

    def test_correspondence_pass_negative_matrix_is_fail_closed(self) -> None:
        self.enable()
        candidate_runner = "correspondence-candidate"
        auditor_id = "correspondence-independent"
        case, candidate_id, independent_id = self.prepare_real_build_pair(
            "correspondence-negative-matrix",
            candidate_runner=candidate_runner,
            independent_runner=auditor_id,
        )
        self.write_positive_correspondence(
            case,
            candidate_run_id=candidate_id,
            independent_run_id=independent_id,
            auditor_id=auditor_id,
            auditor_run_id=independent_id,
        )
        verdict_path = case / "correspondence_verdict.yaml"
        report_path = case / "formal_correspondence.md"
        base_verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
        base_report = report_path.read_text(encoding="utf-8")
        variants = (
            ("missing-attack", "missing adversarial correspondence checks"),
            ("check-false", "every required semantic correspondence check must be true"),
            ("open-objection", "PASS correspondence verdict has unresolved objections"),
            ("gs1", "PASS correspondence verdict requires highest_gap_class GS0"),
            ("scope-mismatch", "correspondence verdict certificate scope mismatch"),
            ("binding-mismatch", "correspondence verdict binding mismatch: target_sha256"),
            ("todo-report", "PASS correspondence report still contains template/open markers"),
        )
        for index, (variant, expected_error) in enumerate(variants, start=1):
            with self.subTest(variant=variant):
                verdict = json.loads(json.dumps(base_verdict))
                report = base_report
                if variant == "missing-attack":
                    verdict["adversarial_checks"] = verdict["adversarial_checks"][1:]
                elif variant == "check-false":
                    verdict["checks"]["conclusion_checked"] = False
                elif variant == "open-objection":
                    verdict["unresolved_objections"] = [
                        "The formal-to-informal direction remains disputed."
                    ]
                elif variant == "gs1":
                    verdict["highest_gap_class"] = "GS1"
                elif variant == "scope-mismatch":
                    verdict["exact_certificate_scope"] = "A broader, unauthorized claim."
                elif variant == "binding-mismatch":
                    current = verdict["bindings"]["target_sha256"]
                    verdict["bindings"]["target_sha256"] = (
                        "0" * 64 if current != "0" * 64 else "1" * 64
                    )
                elif variant == "todo-report":
                    report += "\nTODO: this marker must make PASS impossible.\n"
                verdict_path.write_text(
                    json.dumps(verdict, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8",
                )
                report_path.write_text(report, encoding="utf-8")
                audit_id = f"AUD-NEG-{index}"
                result = self.run_script(
                    "record_lean_audit.py",
                    "eval-problem",
                    "correspondence-negative-matrix",
                    "--audit-id",
                    audit_id,
                    "--auditor-id",
                    auditor_id,
                    "--auditor-run-id",
                    independent_id,
                    "--candidate-run-id",
                    candidate_id,
                    "--independent-run-id",
                    independent_id,
                    "--verdict",
                    "PASS",
                    "--attest-exact-correspondence",
                    "--highest-gap-class",
                    "GS0",
                    "--json",
                )
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                output = (result.stdout + result.stderr).lower()
                if variant == "missing-attack":
                    self.assertTrue(
                        expected_error.lower() in output
                        or "adversarial correspondence class mismatch" in output,
                        output,
                    )
                else:
                    self.assertIn(expected_error.lower(), output)
                self.assertFalse((case / "audits" / audit_id).exists())

    def test_one_byte_tamper_of_genuine_build_evidence_blocks_audit(self) -> None:
        self.enable()
        auditor_id = "tamper-independent"
        case, candidate_id, independent_id = self.prepare_real_build_pair(
            "genuine-build-tamper",
            candidate_runner="tamper-candidate",
            independent_runner=auditor_id,
        )
        self.write_positive_correspondence(
            case,
            candidate_run_id=candidate_id,
            independent_run_id=independent_id,
            auditor_id=auditor_id,
            auditor_run_id=independent_id,
        )
        candidate_log = case / "evidence/runs" / candidate_id / "build.log"
        before = candidate_log.read_bytes()
        candidate_log.write_bytes(before + b"\x00")
        self.assertEqual(candidate_log.stat().st_size, len(before) + 1)

        result = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "genuine-build-tamper",
            "--audit-id",
            "AUD-TAMPERED-BUILD",
            "--auditor-id",
            auditor_id,
            "--auditor-run-id",
            independent_id,
            "--candidate-run-id",
            candidate_id,
            "--independent-run-id",
            independent_id,
            "--verdict",
            "PASS",
            "--attest-exact-correspondence",
            "--highest-gap-class",
            "GS0",
            "--json",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn("build log hash mismatch", result.stdout + result.stderr)
        self.assertFalse((case / "audits/AUD-TAMPERED-BUILD").exists())

    def test_one_byte_tamper_of_pass_audit_blocks_certificate(self) -> None:
        self.enable()
        auditor_id = "audit-tamper-independent"
        case, candidate_id, independent_id = self.prepare_real_build_pair(
            "pass-audit-tamper",
            candidate_runner="audit-tamper-candidate",
            independent_runner=auditor_id,
        )
        audit = self.record_positive_audit(
            case,
            "pass-audit-tamper",
            candidate_run_id=candidate_id,
            independent_run_id=independent_id,
            auditor_id=auditor_id,
            audit_id="AUD-BEFORE-TAMPER",
        )
        audit_manifest = audit / "formal_audit_manifest.yaml"
        before = audit_manifest.read_bytes()
        marker = b'"candidate_build_manifest_sha256": "'
        start = before.find(marker)
        self.assertGreaterEqual(start, 0)
        offset = start + len(marker)
        replacement = b"0" if before[offset : offset + 1] != b"0" else b"1"
        after = before[:offset] + replacement + before[offset + 1 :]
        self.assertEqual(len(after), len(before))
        self.assertEqual(sum(left != right for left, right in zip(before, after)), 1)
        audit_manifest.write_bytes(after)

        certificate = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "pass-audit-tamper",
            "--audit-id",
            "AUD-BEFORE-TAMPER",
            "--issued-by",
            "tamper-eval-issuer",
            "--certificate-id",
            "CERT-MUST-BLOCK-TAMPER",
            "--json",
        )
        self.assertEqual(certificate.returncode, 5, certificate.stdout + certificate.stderr)
        self.assertIn(
            "candidate build manifest SHA-256 mismatch",
            certificate.stdout + certificate.stderr,
        )
        self.assertFalse((case / "certificates/CERT-MUST-BLOCK-TAMPER").exists())

    def test_same_runner_candidate_and_independent_builds_cannot_form_audit(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case(
            "same-runner", source_fixture="valid", toolchain=toolchain
        )
        self.freeze_case("same-runner")
        candidate, candidate_id = self.guarded_verify(
            "same-runner", runner_id="same-runner", run_kind="candidate"
        )
        independent, independent_id = self.guarded_verify(
            "same-runner", runner_id="same-runner", run_kind="independent"
        )
        self.assertEqual(candidate.returncode, 0, self.command_diagnostic(candidate))
        self.assertEqual(independent.returncode, 0, self.command_diagnostic(independent))
        self.assertIsNotNone(candidate_id)
        self.assertIsNotNone(independent_id)
        self.write_positive_correspondence(
            case,
            candidate_run_id=str(candidate_id),
            independent_run_id=str(independent_id),
            auditor_id="same-runner",
            auditor_run_id=str(independent_id),
        )
        result = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "same-runner",
            "--audit-id",
            "AUD-SAME-RUNNER",
            "--auditor-id",
            "same-runner",
            "--auditor-run-id",
            independent_id,
            "--candidate-run-id",
            candidate_id,
            "--independent-run-id",
            independent_id,
            "--verdict",
            "PASS",
            "--attest-exact-correspondence",
            "--highest-gap-class",
            "GS0",
            "--json",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn(
            "independent build runner must differ from candidate runner",
            result.stdout + result.stderr,
        )
        self.assertFalse((case / "audits/AUD-SAME-RUNNER").exists())

    def test_disabled_room_blocks_audit_and_certificate_writes(self) -> None:
        self.enable()
        case = self.create_case("disabled-lr6", source_fixture="valid")
        self.freeze_case("disabled-lr6")
        disabled = self.run_script("lean_room.py", "disable", "--json")
        self.assertEqual(disabled.returncode, 0, disabled.stdout + disabled.stderr)
        before = tree_digest(case)
        audit = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "disabled-lr6",
            "--audit-id",
            "AUD-BLOCKED",
            "--auditor-id",
            "auditor",
            "--auditor-run-id",
            "AUDITOR-RUN",
            "--candidate-run-id",
            "RUN-CANDIDATE",
            "--independent-run-id",
            "RUN-INDEPENDENT",
            "--verdict",
            "FAIL",
            "--json",
        )
        certificate = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "disabled-lr6",
            "--audit-id",
            "AUD-BLOCKED",
            "--issued-by",
            "issuer",
            "--certificate-id",
            "CERT-BLOCKED",
            "--json",
        )
        self.assertEqual(audit.returncode, 3, audit.stdout + audit.stderr)
        self.assertEqual(certificate.returncode, 3, certificate.stdout + certificate.stderr)
        self.assertEqual(tree_digest(case), before)
        self.assertFalse((case / "audits/AUD-BLOCKED").exists())
        self.assertFalse((case / "certificates/CERT-BLOCKED").exists())

    def test_symlinked_freeze_container_cannot_escape_case(self) -> None:
        self.enable()

        freeze_case = self.create_case("symlink-freezes", source_fixture="valid")
        freeze_container = freeze_case / "evidence/freezes"
        freeze_container.rmdir()
        outside_freezes = self.root / "outside-freezes"
        outside_freezes.mkdir()
        freeze_container.symlink_to(outside_freezes, target_is_directory=True)
        freeze_result = self.run_script(
            "freeze_lean_case.py",
            "eval-problem",
            "symlink-freezes",
            "--gate",
            "LR0",
            "--actor",
            "lean-room-eval",
            "--json",
        )
        self.assertEqual(freeze_result.returncode, 5, freeze_result.stdout + freeze_result.stderr)
        self.assert_failed(freeze_result, "symlink", "unsafe", "container")
        self.assertEqual(list(outside_freezes.iterdir()), [])

    def test_symlinked_run_container_cannot_escape_case(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case(
            "symlink-runs", source_fixture="valid", toolchain=toolchain
        )
        self.freeze_case("symlink-runs")
        run_container = case / "evidence/runs"
        run_container.rmdir()
        outside_runs = self.root / "outside-runs"
        outside_runs.mkdir()
        run_container.symlink_to(outside_runs, target_is_directory=True)

        result = self.run_script(
            "verify_lean_case.py",
            "eval-problem",
            "symlink-runs",
            "--runner-id",
            "symlink-runner",
            "--run-kind",
            "candidate",
            "--json",
        )
        self.assertEqual(result.returncode, 5, self.command_diagnostic(result))
        self.assert_failed(result, "symlink", "unsafe", "container")
        self.assertEqual(list(outside_runs.iterdir()), [])

    def test_symlinked_audit_container_cannot_escape_case(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        audit_case = self.create_case(
            "symlink-audits", source_fixture="valid", toolchain=toolchain
        )
        self.freeze_case("symlink-audits")
        candidate, candidate_id = self.guarded_verify(
            "symlink-audits", runner_id="candidate-runner", run_kind="candidate"
        )
        independent, independent_id = self.guarded_verify(
            "symlink-audits", runner_id="independent-runner", run_kind="independent"
        )
        self.assertEqual(candidate.returncode, 0, self.command_diagnostic(candidate))
        self.assertEqual(independent.returncode, 0, self.command_diagnostic(independent))
        self.assertIsNotNone(candidate_id)
        self.assertIsNotNone(independent_id)
        audit_container = audit_case / "audits"
        shutil.rmtree(audit_container)
        outside_audits = self.root / "outside-audits"
        outside_audits.mkdir()
        audit_container.symlink_to(outside_audits, target_is_directory=True)
        audit_result = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "symlink-audits",
            "--audit-id",
            "AUD-ESCAPE",
            "--auditor-id",
            "independent-runner",
            "--auditor-run-id",
            independent_id,
            "--candidate-run-id",
            candidate_id,
            "--independent-run-id",
            independent_id,
            "--verdict",
            "FAIL",
            "--json",
        )
        self.assertEqual(audit_result.returncode, 5, audit_result.stdout + audit_result.stderr)
        self.assert_failed(audit_result, "symlink", "unsafe", "container")
        self.assertEqual(list(outside_audits.iterdir()), [])

    def test_symlinked_certificate_container_cannot_escape_case(self) -> None:
        self.enable()
        auditor_id = "certificate-symlink-independent"
        case, candidate_id, independent_id = self.prepare_real_build_pair(
            "symlink-certificates",
            candidate_runner="certificate-symlink-candidate",
            independent_runner=auditor_id,
        )
        self.record_positive_audit(
            case,
            "symlink-certificates",
            candidate_run_id=candidate_id,
            independent_run_id=independent_id,
            auditor_id=auditor_id,
            audit_id="AUD-CERTIFICATE-SYMLINK",
        )
        certificate_container = case / "certificates"
        shutil.rmtree(certificate_container)
        outside_certificates = self.root / "outside-certificates"
        outside_certificates.mkdir()
        certificate_container.symlink_to(
            outside_certificates, target_is_directory=True
        )

        result = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "symlink-certificates",
            "--audit-id",
            "AUD-CERTIFICATE-SYMLINK",
            "--issued-by",
            "certificate-symlink-issuer",
            "--certificate-id",
            "CERT-ESCAPE",
            "--json",
        )
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assert_failed(result, "symlink", "unsafe", "container")
        self.assertEqual(list(outside_certificates.iterdir()), [])

    def test_wrong_type_is_not_mistaken_for_static_correspondence_success(self) -> None:
        self.enable()
        case = self.create_case("wrong-theorem", source_fixture="wrong_theorem")
        result = self.run_script(
            "validate_lean_case.py", "eval-problem", "wrong-theorem", "--json"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        contract = json.loads((case / "formalization_contract.yaml").read_text(encoding="utf-8"))
        self.assertEqual(contract["formal_target"]["declaration_name"], "lean_room_expected")
        self.assertEqual(contract["formal_target"]["exact_type"], "1 + 1 = 2")
        self.assertEqual(contract["status"], "DRAFT")
        self.assertFalse(any((case / "certificates").glob("*/formal_certificate_manifest.yaml")))

    def test_guarded_exact_type_probe_rejects_compiling_wrong_type(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()

        bad_case = self.create_case(
            "wrong-type-contract",
            source_fixture="wrong_theorem",
            toolchain=toolchain,
            exact_type="1 + 1 = 2",
        )
        self.freeze_case("wrong-type-contract")
        rejected = self.run_script(
            "verify_lean_case.py", "eval-problem", "wrong-type-contract", "--json"
        )
        self.assertNotEqual(rejected.returncode, 0, rejected.stdout + rejected.stderr)
        bad_manifests = sorted((bad_case / "evidence/runs").glob("*/build_manifest.yaml"))
        for manifest_path in bad_manifests:
            result = json.loads(manifest_path.read_text(encoding="utf-8")).get("result")
            self.assertNotEqual(result, "PASS")
        self.assertFalse(any((bad_case / "certificates").glob("*/formal_certificate_manifest.yaml")))

        compiling_case = self.create_case(
            "wrong-type-matching-contract",
            source_fixture="wrong_theorem",
            toolchain=toolchain,
            exact_type="True",
        )
        self.freeze_case("wrong-type-matching-contract")
        accepted = self.run_script(
            "verify_lean_case.py", "eval-problem", "wrong-type-matching-contract", "--json"
        )
        self.assertEqual(
            accepted.returncode,
            0,
            "the same source must compile when the guarded contract states its actual type:\n"
            + self.command_diagnostic(accepted),
        )

    def test_guarded_exact_type_probe_rejects_user_defined_coercion(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case(
            "coercion-type-mismatch",
            source_fixture="coercion_mismatch",
            toolchain=toolchain,
            exact_type="Q",
        )
        self.freeze_case("coercion-type-mismatch")
        result = self.run_script(
            "verify_lean_case.py",
            "eval-problem",
            "coercion-type-mismatch",
            "--runner-id",
            "coercion-regression-runner",
            "--run-kind",
            "candidate",
            "--json",
        )
        self.assertEqual(result.returncode, 5, self.command_diagnostic(result))
        runs = sorted((case / "evidence/runs").glob("*/build_manifest.yaml"))
        self.assertEqual(len(runs), 1)
        manifest = json.loads(runs[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["result"], "FAIL")
        self.assertEqual(manifest["failure_class"], "DECLARATION_OR_TYPE_MISMATCH")
        self.assertEqual(manifest["gates"]["LR2"], "PASS")
        self.assertEqual(manifest["gates"]["LR3"], "FAIL")
        self.assertFalse(any((case / "certificates").glob("*/formal_certificate_manifest.yaml")))

    def test_valid_pinned_project_builds_and_records_append_only_evidence(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case("valid-build", source_fixture="valid", toolchain=toolchain)
        self.freeze_case("valid-build")
        verify = self.run_script("verify_lean_case.py", "eval-problem", "valid-build", "--json")
        self.assertEqual(verify.returncode, 0, self.command_diagnostic(verify))
        runs = sorted((case / "evidence/runs").iterdir())
        self.assertEqual(len(runs), 1)
        for filename in ("build_manifest.yaml", "build.log", "source_tree.sha256", "axioms.txt"):
            self.assertTrue((runs[0] / filename).is_file(), filename)
        manifest = json.loads((runs[0] / "build_manifest.yaml").read_text(encoding="utf-8"))
        self.assertIn(manifest.get("result"), ("PASS", "passed", "success", "SUCCESS"))
        self.assertEqual(manifest["environment"]["lean_toolchain"], toolchain)
        self.assertEqual(manifest["gates"]["LR2"], "PASS")
        self.assertEqual(manifest["gates"]["LR3"], "PASS")
        contract = json.loads((case / "formalization_contract.yaml").read_text(encoding="utf-8"))
        self.assertEqual(contract["status"], "FROZEN")
        self.assertTrue(contract["freeze"]["lr0_contract_frozen"])
        self.assertTrue(contract["freeze"]["lr1_sources_frozen"])
        self.assertFalse(any((case / "certificates").glob("*/formal_certificate_manifest.yaml")))

    def test_path_and_home_poisoning_cannot_replace_canonical_toolchain(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        fake_home = self.root / "attacker-home"
        fake_bin = self.root / "attacker-bin"
        fake_home.mkdir()
        fake_bin.mkdir()
        for executable in ("elan", "lean", "lake"):
            path = fake_bin / executable
            path.write_text(
                "#!/bin/sh\nprintf 'LEAN_ROOM_PATH_POISON_EXECUTED\\n'\nexit 0\n",
                encoding="utf-8",
            )
            path.chmod(0o755)
        self.env["PATH"] = str(fake_bin) + os.pathsep + self.env.get("PATH", "")
        self.env["HOME"] = str(fake_home)

        case = self.create_case(
            "poisoned-caller-environment",
            source_fixture="valid",
            toolchain=toolchain,
        )
        self.freeze_case("poisoned-caller-environment")
        verify = self.run_script(
            "verify_lean_case.py",
            "eval-problem",
            "poisoned-caller-environment",
            "--runner-id",
            "poison-resistant-runner",
            "--run-kind",
            "candidate",
            "--json",
        )
        self.assertEqual(verify.returncode, 0, self.command_diagnostic(verify))
        evidence = Path(json.loads(verify.stdout)["evidence"])
        manifest = json.loads(
            (evidence / "build_manifest.yaml").read_text(encoding="utf-8")
        )
        bindings = manifest["environment"]["binary_bindings"]
        for executable in ("elan", "lean", "lake"):
            artifact = Path(bindings[executable]["artifact"])
            self.assertTrue(artifact.is_absolute())
            self.assertFalse(str(artifact).startswith(str(fake_bin)))
            self.assertFalse(str(artifact).startswith(str(fake_home)))
            self.assertEqual(
                file_sha256(artifact),
                bindings[executable]["sha256"],
            )
            self.assertEqual(artifact.stat().st_size, bindings[executable]["size"])
        combined_versions = "\n".join(
            manifest["environment"][field]
            for field in (
                "lean_version_output",
                "lake_version_output",
                "elan_version_output",
            )
        )
        self.assertNotIn("LEAN_ROOM_PATH_POISON_EXECUTED", combined_versions)

    def test_genuine_independent_builds_can_reach_exact_scope_lr6_certificate(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case(
            "positive-lr6", source_fixture="valid", toolchain=toolchain
        )
        self.freeze_case("positive-lr6")
        candidate, candidate_id = self.guarded_verify(
            "positive-lr6", runner_id="eval-candidate-builder", run_kind="candidate"
        )
        independent, independent_id = self.guarded_verify(
            "positive-lr6",
            runner_id="eval-independent-builder",
            run_kind="independent",
        )
        self.assertEqual(candidate.returncode, 0, self.command_diagnostic(candidate))
        self.assertEqual(independent.returncode, 0, self.command_diagnostic(independent))
        self.assertIsNotNone(candidate_id)
        self.assertIsNotNone(independent_id)
        self.assertNotEqual(candidate_id, independent_id)
        candidate_id = str(candidate_id)
        independent_id = str(independent_id)
        candidate_dir = case / "evidence/runs" / candidate_id
        independent_dir = case / "evidence/runs" / independent_id
        candidate_manifest_path = candidate_dir / "build_manifest.yaml"
        independent_manifest_path = independent_dir / "build_manifest.yaml"
        candidate_manifest = json.loads(
            candidate_manifest_path.read_text(encoding="utf-8")
        )
        independent_manifest = json.loads(
            independent_manifest_path.read_text(encoding="utf-8")
        )
        self.assertEqual(candidate_manifest["run_id"], candidate_id)
        self.assertEqual(candidate_manifest["run_kind"], "candidate")
        self.assertEqual(candidate_manifest["runner_id"], "eval-candidate-builder")
        self.assertEqual(independent_manifest["run_id"], independent_id)
        self.assertEqual(independent_manifest["run_kind"], "independent")
        self.assertEqual(independent_manifest["runner_id"], "eval-independent-builder")
        contract = json.loads(
            (case / "formalization_contract.yaml").read_text(encoding="utf-8")
        )
        frozen_source_digest = contract["freeze"]["frozen_source_tree_sha256"]
        for build_manifest in (candidate_manifest, independent_manifest):
            self.assertEqual(build_manifest["result"], "PASS")
            self.assertEqual(build_manifest["gates"], {"LR2": "PASS", "LR3": "PASS"})
            self.assertEqual(
                build_manifest["input_bindings"]["source_tree_sha256_before"],
                frozen_source_digest,
            )
            self.assertEqual(
                build_manifest["output_bindings"]["source_tree_sha256_after"],
                frozen_source_digest,
            )
            self.assertTrue(
                build_manifest["output_bindings"]["source_tree_unchanged"]
            )

        # The decisive semantic auditor is the independent rebuild runner;
        # recorder policy binds both human/agent identity and exact run id.
        auditor_id = "eval-independent-builder"
        auditor_run_id = independent_id
        self.write_positive_correspondence(
            case,
            candidate_run_id=candidate_id,
            independent_run_id=independent_id,
            auditor_id=auditor_id,
            auditor_run_id=auditor_run_id,
        )
        audit = self.run_script(
            "record_lean_audit.py",
            "eval-problem",
            "positive-lr6",
            "--audit-id",
            "AUD-POSITIVE-LR6",
            "--auditor-id",
            auditor_id,
            "--auditor-run-id",
            auditor_run_id,
            "--candidate-run-id",
            candidate_id,
            "--independent-run-id",
            independent_id,
            "--verdict",
            "PASS",
            "--attest-exact-correspondence",
            "--highest-gap-class",
            "GS0",
            "--json",
        )
        self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
        audit_manifest_path = (
            case / "audits/AUD-POSITIVE-LR6/formal_audit_manifest.yaml"
        )
        audit_manifest = json.loads(audit_manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(
            audit_manifest["gate_verdicts"],
            {gate: "PASS" for gate in ("LR0", "LR1", "LR2", "LR3", "LR4", "LR5")},
        )
        self.assertEqual(audit_manifest["auditor_id"], "eval-independent-builder")
        self.assertEqual(audit_manifest["auditor_run_id"], independent_id)
        self.assertEqual(audit_manifest["trust_audit"]["permitted_axioms"], [])
        self.assertEqual(
            audit_manifest["trust_audit"]["permitted_axiom_rationales"], {}
        )
        self.assertTrue(audit_manifest["certificate_eligible"])
        lean_room_module = self.load_script_module("lean_room.py")
        candidate_run_tree_sha = lean_room_module.project_tree_inventory(candidate_dir)[1]
        independent_run_tree_sha = lean_room_module.project_tree_inventory(independent_dir)[1]
        self.assertEqual(
            audit_manifest["bindings"]["candidate_build_run_tree_sha256"],
            candidate_run_tree_sha,
        )
        self.assertEqual(
            audit_manifest["bindings"]["independent_build_run_tree_sha256"],
            independent_run_tree_sha,
        )
        certificate = self.run_script(
            "issue_lean_certificate.py",
            "eval-problem",
            "positive-lr6",
            "--audit-id",
            "AUD-POSITIVE-LR6",
            "--issued-by",
            "eval-certificate-issuer",
            "--certificate-id",
            "CERT-POSITIVE-LR6",
            "--json",
        )
        self.assertEqual(certificate.returncode, 0, certificate.stdout + certificate.stderr)
        manifest_path = (
            case
            / "certificates/CERT-POSITIVE-LR6/formal_certificate_manifest.yaml"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "ISSUED")
        self.assertEqual(
            manifest["gate_verdicts"],
            {
                gate: "PASS"
                for gate in ("LR0", "LR1", "LR2", "LR3", "LR4", "LR5", "LR6")
            },
        )
        self.assertEqual(manifest["bindings"]["source_tree_sha256"], frozen_source_digest)
        self.assertEqual(
            manifest["bindings"]["candidate_build_manifest"],
            f"evidence/runs/{candidate_id}/build_manifest.yaml",
        )
        self.assertEqual(
            manifest["bindings"]["independent_build_manifest"],
            f"evidence/runs/{independent_id}/build_manifest.yaml",
        )
        self.assertEqual(
            manifest["bindings"]["candidate_build_manifest_sha256"],
            hashlib.sha256(candidate_manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["bindings"]["independent_build_manifest_sha256"],
            hashlib.sha256(independent_manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["bindings"]["candidate_build_run_tree_sha256"],
            candidate_run_tree_sha,
        )
        self.assertEqual(
            manifest["bindings"]["independent_build_run_tree_sha256"],
            independent_run_tree_sha,
        )
        self.assertEqual(
            manifest["bindings"]["formal_audit_manifest_sha256"],
            hashlib.sha256(audit_manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            manifest["exact_scope"]["certified_claim"],
            contract["acceptance_criterion"]["certificate_scope"],
        )
        self.assertEqual(manifest["exact_scope"]["permitted_axioms"], [])
        self.assertEqual(
            manifest["exact_scope"]["permitted_axiom_rationales"], {}
        )
        for nonclaim in contract["acceptance_criterion"]["explicit_nonclaims"]:
            self.assertIn(nonclaim, manifest["exact_scope"]["explicit_nonclaims"])
        self.assertFalse(manifest["research_integration"]["automatic_obligation_closure"])
        self.assertFalse(
            manifest["research_integration"]["automatic_theorem_status_promotion"]
        )
        self.assertFalse(manifest["research_integration"]["automatic_ledger_promotion"])

    def test_source_mutation_after_recorded_digest_is_rejected(self) -> None:
        self.enable()
        self.require_verification_backend()
        toolchain = self.require_installed_toolchain()
        case = self.create_case("mutation", source_fixture="valid", toolchain=toolchain)
        self.freeze_case("mutation")
        verify = self.run_script("verify_lean_case.py", "eval-problem", "mutation", "--json")
        self.assertEqual(verify.returncode, 0, self.command_diagnostic(verify))
        source = case / "project/Main.lean"
        source.write_text(source.read_text(encoding="utf-8") + "\n-- post-build mutation\n", encoding="utf-8")
        validation = self.run_script("validate_lean_case.py", "eval-problem", "mutation", "--json")
        self.assertEqual(validation.returncode, 5, validation.stdout + validation.stderr)
        self.assert_failed(validation, "digest", "hash", "mutation", "changed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
