#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any, Dict, Optional


MODULE = Path(__file__).resolve().parents[1]
BASE = MODULE.parents[1] / "base"
KERNEL_SOURCE = (
    BASE
    if (BASE / "scripts/validate_proof_search.py").is_file()
    else MODULE
)
MECHANISM_FAMILIES = (
    "ALGEBRAIC",
    "ANALYTIC",
    "COMBINATORIAL",
    "COMPUTATIONAL_EXPERIMENTAL",
    "COUNTEREXAMPLE_SEARCH",
    "DYNAMICAL",
)


class DeepResearchGoalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="deep-research-goal-")
        self.root = Path(self.temp.name)
        for name in ("scripts", "schemas", "templates", "research", "workflows"):
            shutil.copytree(MODULE / name, self.root / name)
        (self.root / "intake").mkdir()
        (self.root / "sources").mkdir()
        (self.root / "evidence").mkdir()
        (self.root / "problems/active/problem-t").mkdir(parents=True)
        (self.root / "sources/reference.txt").write_text(
            "A source-bound statement.\n", encoding="utf-8"
        )
        (self.root / "evidence/check.txt").write_text(
            "Independent checking artifact.\n", encoding="utf-8"
        )
        target_contract = {
            "schema_version": 1,
            "kind": "EXACT_MATHEMATICAL_TARGET",
            "problem_id": "problem-t",
            "target_id": "TARGET-T",
            "statement": "Prove or refute the exact frozen target T.",
            "acceptance_criteria": ["Discharge the exact frozen obligation."],
            "anti_targets": ["A weaker statement does not count."],
            "traps": ["Do not assume the desired conclusion."],
        }
        (self.root / "problems/active/problem-t/target_contract.json").write_text(
            json.dumps(
                target_contract,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts/deep_research_goal.py"),
                "--root",
                str(self.root),
                *args,
            ],
            text=True,
            capture_output=True,
        )

    def write(self, relative: str, value: Dict[str, Any]) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def load_helper_module(self) -> Any:
        path = self.root / "scripts/deep_research_goal.py"
        spec = importlib.util.spec_from_file_location(
            f"deep_research_goal_test_{id(self)}", path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def install_real_kernel_fixture(
        self, plan: Dict[str, Any], outcome_class: str
    ) -> str:
        """Install and validate a real kernel I3 fixture bound to this goal."""

        shutil.copy2(
            KERNEL_SOURCE / "scripts/validate_proof_search.py",
            self.root / "scripts/validate_proof_search.py",
        )
        shutil.copytree(
            KERNEL_SOURCE / "workflows",
            self.root / "workflows",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            KERNEL_SOURCE / "templates",
            self.root / "templates",
            dirs_exist_ok=True,
        )
        shutil.copytree(
            KERNEL_SOURCE / "problems/templates",
            self.root / "problems/templates",
        )
        fixture_relative = Path(
            "evals/regression/proof_search_valid_states"
        )
        fixture_root = self.root / fixture_relative
        shutil.copytree(
            KERNEL_SOURCE / fixture_relative,
            fixture_root,
        )
        shutil.copytree(
            KERNEL_SOURCE / "evals/regression/proof_search_invalid_states",
            self.root / "evals/regression/proof_search_invalid_states",
        )
        shutil.copytree(
            KERNEL_SOURCE / "evals/adversarial",
            self.root / "evals/adversarial",
        )
        live_root = (
            self.root
            / "problems/active"
            / plan["target"]["problem_id"]
        )
        shutil.copytree(
            fixture_root / "artifacts",
            live_root / "artifacts",
        )
        shutil.copytree(
            fixture_root / "verifier_reports",
            live_root / "verifier_reports",
        )
        target_path = plan["target_binding"]["path"]
        target_digest = plan["target_binding"]["sha256"]
        replacements = {
            "eval-valid-verified-proof": plan["target"]["problem_id"],
            "EVAL-TARGET-REFLEXIVITY-v1": plan["target"]["target_id"],
            "evals/regression/proof_search_valid_states/artifacts/target.md": (
                target_path
            ),
            "3600f4194aa8ff38f7bb504c4e443a12765771140752c1f9a07aaf9d13479fa9": (
                target_digest
            ),
            "evals/regression/proof_search_valid_states/artifacts/": (
                f"problems/active/{plan['target']['problem_id']}/artifacts/"
            ),
            "evals/regression/proof_search_valid_states/verifier_reports/": (
                f"problems/active/{plan['target']['problem_id']}/"
                "verifier_reports/"
            ),
        }
        for path in live_root.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            replaced = text
            for old, new in replacements.items():
                replaced = replaced.replace(old, new)
            if replaced != text:
                path.write_text(replaced, encoding="utf-8")

        def replace_strings(value: Any) -> Any:
            if isinstance(value, list):
                return [replace_strings(item) for item in value]
            if isinstance(value, dict):
                return {
                    key: replace_strings(item)
                    for key, item in value.items()
                }
            if isinstance(value, str):
                for old, new in replacements.items():
                    value = value.replace(old, new)
            return value

        def refresh_hashes(value: Any) -> None:
            if isinstance(value, list):
                for item in value:
                    refresh_hashes(item)
                return
            if not isinstance(value, dict):
                return
            for item in value.values():
                refresh_hashes(item)
            for key in list(value):
                if key == "sha256":
                    path_value = value.get("path")
                elif key.endswith("_sha256"):
                    path_value = value.get(key[: -len("_sha256")])
                else:
                    continue
                if not isinstance(path_value, str):
                    continue
                artifact = self.root / path_value
                if artifact.is_file():
                    value[key] = hashlib.sha256(
                        artifact.read_bytes()
                    ).hexdigest()

        json_paths = sorted(live_root.rglob("*.json"))
        for _ in range(12):
            changed = False
            for path in json_paths:
                value = json.loads(path.read_text(encoding="utf-8"))
                refresh_hashes(value)
                payload = (
                    json.dumps(
                        value,
                        indent=2,
                        sort_keys=True,
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                if path.read_text(encoding="utf-8") != payload:
                    path.write_text(payload, encoding="utf-8")
                    changed = True
            if not changed:
                break
        else:
            self.fail("kernel fixture digest graph did not converge")

        state = replace_strings(json.loads(
            (fixture_root / "verified_proof.yaml").read_text(encoding="utf-8")
        ))
        if outcome_class == "VERIFIED_REFUTATION":
            state["global_status"] = "VERIFIED_COUNTEREXAMPLE"
            state["routes"][0]["status"] = "CLOSED_COUNTEREXAMPLE"
            state["routes"][0]["transitions"][-1][
                "to_status"
            ] = "CLOSED_COUNTEREXAMPLE"
            closure_path = (
                live_root / "artifacts/closure_manifest.json"
            )
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            closure["global_status"] = "VERIFIED_COUNTEREXAMPLE"
            closure_path.write_text(
                json.dumps(
                    closure,
                    indent=2,
                    sort_keys=True,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        refresh_hashes(state)
        state_relative = (
            f"problems/active/{plan['target']['problem_id']}/"
            "proof_search_state.yaml"
        )
        self.write(state_relative, state)
        checked = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts/validate_proof_search.py"),
                str(self.root / state_relative),
            ],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(
            checked.returncode, 0, checked.stdout + checked.stderr
        )
        return state_relative

    def goal(
        self,
        mode: str,
        goal_id: str,
        *,
        marathon: Optional[Dict[str, Any]] = None,
        approved_total_seconds: Optional[int] = None,
        created_at: str = "2026-01-01T00:00:00Z",
    ) -> Dict[str, Any]:
        route_count = {"SCOUT": 1, "TRIAL": 3, "DEEP": 5, "MARATHON": 5}[mode]
        return {
            "schema_version": 1,
            "goal_id": goal_id,
            "mode": mode,
            "created_at": created_at,
            "target": {
                "kind": (
                    "SELECTION_QUESTION"
                    if mode == "SCOUT"
                    else "EXACT_MATHEMATICAL_TARGET"
                ),
                "problem_id": None if mode == "SCOUT" else "problem-t",
                "target_id": None if mode == "SCOUT" else "TARGET-T",
                "artifact_path": (
                    None
                    if mode == "SCOUT"
                    else "problems/active/problem-t/target_contract.json"
                ),
                "statement": (
                    "Which source-bound candidates merit a trial?"
                    if mode == "SCOUT"
                    else "Prove or refute the exact frozen target T."
                ),
                "acceptance_criteria": ["Discharge the exact frozen obligation."],
                "anti_targets": ["A weaker statement does not count."],
                "traps": ["Do not assume the desired conclusion."],
            },
            "source_policy": {
                "human_leads_allowed": True,
                "public_web_search_allowed": True,
                "allowed_source_paths": ["sources/reference.txt"],
                "citation_required": True,
            },
            "search_policy": {
                "initial_routes": [
                    {
                        "route_id": f"route-{index + 1}",
                        "mechanism_family": MECHANISM_FAMILIES[index],
                        "mechanism": f"mechanism family {index + 1}",
                    }
                    for index in range(route_count)
                ],
                "stopping_conditions": ["Stop at the mode wall-time cap."],
                "counterexample_search_required": True,
                "keep_incompatible_routes_alive": True,
            },
            "authorization": {
                "kind": (
                    "EXPLICIT_MARATHON"
                    if mode == "MARATHON"
                    else "CAMPAIGN_APPROVAL"
                ),
                "approved_at": created_at,
                "approved_by": ["researcher"],
                "approved_total_seconds": approved_total_seconds,
            },
            "marathon": marathon,
        }

    def prepare(self, request: Dict[str, Any], name: str = "goal.json") -> Dict[str, Any]:
        self.write(f"intake/{name}", request)
        result = self.cli("prepare", "--input", f"intake/{name}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(
            (
                self.root
                / f"research/deep_goals/{request['goal_id']}/approved_goal.json"
            ).read_text(encoding="utf-8")
        )

    def outcome(
        self,
        plan: Dict[str, Any],
        outcome_id: str = "outcome-a",
        *,
        outcome_class: str = "EXACT_LEMMA",
        candidate_appeared: Optional[bool] = None,
        usage_source: str = "OUTER_RUNNER_REPORTED",
    ) -> Dict[str, Any]:
        strict = outcome_class != "NO_STRICT_REDUCTION"
        if candidate_appeared is None:
            candidate_appeared = strict
        elapsed = 1000
        verification_seconds = 300 if candidate_appeared else 150
        discharged: list[str] = []
        falsified: list[str] = []
        narrowed: list[str] = []
        remaining_gap: Optional[str] = "Subcase C remains open."
        if outcome_class == "VERIFIED_PROOF":
            discharged = ["The exact frozen target."]
            remaining_gap = None
        elif outcome_class == "VERIFIED_REFUTATION":
            falsified = ["The exact frozen target."]
            remaining_gap = None
        elif outcome_class == "EXACT_LEMMA":
            discharged = ["Exact lemma L under its frozen hypotheses."]
        elif outcome_class == "CHECKED_COUNTEREXAMPLE":
            falsified = ["Proposed universal subclaim U."]
        elif outcome_class == "DECISIVE_BARRIER":
            narrowed = ["Route family R cannot cross exact obstruction B."]
        return {
            "schema_version": 1,
            "goal_id": plan["goal_id"],
            "plan_sha256": plan["plan_sha256"],
            "outcome_id": outcome_id,
            "recorded_at": plan["created_at"],
            "outcome_class": outcome_class,
            "strict_uncertainty_reduction": strict,
            "semantic_delta": {
                "discharged": discharged,
                "falsified": falsified,
                "narrowed": narrowed,
                "left_open": [] if strict else [],
            },
            "verification": {
                "evidence_paths": ["evidence/check.txt"] if strict else [],
                "generator_ids": ["generator-run"] if strict else [],
                "material_reviser_ids": ["repair-run"] if strict else [],
                "verifier_ids": ["independent-verifier"] if strict else [],
                "decisive_verifier_independent": strict,
                "independence_level": "I2" if strict else None,
                "kernel_state_path": None,
                "remaining_highest_gap": remaining_gap,
            },
            "compute": {
                "elapsed_wall_seconds": elapsed,
                "verification_wall_seconds": verification_seconds,
                "model_attempts": 2,
                "route_attempts": 3,
                "route_ids_attempted": ["route-1"] if strict else [],
                "verifier_attempts": 1,
                "candidate_appeared": candidate_appeared,
                "usage_source": usage_source,
                "input_tokens": 1200 if usage_source != "UNAVAILABLE" else None,
                "output_tokens": 400 if usage_source != "UNAVAILABLE" else None,
            },
        }

    def record(
        self, plan: Dict[str, Any], request: Dict[str, Any], name: str = "outcome.json"
    ) -> Dict[str, Any]:
        self.write(f"intake/{name}", request)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            f"intake/{name}",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(
            (
                self.root
                / f"research/deep_goals/{plan['goal_id']}/outcomes/{request['outcome_id']}.json"
            ).read_text(encoding="utf-8")
        )

    def marathon_parent(self) -> tuple[Dict[str, Any], str, str]:
        parent = self.prepare(self.goal("DEEP", "deep-parent"), "deep-parent.json")
        outcome_input = self.outcome(parent, outcome_id="deep-check")
        self.record(parent, outcome_input, "deep-check.json")
        relative = "research/deep_goals/deep-parent/outcomes/deep-check.json"
        digest = hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
        return parent, relative, digest

    def test_exact_presets_and_reserve_bands(self) -> None:
        expected = {
            "SCOUT": (1800, 12, 1, "QUALIFICATION"),
            "TRIAL": (7200, 3, 3, "FULL"),
            "DEEP": (21600, 1, 5, "FULL"),
        }
        for mode, values in expected.items():
            with self.subTest(mode=mode):
                plan = self.prepare(
                    self.goal(mode, f"{mode.lower()}-goal"),
                    f"{mode.lower()}.json",
                )
                budget = plan["budget"]
                self.assertEqual(
                    (
                        budget["stage_wall_time_cap_seconds"],
                        budget["target_cap"],
                        budget["minimum_initial_routes"],
                        budget["orchestration"],
                    ),
                    values,
                )
                self.assertEqual(
                    budget["verification_reserve"]["pre_candidate_percent_range"],
                    [15, 20],
                )
                self.assertEqual(
                    budget["verification_reserve"]["post_candidate_percent_range"],
                    [30, 40],
                )

    def test_prepare_is_canonical_read_only_and_idempotent(self) -> None:
        request = self.goal("DEEP", "canonical-goal")
        plan = self.prepare(request)
        path = self.root / "research/deep_goals/canonical-goal/approved_goal.json"
        self.assertEqual(path.read_bytes(), (
            json.dumps(plan, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8"))
        self.assertEqual(path.stat().st_mode & 0o222, 0)
        repeated = self.cli("prepare", "--input", "intake/goal.json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "EXISTS_IDENTICAL")

    def test_transition_lock_blocks_competition_and_releases_after_kill(self) -> None:
        self.write("intake/locked.json", self.goal("SCOUT", "locked-goal"))
        lock = self.root / "research/deep_goals/.operation.lock"
        holder = subprocess.Popen(
            [
                sys.executable,
                "-c",
                (
                    "import sys,time;"
                    "from pathlib import Path;"
                    f"sys.path.insert(0,{str(self.root / 'scripts')!r});"
                    "from deep_research_goal import OperationLock;"
                    "lock=OperationLock(Path(sys.argv[1]));"
                    "lock.__enter__();"
                    "print('LOCKED',flush=True);"
                    "time.sleep(60)"
                ),
                str(lock),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertIsNotNone(holder.stdout)
            self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
            result = self.cli("prepare", "--input", "intake/locked.json")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                "another deep-goal state transition is active", result.stderr
            )
            self.assertFalse(
                (self.root / "research/deep_goals/locked-goal").exists()
            )
        finally:
            holder.send_signal(signal.SIGKILL)
            holder.wait(timeout=5)
            if holder.stdout is not None:
                holder.stdout.close()
            if holder.stderr is not None:
                holder.stderr.close()
        self.assertTrue(lock.is_file())
        recovered = self.cli("prepare", "--input", "intake/locked.json")
        self.assertEqual(
            recovered.returncode, 0, recovered.stdout + recovered.stderr
        )
        validated = self.cli("validate")
        self.assertEqual(
            validated.returncode, 0, validated.stdout + validated.stderr
        )

    def test_prepare_recovers_abandoned_atomic_staging(self) -> None:
        helper = self.load_helper_module()
        request = self.goal("DEEP", "crash-recovery")
        self.write("intake/crash-recovery.json", request)
        with mock.patch.object(
            helper.os, "rename", side_effect=SystemExit("simulated kill")
        ):
            with self.assertRaisesRegex(SystemExit, "simulated kill"):
                helper.prepare(self.root, "intake/crash-recovery.json")
        abandoned = list(
            (self.root / "research/deep_goals").glob(".prepare-*")
        )
        self.assertEqual(len(abandoned), 1)
        self.assertFalse(
            (self.root / "research/deep_goals/crash-recovery").exists()
        )
        recovered = self.cli(
            "prepare", "--input", "intake/crash-recovery.json"
        )
        self.assertEqual(
            recovered.returncode, 0, recovered.stdout + recovered.stderr
        )
        self.assertFalse(
            list((self.root / "research/deep_goals").glob(".prepare-*"))
        )

    def test_locked_recheck_rejects_source_and_evidence_drift(self) -> None:
        helper = self.load_helper_module()
        request = self.goal("SCOUT", "source-race")
        self.write("intake/source-race.json", request)
        original_enter = helper.OperationLock.__enter__

        def mutate_source(lock: Any) -> Any:
            entered = original_enter(lock)
            (self.root / "sources/reference.txt").write_text(
                "Mutated between preflight and lock.\n", encoding="utf-8"
            )
            return entered

        with mock.patch.object(
            helper.OperationLock, "__enter__", mutate_source
        ):
            with self.assertRaisesRegex(
                helper.DeepGoalError, "dependencies drifted"
            ):
                helper.prepare(self.root, "intake/source-race.json")
        self.assertFalse((self.root / "research/deep_goals/source-race").exists())

        (self.root / "sources/reference.txt").write_text(
            "A source-bound statement.\n", encoding="utf-8"
        )
        plan = self.prepare(self.goal("DEEP", "evidence-race"), "evidence-race.json")
        outcome = self.outcome(plan)
        self.write("intake/evidence-race-outcome.json", outcome)

        def mutate_evidence(lock: Any) -> Any:
            entered = original_enter(lock)
            (self.root / "evidence/check.txt").write_text(
                "Mutated between preflight and lock.\n", encoding="utf-8"
            )
            return entered

        with mock.patch.object(
            helper.OperationLock, "__enter__", mutate_evidence
        ):
            with self.assertRaisesRegex(
                helper.DeepGoalError, "evidence or dependencies drifted"
            ):
                helper.record_outcome(
                    self.root,
                    plan["goal_id"],
                    "intake/evidence-race-outcome.json",
                )
        self.assertEqual(
            list(
                (
                    self.root
                    / "research/deep_goals/evidence-race/outcomes"
                ).glob("*.json")
            ),
            [],
        )

    def test_prepare_refuses_goal_id_reuse_with_drift(self) -> None:
        request = self.goal("DEEP", "fixed-goal")
        self.prepare(request)
        request["search_policy"]["stopping_conditions"] = [
            "A different immutable stopping condition."
        ]
        self.write("intake/goal.json", request)
        result = self.cli("prepare", "--input", "intake/goal.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("different immutable plan", result.stderr)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        (self.root / "intake/duplicate.json").write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        result = self.cli("prepare", "--input", "intake/duplicate.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate JSON key", result.stderr)

    def test_input_escape_and_symlink_are_rejected(self) -> None:
        escaped = self.cli("prepare", "--input", "../outside.json")
        self.assertNotEqual(escaped.returncode, 0)
        target = self.write("intake/real.json", self.goal("SCOUT", "linked-goal"))
        link = self.root / "intake/link.json"
        link.symlink_to(target)
        linked = self.cli("prepare", "--input", "intake/link.json")
        self.assertNotEqual(linked.returncode, 0)
        self.assertIn("symlink", linked.stderr)

    def test_scout_requires_hybrid_source_bound_policy(self) -> None:
        request = self.goal("SCOUT", "bad-scout")
        request["source_policy"]["human_leads_allowed"] = False
        request["source_policy"]["public_web_search_allowed"] = False
        request["source_policy"]["allowed_source_paths"] = []
        self.write("intake/bad.json", request)
        result = self.cli("prepare", "--input", "intake/bad.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hybrid sourcing", result.stderr)

    def test_route_minimum_and_mechanism_duplication_are_rejected(self) -> None:
        too_few = self.goal("DEEP", "few-routes")
        too_few["search_policy"]["initial_routes"] = too_few["search_policy"][
            "initial_routes"
        ][:4]
        self.write("intake/few.json", too_few)
        self.assertNotEqual(
            self.cli("prepare", "--input", "intake/few.json").returncode, 0
        )
        duplicate = self.goal("TRIAL", "duplicate-routes")
        duplicate["search_policy"]["initial_routes"][1]["mechanism_family"] = (
            duplicate["search_policy"]["initial_routes"][0]["mechanism_family"]
        )
        duplicate["search_policy"]["initial_routes"][1]["mechanism"] = (
            duplicate["search_policy"]["initial_routes"][0]["mechanism"].upper()
        )
        self.write("intake/duplicate-routes.json", duplicate)
        result = self.cli("prepare", "--input", "intake/duplicate-routes.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("structural mechanism families", result.stderr)

    def test_mode_cannot_drift_target_kind_or_authorization(self) -> None:
        request = self.goal("DEEP", "wrong-kind")
        request["target"]["kind"] = "SELECTION_QUESTION"
        self.write("intake/wrong-kind.json", request)
        self.assertNotEqual(
            self.cli("prepare", "--input", "intake/wrong-kind.json").returncode, 0
        )
        request = self.goal("DEEP", "wrong-auth")
        request["authorization"]["kind"] = "EXPLICIT_MARATHON"
        request["authorization"]["approved_total_seconds"] = 43200
        self.write("intake/wrong-auth.json", request)
        self.assertNotEqual(
            self.cli("prepare", "--input", "intake/wrong-auth.json").returncode, 0
        )

    def test_non_scout_target_artifact_is_canonical_full_contract(self) -> None:
        request = self.goal("DEEP", "target-contract-guard")
        request["target"]["statement"] = "Prove an unrelated famous conjecture."
        self.write("intake/mismatched-target.json", request)
        result = self.cli("prepare", "--input", "intake/mismatched-target.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("canonical serialization", result.stderr)

    def test_factory_generated_unicode_problem_id_is_supported(self) -> None:
        problem_id = "20260729-задача-пилот-a1b2c3d4e5"
        target_path = (
            f"problems/active/{problem_id}/target_contract.json"
        )
        request = self.goal("DEEP", "unicode-problem-id")
        request["target"]["problem_id"] = problem_id
        request["target"]["target_id"] = "ЦЕЛЬ-1"
        request["target"]["artifact_path"] = target_path
        self.write(
            target_path,
            {
                "schema_version": 1,
                "kind": request["target"]["kind"],
                "problem_id": problem_id,
                "target_id": request["target"]["target_id"],
                "statement": request["target"]["statement"],
                "acceptance_criteria": request["target"][
                    "acceptance_criteria"
                ],
                "anti_targets": request["target"]["anti_targets"],
                "traps": request["target"]["traps"],
            },
        )
        plan = self.prepare(request, "unicode-problem.json")
        self.assertEqual(plan["target"]["problem_id"], problem_id)

    def test_marathon_requires_exact_duration_and_parent_binding(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        marathon = {
            "campaign_id": "campaign-a",
            "stage_index": 1,
            "parent_goal_id": "deep-parent",
            "parent_plan_sha256": parent["plan_sha256"],
            "parent_record_path": record_path,
            "parent_record_sha256": record_digest,
        }
        plan = self.prepare(
            self.goal(
                "MARATHON",
                "marathon-one",
                marathon=marathon,
                approved_total_seconds=43200,
                created_at="2026-01-03T00:00:00Z",
            ),
            "marathon-one.json",
        )
        self.assertEqual(plan["budget"]["stage_wall_time_cap_seconds"], 21600)
        self.assertEqual(plan["budget"]["approved_cumulative_total_seconds"], 43200)
        bad = self.goal(
            "MARATHON",
            "marathon-bad-total",
            marathon=marathon,
            approved_total_seconds=36000,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/bad-total.json", bad)
        self.assertNotEqual(
            self.cli("prepare", "--input", "intake/bad-total.json").returncode, 0
        )
        bad = self.goal(
            "MARATHON",
            "marathon-bad-hash",
            marathon={**marathon, "parent_record_sha256": "0" * 64},
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/bad-hash.json", bad)
        self.assertNotEqual(
            self.cli("prepare", "--input", "intake/bad-hash.json").returncode, 0
        )

    def test_marathon_rejects_target_drift_and_arbitrary_checkpoint_parent(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        binding = {
            "campaign_id": "campaign-target-guard",
            "stage_index": 1,
            "parent_goal_id": parent["goal_id"],
            "parent_plan_sha256": parent["plan_sha256"],
            "parent_record_path": record_path,
            "parent_record_sha256": record_digest,
        }
        drifted = self.goal(
            "MARATHON",
            "marathon-drifted-target",
            marathon=binding,
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        drifted["target"]["acceptance_criteria"] = ["A substituted criterion."]
        drifted["target"]["artifact_path"] = (
            "problems/active/problem-t/drifted-target.json"
        )
        self.write(
            "problems/active/problem-t/drifted-target.json",
            {
                "schema_version": 1,
                "kind": drifted["target"]["kind"],
                "problem_id": drifted["target"]["problem_id"],
                "target_id": drifted["target"]["target_id"],
                "statement": drifted["target"]["statement"],
                "acceptance_criteria": drifted["target"]["acceptance_criteria"],
                "anti_targets": drifted["target"]["anti_targets"],
                "traps": drifted["target"]["traps"],
            },
        )
        self.write("intake/drifted-marathon.json", drifted)
        result = self.cli("prepare", "--input", "intake/drifted-marathon.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must exactly match", result.stderr)

        checkpoint = self.write(
            "research/checkpoints/arbitrary.txt",
            {"not": "a parent outcome"},
        )
        checkpoint_binding = {
            **binding,
            "campaign_id": "campaign-checkpoint-guard",
            "parent_record_path": "research/checkpoints/arbitrary.txt",
            "parent_record_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        }
        request = self.goal(
            "MARATHON",
            "marathon-arbitrary-checkpoint",
            marathon=checkpoint_binding,
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/checkpoint-marathon.json", request)
        result = self.cli("prepare", "--input", "intake/checkpoint-marathon.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immutable outcome", result.stderr)

    def test_marathon_requires_latest_chronological_parent_outcome(self) -> None:
        parent = self.prepare(self.goal("DEEP", "chronology-parent"))
        first = self.outcome(parent, outcome_id="first")
        first_record = self.record(parent, first, "chronology-first.json")
        second = self.outcome(parent, outcome_id="second")
        self.record(parent, second, "chronology-second.json")
        first_path = "research/deep_goals/chronology-parent/outcomes/first.json"
        request = self.goal(
            "MARATHON",
            "not-latest-child",
            marathon={
                "campaign_id": "latest-parent-campaign",
                "stage_index": 1,
                "parent_goal_id": parent["goal_id"],
                "parent_plan_sha256": parent["plan_sha256"],
                "parent_record_path": first_path,
                "parent_record_sha256": hashlib.sha256(
                    (self.root / first_path).read_bytes()
                ).hexdigest(),
            },
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/not-latest.json", request)
        result = self.cli("prepare", "--input", "intake/not-latest.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("latest immutable parent outcome", result.stderr)
        self.assertEqual(first_record["outcome_id"], "first")

        late_parent = self.prepare(
            self.goal(
                "DEEP",
                "late-parent",
                created_at="2026-01-05T00:00:00Z",
            ),
            "late-parent.json",
        )
        late_outcome = self.outcome(late_parent, outcome_id="late-outcome")
        self.record(late_parent, late_outcome, "late-outcome.json")
        late_path = "research/deep_goals/late-parent/outcomes/late-outcome.json"
        too_early = self.goal(
            "MARATHON",
            "too-early-child",
            marathon={
                "campaign_id": "chronology-campaign",
                "stage_index": 1,
                "parent_goal_id": late_parent["goal_id"],
                "parent_plan_sha256": late_parent["plan_sha256"],
                "parent_record_path": late_path,
                "parent_record_sha256": hashlib.sha256(
                    (self.root / late_path).read_bytes()
                ).hexdigest(),
            },
            approved_total_seconds=43200,
            created_at="2026-01-04T00:00:00Z",
        )
        self.write("intake/too-early.json", too_early)
        result = self.cli("prepare", "--input", "intake/too-early.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not precede", result.stderr)

    def test_marathon_inherits_candidate_reserve_and_seals_parent(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        child = self.prepare(
            self.goal(
                "MARATHON",
                "reserve-child",
                marathon={
                    "campaign_id": "reserve-campaign",
                    "stage_index": 1,
                    "parent_goal_id": parent["goal_id"],
                    "parent_plan_sha256": parent["plan_sha256"],
                    "parent_record_path": record_path,
                    "parent_record_sha256": record_digest,
                },
                approved_total_seconds=43200,
                created_at="2026-01-03T00:00:00Z",
            ),
            "reserve-child.json",
        )
        self.assertTrue(
            child["budget"]["verification_reserve"][
                "inherited_candidate_appeared"
            ]
        )
        reset = self.outcome(
            child,
            outcome_id="reset",
            outcome_class="NO_STRICT_REDUCTION",
            candidate_appeared=False,
        )
        self.write("intake/marathon-reset.json", reset)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            child["goal_id"],
            "--input",
            "intake/marathon-reset.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot reset across", result.stderr)

        extra_parent = self.outcome(parent, outcome_id="later-parent-outcome")
        self.write("intake/later-parent.json", extra_parent)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            parent["goal_id"],
            "--input",
            "intake/later-parent.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is sealed", result.stderr)

    def test_marathon_stages_chain_and_last_32h_stage_is_2h(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        prior_plan = parent
        prior_path = record_path
        prior_digest = record_digest
        for stage_index in range(1, 7):
            goal_id = f"marathon-stage-{stage_index}"
            request = self.goal(
                "MARATHON",
                goal_id,
                marathon={
                    "campaign_id": "campaign-32h",
                    "stage_index": stage_index,
                    "parent_goal_id": prior_plan["goal_id"],
                    "parent_plan_sha256": prior_plan["plan_sha256"],
                    "parent_record_path": prior_path,
                    "parent_record_sha256": prior_digest,
                },
                approved_total_seconds=115200,
                created_at=f"2026-01-{stage_index + 2:02d}T00:00:00Z",
            )
            plan = self.prepare(request, f"marathon-stage-{stage_index}.json")
            outcome_input = self.outcome(plan, outcome_id=f"stage-{stage_index}-outcome")
            self.record(plan, outcome_input, f"stage-{stage_index}-outcome.json")
            prior_path = (
                f"research/deep_goals/{goal_id}/outcomes/"
                f"stage-{stage_index}-outcome.json"
            )
            prior_digest = hashlib.sha256((self.root / prior_path).read_bytes()).hexdigest()
            prior_plan = plan
        self.assertEqual(prior_plan["budget"]["stage_wall_time_cap_seconds"], 7200)
        self.assertEqual(
            prior_plan["budget"]["cumulative_seconds_before_stage"], 108000
        )

    def test_marathon_cannot_skip_a_stage_or_change_total(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        marathon = {
            "campaign_id": "campaign-skipped",
            "stage_index": 2,
            "parent_goal_id": parent["goal_id"],
            "parent_plan_sha256": parent["plan_sha256"],
            "parent_record_path": record_path,
            "parent_record_sha256": record_digest,
        }
        request = self.goal(
            "MARATHON",
            "skipped-stage",
            marathon=marathon,
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/skipped.json", request)
        result = self.cli("prepare", "--input", "intake/skipped.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("immediately preceding", result.stderr)

    def test_marathon_cannot_fork_an_already_used_campaign_stage(self) -> None:
        parent, record_path, record_digest = self.marathon_parent()
        binding = {
            "campaign_id": "nonresetting-campaign",
            "stage_index": 1,
            "parent_goal_id": parent["goal_id"],
            "parent_plan_sha256": parent["plan_sha256"],
            "parent_record_path": record_path,
            "parent_record_sha256": record_digest,
        }
        self.prepare(
            self.goal(
                "MARATHON",
                "first-stage-copy",
                marathon=binding,
                approved_total_seconds=43200,
                created_at="2026-01-03T00:00:00Z",
            ),
            "first-stage-copy.json",
        )
        duplicate = self.goal(
            "MARATHON",
            "second-stage-copy",
            marathon=binding,
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/second-stage-copy.json", duplicate)
        result = self.cli("prepare", "--input", "intake/second-stage-copy.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already consumed stage 1", result.stderr)

        renamed_campaign = self.goal(
            "MARATHON",
            "renamed-campaign-fork",
            marathon={**binding, "campaign_id": "renamed-campaign"},
            approved_total_seconds=43200,
            created_at="2026-01-03T00:00:00Z",
        )
        self.write("intake/renamed-campaign.json", renamed_campaign)
        result = self.cli("prepare", "--input", "intake/renamed-campaign.json")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only one MARATHON child", result.stderr)

    def test_strict_outcome_is_vector_without_score_or_status(self) -> None:
        plan = self.prepare(self.goal("DEEP", "vector-goal"))
        record = self.record(plan, self.outcome(plan))
        self.assertEqual(record["outcome_class"], "EXACT_LEMMA")
        self.assertEqual(
            record["usage_assessment"], "UNAUTHENTICATED_OUTER_RUNNER_REPORT"
        )
        self.assertNotIn("score", record)
        self.assertNotIn("theorem_status", record)
        path = self.root / "research/deep_goals/vector-goal/outcomes/outcome-a.json"
        self.assertEqual(path.stat().st_mode & 0o222, 0)

    def test_outcome_classes_have_class_specific_semantics(self) -> None:
        plan = self.prepare(self.goal("DEEP", "class-semantics"))
        fake_proof = self.outcome(plan, outcome_class="VERIFIED_PROOF")
        fake_proof["semantic_delta"]["discharged"] = []
        fake_proof["semantic_delta"]["narrowed"] = ["Only a reduction."]
        fake_proof["verification"]["remaining_highest_gap"] = "Target remains open."
        self.write("intake/fake-proof.json", fake_proof)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/fake-proof.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VERIFIED_PROOF must discharge", result.stderr)

        fake_counterexample = self.outcome(
            plan,
            outcome_id="fake-counterexample",
            outcome_class="CHECKED_COUNTEREXAMPLE",
        )
        fake_counterexample["semantic_delta"]["falsified"] = []
        fake_counterexample["semantic_delta"]["narrowed"] = ["Only narrowed."]
        self.write("intake/fake-counterexample.json", fake_counterexample)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/fake-counterexample.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must falsify", result.stderr)

    def test_verified_classes_require_kernel_i3_state(self) -> None:
        plan = self.prepare(self.goal("DEEP", "kernel-i3-required"))
        request = self.outcome(plan, outcome_class="VERIFIED_PROOF")
        request["verification"]["independence_level"] = "I3"
        self.write("intake/no-kernel-state.json", request)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/no-kernel-state.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("kernel_state_path", result.stderr)

    def test_verified_bridge_binds_kernel_target_and_exact_lineage(self) -> None:
        plan = self.prepare(self.goal("DEEP", "kernel-bridge"))
        target_path = self.root / plan["target_binding"]["path"]
        state_relative = (
            "problems/active/problem-t/proof_search_state.yaml"
        )
        self.write(
            state_relative,
            {
                "global_status": "VERIFIED_PROOF",
                "problem_id": "problem-t",
                "target_binding": {
                    "target_id": "TARGET-T",
                    "artifact": plan["target_binding"]["path"],
                    "artifact_sha256": hashlib.sha256(
                        target_path.read_bytes()
                    ).hexdigest(),
                },
                "candidate_lineage": {
                    "originating_run_ids": ["generator-run"],
                    "material_repair_run_ids": ["repair-run"],
                },
                "independent_verifier": {
                    "id": "independent-verifier",
                    "independence_level": "I3",
                    "independent_of_candidate": True,
                    "completed": True,
                    "verdict": "PASS",
                },
            },
        )
        (self.root / "scripts/validate_proof_search.py").write_text(
            "raise SystemExit(0)\n", encoding="utf-8"
        )
        request = self.outcome(plan, outcome_class="VERIFIED_PROOF")
        request["verification"]["independence_level"] = "I3"
        request["verification"]["kernel_state_path"] = state_relative
        request["verification"]["evidence_paths"].append(state_relative)
        self.record(plan, request, "kernel-proof.json")

        mismatch = self.outcome(
            plan,
            outcome_id="lineage-mismatch",
            outcome_class="VERIFIED_PROOF",
        )
        mismatch["verification"]["independence_level"] = "I3"
        mismatch["verification"]["kernel_state_path"] = state_relative
        mismatch["verification"]["evidence_paths"].append(state_relative)
        mismatch["verification"]["generator_ids"] = ["fake-generator"]
        self.write("intake/lineage-mismatch.json", mismatch)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/lineage-mismatch.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exactly match the kernel I3 state", result.stderr)

    def test_real_kernel_i3_fixture_records_verified_proof(self) -> None:
        plan = self.prepare(self.goal("DEEP", "real-kernel-proof"))
        state_relative = self.install_real_kernel_fixture(
            plan, "VERIFIED_PROOF"
        )
        request = self.outcome(plan, outcome_class="VERIFIED_PROOF")
        request["verification"].update(
            {
                "generator_ids": ["EVAL-GENERATOR-1"],
                "material_reviser_ids": [],
                "verifier_ids": ["EVAL-VERIFIER-1"],
                "independence_level": "I3",
                "kernel_state_path": state_relative,
            }
        )
        request["verification"]["evidence_paths"].append(state_relative)
        record = self.record(plan, request, "real-kernel-proof.json")
        self.assertEqual(record["outcome_class"], "VERIFIED_PROOF")

    def test_real_kernel_i3_fixture_records_verified_refutation(self) -> None:
        plan = self.prepare(self.goal("DEEP", "real-kernel-refutation"))
        state_relative = self.install_real_kernel_fixture(
            plan, "VERIFIED_REFUTATION"
        )
        request = self.outcome(
            plan, outcome_class="VERIFIED_REFUTATION"
        )
        request["verification"].update(
            {
                "generator_ids": ["EVAL-GENERATOR-1"],
                "material_reviser_ids": [],
                "verifier_ids": ["EVAL-VERIFIER-1"],
                "independence_level": "I3",
                "kernel_state_path": state_relative,
            }
        )
        request["verification"]["evidence_paths"].append(state_relative)
        record = self.record(
            plan, request, "real-kernel-refutation.json"
        )
        self.assertEqual(record["outcome_class"], "VERIFIED_REFUTATION")

    def test_strict_lineage_is_disjoint_and_attempts_are_nonzero(self) -> None:
        plan = self.prepare(self.goal("DEEP", "strict-lineage"))
        entangled = self.outcome(plan, outcome_id="entangled")
        entangled["verification"]["verifier_ids"] = ["generator-run"]
        self.write("intake/entangled.json", entangled)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/entangled.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be disjoint", result.stderr)

        zero_attempts = self.outcome(plan, outcome_id="zero-attempts")
        zero_attempts["compute"]["route_attempts"] = 0
        zero_attempts["compute"]["route_ids_attempted"] = []
        self.write("intake/zero-attempts.json", zero_attempts)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/zero-attempts.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires at least one", result.stderr)

    def test_strict_outcome_requires_delta_evidence_and_independence(self) -> None:
        plan = self.prepare(self.goal("DEEP", "strict-guard"))
        request = self.outcome(plan)
        request["semantic_delta"]["discharged"] = []
        request["semantic_delta"]["narrowed"] = []
        request["verification"]["evidence_paths"] = []
        request["verification"]["verifier_ids"] = []
        request["verification"]["decisive_verifier_independent"] = False
        self.write("intake/bad-outcome.json", request)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/bad-outcome.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strict-reduction class", result.stderr)

    def test_no_reduction_requires_entirely_empty_delta(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "no-reduction"))
        request = self.outcome(plan, outcome_class="NO_STRICT_REDUCTION")
        self.record(plan, request)
        bad = self.outcome(
            plan, outcome_id="bad-no-reduction", outcome_class="NO_STRICT_REDUCTION"
        )
        bad["semantic_delta"]["left_open"] = ["Still open."]
        self.write("intake/bad-no.json", bad)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/bad-no.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("entirely empty", result.stderr)

    def test_pre_and_post_candidate_reserves_are_enforced(self) -> None:
        plan = self.prepare(self.goal("DEEP", "reserve-goal"))
        pre = self.outcome(plan, outcome_id="bad-pre")
        pre["compute"]["verification_wall_seconds"] = 149
        self.write("intake/bad-pre.json", pre)
        self.assertNotEqual(
            self.cli(
                "record-outcome",
                "--goal-id",
                plan["goal_id"],
                "--input",
                "intake/bad-pre.json",
            ).returncode,
            0,
        )
        post = self.outcome(
            plan,
            outcome_id="exact-lemma",
            outcome_class="EXACT_LEMMA",
            candidate_appeared=True,
        )
        post["compute"]["verification_wall_seconds"] = 299
        self.write("intake/bad-post.json", post)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/bad-post.json",
        )
        self.assertNotEqual(result.returncode, 0)
        post["compute"]["verification_wall_seconds"] = 300
        self.record(plan, post, "good-post.json")

    def test_candidate_reserve_cannot_reset_after_candidate(self) -> None:
        plan = self.prepare(self.goal("DEEP", "reserve-monotone"))
        self.record(plan, self.outcome(plan, outcome_id="candidate"), "candidate.json")
        reset = self.outcome(
            plan,
            outcome_id="reset",
            outcome_class="NO_STRICT_REDUCTION",
            candidate_appeared=False,
        )
        self.write("intake/reset.json", reset)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/reset.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot reset", result.stderr)

    def test_append_key_cannot_reorder_equal_timestamp_history(self) -> None:
        plan = self.prepare(self.goal("DEEP", "append-key-order"))
        first = self.outcome(
            plan,
            outcome_id="z-last",
            outcome_class="NO_STRICT_REDUCTION",
            candidate_appeared=False,
        )
        self.record(plan, first, "z-last.json")
        reordered = self.outcome(plan, outcome_id="a-first")
        self.write("intake/a-first.json", reordered)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/a-first.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("strictly greater", result.stderr)

    def test_scout_cannot_claim_proof_closure(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "scout-proof-guard"))
        request = self.outcome(plan, outcome_class="VERIFIED_PROOF")
        self.write("intake/scout-proof.json", request)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/scout-proof.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("qualification-only", result.stderr)

    def test_elapsed_time_cannot_exceed_stage_cap(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "bounded-goal"))
        request = self.outcome(plan, outcome_class="NO_STRICT_REDUCTION")
        request["compute"]["elapsed_wall_seconds"] = 1801
        request["compute"]["verification_wall_seconds"] = 271
        self.write("intake/overrun.json", request)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/overrun.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outside the allowed range", result.stderr)

    def test_multiple_outcomes_share_instead_of_resetting_stage_budget(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "shared-budget"))
        first = self.outcome(
            plan, outcome_id="first", outcome_class="NO_STRICT_REDUCTION"
        )
        self.record(plan, first, "first.json")
        second = self.outcome(
            plan, outcome_id="second", outcome_class="NO_STRICT_REDUCTION"
        )
        self.write("intake/second.json", second)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/second.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("retry cannot reset elapsed time", result.stderr)

    def test_validate_rejects_manually_inserted_cumulative_overrun(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "manual-overrun"))
        first = self.outcome(
            plan, outcome_id="first", outcome_class="NO_STRICT_REDUCTION"
        )
        self.record(plan, first, "first.json")

        helper = self.load_helper_module()
        second = self.outcome(
            plan, outcome_id="second", outcome_class="NO_STRICT_REDUCTION"
        )
        normalized = helper.normalize_outcome_request(second, self.root, plan)
        first_record = json.loads(
            (
                self.root
                / "research/deep_goals/manual-overrun/outcomes/first.json"
            ).read_text(encoding="utf-8")
        )
        record = helper.build_outcome_record(
            self.root,
            plan,
            normalized,
            sequence_index=2,
            previous_outcome_sha256=first_record["outcome_sha256"],
        )
        path = (
            self.root
            / "research/deep_goals/manual-overrun/outcomes/second.json"
        )
        path.write_bytes(helper.record_bytes(record))
        path.chmod(0o444)

        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cumulative outcome time exceeds", result.stderr)

    def test_outcome_hash_chain_detects_interior_deletion(self) -> None:
        plan = self.prepare(self.goal("DEEP", "outcome-chain"))
        for outcome_id in ("first", "second", "third"):
            request = self.outcome(
                plan,
                outcome_id=outcome_id,
                outcome_class="NO_STRICT_REDUCTION",
            )
            self.record(plan, request, f"{outcome_id}.json")
        middle = (
            self.root
            / "research/deep_goals/outcome-chain/outcomes/second.json"
        )
        middle.unlink()
        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("outcome hash chain", result.stderr)

    def test_usage_provenance_missing_is_unscored_not_zero(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "usage-goal"))
        request = self.outcome(
            plan,
            outcome_class="NO_STRICT_REDUCTION",
            usage_source="UNAVAILABLE",
        )
        record = self.record(plan, request)
        self.assertEqual(record["usage_assessment"], "UNSCORED_MISSING_USAGE")
        status = self.cli("status", "--goal-id", plan["goal_id"])
        self.assertEqual(status.returncode, 0, status.stderr)
        summary = json.loads(status.stdout)
        self.assertIsNone(summary["latest_outcome"]["token_usage"])
        self.assertFalse(summary["theorem_status_changed"])

    def test_runner_usage_requires_counts_and_user_usage_is_untrusted(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "usage-trust"))
        bad = self.outcome(
            plan,
            outcome_class="NO_STRICT_REDUCTION",
            usage_source="OUTER_RUNNER_REPORTED",
        )
        bad["compute"]["input_tokens"] = None
        self.write("intake/missing-runner.json", bad)
        self.assertNotEqual(
            self.cli(
                "record-outcome",
                "--goal-id",
                plan["goal_id"],
                "--input",
                "intake/missing-runner.json",
            ).returncode,
            0,
        )
        user = self.outcome(
            plan,
            outcome_id="user-usage",
            outcome_class="NO_STRICT_REDUCTION",
            usage_source="USER_RECORDED",
        )
        record = self.record(plan, user, "user-usage.json")
        self.assertEqual(record["usage_assessment"], "UNTRUSTED_SELF_REPORT")

    def test_outer_runner_counts_are_reported_not_trusted(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "runner-report"))
        request = self.outcome(
            plan,
            outcome_class="NO_STRICT_REDUCTION",
            usage_source="OUTER_RUNNER_REPORTED",
        )
        request["compute"]["input_tokens"] = 0
        request["compute"]["output_tokens"] = 0
        record = self.record(plan, request)
        self.assertEqual(
            record["usage_assessment"], "UNAUTHENTICATED_OUTER_RUNNER_REPORT"
        )
        self.assertNotIn("TRUSTED", record["usage_assessment"])

    def test_immutable_publication_is_atomic_on_mid_write_failure(self) -> None:
        helper = self.load_helper_module()
        target = self.root / "research/deep_goals/atomic-record.json"
        original_write = helper.os.write
        calls = 0

        def interrupted_write(descriptor: int, payload: bytes) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return original_write(descriptor, payload[: max(1, len(payload) // 3)])
            raise OSError("injected mid-write failure")

        with mock.patch.object(helper.os, "write", side_effect=interrupted_write):
            with self.assertRaises(OSError):
                helper.write_immutable(target, {"schema_version": 1, "value": "x" * 200})
        self.assertFalse(target.exists())
        self.assertEqual(
            list(target.parent.glob(f".{target.name}.publish-*")),
            [],
        )

    def test_evidence_escape_and_symlink_are_rejected(self) -> None:
        plan = self.prepare(self.goal("DEEP", "evidence-guard"))
        escaped = self.outcome(plan, outcome_id="escaped")
        escaped["verification"]["evidence_paths"] = ["../outside.txt"]
        self.write("intake/escaped.json", escaped)
        self.assertNotEqual(
            self.cli(
                "record-outcome",
                "--goal-id",
                plan["goal_id"],
                "--input",
                "intake/escaped.json",
            ).returncode,
            0,
        )
        (self.root / "evidence/link.txt").symlink_to(self.root / "evidence/check.txt")
        linked = self.outcome(plan, outcome_id="linked")
        linked["verification"]["evidence_paths"] = ["evidence/link.txt"]
        self.write("intake/linked.json", linked)
        result = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/linked.json",
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("symlink", result.stderr)

    def test_outcome_is_append_only_and_idempotent(self) -> None:
        plan = self.prepare(self.goal("DEEP", "append-only"))
        request = self.outcome(plan)
        self.record(plan, request)
        repeated = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/outcome.json",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "EXISTS_IDENTICAL")
        request["compute"]["model_attempts"] = 99
        self.write("intake/outcome.json", request)
        conflict = self.cli(
            "record-outcome",
            "--goal-id",
            plan["goal_id"],
            "--input",
            "intake/outcome.json",
        )
        self.assertNotEqual(conflict.returncode, 0)
        self.assertIn("different immutable record", conflict.stderr)

    def test_validate_detects_plan_and_outcome_tampering(self) -> None:
        plan = self.prepare(self.goal("DEEP", "tamper-goal"))
        self.record(plan, self.outcome(plan))
        outcome_path = (
            self.root / "research/deep_goals/tamper-goal/outcomes/outcome-a.json"
        )
        outcome_path.chmod(0o644)
        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("read-only", result.stderr)
        outcome_path.chmod(0o444)
        plan_path = self.root / "research/deep_goals/tamper-goal/approved_goal.json"
        plan_path.chmod(0o644)
        tampered = json.loads(plan_path.read_text(encoding="utf-8"))
        tampered["budget"]["target_cap"] = 99
        plan_path.write_text(
            json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        plan_path.chmod(0o444)
        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("drifted", result.stderr)

    def test_source_and_evidence_bytes_are_digest_bound(self) -> None:
        source_plan = self.prepare(self.goal("SCOUT", "source-binding"))
        (self.root / "sources/reference.txt").write_text(
            "Changed after the plan was frozen.\n",
            encoding="utf-8",
        )
        source_result = self.cli(
            "validate",
            "--goal-id",
            source_plan["goal_id"],
        )
        self.assertNotEqual(source_result.returncode, 0)
        self.assertIn("drifted", source_result.stderr)

        (self.root / "sources/reference.txt").write_text(
            "A source-bound statement.\n",
            encoding="utf-8",
        )
        evidence_plan = self.prepare(self.goal("DEEP", "evidence-binding"))
        self.record(evidence_plan, self.outcome(evidence_plan))
        (self.root / "evidence/check.txt").write_text(
            "Changed after the outcome was frozen.\n",
            encoding="utf-8",
        )
        evidence_result = self.cli(
            "validate",
            "--goal-id",
            evidence_plan["goal_id"],
        )
        self.assertNotEqual(evidence_result.returncode, 0)
        self.assertIn("drifted", evidence_result.stderr)

    def test_validate_rejects_state_symlinks_and_special_files(self) -> None:
        plan = self.prepare(self.goal("SCOUT", "state-hazards"))
        link = self.root / "research/deep_goals/state-hazards/outcomes/link.json"
        link.symlink_to(self.root / "evidence/check.txt")
        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        link.unlink()
        fifo = self.root / "research/deep_goals/state-hazards/outcomes/pipe"
        os.mkfifo(fifo)
        result = self.cli("validate", "--goal-id", plan["goal_id"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("special file", result.stderr)

    def test_full_validation_accepts_empty_and_populated_state(self) -> None:
        empty = self.cli("validate")
        self.assertEqual(empty.returncode, 0, empty.stderr)
        self.assertEqual(json.loads(empty.stdout)["goal_count"], 0)
        plan = self.prepare(self.goal("TRIAL", "valid-trial"))
        self.record(plan, self.outcome(plan))
        populated = self.cli("validate")
        self.assertEqual(populated.returncode, 0, populated.stdout + populated.stderr)
        self.assertEqual(json.loads(populated.stdout)["goal_count"], 1)

    def test_templates_and_schemas_are_closed_json(self) -> None:
        for path in sorted((self.root / "templates").glob("*.json")):
            with self.subTest(path=path.name):
                json.loads(path.read_text(encoding="utf-8"))
        for path in sorted((self.root / "schemas").glob("*.json")):
            with self.subTest(path=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

    def test_suite_contains_no_skipped_tests(self) -> None:
        methods = [
            name
            for name in dir(type(self))
            if name.startswith("test_") and callable(getattr(type(self), name))
        ]
        self.assertGreaterEqual(len(methods), 20)
        for name in methods:
            method = getattr(type(self), name)
            self.assertFalse(getattr(method, "__unittest_skip__", False), name)


if __name__ == "__main__":
    unittest.main()
