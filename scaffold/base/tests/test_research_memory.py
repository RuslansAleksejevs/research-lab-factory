from __future__ import annotations

import contextlib
import copy
import ast
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/research_memory.py"
SCHEMA = Path(__file__).resolve().parents[1] / "schemas/research_checkpoint.schema.json"
TEMPLATE = Path(__file__).resolve().parents[1] / "templates/research_checkpoint.json"
SPEC = importlib.util.spec_from_file_location("research_memory_under_test", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load {SCRIPT}")
memory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(memory)


class ResearchMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="research-memory-test-")
        self.root = Path(self.temporary.name)
        (self.root / "research/checkpoints").mkdir(parents=True)
        (self.root / "research/checkpoints/README.md").write_text(
            "# Append-only checkpoints\n", encoding="utf-8"
        )
        (self.root / "research/checkpoint_index.json").write_bytes(
            memory.canonical_json_bytes(
                {"schema_version": 1, "checkpoint_count": 0, "entries": []}
            )
        )
        self.original_root = memory.ROOT
        memory.ROOT = self.root

    def tearDown(self) -> None:
        memory.ROOT = self.original_root
        self.temporary.cleanup()

    def payload(
        self,
        checkpoint_id: str = "20260804T120000Z-alpha",
        *,
        recorded_at: str = "2026-08-04T12:00:00Z",
        research_date: object = "2026-08-04",
        status: str = "PARTIAL",
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "checkpoint_id": checkpoint_id,
            "research_date": research_date,
            "recorded_at_utc": recorded_at,
            "outcome_status": status,
            "target": "Decide the exact bounded target.",
            "scope": "Finite objects over the specified coefficient ring only.",
            "outcome": {
                "summary": "Reduced the target to one explicit matrix calculation.",
                "generality": "All objects in the stated finite scope.",
                "remaining_unproved": "The matrix rank has not been independently checked.",
            },
            "verification": {
                "state": "SELF_CHECKED",
                "summary": "Definitions and two boundary cases were checked.",
                "independence": "No independent verification was performed.",
            },
            "continuation": {
                "next_action": "Compute the remaining matrix rank.",
                "cheapest_falsifier": "Find a nonzero kernel vector.",
                "success_criterion": "Decide whether the kernel is zero.",
                "stop_condition": "Stop when the rank is decided or the matrix is ill-posed.",
            },
            "discovery": {
                "topics": ["Exact comparison"],
                "objects": ["Kernel matrix"],
                "methods": ["Explicit calculation"],
            },
        }

    def revision_binding(
        self,
        predecessor_ids: list[str],
        *,
        suffix: str,
        predecessor_digests: Optional[dict[str, str]] = None,
    ) -> dict[str, object]:
        base = self.root / "reviews/revisions"
        base.mkdir(parents=True, exist_ok=True)
        bodies = {
            "finding": f"Reviewer finding for {suffix}.\n".encode(),
            "preimage": f"Preserved preimage for {suffix}.\n".encode(),
            "revision": f"Correcting revision for {suffix}.\n".encode(),
        }
        result: dict[str, object] = {}
        for key, data in bodies.items():
            relative = f"reviews/revisions/{suffix}-{key}.md"
            (self.root / relative).write_bytes(data)
            result[key] = {
                "path": relative,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        digests = predecessor_digests or {}
        result["predecessor_checkpoints"] = [
            {
                "checkpoint_id": checkpoint_id,
                "sha256": digests.get(checkpoint_id, "0" * 64),
            }
            for checkpoint_id in predecessor_ids
        ]
        return result

    def input_file(self, value: object, name: str = "input.json") -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def invoke(self, argv: list[str]) -> tuple[int, dict[str, object], str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = memory.run(argv)
        output = json.loads(stdout.getvalue()) if stdout.getvalue() else {}
        return code, output, stderr.getvalue()

    def record(self, value: dict[str, object], input_name: str = "input.json") -> dict[str, object]:
        checkpoint_id = str(value["checkpoint_id"])
        source = self.input_file(value, input_name)
        code, output, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                f"research/checkpoints/{checkpoint_id}.md",
                "--input",
                str(source),
            ]
        )
        self.assertEqual(code, 0, error)
        return output

    def error_record(
        self,
        value: dict[str, object],
        *,
        path: Optional[str] = None,
        input_name: str = "bad.json",
    ) -> str:
        source = self.input_file(value, input_name)
        path = path or f"research/checkpoints/{value.get('checkpoint_id', 'bad')}.md"
        code, _, error = self.invoke(
            ["record", "--checkpoint-path", path, "--input", str(source)]
        )
        self.assertEqual(code, 2)
        return json.loads(error)["error"]

    def test_single_day_record_is_canonical_and_omits_optional_sections(self) -> None:
        value = self.payload()
        del value["outcome"]["generality"]
        del value["outcome"]["remaining_unproved"]
        del value["verification"]["independence"]
        for key in ("cheapest_falsifier", "success_criterion", "stop_condition"):
            del value["continuation"][key]
        result = self.record(value)
        self.assertFalse(result["idempotent"])
        checkpoint = self.root / "research/checkpoints/20260804T120000Z-alpha.md"
        data = checkpoint.read_bytes()
        self.assertIn(memory.COMMENT_START.encode(), data)
        self.assertNotIn(b"## Examples", data)
        self.assertNotIn(b"## Failed routes", data)
        self.assertNotIn(b"Generality established", data)
        self.assertNotIn(b"Remaining unproved or unaudited", data)
        self.assertNotIn(b"Independence state", data)
        self.assertNotIn(b"Cheapest falsifier", data)
        self.assertNotIn(b"Success criterion", data)
        self.assertNotIn(b"Stop condition", data)
        parsed = memory.parse_checkpoint(data, checkpoint.relative_to(self.root).as_posix())
        self.assertEqual(parsed["research_date"], "2026-08-04")
        index = json.loads((self.root / "research/checkpoint_index.json").read_text())
        self.assertEqual(index["checkpoint_count"], 1)
        self.assertEqual(index["entries"][0]["path"], "research/checkpoints/20260804T120000Z-alpha.md")
        self.assertEqual(index["entries"][0]["sha256"], memory.hashlib.sha256(data).hexdigest())
        self.assertNotIn(str(self.root), json.dumps(index))
        self.assertNotIn("generated_at", index)
        code, output, error = self.invoke(["validate"])
        self.assertEqual((code, output["status"]), (0, "VALID"), error)

    def test_date_range_is_exact_and_searches_by_overlap(self) -> None:
        value = self.payload(
            "20260806T120000Z-range",
            recorded_at="2026-08-06T12:00:00Z",
            research_date={"start": "2026-08-02", "end": "2026-08-05"},
        )
        self.record(value)
        code, output, error = self.invoke(
            ["search", "--date-from", "2026-08-05", "--date-to", "2026-08-05"]
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(output["count"], 1)
        code, output, error = self.invoke(["search", "--date-from", "2026-08-06"])
        self.assertEqual(code, 0, error)
        self.assertEqual(output["count"], 0)

    def test_control_room_maximum_round_attempt_checkpoint_stem_is_accepted(self) -> None:
        round_id = "r" + "a" * 95
        attempt_id = "att-" + "b" * 32
        checkpoint_id = f"{round_id}-{attempt_id}"
        self.assertEqual(len(round_id), 96)
        self.assertEqual(len(checkpoint_id), 133)
        value = self.payload(checkpoint_id)
        value["round_id"] = round_id
        value["run_id"] = attempt_id
        result = self.record(value, "control-room-boundary.json")
        self.assertEqual(result["checkpoint_id"], checkpoint_id)
        self.assertEqual(self.invoke(["validate"])[0], 0)

    def test_control_room_validation_is_exact_and_read_only(self) -> None:
        round_id = "rr-exact-memory"
        run_id = "att-" + "a" * 32
        checkpoint_id = f"{round_id}-{run_id}"
        value = self.payload(checkpoint_id)
        value["round_id"] = round_id
        value["run_id"] = run_id
        self.record(value, "control-room-exact.json")
        checkpoint_path = f"research/checkpoints/{checkpoint_id}.md"
        before = {
            path.relative_to(self.root).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in sorted((self.root / "research").rglob("*"))
            if path.is_file()
        }
        code, output, error = self.invoke(
            [
                "validate-control-room",
                "--checkpoint-path",
                checkpoint_path,
                "--checkpoint-id",
                checkpoint_id,
                "--round-id",
                round_id,
                "--run-id",
                run_id,
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(
            output,
            {
                "status": "VALID",
                "checkpoint_count": 1,
                "checkpoint_id": checkpoint_id,
                "checkpoint_path": checkpoint_path,
                "checkpoint_sha256": hashlib.sha256(
                    before[checkpoint_path][0]
                ).hexdigest(),
                "checkpoint_size": len(before[checkpoint_path][0]),
                "index_path": "research/checkpoint_index.json",
                "index_sha256": hashlib.sha256(
                    before["research/checkpoint_index.json"][0]
                ).hexdigest(),
                "index_size": len(before["research/checkpoint_index.json"][0]),
                "round_id": round_id,
                "run_id": run_id,
            },
        )
        after = {
            path.relative_to(self.root).as_posix(): (
                path.read_bytes(),
                path.stat().st_mtime_ns,
            )
            for path in sorted((self.root / "research").rglob("*"))
            if path.is_file()
        }
        self.assertEqual(after, before)

        for option, wrong in (
            ("--checkpoint-id", checkpoint_id + "-wrong"),
            ("--round-id", "rr-wrong-memory"),
            ("--run-id", "att-" + "b" * 32),
        ):
            arguments = [
                "validate-control-room",
                "--checkpoint-path",
                checkpoint_path,
                "--checkpoint-id",
                checkpoint_id,
                "--round-id",
                round_id,
                "--run-id",
                run_id,
            ]
            arguments[arguments.index(option) + 1] = wrong
            with self.subTest(option=option):
                code, output, error = self.invoke(arguments)
                self.assertEqual(code, 2)
                self.assertEqual(output, {})
                self.assertIn("error", json.loads(error))

    def test_safe_reads_reject_fifo_swap_without_blocking(self) -> None:
        regular = self.root / "regular-snapshot"
        regular.write_bytes(b"safe")
        fifo = self.root / "fifo-swap"
        os.mkfifo(fifo)
        directory_descriptor = os.open(
            self.root,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        started = time.monotonic()
        try:
            with (
                mock.patch.object(memory, "_stat_at", return_value=regular.stat()),
                self.assertRaises(memory.ResearchMemoryError),
            ):
                memory._safe_read_at(
                    directory_descriptor,
                    fifo.name,
                    "raced checkpoint",
                    1024,
                    single_link=True,
                )
            with (
                mock.patch.object(memory, "_lstat", return_value=regular.stat()),
                self.assertRaises(memory.ResearchMemoryError),
            ):
                memory._safe_read_bytes(
                    fifo,
                    "raced checkpoint",
                    1024,
                    single_link=True,
                )
        finally:
            os.close(directory_descriptor)
        self.assertLess(time.monotonic() - started, 1.0)

    def test_control_room_validation_uses_inherited_directory_descriptors(self) -> None:
        round_id = "rr-descriptor-root"
        run_id = "att-" + "d" * 32
        checkpoint_id = f"{round_id}-{run_id}"
        value = self.payload(checkpoint_id)
        value["round_id"] = round_id
        value["run_id"] = run_id
        self.record(value, "descriptor-root.json")
        root_fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        research_fd = os.open(
            "research",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            dir_fd=root_fd,
        )
        checkpoints_fd = os.open(
            "checkpoints",
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            dir_fd=research_fd,
        )
        original = (
            memory.ROOT,
            memory._CONTROL_ROOM_ROOT_FD,
            memory._CONTROL_ROOM_RESEARCH_FD,
            memory._CONTROL_ROOM_CHECKPOINTS_FD,
        )
        # Keep the intentionally wrong synthetic root inside this test's
        # unique TemporaryDirectory so repeated and concurrent suites neither
        # collide nor leak state into the shared system temp directory.
        hostile = self.root / "hostile-synthetic-helper-root"
        hostile.mkdir()
        try:
            memory.ROOT = hostile
            memory._CONTROL_ROOM_ROOT_FD = root_fd
            memory._CONTROL_ROOM_RESEARCH_FD = research_fd
            memory._CONTROL_ROOM_CHECKPOINTS_FD = checkpoints_fd
            output = memory.validate_control_room(
                f"research/checkpoints/{checkpoint_id}.md",
                checkpoint_id,
                round_id,
                run_id,
            )
            self.assertEqual(output["status"], "VALID")
            self.assertEqual(output["checkpoint_id"], checkpoint_id)
        finally:
            (
                memory.ROOT,
                memory._CONTROL_ROOM_ROOT_FD,
                memory._CONTROL_ROOM_RESEARCH_FD,
                memory._CONTROL_ROOM_CHECKPOINTS_FD,
            ) = original
            os.close(checkpoints_fd)
            os.close(research_fd)
            os.close(root_fd)

    def test_control_room_validation_rejects_missing_bindings_and_stale_index(self) -> None:
        checkpoint_id = "rr-memory-att-missing"
        value = self.payload(checkpoint_id)
        self.record(value, "control-room-missing.json")
        arguments = [
            "validate-control-room",
            "--checkpoint-path",
            f"research/checkpoints/{checkpoint_id}.md",
            "--checkpoint-id",
            checkpoint_id,
            "--round-id",
            "rr-memory",
            "--run-id",
            "att-missing",
        ]
        code, output, error = self.invoke(arguments)
        self.assertEqual(code, 2)
        self.assertEqual(output, {})
        self.assertIn("round_id", json.loads(error)["error"])

        bound = self.payload("rr-memory-att-stale")
        bound["round_id"] = "rr-memory"
        bound["run_id"] = "att-stale"
        self.record(bound, "control-room-stale.json")
        stale_arguments = list(arguments)
        stale_arguments[stale_arguments.index("--checkpoint-path") + 1] = (
            "research/checkpoints/rr-memory-att-stale.md"
        )
        stale_arguments[stale_arguments.index("--checkpoint-id") + 1] = (
            "rr-memory-att-stale"
        )
        stale_arguments[stale_arguments.index("--run-id") + 1] = "att-stale"
        index_path = self.root / "research/checkpoint_index.json"
        index_path.write_bytes(
            memory.canonical_json_bytes(
                {"schema_version": 1, "checkpoint_count": 0, "entries": []}
            )
        )
        checkpoint_before = (
            self.root / "research/checkpoints/rr-memory-att-stale.md"
        ).read_bytes()
        stale_before = index_path.read_bytes()
        code, output, error = self.invoke(stale_arguments)
        self.assertEqual(code, 2)
        self.assertEqual(output, {})
        self.assertIn("stale or non-canonical", json.loads(error)["error"])
        self.assertEqual(index_path.read_bytes(), stale_before)
        self.assertEqual(
            (self.root / "research/checkpoints/rr-memory-att-stale.md").read_bytes(),
            checkpoint_before,
        )

    def test_invalid_dates_ranges_and_timestamp_are_rejected_before_write(self) -> None:
        invalid_values = []
        bad_day = self.payload("bad-day")
        bad_day["research_date"] = "2026-02-30"
        invalid_values.append((bad_day, "calendar date"))
        backward = self.payload("backward")
        backward["research_date"] = {"start": "2026-08-05", "end": "2026-08-04"}
        invalid_values.append((backward, "must not be after"))
        bad_timestamp = self.payload("bad-time")
        bad_timestamp["recorded_at_utc"] = "2026-08-04T12:00:00+00:00"
        invalid_values.append((bad_timestamp, "exact UTC timestamp"))
        for index, (value, fragment) in enumerate(invalid_values):
            with self.subTest(fragment=fragment):
                error = self.error_record(value, input_name=f"invalid-{index}.json")
                self.assertIn(fragment, error)
        self.assertEqual(
            sorted(path.name for path in (self.root / "research/checkpoints").iterdir()),
            ["README.md"],
        )

    def test_idempotence_requires_exact_rendered_bytes_and_never_overwrites(self) -> None:
        value = self.payload()
        first = self.record(value)
        target = self.root / "research/checkpoints/20260804T120000Z-alpha.md"
        before = target.read_bytes()
        second = self.record(copy.deepcopy(value), "same.json")
        self.assertFalse(first["idempotent"])
        self.assertTrue(second["idempotent"])
        changed = copy.deepcopy(value)
        changed["outcome"]["summary"] = "A conflicting replacement result."
        error = self.error_record(changed, input_name="changed.json")
        self.assertIn("different bytes", error)
        self.assertEqual(target.read_bytes(), before)

    def test_count_bound_is_preflighted_before_the_append_commit(self) -> None:
        first_value = self.payload("count-bound-first")
        second_value = self.payload(
            "count-bound-second", recorded_at="2026-08-04T12:01:00Z"
        )
        with mock.patch.object(memory, "MAX_CHECKPOINTS", 1):
            first = self.record(first_value, "count-bound-first.json")
            checkpoint = self.root / "research/checkpoints/count-bound-first.md"
            index_path = self.root / "research/checkpoint_index.json"
            checkpoint_before = checkpoint.read_bytes()
            index_before = index_path.read_bytes()

            error = self.error_record(
                second_value, input_name="count-bound-second.json"
            )
            self.assertIn("count bound", error)
            self.assertFalse(
                (self.root / "research/checkpoints/count-bound-second.md").exists()
            )
            self.assertEqual(checkpoint.read_bytes(), checkpoint_before)
            self.assertEqual(index_path.read_bytes(), index_before)
            self.assertEqual(self.invoke(["validate"])[0], 0)

            retry = self.record(first_value, "count-bound-first-retry.json")
            self.assertFalse(first["idempotent"])
            self.assertTrue(retry["idempotent"])

    def test_total_size_bound_is_preflighted_before_the_append_commit(self) -> None:
        first_value = self.payload("size-bound-first")
        self.record(first_value, "size-bound-first.json")
        first_path = self.root / "research/checkpoints/size-bound-first.md"
        index_path = self.root / "research/checkpoint_index.json"
        checkpoint_before = first_path.read_bytes()
        index_before = index_path.read_bytes()

        second_value = self.payload(
            "size-bound-second", recorded_at="2026-08-04T12:01:00Z"
        )
        rendered_second = memory.render_checkpoint(
            memory.normalize_record(second_value)
        )
        too_small = len(checkpoint_before) + len(rendered_second) - 1
        with mock.patch.object(memory, "MAX_CHECKPOINT_TOTAL_BYTES", too_small):
            error = self.error_record(
                second_value, input_name="size-bound-second.json"
            )
            self.assertIn("total size bound", error)
            self.assertFalse(
                (self.root / "research/checkpoints/size-bound-second.md").exists()
            )
            self.assertEqual(first_path.read_bytes(), checkpoint_before)
            self.assertEqual(index_path.read_bytes(), index_before)
            self.assertEqual(self.invoke(["validate"])[0], 0)

            retry = self.record(first_value, "size-bound-first-retry.json")
            self.assertTrue(retry["idempotent"])

    def test_supersession_is_append_only_reasoned_and_indexed(self) -> None:
        first = self.payload()
        self.record(first)
        second = self.payload(
            "20260805T120000Z-correction",
            recorded_at="2026-08-05T12:00:00Z",
            status="SUPERSEDED",
        )
        second["supersedes"] = [first["checkpoint_id"]]
        second["related_checkpoints"] = [first["checkpoint_id"]]
        second["revision_reason"] = "A sign error changes the earlier coarse outcome."
        first_path = self.root / f"research/checkpoints/{first['checkpoint_id']}.md"
        second["revision_binding"] = self.revision_binding(
            [str(first["checkpoint_id"])],
            suffix="sign-correction",
            predecessor_digests={
                str(first["checkpoint_id"]): hashlib.sha256(first_path.read_bytes()).hexdigest()
            },
        )
        second["outcome"]["summary"] = "Corrected the sign error and withdrew the earlier reduction."
        self.record(second, "correction.json")
        second_path = self.root / f"research/checkpoints/{second['checkpoint_id']}.md"
        self.assertTrue(first_path.is_file())
        self.assertTrue(second_path.is_file())
        index = memory.validate_memory()
        by_id = {entry["checkpoint_id"]: entry for entry in index["entries"]}
        self.assertEqual(by_id[str(second["checkpoint_id"])]["supersedes"], [first["checkpoint_id"]])
        self.assertIn("revision_reason_summary", by_id[str(second["checkpoint_id"])])
        self.assertEqual(by_id[str(first["checkpoint_id"])]["superseded_by"], [second["checkpoint_id"]])
        self.assertEqual(by_id[str(first["checkpoint_id"])]["outcome_status"], "PARTIAL")

    def test_supersession_requires_reason_and_existing_predecessor(self) -> None:
        standalone = self.payload("standalone-superseded", status="SUPERSEDED")
        self.assertIn(
            "SUPERSEDED requires supersedes",
            self.error_record(standalone, input_name="standalone-superseded.json"),
        )
        no_reason = self.payload("20260805T120000Z-no-reason")
        no_reason["supersedes"] = ["20260804T120000Z-missing"]
        self.assertIn("revision_reason", self.error_record(no_reason, input_name="no-reason.json"))
        missing = self.payload("20260805T120100Z-missing-link")
        missing["supersedes"] = ["20260804T120000Z-missing"]
        missing["revision_reason"] = "Correction of a prior record."
        missing["revision_binding"] = self.revision_binding(
            ["20260804T120000Z-missing"], suffix="missing-predecessor"
        )
        error = self.error_record(missing, input_name="missing-link.json")
        self.assertIn("missing local supersedes link", error)
        self.assertFalse(
            (self.root / "research/checkpoints/20260805T120100Z-missing-link.md").exists()
        )

    def test_supersession_cycles_are_detected(self) -> None:
        self.record(self.payload("unrelated-to-cycle"))
        first = self.payload("cycle-a")
        first["supersedes"] = ["cycle-b"]
        first["revision_reason"] = "Synthetic cycle test."
        first["revision_binding"] = self.revision_binding(
            ["cycle-b"], suffix="cycle-a"
        )
        second = self.payload("cycle-b", recorded_at="2026-08-04T12:01:00Z")
        second["supersedes"] = ["cycle-a"]
        second["revision_reason"] = "Synthetic cycle test."
        second["revision_binding"] = self.revision_binding(
            ["cycle-a"], suffix="cycle-b"
        )
        for value in (first, second):
            normalized = memory.normalize_record(value)
            (self.root / f"research/checkpoints/{value['checkpoint_id']}.md").write_bytes(
                memory.render_checkpoint(normalized)
            )
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("supersession cycle", error)
        code, result, error = self.invoke(["search"])
        self.assertEqual(code, 0, error)
        self.assertEqual(result["index_status"], "PARTIAL_RECOVERY")
        self.assertEqual([item["checkpoint_id"] for item in result["matches"]], ["unrelated-to-cycle"])
        self.assertEqual(len(result["warnings"]), 2)

    def test_revision_and_artifact_hash_bindings_are_revalidated(self) -> None:
        first = self.payload()
        self.record(first)
        first_path = self.root / f"research/checkpoints/{first['checkpoint_id']}.md"
        second = self.payload(
            "20260805T130000Z-bound-correction",
            recorded_at="2026-08-05T13:00:00Z",
        )
        second["supersedes"] = [first["checkpoint_id"]]
        second["revision_reason"] = "A reviewer finding requires an exact correction."
        second["revision_binding"] = self.revision_binding(
            [str(first["checkpoint_id"])],
            suffix="bound-correction",
            predecessor_digests={
                str(first["checkpoint_id"]): hashlib.sha256(first_path.read_bytes()).hexdigest()
            },
        )
        self.record(second, "bound-correction.json")

        revision_path = self.root / second["revision_binding"]["revision"]["path"]
        revision_path.write_text("tampered revision\n", encoding="utf-8")
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("SHA-256 does not match", error)

        standalone = self.payload("missing-hash-bound-artifact")
        standalone["artifacts"] = [
            {
                "path": "reviews/does-not-exist.md",
                "role": "Claimed but absent evidence.",
                "sha256": "0" * 64,
            }
        ]
        error = self.error_record(standalone, input_name="missing-artifact.json")
        self.assertIn("missing artifacts[0]", error)

    def test_supersession_validation_handles_the_full_iterative_bound(self) -> None:
        records = []
        for index in range(memory.MAX_CHECKPOINTS):
            checkpoint_id = f"chain-{index:04d}"
            record = {"checkpoint_id": checkpoint_id}
            if index + 1 < memory.MAX_CHECKPOINTS:
                record["supersedes"] = [f"chain-{index + 1:04d}"]
            records.append({"record": record})
        memory._validate_links(records)

        records[-1]["record"]["supersedes"] = ["chain-0000"]
        with self.assertRaisesRegex(memory.ResearchMemoryError, "supersession cycle"):
            memory._validate_links(records)

    def test_strict_invalid_record_and_duplicate_keys_are_rejected(self) -> None:
        bad_status = self.payload("bad-status")
        bad_status["outcome_status"] = "COMPLETED"
        self.assertIn("outcome_status", self.error_record(bad_status, input_name="status.json"))
        unknown = self.payload("unknown-field")
        unknown["reasoning"] = "private scratch work"
        self.assertIn("unknown keys", self.error_record(unknown, input_name="unknown.json"))
        escaped_surrogate = json.dumps(self.payload("surrogate"))
        escaped_surrogate = escaped_surrogate.replace(
            '"Decide the exact bounded target."', '"\\ud800"'
        )
        surrogate_path = self.root / "surrogate.json"
        surrogate_path.write_text(escaped_surrogate, encoding="utf-8")
        code, _, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                "research/checkpoints/surrogate.md",
                "--input",
                str(surrogate_path),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("non-scalar Unicode surrogate", error)

        duplicate_path = self.root / "duplicate.json"
        duplicate_path.write_text(
            '{"schema_version":1,"schema_version":1}', encoding="utf-8"
        )
        code, _, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                "research/checkpoints/duplicate.md",
                "--input",
                str(duplicate_path),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("duplicate JSON key", error)

    def test_comment_terminator_text_is_safely_embedded(self) -> None:
        value = self.payload("comment-safe")
        value["target"] = "Decide whether A --> B is injective and compare x < y."
        self.record(value)
        data = (self.root / "research/checkpoints/comment-safe.md").read_bytes()
        self.assertEqual(data.count(memory.COMMENT_START.encode()), 1)
        embedded_area = data.split(memory.COMMENT_START.encode(), 1)[1].split(
            memory.COMMENT_END.encode(), 1
        )[0]
        self.assertNotIn(b"-->", embedded_area)
        memory.validate_memory()

    def test_unstructured_and_non_markdown_checkpoint_files_are_rejected(self) -> None:
        (self.root / "research/checkpoints/legacy.md").write_text(
            "# Unstructured legacy checkpoint\n", encoding="utf-8"
        )
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("designated v1 JSON comment", error)
        (self.root / "research/checkpoints/legacy.md").unlink()
        (self.root / "research/checkpoints/note.txt").write_text("note\n", encoding="utf-8")
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("must name", error)

    def test_index_freshness_is_exact_and_rebuild_repairs_only_the_index(self) -> None:
        value = self.payload()
        self.record(value)
        checkpoint = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
        checkpoint_before = checkpoint.read_bytes()
        index_path = self.root / "research/checkpoint_index.json"
        index_path.write_text('{"schema_version":1,"checkpoint_count":0,"entries":[]}\n')
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("stale or non-canonical", error)
        code, output, error = self.invoke(["rebuild-index"])
        self.assertEqual((code, output["status"]), (0, "REBUILT"), error)
        self.assertEqual(checkpoint.read_bytes(), checkpoint_before)
        self.assertEqual(self.invoke(["validate"])[0], 0)

    def test_tampered_canonical_checkpoint_cannot_be_reindexed(self) -> None:
        value = self.payload()
        self.record(value)
        checkpoint = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
        checkpoint.write_bytes(checkpoint.read_bytes() + b"\n")
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("strict canonical rendering", error)

    def test_search_recovers_disposable_index_without_changing_files(self) -> None:
        value = self.payload("useful-result-no-date-prefix")
        self.record(value)
        checkpoint = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
        original = checkpoint.read_bytes()
        index = self.root / "research/checkpoint_index.json"
        canonical = index.read_bytes()
        for damaged in [None, b'{"broken":', b'{"entries": []}', canonical + b'\n']:
            with self.subTest(damaged=damaged):
                if damaged is None:
                    index.unlink()
                else:
                    index.write_bytes(damaged)
                code, result, error = self.invoke(["search", "--query", "matrix"])
                self.assertEqual(code, 0, error)
                self.assertEqual(result['index_status'], 'REBUILT_IN_MEMORY')
                self.assertEqual(result['count'], 1)
                self.assertTrue(result['warnings'])
                self.assertEqual(checkpoint.read_bytes(), original)
                self.assertEqual(index.read_bytes() if index.exists() else None, damaged)
                self.assertEqual(self.invoke(["validate"])[0], 2)
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertEqual(index.read_bytes(), canonical)
        self.assertEqual(self.invoke(["search"])[1]['index_status'], 'CURRENT')

    def test_search_does_not_hide_damaged_records_or_follow_cache_symlink(self) -> None:
        value = self.payload("plain-name")
        self.record(value)
        healthy = self.payload("healthy-name")
        self.record(healthy)
        checkpoint = self.root / 'research/checkpoints/plain-name.md'
        original = checkpoint.read_bytes()
        checkpoint.write_bytes(original + b'\n')
        index = self.root / 'research/checkpoint_index.json'
        index_before = index.read_bytes()
        code, result, error = self.invoke(["search"])
        self.assertEqual(code, 0, error)
        self.assertEqual(result["index_status"], "PARTIAL_RECOVERY")
        self.assertEqual([item["checkpoint_id"] for item in result["matches"]], ["healthy-name"])
        self.assertIn("plain-name.md", result["warnings"][0])
        self.assertIn("strict canonical rendering", result["warnings"][0])
        self.assertEqual(index.read_bytes(), index_before)
        self.assertEqual(checkpoint.read_bytes(), original + b'\n')
        self.assertEqual(self.invoke(["validate"])[0], 2)
        self.assertEqual(self.invoke(["rebuild-index"])[0], 2)
        self.assertIn("strict canonical rendering", self.error_record(self.payload("unrelated-new")))
        checkpoint.write_bytes(original)
        index.unlink()
        outside = self.root / 'outside.json'
        outside.write_bytes(b'valuable original')
        index.symlink_to(outside)
        self.assertEqual(self.invoke(["search"])[0], 2)
        self.assertEqual(outside.read_bytes(), b'valuable original')

    def _bound_checkpoint(self, checkpoint_id: str) -> dict[str, object]:
        value = self.payload(checkpoint_id)
        artifact = self.root / (checkpoint_id + "-evidence.md")
        artifact.write_bytes(b"Exact synthetic evidence.\n")
        value["artifacts"] = [{"path": artifact.name, "role": "Synthetic fixture",
                               "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}]
        value["round_id"] = "round-" + checkpoint_id
        value["run_id"] = "run-" + checkpoint_id
        return value

    def _control_arguments(self, checkpoint_id: str) -> list[str]:
        return ["validate-control-room", "--checkpoint-path",
                f"research/checkpoints/{checkpoint_id}.md", "--checkpoint-id", checkpoint_id,
                "--round-id", "round-" + checkpoint_id, "--run-id", "run-" + checkpoint_id]

    def test_regular_finder_metadata_does_not_block_memory_operations(self) -> None:
        self.record(self._bound_checkpoint("finder-safe"))
        metadata = self.root / "research/checkpoints/.DS_Store"
        metadata.write_bytes(b"Synthetic Finder metadata\x00")
        before = (metadata.read_bytes(), metadata.stat().st_mtime_ns)
        for command in (["search"], ["validate"], ["rebuild-index"], self._control_arguments("finder-safe")):
            with self.subTest(command=command):
                code, result, error = self.invoke(command)
                self.assertEqual(code, 0, error)
                if command == ["search"]:
                    self.assertEqual(result["count"], 1)
                    self.assertEqual(result["warnings"], [])
        self.record(self.payload("finder-new"))
        self.assertEqual((metadata.read_bytes(), metadata.stat().st_mtime_ns), before)

    def test_finder_name_does_not_exempt_symlinks_specials_or_resource_limits(self) -> None:
        metadata = self.root / "research/checkpoints/.DS_Store"
        external = self.root / "external-sentinel"
        external.write_bytes(b"Must remain untouched.")
        for kind in ("symlink", "fifo", "oversized"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    metadata.symlink_to(external)
                elif kind == "fifo":
                    os.mkfifo(metadata)
                else:
                    metadata.write_bytes(b"x" * (memory.MAX_CHECKPOINT_BYTES + 1))
                for command in (["search"], ["validate"], ["rebuild-index"]):
                    self.assertEqual(self.invoke(command)[0], 2)
                self.error_record(self.payload("finder-unsafe"))
                self.assertFalse((self.root / "research/checkpoints/finder-unsafe.md").exists())
                metadata.unlink()
        self.assertEqual(external.read_bytes(), b"Must remain untouched.")

    def test_unrelated_stale_evidence_does_not_block_append_search_or_exact_control_target(self) -> None:
        for checkpoint_id in ("old-a", "healthy-b"):
            self.record(self._bound_checkpoint(checkpoint_id))
        old_checkpoint = self.root / "research/checkpoints/old-a.md"
        old_bytes = old_checkpoint.read_bytes()
        (self.root / "old-a-evidence.md").write_bytes(b"Changed historical artifact.\n")
        index = self.root / "research/checkpoint_index.json"
        before = index.read_bytes()
        code, result, error = self.invoke(["search"])
        self.assertEqual(code, 0, error)
        self.assertEqual(result["index_status"], "PARTIAL_RECOVERY")
        self.assertEqual([item["checkpoint_id"] for item in result["matches"]], ["healthy-b"])
        self.assertIn("old-a.md", result["warnings"][0])
        self.assertIn("SHA-256", result["warnings"][0])
        self.assertEqual(index.read_bytes(), before)
        self.assertEqual(self.invoke(self._control_arguments("healthy-b"))[0], 0)
        self.assertEqual(self.invoke(self._control_arguments("old-a"))[0], 2)
        self.assertEqual(self.invoke(["validate"])[0], 2)
        appended = self.record(self._bound_checkpoint("new-c"))
        self.assertEqual(appended["checkpoint_count"], 3)
        self.assertIn("old-a.md", appended["warnings"][0])
        self.assertEqual(old_checkpoint.read_bytes(), old_bytes)
        self.assertEqual(json.loads(index.read_bytes())["checkpoint_count"], 3)
        self.assertEqual(self.invoke(self._control_arguments("new-c"))[0], 0)
        index.write_bytes(before)
        code, _, error = self.invoke(self._control_arguments("healthy-b"))
        self.assertEqual(code, 2)
        self.assertIn("stale or non-canonical", error)
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertEqual(self.invoke(self._control_arguments("healthy-b"))[0], 0)
        self.assertEqual(self.invoke(["validate"])[0], 2)

    def test_missing_artifacts_are_reported_and_never_accepted_for_the_target(self) -> None:
        for missing_parent in (False, True):
            with self.subTest(missing_parent=missing_parent):
                checkpoint_id = "missing-parent" if missing_parent else "missing-leaf"
                value = self._bound_checkpoint(checkpoint_id)
                original = self.root / str(value["artifacts"][0]["path"])
                if missing_parent:
                    directory = self.root / "evidence-directory"
                    directory.mkdir()
                    original.rename(directory / "item.md")
                    value["artifacts"][0]["path"] = "evidence-directory/item.md"
                    original = directory / "item.md"
                self.record(value)
                original.unlink()
                if missing_parent:
                    directory.rmdir()
                code, result, error = self.invoke(["search"])
                self.assertEqual(code, 0, error)
                self.assertEqual(result["count"], 0)
                self.assertTrue(any(checkpoint_id + ".md" in warning for warning in result["warnings"]))
                self.assertEqual(self.invoke(self._control_arguments(checkpoint_id))[0], 2)
        self.assertTrue(self.record(self.payload("after-missing"))["warnings"])

    def test_broken_evidence_propagates_only_to_explicit_dependency_closure(self) -> None:
        self.record(self._bound_checkpoint("dependency-a"))
        for checkpoint_id, predecessor in (("dependency-b", "dependency-a"), ("dependency-c", "dependency-b")):
            value = self._bound_checkpoint(checkpoint_id)
            value["related_checkpoints"] = [predecessor]
            self.record(value)
        self.record(self._bound_checkpoint("independent-d"))
        (self.root / "dependency-a-evidence.md").write_bytes(b"Changed.\n")
        code, result, error = self.invoke(["search"])
        self.assertEqual(code, 0, error)
        self.assertEqual([item["checkpoint_id"] for item in result["matches"]], ["independent-d"])
        self.assertEqual(len(result["warnings"]), 3)
        self.assertEqual(self.invoke(self._control_arguments("dependency-c"))[0], 2)
        self.assertEqual(self.invoke(self._control_arguments("independent-d"))[0], 0)
        dependent = self.payload("new-dependent")
        dependent["related_checkpoints"] = ["dependency-c"]
        self.assertIn("SHA-256", self.error_record(dependent))
        self.assertFalse((self.root / "research/checkpoints/new-dependent.md").exists())

    def test_recovery_keeps_checkpoint_and_evidence_safety_failures_hard(self) -> None:
        self.record(self._bound_checkpoint("safe-a"))
        artifact = self.root / "safe-a-evidence.md"
        artifact.unlink()
        artifact.symlink_to(self.root / "input.json")
        self.assertEqual(self.invoke(["search"])[0], 2)
        self.error_record(self.payload("unsafe-unrelated"))
        artifact.unlink()
        artifact.write_bytes(b"Exact synthetic evidence.\n")
        checkpoint = self.root / "research/checkpoints/unsafe.md"
        checkpoint.symlink_to(self.root / "input.json")
        self.assertEqual(self.invoke(["search"])[0], 2)
        checkpoint.unlink()
        checkpoint.write_bytes(b"x" * (memory.MAX_CHECKPOINT_BYTES + 1))
        self.assertEqual(self.invoke(["search"])[0], 2)
        checkpoint.write_bytes(b"malformed checkpoint")
        with mock.patch.object(memory, "MAX_CHECKPOINTS", 1):
            self.assertEqual(self.invoke(["search"])[0], 2)
        with mock.patch.object(memory, "MAX_CHECKPOINT_TOTAL_BYTES", 1):
            self.assertEqual(self.invoke(["search"])[0], 2)

    def test_search_reports_missing_and_mismatched_links_without_hiding_their_healthy_predecessor(self) -> None:
        first = self.payload("healthy-predecessor")
        self.record(first)
        successor = self.payload("bad-revision-binding")
        successor["supersedes"] = ["healthy-predecessor"]
        successor["revision_reason"] = "Synthetic historical binding damage."
        successor["revision_binding"] = self.revision_binding(["healthy-predecessor"], suffix="bad-binding")
        missing = self.payload("missing-link")
        missing["related_checkpoints"] = ["absent-record"]
        for value in (successor, missing):
            checkpoint = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
            checkpoint.write_bytes(memory.render_checkpoint(memory.normalize_record(value)))
        code, result, error = self.invoke(["search"])
        self.assertEqual(code, 0, error)
        self.assertEqual([item["checkpoint_id"] for item in result["matches"]], ["healthy-predecessor"])
        self.assertEqual(len(result["warnings"]), 2)
        self.assertTrue(any("predecessor checkpoint SHA-256" in warning for warning in result["warnings"]))
        self.assertTrue(any("absent-record" in warning for warning in result["warnings"]))
        self.assertEqual(self.invoke(["rebuild-index"])[0], 2)

    def test_recoverable_first_artifact_does_not_mask_later_unsafe_evidence(self) -> None:
        value = self._bound_checkpoint("mixed-evidence")
        # Canonical artifacts sort by path: keep unsafe evidence after stale.
        later = self.root / "zz-later-evidence.md"
        later.write_bytes(b"Second exact artifact.\n")
        value["artifacts"].append({"path": later.name, "role": "Second bound artifact",
                                    "sha256": hashlib.sha256(later.read_bytes()).hexdigest()})
        self.record(value)
        (self.root / "mixed-evidence-evidence.md").write_bytes(b"Stale first artifact.\n")
        later.unlink()
        for kind in ("symlink", "fifo", "oversized"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    later.symlink_to(self.root / "input.json")
                elif kind == "fifo":
                    os.mkfifo(later)
                else:
                    with later.open("wb") as stream:
                        stream.truncate(memory.MAX_BOUND_ARTIFACT_BYTES + 1)
                for command in (["search"], self._control_arguments("mixed-evidence")):
                    code, _, error = self.invoke(command)
                    self.assertEqual(code, 2)
                    self.assertIn("artifacts[1]", error)
                error = self.error_record(self.payload("mixed-unrelated"))
                self.assertIn("artifacts[1]", error)
                self.assertFalse((self.root / "research/checkpoints/mixed-unrelated.md").exists())
                later.unlink()

    def test_search_is_bounded_filtered_and_read_only(self) -> None:
        first = self.payload()
        first["track"] = "primary"
        first["problem_ids"] = ["problem-one"]
        self.record(first)
        second = self.payload(
            "20260805T120000Z-beta",
            recorded_at="2026-08-05T12:00:00Z",
            status="PROVED",
        )
        second["track"] = "secondary"
        second["problem_ids"] = ["problem-two"]
        second["target"] = "Prove the spectral comparison target."
        second["discovery"] = {
            "topics": ["Spectral sequence"],
            "objects": ["Filtered complex"],
            "methods": ["Filtration argument"],
            "keywords": ["Page differential"],
            "future_capabilities": ["Formal checker"],
        }
        second["continuation"]["reopen_condition"] = "A checked differential becomes available."
        self.record(second, "second.json")
        index_path = self.root / "research/checkpoint_index.json"
        index_before = (index_path.read_bytes(), index_path.stat().st_mtime_ns)
        research_before = (
            sorted(path.name for path in (self.root / "research").iterdir()),
            (self.root / "research").stat().st_mtime_ns,
        )
        checkpoint_state = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.root / "research/checkpoints").glob("*.md")
        }
        code, output, error = self.invoke(
            [
                "search",
                "--status",
                "PROVED",
                "--track",
                "SECONDARY",
                "--problem-id",
                "problem-two",
                "--topic",
                "spectral sequence",
                "--method",
                "filtration argument",
                "--keyword",
                "page differential",
                "--future-capability",
                "formal checker",
                "--reopen-trigger",
                "a checked differential becomes available.",
                "--query",
                "spectral",
                "--limit",
                "1",
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(output["count"], 1)
        self.assertEqual(output["matches"][0]["checkpoint_id"], second["checkpoint_id"])
        self.assertEqual((index_path.read_bytes(), index_path.stat().st_mtime_ns), index_before)
        self.assertEqual(
            (
                sorted(path.name for path in (self.root / "research").iterdir()),
                (self.root / "research").stat().st_mtime_ns,
            ),
            research_before,
        )
        after = {
            path.name: (path.read_bytes(), path.stat().st_mtime_ns)
            for path in (self.root / "research/checkpoints").glob("*.md")
        }
        self.assertEqual(after, checkpoint_state)
        code, _, error = self.invoke(["search", "--limit", "101"])
        self.assertEqual(code, 2)
        self.assertIn("between 1 and", error)

    def test_search_preserves_full_exact_reactivation_metadata(self) -> None:
        value = self.payload("lossless-reactivation")
        common_prefix = "Capability " + "x" * 300
        capability_a = common_prefix + " alpha"
        capability_b = common_prefix + " beta"
        missing_capability = (
            "A capability  with  preserved spacing\nand a second line "
            + "m" * 1400
        )
        reopen_condition = (
            "Reopen  only  when exact evidence exists\n"
            "and the independent checker is available."
        )
        obstruction_trigger = (
            "Retry after a stronger model can inspect the full obstruction\n"
            "without collapsing whitespace."
        )
        obstruction_description = (
            "The current route fails after the bounded comparison because "
            + "d" * 500
            + " OBSTRUCTION-TAIL-UNIQUE"
        )
        value["discovery"]["future_capabilities"] = [
            capability_b,
            capability_a,
        ]
        value["continuation"]["reopen_condition"] = reopen_condition
        value["obstructions"] = [
            {
                "description": obstruction_description,
                "missing_capability": missing_capability,
                "reopen_trigger": obstruction_trigger,
            }
        ]
        self.record(value, "lossless-reactivation.json")

        index = json.loads(
            (self.root / "research/checkpoint_index.json").read_text(encoding="utf-8")
        )
        entry = index["entries"][0]
        self.assertEqual(entry["obstructions"], [obstruction_description])
        self.assertEqual(
            entry["future_capabilities"],
            sorted(
                [capability_a, capability_b, missing_capability],
                key=lambda item: (item.casefold(), item),
            ),
        )
        self.assertEqual(
            entry["reopen_triggers"],
            sorted(
                [reopen_condition, obstruction_trigger],
                key=lambda item: (item.casefold(), item),
            ),
        )

        for option, exact_value in (
            ("--obstruction", obstruction_description),
            ("--future-capability", capability_a),
            ("--future-capability", capability_b),
            ("--future-capability", missing_capability),
            ("--reopen-trigger", reopen_condition),
            ("--reopen-trigger", obstruction_trigger),
        ):
            code, output, error = self.invoke(["search", option, exact_value])
            self.assertEqual(code, 0, error)
            self.assertEqual(
                [item["checkpoint_id"] for item in output["matches"]],
                ["lossless-reactivation"],
            )
        code, output, error = self.invoke(
            ["search", "--query", "obstruction-tail-unique"]
        )
        self.assertEqual(code, 0, error)
        self.assertEqual(output["count"], 1)

    def test_concurrent_records_cannot_lose_an_index_update(self) -> None:
        first = self.payload("concurrent-alpha")
        second = self.payload(
            "concurrent-beta", recorded_at="2026-08-04T12:01:00Z"
        )
        first_input = self.input_file(first, "concurrent-alpha.json")
        second_input = self.input_file(second, "concurrent-beta.json")
        entered_publish = threading.Event()
        release_publish = threading.Event()
        original_publish = memory._publish_checkpoint
        errors: list[BaseException] = []

        def delayed_publish(relative: str, data: bytes) -> bool:
            if relative.endswith("concurrent-alpha.md"):
                entered_publish.set()
                if not release_publish.wait(2):
                    raise AssertionError("test did not release delayed publication")
            return original_publish(relative, data)

        def worker(value: dict[str, object], source: Path) -> None:
            try:
                checkpoint_id = str(value["checkpoint_id"])
                memory.record_checkpoint(
                    f"research/checkpoints/{checkpoint_id}.md", str(source)
                )
            except BaseException as exc:  # retained for assertion in the main thread
                errors.append(exc)

        with mock.patch.object(memory, "_publish_checkpoint", side_effect=delayed_publish):
            first_thread = threading.Thread(target=worker, args=(first, first_input))
            second_thread = threading.Thread(target=worker, args=(second, second_input))
            first_thread.start()
            self.assertTrue(entered_publish.wait(1))
            second_thread.start()
            time.sleep(0.05)
            self.assertTrue(second_thread.is_alive())
            release_publish.set()
            first_thread.join(2)
            second_thread.join(2)
        self.assertFalse(first_thread.is_alive())
        self.assertFalse(second_thread.is_alive())
        self.assertEqual(errors, [])
        index = memory.validate_memory()
        self.assertEqual(index["checkpoint_count"], 2)
        self.assertEqual(
            {entry["checkpoint_id"] for entry in index["entries"]},
            {"concurrent-alpha", "concurrent-beta"},
        )

    def test_transient_checkpoint_directory_identity_drift_aborts_publication(self) -> None:
        value = self.payload("identity-drift")
        source = self.input_file(value, "identity-drift.json")
        checkpoints = self.root / "research/checkpoints"
        displaced = self.root / "research/checkpoints-displaced"
        original_publish = memory._publish_checkpoint

        def drift(relative: str, data: bytes) -> bool:
            checkpoints.rename(displaced)
            checkpoints.symlink_to(displaced)
            try:
                return original_publish(relative, data)
            finally:
                checkpoints.unlink()
                displaced.rename(checkpoints)

        with mock.patch.object(memory, "_publish_checkpoint", side_effect=drift):
            code, _, error = self.invoke(
                [
                    "record",
                    "--checkpoint-path",
                    "research/checkpoints/identity-drift.md",
                    "--input",
                    str(source),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("real directory", error)
        self.assertFalse((checkpoints / "identity-drift.md").exists())
        self.assertEqual(self.invoke(["validate"])[0], 0)

    def test_directory_name_replacement_preserves_only_the_pinned_commit(self) -> None:
        value = self.payload("descriptor-race")
        source = self.input_file(value, "descriptor-race.json")
        research = self.root / "research"
        checkpoints = research / "checkpoints"
        displaced = research / "checkpoints-displaced"
        outside = self.root / "outside"
        outside.mkdir()
        index_before = (research / "checkpoint_index.json").read_bytes()
        original_link = memory.os.link
        replaced = False

        def replace_name_during_link(*args, **kwargs):
            nonlocal replaced
            if not replaced:
                checkpoints.rename(displaced)
                checkpoints.symlink_to(outside, target_is_directory=True)
                replaced = True
            return original_link(*args, **kwargs)

        try:
            with mock.patch.object(memory.os, "link", side_effect=replace_name_during_link):
                code, output, error = self.invoke(
                    [
                        "record",
                        "--checkpoint-path",
                        "research/checkpoints/descriptor-race.md",
                        "--input",
                        str(source),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertEqual(output, {})
            self.assertIn("directory", json.loads(error)["error"])
            self.assertFalse((outside / "descriptor-race.md").exists())
            pinned_target = displaced / "descriptor-race.md"
            self.assertTrue(pinned_target.is_file())
            self.assertEqual(pinned_target.stat().st_nlink, 1)
            self.assertEqual(
                pinned_target.read_bytes(),
                memory.render_checkpoint(memory.normalize_record(value)),
            )
            self.assertEqual((research / "checkpoint_index.json").read_bytes(), index_before)
        finally:
            if checkpoints.is_symlink():
                checkpoints.unlink()
            if displaced.exists():
                displaced.rename(checkpoints)
        self.assertTrue((checkpoints / "descriptor-race.md").is_file())
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertEqual(self.invoke(["validate"])[0], 0)

    def test_path_escape_and_artifact_escape_are_rejected(self) -> None:
        value = self.payload()
        error = self.error_record(
            value,
            path="research/checkpoints/../escaped.md",
            input_name="escape-command.json",
        )
        self.assertIn("unsafe path component", error)
        self.assertFalse((self.root / "research/escaped.md").exists())
        artifact = self.payload("artifact-escape")
        artifact["artifacts"] = [{"path": "../outside", "role": "bad"}]
        error = self.error_record(artifact, input_name="artifact-escape.json")
        self.assertIn("unsafe path component", error)

        newline = self.payload("artifact-newline")
        newline["artifacts"] = [
            {"path": "research/attempts/line\nbreak.md", "role": "bad"}
        ]
        error = self.error_record(newline, input_name="artifact-newline.json")
        self.assertIn("control characters", error)

        tab = self.payload("artifact-tab")
        tab["failed"] = [
            {
                "attempt": "A bounded failed route.",
                "exact_reason": "The test obstruction applies.",
                "artifact_paths": ["research/attempts/tab\tbreak.md"],
            }
        ]
        error = self.error_record(tab, input_name="artifact-tab.json")
        self.assertIn("control characters", error)
        self.assertEqual(
            sorted(path.name for path in (self.root / "research/checkpoints").iterdir()),
            ["README.md"],
        )

    def test_symlink_checkpoint_and_input_are_rejected(self) -> None:
        value = self.payload()
        self.record(value)
        original = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
        link = self.root / "research/checkpoints/link.md"
        link.symlink_to(original)
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("real regular file", error)
        link.unlink()

        source = self.input_file(self.payload("symlink-input"), "real-input.json")
        input_link = self.root / "input-link.json"
        input_link.symlink_to(source)
        code, _, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                "research/checkpoints/symlink-input.md",
                "--input",
                str(input_link),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("real regular file", error)

    def test_hardlinked_checkpoint_and_index_are_rejected(self) -> None:
        value = self.payload()
        self.record(value)
        original = self.root / f"research/checkpoints/{value['checkpoint_id']}.md"
        linked = self.root / "checkpoint-hardlink"
        os.link(original, linked)
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("exactly one hard link", error)
        linked.unlink()
        self.assertEqual(self.invoke(["validate"])[0], 0)

        index = self.root / "research/checkpoint_index.json"
        index_link = self.root / "index-hardlink"
        os.link(index, index_link)
        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("exactly one hard link", error)
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("exactly one hard link", error)

    def test_interrupted_checkpoint_commit_recovers_durably_and_retries(self) -> None:
        value = self.payload("crash-committed")
        rendered = memory.render_checkpoint(memory.normalize_record(value))
        research = self.root / "research"
        checkpoints = research / "checkpoints"
        staging = research / (memory.CHECKPOINT_STAGING_PREFIX + "a" * 32)
        target = checkpoints / "crash-committed.md"
        staging.write_bytes(rendered)
        staging.chmod(0o644)
        os.link(staging, target)
        self.assertEqual((staging.stat().st_nlink, target.stat().st_nlink), (2, 2))

        before = {
            path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_nlink)
            for path in (staging, target, research / "checkpoint_index.json")
        }
        directory_mtimes = (
            research.stat().st_mtime_ns,
            checkpoints.stat().st_mtime_ns,
        )
        for command in (["validate"], ["search"]):
            code, _, error = self.invoke(list(command))
            self.assertEqual(code, 2)
            self.assertIn("interrupted research-memory publication", error)
            self.assertEqual(
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_nlink)
                    for path in (staging, target, research / "checkpoint_index.json")
                },
                before,
            )
            self.assertEqual(
                (research.stat().st_mtime_ns, checkpoints.stat().st_mtime_ns),
                directory_mtimes,
            )

        events = []
        research_identity = (research.stat().st_dev, research.stat().st_ino)
        checkpoints_identity = (checkpoints.stat().st_dev, checkpoints.stat().st_ino)
        real_fsync = memory.os.fsync
        real_unlink = memory.os.unlink

        def track_fsync(descriptor):
            info = os.fstat(descriptor)
            identity = (info.st_dev, info.st_ino)
            if identity == checkpoints_identity:
                events.append("fsync-checkpoints")
            elif identity == research_identity:
                events.append("fsync-research")
            return real_fsync(descriptor)

        def track_unlink(name, *args, **kwargs):
            if name == staging.name:
                events.append("unlink-staging")
            return real_unlink(name, *args, **kwargs)

        with mock.patch.object(memory.os, "fsync", side_effect=track_fsync), mock.patch.object(
            memory.os, "unlink", side_effect=track_unlink
        ):
            code, output, error = self.invoke(["rebuild-index"])
        self.assertEqual((code, output["status"]), (0, "REBUILT"), error)
        self.assertLess(
            events.index("fsync-checkpoints"),
            events.index("unlink-staging"),
        )
        self.assertLess(
            events.index("unlink-staging"),
            events.index("fsync-research"),
        )
        self.assertFalse(staging.exists())
        self.assertEqual(target.stat().st_nlink, 1)
        self.assertEqual(target.read_bytes(), rendered)
        self.assertEqual(self.invoke(["validate"])[0], 0)

        source = self.input_file(value, "crash-committed-retry.json")
        code, retry, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                "research/checkpoints/crash-committed.md",
                "--input",
                str(source),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertTrue(retry["idempotent"])
        first_index = (research / "checkpoint_index.json").read_bytes()
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertEqual((research / "checkpoint_index.json").read_bytes(), first_index)

    def test_post_commit_fsync_failures_never_delete_the_checkpoint(self) -> None:
        research = self.root / "research"
        checkpoints = research / "checkpoints"
        research_identity = (research.stat().st_dev, research.stat().st_ino)
        checkpoints_identity = (checkpoints.stat().st_dev, checkpoints.stat().st_ino)
        real_fsync = memory.os.fsync

        first = self.payload("fsync-destination-failure")
        first_source = self.input_file(first, "fsync-destination-failure.json")
        destination_failed = False

        def fail_destination_fsync(descriptor):
            nonlocal destination_failed
            info = os.fstat(descriptor)
            if (
                not destination_failed
                and (info.st_dev, info.st_ino) == checkpoints_identity
            ):
                destination_failed = True
                raise OSError("synthetic checkpoint-directory fsync failure")
            return real_fsync(descriptor)

        with mock.patch.object(memory.os, "fsync", side_effect=fail_destination_fsync):
            code, _, error = self.invoke(
                [
                    "record",
                    "--checkpoint-path",
                    "research/checkpoints/fsync-destination-failure.md",
                    "--input",
                    str(first_source),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("synthetic checkpoint-directory fsync failure", error)
        first_target = checkpoints / "fsync-destination-failure.md"
        first_stages = list(research.glob(memory.CHECKPOINT_STAGING_PREFIX + "*"))
        self.assertTrue(first_target.is_file())
        self.assertEqual(len(first_stages), 1)
        self.assertEqual((first_target.stat().st_nlink, first_stages[0].stat().st_nlink), (2, 2))
        self.assertEqual(self.invoke(["validate"])[0], 2)
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertEqual(first_target.stat().st_nlink, 1)
        self.assertEqual(list(research.glob(memory.CHECKPOINT_STAGING_PREFIX + "*")), [])

        second = self.payload(
            "fsync-source-failure",
            recorded_at="2026-08-04T12:02:00Z",
        )
        second_source = self.input_file(second, "fsync-source-failure.json")
        source_failed = False

        def fail_source_fsync(descriptor):
            nonlocal source_failed
            info = os.fstat(descriptor)
            if not source_failed and (info.st_dev, info.st_ino) == research_identity:
                source_failed = True
                raise OSError("synthetic research-directory fsync failure")
            return real_fsync(descriptor)

        with mock.patch.object(memory.os, "fsync", side_effect=fail_source_fsync):
            code, _, error = self.invoke(
                [
                    "record",
                    "--checkpoint-path",
                    "research/checkpoints/fsync-source-failure.md",
                    "--input",
                    str(second_source),
                ]
            )
        self.assertEqual(code, 2)
        self.assertIn("synthetic research-directory fsync failure", error)
        second_target = checkpoints / "fsync-source-failure.md"
        self.assertTrue(second_target.is_file())
        self.assertEqual(second_target.stat().st_nlink, 1)
        self.assertEqual(list(research.glob(memory.CHECKPOINT_STAGING_PREFIX + "*")), [])

        code, retry, error = self.invoke(
            [
                "record",
                "--checkpoint-path",
                "research/checkpoints/fsync-source-failure.md",
                "--input",
                str(second_source),
            ]
        )
        self.assertEqual(code, 0, error)
        self.assertTrue(retry["idempotent"])
        self.assertEqual(memory.validate_memory()["checkpoint_count"], 2)

    def test_exclusive_rebuild_cleans_safe_precommit_and_index_residue(self) -> None:
        research = self.root / "research"
        checkpoint_stage = research / (
            memory.CHECKPOINT_STAGING_PREFIX + "b" * 32
        )
        index_stage = research / (memory.INDEX_STAGING_PREFIX + "c" * 32)
        checkpoint_stage.write_bytes(b"partial checkpoint bytes")
        checkpoint_stage.chmod(0o600)
        index_stage.write_bytes(b'{"partial":')
        index_stage.chmod(0o644)

        code, _, error = self.invoke(["validate"])
        self.assertEqual(code, 2)
        self.assertIn("interrupted research-memory publication", error)
        code, output, error = self.invoke(["rebuild-index"])
        self.assertEqual((code, output["status"]), (0, "REBUILT"), error)
        self.assertFalse(checkpoint_stage.exists())
        self.assertFalse(index_stage.exists())
        self.assertEqual(self.invoke(["validate"])[0], 0)
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)

    def test_residue_recovery_preflights_all_names_and_rejects_ambiguity(self) -> None:
        research = self.root / "research"
        safe_stage = research / (memory.CHECKPOINT_STAGING_PREFIX + "d" * 32)
        invalid_name = research / (memory.CHECKPOINT_STAGING_PREFIX + "e" * 31)
        safe_stage.write_bytes(b"safe removable residue")
        safe_stage.chmod(0o600)
        invalid_name.write_bytes(b"invalid reserved name")
        invalid_name.chmod(0o600)
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("invalid reserved checkpoint staging name", error)
        self.assertTrue(safe_stage.exists())
        self.assertTrue(invalid_name.exists())
        invalid_name.unlink()
        self.assertEqual(self.invoke(["rebuild-index"])[0], 0)
        self.assertFalse(safe_stage.exists())

        outside = self.root / "outside-residue.bin"
        outside.write_bytes(b"outside hardlink")
        outside.chmod(0o644)
        ambiguous = research / (memory.CHECKPOINT_STAGING_PREFIX + "f" * 32)
        os.link(outside, ambiguous)
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("one exact checkpoint link", error)
        self.assertTrue(ambiguous.exists())
        self.assertEqual(outside.read_bytes(), b"outside hardlink")
        ambiguous.unlink()
        outside.unlink()

        invalid_stage = research / (memory.CHECKPOINT_STAGING_PREFIX + "2" * 32)
        invalid_target = self.root / "research/checkpoints/invalid-commit.md"
        invalid_stage.write_bytes(b"not a canonical checkpoint\n")
        invalid_stage.chmod(0o644)
        os.link(invalid_stage, invalid_target)
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("designated v1 JSON comment", error)
        self.assertEqual((invalid_stage.stat().st_nlink, invalid_target.stat().st_nlink), (2, 2))
        invalid_target.unlink()
        invalid_stage.unlink()

        unsafe_mode = research / (memory.INDEX_STAGING_PREFIX + "0" * 32)
        unsafe_mode.write_bytes(b"mode attack")
        unsafe_mode.chmod(0o666)
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("unsafe mode", error)
        self.assertTrue(unsafe_mode.exists())
        unsafe_mode.unlink()

        exact_symlink = research / (memory.INDEX_STAGING_PREFIX + "1" * 32)
        exact_symlink.symlink_to(research / "checkpoint_index.json")
        code, _, error = self.invoke(["rebuild-index"])
        self.assertEqual(code, 2)
        self.assertIn("must be a regular file", error)
        self.assertTrue(exact_symlink.is_symlink())
        exact_symlink.unlink()
        self.assertEqual(self.invoke(["validate"])[0], 0)

    def test_symlinked_checkpoint_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="research-memory-target-") as target_temp:
            alternate = Path(target_temp)
            root = self.root / "linked-root"
            (root / "research").mkdir(parents=True)
            (root / "research/checkpoints").symlink_to(alternate)
            (root / "research/checkpoint_index.json").write_bytes(
                memory.canonical_json_bytes(
                    {"schema_version": 1, "checkpoint_count": 0, "entries": []}
                )
            )
            memory.ROOT = root
            code, _, error = self.invoke(["validate"])
            self.assertEqual(code, 2)
            self.assertIn("real directory", error)

    def test_schema_and_example_template_are_strict_valid_inputs(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schema["additionalProperties"])
        template = memory.strict_json_loads(
            TEMPLATE.read_text(encoding="utf-8"), "research checkpoint template"
        )
        normalized = memory.normalize_record(template)
        rendered = memory.render_checkpoint(normalized)
        parsed = memory.parse_checkpoint(rendered, "template-render.md")
        self.assertEqual(parsed, normalized)
        self.assertIn(b"## Failed routes", rendered)
        self.assertIn(b"## Obstructions", rendered)
        self.assertIn(b"## Claims", rendered)
        self.assertIn(b"## Canonical artifact references", rendered)

    def test_cli_has_no_root_override(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                memory.run(["--root", str(self.root), "validate"])

    def test_script_and_test_suite_parse_with_python_39_grammar(self) -> None:
        ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT), feature_version=9)
        ast.parse(
            Path(__file__).read_text(encoding="utf-8"),
            filename=str(Path(__file__)),
            feature_version=9,
        )


if __name__ == "__main__":
    unittest.main()
