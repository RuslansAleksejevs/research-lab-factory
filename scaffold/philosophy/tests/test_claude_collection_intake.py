"""Offline evidence-intake tests: synthetic untrusted bytes, no model execution."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HELPER = Path(__file__).resolve().parents[1] / 'scripts/claude_terminal/claude_collection_intake.py'
SPEC = importlib.util.spec_from_file_location('collection_intake_under_test', HELPER)
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


class CollectionIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.collection = 'runs/collected'
        self.folder = self.root / self.collection
        self.folder.mkdir(parents=True)
        self.original = b'An unverified argument.\n'
        self.latest = b'An unverified revised argument.\n'
        self.files = {
            'runner.py': b'raise RuntimeError("Collected runner must never execute")\n',
            'claude_runner_support.py': b'raise RuntimeError("Do not import")\n',
            'claude_source_capture.py': b'raise RuntimeError("Do not import")\n',
            'inputs/task-1/task.md': b'Review a synthetic mathematical argument.\n',
            'inputs/task-1/FILES.json': encoded({'read': ['task.md'], 'sources': []}),
            'objects/' + sha(self.original): self.original,
            'snapshots/task-1.json': encoded({'report.md': sha(self.original)}),
        }
        self.manifest = {
            'protocol': intake.PROTOCOL, 'id': 'old-packet', 'purpose': 'research',
            'runner_sha256': sha(self.files['runner.py']),
            'input_hashes': {name: sha(data) for name, data in self.files.items() if name.startswith('inputs/')},
            'support_hashes': {name: sha(self.files[name]) for name in ('claude_runner_support.py', 'claude_source_capture.py')},
            'tasks': [{'id': 'task-1', 'required_outputs': ['report.md']}],
        }
        self.states = {'task-1': {'status': 'done', 'reason': 'accepted_files', 'session_id': 'old-session',
                                  'outputs': {'report.md': sha(self.original)}}}
        self.integrity = {'task-1': 'snapshot_preserved'}
        self.write()

    def write(self, released=True):
        self.files['manifest.json'] = encoded(self.manifest)
        self.files['state.json'] = encoded(self.states)
        if released:
            self.files['release.json'] = encoded({'manifest_sha256': sha(self.files['manifest.json']),
                'runner_sha256': self.manifest['runner_sha256'], 'review_sha256': 'a' * 64,
                'research_approved': True})
        else:
            self.files.pop('release.json', None)
        receipt = {'protocol': intake.PROTOCOL, 'packet': self.manifest['id'],
            'files': {name: sha(data) for name, data in self.files.items()},
            'status': self.states, 'integrity': self.integrity, 'canonical_import': 'pending'}
        for name, data in {**self.files, 'collection.json': encoded(receipt)}.items():
            path = self.folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        self.receipt_sha = sha(encoded(receipt))

    def inspect(self, **kwargs):
        return intake.inspect_collection(self.root, self.collection, self.receipt_sha, **kwargs)

    def materialize(self, output='runs/imported'):
        return intake.materialize_collection(self.root, self.collection, self.receipt_sha, output)

    def test_old_runner_is_data_and_read_only_inspection_returns_checkpoint_bindings(self):
        before = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        report = self.inspect()
        self.assertEqual(report['status'], 'UNVERIFIED_EXTERNAL_OUTPUT')
        self.assertEqual(report['canonical_import'], 'pending')
        self.assertFalse(report['partial'])
        self.assertEqual(report['artifacts'][0]['name'], 'report.md')
        self.assertEqual(report['artifacts'][0]['version'], 'accepted')
        self.assertTrue(report['artifacts'][0]['is_latest'])
        self.assertNotEqual(report['runner_sha256'], sha(HELPER.read_bytes()))
        self.assertEqual(len(report['checkpoint_artifacts']), 3)
        after = {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def test_changed_accepted_output_preserves_both_versions(self):
        self.files['objects/' + sha(self.latest)] = self.latest
        self.files['snapshots/task-1.json'] = encoded({'report.md': sha(self.latest)})
        self.integrity['task-1'] = 'changed_after_acceptance'
        self.write()
        report = self.materialize()
        self.assertTrue(report['partial'])
        versions = {row['version']: row for row in report['artifacts']}
        self.assertEqual(set(versions), {'accepted', 'latest'})
        self.assertFalse(versions['accepted']['is_latest'])
        self.assertTrue(versions['latest']['is_latest'])
        self.assertEqual((self.root / versions['accepted']['path']).read_bytes(), self.original)
        self.assertEqual((self.root / versions['latest']['path']).read_bytes(), self.latest)
        self.assertTrue(report['tasks'][0]['changed_after_acceptance'])
        for row in report['checkpoint_artifacts']:
            path = self.root / row['path']
            self.assertEqual(sha(path.read_bytes()), row['sha256'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o444)
        self.assertEqual(json.loads((self.root / 'runs/imported/intake.json').read_text()), report)

    def test_progress_is_available_without_a_completed_report(self):
        self.states['task-1'].update(status='paused', reason='quota', outputs={})
        self.files['snapshots/task-1.json'] = encoded({'progress.md': sha(self.original)})
        self.write()
        report = self.materialize()
        self.assertTrue(report['partial'])
        self.assertEqual(report['tasks'][0]['missing_required_outputs'], ['report.md'])
        self.assertEqual(report['artifacts'][0]['version'], 'latest')
        self.assertEqual(report['artifacts'][0]['name'], 'progress.md')
        self.assertEqual((self.root / report['artifacts'][0]['path']).read_bytes(), self.original)

    def test_interrupted_previous_attempt_is_not_mechanical_acceptance(self):
        self.states['task-1']['status'] = 'paused'
        self.write()
        report = self.inspect()
        self.assertEqual(report['artifacts'][0]['version'], 'last_attempt')
        self.assertTrue(report['partial'])

    def test_unstarted_packet_with_no_release_or_outputs_remains_inspectable(self):
        self.states = {}
        self.integrity = {}
        self.files.pop('snapshots/task-1.json')
        (self.folder / 'snapshots/task-1.json').unlink()
        (self.folder / 'release.json').unlink()
        self.write(released=False)
        report = self.inspect()
        self.assertEqual(report['artifacts'], [])
        self.assertTrue(report['partial'])
        self.assertFalse(report['release_binding_present'])
        self.assertEqual(report['tasks'][0]['runner_status'], 'not_started')
        self.assertEqual(len(report['checkpoint_artifacts']), 2)

    def test_oversized_collection_preserves_accepted_bytes_without_claiming_current_output(self):
        self.integrity['task-1'] = 'partial_snapshot_output_limit'
        self.write()
        report = self.materialize()
        self.assertTrue(report['partial'])
        self.assertFalse(report['tasks'][0]['snapshot_complete'])
        self.assertFalse(report['artifacts'][0]['is_latest'])
        self.assertTrue(report['artifacts'][0]['is_latest_snapshot'])
        self.assertEqual(report['artifacts'][0]['version'], 'accepted')
        self.assertEqual((self.root / report['artifacts'][0]['path']).read_bytes(), self.original)

    def test_resource_pause_with_incomplete_snapshot_remains_partial(self):
        self.states['task-1'].update(status='paused', reason='output_limit', output_snapshot_complete=False)
        self.integrity['task-1'] = 'partial_snapshot_output_limit'
        self.write()
        report = self.inspect()
        self.assertTrue(report['partial'])
        self.assertFalse(report['tasks'][0]['snapshot_complete'])
        self.assertEqual(report['artifacts'][0]['version'], 'last_attempt')

    def test_checkpoint_selection_is_bounded_without_losing_named_artifacts(self):
        names = {'result-%03d.md' % index: sha(self.original) for index in range(70)}
        names['report.md'] = sha(self.original)
        self.files['snapshots/task-1.json'] = encoded(names)
        self.states['task-1']['outputs'] = names
        self.write()
        report = self.materialize()
        self.assertEqual(len(report['artifacts']), 71)
        self.assertEqual(len(report['checkpoint_artifacts']), 64)
        self.assertEqual(report['checkpoint_artifacts_omitted'], 9)
        self.assertTrue(report['warnings'])
        self.assertEqual(len(list((self.root / 'runs/imported/tasks/task-1/accepted').glob('*.md'))), 71)

    def test_selected_receipt_hash_must_match(self):
        with self.assertRaisesRegex(intake.IntakeError, 'receipt'):
            intake.inspect_collection(self.root, self.collection, '0' * 64)

    def test_corrupt_file_and_extra_file_fail(self):
        (self.folder / 'runner.py').write_bytes(b'changed')
        with self.assertRaisesRegex(intake.IntakeError, 'hash mismatch'):
            self.inspect()
        self.write()
        (self.folder / 'surprise.txt').write_bytes(b'not inventoried')
        with self.assertRaisesRegex(intake.IntakeError, 'inventory'):
            self.inspect()

    def test_receipt_cannot_hide_missing_input(self):
        name = 'inputs/task-1/task.md'
        self.files.pop(name)
        (self.folder / name).unlink()
        self.write()
        with self.assertRaisesRegex(intake.IntakeError, 'input bindings'):
            self.inspect()

    def test_manifest_code_hash_must_match_even_with_resealed_receipt(self):
        self.manifest['runner_sha256'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(intake.IntakeError, 'code binding'):
            self.inspect()

    def test_support_hash_must_match(self):
        self.manifest['support_hashes']['claude_runner_support.py'] = '0' * 64
        self.write()
        with self.assertRaisesRegex(intake.IntakeError, 'code binding'):
            self.inspect()

    def test_release_must_bind_collected_manifest(self):
        self.files['release.json'] = encoded({'manifest_sha256': '0' * 64,
            'runner_sha256': self.manifest['runner_sha256'], 'review_sha256': 'a' * 64})
        receipt = json.loads((self.folder / 'collection.json').read_text())
        receipt['files']['release.json'] = sha(self.files['release.json'])
        (self.folder / 'release.json').write_bytes(self.files['release.json'])
        (self.folder / 'collection.json').write_bytes(encoded(receipt))
        self.receipt_sha = sha(encoded(receipt))
        with self.assertRaisesRegex(intake.IntakeError, 'Release binding'):
            self.inspect()

    def test_missing_snapshot_object_fails(self):
        self.files['snapshots/task-1.json'] = encoded({'report.md': 'b' * 64})
        self.integrity['task-1'] = 'changed_after_acceptance'
        self.write()
        with self.assertRaisesRegex(intake.IntakeError, 'snapshot object'):
            self.inspect()

    def test_changed_output_cannot_be_labeled_preserved(self):
        self.files['objects/' + sha(self.latest)] = self.latest
        self.files['snapshots/task-1.json'] = encoded({'report.md': sha(self.latest)})
        self.write()
        with self.assertRaisesRegex(intake.IntakeError, 'integrity mismatch'):
            self.inspect()

    def test_receipt_and_state_must_agree(self):
        receipt = json.loads((self.folder / 'collection.json').read_text())
        receipt['status']['task-1']['status'] = 'paused'
        (self.folder / 'collection.json').write_bytes(encoded(receipt))
        self.receipt_sha = sha(encoded(receipt))
        with self.assertRaisesRegex(intake.IntakeError, 'state differs'):
            self.inspect()

    def test_snapshot_traversal_and_absolute_paths_fail(self):
        for bad in ('../stolen', '/tmp/stolen', 'a/../../stolen', 'a\\stolen', 'a//b'):
            with self.subTest(path=bad):
                self.files['snapshots/task-1.json'] = encoded({bad: sha(self.original)})
                self.write()
                with self.assertRaises(intake.IntakeError):
                    self.inspect()

    def test_source_symlink_file_and_directory_fail(self):
        path = self.folder / 'runner.py'
        path.unlink()
        path.symlink_to(HELPER)
        with self.assertRaises(intake.IntakeError):
            self.inspect()
        path.unlink()
        self.write()
        (self.root / 'link').symlink_to(self.folder, target_is_directory=True)
        with self.assertRaises(OSError):
            intake.inspect_collection(self.root, 'link', self.receipt_sha)

    def test_special_file_rejected_without_blocking(self):
        os.mkfifo(self.folder / 'pipe')
        with self.assertRaisesRegex(intake.IntakeError, 'special file'):
            self.inspect()

    def test_snapshot_without_current_output_observation_is_explicitly_partial(self):
        self.integrity = {}
        self.write()
        report = self.inspect()
        self.assertTrue(report['partial'])
        self.assertFalse(report['artifacts'][0]['is_latest'])
        self.assertEqual(report['artifacts'][0]['version'], 'accepted')

    def test_read_bounds_enforced_before_unbounded_read(self):
        for limits in ({'max_file_bytes': 10}, {'max_total_bytes': 10}, {'max_files': 1}):
            with self.subTest(limits=limits):
                with self.assertRaisesRegex(intake.IntakeError, 'bound'):
                    self.inspect(**limits)

    def test_existing_destination_is_never_replaced(self):
        output = self.root / 'runs/imported'
        output.mkdir()
        for content in (None, b'private existing work'):
            if content:
                (output / 'work.txt').write_bytes(content)
            with self.assertRaisesRegex(intake.IntakeError, 'already exists'):
                self.materialize()
            self.assertTrue(output.is_dir())
            if content:
                self.assertEqual((output / 'work.txt').read_bytes(), content)

    def test_output_symlink_and_source_overlap_fail(self):
        (self.root / 'redirect').symlink_to(self.root / 'runs', target_is_directory=True)
        with self.assertRaises(OSError):
            self.materialize('redirect/imported')
        for target in ('runs', self.collection, self.collection + '/inside'):
            with self.subTest(target=target):
                with self.assertRaises(intake.IntakeError):
                    self.materialize(target)

    def test_atomic_publish_refuses_competing_empty_directory_and_cleans_stage(self):
        original = intake._rename_exclusive
        def competing(parent_fd, old, new):
            os.mkdir(new, dir_fd=parent_fd)
            original(parent_fd, old, new)
        with mock.patch.object(intake, '_rename_exclusive', side_effect=competing):
            with self.assertRaisesRegex(intake.IntakeError, 'already exists'):
                self.materialize()
        self.assertEqual(list((self.root / 'runs/imported').iterdir()), [])
        self.assertEqual(list((self.root / 'runs').glob('.claude-intake-*')), [])

    def test_cli_uses_installed_lab_root_and_emits_machine_readable_report(self):
        installed = self.root / 'scripts/claude_terminal/claude_collection_intake.py'
        installed.parent.mkdir(parents=True)
        installed.write_bytes(HELPER.read_bytes())
        run = subprocess.run([sys.executable, '-B', str(installed), 'inspect', '--collection', self.collection,
                              '--collection-sha256', self.receipt_sha], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)['packet_id'], 'old-packet')
        self.assertEqual(list(self.root.rglob('__pycache__')), [])
        command = [sys.executable, '-B', str(installed), 'inspect', '--collection', self.collection,
                   '--collection-sha256', self.receipt_sha]
        rejected = subprocess.run(command + ['--max-total-bytes', '10'], capture_output=True, text=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn('--max-total-bytes', json.loads(rejected.stderr)['error'])
        accepted = subprocess.run(command + ['--max-total-bytes', '65536', '--max-file-bytes', '32768',
                                            '--max-files', '32'], capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        invalid = subprocess.run(command + ['--max-files', '0'], capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn('positive integers', json.loads(invalid.stderr)['error'])


if __name__ == '__main__':
    unittest.main()
