"""Source-capture provenance regressions; mocked bytes only, no web/model calls."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(__name__ + '_fixture', Path(__file__).with_name('test_claude_terminal.py'))
fixture_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = fixture_module
spec.loader.exec_module(fixture_module)
r, support = fixture_module.r, fixture_module.support


class SourceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.RunnerTests('runTest')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.task = {**self.fixture.req['tasks'][0], 'research_checks': True, 'public_web': True}
        self.states = {'survey': {'status': 'pending', 'session_id': 'test'}}
        self.work = r.stage(self.root, self.task, self.states)
        self.folder = self.work / 'output/sources'
        self.folder.mkdir()
        self.url = 'https://example.org/synthetic-paper'
        self.key = r.digest(self.url.encode())
        self.receipt = self.folder / (self.key + '.json')
        self.authority = self.root / 'records/source-captures/survey' / self.receipt.name
        (self.work / 'output/report.md').write_text('Synthetic report, not mathematical evidence.')
        (self.work / 'output/source-status.json').write_bytes(r.canonical({
            'sources': [], 'no_external_sources_reason': 'Synthetic offline test.'}))
        self.response = (b'Actual mocked source bytes', 'text/plain', 'utf-8', {
            'requested_url': self.url, 'final_url': self.url, 'http_status': 200})

    def capture(self):
        with patch.object(support.sources, 'fetch', return_value=self.response) as fetch:
            support.source_capture(r, self.root, 'survey', self.url)
        return fetch.call_count

    def validate(self):
        return support.validate(r, self.root, self.task, self.states['survey'], {
            'observations': [{'model': self.task['model'], 'effort': self.task['effort']}]})

    def fake_receipt(self):
        fake = b'abc'
        text_name = self.key + '.txt'
        (self.folder / text_name).write_bytes(fake)
        self.receipt.write_bytes(r.canonical({'url': self.url, 'status': 'raw_and_text_saved',
            'raw': None, 'text': text_name, 'text_sha256': r.digest(fake)}))

    def test_model_receipt_alone_does_not_skip_actual_retrieval(self):
        self.fake_receipt()
        self.assertEqual(self.capture(), 1)
        self.assertEqual((self.folder / (self.key + '.txt')).read_bytes(), self.response[0])
        self.assertTrue(self.authority.is_file())
        self.assertTrue(self.validate()['passed'])

    def test_model_receipt_without_runner_authority_is_untrusted(self):
        self.fake_receipt()
        report = self.validate()
        self.assertFalse(report['passed'])
        self.assertIn('untrusted_source_receipt:' + self.receipt.name, report['errors'])

    def test_unchanged_runner_capture_can_be_reused_without_fetch(self):
        self.assertEqual(self.capture(), 1)
        before = self.authority.read_bytes()
        with patch.object(support.sources, 'fetch', side_effect=AssertionError('Unexpected network call')):
            support.source_capture(r, self.root, 'survey', self.url)
        self.assertEqual(self.authority.read_bytes(), before)
        self.assertTrue(self.validate()['passed'])

    def test_joint_artifact_and_receipt_edit_cannot_rebind_authority(self):
        self.capture()
        receipt = r.load(self.receipt)
        for kind in ('raw', 'text'):
            (self.folder / receipt[kind]).write_bytes(b'abc')
            receipt[kind + '_sha256'] = r.digest(b'abc')
        self.receipt.write_bytes(r.canonical(receipt))
        report = self.validate()
        self.assertFalse(report['passed'])
        self.assertIn('source_authority_mismatch:' + self.receipt.name, report['errors'])
        with patch.object(support.sources, 'fetch', side_effect=AssertionError('Do not silently repair tampering')):
            with self.assertRaisesRegex(ValueError, 'receipt changed'):
                support.source_capture(r, self.root, 'survey', self.url)

    def test_removed_captured_receipt_or_artifact_is_detected(self):
        self.capture()
        original = self.receipt.read_bytes()
        self.receipt.unlink()
        self.assertFalse(self.validate()['passed'])
        self.receipt.write_bytes(original)
        (self.folder / r.load(self.receipt)['raw']).unlink()
        self.assertFalse(self.validate()['passed'])

    def test_failed_retrieval_is_bound_as_unavailable_not_source_evidence(self):
        with patch.object(support.sources, 'fetch', side_effect=OSError('synthetic unavailable')):
            support.source_capture(r, self.root, 'survey', self.url)
        self.assertEqual(r.load(self.receipt)['status'], 'unavailable')
        self.assertEqual(r.load(self.authority)['files'], {})
        self.assertTrue(self.validate()['passed'])

    def test_coverage_row_is_a_model_declaration_not_a_capture_receipt(self):
        (self.work / 'output/model-notes.txt').write_text('Model-produced text')
        (self.work / 'output/source-status.json').write_bytes(r.canonical({'sources': [{
            'url': self.url, 'coverage': 'full', 'note': 'Synthetic declared coverage only',
            'artifact': 'output/model-notes.txt'}]}))
        report = self.validate()
        self.assertTrue(report['passed'])
        self.assertEqual(report['checks']['source_capture_authorities'], 0)

    def test_runner_authority_is_collected_with_existing_records(self):
        self.fixture.release()
        self.capture()
        destination = self.fixture.base / 'collected'
        r.collect(self.root, destination)
        relative = self.authority.relative_to(self.root).as_posix()
        self.assertEqual((destination / relative).read_bytes(), self.authority.read_bytes())
        self.assertEqual(r.load(destination / 'collection.json')['files'][relative], r.digest(self.authority.read_bytes()))

    def test_authority_directory_symlink_cannot_redirect_capture(self):
        outside = self.fixture.base / 'outside'
        outside.mkdir()
        records = self.root / 'records'
        records.mkdir(exist_ok=True)
        (records / 'source-captures').symlink_to(outside, target_is_directory=True)
        with patch.object(support.sources, 'fetch', side_effect=AssertionError('No retrieval before safe destination')):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                support.source_capture(r, self.root, 'survey', self.url)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
