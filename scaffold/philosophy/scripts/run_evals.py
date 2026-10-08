#!/usr/bin/env python3
"""Synthetic smoke checks; intentionally distinct from actual provider capture."""
import argparse
from pathlib import Path
import sys
import unittest

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--smoke', action='store_true')
parser.add_argument('--no-report', action='store_true')
parser.parse_args()
root = Path(__file__).resolve().parents[1]
required_terminal = [
    "scripts/claude_terminal/claude_runner.py",
    "scripts/claude_terminal/claude_cli_launch.py",
    "scripts/claude_terminal/claude_runner_support.py",
    "scripts/claude_terminal/claude_source_capture.py",
    "templates/claude_terminal/request.json",
    "workflows/claude_terminal_protocol.md",
    "tests/test_claude_terminal.py",
    "tests/test_claude_terminal_launch.py",
    "scripts/claude_terminal/claude_collection_intake.py",
    "tests/test_claude_terminal_timeout.py",
    "tests/test_claude_terminal_research.py",
    "tests/test_claude_collection_intake.py",
]
missing = [p for p in required_terminal if not (root / p).is_file() or (root / p).is_symlink()]
if missing:
    for path in missing:
        print('FAIL missing or unsafe Claude terminal file: ' + path)
    sys.exit(1)
suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
