"""Synthetic engineering fixtures only. They are not research evidence."""
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "research_archive.py"
spec = importlib.util.spec_from_file_location("research_archive", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Archive, ArchiveError = module.Archive, module.ArchiveError


def request(kind="synthetic.record", **updates):
    value = {"kind": kind, "actor": {"id": "synthetic-actor", "role": "test"},
             "session_id": "synthetic-session", "run_id": "synthetic-run",
             "operation_id": "synthetic-operation", "attempt_id": "synthetic-attempt",
             "payload": {"synthetic": True}}
    value.update(updates)
    return value


def writer(root, number):
    archive = Archive(root).init()
    value = archive.put(("synthetic worker %d\n" % number).encode())
    archive.append(request(inputs=[value], payload={"synthetic": True, "worker": number}), "worker-%d" % number)


def overwrite(path, data):
    path.chmod(0o600)
    path.write_bytes(data)


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="synthetic-archive-test-")
        self.base = Path(self.temp.name).resolve()
        self.archive = Archive(self.base / "archive").init()

    def tearDown(self):
        self.temp.cleanup()

    def append(self, kind="synthetic.record", **updates):
        key = updates.pop("key", "delivery-%d" % (len(self.archive.events()) + 1))
        return self.archive.append(request(kind, **updates), key)

    def test_exact_binary_bytes_and_readable_views(self):
        content = b"synthetic\r\n\x00\xff"
        digest = self.archive.put(content)
        event = self.append(inputs=[digest], outputs=[digest])
        self.assertEqual(self.archive.get(digest), content)
        self.assertEqual(event["model"]["status"], "unknown")
        self.assertEqual(event["cost"]["status"], "unknown")
        self.assertEqual(event["timestamp_source"], "archive-clock-event-time-unknown")
        self.assertEqual(event["timestamp"], event["recorded_at"])
        self.assertEqual(self.archive.view()["events"], [event])
        self.assertIn(event["id"], self.archive.markdown())
        self.assertTrue(self.archive.validate()["ok"])

    def test_event_time_and_recording_time_are_distinct(self):
        event = self.append(timestamp="2020-01-02T03:04:05+00:00")
        self.assertEqual(event["timestamp_source"], "supplied-event-time")
        self.assertNotEqual(event["timestamp"], event["recorded_at"])

    def test_duplicate_delivery_is_exact_and_conflict_fails(self):
        value = request()
        first = self.archive.append(value, "synthetic-delivery")
        self.assertEqual(self.archive.append(value, "synthetic-delivery"), first)
        with self.assertRaisesRegex(ArchiveError, "conflict"):
            self.archive.append(request(payload={"synthetic": "different"}), "synthetic-delivery")
        self.assertEqual(len(self.archive.events()), 1)

    def test_concurrent_initialization_and_writes(self):
        destination = self.base / "new-concurrent-archive"
        context = multiprocessing.get_context("fork")
        processes = [context.Process(target=writer, args=(destination, n)) for n in range(10)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            self.assertFalse(process.is_alive())
            self.assertEqual(process.exitcode, 0)
        archive = Archive(destination)
        self.assertEqual([e["sequence"] for e in archive.events()], list(range(1, 11)))
        self.assertTrue(archive.validate()["ok"])

    def test_parallel_duplicate_delivery_only_commits_once(self):
        context = multiprocessing.get_context("fork")
        processes = [context.Process(target=writer, args=(self.archive.root, 1)) for _ in range(5)]
        for process in processes:
            process.start()
        for process in processes:
            process.join(20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(len(self.archive.events()), 1)

    def test_branch_merge_reject_reopen_method_switch_and_correction(self):
        original = self.archive.put(b"synthetic original candidate\n")
        corrected = self.archive.put(b"synthetic corrected candidate\n")
        m1 = self.archive.put(b"synthetic method v1\n")
        m2 = self.archive.put(b"synthetic method v2\n")
        bindings = {"method": [m1], "instruction": [], "config": [], "input": []}
        root = self.append("candidate.created", outputs=[original], bindings=bindings)
        original_bytes = (self.archive.root / "events" / "000000000001.json").read_bytes()
        branch1 = self.append("candidate.branch", parents=[root["id"]], bindings=bindings)
        branch2 = self.append("candidate.branch", parents=[root["id"]], bindings=bindings)
        merge = self.append("candidate.merge", parents=[branch1["id"], branch2["id"]], bindings=bindings)
        reject = self.append("candidate.reject", parents=[merge["id"]])
        reopen = self.append("candidate.reopen", parents=[reject["id"]])
        switch = self.append("method.switch", parents=[reopen["id"]],
                             bindings=dict(bindings, method=[m2]), inputs=[m1], outputs=[m2])
        correction = self.append("correction", parents=[root["id"], switch["id"]],
                                 inputs=[original], outputs=[corrected])
        self.append("decision", parents=[correction["id"]])
        self.assertEqual((self.archive.root / "events" / "000000000001.json").read_bytes(), original_bytes)
        self.assertEqual(self.archive.get(original), b"synthetic original candidate\n")
        self.assertEqual(len(self.archive.view()["branches"]), 9)
        self.assertTrue(self.archive.validate()["ok"])

    def test_missing_parents_merge_arity_and_missing_version_objects_fail(self):
        with self.assertRaises(ArchiveError):
            self.append("candidate.branch", parents=["missing"])
        with self.assertRaises(ArchiveError):
            self.append("candidate.merge")
        with self.assertRaises((ArchiveError, OSError)):
            self.append(bindings={"method": ["0" * 64], "instruction": [], "config": [], "input": []})
        self.assertEqual(self.archive.events(), [])

    def test_interrupted_attempt_is_unresolved_until_explicit_terminal(self):
        start = self.append("operation.started")
        audit = self.archive.recover()
        self.assertEqual(audit["incomplete_attempts"][0]["status"], "unresolved")
        self.assertEqual(self.archive.view()["attempts"]["synthetic-attempt"]["status"], "unresolved")
        with self.assertRaises(ArchiveError):
            self.append("operation.completed")
        self.append("operation.interrupted", parents=[start["id"]])
        self.assertEqual(self.archive.recover()["incomplete_attempts"], [])
        with self.assertRaises(ArchiveError):
            self.append("operation.completed", parents=[start["id"]])
        next_start = self.append("operation.started", attempt_id="synthetic-attempt-2")
        self.append("operation.completed", attempt_id="synthetic-attempt-2", parents=[next_start["id"]])
        self.assertEqual(self.archive.view()["attempts"]["synthetic-attempt"]["status"], "interrupted")

    def test_terminal_rejects_version_and_provenance_drift(self):
        start = self.append("operation.started")
        digest = self.archive.put(b"synthetic changed method")
        for changed in ({"run_id": "other-run"},
                        {"bindings": {"method": [digest], "instruction": [], "config": [], "input": []}}):
            with self.assertRaises(ArchiveError):
                self.append("operation.completed", parents=[start["id"]], **changed)
        self.assertEqual(len(self.archive.events()), 1)

    def test_corrupt_object_is_not_overwritten(self):
        original = b"synthetic original"
        digest = self.archive.put(original)
        self.append(inputs=[digest])
        path = self.archive.root / "objects" / digest
        overwrite(path, b"damaged")
        self.assertFalse(self.archive.validate()["ok"])
        with self.assertRaisesRegex(ArchiveError, "refusing"):
            self.archive.put(original)
        with self.assertRaises(ArchiveError):
            self.archive.append(request(), "new")
        self.assertEqual(path.read_bytes(), b"damaged")

    def test_partial_tail_temporary_and_orphan_are_reported_read_only(self):
        self.append()
        orphan = self.archive.put(b"synthetic unreferenced object")
        temp = self.archive.root / "events" / ".tmp-interrupted"
        temp.write_bytes(b"partial")
        tail = self.archive.root / "events" / "000000000002.json"
        tail.write_bytes(b'{"schema_version":1,')
        report = self.archive.recover()
        self.assertFalse(report["ok"])
        self.assertIn(orphan, report["orphan_objects"])
        self.assertIn("events/.tmp-interrupted", report["temporary_files"])
        self.assertTrue(any(x.get("path") == "events/000000000002.json" for x in report["errors"]))
        self.assertEqual(tail.read_bytes(), b'{"schema_version":1,')
        self.assertEqual(temp.read_bytes(), b"partial")

    def test_missing_event_gap_is_reported(self):
        for _ in range(3):
            self.append()
        (self.archive.root / "events" / "000000000002.json").unlink()
        report = self.archive.validate()
        self.assertFalse(report["ok"])
        self.assertEqual(report["sequence_gaps"], [2])

    def test_replay_after_uncertain_published_event(self):
        value = request()
        event = self.archive.append(value, "uncertain")
        # Synthetic crash residue after final link but before temporary unlink.
        os.link(self.archive.root / "events" / "000000000001.json", self.archive.root / "events" / ".tmp-after-link")
        self.assertEqual(self.archive.append(value, "uncertain"), event)
        self.assertEqual(len(self.archive.events()), 1)
        self.assertIn("events/.tmp-after-link", self.archive.recover()["temporary_files"])

    def test_detached_export_import_preserves_bytes_ids_and_provenance(self):
        digest = self.archive.put(b"synthetic\r\n\xff")
        first = self.append(inputs=[digest])
        bundle = self.base / "portable"
        manifest = self.archive.export(bundle)
        self.assertIn("format/research_archive.py", manifest["files"])
        original_bytes = (self.archive.root / "events" / "000000000001.json").read_bytes()
        shutil.rmtree(self.archive.root)
        destination = self.base / "detached"
        destination.mkdir()
        imported = Archive.import_bundle(bundle, destination)
        shutil.rmtree(bundle)
        self.assertEqual(imported.events(), [first])
        self.assertEqual(imported.get(digest), b"synthetic\r\n\xff")
        self.assertEqual((destination / "events" / "000000000001.json").read_bytes(), original_bytes)
        self.assertTrue(imported.validate()["ok"])
        imported.export(self.base / "reexport")
        carried_runtime = destination / "format" / "research_archive.py"
        run = subprocess.run([sys.executable, str(carried_runtime), "--root", str(destination), "validate"],
                             capture_output=True, text=True, cwd=self.base)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_scoped_parent_closure_explicit_omissions_and_continuation(self):
        root = self.append("candidate.created", key="root-key")
        unrelated = self.append(key="unrelated-key")
        leaf = self.append("candidate.branch", parents=[root["id"]])
        bundle = self.base / "scoped"
        self.archive.export(bundle, [leaf["id"]])
        imported = Archive.import_bundle(bundle, self.base / "detached")
        self.assertEqual([e["id"] for e in imported.events()], [root["id"], leaf["id"]])
        report = imported.validate()
        self.assertTrue(report["ok"])
        self.assertEqual(report["omitted_events"][0]["id"], unrelated["id"])
        with self.assertRaisesRegex(ArchiveError, "omitted"):
            imported.append(request(), "unrelated-key")
        next_event = imported.append(request(), "new-key")
        self.assertEqual(next_event["sequence"], 4)
        self.assertTrue(imported.validate()["ok"])

    def test_bundle_tamper_missing_file_traversal_and_extra_file_rejected(self):
        digest = self.archive.put(b"synthetic bundle object")
        self.append(inputs=[digest])
        for attack in ("tamper", "missing", "traversal", "extra"):
            bundle = self.base / ("bundle-" + attack)
            self.archive.export(bundle)
            if attack == "tamper":
                overwrite(bundle / "objects" / digest, b"changed")
            elif attack == "missing":
                (bundle / "objects" / digest).unlink()
            elif attack == "extra":
                (bundle / "unexpected").write_bytes(b"synthetic")
            else:
                manifest = json.loads((bundle / "manifest.json").read_bytes())
                manifest["files"]["../escaped"] = {"sha256": "0" * 64, "size": 0}
                overwrite(bundle / "manifest.json", module.canonical(manifest))
            destination = self.base / ("destination-" + attack)
            with self.assertRaises(ArchiveError):
                Archive.import_bundle(bundle, destination)
            self.assertFalse(destination.exists())
        self.assertFalse((self.base / "escaped").exists())

    def test_invalid_semantics_with_rehashed_manifest_rejected_before_destination(self):
        self.append()
        bundle = self.base / "invalid-semantics"
        self.archive.export(bundle)
        eventpath = bundle / "events" / "000000000001.json"
        event = json.loads(eventpath.read_bytes())
        event["parents"] = ["missing-causal-parent"]
        event.pop("sha256")
        event["sha256"] = module.sha(module.canonical(event))
        overwrite(eventpath, module.canonical(event))
        manifest = json.loads((bundle / "manifest.json").read_bytes())
        manifest["files"]["events/000000000001.json"] = {"sha256": module.sha(eventpath.read_bytes()), "size": len(eventpath.read_bytes())}
        overwrite(bundle / "manifest.json", module.canonical(manifest))
        destination = self.base / "must-remain-absent"
        with self.assertRaises(ArchiveError):
            Archive.import_bundle(bundle, destination)
        self.assertFalse(destination.exists())

    def test_bundle_links_and_special_files_are_rejected(self):
        self.append()
        for kind in ("symlink", "hardlink", "fifo"):
            bundle = self.base / ("bundle-" + kind)
            self.archive.export(bundle)
            path = bundle / "format" / "extra"
            if kind == "symlink":
                path.symlink_to(bundle / "archive.json")
            elif kind == "hardlink":
                os.link(bundle / "archive.json", path)
            else:
                os.mkfifo(path)
            with self.assertRaises(ArchiveError):
                Archive.import_bundle(bundle, self.base / ("out-" + kind))

    def test_no_clobber_export_import_and_symlink_root(self):
        self.append()
        bundle = self.base / "bundle"
        self.archive.export(bundle)
        with self.assertRaises((ArchiveError, FileExistsError)):
            self.archive.export(bundle)
        with self.assertRaises(ArchiveError):
            Archive.import_bundle(bundle, self.archive.root)
        alias = self.base / "alias"
        alias.symlink_to(self.archive.root, target_is_directory=True)
        with self.assertRaises(ArchiveError):
            Archive(alias)
        self.assertTrue(self.archive.validate()["ok"])

    def test_imported_interpretation_tampering_is_reported(self):
        self.append()
        bundle = self.base / "bundle"
        self.archive.export(bundle)
        imported = Archive.import_bundle(bundle, self.base / "imported")
        overwrite(imported.root / "format" / "ARCHIVE_FORMAT.md", b"modified interpretation")
        self.assertFalse(imported.validate()["ok"])
        with self.assertRaises(ArchiveError):
            imported.export(self.base / "bad-reexport")


if __name__ == "__main__":
    unittest.main()
