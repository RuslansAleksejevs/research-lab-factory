#!/usr/bin/env python3
"""Local public-package checks; no model calls, publication or network."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import re
import unicodedata
import os
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILES = ('minimal_article.json', 'exploratory_program.json', 'philosophy_program.json')

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
MAX_FILES = 1000
REQUIRED_FILES = {
    'TEMPLATE_VERSION', 'scripts/new_lab.py', 'scripts/local_bootstrap_layer.py',
    'schemas/new_lab_request.schema.json', 'schemas/lab_profile.schema.json',
    'schemas/generation_manifest.schema.json', 'scaffold/manifest.json',
    'README.md', 'AGENTS.md', 'Makefile', 'scripts/check_public_kit.py',
    'overlays/user/AGENTS.user.md', 'overlays/user/user_policy_manifest.json',
    '.agents/skills/create-research-lab/SKILL.md',
    'scaffold/base/AGENTS.md', 'scaffold/base/scripts/doctor.py',
    'scaffold/base/scripts/validate_lab.py', 'scaffold/base/scripts/research_memory.py',
    'scaffold/philosophy/AGENTS.md', 'scaffold/philosophy/scripts/doctor.py',
    'scaffold/philosophy/scripts/validate_lab.py',
    *('profiles/examples/' + name for name in PROFILES),
}


def relative(name):
    if (not isinstance(name, str) or not name or name.startswith('/') or '\\' in name
            or any(part in ('', '.', '..') for part in name.split('/'))
            or any(ord(c) < 32 for c in name)):
        raise ValueError('Unsafe inventory path')
    return PurePosixPath(name)


def regular_bytes(name, limit):
    parts = relative(name).parts
    # Anchor every component to an open directory: a symlink swapped in after
    # the check cannot redirect the content read to a different directory.
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open('/', flags)
    try:
        root_parts = Path(os.path.abspath(ROOT)).parts[1:]
        for component in (*root_parts, *parts[:-1]):
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        with os.fdopen(fd, 'rb') as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
                raise ValueError('Not a bounded regular candidate file: ' + name)
            data = source.read(limit + 1)
            after = os.fstat(source.fileno())
            signature = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
            named = os.stat(parts[-1], dir_fd=descriptor, follow_symlinks=False)
            if len(data) > limit or signature(before) != signature(after) or signature(before) != signature(named):
                raise ValueError('Candidate file changed during read: ' + name)
            return data, '100755' if before.st_mode & 0o111 else '100644'
    finally:
        os.close(descriptor)


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate manifest JSON key')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def digest(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def manifest_rows(inventory):
    expected = {'schema_version', 'kit_id', 'status', 'spec_sha256', 'files', 'data_overrides', 'boundary'}
    if not isinstance(inventory, dict) or set(inventory) != expected:
        raise ValueError('Unexpected or missing manifest fields')
    if (type(inventory['schema_version']) is not int or inventory['schema_version'] != 1
            or inventory['kit_id'] != 'research-lab-factory-experimental'
            or inventory['status'] != 'EXPERIMENTAL_SNAPSHOT'
            or not digest(inventory['spec_sha256'])
            or not isinstance(inventory['boundary'], str) or not 1 <= len(inventory['boundary']) <= 4096):
        raise ValueError('Invalid manifest metadata')
    overrides = inventory['data_overrides']
    if not isinstance(overrides, list) or len(overrides) != 1:
        raise ValueError('Expected one documented manifest data override')
    override = overrides[0]
    if (not isinstance(override, dict) or set(override) != {'path', 'fields', 'source_sha256', 'override_sha256', 'reason'}
            or override['path'] != 'scaffold/manifest.json' or override['fields'] != ['forbidden_kernel_fingerprints']
            or not digest(override['source_sha256']) or not digest(override['override_sha256'])
            or not isinstance(override['reason'], str) or not 1 <= len(override['reason']) <= 4096):
        raise ValueError('Invalid manifest data override')
    rows = inventory['files']
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_FILES:
        raise ValueError('Manifest needs a nonempty bounded file inventory')
    seen, names, total = set(), set(), 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'path', 'sha256', 'bytes', 'mode', 'origin'}:
            raise ValueError('Unexpected or missing inventory row fields')
        relative(row['path'])
        folded = unicodedata.normalize('NFC', row['path']).casefold()
        if folded in seen or row['path'] == 'PUBLIC_KIT_MANIFEST.json':
            raise ValueError('Duplicate, case-colliding or recursive inventory row')
        seen.add(folded); names.add(row['path'])
        if (not digest(row['sha256']) or type(row['bytes']) is not int or not 0 <= row['bytes'] <= MAX_FILE_BYTES
                or row['mode'] not in ('100644', '100755')
                or row['origin'] not in ('sources', 'assets', 'reviewed_data_override')):
            raise ValueError('Invalid inventory size, digest, mode or origin')
        total += row['bytes']
        if total > MAX_TOTAL_BYTES:
            raise ValueError('Inventory exceeds total byte bound')
    if not REQUIRED_FILES <= names:
        raise ValueError('Manifest is missing required core files')
    return rows


def verify():
    raw, _ = regular_bytes('PUBLIC_KIT_MANIFEST.json', MAX_MANIFEST_BYTES)
    rows = manifest_rows(strict_json(raw))
    changed = []
    actual_total = 0
    for row in rows:
        try:
            data, mode = regular_bytes(row['path'], MAX_FILE_BYTES)
        except FileNotFoundError:
            changed.append(row['path'])
            continue
        actual_total += len(data)
        if actual_total > MAX_TOTAL_BYTES:
            raise ValueError('Candidate exceeds total byte bound')
        if hashlib.sha256(data).hexdigest() != row['sha256'] or len(data) != row['bytes'] or mode != row['mode']:
            changed.append(row['path'])
    print(json.dumps({'status': 'MODIFIED_CHECKOUT' if changed else 'CONSISTENT_WITH_MANIFEST',
                      'changed_files': changed, 'files_checked': len(rows),
                      'boundary': 'Consistency with this mutable local manifest only; not release authenticity or research quality.'}, indent=2))
    return 1 if changed else 0


def validate():
    for name in PROFILES:
        result = subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/new_lab.py'),
                                 'validate-profile', '--request', 'profiles/examples/' + name],
                                cwd=ROOT, check=False, timeout=120,
                                env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
        if result.returncode:
            return result.returncode
    print('PASS: three neutral starter profiles; no laboratory or model run created.')
    return 0

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'validate'))
    command = parser.parse_args().command
    try:
        return verify() if command == 'verify' else validate()
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
