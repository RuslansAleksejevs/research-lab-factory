#!/usr/bin/env python3
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


MODULE = Path(__file__).resolve().parents[1]


class DiscoveryPortfolioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="discovery-portfolio-")
        self.root = Path(self.temp.name)
        for name in ("portfolio", "knowledge", "scripts", "templates", "workflows"):
            shutil.copytree(MODULE / name, self.root / name)
        (self.root / "problems/active").mkdir(parents=True)
        (self.root / "problems/backlog").mkdir()
        (self.root / "problems/closed").mkdir()
        (self.root / "LAB_PROFILE.json").write_text(json.dumps({"lab": {"id": "test-lab"}}), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(self.root / "scripts/discovery_portfolio.py"), "--root", str(self.root), *args], text=True, capture_output=True)

    def load_cli_module(self, root: Path, name: str):
        scripts = root / "scripts"
        previous = sys.modules.pop("discovery_portfolio_lib", None)
        sys.path.insert(0, str(scripts))
        try:
            spec = importlib.util.spec_from_file_location(
                name, scripts / "discovery_portfolio.py"
            )
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.remove(str(scripts))
            sys.modules.pop("discovery_portfolio_lib", None)
            if previous is not None:
                sys.modules["discovery_portfolio_lib"] = previous
        return module

    def write(self, relative: str, value: dict) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def v2_intake(
        self,
        *,
        candidate_id: str = "candidate-a",
        origin: str = "USER_SUPPLIED",
        artifact_paths: list[str] | None = None,
        cohort_id: str | None = "cohort-a",
    ) -> dict:
        return {
            "schema_version": 2,
            "candidate_id": candidate_id,
            "title": "Candidate A",
            "track": "probability",
            "lead": "A bounded unverified lead.",
            "why_now": "Cheap to falsify.",
            "created_by": ["researcher-a"],
            "created_at": "2026-01-01T00:00:00Z",
            "problem_id": None,
            "origin": origin,
            "origin_artifact_paths": artifact_paths or [],
            "cohort_id": cohort_id,
        }

    def decide(
        self,
        *,
        decision_id: str,
        to_status: str,
        candidate_id: str = "candidate-a",
        rationale: str = "Reviewed resource-allocation decision.",
    ) -> subprocess.CompletedProcess[str]:
        self.write(
            f"portfolio/inbox/{decision_id}.json",
            {
                "schema_version": 1,
                "decision_id": decision_id,
                "decision": "CONTINUE",
                "to_status": to_status,
                "decided_at": "2026-01-02T00:00:00Z",
                "decided_by": ["researcher-a"],
                "rationale": rationale,
                "supporting_artifact_paths": [],
                "park": None,
                "reopen": None,
                "spinout": None,
            },
        )
        return self.run_cli(
            "decide",
            "--candidate-id",
            candidate_id,
            "--input",
            f"portfolio/inbox/{decision_id}.json",
        )

    def qualify_and_link(
        self,
        *,
        candidate_id: str = "candidate-a",
        problem_id: str = "problem-a",
    ) -> None:
        suffix = candidate_id.removeprefix("candidate-")
        self.assertEqual(
            self.decide(
                decision_id=f"begin-qualification-{suffix}",
                to_status="QUALIFYING",
                candidate_id=candidate_id,
            ).returncode,
            0,
        )
        self.write(
            f"portfolio/inbox/qualification-{suffix}.json",
            {
                "schema_version": 1,
                "qualification_id": f"qualification-{suffix}",
                "assessed_at": "2026-01-02T00:00:00Z",
                "assessed_by": ["researcher-a"],
                "exact_statement": "An exact candidate statement.",
                "open_assessment": "UNASSESSED",
                "significance_rationale": "A checked answer would matter.",
                "tractability_rationale": "Cheap falsifiers are available.",
                "verification_plan": "Use an independent checker.",
                "cheap_falsifiers": ["Search the first finite cases."],
                "artifact_paths": [],
            },
        )
        result = self.run_cli(
            "record-qualification",
            "--candidate-id",
            candidate_id,
            "--input",
            f"portfolio/inbox/qualification-{suffix}.json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        result = self.decide(
            decision_id=f"begin-trial-status-{suffix}",
            to_status="TRIAL_ACTIVE",
            candidate_id=candidate_id,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        (self.root / "problems/active" / problem_id).mkdir()
        self.write(
            f"portfolio/inbox/dossier-{suffix}.json",
            {
                "schema_version": 1,
                "link_id": f"dossier-{suffix}",
                "problem_id": problem_id,
                "reason": "This dossier contains the serious trial.",
                "linked_by": ["researcher-a"],
            },
        )
        result = self.run_cli(
            "link-dossier",
            "--candidate-id",
            candidate_id,
            "--input",
            f"portfolio/inbox/dossier-{suffix}.json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def promote(
        self,
        *,
        promotion_id: str,
        to_tier: str,
        pool: int,
        selected: int,
        candidate_id: str = "candidate-a",
        deviation_rationale: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        self.write(
            f"portfolio/inbox/{promotion_id}.json",
            {
                "schema_version": 1,
                "promotion_id": promotion_id,
                "to_tier": to_tier,
                "decided_at": "2026-01-03T00:00:00Z",
                "decided_by": ["researcher-a"],
                "rationale": "Explicit allocation decision for this exact candidate.",
                "supporting_artifact_paths": [],
                "funnel_observation": {
                    "observed_pool_size": pool,
                    "observed_selected_size": selected,
                    "deviation_rationale": deviation_rationale,
                },
            },
        )
        return self.run_cli(
            "promote-engagement",
            "--candidate-id",
            candidate_id,
            "--input",
            f"portfolio/inbox/{promotion_id}.json",
        )

    def make_target_lab(self, name: str, lab_id: str = "target-lab") -> Path:
        target = self.root / name
        for directory in ("portfolio", "knowledge", "scripts", "templates", "workflows"):
            shutil.copytree(MODULE / directory, target / directory)
        (target / "problems/active").mkdir(parents=True)
        (target / "problems/backlog").mkdir()
        (target / "problems/closed").mkdir()
        (target / "LAB_PROFILE.json").write_text(
            json.dumps({"lab": {"id": lab_id}}), encoding="utf-8"
        )
        return target

    def run_target_cli(
        self, target: Path, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(target / "scripts/discovery_portfolio.py"),
                "--root",
                str(target),
                *args,
            ],
            text=True,
            capture_output=True,
        )

    def rehash_package(self, package: Path) -> None:
        payload = package / "payload"
        entries = []
        for path in sorted(item for item in payload.rglob("*") if item.is_file()):
            data = path.read_bytes()
            entries.append(
                {
                    "path": path.relative_to(payload).as_posix(),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "size": len(data),
                }
            )
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["files"] = entries
        manifest["payload_digest_sha256"] = hashlib.sha256(
            json.dumps(
                entries,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def prepare_trial_candidate(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        created = self.run_cli(
            "intake", "--input", "portfolio/inbox/intake-v2.json"
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.qualify_and_link()
        promoted = self.promote(
            promotion_id="trial-tier",
            to_tier="TRIAL",
            pool=1,
            selected=1,
        )
        self.assertEqual(promoted.returncode, 0, promoted.stdout + promoted.stderr)

    def round_input(self, round_id: str) -> dict:
        return {
            "schema_version": 1,
            "round_id": round_id,
            "started_at": "2026-01-03T00:00:00Z",
            "completed_at": "2026-01-03T01:00:00Z",
            "conducted_by": ["researcher-a"],
            "objective": "Run one discriminating trial.",
            "methods": "Independent routes and cheap falsifiers.",
            "observations": "The attempt produced bounded evidence.",
            "strongest_result": "No canonical status change.",
            "remaining_gap": "The exact main gap remains.",
            "semantic_progress": False,
            "proposed_decision": "CONTINUE",
            "artifact_paths": [],
        }

    def spinout_decide(
        self,
        *,
        candidate_id: str,
        decision_id: str,
        to_status: str,
        spinout: dict | None,
    ) -> subprocess.CompletedProcess[str]:
        self.write(
            f"portfolio/inbox/{decision_id}.json",
            {
                "schema_version": 1,
                "decision_id": decision_id,
                "decision": "SPIN_OUT",
                "to_status": to_status,
                "decided_at": "2026-01-04T00:00:00Z",
                "decided_by": ["researcher-a"],
                "rationale": "Reviewed spin-out allocation decision.",
                "supporting_artifact_paths": [],
                "park": None,
                "reopen": None,
                "spinout": spinout,
            },
        )
        return self.run_cli(
            "decide",
            "--candidate-id",
            candidate_id,
            "--input",
            f"portfolio/inbox/{decision_id}.json",
        )

    def prepare_spinout_seed(
        self,
        *,
        seed_id: str = "seed-a",
        target_lab_id: str = "target-lab",
    ) -> Path:
        self.prepare_trial_candidate()
        self.write("portfolio/inbox/spinout-round.json", self.round_input("spinout-round"))
        rounded = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/spinout-round.json",
        )
        self.assertEqual(rounded.returncode, 0, rounded.stdout + rounded.stderr)
        ready = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="spinout-ready",
            to_status="SPINOUT_READY",
            spinout=None,
        )
        self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
        self.write(
            "portfolio/inbox/spinout-request.json",
            {
                "schema_version": 1,
                "target_lab_id": target_lab_id,
                "directory_name": "Target Lab",
                "title": "Target Lab",
                "mission": "Continue the bounded program.",
                "areas": ["combinatorics"],
                "deliverables": ["theorem"],
                "unresolved_questions": ["gap"],
            },
        )
        prepared = self.run_cli(
            "prepare-spinout",
            "--candidate-id",
            "candidate-a",
            "--seed-id",
            seed_id,
            "--target-lab-id",
            target_lab_id,
            "--request",
            "portfolio/inbox/spinout-request.json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        return self.root / "portfolio/spinouts" / seed_id

    def test_fresh_overlay_and_intake_are_valid(self) -> None:
        validation = subprocess.run([sys.executable, str(self.root / "scripts/validate_discovery_portfolio.py"), "--root", str(self.root)], text=True, capture_output=True)
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        self.write("portfolio/inbox/intake.json", {"schema_version": 1, "candidate_id": "candidate-a", "title": "Candidate A", "track": "probability", "lead": "A bounded unverified lead.", "why_now": "Cheap to falsify.", "created_by": ["researcher-a"], "created_at": "2026-01-01T00:00:00Z", "problem_id": None})
        created = self.run_cli("intake", "--input", "portfolio/inbox/intake.json")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        summary = json.loads((self.root / "knowledge/control_room_summary.json").read_text())
        self.assertEqual(summary["candidate_counts"]["LEAD"], 1)
        payload = {k: v for k, v in summary.items() if k not in ("generated_at", "source_digest_sha256")}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(summary["source_digest_sha256"], digest)

    def test_path_escape_and_symlink_are_rejected(self) -> None:
        escaped = self.run_cli("intake", "--input", "../outside.json")
        self.assertNotEqual(escaped.returncode, 0)
        link = self.root / "portfolio/inbox/link.json"
        link.symlink_to(self.root / "LAB_PROFILE.json")
        linked = self.run_cli("intake", "--input", "portfolio/inbox/link.json")
        self.assertNotEqual(linked.returncode, 0)

    def test_invalid_decision_is_preflighted_without_append(self) -> None:
        self.write("portfolio/inbox/intake.json", {"schema_version": 1, "candidate_id": "candidate-a", "title": "Candidate A", "track": "probability", "lead": "A bounded unverified lead.", "why_now": "Cheap to falsify.", "created_by": ["researcher-a"], "created_at": "2026-01-01T00:00:00Z", "problem_id": None})
        self.assertEqual(self.run_cli("intake", "--input", "portfolio/inbox/intake.json").returncode, 0)
        self.write("portfolio/inbox/invalid-decision.json", {"schema_version": 1, "decision_id": "bad-jump", "decision": "CONTINUE", "to_status": "TRIAL_ACTIVE", "decided_at": "2026-01-02T00:00:00Z", "decided_by": ["researcher-a"], "rationale": "Invalid shortcut.", "supporting_artifact_paths": [], "park": None, "reopen": None, "spinout": None})
        failed = self.run_cli("decide", "--candidate-id", "candidate-a", "--input", "portfolio/inbox/invalid-decision.json")
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(list((self.root / "portfolio/candidates/candidate-a/events").iterdir()), [])

    def test_unicode_project_ids_are_manifest_data_not_paths(self) -> None:
        (self.root / "LAB_PROFILE.json").write_text(json.dumps({"lab": {"id": "лаборатория-тест"}}, ensure_ascii=False), encoding="utf-8")
        self.write("portfolio/inbox/intake.json", {"schema_version": 1, "candidate_id": "candidate-a", "title": "Candidate A", "track": "probability", "lead": "A bounded unverified lead.", "why_now": "Cheap to falsify.", "created_by": ["researcher-a"], "created_at": "2026-01-01T00:00:00Z", "problem_id": None})
        self.assertEqual(self.run_cli("intake", "--input", "portfolio/inbox/intake.json").returncode, 0)
        exported = self.run_cli("export", "--candidate-id", "candidate-a", "--package-id", "transfer-a", "--target-project-id", "другая-лаборатория")
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        manifest = json.loads((self.root / "portfolio/exports/transfer-a/manifest.json").read_text())
        self.assertEqual(manifest["source_project_id"], "лаборатория-тест")
        self.assertEqual(manifest["target_project_id"], "другая-лаборатория")

    def test_generated_unicode_long_problem_id_links_rounds_and_spins_out(self) -> None:
        problem_id = "20260729-" + ("д" * 55) + "-" + ("a" * 10)
        self.assertEqual(len(problem_id.encode("utf-8")), 130)
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        created = self.run_cli(
            "intake", "--input", "portfolio/inbox/intake-v2.json"
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.qualify_and_link(problem_id=problem_id)
        promoted = self.promote(
            promotion_id="unicode-problem-trial",
            to_tier="TRIAL",
            pool=1,
            selected=1,
        )
        self.assertEqual(promoted.returncode, 0, promoted.stdout + promoted.stderr)
        self.write(
            "portfolio/inbox/unicode-round.json",
            self.round_input("unicode-round"),
        )
        rounded = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/unicode-round.json",
        )
        self.assertEqual(rounded.returncode, 0, rounded.stdout + rounded.stderr)
        ready = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="unicode-spinout-ready",
            to_status="SPINOUT_READY",
            spinout=None,
        )
        self.assertEqual(ready.returncode, 0, ready.stdout + ready.stderr)
        self.write(
            "portfolio/inbox/unicode-request.json",
            {
                "schema_version": 1,
                "target_lab_id": "новая-лаборатория",
                "directory_name": "Новая лаборатория",
                "title": "Новая лаборатория",
                "mission": "Продолжить проверяемую программу.",
                "areas": ["комбинаторика"],
                "deliverables": ["theorem"],
                "unresolved_questions": ["gap"],
            },
        )
        prepared = self.run_cli(
            "prepare-spinout",
            "--candidate-id",
            "candidate-a",
            "--seed-id",
            "unicode-seed",
            "--target-lab-id",
            "новая-лаборатория",
            "--request",
            "portfolio/inbox/unicode-request.json",
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        copied = (
            self.root
            / "portfolio/spinouts/unicode-seed/payload/problem_dossier"
        )
        self.assertTrue(copied.is_dir())
        status = json.loads(self.run_cli("status").stdout)["candidates"][0]
        self.assertEqual(status["problem_id"], problem_id)
        validation = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts/validate_discovery_portfolio.py"),
                "--root",
                str(self.root),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_problem_id_rejects_unsafe_unicode_and_path_components(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        events = self.root / "portfolio/candidates/candidate-a/events"
        for index, problem_id in enumerate(
            (
                ".",
                "..",
                "bad id",
                "bad/name",
                "bad\\name",
                "bad\u200bname",
                "е\u0301",
                "-bad",
                "bad-",
                "a" * 161,
            ),
            1,
        ):
            self.write(
                f"portfolio/inbox/unsafe-problem-{index}.json",
                {
                    "schema_version": 1,
                    "link_id": f"unsafe-link-{index}",
                    "problem_id": problem_id,
                    "reason": "Must fail before append.",
                    "linked_by": ["researcher-a"],
                },
            )
            failed = self.run_cli(
                "link-dossier",
                "--candidate-id",
                "candidate-a",
                "--input",
                f"portfolio/inbox/unsafe-problem-{index}.json",
            )
            self.assertNotEqual(failed.returncode, 0, problem_id)
            self.assertEqual(list(events.iterdir()), [])

    def test_event_id_replay_is_idempotent_and_conflicts_fail(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        first = self.decide(
            decision_id="stable-event", to_status="QUALIFYING"
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        event = next(
            (self.root / "portfolio/candidates/candidate-a/events").iterdir()
        )
        original = event.read_bytes()
        replay = self.decide(
            decision_id="stable-event", to_status="QUALIFYING"
        )
        self.assertEqual(replay.returncode, 0, replay.stdout + replay.stderr)
        self.assertEqual(len(list(event.parent.iterdir())), 1)
        self.assertEqual(event.read_bytes(), original)

        conflicting = self.decide(
            decision_id="stable-event",
            to_status="QUALIFYING",
            rationale="A different payload must not reuse an event identity.",
        )
        self.assertNotEqual(conflicting.returncode, 0)
        self.assertIn("different event bytes", conflicting.stderr)
        self.assertEqual(len(list(event.parent.iterdir())), 1)

        self.write(
            "portfolio/inbox/conflicting-type.json",
            {
                "schema_version": 1,
                "qualification_id": "stable-event",
                "assessed_at": "2026-01-02T00:00:00Z",
                "assessed_by": ["researcher-a"],
                "exact_statement": "Statement.",
                "open_assessment": "UNKNOWN",
                "significance_rationale": "Significant.",
                "tractability_rationale": "Testable.",
                "verification_plan": "Check.",
                "cheap_falsifiers": ["Finite cases."],
                "artifact_paths": [],
            },
        )
        reused = self.run_cli(
            "record-qualification",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/conflicting-type.json",
        )
        self.assertNotEqual(reused.returncode, 0)
        self.assertEqual(len(list(event.parent.iterdir())), 1)

    def test_intake_retry_repairs_summary_and_binds_exact_evidence(self) -> None:
        source = self.root / "portfolio/inbox/scout-source.txt"
        source.write_text("first evidence\n", encoding="utf-8")
        self.write(
            "portfolio/inbox/intake-retry.json",
            self.v2_intake(
                origin="LAB_SCOUTED",
                artifact_paths=["portfolio/inbox/scout-source.txt"],
            ),
        )
        module = self.load_cli_module(self.root, "discovery_intake_retry_test")
        args = argparse.Namespace(input="portfolio/inbox/intake-retry.json")
        resolved_root = self.root.resolve()
        with mock.patch.object(
            module,
            "_refresh_summary_locked",
            side_effect=OSError("simulated summary write failure"),
        ):
            with self.assertRaises(OSError):
                module.cmd_intake(resolved_root, args)
        candidate = self.root / "portfolio/candidates/candidate-a"
        self.assertTrue(candidate.is_dir())
        summary = json.loads(
            (self.root / "knowledge/control_room_summary.json").read_text()
        )
        self.assertEqual(summary["candidate_counts"]["LEAD"], 0)

        retried = module.cmd_intake(resolved_root, args)
        self.assertTrue(retried["already_committed"])
        self.assertEqual(
            json.loads(
                (self.root / "knowledge/control_room_summary.json").read_text()
            )["candidate_counts"]["LEAD"],
            1,
        )
        source.write_text("different evidence\n", encoding="utf-8")
        with self.assertRaises(module.PortfolioError):
            module.cmd_intake(resolved_root, args)
        self.assertEqual(len(list((candidate / "origin_evidence").iterdir())), 1)

    def test_import_retry_repairs_summary_without_merging(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "retry-transfer",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.make_target_lab("target-retry")
        shutil.copytree(
            self.root / "portfolio/exports/retry-transfer",
            target / "portfolio/imports/retry-transfer",
        )
        module = self.load_cli_module(target, "discovery_import_retry_test")
        args = argparse.Namespace(package="portfolio/imports/retry-transfer")
        resolved_target = target.resolve()
        with mock.patch.object(
            module,
            "_refresh_summary_locked",
            side_effect=OSError("simulated summary write failure"),
        ):
            with self.assertRaises(OSError):
                module.cmd_import(resolved_target, args)
        candidate = target / "portfolio/candidates/candidate-a"
        self.assertTrue(candidate.is_dir())
        retried = module.cmd_import(resolved_target, args)
        self.assertTrue(retried["already_committed"])
        receipts = list((candidate / "import_receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        validation = subprocess.run(
            [
                sys.executable,
                str(target / "scripts/validate_discovery_portfolio.py"),
                "--root",
                str(target),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_lab_scouted_origin_is_bound_and_survives_transfer(self) -> None:
        (self.root / "portfolio/inbox/scout-source.txt").write_text(
            "Source-bound scouting evidence.\n",
            encoding="utf-8",
        )
        self.write(
            "portfolio/inbox/intake-v2.json",
            self.v2_intake(
                origin="LAB_SCOUTED",
                artifact_paths=["portfolio/inbox/scout-source.txt"],
            ),
        )
        created = self.run_cli("intake", "--input", "portfolio/inbox/intake-v2.json")
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        metadata = json.loads(
            (self.root / "portfolio/candidates/candidate-a/candidate.json").read_text()
        )
        self.assertEqual(metadata["origin"], "LAB_SCOUTED")
        self.assertEqual(
            metadata["origin_artifacts"][0]["path"],
            "portfolio/candidates/candidate-a/origin_evidence/0001",
        )
        (self.root / "portfolio/inbox/scout-source.txt").unlink()

        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "transfer-a",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.root / "target"
        for name in ("portfolio", "knowledge", "scripts", "templates", "workflows"):
            shutil.copytree(MODULE / name, target / name)
        (target / "problems/active").mkdir(parents=True)
        (target / "problems/backlog").mkdir()
        (target / "problems/closed").mkdir()
        (target / "LAB_PROFILE.json").write_text(
            json.dumps({"lab": {"id": "target-lab"}}),
            encoding="utf-8",
        )
        shutil.copytree(
            self.root / "portfolio/exports/transfer-a",
            target / "portfolio/imports/transfer-a",
        )
        imported = subprocess.run(
            [
                sys.executable,
                str(target / "scripts/discovery_portfolio.py"),
                "--root",
                str(target),
                "import",
                "--package",
                "portfolio/imports/transfer-a",
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        validation = subprocess.run(
            [
                sys.executable,
                str(target / "scripts/validate_discovery_portfolio.py"),
                "--root",
                str(target),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_lab_scouted_origin_requires_safe_evidence(self) -> None:
        self.write(
            "portfolio/inbox/missing-evidence.json",
            self.v2_intake(origin="LAB_SCOUTED"),
        )
        missing = self.run_cli(
            "intake",
            "--input",
            "portfolio/inbox/missing-evidence.json",
        )
        self.assertNotEqual(missing.returncode, 0)
        value = self.v2_intake(
            origin="LAB_SCOUTED",
            artifact_paths=["../outside.txt"],
        )
        self.write("portfolio/inbox/unsafe-evidence.json", value)
        unsafe = self.run_cli(
            "intake",
            "--input",
            "portfolio/inbox/unsafe-evidence.json",
        )
        self.assertNotEqual(unsafe.returncode, 0)

    def test_engagement_is_sequential_gated_and_does_not_change_status(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli("intake", "--input", "portfolio/inbox/intake-v2.json").returncode,
            0,
        )
        direct = self.promote(
            promotion_id="direct-deep",
            to_tier="DEEP",
            pool=3,
            selected=1,
        )
        self.assertNotEqual(direct.returncode, 0)
        self.assertEqual(
            list((self.root / "portfolio/candidates/candidate-a/events").iterdir()),
            [],
        )

        self.qualify_and_link()
        trial = self.promote(
            promotion_id="trial-tier",
            to_tier="TRIAL",
            pool=1,
            selected=1,
        )
        self.assertEqual(trial.returncode, 0, trial.stdout + trial.stderr)
        trial_payload = json.loads(trial.stdout)
        self.assertEqual(trial_payload["status"], "TRIAL_ACTIVE")
        self.assertEqual(trial_payload["engagement_tier"], "TRIAL")

        premature = self.promote(
            promotion_id="premature-deep",
            to_tier="DEEP",
            pool=1,
            selected=1,
        )
        self.assertNotEqual(premature.returncode, 0)
        self.write(
            "portfolio/inbox/round.json",
            {
                "schema_version": 1,
                "round_id": "trial-round-a",
                "started_at": "2026-01-03T00:00:00Z",
                "completed_at": "2026-01-03T01:00:00Z",
                "conducted_by": ["researcher-a"],
                "objective": "Run one discriminating trial.",
                "methods": "Independent routes and cheap falsifiers.",
                "observations": "The attempt produced bounded evidence.",
                "strongest_result": "No canonical status change.",
                "remaining_gap": "The exact main gap remains.",
                "semantic_progress": False,
                "proposed_decision": "CONTINUE",
                "artifact_paths": [],
            },
        )
        recorded = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/round.json",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        pending_deep = self.promote(
            promotion_id="pending-deep",
            to_tier="DEEP",
            pool=1,
            selected=1,
        )
        self.assertNotEqual(pending_deep.returncode, 0)
        decision = self.decide(
            decision_id="close-trial-round",
            to_status="TRIAL_ACTIVE",
        )
        self.assertEqual(decision.returncode, 0, decision.stdout + decision.stderr)
        deep = self.promote(
            promotion_id="deep-tier",
            to_tier="DEEP",
            pool=1,
            selected=1,
        )
        self.assertEqual(deep.returncode, 0, deep.stdout + deep.stderr)
        deep_payload = json.loads(deep.stdout)
        self.assertEqual(deep_payload["status"], "TRIAL_ACTIVE")
        self.assertEqual(deep_payload["engagement_tier"], "DEEP")

    def test_smaller_funnel_is_within_default_caps(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli("intake", "--input", "portfolio/inbox/intake-v2.json").returncode,
            0,
        )
        self.qualify_and_link()
        compact = self.promote(
            promotion_id="trial-compact",
            to_tier="TRIAL",
            pool=1,
            selected=1,
        )
        self.assertEqual(compact.returncode, 0, compact.stdout + compact.stderr)

    def test_funnel_cap_excess_requires_rationale(self) -> None:
        candidate_ids = ["candidate-a"] + [
            f"candidate-{index:02d}" for index in range(2, 14)
        ]
        for candidate_id in candidate_ids:
            name = f"intake-{candidate_id}.json"
            self.write(
                f"portfolio/inbox/{name}",
                self.v2_intake(candidate_id=candidate_id, cohort_id="cohort-a"),
            )
            created = self.run_cli(
                "intake", "--input", f"portfolio/inbox/{name}"
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.qualify_and_link()
        false_observation = self.promote(
            promotion_id="trial-false-counts",
            to_tier="TRIAL",
            pool=12,
            selected=1,
        )
        self.assertNotEqual(false_observation.returncode, 0)
        self.assertIn("canonical cohort counts", false_observation.stderr)
        unexplained = self.promote(
            promotion_id="trial-unexplained",
            to_tier="TRIAL",
            pool=13,
            selected=1,
        )
        self.assertNotEqual(unexplained.returncode, 0)
        explained = self.promote(
            promotion_id="trial-explained",
            to_tier="TRIAL",
            pool=13,
            selected=1,
            deviation_rationale="The reviewed scout cohort contains thirteen non-duplicative mechanisms.",
        )
        self.assertEqual(explained.returncode, 0, explained.stdout + explained.stderr)

    def test_trial_and_deep_selection_counts_are_cohort_derived(self) -> None:
        for candidate_id in ("candidate-a", "candidate-b"):
            name = f"intake-{candidate_id}.json"
            self.write(
                f"portfolio/inbox/{name}",
                self.v2_intake(candidate_id=candidate_id, cohort_id="cohort-shared"),
            )
            created = self.run_cli(
                "intake", "--input", f"portfolio/inbox/{name}"
            )
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        for candidate_id, problem_id in (
            ("candidate-a", "problem-a"),
            ("candidate-b", "problem-b"),
        ):
            self.qualify_and_link(
                candidate_id=candidate_id, problem_id=problem_id
            )
        first_trial = self.promote(
            promotion_id="trial-a",
            to_tier="TRIAL",
            pool=2,
            selected=1,
            candidate_id="candidate-a",
        )
        self.assertEqual(
            first_trial.returncode, 0, first_trial.stdout + first_trial.stderr
        )
        false_trial = self.promote(
            promotion_id="trial-b-false",
            to_tier="TRIAL",
            pool=2,
            selected=1,
            candidate_id="candidate-b",
        )
        self.assertNotEqual(false_trial.returncode, 0)
        second_trial = self.promote(
            promotion_id="trial-b",
            to_tier="TRIAL",
            pool=2,
            selected=2,
            candidate_id="candidate-b",
        )
        self.assertEqual(
            second_trial.returncode, 0, second_trial.stdout + second_trial.stderr
        )
        for candidate_id in ("candidate-a", "candidate-b"):
            round_id = f"round-{candidate_id[-1]}"
            self.write(
                f"portfolio/inbox/{round_id}.json", self.round_input(round_id)
            )
            rounded = self.run_cli(
                "record-round",
                "--candidate-id",
                candidate_id,
                "--input",
                f"portfolio/inbox/{round_id}.json",
            )
            self.assertEqual(rounded.returncode, 0, rounded.stdout + rounded.stderr)
            closed = self.decide(
                decision_id=f"close-{round_id}",
                to_status="TRIAL_ACTIVE",
                candidate_id=candidate_id,
            )
            self.assertEqual(closed.returncode, 0, closed.stdout + closed.stderr)
        first_deep = self.promote(
            promotion_id="deep-a",
            to_tier="DEEP",
            pool=2,
            selected=1,
            candidate_id="candidate-a",
        )
        self.assertEqual(first_deep.returncode, 0, first_deep.stdout + first_deep.stderr)
        second_deep = self.promote(
            promotion_id="deep-b-no-rationale",
            to_tier="DEEP",
            pool=2,
            selected=2,
            candidate_id="candidate-b",
        )
        self.assertNotEqual(second_deep.returncode, 0)
        explained = self.promote(
            promotion_id="deep-b-explained",
            to_tier="DEEP",
            pool=2,
            selected=2,
            candidate_id="candidate-b",
            deviation_rationale="Two independent mechanisms earned bounded deep runs.",
        )
        self.assertEqual(explained.returncode, 0, explained.stdout + explained.stderr)

    def test_v1_trial_history_remains_valid_without_engagement_event(self) -> None:
        self.write(
            "portfolio/inbox/intake.json",
            {
                "schema_version": 1,
                "candidate_id": "candidate-a",
                "title": "Legacy Candidate",
                "track": "probability",
                "lead": "A legacy bounded lead.",
                "why_now": "Preserve the old workflow exactly.",
                "created_by": ["researcher-a"],
                "created_at": "2026-01-01T00:00:00Z",
                "problem_id": None,
            },
        )
        self.assertEqual(
            self.run_cli("intake", "--input", "portfolio/inbox/intake.json").returncode,
            0,
        )
        self.qualify_and_link()
        self.write(
            "portfolio/inbox/legacy-round.json",
            {
                "schema_version": 1,
                "round_id": "legacy-round",
                "started_at": "2026-01-03T00:00:00Z",
                "completed_at": "2026-01-03T01:00:00Z",
                "conducted_by": ["researcher-a"],
                "objective": "Exercise the pre-tier round path.",
                "methods": "The legacy method.",
                "observations": "The legacy event remains accepted.",
                "strongest_result": "No mathematical status effect.",
                "remaining_gap": "Still unknown.",
                "semantic_progress": False,
                "proposed_decision": "CONTINUE",
                "artifact_paths": [],
            },
        )
        round_result = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/legacy-round.json",
        )
        self.assertEqual(
            round_result.returncode,
            0,
            round_result.stdout + round_result.stderr,
        )
        status = self.run_cli("status")
        self.assertEqual(status.returncode, 0, status.stdout + status.stderr)
        record = json.loads(status.stdout)["candidates"][0]
        self.assertEqual(record["origin"], "USER_SUPPLIED")
        self.assertEqual(record["engagement_tier"], "SCOUT")
        validation = subprocess.run(
            [
                sys.executable,
                str(self.root / "scripts/validate_discovery_portfolio.py"),
                "--root",
                str(self.root),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)

    def test_event_publication_is_atomic_and_no_clobber(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "discovery_portfolio_lib_under_test",
            self.root / "scripts/discovery_portfolio_lib.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        target = self.root / "portfolio/inbox/atomic-event.json"
        with mock.patch.object(
            module.os, "link", side_effect=OSError("simulated crash before commit")
        ):
            with self.assertRaises(OSError):
                module.write_json_atomic_exclusive(
                    target,
                    {"complete": True},
                    staging_directory=self.root / "portfolio/inbox",
                )
        self.assertFalse(target.exists())
        module.write_json_atomic_exclusive(
            target,
            {"complete": True},
            staging_directory=self.root / "portfolio/inbox",
        )
        original = target.read_bytes()
        with self.assertRaises(module.PortfolioError):
            module.write_json_atomic_exclusive(
                target,
                {"complete": False},
                staging_directory=self.root / "portfolio/inbox",
            )
        self.assertEqual(target.read_bytes(), original)

    def test_transfer_rejects_a_linked_dossier(self) -> None:
        self.prepare_trial_candidate()
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "not-closed",
            "--target-project-id",
            "target-lab",
        )
        self.assertNotEqual(exported.returncode, 0)
        self.assertIn("linked problem dossiers", exported.stderr)
        self.assertFalse((self.root / "portfolio/exports/not-closed").exists())

    def test_transfer_rejects_external_artifact_bindings(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        self.assertEqual(
            self.decide(
                decision_id="qualify-external", to_status="QUALIFYING"
            ).returncode,
            0,
        )
        (self.root / "portfolio/inbox/external-evidence.txt").write_text(
            "External evidence.\n", encoding="utf-8"
        )
        qualification = {
            "schema_version": 1,
            "qualification_id": "external-binding",
            "assessed_at": "2026-01-02T00:00:00Z",
            "assessed_by": ["researcher-a"],
            "exact_statement": "An exact candidate statement.",
            "open_assessment": "UNKNOWN",
            "significance_rationale": "A checked answer would matter.",
            "tractability_rationale": "Cheap falsifiers are available.",
            "verification_plan": "Use an independent checker.",
            "cheap_falsifiers": ["Search the first finite cases."],
            "artifact_paths": ["portfolio/inbox/external-evidence.txt"],
        }
        self.write("portfolio/inbox/external-qualification.json", qualification)
        recorded = self.run_cli(
            "record-qualification",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/external-qualification.json",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "external-transfer",
            "--target-project-id",
            "target-lab",
        )
        self.assertNotEqual(exported.returncode, 0)
        self.assertIn("external artifact bindings", exported.stderr)
        self.assertFalse(
            (self.root / "portfolio/exports/external-transfer").exists()
        )

    def test_import_compares_manifest_status_before_publication(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "status-drift",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.make_target_lab("target-status")
        package = target / "portfolio/imports/status-drift"
        shutil.copytree(self.root / "portfolio/exports/status-drift", package)
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["candidate_status"] = "QUALIFYING"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        imported = self.run_target_cli(
            target, "import", "--package", "portfolio/imports/status-drift"
        )
        self.assertNotEqual(imported.returncode, 0)
        self.assertIn("candidate_status does not match", imported.stderr)
        self.assertFalse(
            (target / "portfolio/candidates/candidate-a").exists()
        )

    def test_transfer_requires_factory_generation_is_kind_bound(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "wrong-factory-flag",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.make_target_lab("target-factory-flag")
        package = target / "portfolio/imports/wrong-factory-flag"
        shutil.copytree(
            self.root / "portfolio/exports/wrong-factory-flag", package
        )
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIs(manifest["requires_factory_generation"], False)
        manifest["requires_factory_generation"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        imported = self.run_target_cli(
            target,
            "import",
            "--package",
            "portfolio/imports/wrong-factory-flag",
        )
        self.assertNotEqual(imported.returncode, 0)
        self.assertIn("safety declarations", imported.stderr)
        self.assertFalse(
            (target / "portfolio/candidates/candidate-a").exists()
        )

    def test_import_semantically_preflights_rehashed_payload_before_publication(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "semantic-drift",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.make_target_lab("target-semantic")
        package = target / "portfolio/imports/semantic-drift"
        shutil.copytree(self.root / "portfolio/exports/semantic-drift", package)
        metadata_path = package / "payload/candidate/candidate.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["candidate_id"] = "different-candidate"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        self.rehash_package(package)
        imported = self.run_target_cli(
            target, "import", "--package", "portfolio/imports/semantic-drift"
        )
        self.assertNotEqual(imported.returncode, 0)
        self.assertIn("directory name does not match", imported.stderr)
        self.assertFalse(
            (target / "portfolio/candidates/candidate-a").exists()
        )

    def test_import_receipt_is_exclusive_before_publication(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        self.write(
            "portfolio/candidates/candidate-a/import_receipts/receipt-collision.json",
            {
                "schema_version": 1,
                "package_id": "receipt-collision",
                "package_manifest_sha256": "0" * 64,
                "candidate_id": "candidate-a",
                "source_project_id": "earlier-source",
                "target_project_id": "test-lab",
                "imported_at": "2026-01-01T00:00:00Z",
                "source_package_retained": True,
                "mathematical_status_effect": "NONE",
            },
        )
        exported = self.run_cli(
            "export",
            "--candidate-id",
            "candidate-a",
            "--package-id",
            "receipt-collision",
            "--target-project-id",
            "target-lab",
        )
        self.assertEqual(exported.returncode, 0, exported.stdout + exported.stderr)
        target = self.make_target_lab("target-receipt")
        shutil.copytree(
            self.root / "portfolio/exports/receipt-collision",
            target / "portfolio/imports/receipt-collision",
        )
        imported = self.run_target_cli(
            target, "import", "--package", "portfolio/imports/receipt-collision"
        )
        self.assertNotEqual(imported.returncode, 0)
        self.assertIn("refusing to overwrite existing record", imported.stderr)
        self.assertFalse(
            (target / "portfolio/candidates/candidate-a").exists()
        )

    def test_final_spinout_requires_typed_bound_passing_receipt(self) -> None:
        seed = self.prepare_spinout_seed()
        manifest_digest = hashlib.sha256(
            (seed / "manifest.json").read_bytes()
        ).hexdigest()
        plain = self.root / "portfolio/inbox/plain-receipt.txt"
        plain.write_text("not a receipt\n", encoding="utf-8")
        before = list(
            (self.root / "portfolio/candidates/candidate-a/events").iterdir()
        )
        rejected_plain = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="plain-final",
            to_status="SPUN_OUT",
            spinout={
                "seed_id": "seed-a",
                "receipt_artifact_path": "portfolio/inbox/plain-receipt.txt",
            },
        )
        self.assertNotEqual(rejected_plain.returncode, 0)
        self.assertEqual(
            list((self.root / "portfolio/candidates/candidate-a/events").iterdir()),
            before,
        )
        manifest_path = seed / "manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        self.assertIs(manifest["requires_factory_generation"], True)
        manifest["requires_factory_generation"] = False
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        rejected_seed_flag = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="wrong-seed-flag-final",
            to_status="SPUN_OUT",
            spinout={
                "seed_id": "seed-a",
                "receipt_artifact_path": "portfolio/inbox/plain-receipt.txt",
            },
        )
        self.assertNotEqual(rejected_seed_flag.returncode, 0)
        self.assertIn("safety declarations", rejected_seed_flag.stderr)
        manifest_path.write_bytes(manifest_bytes)

        receipt = {
            "schema_version": 1,
            "seed_id": "seed-a",
            "target_lab_id": "target-lab",
            "seed_manifest_sha256": manifest_digest,
            "doctor_passed": False,
            "validator_passed": True,
            "smoke_eval_passed": True,
            "recorded_at": "2026-01-05T00:00:00Z",
            "recorded_by": "researcher-a",
        }
        self.write("portfolio/inbox/spinout-receipt.json", receipt)
        rejected_gate = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="false-gate-final",
            to_status="SPUN_OUT",
            spinout={
                "seed_id": "seed-a",
                "receipt_artifact_path": "portfolio/inbox/spinout-receipt.json",
            },
        )
        self.assertNotEqual(rejected_gate.returncode, 0)
        self.assertIn("doctor_passed=true", rejected_gate.stderr)

        self.write(
            "portfolio/inbox/intake-b.json",
            self.v2_intake(candidate_id="candidate-b", cohort_id="cohort-b"),
        )
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-b.json"
            ).returncode,
            0,
        )
        self.qualify_and_link(candidate_id="candidate-b", problem_id="problem-b")
        promoted_b = self.promote(
            promotion_id="trial-b",
            to_tier="TRIAL",
            pool=1,
            selected=1,
            candidate_id="candidate-b",
        )
        self.assertEqual(
            promoted_b.returncode, 0, promoted_b.stdout + promoted_b.stderr
        )
        self.write("portfolio/inbox/round-b.json", self.round_input("round-b"))
        rounded_b = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-b",
            "--input",
            "portfolio/inbox/round-b.json",
        )
        self.assertEqual(rounded_b.returncode, 0, rounded_b.stdout + rounded_b.stderr)
        ready_b = self.spinout_decide(
            candidate_id="candidate-b",
            decision_id="ready-b",
            to_status="SPINOUT_READY",
            spinout=None,
        )
        self.assertEqual(ready_b.returncode, 0, ready_b.stdout + ready_b.stderr)

        receipt["doctor_passed"] = True
        self.write("portfolio/inbox/spinout-receipt.json", receipt)
        wrong_candidate = self.spinout_decide(
            candidate_id="candidate-b",
            decision_id="wrong-candidate-final",
            to_status="SPUN_OUT",
            spinout={
                "seed_id": "seed-a",
                "receipt_artifact_path": "portfolio/inbox/spinout-receipt.json",
            },
        )
        self.assertNotEqual(wrong_candidate.returncode, 0)
        self.assertIn("does not match this candidate", wrong_candidate.stderr)

        completed = self.spinout_decide(
            candidate_id="candidate-a",
            decision_id="valid-final",
            to_status="SPUN_OUT",
            spinout={
                "seed_id": "seed-a",
                "receipt_artifact_path": "portfolio/inbox/spinout-receipt.json",
            },
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        status = {
            item["candidate_id"]: item
            for item in json.loads(self.run_cli("status").stdout)["candidates"]
        }
        self.assertEqual(status["candidate-a"]["status"], "SPUN_OUT")
        self.assertEqual(status["candidate-b"]["status"], "SPINOUT_READY")

    def test_dossier_relink_is_forbidden_after_first_round(self) -> None:
        self.prepare_trial_candidate()
        self.write("portfolio/inbox/round-one.json", self.round_input("round-one"))
        recorded = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/round-one.json",
        )
        self.assertEqual(recorded.returncode, 0, recorded.stdout + recorded.stderr)
        (self.root / "problems/active/problem-b").mkdir()
        self.write(
            "portfolio/inbox/relink.json",
            {
                "schema_version": 1,
                "link_id": "dossier-b",
                "problem_id": "problem-b",
                "reason": "Attempt to move serious work after it began.",
                "linked_by": ["researcher-a"],
            },
        )
        events = self.root / "portfolio/candidates/candidate-a/events"
        before = [path.name for path in events.iterdir()]
        relinked = self.run_cli(
            "link-dossier",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/relink.json",
        )
        self.assertNotEqual(relinked.returncode, 0)
        self.assertIn("cannot be relinked", relinked.stderr)
        self.assertEqual([path.name for path in events.iterdir()], before)

    def test_round_requires_decision_before_next_round_or_deep(self) -> None:
        self.prepare_trial_candidate()
        self.write("portfolio/inbox/round-one.json", self.round_input("round-one"))
        first = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/round-one.json",
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        status = json.loads(self.run_cli("status").stdout)["candidates"][0]
        self.assertTrue(status["pending_round_decision"])

        self.write("portfolio/inbox/round-two.json", self.round_input("round-two"))
        second = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/round-two.json",
        )
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("previous round requires", second.stderr)
        deep = self.promote(
            promotion_id="deep-while-pending",
            to_tier="DEEP",
            pool=1,
            selected=1,
        )
        self.assertNotEqual(deep.returncode, 0)
        self.assertIn("decision after the latest round", deep.stderr)

        decision = self.decide(
            decision_id="close-round-one", to_status="TRIAL_ACTIVE"
        )
        self.assertEqual(decision.returncode, 0, decision.stdout + decision.stderr)
        status = json.loads(self.run_cli("status").stdout)["candidates"][0]
        self.assertFalse(status["pending_round_decision"])
        second = self.run_cli(
            "record-round",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/round-two.json",
        )
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

    def test_refresh_summary_requires_the_portfolio_lock(self) -> None:
        summary = self.root / "knowledge/control_room_summary.json"
        before = summary.read_bytes()
        spec = importlib.util.spec_from_file_location(
            "discovery_portfolio_lock_under_test",
            self.root / "scripts/discovery_portfolio_lib.py",
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        lock = self.root / "portfolio/.discovery-portfolio.lock"
        lock.write_text("pid=stale\n", encoding="ascii")
        identity = (lock.stat().st_dev, lock.stat().st_ino)
        with module.FileLock(lock):
            refreshed = self.run_cli("refresh-summary")
            self.assertNotEqual(refreshed.returncode, 0)
            self.assertIn("another portfolio operation is active", refreshed.stderr)
        self.assertEqual(summary.read_bytes(), before)
        self.assertEqual((lock.stat().st_dev, lock.stat().st_ino), identity)
        refreshed = self.run_cli("refresh-summary")
        self.assertEqual(refreshed.returncode, 0, refreshed.stdout + refreshed.stderr)
        self.assertTrue(lock.is_file())

    def test_summary_lock_blocks_before_primary_commit_and_is_cross_module_compatible(self) -> None:
        discovery_spec = importlib.util.spec_from_file_location(
            "discovery_lock_cross_test",
            self.root / "scripts/discovery_portfolio_lib.py",
        )
        self.assertIsNotNone(discovery_spec)
        self.assertIsNotNone(discovery_spec.loader)
        discovery = importlib.util.module_from_spec(discovery_spec)
        discovery_spec.loader.exec_module(discovery)
        team = None
        team_paths = (
            MODULE.parent / "team_collaboration/scripts/team_collaboration.py",
            MODULE / "scripts/team_collaboration.py",
        )
        team_path = next((path for path in team_paths if path.is_file()), None)
        if team_path is not None:
            team_spec = importlib.util.spec_from_file_location(
                "team_lock_cross_test", team_path
            )
            self.assertIsNotNone(team_spec)
            self.assertIsNotNone(team_spec.loader)
            team = importlib.util.module_from_spec(team_spec)
            team_spec.loader.exec_module(team)

        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        summary_lock = self.root / "knowledge/.control-room-summary.lock"

        @contextmanager
        def peer_lock():
            if team is not None:
                with team.FileLock(summary_lock, "Control Room summary"):
                    yield
                return
            descriptor = os.open(
                str(summary_lock),
                os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                yield
            finally:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

        with peer_lock():
            blocked = self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            )
            self.assertNotEqual(blocked.returncode, 0)
            self.assertFalse(
                (self.root / "portfolio/candidates/candidate-a").exists()
            )
            with self.assertRaises(discovery.PortfolioError):
                with discovery.FileLock(summary_lock):
                    pass
        with discovery.FileLock(summary_lock):
            expected_error = (
                team.CollaborationError
                if team is not None
                else BlockingIOError
            )
            with self.assertRaises(expected_error):
                with peer_lock():
                    pass
        created = self.run_cli(
            "intake", "--input", "portfolio/inbox/intake-v2.json"
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        self.assertTrue(summary_lock.is_file())

    def test_advisory_lock_is_released_when_holder_is_killed(self) -> None:
        lock = self.root / "portfolio/.discovery-portfolio.lock"
        code = (
            "import sys,time;"
            f"sys.path.insert(0,{str(self.root / 'scripts')!r});"
            "from discovery_portfolio_lib import FileLock;"
            f"p={str(lock)!r};"
            "lease=FileLock(__import__('pathlib').Path(p));"
            "lease.__enter__();print('ready',flush=True);time.sleep(60)"
        )
        holder = subprocess.Popen(
            [sys.executable, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self.assertEqual(holder.stdout.readline().strip(), "ready")
            blocked = self.run_cli("refresh-summary")
            self.assertNotEqual(blocked.returncode, 0)
            holder.kill()
            holder.wait(timeout=5)
            recovered = self.run_cli("refresh-summary")
            self.assertEqual(
                recovered.returncode, 0, recovered.stdout + recovered.stderr
            )
            self.assertTrue(lock.is_file())
        finally:
            if holder.poll() is None:
                holder.kill()
                holder.wait(timeout=5)
            if holder.stdout is not None:
                holder.stdout.close()
            if holder.stderr is not None:
                holder.stderr.close()

    def test_marker_bound_staging_recovery_preserves_near_matches(self) -> None:
        module_spec = importlib.util.spec_from_file_location(
            "discovery_stage_recovery_test",
            self.root / "scripts/discovery_portfolio_lib.py",
        )
        self.assertIsNotNone(module_spec)
        self.assertIsNotNone(module_spec.loader)
        module = importlib.util.module_from_spec(module_spec)
        module_spec.loader.exec_module(module)
        abandoned = module.create_staging_directory(self.root, "CANDIDATE")
        (abandoned / "partial").mkdir()
        near_match = self.root / "portfolio/inbox/.candidate-stage-usernotes"
        near_match.mkdir()
        (near_match / "keep.txt").write_text("user-owned\n", encoding="utf-8")
        recovered = self.run_cli("refresh-summary")
        self.assertEqual(recovered.returncode, 0, recovered.stdout + recovered.stderr)
        self.assertFalse(abandoned.exists())
        self.assertEqual(
            (near_match / "keep.txt").read_text(encoding="utf-8"), "user-owned\n"
        )

    def test_spinout_request_copy_rejects_a_late_symlink_swap(self) -> None:
        self.prepare_spinout_seed(seed_id="seed-first")
        self.write(
            "portfolio/inbox/race-request.json",
            {
                "schema_version": 1,
                "target_lab_id": "race-target",
                "directory_name": "Race Target",
                "title": "Race Target",
                "mission": "The validated request bytes only.",
                "areas": ["combinatorics"],
                "deliverables": ["theorem"],
                "unresolved_questions": ["gap"],
            },
        )
        outside = self.root / "outside-request.json"
        outside.write_text('{"secret":"outside"}\n', encoding="utf-8")
        module = self.load_cli_module(self.root, "discovery_request_race_test")
        original_copy = module.copy_safe_file
        swapped = False

        def swap_then_copy(source: Path, target: Path) -> None:
            nonlocal swapped
            if not swapped:
                swapped = True
                source.unlink()
                source.symlink_to(outside)
            original_copy(source, target)

        args = argparse.Namespace(
            candidate_id="candidate-a",
            seed_id="seed-race",
            target_lab_id="race-target",
            request="portfolio/inbox/race-request.json",
        )
        with mock.patch.object(module, "copy_safe_file", side_effect=swap_then_copy):
            with self.assertRaises(module.PortfolioError):
                module.cmd_prepare_spinout(self.root.resolve(), args)
        self.assertFalse((self.root / "portfolio/spinouts/seed-race").exists())
        self.assertEqual(outside.read_text(encoding="utf-8"), '{"secret":"outside"}\n')

    def test_artifact_is_rechecked_after_event_preflight(self) -> None:
        self.write("portfolio/inbox/intake-v2.json", self.v2_intake())
        self.assertEqual(
            self.run_cli(
                "intake", "--input", "portfolio/inbox/intake-v2.json"
            ).returncode,
            0,
        )
        self.assertEqual(
            self.decide(
                decision_id="begin-artifact-check", to_status="QUALIFYING"
            ).returncode,
            0,
        )
        artifact = self.root / "portfolio/inbox/qualification-artifact.txt"
        artifact.write_text("first bytes\n", encoding="utf-8")
        self.write(
            "portfolio/inbox/raced-qualification.json",
            {
                "schema_version": 1,
                "qualification_id": "raced-qualification",
                "assessed_at": "2026-01-02T00:00:00Z",
                "assessed_by": ["researcher-a"],
                "exact_statement": "An exact statement.",
                "open_assessment": "UNKNOWN",
                "significance_rationale": "Significant.",
                "tractability_rationale": "Testable.",
                "verification_plan": "Independently check.",
                "cheap_falsifiers": ["Finite cases."],
                "artifact_paths": ["portfolio/inbox/qualification-artifact.txt"],
            },
        )
        module = self.load_cli_module(self.root, "discovery_artifact_race_test")
        append_globals = module.append_event.__globals__
        original_derive = append_globals["derive_candidate"]
        calls = 0

        def mutate_after_first_stage(*args, **kwargs):
            nonlocal calls
            result = original_derive(*args, **kwargs)
            calls += 1
            if calls == 2:
                artifact.write_text("changed after preflight\n", encoding="utf-8")
            return result

        args = argparse.Namespace(
            candidate_id="candidate-a",
            input="portfolio/inbox/raced-qualification.json",
        )
        events = self.root / "portfolio/candidates/candidate-a/events"
        before = [path.name for path in events.iterdir()]
        with mock.patch.dict(
            append_globals, {"derive_candidate": mutate_after_first_stage}
        ):
            with self.assertRaises(module.PortfolioError):
                module.cmd_record_qualification(self.root.resolve(), args)
        self.assertEqual([path.name for path in events.iterdir()], before)
        succeeded = self.run_cli(
            "record-qualification",
            "--candidate-id",
            "candidate-a",
            "--input",
            "portfolio/inbox/raced-qualification.json",
        )
        self.assertEqual(succeeded.returncode, 0, succeeded.stdout + succeeded.stderr)

    def test_lock_symlink_failure_is_typed(self) -> None:
        target = self.root / "portfolio/inbox/lock-target"
        target.write_text("unchanged\n", encoding="utf-8")
        lock = self.root / "portfolio/.discovery-portfolio.lock"
        if lock.exists() or lock.is_symlink():
            lock.unlink()
        lock.symlink_to(target)
        failed = self.run_cli("refresh-summary")
        self.assertEqual(failed.returncode, 2)
        self.assertIn("discovery portfolio error", failed.stderr)
        self.assertNotIn("Traceback", failed.stderr)
        self.assertEqual(target.read_text(encoding="utf-8"), "unchanged\n")


if __name__ == "__main__":
    unittest.main()
