"""Offline launcher configuration and dispatch boundaries; no Claude calls."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# Isolate the new adapter from existing bound runners during test discovery.
import importlib.util as _importutil
_standard = ('claude_runner', 'claude_runner_support', 'claude_source_capture')
_saved = {name: sys.modules.get(name) for name in _standard}
_scripts = Path(__file__).resolve().parents[1] / 'scripts' / 'claude_terminal'
def _load(name, filename):
    spec = _importutil.spec_from_file_location(name, _scripts / filename)
    module = _importutil.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module
try:
    capture = _load(__name__ + '_source', 'claude_source_capture.py')
    sys.modules['claude_source_capture'] = capture
    support = _load(__name__ + '_support', 'claude_runner_support.py')
    sys.modules['claude_runner_support'] = support
    r = _load(__name__ + '_runner', 'claude_runner.py')
    sys.modules['claude_runner'] = r
    launcher = _load(__name__ + '_launcher', 'claude_cli_launch.py')
finally:
    for name, module in _saved.items():
        if module is None: sys.modules.pop(name, None)
        else: sys.modules[name] = module


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / 'runs/round').mkdir(parents=True)
        mocked = patch.object(launcher, 'ROOT', self.root)
        mocked.start()
        self.addCleanup(mocked.stop)

    def config(self, directory='runs/round'):
        (self.root / 'runs/claude-terminal-active.json').write_text(json.dumps({
            'packet': '/Users/Shared/math-research-cli/abel-rounds/test',
            'record_directory': directory,
        }))

    def test_unconfigured_status_does_not_launch(self):
        with patch.object(launcher.r, 'preflight', side_effect=AssertionError('no dispatch')):
            self.assertEqual(launcher.status()['status'], 'not_configured')

    def test_status_command_without_bytecode_flags_keeps_tree_clean(self):
        scripts = self.root / 'ordinary-cli/scripts/claude_terminal'
        scripts.mkdir(parents=True)
        for source in _scripts.glob('*.py'):
            shutil.copy2(source, scripts / source.name)
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        env.pop('PYTHONPYCACHEPREFIX', None)
        result = subprocess.run([sys.executable, str(scripts / 'claude_cli_launch.py'), '--status'],
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'not_configured')
        self.assertEqual(list(scripts.rglob('__pycache__')), [])

    def test_launch_without_round_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'No active round'):
            launcher.launch()

    def test_record_path_escape_rejected(self):
        for directory in ('../escape', '/tmp/escape', 'knowledge/round'):
            self.config(directory)
            with self.assertRaises(ValueError):
                launcher.configure()

    def test_record_symlink_rejected(self):
        (self.root / 'runs/link').symlink_to(self.root / 'runs/round')
        self.config('runs/link')
        with self.assertRaisesRegex(ValueError, 'symlinks'):
            launcher.configure()

    def test_running_supervisor_prevents_duplicate(self):
        self.config()
        (self.root / 'runs/round/status.json').write_text(json.dumps({'phase': 'running', 'pid': 123}))
        with patch.object(launcher.r, 'alive', return_value=True), patch.object(launcher.r, 'preflight', side_effect=AssertionError('no dispatch')):
            self.assertEqual(launcher.launch()['status'], 'already_running')

    def test_uncertain_launch_requires_inspection(self):
        self.config()
        (self.root / 'runs/round/status.json').write_text('{"phase":"starting"}')
        with self.assertRaisesRegex(ValueError, 'Uncertain previous start'):
            launcher.launch()

    def test_disabled_switch_blocks_launch_and_worker_before_dispatch(self):
        (self.root / 'config').mkdir()
        (self.root / 'config/integrations.json').write_text('{"claude_terminal":{"enabled":false}}')
        with patch.object(launcher.r, 'preflight', side_effect=AssertionError('no provider')):
            self.assertEqual(launcher.status()['status'], 'disabled')
            for operation in (lambda: launcher.launch(), lambda: launcher.worker('unused')):
                with self.assertRaisesRegex(ValueError, 'disabled'):
                    operation()
        self.assertFalse((self.root / 'runs/round/status.json').exists())

    def test_new_profile_cannot_silently_fall_back_if_setting_is_missing(self):
        (self.root / 'LAB_PROFILE.json').write_text('{"integrations":{"claude_terminal":{"enabled":false}}}')
        with self.assertRaisesRegex(ValueError, 'Missing config'):
            launcher.launch()

    def test_malformed_or_symlinked_switch_fails_before_dispatch(self):
        (self.root / 'config').mkdir()
        path = self.root / 'config/integrations.json'
        for value in (None, {}, {'claude_terminal': {'enabled': 1}}, {'claude_terminal': {'enabled': 'false'}}):
            path.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'boolean'):
                launcher.launch()
        path.unlink()
        target = self.root / 'setting.json'
        target.write_text('{"claude_terminal":{"enabled":true}}')
        path.symlink_to(target)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            launcher.launch()


if __name__ == '__main__':
    unittest.main()
