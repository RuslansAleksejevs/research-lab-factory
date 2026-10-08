#!/usr/bin/env python3
"""Read-only runtime check; no provider availability is inferred."""
import ast
import json
import os
from pathlib import Path
import sys
import fcntl

root = Path(__file__).resolve().parents[1]
errors = []
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
for relative in required_terminal:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        errors.append('missing or unsafe Claude terminal file: ' + relative)
if sys.version_info < (3, 9):
    errors.append('Python 3.9+ required')
for option in ('O_NOFOLLOW', 'O_DIRECTORY'):
    if not hasattr(os, option):
        errors.append('runtime missing ' + option)
for path in sorted((root / 'scripts').glob('*.py')):
    try:
        ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    except (OSError, SyntaxError) as exc:
        errors.append(str(exc))
print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'errors': errors,
                  'python': sys.version.split()[0], 'archive': 'local stdlib filesystem',
                  'provider_capture': 'Must be checked per explicit session; not inferred from doctor',
                  'optional_provider': 'UNCONFIGURED'}, indent=2))
sys.exit(bool(errors))
