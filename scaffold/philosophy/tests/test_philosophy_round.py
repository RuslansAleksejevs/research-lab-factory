"""Synthetic round fixtures only; no philosophical work or native capture claims."""
import datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "philosophy_round.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("philosophy_round_under_test", SCRIPT)
rounds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rounds)
Archive, ArchiveError = rounds.Archive, rounds.ArchiveError
REAL_DATETIME = datetime.datetime


class FixedClock(REAL_DATETIME):
    instant = REAL_DATETIME(2026, 1, 2, 23, 59, 59, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        return cls.instant.astimezone(tz) if tz else cls.instant.replace(tzinfo=None)


class PhilosophyRoundTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-philosophy-round-")
        # macOS exposes some temporary directories through /var symlinks. The
        # helper intentionally refuses symlink ancestors, so bind the real root.
        self.root = Path(self.temp.name).resolve()
        self.write("LAB_PROFILE.json", {"lab": {"kind": "PHILOSOPHY_PROGRAM"}})
        self.write("methods/simple-v1.json", {
            "id": "synthetic-method-v1", "stages": rounds.STAGES,
            "synthetic": True,
        })
        for name in ("AGENTS.md", "AGENT_POLICY.md", "USER_PREFERENCES.md", "workflows/ROUND.md"):
            self.write(name, "Synthetic instructions for " + name + "\n")
        self.write(".codex/config.toml", "# synthetic configuration\n")
        self.write(".lab/philosophy.json", {"synthetic": True})
        self.write("inputs/seed.txt", b"synthetic seed\r\n")
        self.archive = Archive(self.root / "research/archive").init()
        self.serial = 0
        self.run = "synthetic-run"
        self.session = "synthetic-author"
        self.critic = "synthetic-critic"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, body):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(body, dict):
            body = json.dumps(body, sort_keys=True).encode()
        elif isinstance(body, str):
            body = body.encode()
        path.write_bytes(body)
        return name

    def start(self, run=None, session=None, purpose="technical", inputs=None):
        return rounds.start(self.root, self.archive, run or self.run, session or self.session,
                            purpose, "methods/simple-v1.json", inputs or ["inputs/seed.txt"])

    def capture(self, session=None, run=None, kind="capture.raw_record", parents=None, status=None, role=None):
        """Explicit fixture events, never records from an actual provider session."""
        self.serial += 1
        payload = {"synthetic": True, "fixture": "not a real capture", "source_type": "message"}
        if status is not None:
            payload["status"] = status
        return self.archive.append({
            "kind": kind, "actor": {"id": "synthetic-collector", "role": role or
                                     ("assistant" if kind == "capture.raw_record" else "tool")},
            "session_id": session or self.session, "run_id": run or self.run,
            "operation_id": "synthetic-capture", "attempt_id": "synthetic-capture-attempt",
            "parents": parents or [], "payload": payload,
            "outputs": [self.archive.put(("synthetic fixture %d\n" % self.serial).encode())]
                       if kind == "capture.raw_record" else [],
        }, "synthetic-capture-%d" % self.serial)

    def stage(self, stage, session=None, evidence=None, source_note=None):
        session = session or (self.critic if stage == "critique" else self.session)
        evidence = evidence or [self.capture(session)["id"]]
        name = self.write("notes/" + stage + ".txt", "Synthetic " + stage + " fixture\n")
        return rounds.record(self.root, self.archive, self.run, stage, name, session, evidence,
                             source_note if source_note is not None else
                             ("Synthetic retrieval fixture; no external source accessed." if stage == "sources" else ""))

    def complete_stages(self):
        self.start()
        return [self.stage(stage) for stage in rounds.STAGES]

    def coverage(self, session=None, parents=None, run=None, status="BOUNDED_COMPLETE"):
        session = session or self.session
        if parents is None:
            parents = [e["id"] for e in self.archive.events()
                       if e["kind"] == "capture.raw_record" and e["session_id"] == session
                       and e["run_id"] == (run or self.run)]
        return self.capture(session, run, "capture.coverage", parents, status)

    def coverage_ids(self):
        return [self.coverage(session)["id"] for session in (self.session, self.critic)]

    def summary(self, **updates):
        value = {"question": "Synthetic engineering question", "outcome": "COMPLETE_TECHNICAL",
                 "contribution": "Synthetic artifact", "criticism": "Synthetic separate-session fixture",
                 "limitations": "No research result and no actual native recording",
                 "next_step": "UNIQUE_OLD_NEXT_STEP", "method_change": "No method change",
                 "comparability": "Engineering exercise only", "coverage_boundary": "Synthetic fixtures only"}
        value.update(updates)
        return self.write("notes/checkpoint.json", value)

    def checkpoint(self, coverage, incomplete=False, **updates):
        return rounds.checkpoint(self.root, self.archive, self.run, self.summary(**updates), coverage, incomplete)

    def archive_bytes(self):
        return {p.relative_to(self.archive.root).as_posix(): p.read_bytes()
                for p in self.archive.root.rglob("*") if p.is_file() and p.name != ".lock"}

    def cli(self, *args, successful=True):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(self.root), *args],
                                text=True, capture_output=True, cwd=self.root)
        self.assertEqual(result.returncode, 0 if successful else 1, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_start_replay_preserves_identity_and_exact_bound_input_versions(self):
        original = self.start()
        original_history = self.archive.events()
        before = self.archive_bytes()
        self.assertEqual(self.start(), original)
        self.assertEqual(self.archive_bytes(), before)
        self.assertEqual(self.archive.get(original["bindings"]["input"][0]), b"synthetic seed\r\n")
        self.write("inputs/seed.txt", b"changed seed\n")
        with self.assertRaisesRegex(ArchiveError, "run ID conflict"):
            self.start()
        self.assertEqual(self.archive.events(), original_history)
        self.assertEqual(self.archive.get(original["bindings"]["input"][0]), b"synthetic seed\r\n")
        new = self.start(run="synthetic-new-version")
        self.assertNotEqual(new["bindings"]["input"], original["bindings"]["input"])

    def test_start_rejects_changed_session_purpose_and_configuration(self):
        self.start()
        original_history = self.archive.events()
        for kwargs in ({"session": "synthetic-other-author"}, {"purpose": "research"}):
            with self.assertRaisesRegex(ArchiveError, "run ID conflict"):
                self.start(**kwargs)
        self.write(".codex/config.toml", "# changed synthetic configuration\n")
        with self.assertRaisesRegex(ArchiveError, "run ID conflict"):
            self.start()
        self.assertEqual(self.archive.events(), original_history)

    def test_stages_are_ordered_and_replay_cannot_replace_artifact(self):
        self.start()
        with self.assertRaisesRegex(ArchiveError, "out of order"):
            self.stage("sources")
        evidence = [self.capture()["id"]]
        question = self.stage("question", evidence=evidence)
        original = self.archive.get(question["outputs"][0])
        replay = rounds.record(self.root, self.archive, self.run, "question", "notes/question.txt",
                               self.session, evidence)
        self.assertEqual(replay, question)
        self.write("notes/question.txt", b"Replacement must not rewrite original\n")
        with self.assertRaisesRegex(ArchiveError, "stage replay conflict"):
            rounds.record(self.root, self.archive, self.run, "question", "notes/question.txt",
                          self.session, evidence)
        self.assertEqual(self.archive.get(question["outputs"][0]), original)
        self.assertEqual(len([e for e in self.archive.events() if e["kind"] == "round.stage"]), 1)

    def test_sources_need_explicit_retrieval_note_and_keep_it_immutable(self):
        self.start()
        self.stage("question")
        evidence = [self.capture()["id"]]
        with self.assertRaisesRegex(ArchiveError, "retrieval/coverage note"):
            self.stage("sources", evidence=evidence, source_note="  ")
        event = self.stage("sources", evidence=evidence)
        with self.assertRaisesRegex(ArchiveError, "stage replay conflict"):
            rounds.record(self.root, self.archive, self.run, "sources", "notes/sources.txt",
                          self.session, evidence, "Changed retrieval account")
        self.assertIn("no external source accessed", event["payload"]["source_note"])

    def test_critique_requires_distinct_actual_session(self):
        self.start()
        for stage in rounds.STAGES[:3]:
            self.stage(stage)
        with self.assertRaisesRegex(ArchiveError, "separate actual AI context/session"):
            self.stage("critique", session=self.session)
        critique = self.stage("critique")
        self.assertEqual(critique["session_id"], self.critic)

    def test_stage_capture_must_match_session_and_run(self):
        self.start()
        self.write("notes/question.txt", "Synthetic question\n")
        invalid = [self.capture(session="synthetic-other-session"), self.capture(run="synthetic-other-run")]
        for event in invalid:
            with self.assertRaisesRegex(ArchiveError, "session and run"):
                rounds.record(self.root, self.archive, self.run, "question", "notes/question.txt",
                              self.session, [event["id"]])
        for evidence in ([], ["missing-event"], [self.coverage()["id"]],
                         [self.capture(kind="synthetic.unrelated")["id"]]):
            with self.assertRaisesRegex(ArchiveError, "original captured"):
                rounds.record(self.root, self.archive, self.run, "question", "notes/question.txt",
                              self.session, evidence)
        self.assertFalse(any(e["kind"] == "round.stage" for e in self.archive.events()))

    def test_user_capture_cannot_certify_ai_contribution_origin(self):
        self.start()
        self.stage("question")
        self.stage("sources")
        user_event = self.capture(role="user")
        with self.assertRaises(ArchiveError):
            self.stage("contribution", evidence=[user_event["id"]])
        self.assertFalse(any(e["kind"] == "round.stage" and e["payload"]["stage"] == "contribution"
                             for e in self.archive.events()))

    def test_round_history_validator_rejects_completed_without_checkpoint(self):
        first = self.start()
        self.archive.append(rounds.envelope(first, "operation.completed"), "synthetic-unjustified-terminal")
        # Generic archive consistency alone is insufficient: the workflow
        # validator must reject a terminal that bypassed its checkpoint gate.
        self.assertTrue(self.archive.validate()["ok"])
        before = self.archive_bytes()
        errors = rounds.validate_round_history(self.archive)
        self.assertTrue(errors)
        self.assertIn("checkpoint", " ".join(errors).lower())
        self.assertEqual(self.archive_bytes(), before)

    def test_round_history_validator_accepts_fully_recorded_round(self):
        self.complete_stages()
        self.checkpoint(self.coverage_ids())
        before = self.archive_bytes()
        self.assertEqual(rounds.validate_round_history(self.archive), [])
        self.assertEqual(self.archive_bytes(), before)

    def test_checkpoint_rejects_unrelated_same_session_coverage(self):
        self.complete_stages()
        unrelated = [self.capture(session)["id"] for session in (self.session, self.critic)]
        coverage = [self.coverage(session, [raw])["id"]
                    for session, raw in zip((self.session, self.critic), unrelated)]
        with self.assertRaisesRegex(ArchiveError, "exact captured evidence"):
            self.checkpoint(coverage)
        self.assertFalse(any(e["kind"] == "checkpoint" for e in self.archive.events()))
        cp = self.checkpoint(self.coverage_ids())
        self.assertEqual(cp["payload"]["capture_status"], "BOUNDED_COMPLETE")

    def test_checkpoint_requires_critic_coverage_and_exact_run(self):
        self.complete_stages()
        author = self.coverage()["id"]
        with self.assertRaisesRegex(ArchiveError, "every stage session"):
            self.checkpoint([author])
        other_run = self.coverage(self.critic, run="synthetic-other-run")["id"]
        with self.assertRaisesRegex(ArchiveError, "exact run-bound"):
            self.checkpoint([author, other_run])

    def test_incomplete_coverage_never_becomes_success(self):
        self.complete_stages()
        coverage = [self.coverage(status="INCOMPLETE")["id"], self.coverage(self.critic)["id"]]
        with self.assertRaisesRegex(ArchiveError, "coverage incomplete"):
            self.checkpoint(coverage)
        cp = self.checkpoint(coverage, incomplete=True)
        terminal = self.archive.events()[-1]
        self.assertEqual(cp["payload"]["capture_status"], "INCOMPLETE")
        self.assertEqual(terminal["kind"], "operation.interrupted")
        self.assertEqual(self.archive.recover()["incomplete_attempts"], [])

    def test_complete_checkpoint_needs_all_stages_and_semantically_complete_summary(self):
        self.start()
        self.stage("question")
        coverage = [self.coverage()["id"]]
        with self.assertRaisesRegex(ArchiveError, "all five stages"):
            self.checkpoint(coverage)
        for stage in rounds.STAGES[1:]:
            self.stage(stage)
        coverage = self.coverage_ids()
        for updates in ({"limitations": ""}, {"criticism": 3}, {"outcome": "PROVEN"}):
            with self.assertRaises(ArchiveError):
                self.checkpoint(coverage, **updates)
        self.assertFalse(any(e["kind"] == "checkpoint" for e in self.archive.events()))

    def test_pause_resume_blocks_dependent_work_and_preserves_control_history(self):
        self.start()
        evidence = [self.capture()["id"]]
        paused = self.cli("pause", "--run", self.run, "--reason", "Synthetic interruption")
        self.assertEqual(self.cli("pause", "--run", self.run, "--reason", "Synthetic interruption"), paused)
        with self.assertRaisesRegex(ArchiveError, "round paused"):
            self.stage("question", evidence=evidence)
        resumed = self.cli("resume", "--run", self.run, "--reason", "Synthetic continuation")
        self.assertEqual(self.cli("resume", "--run", self.run, "--reason", "Synthetic continuation"), resumed)
        self.stage("question")
        controls = [e for e in self.archive.events() if e["kind"] in ("round.pause", "round.resume")]
        self.assertEqual(controls, [paused, resumed])
        self.assertIn(paused["id"], resumed["parents"])

    def test_paused_partial_round_can_only_finish_with_incomplete_checkpoint(self):
        self.start()
        self.stage("question")
        self.cli("pause", "--run", self.run, "--reason", "Synthetic stopped segment")
        coverage = [self.coverage()["id"]]
        with self.assertRaisesRegex(ArchiveError, "round paused"):
            self.checkpoint(coverage)
        cp = self.checkpoint(coverage, incomplete=True)
        self.assertEqual(cp["payload"]["capture_status"], "INCOMPLETE")
        with self.assertRaisesRegex(ArchiveError, "terminal"):
            self.stage("sources")
        blocked = self.cli("resume", "--run", self.run, "--reason", "Cannot reopen terminal", successful=False)
        self.assertIn("terminal", blocked["error"])

    def test_checkpoint_recovers_next_day_after_terminal_write_interruption(self):
        self.complete_stages()
        coverage = self.coverage_ids()
        original_append = self.archive.append

        def crash_before_terminal(event, key):
            if event["kind"] == "operation.completed":
                raise OSError("synthetic interruption after checkpoint publication")
            return original_append(event, key)

        FixedClock.instant = REAL_DATETIME(2026, 1, 2, 23, 59, 59, tzinfo=datetime.timezone.utc)
        with mock.patch.object(rounds.datetime, "datetime", FixedClock):
            with mock.patch.object(self.archive, "append", side_effect=crash_before_terminal):
                with self.assertRaisesRegex(OSError, "synthetic interruption"):
                    self.checkpoint(coverage)
        cp = next(e for e in self.archive.events() if e["kind"] == "checkpoint")
        old_events = {p.name: p.read_bytes() for p in (self.archive.root / "events").glob("*.json")}
        self.assertEqual(cp["payload"]["research_date"], "2026-01-02")
        self.assertEqual(len(self.archive.recover()["incomplete_attempts"]), 1)
        FixedClock.instant = REAL_DATETIME(2026, 1, 3, 0, 0, 1, tzinfo=datetime.timezone.utc)
        with mock.patch.object(rounds.datetime, "datetime", FixedClock):
            self.assertEqual(self.checkpoint(coverage), cp)
        for name, body in old_events.items():
            self.assertEqual((self.archive.root / "events" / name).read_bytes(), body)
        terminals = [e for e in self.archive.events() if e["kind"] == "operation.completed"]
        self.assertEqual(len(terminals), 1)
        self.assertIn(cp["id"], terminals[0]["parents"])
        self.assertTrue(terminals[0]["recorded_at"].startswith("2026-01-03"))
        self.assertEqual(self.archive.recover()["incomplete_attempts"], [])

    def test_terminal_retry_is_idempotent_and_changed_checkpoint_is_rejected(self):
        self.complete_stages()
        coverage = self.coverage_ids()
        cp = self.checkpoint(coverage)
        before = self.archive_bytes()
        self.assertEqual(self.checkpoint(coverage), cp)
        self.assertEqual(self.archive_bytes(), before)
        with self.assertRaisesRegex(ArchiveError, "checkpoint replay conflict"):
            self.checkpoint(coverage, limitations="Changed summary must not rewrite original")
        self.assertEqual(len([e for e in self.archive.events() if e["kind"] == "checkpoint"]), 1)
        self.assertEqual(len([e for e in self.archive.events() if e["kind"] == "operation.completed"]), 1)

    def test_refresh_writes_only_derived_views_and_does_not_mix_old_checkpoint_into_active_run(self):
        self.complete_stages()
        cp = self.checkpoint(self.coverage_ids())
        before = self.archive_bytes()
        rounds.refresh(self.root, self.archive)
        self.assertEqual(self.archive_bytes(), before)
        self.assertIn(cp["id"], (self.root / "knowledge/resume.md").read_text())
        self.start(run="synthetic-new-active-run")
        before = self.archive_bytes()
        result = rounds.refresh(self.root, self.archive)
        self.assertEqual(result["checkpoints"], 1)
        self.assertEqual(self.archive_bytes(), before)
        resume = (self.root / "knowledge/resume.md").read_text()
        self.assertIn("synthetic-new-active-run", resume)
        self.assertNotIn(cp["id"], resume)
        self.assertNotIn("UNIQUE_OLD_NEXT_STEP", resume)
        index = json.loads((self.root / "knowledge/checkpoint_index.json").read_bytes())
        self.assertEqual(index[0]["id"], cp["id"])
        self.assertTrue((self.root / "research/views/index.json").is_file())
        self.assertTrue((self.root / "research/views/index.md").is_file())
        self.assertTrue(self.archive.validate()["ok"])


if __name__ == "__main__":
    unittest.main()
