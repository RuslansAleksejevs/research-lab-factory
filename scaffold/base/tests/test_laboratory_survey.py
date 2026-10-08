from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/laboratory_survey.py"
SPEC = importlib.util.spec_from_file_location("laboratory_survey_under_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
survey = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(survey)


class LaboratorySurveyTests(unittest.TestCase):
    def make_lab(self, root: Path) -> None:
        (root / ".lab").mkdir(parents=True)
        (root / "knowledge").mkdir(parents=True)
        (root / "research/checkpoints").mkdir(parents=True)
        (root / "runs/laboratory_surveys").mkdir(parents=True)
        (root / "runs/laboratory_stewardship/r1").mkdir(parents=True)
        (root / "problems/active/p1").mkdir(parents=True)
        (root / "LAB_PROFILE.json").write_text(
            '{"template":{"id":"math-research-lab-template"},'
            '"lab":{"title":"Test"}}\n',
            encoding="utf-8",
        )
        (root / ".lab/manifest.json").write_text(
            '{"template_id":"math-research-lab-template"}\n', encoding="utf-8"
        )
        (root / "PROJECT_CHARTER.md").write_text("# Charter\n", encoding="utf-8")
        (root / "knowledge/results_ledger.yaml").write_text(
            '{"results":[]}\n', encoding="utf-8"
        )
        (root / "knowledge/laboratory_overview.md").write_text(
            "# No survey\n", encoding="utf-8"
        )
        (root / "knowledge/laboratory_survey_state.json").write_text(
            '{"schema_version":1,"basis_sha256":null,"freshness":"NONE"}\n',
            encoding="utf-8",
        )
        (root / "problems/active/p1/status.yaml").write_text(
            '{"status":"UNKNOWN"}\n', encoding="utf-8"
        )
        (root / "problems/INDEX.md").write_text(
            "# Problem index\n", encoding="utf-8"
        )
        (root / "runs/laboratory_stewardship/r1/completion_basis.json").write_text(
            '{"status":"VALIDATED_PENDING_SURVEY"}\n', encoding="utf-8"
        )

    def quiet_run(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return survey.run(args)

    def test_snapshot_is_read_only_and_digest_is_deterministic(self):
        with tempfile.TemporaryDirectory(prefix="survey-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            first = survey.build_snapshot(root)
            second = survey.build_snapshot(root)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertEqual(first["inventory_sha256"], second["inventory_sha256"])
            self.assertEqual(before, after)
            self.assertNotIn("knowledge/laboratory_overview.md", [x["path"] for x in first["files"]])
            self.assertNotIn(
                "runs/laboratory_stewardship/r1/completion_basis.json",
                [x["path"] for x in first["files"]],
            )
            self.assertIn("problems/INDEX.md", [x["path"] for x in first["files"]])

    def test_problem_index_drift_invalidates_final_survey(self):
        with tempfile.TemporaryDirectory(prefix="survey-problem-index-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260812T120000Z-problem-index"
            survey.start_survey(root, survey_id, "LOCAL_FULL")
            packet = root / "runs/laboratory_surveys" / survey_id
            (packet / "report.md").write_text("# Report\n", encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, survey_id)[1], 0)
            self.assertEqual(survey.check_freshness(root)[1], 0)

            (root / "problems/INDEX.md").write_text(
                "# Problem index\n\nChanged after survey.\n",
                encoding="utf-8",
            )
            freshness, code = survey.check_freshness(root)
            self.assertEqual(code, 2)
            self.assertEqual(freshness["freshness"], "STALE")

    def test_snapshot_covers_optional_live_memory_and_excludes_migrations(self):
        with tempfile.TemporaryDirectory(prefix="survey-memory-roots-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            expected = {
                "portfolio/candidates/c1/rounds/0001.json": "portfolio round\n",
                "collaboration/cycles/0001/handoff.md": "team handoff\n",
                "archive/research/old-route.md": "historical route\n",
            }
            for relative, content in expected.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            migration = root / "archive/migrations/m1/record.json"
            migration.parent.mkdir(parents=True, exist_ok=True)
            migration.write_text('{}\n', encoding="utf-8")

            snapshot = survey.build_snapshot(root)
            paths = {item["path"] for item in snapshot["files"]}
            self.assertTrue(set(expected).issubset(paths))
            self.assertNotIn("archive/migrations/m1/record.json", paths)

    def test_snapshot_excludes_only_exact_research_memory_staging_names(self):
        with tempfile.TemporaryDirectory(prefix="survey-memory-staging-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            exact_names = {
                ".research-memory-" + "a" * 32,
                ".checkpoint-index-" + "b" * 32,
            }
            visible_near_misses = {
                ".research-memory-" + "c" * 31,
                ".checkpoint-index-" + "D" * 32,
            }
            for name in exact_names | visible_near_misses:
                (root / "research" / name).write_text(name + "\n", encoding="utf-8")

            snapshot = survey.build_snapshot(root)
            paths = {item["path"] for item in snapshot["files"]}
            for name in exact_names:
                self.assertNotIn(f"research/{name}", paths)
            for name in visible_near_misses:
                self.assertIn(f"research/{name}", paths)

    def test_snapshot_regular_to_fifo_race_is_nonblocking(self):
        with tempfile.TemporaryDirectory(prefix="survey-fifo-race-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            target = root / "research/raced.md"
            target.write_text("regular before race\n", encoding="utf-8")
            real_open = survey.os.open
            nonblocking_seen = []

            def replace_regular_with_fifo(candidate, flags, *open_args, **open_kwargs):
                if Path(candidate) == target:
                    target.unlink()
                    os.mkfifo(target)
                    nonblocking_seen.append(
                        bool(flags & getattr(os, "O_NONBLOCK", 0))
                    )
                    if not nonblocking_seen[-1]:
                        raise OSError("blocking FIFO open refused by test")
                return real_open(candidate, flags, *open_args, **open_kwargs)

            with mock.patch.object(survey.os, "open", side_effect=replace_regular_with_fifo):
                snapshot = survey.build_snapshot(root)
            self.assertEqual(nonblocking_seen, [True])
            self.assertIn(
                "research/raced.md",
                [item["path"] for item in snapshot["skipped"]],
            )

    def test_excluded_binding_is_rechecked_for_finalize_and_freshness(self):
        with tempfile.TemporaryDirectory(prefix="survey-binding-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            binding = "runs/laboratory_stewardship/r1/completion_basis.json"
            first_id = "20260716T120000Z-bound"
            survey.start_survey(root, first_id, "LOCAL_FULL", [binding])
            packet = root / "runs/laboratory_surveys" / first_id
            (packet / "report.md").write_text("# Bound report\n", encoding="utf-8")
            result, code = survey.finalize_survey(root, first_id)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "FRESH")
            completion = root / binding
            completion.write_text('{"status":"TAMPERED"}\n', encoding="utf-8")
            freshness, code = survey.check_freshness(root)
            self.assertEqual(code, 2)
            self.assertEqual(freshness["freshness"], "STALE")
            self.assertEqual(
                freshness["changed_external_bindings"],
                [f"<external-binding:{binding}>"],
            )

            second_id = "20260716T120100Z-bound-drift"
            survey.start_survey(root, second_id, "LOCAL_FULL", [binding])
            second_packet = root / "runs/laboratory_surveys" / second_id
            (second_packet / "report.md").write_text("# Drift report\n", encoding="utf-8")
            completion.write_text('{"status":"CHANGED_AGAIN"}\n', encoding="utf-8")
            result, code = survey.finalize_survey(root, second_id)
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "DRIFT_DETECTED")
            self.assertIn(f"<external-binding:{binding}>", result["changed_paths"])

    def test_start_seal_rejects_removed_bindings_before_finalize(self):
        with tempfile.TemporaryDirectory(prefix="survey-seal-binding-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            binding = "runs/laboratory_stewardship/r1/completion_basis.json"
            survey_id = "20260716T121000Z-sealed-bindings"
            survey.start_survey(root, survey_id, "LOCAL_FULL", [binding])
            packet = root / "runs/laboratory_surveys" / survey_id
            seal = packet / "start_seal.json"
            self.assertEqual(stat.S_IMODE(seal.stat().st_mode), 0o444)
            (packet / "report.md").write_text("# Bound report\n", encoding="utf-8")
            manifest_path = packet / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["external_bindings"] = []
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(survey.SurveyError, "start seal"):
                survey.finalize_survey(root, survey_id)

    def test_stable_finalize_and_later_staleness(self):
        with tempfile.TemporaryDirectory(prefix="survey-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260715T120000Z-test"
            self.assertEqual(self.quiet_run(["--root", str(root), "start", "--survey-id", survey_id]), 0)
            report = root / "runs/laboratory_surveys" / survey_id / "report.md"
            report.write_text("# Stable report\n", encoding="utf-8")
            self.assertEqual(
                self.quiet_run(["--root", str(root), "finalize", "--survey-id", survey_id]),
                0,
            )
            state = json.loads((root / "knowledge/laboratory_survey_state.json").read_text())
            self.assertEqual(state["freshness"], "FRESH")
            self.assertEqual((root / "knowledge/laboratory_overview.md").read_text(), "# Stable report\n")
            self.assertEqual(self.quiet_run(["--root", str(root), "check"]), 0)
            (root / "problems/active/p1/status.yaml").write_text(
                '{"status":"CANDIDATE"}\n', encoding="utf-8"
            )
            self.assertEqual(self.quiet_run(["--root", str(root), "check"]), 2)

    def test_changed_authoritative_report_is_stale(self):
        with tempfile.TemporaryDirectory(prefix="survey-report-tamper-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T122000Z-report-tamper"
            survey.start_survey(root, survey_id, "LOCAL_FULL")
            report = root / "runs/laboratory_surveys" / survey_id / "report.md"
            report.write_text("# Authoritative report\n", encoding="utf-8")
            result, code = survey.finalize_survey(root, survey_id)
            self.assertEqual(code, 0)
            self.assertEqual(result["status"], "FRESH")
            report.write_text("# Rewritten after finalization\n", encoding="utf-8")
            freshness, code = survey.check_freshness(root)
            self.assertEqual(code, 2)
            self.assertEqual(freshness["freshness"], "STALE")
            self.assertIn("report", freshness["changed_authoritative_artifacts"])
            self.assertIn("overview", freshness["changed_authoritative_artifacts"])

    def test_finalize_recovers_publication_after_stable_manifest(self):
        with tempfile.TemporaryDirectory(prefix="survey-finalize-resume-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T122500Z-finalize-resume"
            survey.start_survey(root, survey_id, "LOCAL_FULL")
            report = root / "runs/laboratory_surveys" / survey_id / "report.md"
            report.write_text("# Recoverable report\n", encoding="utf-8")
            result, code = survey.finalize_survey(root, survey_id)
            self.assertEqual((result["status"], code), ("FRESH", 0))
            state = root / "knowledge/laboratory_survey_state.json"
            state.unlink()
            (root / "knowledge/laboratory_overview.md").write_text(
                "# Interrupted publication\n", encoding="utf-8"
            )
            result, code = survey.finalize_survey(root, survey_id)
            self.assertEqual((result["status"], code), ("FRESH", 0))
            self.assertEqual(
                (root / "knowledge/laboratory_overview.md").read_text(encoding="utf-8"),
                "# Recoverable report\n",
            )
            self.assertEqual(survey.check_freshness(root)[1], 0)

    def test_start_recovers_after_partial_packet_crash(self):
        with tempfile.TemporaryDirectory(prefix="survey-start-resume-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T122700Z-start-resume"
            packet = root / "runs/laboratory_surveys" / survey_id
            original_create = survey.atomic_create

            def fail_manifest(path, data, lab_root, mode=0o644):
                if path == packet / "manifest.json":
                    raise survey.SurveyError("synthetic manifest crash")
                return original_create(path, data, lab_root, mode)

            with mock.patch.object(survey, "atomic_create", side_effect=fail_manifest):
                with self.assertRaisesRegex(survey.SurveyError, "manifest crash"):
                    survey.start_survey(root, survey_id, "LOCAL_FULL")
            self.assertTrue((packet / "inventory.json").is_file())
            self.assertFalse((packet / "start_seal.json").exists())
            result = survey.start_survey(root, survey_id, "LOCAL_FULL")
            self.assertEqual(result["status"], "IN_PROGRESS")
            self.assertTrue((packet / "start_seal.json").is_file())

    def test_atomic_create_never_publishes_partial_final_leaf(self):
        with tempfile.TemporaryDirectory(prefix="survey-atomic-create-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            target = root / "runs/laboratory_surveys/partial.bin"

            def partial_write(descriptor, data):
                os.write(descriptor, data[:3])
                raise survey.SurveyError("synthetic interrupted write")

            with mock.patch.object(survey, "_write_all", side_effect=partial_write):
                with self.assertRaisesRegex(survey.SurveyError, "interrupted"):
                    survey.atomic_create(target, b"complete payload", root)
            self.assertFalse(target.exists())

    def test_append_refuses_preexisting_hardlink(self):
        with tempfile.TemporaryDirectory(prefix="survey-hardlink-test-") as temp:
            base = Path(temp)
            root = base / "lab"
            root.mkdir()
            self.make_lab(root)
            outside = base / "outside.log"
            outside.write_bytes(b"outside\n")
            journal = root / "runs/laboratory_stewardship/r1/apply_journal.jsonl"
            try:
                os.link(outside, journal)
            except OSError:
                self.skipTest("hardlinks unavailable")
            with self.assertRaisesRegex(survey.SurveyError, "single-link"):
                survey.append_bytes(journal, b"attack\n", root)
            self.assertEqual(outside.read_bytes(), b"outside\n")

    def test_append_cas_detects_hardlink_added_after_initial_read(self):
        with tempfile.TemporaryDirectory(prefix="survey-hardlink-race-test-") as temp:
            base = Path(temp)
            root = base / "lab"
            root.mkdir()
            self.make_lab(root)
            journal = root / "runs/laboratory_stewardship/r1/apply_journal.jsonl"
            journal.write_bytes(b"initial\n")
            outside = base / "outside-link.log"
            original_replace = survey.atomic_replace

            def race_replace(path, data, lab_root, mode=0o644, **kwargs):
                os.link(journal, outside)
                return original_replace(path, data, lab_root, mode, **kwargs)

            with mock.patch.object(survey, "atomic_replace", side_effect=race_replace):
                with self.assertRaises(survey.SurveyError):
                    survey.append_bytes(journal, b"new\n", root)
            self.assertEqual(journal.read_bytes(), b"initial\n")
            self.assertEqual(outside.read_bytes(), b"initial\n")

    def test_old_stable_packet_cannot_roll_back_newer_latest_state(self):
        with tempfile.TemporaryDirectory(prefix="survey-latest-rollback-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            first = "20260716T122800Z-first"
            second = "20260716T122900Z-second"
            for survey_id in (first, second):
                survey.start_survey(root, survey_id, "LOCAL_FULL")
                packet = root / "runs/laboratory_surveys" / survey_id
                (packet / "report.md").write_text(f"# {survey_id}\n", encoding="utf-8")
                result, code = survey.finalize_survey(root, survey_id)
                self.assertEqual((result["status"], code), ("FRESH", 0))
                if survey_id == first:
                    first_state = (
                        root / "knowledge/laboratory_survey_state.json"
                    ).read_bytes()
                    first_overview = (
                        root / "knowledge/laboratory_overview.md"
                    ).read_bytes()
            (root / "knowledge/laboratory_survey_state.json").write_bytes(first_state)
            (root / "knowledge/laboratory_overview.md").write_bytes(first_overview)
            recovered, recovered_code = survey.finalize_survey(root, second)
            self.assertEqual((recovered["status"], recovered_code), ("FRESH", 0))
            with self.assertRaisesRegex(survey.SurveyError, "newer latest survey"):
                survey.finalize_survey(root, first)
            state = json.loads(
                (root / "knowledge/laboratory_survey_state.json").read_text()
            )
            self.assertEqual(state["latest_survey_id"], second)

    def test_newer_stable_packet_replaces_structurally_valid_stale_pointer(self):
        with tempfile.TemporaryDirectory(prefix="survey-stale-successor-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            first = "20260812T221000Z-stale-first"
            survey.start_survey(root, first, "LOCAL_FULL")
            first_packet = root / "runs/laboratory_surveys" / first
            (first_packet / "report.md").write_text("# First\n", encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, first)[1], 0)

            (root / "problems/active/p1/status.yaml").write_text(
                '{"status":"CHANGED"}\n', encoding="utf-8"
            )
            freshness, code = survey.check_freshness(root)
            self.assertEqual((freshness["freshness"], code), ("STALE", 2))
            self.assertEqual(freshness["artifact_errors"], [])
            self.assertEqual(freshness["changed_authoritative_artifacts"], [])
            self.assertEqual(freshness["changed_external_bindings"], [])

            second = "20260812T221100Z-fresh-successor"
            survey.start_survey(root, second, "LOCAL_FULL")
            second_packet = root / "runs/laboratory_surveys" / second
            (second_packet / "report.md").write_text("# Second\n", encoding="utf-8")
            result, result_code = survey.finalize_survey(root, second)
            self.assertEqual((result["status"], result_code), ("FRESH", 0))
            state = json.loads(
                (root / "knowledge/laboratory_survey_state.json").read_text()
            )
            self.assertEqual(state["latest_survey_id"], second)

    def test_newer_packet_refuses_tampered_stale_authoritative_artifact(self):
        with tempfile.TemporaryDirectory(prefix="survey-stale-tamper-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            first = "20260812T221200Z-tampered-first"
            survey.start_survey(root, first, "LOCAL_FULL")
            first_packet = root / "runs/laboratory_surveys" / first
            (first_packet / "report.md").write_text("# First\n", encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, first)[1], 0)
            (first_packet / "report.md").write_text("# Tampered\n", encoding="utf-8")

            second = "20260812T221300Z-refused-second"
            survey.start_survey(root, second, "LOCAL_FULL")
            second_packet = root / "runs/laboratory_surveys" / second
            (second_packet / "report.md").write_text("# Second\n", encoding="utf-8")
            with self.assertRaisesRegex(
                survey.SurveyError, "existing latest survey state is inconsistent"
            ):
                survey.finalize_survey(root, second)

    def test_drifted_old_packet_cannot_roll_back_newer_latest_state(self):
        with tempfile.TemporaryDirectory(prefix="survey-drift-rollback-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            first = "20260716T123000Z-drift-first"
            survey.start_survey(root, first, "LOCAL_FULL")
            first_packet = root / "runs/laboratory_surveys" / first
            (first_packet / "report.md").write_text("# First\n", encoding="utf-8")
            status_path = root / "problems/active/p1/status.yaml"
            original_status = status_path.read_bytes()
            status_path.write_text('{"status":"CHANGED"}\n', encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, first)[1], 2)
            status_path.write_bytes(original_status)

            second = "20260716T123100Z-fresh-second"
            survey.start_survey(root, second, "LOCAL_FULL")
            second_packet = root / "runs/laboratory_surveys" / second
            (second_packet / "report.md").write_text("# Second\n", encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, second)[1], 0)
            with self.assertRaisesRegex(survey.SurveyError, "newer latest survey"):
                survey.finalize_survey(root, first)
            first_manifest = json.loads(
                (first_packet / "manifest.json").read_text()
            )
            self.assertEqual(first_manifest["status"], "DRIFT_DETECTED")
            state = json.loads(
                (root / "knowledge/laboratory_survey_state.json").read_text()
            )
            self.assertEqual(state["latest_survey_id"], second)

    def test_root_inode_is_pinned_before_any_write(self):
        with tempfile.TemporaryDirectory(prefix="survey-root-pin-test-") as temp:
            base = Path(temp)
            root = base / "lab"
            root.mkdir()
            self.make_lab(root)
            survey.require_lab_identity(root)
            moved = base / "original-lab"
            root.rename(moved)
            root.mkdir()
            with self.assertRaisesRegex(survey.SurveyError, "root identity changed"):
                survey.atomic_create(root / "escape.txt", b"no write\n", root)
            self.assertFalse((root / "escape.txt").exists())

    def test_state_metadata_and_overview_tamper_are_stale(self):
        with tempfile.TemporaryDirectory(prefix="survey-state-tamper-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T123200Z-state-tamper"
            survey.start_survey(root, survey_id, "LOCAL_FULL")
            packet = root / "runs/laboratory_surveys" / survey_id
            (packet / "report.md").write_text("# Stable state\n", encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, survey_id)[1], 0)
            state_path = root / "knowledge/laboratory_survey_state.json"
            state = json.loads(state_path.read_text())
            state["completed_at_utc"] = "1900-01-01T00:00:00Z"
            state_path.write_text(json.dumps(state) + "\n", encoding="utf-8")
            freshness, code = survey.check_freshness(root)
            self.assertEqual((freshness["freshness"], code), ("STALE", 2))
            survey.finalize_survey(root, survey_id)
            (root / "knowledge/laboratory_overview.md").write_text(
                "# Wrong visible overview\n", encoding="utf-8"
            )
            freshness, code = survey.check_freshness(root)
            self.assertEqual((freshness["freshness"], code), ("STALE", 2))
            self.assertIn("overview", freshness["changed_authoritative_artifacts"])

    def test_finalize_rechecks_freshness_after_publication(self):
        with tempfile.TemporaryDirectory(prefix="survey-post-publish-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T123250Z-post-publish"
            survey.start_survey(root, survey_id, "LOCAL_FULL")
            packet = root / "runs/laboratory_surveys" / survey_id
            (packet / "report.md").write_text("# Post publication\n", encoding="utf-8")
            state_path = root / "knowledge/laboratory_survey_state.json"
            included = root / "problems/active/p1/status.yaml"
            original_replace = survey.atomic_replace

            def mutate_after_state(path, data, lab_root, mode=0o644, **kwargs):
                result = original_replace(path, data, lab_root, mode, **kwargs)
                if path == state_path:
                    included.write_text('{"status":"CONCURRENT"}\n', encoding="utf-8")
                return result

            with mock.patch.object(
                survey, "atomic_replace", side_effect=mutate_after_state
            ):
                result, code = survey.finalize_survey(root, survey_id)
            self.assertEqual(code, 2)
            self.assertEqual(result["status"], "STALE_AFTER_PUBLICATION")

    def test_explicit_literature_mode_cannot_drop_bound_delta_on_retry(self):
        with tempfile.TemporaryDirectory(prefix="survey-literature-retry-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260716T123300Z-literature"
            survey.start_survey(
                root, survey_id, "LOCAL_WITH_EXPLICIT_LITERATURE_DELTA"
            )
            packet = root / "runs/laboratory_surveys" / survey_id
            (packet / "report.md").write_text("# Literature report\n", encoding="utf-8")
            delta = packet / "literature_delta.md"
            delta.write_text("# Dated delta\n", encoding="utf-8")
            status_path = root / "problems/active/p1/status.yaml"
            original = status_path.read_bytes()
            status_path.write_text('{"status":"DRIFT"}\n', encoding="utf-8")
            self.assertEqual(survey.finalize_survey(root, survey_id)[1], 2)
            status_path.write_bytes(original)
            delta.unlink()
            with self.assertRaisesRegex(survey.SurveyError, "requires literature_delta"):
                survey.finalize_survey(root, survey_id)

    def test_write_commands_refuse_non_laboratory_identity(self):
        with tempfile.TemporaryDirectory(prefix="survey-identity-test-") as temp:
            root = Path(temp)
            (root / "knowledge").mkdir()
            with self.assertRaisesRegex(survey.SurveyError, "neither a generated"):
                survey.start_survey(root, "20260716T123000Z-not-a-lab", "LOCAL_FULL")

            (root / "AGENTS.md").write_text(
                "This repository is a long-lived mathematical research laboratory.\n",
                encoding="utf-8",
            )
            (root / "scripts").mkdir()
            (root / "scripts/doctor.py").write_text("# marker\n", encoding="utf-8")
            (root / "scripts/run_evals.py").write_text("# marker\n", encoding="utf-8")
            with self.assertRaisesRegex(survey.SurveyError, "BOOTSTRAP_REPORT"):
                survey.start_survey(root, "20260716T123100Z-scaffold", "LOCAL_FULL")

    def test_openat_write_refuses_symlinked_survey_parent(self):
        with tempfile.TemporaryDirectory(prefix="survey-symlink-parent-test-") as temp:
            root = Path(temp) / "lab"
            outside = Path(temp) / "outside"
            root.mkdir()
            outside.mkdir()
            self.make_lab(root)
            surveys = root / "runs/laboratory_surveys"
            surveys.rmdir()
            try:
                surveys.symlink_to(outside, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            with self.assertRaises(survey.SurveyError):
                survey.start_survey(root, "20260716T124000Z-no-follow", "LOCAL_FULL")
            self.assertEqual(list(outside.iterdir()), [])

    def test_drift_prevents_latest_update(self):
        with tempfile.TemporaryDirectory(prefix="survey-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            survey_id = "20260715T120100Z-drift"
            self.assertEqual(self.quiet_run(["--root", str(root), "start", "--survey-id", survey_id]), 0)
            packet = root / "runs/laboratory_surveys" / survey_id
            (packet / "report.md").write_text("# Drifted report\n", encoding="utf-8")
            (root / "research/checkpoints/new.md").write_text("new evidence\n", encoding="utf-8")
            self.assertEqual(
                self.quiet_run(["--root", str(root), "finalize", "--survey-id", survey_id]),
                2,
            )
            manifest = json.loads((packet / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "DRIFT_DETECTED")
            self.assertEqual((root / "knowledge/laboratory_overview.md").read_text(), "# No survey\n")
            state = json.loads((root / "knowledge/laboratory_survey_state.json").read_text())
            self.assertEqual(state["freshness"], "NONE")

    def test_none_and_symlink_is_not_followed(self):
        with tempfile.TemporaryDirectory(prefix="survey-test-") as temp:
            root = Path(temp)
            self.make_lab(root)
            self.assertEqual(self.quiet_run(["--root", str(root), "check"]), 3)
            outside = root / "outside.txt"
            outside.write_text("secret\n", encoding="utf-8")
            link = root / "research/checkpoints/link.md"
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable")
            snapshot = survey.build_snapshot(root)
            self.assertIn(
                "research/checkpoints/link.md",
                [item["path"] for item in snapshot["skipped"]],
            )


if __name__ == "__main__":
    unittest.main()
