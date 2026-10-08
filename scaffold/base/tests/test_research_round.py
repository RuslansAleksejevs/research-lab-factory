from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional


SOURCE_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = SOURCE_ROOT / "scripts/research_round.py"
MARKER = {
    "schema_version": 1,
    "protocol_version": 1,
    "actions": ["propose-rounds", "run-rounds", "collect-rounds"],
    "projection_path_template": "research/rounds/{round_id}/control_room_status.json",
}


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def plan_bound_projection_digest(root: Path, round_id: str, value: Dict[str, Any]) -> str:
    projection = {
        key: item
        for key, item in value.items()
        if key not in {"generated_at", "source_digest_sha256"}
    }
    plan_sha256 = hashlib.sha256(
        (root / f"research/rounds/{round_id}/approved_plan.json").read_bytes()
    ).hexdigest()
    basis = {
        "approved_plan_sha256": plan_sha256,
        "projection": projection,
    }
    return hashlib.sha256(
        json.dumps(
            basis,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


class ResearchRoundTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="research-round-test-")
        self.root = Path(self.temporary.name)
        self.guard_digests: Dict[tuple[str, str], str] = {}
        (self.root / "scripts").mkdir()
        (self.root / "research/checkpoints").mkdir(parents=True)
        (self.root / "knowledge").mkdir()
        (self.root / ".lab").mkdir()
        shutil.copy2(SCRIPT, self.root / "scripts/research_round.py")
        write_json(
            self.root / "LAB_PROFILE.json",
            {"schema_version": 1, "lab": {"id": "fixture-lab"}},
        )
        write_json(self.root / ".lab/control_room_actions.json", MARKER)
        (self.root / ".lab/control_room_actions.json").chmod(0o644)
        (self.root / "AGENTS.md").write_text("# Fixture policy\n", encoding="utf-8")
        (self.root / "AGENT_POLICY.md").write_text("# Fixture agent policy\n", encoding="utf-8")
        (self.root / "knowledge/research_state.yaml").write_text(
            '{"schema_version":1,"active_problem_ids":[]}\n',
            encoding="utf-8",
        )
        (self.root / "research/checkpoints/README.md").write_text(
            "Append-only checkpoints.\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_helper(
        self,
        *arguments: str,
        payload: Optional[Any] = None,
        raw: Optional[bytes] = None,
    ) -> subprocess.CompletedProcess[str]:
        if payload is not None and raw is not None:
            raise AssertionError("choose payload or raw")
        stdin = raw if raw is not None else (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else b""
        )
        return subprocess.run(
            [sys.executable, "-I", "-B", "scripts/research_round.py", *arguments],
            cwd=self.root,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
            timeout=20,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )

    def run_parallel_helpers(
        self,
        commands: list[list[str]],
        payloads: Optional[list[bytes]] = None,
    ) -> list[subprocess.CompletedProcess[bytes]]:
        if payloads is None:
            payloads = [b""] * len(commands)
        self.assertEqual(len(commands), len(payloads))
        processes = [
            subprocess.Popen(
                [sys.executable, "-I", "-B", "scripts/research_round.py", *command],
                cwd=self.root,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            for command in commands
        ]
        for process, payload in zip(processes, payloads):
            assert process.stdin is not None
            process.stdin.write(payload)
            process.stdin.close()
            process.stdin = None
        completed: list[subprocess.CompletedProcess[bytes]] = []
        for process, command in zip(processes, commands):
            stdout, stderr = process.communicate(timeout=20)
            completed.append(
                subprocess.CompletedProcess(
                    [sys.executable, "-I", "-B", "scripts/research_round.py", *command],
                    process.returncode,
                    stdout,
                    stderr,
                )
            )
        return completed

    def output(self, result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
        return json.loads(result.stdout.decode("utf-8"))

    def assert_ok(self, result: subprocess.CompletedProcess[str]) -> Dict[str, Any]:
        self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
        return self.output(result)

    def prepare(self, round_id: str = "round-1", scope: str = "Resolve the exact fixture target.") -> Dict[str, Any]:
        return self.assert_ok(
            self.run_helper(
                "prepare",
                "--round-id",
                round_id,
                "--request-id",
                f"request-{round_id}",
                payload={"scope": scope},
            )
        )

    def begin(self, round_id: str = "round-1", attempt_id: str = "attempt-1") -> Dict[str, Any]:
        result = self.assert_ok(
            self.run_helper(
                "begin",
                "--round-id",
                round_id,
                "--attempt-id",
                attempt_id,
            )
        )
        self.guard_digests[(round_id, attempt_id)] = result["guard_start_sha256"]
        return result

    def checkpoint(self, round_id: str, label: str) -> str:
        relative = f"research/checkpoints/20260718T120000Z-{round_id}-{label}.md"
        target = self.root / relative
        target.write_text(
            f"# Research Checkpoint\n\n- Round ID: `{round_id}`\n- Outcome: auditable fixture.\n",
            encoding="utf-8",
        )
        return relative

    def result_payload(
        self,
        round_id: str,
        status: str,
        checkpoint: Optional[str],
        *,
        changed_paths: Optional[list[str]] = None,
    ) -> Dict[str, Any]:
        return {
            "schema_version": 1,
            "round_id": round_id,
            "status": status,
            "summary": "The fixture attempt recorded an honest bounded result.",
            "changed_paths": changed_paths or ([] if checkpoint is None else [checkpoint]),
            "checkpoint_path": checkpoint,
            "blockers": [] if status == "COMPLETED" else ["One exact fixture blocker remains."],
            "next_step": "Run the next discriminating fixture check." if status != "CANCELLED" else "",
        }

    def finalize(
        self,
        payload: Dict[str, Any],
        attempt_id: str = "attempt-1",
    ) -> subprocess.CompletedProcess[str]:
        return self.run_helper(
            "finalize",
            "--round-id",
            str(payload["round_id"]),
            "--attempt-id",
            attempt_id,
            "--expected-guard-start-sha256",
            self.guard_digests[(str(payload["round_id"]), attempt_id)],
            payload=payload,
        )

    def test_prepare_begin_finalize_and_projection_contract(self) -> None:
        self.assertFalse((self.root / "research/rounds").exists())
        prepared = self.prepare("fleet.2026-07-18_01")
        self.assertEqual(prepared["status"], "PREPARED")
        plan_path = self.root / prepared["plan_path"]
        self.assertEqual(plan_path.stat().st_mode & 0o777, 0o444)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["model"], "gpt-5.6-sol")
        self.assertEqual(plan["reasoning_effort"], "ultra")
        self.assertEqual(plan["architecture_guard_policy_version"], 2)
        self.assertEqual(
            plan["scope_sha256"],
            hashlib.sha256(plan["scope"].encode("utf-8")).hexdigest(),
        )

        self.begin("fleet.2026-07-18_01")
        live_file = self.root / "research/fixture-note.md"
        live_file.write_text("allowed research state\n", encoding="utf-8")
        checkpoint = self.checkpoint("fleet.2026-07-18_01", "attempt-1")
        finalized = self.assert_ok(
            self.finalize(
                self.result_payload(
                    "fleet.2026-07-18_01",
                    "COMPLETED",
                    checkpoint,
                    changed_paths=["research/fixture-note.md", checkpoint],
                )
            )
        )
        self.assertEqual(finalized["status"], "COMPLETED")
        projection_path = self.root / finalized["projection_path"]
        self.assertLessEqual(projection_path.stat().st_size, 32 * 1024)
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        self.assertEqual(projection["action_id"], "run-rounds.v1")
        self.assertEqual(
            set(projection),
            {
                "schema_version",
                "round_id",
                "lab_id",
                "action_id",
                "action_version",
                "generated_at",
                "status",
                "summary",
                "changed_paths",
                "checkpoint_path",
                "blockers",
                "next_step",
                "source_digest_sha256",
            },
        )
        self.assertEqual(
            projection["source_digest_sha256"],
            plan_bound_projection_digest(
                self.root,
                "fleet.2026-07-18_01",
                projection,
            ),
        )
        validation = self.assert_ok(self.run_helper("validate"))
        self.assertEqual(validation["status"], "PASS")

    def test_prepare_is_idempotent_and_scope_bound(self) -> None:
        first = self.prepare()
        second = self.prepare()
        self.assertEqual(first["plan_sha256"], second["plan_sha256"])
        self.assertEqual(second["status"], "UNCHANGED")
        conflict = self.run_helper(
            "prepare",
            "--round-id",
            "round-1",
            "--request-id",
            "request-round-1",
            payload={"scope": "A different scope."},
        )
        self.assertEqual(conflict.returncode, 2)
        self.assertIn("different immutable approved plan", self.output(conflict)["error"])

    def test_concurrent_prepare_publishes_one_complete_plan(self) -> None:
        command = [
            "prepare",
            "--round-id",
            "round-race",
            "--request-id",
            "request-round-race",
        ]
        payload = json.dumps({"scope": "Exercise the publication race."}).encode("utf-8")
        completed = self.run_parallel_helpers([command, command], [payload, payload])
        for result in completed:
            self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
        responses = [json.loads(result.stdout.decode("utf-8")) for result in completed]
        self.assertEqual({item["status"] for item in responses}, {"PREPARED", "UNCHANGED"})
        self.assertEqual(len({item["plan_sha256"] for item in responses}), 1)

        plan_path = self.root / "research/rounds/round-race/approved_plan.json"
        self.assertEqual(plan_path.stat().st_mode & 0o777, 0o444)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(plan["round_id"], "round-race")
        self.assertEqual(plan["scope"], "Exercise the publication race.")
        self.assertFalse(any(plan_path.parent.glob(".approved_plan.json.create-*")))

    def test_concurrent_begin_and_cancel_transitions_remain_consistent(self) -> None:
        self.prepare("transition-race")
        begin_commands = [
            ["begin", "--round-id", "transition-race", "--attempt-id", "attempt-a"],
            ["begin", "--round-id", "transition-race", "--attempt-id", "attempt-b"],
        ]
        begun = self.run_parallel_helpers(begin_commands)
        self.assertEqual(sorted(item.returncode for item in begun), [0, 2])
        self.assertEqual(
            len(list((self.root / "research/rounds/transition-race/attempts").glob("*/guard_start.json"))),
            1,
        )
        self.assertEqual(
            self.assert_ok(self.run_helper("validate", "--round-id", "transition-race"))["status"],
            "PASS",
        )
        status = self.assert_ok(self.run_helper("status", "--round-id", "transition-race"))
        self.assertEqual(status["status"], "RUNNING")
        self.assertFalse((self.root / "research/rounds/transition-race/.transition.lock").exists())

        active_attempt = status["current_attempt_id"]
        digest = json.loads(
            next(item.stdout for item in begun if item.returncode == 0).decode("utf-8")
        )["guard_start_sha256"]
        cancelled = self.assert_ok(
            self.run_helper(
                "cancel",
                "--round-id",
                "transition-race",
                "--expected-guard-start-sha256",
                digest,
            )
        )
        self.assertEqual(cancelled["attempt_id"], active_attempt)

        self.prepare("begin-cancel-race")
        raced = self.run_parallel_helpers(
            [
                ["begin", "--round-id", "begin-cancel-race", "--attempt-id", "attempt-1"],
                ["cancel", "--round-id", "begin-cancel-race"],
            ]
        )
        self.assertEqual(raced[0].returncode, 0)
        self.assertIn(raced[1].returncode, {0, 2})
        self.assertEqual(
            self.assert_ok(self.run_helper("validate", "--round-id", "begin-cancel-race"))["status"],
            "PASS",
        )
        final_status = self.assert_ok(
            self.run_helper("status", "--round-id", "begin-cancel-race")
        )
        self.assertEqual(final_status["status"], "RUNNING")

    def test_concurrent_duplicate_finalize_is_idempotent(self) -> None:
        self.prepare("finalize-race")
        begin = self.begin("finalize-race", "attempt-1")
        checkpoint = self.checkpoint("finalize-race", "complete")
        payload = json.dumps(
            self.result_payload("finalize-race", "COMPLETED", checkpoint),
            ensure_ascii=False,
        ).encode("utf-8")
        command = [
            "finalize",
            "--round-id",
            "finalize-race",
            "--attempt-id",
            "attempt-1",
            "--expected-guard-start-sha256",
            begin["guard_start_sha256"],
        ]
        completed = self.run_parallel_helpers([command, command], [payload, payload])
        self.assertEqual([item.returncode for item in completed], [0, 0])
        responses = [json.loads(item.stdout.decode("utf-8")) for item in completed]
        self.assertTrue(all(item["status"] == "COMPLETED" for item in responses))
        self.assertEqual(responses[0]["projection"], responses[1]["projection"])
        self.assertEqual(
            len({item["projection"]["source_digest_sha256"] for item in responses}),
            1,
        )
        self.assertEqual(
            self.assert_ok(self.run_helper("validate", "--round-id", "finalize-race"))["status"],
            "PASS",
        )

    def test_transition_lock_timeout_and_process_death_release(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_lock_round", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root
        module.TRANSITION_LOCK_TIMEOUT_SECONDS = 0.075
        module.TRANSITION_LOCK_POLL_SECONDS = 0.005

        holder = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                (
                    "import fcntl,os,signal,sys;"
                    "fd=os.open(sys.argv[1],os.O_RDONLY);"
                    "fcntl.flock(fd,fcntl.LOCK_EX);"
                    "print('LOCKED',flush=True);"
                    "signal.pause()"
                ),
                str(self.root / ".lab/control_room_actions.json"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert holder.stdout is not None
            self.assertEqual(holder.stdout.readline().strip(), "LOCKED")
            with self.assertRaisesRegex(module.ResearchRoundError, "timed out acquiring"):
                with module.laboratory_transition_lock():
                    pass
        finally:
            holder.terminate()
            holder.communicate(timeout=5)
        with module.laboratory_transition_lock():
            pass
        self.assertFalse((self.root / "research/rounds/.transition.lock").exists())

    def test_duplicate_key_oversize_and_identifier_rejection(self) -> None:
        duplicate = self.run_helper(
            "prepare",
            "--round-id",
            "round-1",
            "--request-id",
            "request-1",
            raw=b'{"scope":"first","scope":"second"}',
        )
        self.assertEqual(duplicate.returncode, 2)
        self.assertIn("duplicate JSON key", self.output(duplicate)["error"])
        oversized = self.run_helper(
            "prepare",
            "--round-id",
            "round-1",
            "--request-id",
            "request-1",
            payload={"scope": "x" * 17_000},
        )
        self.assertEqual(oversized.returncode, 2)
        invalid = self.run_helper(
            "prepare",
            "--round-id",
            "../round",
            "--request-id",
            "request-1",
            payload={"scope": "scope"},
        )
        self.assertEqual(invalid.returncode, 2)
        self.assertFalse((self.root.parent / "round").exists())

    def test_checkpoint_is_mandatory_and_append_only(self) -> None:
        self.prepare()
        self.begin()
        missing = self.finalize(self.result_payload("round-1", "BLOCKED", None))
        self.assertEqual(missing.returncode, 2)
        self.assertIn("requires an append-only checkpoint", self.output(missing)["error"])
        checkpoint = self.checkpoint("round-1", "blocked")
        success = self.assert_ok(
            self.finalize(self.result_payload("round-1", "BLOCKED", checkpoint))
        )
        self.assertEqual(success["status"], "BLOCKED")

        self.begin("round-1", "attempt-2")
        reused = self.finalize(
            self.result_payload("round-1", "COMPLETED", checkpoint),
            attempt_id="attempt-2",
        )
        self.assertEqual(reused.returncode, 2)
        self.assertIn("existed before this attempt", self.output(reused)["error"])

    def test_checkpoint_hardlink_cannot_satisfy_new_inode_gate(self) -> None:
        self.prepare("hardlink-round")
        self.begin("hardlink-round", "attempt-1")
        original = self.checkpoint("hardlink-round", "blocked")
        self.assert_ok(
            self.finalize(
                self.result_payload("hardlink-round", "BLOCKED", original),
                attempt_id="attempt-1",
            )
        )
        self.begin("hardlink-round", "attempt-2")
        guard_start = json.loads(
            (
                self.root
                / "research/rounds/hardlink-round/attempts/attempt-2/guard_start.json"
            ).read_text(encoding="utf-8")
        )
        original_record = next(
            item for item in guard_start["checkpoint_inventory"] if item["path"] == original
        )
        self.assertTrue({"device", "inode", "nlink"}.issubset(original_record))
        self.assertEqual(original_record["nlink"], 1)
        linked = "research/checkpoints/20260718T120000Z-hardlink-round-linked.md"
        os.link(self.root / original, self.root / linked)
        self.assertEqual((self.root / original).stat().st_ino, (self.root / linked).stat().st_ino)
        rejected = self.finalize(
            self.result_payload("hardlink-round", "COMPLETED", linked),
            attempt_id="attempt-2",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("single-link regular file", self.output(rejected)["error"])
        self.assertFalse(
            (
                self.root
                / "research/rounds/hardlink-round/attempts/attempt-2/guard_end.json"
            ).exists()
        )

    def test_retry_preserves_prior_attempt_and_plan(self) -> None:
        self.prepare()
        plan_before = (self.root / "research/rounds/round-1/approved_plan.json").read_bytes()
        self.begin()
        checkpoint_one = self.checkpoint("round-1", "blocked")
        self.assert_ok(
            self.finalize(self.result_payload("round-1", "BLOCKED", checkpoint_one))
        )
        result_one = (
            self.root / "research/rounds/round-1/attempts/attempt-1/result.json"
        ).read_bytes()

        self.begin("round-1", "attempt-2")
        self.assertFalse(
            (self.root / "research/rounds/round-1/control_room_status.json").exists()
        )
        checkpoint_two = self.checkpoint("round-1", "complete")
        second = self.assert_ok(
            self.finalize(
                self.result_payload("round-1", "COMPLETED", checkpoint_two),
                attempt_id="attempt-2",
            )
        )
        self.assertEqual(second["status"], "COMPLETED")
        self.assertEqual(
            (self.root / "research/rounds/round-1/approved_plan.json").read_bytes(),
            plan_before,
        )
        self.assertEqual(
            (self.root / "research/rounds/round-1/attempts/attempt-1/result.json").read_bytes(),
            result_one,
        )

    def test_architecture_drift_forces_failed_projection(self) -> None:
        self.prepare()
        self.begin()
        (self.root / "AGENTS.md").write_text("unauthorized architecture edit\n", encoding="utf-8")
        checkpoint = self.checkpoint("round-1", "drift")
        finished = self.assert_ok(
            self.finalize(self.result_payload("round-1", "COMPLETED", checkpoint))
        )
        self.assertEqual(finished["status"], "FAILED")
        projection = finished["projection"]
        self.assertTrue(any("architecture/policy drift" in item for item in projection["blockers"]))
        guard = json.loads(
            (
                self.root
                / "research/rounds/round-1/attempts/attempt-1/guard_end.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(guard["guard_status"], "DRIFT_DETECTED")
        self.assertIn(
            {"path": "AGENTS.md", "change": "CHANGED"},
            guard["architecture_changes"],
        )

    def test_safe_ds_store_is_ignored_across_guard_inventories(self) -> None:
        protected = self.root / "nested/policy/.DS_Store"
        checkpoint_metadata = self.root / "research/checkpoints/cache/.DS_Store"
        round_metadata = self.root / "research/rounds/prior/cache/.DS_Store"
        added_protected = self.root / "nested/added/.DS_Store"
        added_checkpoint = self.root / "research/checkpoints/added/.DS_Store"
        added_round = self.root / "research/rounds/prior/added/.DS_Store"
        for path in (
            protected,
            checkpoint_metadata,
            round_metadata,
            added_protected,
            added_checkpoint,
            added_round,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
        for path in (protected, checkpoint_metadata, round_metadata):
            path.write_bytes(b"finder-before")

        self.prepare("ds-store-round")
        begun = self.begin("ds-store-round", "attempt-1")
        guard_start = json.loads(
            (
                self.root
                / "research/rounds/ds-store-round/attempts/attempt-1/guard_start.json"
            ).read_text(encoding="utf-8")
        )
        for field in (
            "protected_inventory",
            "checkpoint_inventory",
            "round_control_inventory",
        ):
            self.assertFalse(
                any(
                    Path(record["path"]).name == ".DS_Store"
                    for record in guard_start[field]
                )
            )

        for path in (protected, checkpoint_metadata, round_metadata):
            path.write_bytes(b"finder-after")
        for path in (added_protected, added_checkpoint, added_round):
            path.write_bytes(b"finder-added")
        (self.root / ".DS_Store").write_bytes(b"finder-root-added")
        (
            self.root / "research/rounds/ds-store-round/attempts/.DS_Store"
        ).write_bytes(b"finder-attempt-list")
        (self.root / "research/rounds/.DS_Store").write_bytes(
            b"finder-round-list"
        )
        checkpoint = self.checkpoint("ds-store-round", "terminal")
        finished = self.assert_ok(
            self.finalize(
                self.result_payload("ds-store-round", "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        self.assertEqual(finished["status"], "COMPLETED")
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", "ds-store-round")
            )["status"],
            "PASS",
        )
        self.assertEqual(
            begun["guard_start_sha256"],
            self.guard_digests[("ds-store-round", "attempt-1")],
        )

    def test_ds_store_unsafe_forms_remain_fail_closed(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_ds_store", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root
        candidate = self.root / ".DS_Store"

        candidate.mkdir()
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module.protected_inventory()
        candidate.rmdir()

        try:
            candidate.symlink_to(self.root / "AGENTS.md")
        except OSError:
            self.skipTest("symlinks unavailable")
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module.protected_inventory()
        candidate.unlink()

        os.mkfifo(candidate)
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module.protected_inventory()
        candidate.unlink()

        source = self.root / "ds-store-hardlink-source"
        source.write_bytes(b"finder")
        try:
            os.link(source, candidate)
        except OSError:
            self.skipTest("hard links unavailable")
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module.protected_inventory()
        candidate.unlink()
        source.unlink()

        candidate.write_bytes(b"finder")
        info_fields = list(candidate.lstat())
        info_fields[2] += 1
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module._ignore_safe_macos_metadata(
                candidate,
                ".DS_Store",
                os.stat_result(info_fields),
                self.root.lstat().st_dev,
            )

    def test_other_dotfile_with_ds_store_prefix_remains_protected(self) -> None:
        lookalike = self.root / "nested/.DS_Store.keep"
        lookalike.parent.mkdir()
        lookalike.write_bytes(b"before")
        self.prepare("ds-store-lookalike")
        self.begin("ds-store-lookalike", "attempt-1")
        lookalike.write_bytes(b"after")
        checkpoint = self.checkpoint("ds-store-lookalike", "terminal")
        finished = self.assert_ok(
            self.finalize(
                self.result_payload("ds-store-lookalike", "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        self.assertEqual(finished["status"], "FAILED")
        self.assertIn(
            {"path": "nested/.DS_Store.keep", "change": "CHANGED"},
            json.loads(
                (
                    self.root
                    / "research/rounds/ds-store-lookalike/attempts/attempt-1/guard_end.json"
                ).read_text(encoding="utf-8")
            )["architecture_changes"],
        )

    def test_ds_store_topology_enumerations_validate_before_filtering(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location(
            "fixture_ds_store_topology", module_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root
        self.prepare("ds-store-topology")

        attempts_metadata = (
            self.root / "research/rounds/ds-store-topology/attempts/.DS_Store"
        )
        attempts_metadata.write_bytes(b"finder")
        self.assertEqual(module._attempt_ids("ds-store-topology"), [])
        attempts_metadata.unlink()
        attempts_metadata.mkdir()
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module._attempt_ids("ds-store-topology")
        attempts_metadata.rmdir()

        rounds_metadata = self.root / "research/rounds/.DS_Store"
        rounds_metadata.write_bytes(b"finder")
        validated = module._command_validate_locked(
            module.argparse.Namespace(round_id=None)
        )
        self.assertEqual(validated["status"], "PASS")
        rounds_metadata.unlink()
        os.mkfifo(rounds_metadata)
        with self.assertRaisesRegex(module.ResearchRoundError, "unsafe .DS_Store"):
            module._command_validate_locked(module.argparse.Namespace(round_id=None))

    def test_immutable_plan_mode_drift_forces_failed_projection(self) -> None:
        self.prepare()
        self.begin()
        plan = self.root / "research/rounds/round-1/approved_plan.json"
        plan.chmod(0o644)
        checkpoint = self.checkpoint("round-1", "plan-mode-drift")
        finished = self.assert_ok(
            self.finalize(self.result_payload("round-1", "COMPLETED", checkpoint))
        )
        self.assertEqual(finished["status"], "FAILED")
        self.assertTrue(
            any("immutable approved plan changed" in item for item in finished["projection"]["blockers"])
        )

    def test_old_checkpoint_mutation_forces_failed_projection(self) -> None:
        old = self.root / "research/checkpoints/old.md"
        old.write_text("old immutable checkpoint\n", encoding="utf-8")
        self.prepare()
        self.begin()
        old.write_text("rewritten checkpoint\n", encoding="utf-8")
        checkpoint = self.checkpoint("round-1", "new")
        finished = self.assert_ok(
            self.finalize(self.result_payload("round-1", "COMPLETED", checkpoint))
        )
        self.assertEqual(finished["status"], "FAILED")
        self.assertTrue(
            any("pre-existing checkpoint drift" in item for item in finished["projection"]["blockers"])
        )

    def test_prior_attempt_mutation_forces_failed_projection(self) -> None:
        self.prepare()
        self.begin()
        checkpoint_one = self.checkpoint("round-1", "blocked")
        self.assert_ok(
            self.finalize(self.result_payload("round-1", "BLOCKED", checkpoint_one))
        )
        self.begin("round-1", "attempt-2")
        prior_result = self.root / "research/rounds/round-1/attempts/attempt-1/result.json"
        prior_result.chmod(0o644)
        prior_result.write_text("tampered prior result\n", encoding="utf-8")
        checkpoint_two = self.checkpoint("round-1", "retry")
        finished = self.assert_ok(
            self.finalize(
                self.result_payload("round-1", "COMPLETED", checkpoint_two),
                attempt_id="attempt-2",
            )
        )
        self.assertEqual(finished["status"], "FAILED")
        self.assertTrue(
            any("prior round-control drift" in item for item in finished["projection"]["blockers"])
        )

    def test_finalize_requires_external_guard_start_binding(self) -> None:
        self.prepare()
        self.begin()
        checkpoint = self.checkpoint("round-1", "bound")
        payload = self.result_payload("round-1", "COMPLETED", checkpoint)
        wrong = self.run_helper(
            "finalize",
            "--round-id",
            "round-1",
            "--attempt-id",
            "attempt-1",
            "--expected-guard-start-sha256",
            "0" * 64,
            payload=payload,
        )
        self.assertEqual(wrong.returncode, 2)
        self.assertIn("external digest mismatch", self.output(wrong)["error"])
        self.assertFalse(
            (self.root / "research/rounds/round-1/attempts/attempt-1/guard_end.json").exists()
        )
        self.assertEqual(self.assert_ok(self.finalize(payload))["status"], "COMPLETED")

    def test_architecture_path_and_unsafe_result_path_are_rejected(self) -> None:
        self.prepare()
        self.begin()
        checkpoint = self.checkpoint("round-1", "safe")
        architecture = self.finalize(
            self.result_payload(
                "round-1",
                "COMPLETED",
                checkpoint,
                changed_paths=["AGENTS.md", checkpoint],
            )
        )
        self.assertEqual(architecture.returncode, 2)
        self.assertIn("architecture/policy protected", self.output(architecture)["error"])
        traversal_payload = self.result_payload("round-1", "COMPLETED", checkpoint)
        traversal_payload["changed_paths"] = ["research/../AGENTS.md"]
        traversal = self.finalize(traversal_payload)
        self.assertEqual(traversal.returncode, 2)
        self.assertIn("canonical relative path", self.output(traversal)["error"])

    def test_checkpoint_must_appear_exactly_once_in_changed_paths(self) -> None:
        self.prepare()
        self.begin()
        checkpoint = self.checkpoint("round-1", "omitted")
        omitted = self.finalize(
            self.result_payload(
                "round-1",
                "COMPLETED",
                checkpoint,
                changed_paths=["research/fixture-note.md"],
            )
        )
        self.assertEqual(omitted.returncode, 2)
        self.assertIn("exactly once in changed_paths", self.output(omitted)["error"])

    def test_symlink_is_rejected_before_attempt(self) -> None:
        self.prepare()
        (self.root / "architecture-link").symlink_to(self.root / "AGENTS.md")
        begin = self.run_helper(
            "begin",
            "--round-id",
            "round-1",
            "--attempt-id",
            "attempt-1",
        )
        self.assertEqual(begin.returncode, 2)
        self.assertIn("symlink is forbidden", self.output(begin)["error"])

    def test_cancel_queued_is_durable_idempotent_and_retryable(self) -> None:
        self.prepare()
        first = self.assert_ok(self.run_helper("cancel", "--round-id", "round-1"))
        second = self.assert_ok(self.run_helper("cancel", "--round-id", "round-1"))
        self.assertEqual(first["status"], "CANCELLED")
        self.assertEqual(second["status"], "CANCELLED")
        begin = self.begin("round-1", "attempt-1")
        self.assertEqual(begin["status"], "RUNNING")

    def test_cancel_active_attempt_requires_external_guard_binding(self) -> None:
        self.prepare()
        begin = self.begin()
        missing = self.run_helper("cancel", "--round-id", "round-1")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("requires --expected-guard-start-sha256", self.output(missing)["error"])
        cancelled = self.assert_ok(
            self.run_helper(
                "cancel",
                "--round-id",
                "round-1",
                "--expected-guard-start-sha256",
                begin["guard_start_sha256"],
            )
        )
        self.assertEqual(cancelled["status"], "CANCELLED")

    def test_recover_active_attempt_is_durable_idempotent_cancel(self) -> None:
        self.prepare("recover-active")
        self.begin("recover-active", "attempt-1")

        recovered = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-active")
        )
        self.assertEqual(recovered["status"], "CANCELLED")
        self.assertEqual(recovered["recovery"], "RECOVERED")
        self.assertEqual(
            recovered["repairs"],
            ["FINALIZED_ACTIVE_ATTEMPT:attempt-1"],
        )
        attempt = self.root / "research/rounds/recover-active/attempts/attempt-1"
        guard_end_path = attempt / "guard_end.json"
        result_path = attempt / "result.json"
        projection_path = self.root / recovered["projection_path"]
        self.assertEqual(guard_end_path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(result_path.stat().st_mode & 0o777, 0o444)
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "CANCELLED")
        self.assertEqual(result["changed_paths"], [])
        self.assertIsNone(result["checkpoint_path"])
        immutable_before = {
            "guard_end": guard_end_path.read_bytes(),
            "result": result_path.read_bytes(),
            "projection": projection_path.read_bytes(),
        }

        unchanged = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-active")
        )
        self.assertEqual(unchanged["recovery"], "UNCHANGED")
        self.assertEqual(unchanged["repairs"], [])
        self.assertEqual(guard_end_path.read_bytes(), immutable_before["guard_end"])
        self.assertEqual(result_path.read_bytes(), immutable_before["result"])
        self.assertEqual(projection_path.read_bytes(), immutable_before["projection"])
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", "recover-active")
            )["status"],
            "PASS",
        )

    def test_recover_removes_bound_stale_projection_then_cancels_active_retry(self) -> None:
        self.prepare("recover-stale")
        self.begin("recover-stale", "attempt-1")
        first_checkpoint = self.checkpoint("recover-stale", "blocked")
        self.assert_ok(
            self.finalize(
                self.result_payload("recover-stale", "BLOCKED", first_checkpoint),
                attempt_id="attempt-1",
            )
        )
        projection_path = self.root / "research/rounds/recover-stale/control_room_status.json"
        stale_projection = projection_path.read_bytes()

        self.begin("recover-stale", "attempt-2")
        self.assertFalse(projection_path.exists())
        projection_path.write_bytes(stale_projection)
        projection_path.chmod(0o644)

        recovered = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-stale")
        )
        self.assertEqual(recovered["status"], "CANCELLED")
        self.assertEqual(
            recovered["repairs"],
            [
                "REMOVED_STALE_PROJECTION",
                "FINALIZED_ACTIVE_ATTEMPT:attempt-2",
            ],
        )
        terminal = json.loads(
            (
                self.root
                / "research/rounds/recover-stale/attempts/attempt-2/guard_end.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(terminal["terminal_sequence"], 2)
        self.assertEqual(terminal["effective_result"]["status"], "CANCELLED")
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", "recover-stale")
            )["status"],
            "PASS",
        )

    def test_recover_republishes_latest_terminal_projection_with_checkpoint_binding(self) -> None:
        self.prepare("recover-projection")
        self.begin("recover-projection", "attempt-1")
        checkpoint = self.checkpoint("recover-projection", "complete")
        self.assert_ok(
            self.finalize(
                self.result_payload(
                    "recover-projection",
                    "COMPLETED",
                    checkpoint,
                    changed_paths=["research/fixture-note.md", checkpoint],
                ),
                attempt_id="attempt-1",
            )
        )
        projection_path = (
            self.root / "research/rounds/recover-projection/control_room_status.json"
        )
        projection_path.unlink()

        recovered = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-projection")
        )
        self.assertEqual(recovered["status"], "COMPLETED")
        self.assertEqual(recovered["repairs"], ["PUBLISHED_TERMINAL_PROJECTION"])
        projection = recovered["projection"]
        self.assertEqual(projection["checkpoint_path"], checkpoint)
        self.assertEqual(projection["changed_paths"].count(checkpoint), 1)
        guard_end = json.loads(
            (
                self.root
                / "research/rounds/recover-projection/attempts/attempt-1/guard_end.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(guard_end["checkpoint_record"]["path"], checkpoint)
        projection_before = projection_path.read_bytes()
        unchanged = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-projection")
        )
        self.assertEqual(unchanged["recovery"], "UNCHANGED")
        self.assertEqual(projection_path.read_bytes(), projection_before)
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", "recover-projection")
            )["status"],
            "PASS",
        )

    def test_recover_completes_guard_end_only_terminal_chain(self) -> None:
        self.prepare("recover-result")
        self.begin("recover-result", "attempt-1")
        checkpoint = self.checkpoint("recover-result", "blocked")
        self.assert_ok(
            self.finalize(
                self.result_payload("recover-result", "BLOCKED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        result_path = (
            self.root
            / "research/rounds/recover-result/attempts/attempt-1/result.json"
        )
        projection_path = (
            self.root / "research/rounds/recover-result/control_room_status.json"
        )
        result_path.unlink()
        projection_path.unlink()

        recovered = self.assert_ok(
            self.run_helper("recover", "--round-id", "recover-result")
        )
        self.assertEqual(
            recovered["repairs"],
            ["CREATED_RESULT:attempt-1", "PUBLISHED_TERMINAL_PROJECTION"],
        )
        restored = json.loads(result_path.read_text(encoding="utf-8"))
        guard_end = json.loads(
            (
                self.root
                / "research/rounds/recover-result/attempts/attempt-1/guard_end.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(restored, guard_end["effective_result"])
        self.assertEqual(restored["changed_paths"].count(checkpoint), 1)
        self.assertEqual(result_path.stat().st_mode & 0o777, 0o444)
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", "recover-result")
            )["status"],
            "PASS",
        )

    def test_recover_rejects_ambiguous_active_attempts_before_writing(self) -> None:
        self.prepare("recover-ambiguous")
        self.begin("recover-ambiguous", "attempt-1")
        first_path = (
            self.root
            / "research/rounds/recover-ambiguous/attempts/attempt-1/guard_start.json"
        )
        second_path = (
            self.root
            / "research/rounds/recover-ambiguous/attempts/attempt-2/guard_start.json"
        )
        second = json.loads(first_path.read_text(encoding="utf-8"))
        second["attempt_id"] = "attempt-2"
        write_json(second_path, second)
        second_path.chmod(0o444)

        rejected = self.run_helper(
            "recover", "--round-id", "recover-ambiguous"
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("ambiguous multiple active attempts", self.output(rejected)["error"])
        for attempt_id in ("attempt-1", "attempt-2"):
            attempt = (
                self.root
                / f"research/rounds/recover-ambiguous/attempts/{attempt_id}"
            )
            self.assertFalse((attempt / "guard_end.json").exists())
            self.assertFalse((attempt / "result.json").exists())

    def test_recover_rejects_result_without_guard_end_before_writing(self) -> None:
        self.prepare("recover-result-only")
        self.begin("recover-result-only", "attempt-1")
        attempt = (
            self.root
            / "research/rounds/recover-result-only/attempts/attempt-1"
        )
        forged_result = self.result_payload(
            "recover-result-only", "CANCELLED", None
        )
        write_json(attempt / "result.json", forged_result)
        (attempt / "result.json").chmod(0o444)

        rejected = self.run_helper(
            "recover", "--round-id", "recover-result-only"
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("result exists without immutable guard_end", self.output(rejected)["error"])
        self.assertFalse((attempt / "guard_end.json").exists())
        self.assertFalse(
            (
                self.root
                / "research/rounds/recover-result-only/control_room_status.json"
            ).exists()
        )

    def test_recover_rejects_unbound_projection_before_writing(self) -> None:
        self.prepare("recover-unbound")
        self.begin("recover-unbound", "attempt-1")
        projection = {
            "schema_version": 1,
            "round_id": "recover-unbound",
            "lab_id": "fixture-lab",
            "action_id": "run-rounds.v1",
            "action_version": "1.0.0",
            "generated_at": "2026-07-18T12:00:00Z",
            "status": "FAILED",
            "summary": "A valid but unbound forged projection.",
            "changed_paths": [],
            "checkpoint_path": None,
            "blockers": ["No immutable terminal binds this projection."],
            "next_step": "",
            "source_digest_sha256": "",
        }
        projection["source_digest_sha256"] = plan_bound_projection_digest(
            self.root,
            "recover-unbound",
            projection,
        )
        projection_path = (
            self.root / "research/rounds/recover-unbound/control_room_status.json"
        )
        write_json(projection_path, projection)
        projection_before = projection_path.read_bytes()

        rejected = self.run_helper("recover", "--round-id", "recover-unbound")
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("unbound projection", self.output(rejected)["error"])
        self.assertEqual(projection_path.read_bytes(), projection_before)
        attempt = self.root / "research/rounds/recover-unbound/attempts/attempt-1"
        self.assertFalse((attempt / "guard_end.json").exists())
        self.assertFalse((attempt / "result.json").exists())

    def test_recover_refuses_changed_terminal_checkpoint(self) -> None:
        self.prepare("recover-checkpoint-drift")
        self.begin("recover-checkpoint-drift", "attempt-1")
        checkpoint = self.checkpoint("recover-checkpoint-drift", "complete")
        self.assert_ok(
            self.finalize(
                self.result_payload(
                    "recover-checkpoint-drift", "COMPLETED", checkpoint
                ),
                attempt_id="attempt-1",
            )
        )
        projection_path = (
            self.root
            / "research/rounds/recover-checkpoint-drift/control_room_status.json"
        )
        projection_path.unlink()
        (self.root / checkpoint).write_text(
            "# Research Checkpoint\n\n"
            "- Round ID: `recover-checkpoint-drift`\n"
            "- Tampered after terminal publication.\n",
            encoding="utf-8",
        )

        rejected = self.run_helper(
            "recover", "--round-id", "recover-checkpoint-drift"
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("terminal checkpoint changed", self.output(rejected)["error"])
        self.assertFalse(projection_path.exists())

    def rebind_terminal_device(
        self,
        round_id: str,
        attempt_id: str,
        *,
        checkpoint_device_delta: int = 0,
        root_inode_delta: int = 0,
    ) -> None:
        attempt = self.root / f"research/rounds/{round_id}/attempts/{attempt_id}"
        guard_start_path = attempt / "guard_start.json"
        guard_end_path = attempt / "guard_end.json"
        guard_start = json.loads(guard_start_path.read_text(encoding="utf-8"))
        current_device = guard_start["root_identity"]["device"]
        historical_device = current_device + 104729
        guard_start["root_identity"]["device"] = historical_device
        guard_start["root_identity"]["inode"] += root_inode_delta
        for prefix in ("protected", "checkpoint", "round_control"):
            inventory = guard_start[f"{prefix}_inventory"]
            for record in inventory:
                if record["type"] == "file":
                    self.assertEqual(record["device"], current_device)
                    record["device"] = historical_device
            guard_start[f"{prefix}_inventory_sha256"] = hashlib.sha256(
                json.dumps(
                    inventory,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
        guard_start_path.chmod(0o644)
        write_json(guard_start_path, guard_start)
        guard_start_path.chmod(0o444)

        guard_end = json.loads(guard_end_path.read_text(encoding="utf-8"))
        guard_end["root_identity"] = dict(guard_start["root_identity"])
        guard_end["guard_start_sha256"] = hashlib.sha256(
            guard_start_path.read_bytes()
        ).hexdigest()
        guard_end["protected_inventory_sha256"] = guard_start[
            "protected_inventory_sha256"
        ]
        guard_end["round_control_inventory_sha256"] = guard_start[
            "round_control_inventory_sha256"
        ]
        guard_end["checkpoint_record"]["device"] = (
            historical_device + checkpoint_device_delta
        )
        guard_end_path.chmod(0o644)
        write_json(guard_end_path, guard_end)
        guard_end_path.chmod(0o444)

    def test_recover_accepts_coherent_apfs_terminal_device_rebinding(self) -> None:
        round_id = "recover-device-rebinding"
        self.prepare(round_id)
        self.begin(round_id, "attempt-1")
        checkpoint = self.checkpoint(round_id, "complete")
        self.assert_ok(
            self.finalize(
                self.result_payload(round_id, "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        self.rebind_terminal_device(round_id, "attempt-1")
        projection_path = (
            self.root / f"research/rounds/{round_id}/control_room_status.json"
        )
        projection_path.unlink()

        recovered = self.assert_ok(
            self.run_helper("recover", "--round-id", round_id)
        )
        self.assertEqual(recovered["status"], "COMPLETED")
        validated = self.assert_ok(
            self.run_helper("validate", "--round-id", round_id)
        )
        self.assertEqual(validated["errors"], [])

    def test_validate_rejects_incoherent_terminal_device_rebinding(self) -> None:
        cases = (
            ("checkpoint-device", {"checkpoint_device_delta": 1}),
            ("root-inode", {"root_inode_delta": 1}),
        )
        for label, mutations in cases:
            with self.subTest(label=label):
                round_id = f"reject-device-rebinding-{label}"
                self.prepare(round_id)
                self.begin(round_id, "attempt-1")
                checkpoint = self.checkpoint(round_id, "complete")
                self.assert_ok(
                    self.finalize(
                        self.result_payload(round_id, "COMPLETED", checkpoint),
                        attempt_id="attempt-1",
                    )
                )
                self.rebind_terminal_device(round_id, "attempt-1", **mutations)

                rejected = self.run_helper("validate", "--round-id", round_id)
                self.assertEqual(rejected.returncode, 1)
                errors = self.output(rejected)["errors"]
                self.assertTrue(
                    any("terminal checkpoint changed" in error for error in errors),
                    errors,
                )

    def test_validate_rejects_exact_checkpoint_under_wrong_terminal_root_inode(self) -> None:
        round_id = "reject-exact-checkpoint-wrong-root-inode"
        self.prepare(round_id)
        self.begin(round_id, "attempt-1")
        checkpoint = self.checkpoint(round_id, "complete")
        self.assert_ok(
            self.finalize(
                self.result_payload(round_id, "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        attempt = self.root / f"research/rounds/{round_id}/attempts/attempt-1"
        start_path = attempt / "guard_start.json"
        end_path = attempt / "guard_end.json"
        guard_start = json.loads(start_path.read_text(encoding="utf-8"))
        guard_start["root_identity"]["inode"] += 1
        start_path.chmod(0o644)
        write_json(start_path, guard_start)
        start_path.chmod(0o444)

        guard_end = json.loads(end_path.read_text(encoding="utf-8"))
        guard_end["root_identity"] = dict(guard_start["root_identity"])
        guard_end["guard_start_sha256"] = hashlib.sha256(
            start_path.read_bytes()
        ).hexdigest()
        end_path.chmod(0o644)
        write_json(end_path, guard_end)
        end_path.chmod(0o444)

        rejected = self.run_helper("validate", "--round-id", round_id)
        self.assertEqual(rejected.returncode, 1)
        errors = self.output(rejected)["errors"]
        self.assertTrue(
            any("terminal checkpoint changed" in error for error in errors),
            errors,
        )

    def test_json_boundary_rejects_lone_surrogates_in_all_keys_and_values(self) -> None:
        payloads = (
            b'{"scope":"\\ud800"}',
            b'{"scope":"safe","\\udfff":{"value":"safe"}}',
            b'{"scope":"safe","extra":{"nested":"\\ud800"}}',
        )
        for index, raw in enumerate(payloads):
            with self.subTest(index=index):
                rejected = self.run_helper(
                    "prepare",
                    "--round-id",
                    f"surrogate-{index}",
                    "--request-id",
                    f"request-surrogate-{index}",
                    raw=raw,
                )
                self.assertEqual(rejected.returncode, 2)
                self.assertIn("lone Unicode surrogate", self.output(rejected)["error"])

        valid_pair = self.assert_ok(
            self.run_helper(
                "prepare",
                "--round-id",
                "surrogate-pair",
                "--request-id",
                "request-surrogate-pair",
                raw=b'{"scope":"valid \\ud83d\\ude00 scalar"}',
            )
        )
        self.assertEqual(valid_pair["status"], "PREPARED")

    def test_prepare_utf8_field_and_stdin_byte_boundaries(self) -> None:
        ascii_scope = "a" * 12_000
        self.assertEqual(
            self.assert_ok(
                self.run_helper(
                    "prepare",
                    "--round-id",
                    "scope-ascii-boundary",
                    "--request-id",
                    "request-scope-ascii-boundary",
                    payload={"scope": ascii_scope},
                )
            )["status"],
            "PREPARED",
        )
        scalar_scope = "😀" * 3_000
        self.assertEqual(len(scalar_scope.encode("utf-8")), 12_000)
        self.assertEqual(
            self.assert_ok(
                self.run_helper(
                    "prepare",
                    "--round-id",
                    "scope-utf8-boundary",
                    "--request-id",
                    "request-scope-utf8-boundary",
                    payload={"scope": scalar_scope},
                )
            )["status"],
            "PREPARED",
        )
        overflow = self.run_helper(
            "prepare",
            "--round-id",
            "scope-utf8-overflow",
            "--request-id",
            "request-scope-utf8-overflow",
            payload={"scope": scalar_scope + "😀"},
        )
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("exceeds 12000 UTF-8 bytes", self.output(overflow)["error"])

        compact = b'{"scope":"stdin boundary"}'
        exact = compact + b" " * (16 * 1024 - len(compact))
        self.assertEqual(len(exact), 16 * 1024)
        self.assertEqual(
            self.assert_ok(
                self.run_helper(
                    "prepare",
                    "--round-id",
                    "prepare-stdin-boundary",
                    "--request-id",
                    "request-prepare-stdin-boundary",
                    raw=exact,
                )
            )["status"],
            "PREPARED",
        )
        too_large = self.run_helper(
            "prepare",
            "--round-id",
            "prepare-stdin-overflow",
            "--request-id",
            "request-prepare-stdin-overflow",
            raw=exact + b" ",
        )
        self.assertEqual(too_large.returncode, 2)
        self.assertIn("exceeds 16384 bytes", self.output(too_large)["error"])

    def test_finalize_utf8_field_and_stdin_byte_boundaries(self) -> None:
        for round_id, summary in (
            ("summary-ascii-boundary", "s" * 4_096),
            ("summary-utf8-boundary", "😀" * 1_024),
        ):
            with self.subTest(round_id=round_id):
                self.prepare(round_id)
                self.begin(round_id, "attempt-1")
                payload = self.result_payload(round_id, "FAILED", None)
                payload["summary"] = summary
                self.assertEqual(len(summary.encode("utf-8")), 4_096)
                self.assertEqual(
                    self.assert_ok(
                        self.finalize(payload, attempt_id="attempt-1")
                    )["status"],
                    "FAILED",
                )

        self.prepare("summary-utf8-overflow")
        self.begin("summary-utf8-overflow", "attempt-1")
        overflow_payload = self.result_payload(
            "summary-utf8-overflow", "FAILED", None
        )
        overflow_payload["summary"] = "😀" * 1_025
        overflow = self.finalize(overflow_payload, attempt_id="attempt-1")
        self.assertEqual(overflow.returncode, 2)
        self.assertIn("exceeds 4096 UTF-8 bytes", self.output(overflow)["error"])

        compact_round = "finalize-stdin-boundary"
        self.prepare(compact_round)
        self.begin(compact_round, "attempt-1")
        compact_payload = self.result_payload(compact_round, "FAILED", None)
        compact = json.dumps(
            compact_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        exact = compact + b" " * (32 * 1024 - len(compact))
        self.assertEqual(len(exact), 32 * 1024)
        accepted = self.run_helper(
            "finalize",
            "--round-id",
            compact_round,
            "--attempt-id",
            "attempt-1",
            "--expected-guard-start-sha256",
            self.guard_digests[(compact_round, "attempt-1")],
            raw=exact,
        )
        self.assertEqual(self.assert_ok(accepted)["status"], "FAILED")

        overflow_round = "finalize-stdin-overflow"
        self.prepare(overflow_round)
        self.begin(overflow_round, "attempt-1")
        overflow_payload = self.result_payload(overflow_round, "FAILED", None)
        compact_overflow = json.dumps(
            overflow_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        oversized = compact_overflow + b" " * (32 * 1024 + 1 - len(compact_overflow))
        rejected = self.run_helper(
            "finalize",
            "--round-id",
            overflow_round,
            "--attempt-id",
            "attempt-1",
            "--expected-guard-start-sha256",
            self.guard_digests[(overflow_round, "attempt-1")],
            raw=oversized,
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("exceeds 32768 bytes", self.output(rejected)["error"])

    def test_tampered_projection_fails_status_and_validation(self) -> None:
        self.prepare()
        self.begin()
        checkpoint = self.checkpoint("round-1", "complete")
        self.assert_ok(
            self.finalize(self.result_payload("round-1", "COMPLETED", checkpoint))
        )
        projection_path = self.root / "research/rounds/round-1/control_room_status.json"
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        projection["summary"] = "tampered"
        write_json(projection_path, projection)
        status = self.run_helper("status", "--round-id", "round-1")
        self.assertEqual(status.returncode, 2)
        validation = self.run_helper("validate")
        self.assertEqual(validation.returncode, 1)
        self.assertEqual(self.output(validation)["status"], "FAIL")

    def test_post_finalize_guard_start_tamper_fails_validation(self) -> None:
        self.prepare()
        self.begin()
        checkpoint = self.checkpoint("round-1", "complete")
        self.assert_ok(
            self.finalize(self.result_payload("round-1", "COMPLETED", checkpoint))
        )
        guard_start = self.root / "research/rounds/round-1/attempts/attempt-1/guard_start.json"
        original = guard_start.read_text(encoding="utf-8")
        guard_start.chmod(0o644)
        guard_start.write_text(original + "\n", encoding="utf-8")
        validation = self.run_helper("validate")
        self.assertEqual(validation.returncode, 1)
        self.assertTrue(
            any("guard_start must have immutable mode 0444" in item for item in self.output(validation)["errors"])
        )

    def test_terminal_chain_forgery_and_mode_drift_fail_closed(self) -> None:
        self.prepare("chain-forge")
        self.begin("chain-forge", "attempt-1")
        checkpoint = self.checkpoint("chain-forge", "blocked")
        self.assert_ok(
            self.finalize(
                self.result_payload("chain-forge", "BLOCKED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        attempt = self.root / "research/rounds/chain-forge/attempts/attempt-1"
        guard_end_path = attempt / "guard_end.json"
        result_path = attempt / "result.json"
        projection_path = self.root / "research/rounds/chain-forge/control_room_status.json"
        guard_end = json.loads(guard_end_path.read_text(encoding="utf-8"))
        forged = dict(guard_end["effective_result"])
        forged["status"] = "COMPLETED"
        forged["summary"] = "A forged completion must not validate."
        forged["blockers"] = []
        canonical_forged = json.dumps(
            forged,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        guard_end["effective_result"] = forged
        guard_end["effective_result_sha256"] = hashlib.sha256(canonical_forged).hexdigest()
        guard_end_path.chmod(0o644)
        result_path.chmod(0o644)
        write_json(guard_end_path, guard_end)
        write_json(result_path, forged)
        guard_end_path.chmod(0o444)
        result_path.chmod(0o444)

        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        for field in (
            "status",
            "summary",
            "changed_paths",
            "checkpoint_path",
            "blockers",
            "next_step",
        ):
            projection[field] = forged[field]
        projection["source_digest_sha256"] = plan_bound_projection_digest(
            self.root,
            "chain-forge",
            projection,
        )
        write_json(projection_path, projection)

        validation = self.run_helper("validate", "--round-id", "chain-forge")
        self.assertEqual(validation.returncode, 1)
        self.assertTrue(
            any(
                "PASS guard_end changed the reported result" in item
                for item in self.output(validation)["errors"]
            )
        )
        status = self.run_helper("status", "--round-id", "chain-forge")
        self.assertEqual(status.returncode, 2)
        self.assertIn("failed validation", self.output(status)["error"])

        guard_start_path = attempt / "guard_start.json"
        guard_start_path.chmod(0o666)
        validation = self.run_helper("validate", "--round-id", "chain-forge")
        self.assertEqual(validation.returncode, 1)
        self.assertTrue(
            any(
                "guard_start must have immutable mode 0444" in item
                for item in self.output(validation)["errors"]
            )
        )

    def test_queued_cancel_projection_is_exactly_bound(self) -> None:
        self.prepare("queued-cancel-forge")
        self.assert_ok(self.run_helper("cancel", "--round-id", "queued-cancel-forge"))
        projection_path = (
            self.root / "research/rounds/queued-cancel-forge/control_room_status.json"
        )
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        projection["summary"] = "Forged queued-cancel summary."
        projection["source_digest_sha256"] = plan_bound_projection_digest(
            self.root,
            "queued-cancel-forge",
            projection,
        )
        write_json(projection_path, projection)
        validation = self.run_helper("validate", "--round-id", "queued-cancel-forge")
        self.assertEqual(validation.returncode, 1)
        self.assertTrue(
            any(
                "queued-cancel projection is not canonical" in item
                for item in self.output(validation)["errors"]
            )
        )
        status = self.run_helper("status", "--round-id", "queued-cancel-forge")
        self.assertEqual(status.returncode, 2)
        self.assertIn("failed validation", self.output(status)["error"])

    def test_projection_digest_is_bound_to_exact_approved_plan_bytes(self) -> None:
        round_id = "queued-plan-replacement"
        self.prepare(round_id)
        self.assert_ok(self.run_helper("cancel", "--round-id", round_id))
        plan_path = self.root / f"research/rounds/{round_id}/approved_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        plan["scope"] = "A different internally consistent approved scope."
        plan["scope_sha256"] = hashlib.sha256(
            plan["scope"].encode("utf-8")
        ).hexdigest()
        plan_path.chmod(0o644)
        write_json(plan_path, plan)
        plan_path.chmod(0o444)

        status = self.run_helper("status", "--round-id", round_id)
        self.assertEqual(status.returncode, 2)
        self.assertIn("projection source digest mismatch", self.output(status)["error"])
        validation = self.run_helper("validate", "--round-id", round_id)
        self.assertEqual(validation.returncode, 1)
        self.assertTrue(
            any(
                "projection source digest mismatch" in item
                for item in self.output(validation)["errors"]
            )
        )

    def test_integer_protocol_fields_require_exact_int_not_bool_or_float(self) -> None:
        round_id = "exact-integer-types"
        self.prepare(round_id)
        self.begin(round_id, "attempt-1")
        checkpoint = self.checkpoint(round_id, "terminal")
        self.assert_ok(
            self.finalize(
                self.result_payload(round_id, "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )

        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_exact_integer_types", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root

        plan_path = self.root / f"research/rounds/{round_id}/approved_plan.json"
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        for field, replacement in (
            ("schema_version", True),
            ("protocol_version", 1.0),
            ("architecture_guard_policy_version", 2.0),
        ):
            with self.subTest(record="plan", field=field, replacement=replacement):
                forged = dict(plan)
                forged[field] = replacement
                with self.assertRaises(module.ResearchRoundError):
                    module.validate_plan(forged, round_id)

        projection_path = self.root / f"research/rounds/{round_id}/control_room_status.json"
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        plan_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
        for replacement in (True, 1.0):
            with self.subTest(record="projection", replacement=replacement):
                forged = dict(projection)
                forged["schema_version"] = replacement
                forged["source_digest_sha256"] = module.projection_digest(
                    forged, plan_sha256
                )
                with self.assertRaises(module.ResearchRoundError):
                    module.validate_projection(
                        forged,
                        round_id,
                        plan_sha256=plan_sha256,
                    )

        attempt = self.root / f"research/rounds/{round_id}/attempts/attempt-1"
        start_raw = (attempt / "guard_start.json").read_bytes()
        guard_start = json.loads(start_raw.decode("utf-8"))
        start_mutations = (
            ("schema_version", True),
            ("guard_policy_version", 2.0),
            ("plan_mode", True),
        )
        for field, replacement in start_mutations:
            with self.subTest(record="guard_start", field=field, replacement=replacement):
                forged = dict(guard_start)
                forged[field] = replacement
                with self.assertRaises(module.ResearchRoundError):
                    module.validate_guard_start(forged, round_id, "attempt-1")
        forged_identity = dict(guard_start)
        forged_identity["root_identity"] = dict(guard_start["root_identity"])
        forged_identity["root_identity"]["inode"] = float(
            forged_identity["root_identity"]["inode"]
        )
        with self.assertRaises(module.ResearchRoundError):
            module.validate_guard_start(forged_identity, round_id, "attempt-1")

        guard_end = json.loads((attempt / "guard_end.json").read_text(encoding="utf-8"))
        for replacement in (True, 1.0):
            with self.subTest(record="guard_end", replacement=replacement):
                forged = dict(guard_end)
                forged["terminal_sequence"] = replacement
                with self.assertRaises(module.ResearchRoundError):
                    module.validate_guard_end(
                        forged,
                        guard_start,
                        start_raw,
                        round_id,
                        "attempt-1",
                    )

        inventory = [dict(item) for item in guard_start["protected_inventory"]]
        self.assertTrue(inventory)
        inventory[0] = dict(inventory[0])
        inventory[0]["mode"] = float(inventory[0]["mode"])
        with self.assertRaises(module.ResearchRoundError):
            module.validate_inventory_records(inventory, "forged inventory")

    def test_compatibility_marker_is_fail_closed(self) -> None:
        bad = dict(MARKER)
        bad["protocol_version"] = 2
        write_json(self.root / ".lab/control_room_actions.json", bad)
        result = self.run_helper(
            "prepare",
            "--round-id",
            "round-1",
            "--request-id",
            "request-1",
            payload={"scope": "scope"},
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("incompatible", self.output(result)["error"])
        self.assertFalse((self.root / "research/rounds").exists())

    def test_inventory_validation_uses_path_component_order(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location(
            "fixture_component_order", module_path
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        directory = {
            "path": "alpha",
            "type": "directory",
            "mode": 0o755,
            "size": 0,
            "sha256": None,
        }
        child = {
            "path": "alpha/child.txt",
            "type": "file",
            "mode": 0o644,
            "size": 1,
            "sha256": "a" * 64,
            "device": 1,
            "inode": 2,
            "nlink": 1,
        }
        sibling = {
            "path": "alpha.txt",
            "type": "file",
            "mode": 0o644,
            "size": 1,
            "sha256": "b" * 64,
            "device": 1,
            "inode": 3,
            "nlink": 1,
        }
        component_order = [directory, child, sibling]
        self.assertEqual(
            module.validate_inventory_records(component_order, "inventory"),
            component_order,
        )

        raw_string_order = sorted(component_order, key=lambda item: item["path"])
        self.assertNotEqual(raw_string_order, component_order)
        with self.assertRaisesRegex(module.ResearchRoundError, "unique and sorted"):
            module.validate_inventory_records(raw_string_order, "inventory")

        with self.assertRaisesRegex(module.ResearchRoundError, "unique and sorted"):
            module.validate_inventory_records(
                [sibling, directory, child], "inventory"
            )

        (self.root / "alpha").mkdir()
        (self.root / "alpha/child.txt").write_text("child\n", encoding="utf-8")
        (self.root / "alpha.txt").write_text("sibling\n", encoding="utf-8")
        round_id = "component-order-round"
        self.prepare(round_id)
        self.begin(round_id, "attempt-1")
        checkpoint = self.checkpoint(round_id, "terminal")
        self.assert_ok(
            self.finalize(
                self.result_payload(round_id, "COMPLETED", checkpoint),
                attempt_id="attempt-1",
            )
        )
        self.assertEqual(
            self.assert_ok(
                self.run_helper("validate", "--round-id", round_id)
            )["status"],
            "PASS",
        )

    def test_guard_file_and_record_bounds_fail_closed(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_research_round", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root

        oversized = self.root / "oversized-policy.bin"
        oversized.write_bytes(b"12345")
        module.MAX_GUARD_FILE_BYTES = 4
        with self.assertRaisesRegex(module.ResearchRoundError, "guard file exceeds"):
            module.protected_inventory()

        oversized.unlink()
        module.MAX_GUARD_FILE_BYTES = 64 * 1024 * 1024
        module.MAX_GUARD_RECORDS = 1
        with self.assertRaisesRegex(module.ResearchRoundError, "guard inventory exceeds"):
            module.protected_inventory()

    def test_guard_skips_only_git_objects_and_lake_cache_contents(self) -> None:
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_bulk_guard", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root

        (self.root / ".git/objects/ab").mkdir(parents=True)
        (self.root / ".git/refs/heads").mkdir(parents=True)
        (self.root / ".git/HEAD").write_bytes(b"h")
        (self.root / ".git/config").write_bytes(b"c")
        (self.root / ".git/index").write_bytes(b"i")
        (self.root / ".git/refs/heads/main").write_bytes(b"r")
        (self.root / ".git/objects-backup").mkdir()
        (self.root / ".git/objects-backup/kept").write_bytes(b"o")

        nested_git = self.root / "nested/.git/objects"
        nested_git.mkdir(parents=True)
        (nested_git / "kept").write_bytes(b"n")

        lean_root = self.root / "formalization/lean/fixture"
        (lean_root / ".lake/build").mkdir(parents=True)
        (lean_root / ".lakehouse").mkdir(parents=True)
        (lean_root / "lake").mkdir(parents=True)
        (lean_root / "Main.lean").write_bytes(b"m")
        (lean_root / ".lakehouse/kept.bin").write_bytes(b"l")
        (lean_root / "lake/kept.bin").write_bytes(b"k")

        largest = max(
            path.stat().st_size for path in self.root.rglob("*") if path.is_file()
        )
        oversized = b"x" * (largest + 1)
        (self.root / ".git/objects/ab/oversized-object").write_bytes(oversized)
        (lean_root / ".lake/build/oversized-cache").write_bytes(oversized)
        module.MAX_GUARD_FILE_BYTES = largest
        paths = {record["path"] for record in module.protected_inventory()}

        self.assertIn(".git/objects", paths)
        self.assertNotIn(".git/objects/ab/oversized-object", paths)
        self.assertIn(".git/HEAD", paths)
        self.assertIn(".git/config", paths)
        self.assertIn(".git/index", paths)
        self.assertIn(".git/refs/heads/main", paths)
        self.assertIn(".git/objects-backup/kept", paths)
        self.assertIn("nested/.git/objects/kept", paths)
        self.assertIn("formalization/lean/fixture/.lake", paths)
        self.assertNotIn(
            "formalization/lean/fixture/.lake/build/oversized-cache", paths
        )
        self.assertIn("formalization/lean/fixture/Main.lean", paths)
        self.assertIn("formalization/lean/fixture/.lakehouse/kept.bin", paths)
        self.assertIn("formalization/lean/fixture/lake/kept.bin", paths)

    def test_oversized_guard_start_fails_before_attempt_state_and_does_not_wedge_round(self) -> None:
        round_id = "oversized-guard-start"
        attempt_id = "attempt-1"
        self.prepare(round_id)
        module_path = self.root / "scripts/research_round.py"
        spec = importlib.util.spec_from_file_location("fixture_guard_start_bound", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader if spec is not None else None)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.ROOT = self.root
        module.MAX_GUARD_START_BYTES = 256

        args = module.argparse.Namespace(round_id=round_id, attempt_id=attempt_id)
        with self.assertRaisesRegex(module.ResearchRoundError, "guard_start exceeds 256 bytes"):
            module.command_begin(args)

        attempt = self.root / f"research/rounds/{round_id}/attempts/{attempt_id}"
        self.assertFalse(attempt.exists())
        self.assertEqual(list(attempt.parent.iterdir()), [])
        self.assertIsNone(module.active_attempt(round_id))
        queued = self.assert_ok(self.run_helper("status", "--round-id", round_id))
        self.assertEqual(queued["status"], "QUEUED")

        begun = self.begin(round_id, attempt_id)
        cancelled = self.assert_ok(
            self.run_helper(
                "cancel",
                "--round-id",
                round_id,
                "--expected-guard-start-sha256",
                begun["guard_start_sha256"],
            )
        )
        self.assertEqual(cancelled["status"], "CANCELLED")
        self.assertEqual(
            self.assert_ok(self.run_helper("validate", "--round-id", round_id))["status"],
            "PASS",
        )


if __name__ == "__main__":
    unittest.main()
