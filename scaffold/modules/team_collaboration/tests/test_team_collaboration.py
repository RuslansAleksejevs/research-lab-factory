#!/usr/bin/env python3
"""Adversarial tests for team cycles and repository bootstrap safety."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional


MODULE_ROOT = Path(__file__).resolve().parents[1]
TEAM_SCRIPT = MODULE_ROOT / "scripts/team_collaboration.py"
REPOSITORY_SCRIPT = MODULE_ROOT / "scripts/team_repository_bootstrap.py"


def summary_digest(value: Dict[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key not in {"generated_at", "source_digest_sha256"}}
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(path.parent))
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


class TeamCollaborationTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="team-collaboration-test-")
        self.root = Path(self.temporary.name)
        # Build an isolated empty fixture instead of copying the generated
        # laboratory's live collaboration state. Full lab evals must remain
        # hermetic after real cycles, work items, plans, or receipts exist.
        for relative in (
            "collaboration/cycles",
            "collaboration/work_items",
            "collaboration/contributions",
            "collaboration/repository/plans",
            "collaboration/repository/reviews",
            "collaboration/repository/receipts",
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        (self.root / "collaboration/team.json").write_text(
            json.dumps(
                {
                    "record_type": "team_collaboration_configuration",
                    "schema_version": 1,
                    "status": "UNCONFIGURED",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (self.root / "knowledge").mkdir()
        (self.root / "notes").mkdir()
        self.profile = {
            "schema_version": 1,
            "lab": {
                "kind": "DISCOVERY_PORTFOLIO",
                "collaboration": {
                    "members": [
                        {
                            "id": "alpha",
                            "display_name": "Alpha Researcher",
                            "role": "STEWARD",
                            "github_handle": "alpha-gh",
                        },
                        {
                            "id": "beta",
                            "display_name": "Beta Researcher",
                            "role": "CO_OWNER",
                            "github_handle": "beta-gh",
                        },
                    ],
                    "steward_id": "alpha",
                    "governance": {
                        "research_decisions": "CONSENSUS",
                        "spinout_decisions": "CONSENSUS",
                        "publication_decisions": "CONSENSUS",
                        "process_decisions": "STEWARD",
                    },
                    "authorship_policy": "ALL_MEMBERS_EXPECTED_COAUTHORS",
                    "integration_mode": "PULL_REQUEST",
                    "cycle_policy": "MEETING_REAUTHORIZED",
                    "meeting_capture": "MANUAL_SUMMARY_REVISIT_AFTER_FIRST_CYCLE",
                    "repository": {
                        "provider": "GITHUB",
                        "visibility": "UNDECIDED",
                        "setup_state": "NOT_CONFIGURED",
                    },
                },
            },
        }
        (self.root / "LAB_PROFILE.json").write_text(
            json.dumps(self.profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_script(
        self, script: Path, *arguments: str, env: Optional[Dict[str, str]] = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script), "--root", str(self.root), "--json", *arguments],
            cwd=str(self.root),
            text=True,
            capture_output=True,
            timeout=30,
            env=env or self.environment,
        )

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return value

    def assert_failed(self, result: subprocess.CompletedProcess[str], fragment: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(fragment.lower(), (result.stdout + result.stderr).lower())

    def bootstrap(self) -> Dict[str, Any]:
        return self.assert_ok(self.run_script(TEAM_SCRIPT, "bootstrap-from-profile"))

    def test_profile_bootstrap_is_exact_idempotent_and_preserves_safe_discovery_fields(self) -> None:
        first = self.bootstrap()
        second = self.bootstrap()
        self.assertEqual(first, second)
        team = json.loads((self.root / "collaboration/team.json").read_text(encoding="utf-8"))
        self.assertEqual(team["steward_id"], "alpha")
        self.assertEqual(team["meeting_capture"], "MANUAL_SUMMARY_REVISIT_AFTER_FIRST_CYCLE")
        self.assertEqual(team["members"], self.profile["lab"]["collaboration"]["members"])

        summary_path = self.root / "knowledge/control_room_summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary["candidate_counts"]["PARKED"] = 2
        summary["model_recheck_count"] = 2
        summary["source_digest_sha256"] = summary_digest(summary)
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        module = load_script(TEAM_SCRIPT, "_team_collaboration_summary_test")
        module.update_summary(
            self.root,
            lambda current: current.__setitem__(
                "repository", {"state": "PENDING", "visibility": "PRIVATE"}
            ),
        )
        updated = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["candidate_counts"]["PARKED"], 2)
        self.assertEqual(updated["model_recheck_count"], 2)
        self.assertEqual(updated["source_digest_sha256"], summary_digest(updated))

        # An immutable profile change cannot silently rewrite configured governance.
        self.profile["lab"]["collaboration"]["members"][1]["display_name"] = "Changed Name"
        (self.root / "LAB_PROFILE.json").write_text(
            json.dumps(self.profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        failed = self.run_script(TEAM_SCRIPT, "bootstrap-from-profile")
        self.assert_failed(failed, "differs from lab_profile")
        self.assertEqual(
            json.loads((self.root / "collaboration/team.json").read_text(encoding="utf-8"))["members"][1]["display_name"],
            "Beta Researcher",
        )

    def test_complete_meeting_reauthorized_append_only_cycle(self) -> None:
        self.bootstrap()
        prepared = self.assert_ok(
            self.run_script(
                TEAM_SCRIPT,
                "prepare-cycle",
                "--cycle-id", "cycle_one",
                "--meeting-id", "meeting_one",
                "--prepared-by", "alpha",
                "--prepared-at", "2026-07-17T10:00:00Z",
                "--starts-at", "2026-07-17T11:00:00Z",
                "--ends-at", "2026-07-31T11:00:00Z",
                "--focus", "Choose one bounded direction and define a falsifier.",
            )
        )
        self.assertEqual(prepared["phase"], "PREPARED")
        agenda_path = self.root / "collaboration/cycles/cycle_one/agenda.md"
        agenda_bytes = agenda_path.read_bytes()
        self.assert_failed(
            self.run_script(
                TEAM_SCRIPT,
                "authorize-cycle",
                "--cycle-id", "cycle_one",
                "--meeting-id", "meeting_one",
                "--authorized-by", "alpha",
            ),
            "every configured member",
        )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT,
                "authorize-cycle",
                "--cycle-id", "cycle_one",
                "--meeting-id", "meeting_one",
                "--authorized-by", "alpha",
                "--authorized-by", "beta",
                "--authorized-at", "2026-07-17T11:30:00Z",
            )
        )
        summary_file = self.root / "notes/meeting-summary.md"
        summary_file.write_text(
            "We reviewed the candidate list and unanimously selected one bounded trial.\n\n"
            "Alpha will produce the exact artifact; Beta will review it independently.\n",
            encoding="utf-8",
        )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT, "record-minutes", "--cycle-id", "cycle_one",
                "--recorded-by", "alpha", "--summary-file", "notes/meeting-summary.md",
                "--recorded-at", "2026-07-17T12:00:00Z",
            )
        )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT,
                "create-work-item",
                "--cycle-id", "cycle_one",
                "--work-item-id", "trial_one",
                "--type", "PROOF",
                "--owner", "alpha",
                "--created-by", "alpha",
                "--created-at", "2026-07-17T12:05:00Z",
                "--title", "Test the bounded mechanism",
                "--expected-artifact", "notes/trial-result.md",
                "--success-criterion", "A checkable proof fragment or explicit obstruction.",
                "--stop-rule", "Stop after the first decisive obstruction or completed fragment.",
            )
        )
        (self.root / "notes/trial-result.md").write_text("A bounded auditable result.\n", encoding="utf-8")
        for event_id, status, timestamp in (
            ("start", "IN_PROGRESS", "2026-07-17T12:10:00Z"),
            ("review", "READY_FOR_REVIEW", "2026-07-18T12:10:00Z"),
            ("accept", "ACCEPTED", "2026-07-19T12:10:00Z"),
        ):
            self.assert_ok(
                self.run_script(
                    TEAM_SCRIPT, "transition-work-item", "--work-item-id", "trial_one",
                    "--event-id", event_id, "--to-status", status, "--actor", "alpha",
                    "--note", f"Recorded transition to {status}.", "--recorded-at", timestamp,
                )
            )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT, "record-contribution", "--contribution-id", "human-proof",
                "--work-item-id", "trial_one", "--recorded-by", "alpha",
                "--contributor-type", "HUMAN", "--contributor-id", "alpha",
                "--contribution-kind", "KEY_MECHANISM",
                "--role", "Produced the bounded argument.",
                "--statement", "Created the exact artifact; this record grants no mathematical status.",
                "--artifact", "notes/trial-result.md", "--recorded-at", "2026-07-19T12:15:00Z",
            )
        )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT, "record-decision", "--cycle-id", "cycle_one",
                "--decision-id", "continue-one", "--type", "RESEARCH",
                "--agreed-by", "alpha", "--agreed-by", "beta",
                "--summary", "Retain the auditable artifact for synthesis.",
                "--rationale", "Both members reviewed scope and evidence; mathematical verification remains separate.",
                "--recorded-at", "2026-07-19T12:20:00Z",
            )
        )
        self.assert_ok(
            self.run_script(
                TEAM_SCRIPT, "close-cycle", "--cycle-id", "cycle_one",
                "--meeting-id", "meeting_two", "--closed-by", "alpha", "--closed-by", "beta",
                "--verdict", "CONTINUE", "--capture-mode-review", "DEFER",
                "--closed-at", "2026-07-31T11:00:00Z", "--next-cycle-at", "2026-08-01T11:00:00Z",
            )
        )
        validated = self.assert_ok(self.run_script(TEAM_SCRIPT, "validate"))
        self.assertEqual(validated["status"], "VALID")
        contribution_path = self.root / "collaboration/contributions/human-proof.json"
        contribution = json.loads(contribution_path.read_text(encoding="utf-8"))
        self.assertEqual(contribution["contribution_kind"], "KEY_MECHANISM")
        self.assertEqual(contribution["authorship_or_mathematical_status_effect"], "NONE")
        self.assertEqual(agenda_path.read_bytes(), agenda_bytes)
        self.assert_failed(
            self.run_script(
                TEAM_SCRIPT, "prepare-cycle", "--cycle-id", "cycle_one",
                "--meeting-id", "meeting_three", "--prepared-by", "alpha",
                "--starts-at", "2026-08-01T11:00:00Z", "--ends-at", "2026-08-15T11:00:00Z",
                "--focus", "This must not overwrite the closed cycle.",
            ),
            "already exists",
        )
        self.assertEqual(agenda_path.read_bytes(), agenda_bytes)

        contribution["authorship_or_mathematical_status_effect"] = "AUTOMATIC_COAUTHOR"
        contribution_path.write_text(
            json.dumps(contribution, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.assert_failed(
            self.run_script(TEAM_SCRIPT, "validate"),
            "cannot grant authorship",
        )

    def test_contribution_taxonomy_and_tree_are_fail_closed(self) -> None:
        self.bootstrap()
        forged = self.root / "collaboration/contributions/forged.json"
        forged.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "record_type": "team_contribution_provenance",
                    "contribution_id": "forged",
                    "authorship_or_mathematical_status_effect": "NONE",
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        self.assert_failed(self.run_script(TEAM_SCRIPT, "validate"), "unsupported or incomplete shape")

        forged.unlink()
        target = self.root / "notes/symlink-target.json"
        target.write_text("{}\n", encoding="utf-8")
        forged.symlink_to(target)
        self.assert_failed(self.run_script(TEAM_SCRIPT, "validate"), "unsafe contributions entry")

    def test_locks_and_digest_tamper_fail_closed(self) -> None:
        self.bootstrap()
        module = load_script(TEAM_SCRIPT, "_team_collaboration_lock_test")
        team_lock = self.root / "collaboration/.team-collaboration.lock"
        team_lock.write_text("pid=stale\n", encoding="ascii")
        team_lock_identity = (team_lock.stat().st_dev, team_lock.stat().st_ino)
        with module.FileLock(team_lock, "team collaboration"):
            self.assertEqual(
                (team_lock.stat().st_dev, team_lock.stat().st_ino),
                team_lock_identity,
            )
            with self.assertRaises(module.CollaborationError):
                with module.FileLock(team_lock, "team collaboration"):
                    pass
            blocked = self.run_script(
                TEAM_SCRIPT, "prepare-cycle", "--cycle-id", "blocked_cycle",
                "--meeting-id", "blocked_meeting", "--prepared-by", "alpha",
                "--starts-at", "2026-07-17T11:00:00Z", "--ends-at", "2026-07-18T11:00:00Z",
                "--focus", "Must never be written while another operation owns the lock.",
            )
            self.assert_failed(blocked, "another team collaboration operation")
        self.assertFalse((self.root / "collaboration/cycles/blocked_cycle").exists())
        self.assertTrue(team_lock.is_file())
        self.assertEqual(
            (team_lock.stat().st_dev, team_lock.stat().st_ino),
            team_lock_identity,
        )
        with module.FileLock(team_lock, "team collaboration"):
            pass
        self.assertTrue(team_lock.is_file())
        lock_target = self.root / "knowledge/lock-target"
        lock_target.write_text("must remain unchanged\n", encoding="utf-8")
        linked_lock = self.root / "collaboration/.linked-team-lock"
        linked_lock.symlink_to(lock_target)
        with self.assertRaises(module.CollaborationError):
            with module.FileLock(linked_lock, "team collaboration"):
                pass
        self.assertEqual(
            lock_target.read_text(encoding="utf-8"),
            "must remain unchanged\n",
        )
        directory_lock = self.root / "collaboration/.directory-team-lock"
        directory_lock.mkdir()
        with self.assertRaises(module.CollaborationError):
            with module.FileLock(directory_lock, "team collaboration"):
                pass

        summary_lock = self.root / "knowledge/.control-room-summary.lock"
        before = (self.root / "knowledge/control_room_summary.json").read_bytes()
        summary_lock.write_text("pid=stale\n", encoding="ascii")
        summary_lock_identity = (
            summary_lock.stat().st_dev,
            summary_lock.stat().st_ino,
        )
        with module.FileLock(summary_lock, "Control Room summary"):
            with self.assertRaises(module.CollaborationError):
                module.update_summary(
                    self.root,
                    lambda summary: summary.__setitem__("pending_cycle_decision", True),
                )
        self.assertEqual((self.root / "knowledge/control_room_summary.json").read_bytes(), before)
        self.assertTrue(summary_lock.is_file())
        self.assertEqual(
            (summary_lock.stat().st_dev, summary_lock.stat().st_ino),
            summary_lock_identity,
        )

        summary = json.loads(before)
        summary["candidate_counts"]["LEAD"] = 99
        (self.root / "knowledge/control_room_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.assert_failed(self.run_script(TEAM_SCRIPT, "validate"), "digest binding")

    def test_repository_plan_and_status_are_side_effect_free_and_apply_is_hash_gated(self) -> None:
        # The pilot intentionally leaves handles undecided at generation. Exact
        # plan-time handles are therefore bound by member order without editing
        # the hash-bound LAB_PROFILE.
        self.profile["lab"]["collaboration"]["members"][0]["github_handle"] = None
        self.profile["lab"]["collaboration"]["members"][1]["github_handle"] = None
        (self.root / "LAB_PROFILE.json").write_text(
            json.dumps(self.profile, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        self.bootstrap()
        fake_tools = tempfile.TemporaryDirectory(prefix="team-fake-tools-")
        self.addCleanup(fake_tools.cleanup)
        fake_bin = Path(fake_tools.name)
        sentinel = fake_bin / "external-command-ran"
        for name in ("git", "gh"):
            executable = fake_bin / name
            executable.write_text(
                "#!/bin/sh\n" + f"touch '{sentinel}'\n" + "exit 97\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
        environment = {
            **self.environment,
            "PATH": str(fake_bin),
            "GH_TOKEN": "TEST_TOKEN_MUST_NEVER_BE_RECORDED",
        }
        planned = self.assert_ok(
            self.run_script(
                REPOSITORY_SCRIPT,
                "plan",
                "--plan-id", "private_plan",
                "--created-by", "alpha",
                "--created-at", "2026-07-17T13:00:00Z",
                "--visibility", "PRIVATE",
                "--repository-name", "research-pair",
                "--owner-handle", "alpha-gh",
                "--collaborator-handle", "beta-gh",
                "--default-branch", "main",
                "--git-author-name", "Alpha Researcher",
                "--git-author-email", "alpha@example.test",
                env=environment,
            )
        )
        self.assertEqual(planned["status"], "PLANNED")
        self.assertFalse(planned["external_actions_performed"])
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / ".git").exists())
        plan_path = self.root / planned["plan"]
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_value = json.loads(plan_text)
        self.assertEqual(
            plan_value["repository"]["owner"],
            {"member_id": "alpha", "handle": "alpha-gh"},
        )
        self.assertEqual(
            plan_value["repository"]["collaborators"],
            [{"member_id": "beta", "handle": "beta-gh"}],
        )
        self.assertNotIn("TEST_TOKEN_MUST_NEVER_BE_RECORDED", plan_text)

        status = self.assert_ok(self.run_script(REPOSITORY_SCRIPT, "status", env=environment))
        self.assertEqual(status["plan_count"], 1)
        self.assertFalse(status["external_actions_performed"])
        self.assertFalse(sentinel.exists())

        wrong_hash = "0" * 64
        self.assertNotEqual(wrong_hash, planned["plan_sha256"])
        denied = self.run_script(
            REPOSITORY_SCRIPT,
            "apply",
            "--plan", planned["plan"],
            "--approved-plan-sha256", wrong_hash,
            "--approved-by", "alpha",
            "--attempt-id", "wrong_hash_attempt",
            "--confirm-external-actions", "APPLY_EXACT_PLAN",
            env=environment,
        )
        self.assert_failed(denied, "does not match")
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / ".git").exists())
        self.assertFalse(any((self.root / "collaboration/repository/receipts").glob("*.json")))

        public = self.assert_ok(
            self.run_script(
                REPOSITORY_SCRIPT,
                "plan",
                "--plan-id", "public_plan",
                "--created-by", "alpha",
                "--created-at", "2026-07-17T13:10:00Z",
                "--visibility", "PUBLIC",
                "--repository-name", "research-pair-public",
                "--owner-handle", "alpha-gh",
                "--collaborator-handle", "beta-gh",
                "--git-author-name", "Alpha Researcher",
                "--git-author-email", "alpha@example.test",
                env=environment,
            )
        )
        denied_public = self.run_script(
            REPOSITORY_SCRIPT,
            "apply",
            "--plan", public["plan"],
            "--approved-plan-sha256", public["plan_sha256"],
            "--approved-by", "alpha",
            "--attempt-id", "missing_review_attempt",
            "--confirm-external-actions", "APPLY_EXACT_PLAN",
            env=environment,
        )
        self.assert_failed(denied_public, "requires an exact public disclosure review")
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / ".git").exists())
        combined = "".join(
            path.read_text(encoding="utf-8", errors="replace")
            for path in (self.root / "collaboration/repository").rglob("*")
            if path.is_file()
        )
        self.assertNotIn("TEST_TOKEN_MUST_NEVER_BE_RECORDED", combined)

        # Even a newly approved SHA cannot make semantically arbitrary edited
        # plan fields executable. The typed plan contract is independently
        # validated before executable discovery or any external command.
        tampered = json.loads(plan_path.read_text(encoding="utf-8"))
        tampered["repository"]["provider"] = "ARBITRARY_EXECUTOR"
        plan_path.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        tampered_sha = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        rejected_tamper = self.run_script(
            REPOSITORY_SCRIPT,
            "apply",
            "--plan", planned["plan"],
            "--approved-plan-sha256", tampered_sha,
            "--approved-by", "alpha",
            "--attempt-id", "tampered_plan_attempt",
            "--confirm-external-actions", "APPLY_EXACT_PLAN",
            env=environment,
        )
        self.assert_failed(rejected_tamper, "member-handle mapping")
        self.assertFalse(sentinel.exists())
        self.assertFalse((self.root / ".git").exists())


if __name__ == "__main__":
    unittest.main()
