"""Offline resource ceilings: synthetic subprocesses, never Claude or a network."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

_standard = ('claude_runner_support', 'claude_source_capture')
_saved = {name: sys.modules.get(name) for name in _standard}
_scripts = Path(__file__).resolve().parents[1] / 'scripts' / 'claude_terminal'
def _load(name, filename):
    spec = importlib.util.spec_from_file_location(name, _scripts / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
try:
    capture = _load(__name__ + '_capture', 'claude_source_capture.py')
    sys.modules['claude_source_capture'] = capture
    support = _load(__name__ + '_support', 'claude_runner_support.py')
    sys.modules['claude_runner_support'] = support
    r = _load(__name__ + '_runner', 'claude_runner.py')
finally:
    for name, module in _saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class ResourceBudgetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='terminal-budget-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = self.base / 'packet'
        for name in ('LAB_ROOT', 'NEUTRAL_ROOT'):
            p = patch.object(r, name, self.base)
            p.start()
            self.addCleanup(p.stop)
        self.req = {'id': 'bounded-round', 'purpose': 'research',
                    'max_wall_seconds': 0.6,
                    'tasks': [{'id': 'one', 'prompt': 'Synthetic resource fixture.',
                               'model': 'claude-opus-5-5', 'effort': 'max',
                               'public_web': False, 'research_checks': False,
                               'required_outputs': ['report.md']}]}
        self.request = self.base / 'request.json'

    def prepare(self):
        self.request.write_bytes(r.canonical(self.req))
        r.prepare(self.request, self.root, research_draft=True)
        m = r.verify(self.root)
        review = {'files': {**m['input_hashes'], **m['support_hashes'],
                           'manifest.json': r.digest(r.regular(self.root / 'manifest.json')),
                           'runner.py': m['runner_sha256']},
                  'privacy_reviewed': True, 'reviewer': 'synthetic-test', 'notes': 'Fixture only',
                  'live_test_approved': True, 'approval_source': 'synthetic-test',
                  'subscription_auth_verified': True, 'research_approved': True,
                  'technical_acceptance': 'synthetic', 'rules_checked': True,
                  'archive_approval_event': 'synthetic'}
        path = self.base / 'review.json'
        path.write_bytes(r.canonical(review))
        r.release(self.root, path)

    def fake(self, body, read_input=True):
        path = self.base / 'fake.py'
        path.write_text('import json, os, signal, subprocess, sys, time\n'
                        'from pathlib import Path\n'
                        'sid = sys.argv[1]\n'
                        + ('sys.stdin.read()\n' if read_input else '')
                        + body)
        return path

    @contextlib.contextmanager
    def fake_cli(self, path, calls=None):
        def args(exe, task, state):
            if calls is not None:
                calls.append((state['session_id'], bool(state.get('session_observed'))))
            return [sys.executable, '-B', str(path), state['session_id']]
        with patch.object(r, 'preflight', return_value='fake'), \
             patch.object(r, 'arguments', side_effect=args), \
             patch.object(support, 'native_observations', return_value={'observations': []}):
            yield

    def state(self, tid='one'):
        return r.load(self.root / 'state.json')[tid]

    def clock_case_in_child(self):
        """Bound a controlled-clock test with a separate real-time watchdog."""
        marker = 'LAB_CONTROLLED_DEADLINE_TEST_CASE'
        if os.environ.get(marker) == self._testMethodName:
            return False
        result = subprocess.run(
            [sys.executable, '-I', '-B', str(Path(__file__).resolve()),
             type(self).__name__ + '.' + self._testMethodName, '-v'],
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', marker: self._testMethodName},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return True

    @contextlib.contextmanager
    def controlled_attempt_clock(self):
        """Charge real attempts at their observed init, independent of host load.

        Only these budget-sharing tests use logical time. Real alarm, blocked
        pipe/source, descendant cleanup and resume integration tests stay real.
        """
        current = [1000.0]
        attempts = []
        runner_time = SimpleNamespace(**vars(time))
        runner_time.monotonic = lambda: current[0]
        runner_signal = SimpleNamespace(**vars(signal))
        runner_signal.getitimer = lambda which: (0.0, 0.0)
        runner_signal.setitimer = lambda *args: (0.0, 0.0)
        original_event = r.event

        def event(root, kind, **payload):
            original_event(root, kind, **payload)
            if kind == 'attempt.started':
                budget = r._ACTIVE_BUDGET
                attempts.append({'budget': budget, 'deadline': budget.deadline,
                                 'task': payload['task'], 'session_id': payload['session_id']})
            observation = payload.get('observation', {})
            if kind == 'provider.visible' and observation.get('type') == 'system':
                current[0] += 0.35

        with patch.object(r, 'time', runner_time), patch.object(r, 'signal', runner_signal), \
                patch.object(r, 'event', side_effect=event):
            yield attempts

    def test_exited_unreaped_leader_is_reaped_before_group_cleanup(self):
        proc = subprocess.Popen([sys.executable, '-S', '-B', '-c', 'pass'],
                                start_new_session=True, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        try:
            # Pipe EOF establishes exit without Popen.wait/poll reaping it.
            proc.stdout.read()
            self.assertIsNone(proc.returncode)
            r.stop_process_group(proc)
            self.assertEqual(proc.returncode, 0)
        finally:
            proc.stdout.close()
            proc.wait(timeout=3)

    def test_exit_between_poll_and_signal_is_reaped_then_retried(self):
        proc = Mock(pid=12345)
        proc.poll.side_effect = [None, 0]
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=[PermissionError('exited leader'), ProcessLookupError()]) as kill:
            group.signal(signal.SIGINT)
        self.assertEqual(kill.call_count, 2)
        self.assertTrue(group.closed)

    def test_live_process_permission_denial_is_not_suppressed(self):
        proc = Mock(pid=12345)
        proc.poll.return_value = None
        proc.wait.side_effect = subprocess.TimeoutExpired('synthetic-live-child', 0.1)
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=PermissionError('genuine denial')) as kill:
            with self.assertRaisesRegex(PermissionError, 'genuine denial'):
                group.signal(signal.SIGKILL)
        self.assertEqual(kill.call_count, 1)
        proc.wait.assert_called_once_with(timeout=0.1)
        self.assertFalse(group.closed)

    def test_exit_not_yet_waitable_gets_bounded_reap_then_group_retry(self):
        proc = Mock(pid=12345)
        proc.poll.side_effect = [None, None]
        proc.wait.return_value = 0
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=[PermissionError('exiting leader'), ProcessLookupError()]) as kill:
            group.signal(signal.SIGINT)
        proc.wait.assert_called_once_with(timeout=0.1)
        self.assertEqual(kill.call_args_list, [unittest.mock.call(12345, signal.SIGINT)] * 2)
        self.assertTrue(group.closed)

    def test_group_descendants_are_force_stopped_after_bounded_leader_reap(self):
        proc = Mock(pid=12345)
        proc.poll.side_effect = [None, None]
        proc.wait.return_value = 0
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=[PermissionError('exiting leader'), None]) as kill:
            group.signal(signal.SIGKILL)
        proc.wait.assert_called_once_with(timeout=0.1)
        self.assertEqual(kill.call_args_list, [unittest.mock.call(12345, signal.SIGKILL)] * 2)
        self.assertTrue(group.closed)

    def test_permission_denial_after_bounded_reap_is_not_suppressed(self):
        proc = Mock(pid=12345)
        proc.poll.side_effect = [None, None]
        proc.wait.return_value = 0
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=[PermissionError('exiting leader'), PermissionError('descendant denied')]) as kill:
            with self.assertRaisesRegex(PermissionError, 'descendant denied'):
                group.signal(signal.SIGKILL)
        proc.wait.assert_called_once_with(timeout=0.1)
        self.assertEqual(kill.call_count, 2)
        self.assertFalse(group.closed)

    def test_permission_denial_after_leader_reaped_is_not_suppressed(self):
        proc = Mock(pid=12345)
        proc.poll.return_value = 0
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=PermissionError('descendant denied')) as kill:
            with self.assertRaisesRegex(PermissionError, 'descendant denied'):
                group.signal(signal.SIGKILL)
        self.assertEqual(kill.call_count, 1)
        proc.wait.assert_not_called()
        self.assertFalse(group.closed)

    def test_successful_force_stop_is_not_repeated_on_zombie_descendants(self):
        proc = Mock(pid=12345)
        proc.poll.return_value = None
        group = r.ProcessGroup(proc)
        with patch.object(r.os, 'killpg', side_effect=[None, PermissionError('already killed zombie')]) as kill:
            group.signal(signal.SIGKILL)
            group.signal(signal.SIGKILL)
            group.signal(signal.SIGINT)
        self.assertEqual(kill.call_count, 1)
        self.assertTrue(group.closed)

    def test_limits_are_sealed_and_defaulted(self):
        del self.req['max_wall_seconds']
        self.prepare()
        manifest = r.verify(self.root)
        self.assertEqual(manifest['max_wall_seconds'], 3600)
        self.assertEqual(manifest['max_output_bytes'], 64 * 1024 * 1024)

    def test_invalid_limits_fail_before_creating_packet(self):
        for field, values in (
                ('max_wall_seconds', [True, False, None, '1', 0, -1, float('inf'), float('nan'), 604801, 10 ** 1000]),
                ('max_output_bytes', [True, False, None, '1', 0, -1, 1.1, 2 ** 63])):
            for value in values:
                with self.subTest(field=field, value=str(value)[:30]):
                    req = {**self.req, field: value}
                    self.request.write_bytes(r.canonical(req))
                    with self.assertRaisesRegex(ValueError, field):
                        r.prepare(self.request, self.root, research_draft=True)
                    self.assertFalse(self.root.exists())

    def test_timeout_preserves_partial_and_explicit_resume_reuses_session(self):
        self.prepare()
        init = "print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n"
        fake = self.fake(init + "Path('output/report.md').write_text('partial evidence')\n"
                         "signal.signal(signal.SIGINT, signal.SIG_IGN)\n"
                         "time.sleep(30)\n")
        calls = []
        before = time.monotonic()
        with self.fake_cli(fake, calls):
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 3)
        first = self.state()
        self.assertEqual((result['status'], first['reason']), ('paused', 'time_limit'))
        self.assertTrue(first['session_observed'])
        self.assertTrue(first['output_snapshot_complete'])
        old_key = first['outputs']['report.md']
        self.assertEqual(r.regular(self.root / 'objects' / old_key), b'partial evidence')
        self.assertIsNone(first['pid'])
        self.assertNotIn('output_repair_attempts', first)
        fake = self.fake(init + "Path('output/report.md').write_text('completed evidence')\n"
                         "print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':sid}), flush=True)\n")
        with self.fake_cli(fake, calls):
            resumed = r.run(self.root)
        self.assertEqual(resumed['status'], 'done')
        self.assertEqual(self.state()['session_id'], first['session_id'])
        self.assertTrue(calls[-1][1])
        self.assertEqual(r.regular(self.root / 'objects' / old_key), b'partial evidence')
        receipt = r.collect(self.root, self.base / 'collected')
        self.assertEqual(receipt['collection_sha256'], r.digest(r.regular(self.base / 'collected/collection.json')))

    def test_child_retaining_stdout_does_not_hold_runner_open(self):
        self.prepare()
        child_file = self.base / 'child.py'
        heartbeat = self.base / 'child-heartbeat'
        child_file.write_text("import signal,time\nfrom pathlib import Path\n"
                              "signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
                              "while True:\n Path(" + repr(str(heartbeat)) + ").write_text(str(time.time_ns()))\n time.sleep(.02)\n")
        fake = self.fake("child = subprocess.Popen([sys.executable, '-B', " + repr(str(child_file)) + "])\n"
                         "Path('output/child-pid').write_text(str(child.pid))\n"
                         "Path('output/report.md').write_text('leader finished; child held stdout')\n"
                         "print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n")
        before = time.monotonic()
        with self.fake_cli(fake):
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 3)
        self.assertEqual(result['reason'], 'time_limit')
        child = int((self.root / 'work/one/output/child-pid').read_text())
        self.addCleanup(lambda: self.kill_if_present(child))
        # No process-table permission is needed, and an already-killed zombie
        # does not make this test fail while the host is waiting to reap it.
        first = heartbeat.read_text()
        time.sleep(.12)
        self.assertEqual(heartbeat.read_text(), first)

    @staticmethod
    def kill_if_present(pid):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

    def test_closed_pipes_with_live_process_are_still_bounded(self):
        self.prepare()
        fake = self.fake("Path('output/report.md').write_text('closed streams')\n"
                         "os.close(1); os.close(2)\nsignal.signal(signal.SIGINT, signal.SIG_IGN)\ntime.sleep(30)\n")
        before = time.monotonic()
        with self.fake_cli(fake):
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 3)
        self.assertEqual(result['reason'], 'time_limit')

    def test_success_also_cleans_up_child_that_closed_its_streams(self):
        self.req['max_wall_seconds'] = 2
        self.prepare()
        heartbeat = self.base / 'detached-stream-heartbeat'
        child_file = self.base / 'child.py'
        child_file.write_text("import os,signal,time\nfrom pathlib import Path\n"
                              "os.close(1);os.close(2)\n"
                              "signal.signal(signal.SIGINT,signal.SIG_IGN)\n"
                              "while True:\n Path(" + repr(str(heartbeat)) + ").write_text(str(time.time_ns()))\n time.sleep(.02)\n")
        fake = self.fake("child = subprocess.Popen([sys.executable, '-B', " + repr(str(child_file)) + "])\n"
                         "Path('output/child-pid').write_text(str(child.pid))\n"
                         "Path('output/report.md').write_text('complete fixture')\n"
                         "print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n"
                         "time.sleep(.15)\n"
                         "print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':sid}), flush=True)\n")
        with self.fake_cli(fake):
            result = r.run(self.root)
        self.assertEqual(result['status'], 'done')
        child = int((self.root / 'work/one/output/child-pid').read_text())
        self.addCleanup(lambda: self.kill_if_present(child))
        first = heartbeat.read_text()
        time.sleep(.12)
        self.assertEqual(heartbeat.read_text(), first)

    def test_blocked_source_capture_uses_the_same_deadline(self):
        self.req['tasks'][0]['public_web'] = True
        self.prepare()
        fake = self.fake("print(json.dumps({'type':'assistant','session_id':sid,'message':{'content':"
                         "[{'type':'tool_use','name':'WebFetch','input':{'url':'https://example.com'}}]}}), flush=True)\n"
                         "time.sleep(30)\n")
        with self.fake_cli(fake), patch.object(support, 'source_capture', side_effect=lambda *args: time.sleep(30)):
            before = time.monotonic()
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 3)
        self.assertEqual(result['reason'], 'time_limit')

    def test_preflight_uses_the_same_deadline_without_launch(self):
        self.prepare()
        with patch.object(r, 'preflight', side_effect=lambda: time.sleep(30)), \
             patch.object(r, 'execute', side_effect=AssertionError('must not launch')):
            before = time.monotonic()
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 2)
        self.assertEqual(result['reason'], 'time_limit')
        self.assertFalse(self.state().get('session_observed', False))

    def test_blocked_stdin_is_bounded(self):
        # Larger than a pipe buffer; the fake provider deliberately never reads.
        self.req['tasks'][0]['prompt'] = 'Synthetic fixture. ' * 50000
        self.prepare()
        fake = self.fake('time.sleep(30)\n', read_input=False)
        with patch.object(r, 'POLICY', r.POLICY + ('padding ' * 100000)), self.fake_cli(fake):
            before = time.monotonic()
            result = r.run(self.root)
        self.assertLess(time.monotonic() - before, 3)
        self.assertEqual(result['reason'], 'time_limit')

    def test_repairs_share_deadline(self):
        if self.clock_case_in_child():
            return
        self.req['tasks'][0]['required_outputs'] = ['report.json']
        self.prepare()
        fake = self.fake("print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n"
                         "Path('output/report.json').write_text('{invalid')\n"
                         "print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':sid}), flush=True)\n")
        with self.fake_cli(fake), self.controlled_attempt_clock() as attempts:
            result = r.run(self.root)
        state = self.state()
        self.assertEqual(result['reason'], 'time_limit')
        self.assertEqual(state.get('output_repair_attempts'), 1)
        self.assertEqual(len(attempts), 2)
        self.assertIs(attempts[0]['budget'], attempts[1]['budget'])
        self.assertEqual(attempts[0]['deadline'], attempts[1]['deadline'])
        self.assertAlmostEqual(attempts[0]['deadline'], 1000.6)
        events = [r.load(p) for p in (self.root / 'records').glob('*.json')]
        starts = [e for e in events if e['kind'] == 'attempt.started']
        self.assertEqual(len(starts), 2)
        self.assertEqual(len({e['session_id'] for e in starts}), 1)

    def test_tasks_share_invocation_deadline(self):
        if self.clock_case_in_child():
            return
        self.req['multi_session_reason'] = 'Two synthetic independent fixtures'
        self.req['tasks'].append({**self.req['tasks'][0], 'id': 'two'})
        self.prepare()
        fake = self.fake("print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n"
                         "Path('output/report.md').write_text('bounded fixture')\n"
                         "print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':sid}), flush=True)\n")
        with self.fake_cli(fake), self.controlled_attempt_clock() as attempts:
            result = r.run(self.root)
        self.assertEqual(self.state('one')['status'], 'done')
        self.assertEqual((result['task'], result['reason']), ('two', 'time_limit'))
        self.assertEqual([attempt['task'] for attempt in attempts], ['one', 'two'])
        self.assertIs(attempts[0]['budget'], attempts[1]['budget'])
        self.assertEqual(attempts[0]['deadline'], attempts[1]['deadline'])
        self.assertAlmostEqual(attempts[0]['deadline'], 1000.6)
        self.assertNotEqual(attempts[0]['session_id'], attempts[1]['session_id'])

    def test_oversized_output_retains_last_snapshot_without_reading_giant_file(self):
        self.req.update(max_wall_seconds=2, max_output_bytes=128 * 1024)
        self.prepare()
        fake = self.fake("Path('output/report.md').write_text('small saved progress')\n"
                         "print(json.dumps({'type':'system','subtype':'init','session_id':sid}), flush=True)\n"
                         "time.sleep(.2)\n"
                         "with Path('output/giant.bin').open('wb') as f: f.truncate(10 * 1024 * 1024)\n"
                         "time.sleep(30)\n")
        with self.fake_cli(fake):
            result = r.run(self.root)
        state = self.state()
        self.assertEqual(result['reason'], 'output_limit')
        self.assertFalse(state['output_snapshot_complete'])
        self.assertIn('report.md', state['outputs'])
        self.assertNotIn('giant.bin', state['outputs'])
        self.assertEqual((self.root / 'work/one/output/giant.bin').stat().st_size, 10 * 1024 * 1024)
        r.collect(self.root, self.base / 'partial')
        receipt = r.load(self.base / 'partial/collection.json')
        self.assertEqual(receipt['integrity']['one'], 'partial_snapshot_output_limit')
        self.assertLess(sum(p.stat().st_size for p in (self.root / 'objects').iterdir()), 128 * 1024)

    def test_tree_snapshot_rejects_oversized_file_before_reading(self):
        output = self.base / 'output'
        output.mkdir()
        with (output / 'large').open('wb') as f:
            f.truncate(1024 * 1024)
        with patch.object(os, 'open', side_effect=AssertionError('must not open oversized content')):
            with self.assertRaises(r.BudgetExceeded) as stopped:
                r.tree_bytes(output, max_bytes=1024)
        self.assertEqual(stopped.exception.reason, 'output_limit')

    def test_output_budget_counts_old_objects_records_and_current_files(self):
        self.prepare()
        for name in ('objects/old', 'records/old', 'work/one/output/current'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'x' * 5000)
        budget = r.InvocationBudget(self.root, {'max_wall_seconds': 10, 'max_output_bytes': 12000})
        with self.assertRaises(r.BudgetExceeded) as stopped:
            budget.check()
        self.assertEqual(stopped.exception.reason, 'output_limit')

    def test_output_inventory_does_not_follow_work_symlink(self):
        self.prepare()
        elsewhere = self.base / 'outside'
        elsewhere.mkdir()
        (self.root / 'work').symlink_to(elsewhere, target_is_directory=True)
        budget = r.InvocationBudget(self.root, r.verify(self.root))
        with self.assertRaisesRegex(ValueError, 'Symlink in resource inventory'):
            budget.check()

    def test_budget_alarm_during_atomic_write_keeps_published_bytes(self):
        destination = self.base / 'record.json'
        destination.write_bytes(b'published version')
        with patch.object(os, 'fsync', side_effect=r.BudgetExceeded('time_limit')):
            with self.assertRaises(r.BudgetExceeded):
                r.atomic(destination, b'new version')
        self.assertEqual(destination.read_bytes(), b'published version')
        self.assertFalse(list(self.base.glob('.tmp-*')))


if __name__ == '__main__':
    unittest.main()
