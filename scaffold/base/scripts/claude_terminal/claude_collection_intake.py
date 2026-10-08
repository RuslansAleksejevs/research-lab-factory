#!/usr/bin/env python3
"""Inspect a collected Claude packet as untrusted data; never execute its code.

Hashes establish internal byte consistency, not provenance or mathematical truth.
The optional materializer publishes a new evidence directory, never a checkpoint.
"""
import argparse
import contextlib
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = 'laboratory-claude-terminal.v1'
STATUS = 'UNVERIFIED_EXTERNAL_OUTPUT'
DEFAULT_MAX_TOTAL_BYTES = 128 * 1024 * 1024
DEFAULT_MAX_FILE_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_FILES = 4096
MAX_JSON_BYTES = 2 * 1024 * 1024


class IntakeError(ValueError):
    pass


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def _relative(value):
    if (not isinstance(value, str) or not value or '\\' in value
            or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
            or len(value) > 2048):
        raise IntakeError('Expected a bounded relative path')
    parts = value.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise IntakeError('Unsafe relative path: ' + value)
    return PurePosixPath(value)


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{64}', value):
        raise IntakeError('Expected a lowercase SHA-256 digest')
    return value


def _mapping(value, label):
    if not isinstance(value, dict):
        raise IntakeError(label + ' must be an object')
    return value


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise IntakeError('Duplicate JSON key: ' + key)
        value[key] = item
    return value


def _json(data, label):
    if len(data) > MAX_JSON_BYTES:
        raise IntakeError(label + ' exceeds the JSON size bound')
    try:
        return _mapping(json.loads(data, object_pairs_hook=_pairs), label)
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise IntakeError('Invalid JSON in ' + label + ': ' + str(exc)) from exc


@contextlib.contextmanager
def _directory(root, relative=None):
    """Open every directory component without following symlinks."""
    path = Path(root).absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        parts = list(path.parts[1:])
        if relative is not None:
            parts.extend(_relative(relative).parts)
        for part in parts:
            if part in ('.', '..'):
                raise IntakeError('Ambiguous directory component')
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read_tree(fd, max_total_bytes, max_file_bytes, max_files):
    """Bound all reads and retain exact validated bytes for materialization."""
    result, total, entries = {}, 0, 0

    def visit(parent, prefix='', depth=0):
        nonlocal total, entries
        if depth > 64:
            raise IntakeError('Collection directory nesting exceeds the bound')
        before = os.fstat(parent)
        for name in sorted(os.listdir(parent)):
            entries += 1
            if entries > max_files * 2:
                raise IntakeError('Collection entry count exceeds the bound')
            rel = prefix + name
            _relative(rel)
            entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                try:
                    if _signature(os.fstat(child)) != _signature(entry):
                        raise IntakeError('Collection directory changed during read')
                    visit(child, rel + '/', depth + 1)
                finally:
                    os.close(child)
            elif stat.S_ISREG(entry.st_mode):
                if len(result) >= max_files or entry.st_size > max_file_bytes or total + entry.st_size > max_total_bytes:
                    raise IntakeError('Collection file count or byte size exceeds the bound; select explicit --max-total-bytes, --max-file-bytes or --max-files limits for a larger reviewed intake')
                child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
                with os.fdopen(child, 'rb') as source:
                    initial = os.fstat(source.fileno())
                    if not stat.S_ISREG(initial.st_mode) or _signature(initial) != _signature(entry):
                        raise IntakeError('Collection file changed before read')
                    data = source.read(min(max_file_bytes, max_total_bytes - total) + 1)
                    if len(data) != entry.st_size or _signature(os.fstat(source.fileno())) != _signature(entry):
                        raise IntakeError('Collection file changed during read')
                total += len(data)
                result[rel] = data
            else:
                raise IntakeError('Collection contains a symlink or special file: ' + rel)
        if _signature(os.fstat(parent)) != _signature(before):
            raise IntakeError('Collection directory changed during read')

    visit(fd)
    return result


def _bindings(value, label):
    result = {}
    for name, digest in _mapping(value, label).items():
        _relative(name)
        result[name] = _digest(digest)
    return result


def _inspect(root, collection, collection_sha256, *, max_total_bytes=DEFAULT_MAX_TOTAL_BYTES,
             max_file_bytes=DEFAULT_MAX_FILE_BYTES, max_files=DEFAULT_MAX_FILES):
    for value in (max_total_bytes, max_file_bytes, max_files):
        if type(value) is not int or value <= 0:
            raise IntakeError('Read bounds must be positive integers')
    collection = str(_relative(collection))
    _digest(collection_sha256)
    with _directory(root, collection) as fd:
        data = _read_tree(fd, max_total_bytes, max_file_bytes, max_files)
    if 'collection.json' not in data or _sha(data['collection.json']) != collection_sha256:
        raise IntakeError('Collection receipt does not match the selected SHA-256')
    receipt = _json(data['collection.json'], 'collection.json')
    files = _bindings(receipt.get('files'), 'receipt.files')
    if 'collection.json' in files or set(data) != set(files) | {'collection.json'}:
        raise IntakeError('Collection inventory differs from receipt.files')
    for name, digest in files.items():
        if _sha(data[name]) != digest:
            raise IntakeError('Collection file hash mismatch: ' + name)
    for required in ('manifest.json', 'runner.py', 'claude_runner_support.py', 'claude_source_capture.py'):
        if required not in data:
            raise IntakeError('Collection is missing a bound input: ' + required)
    manifest = _json(data['manifest.json'], 'manifest.json')
    if receipt.get('protocol') != PROTOCOL or manifest.get('protocol') != PROTOCOL:
        raise IntakeError('Unsupported collection protocol')
    packet = manifest.get('id')
    if not isinstance(packet, str) or not packet or len(packet) > 256 or receipt.get('packet') != packet:
        raise IntakeError('Collection packet identity mismatch')
    if receipt.get('canonical_import') != 'pending':
        raise IntakeError('Collection must retain its pending canonical import status')
    inputs = _bindings(manifest.get('input_hashes'), 'manifest.input_hashes')
    if any(not name.startswith('inputs/') for name in inputs) or inputs != {
            name: digest for name, digest in files.items() if name.startswith('inputs/')}:
        raise IntakeError('Manifest input bindings mismatch')
    support = _bindings(manifest.get('support_hashes'), 'manifest.support_hashes')
    if set(support) != {'claude_runner_support.py', 'claude_source_capture.py'}:
        raise IntakeError('Unsupported manifest support inventory')
    for name, digest in {**support, 'runner.py': _digest(manifest.get('runner_sha256'))}.items():
        if files.get(name) != digest:
            raise IntakeError('Manifest code binding mismatch: ' + name)
    released = 'release.json' in data
    if released:
        release = _json(data['release.json'], 'release.json')
        if release.get('manifest_sha256') != files['manifest.json'] or release.get('runner_sha256') != manifest['runner_sha256']:
            raise IntakeError('Release binding mismatch')
        _digest(release.get('review_sha256'))
    states = _json(data['state.json'], 'state.json') if 'state.json' in data else {}
    if receipt.get('status') != states:
        raise IntakeError('Receipt state differs from state.json')
    integrity = _mapping(receipt.get('integrity'), 'receipt.integrity')
    tasks = manifest.get('tasks')
    if not isinstance(tasks, list) or not tasks or len(tasks) > 256:
        raise IntakeError('Expected a bounded non-empty manifest task list')
    task_ids, artifacts, summaries, warnings = set(), [], [], []
    for task in tasks:
        task = _mapping(task, 'task')
        tid = task.get('id')
        if len(_relative(tid).parts) != 1 or tid in task_ids:
            raise IntakeError('Invalid or duplicate task id')
        task_ids.add(tid)
        required = task.get('required_outputs')
        if not isinstance(required, list) or not required or len(required) > 4096:
            raise IntakeError('Expected bounded required outputs')
        required = [str(_relative(name)) for name in required]
        if len(set(required)) != len(required):
            raise IntakeError('Duplicate required output')
        state = _mapping(states.get(tid, {}), 'task state')
        status = state.get('status', 'not_started')
        if status not in ('not_started', 'pending', 'running', 'paused', 'needs_review', 'done'):
            raise IntakeError('Unknown task state: ' + str(status))
        previous = _bindings(state.get('outputs', {}), 'state outputs')
        snapshot_path = 'snapshots/' + tid + '.json'
        latest = _bindings(_json(data[snapshot_path], snapshot_path), 'snapshot') if snapshot_path in data else {}
        if previous and snapshot_path not in data:
            raise IntakeError('State output has no collected snapshot')
        changed = status == 'done' and previous != latest
        declared = integrity.get(tid)
        if declared not in (None, 'changed_after_acceptance', 'snapshot_preserved', 'partial_snapshot_output_limit'):
            raise IntakeError('Unknown collected integrity state')
        complete = state.get('output_snapshot_complete', True)
        if type(complete) is not bool:
            raise IntakeError('Invalid output snapshot completeness flag')
        incomplete = not complete or declared == 'partial_snapshot_output_limit' or (declared is None and bool(latest))
        if declared != 'partial_snapshot_output_limit' and changed != (declared == 'changed_after_acceptance'):
            raise IntakeError('Accepted/latest output integrity mismatch')
        for bindings in (previous, latest):
            for name, digest in bindings.items():
                object_path = 'objects/' + digest
                if files.get(object_path) != digest:
                    raise IntakeError('Missing or corrupt snapshot object: ' + name)
        missing = [name for name in required if name not in latest or not data['objects/' + latest[name]]]
        if status == 'done' and any(name not in previous or not data['objects/' + previous[name]] for name in required):
            raise IntakeError('Accepted state is missing a required nonempty output')
        for name in sorted(set(previous) | set(latest)):
            old, new = previous.get(name), latest.get(name)
            versions = []
            if old:
                versions.append(('accepted' if status == 'done' else 'last_attempt', old, old == new))
            if new and new != old:
                versions.append(('latest', new, True))
            for version, digest, is_latest in versions:
                object_path = 'objects/' + digest
                artifacts.append({'task_id': tid, 'name': name, 'version': version,
                                  'is_latest': is_latest and not incomplete, 'is_latest_snapshot': is_latest, 'path': collection + '/' + object_path,
                                  'sha256': digest, 'bytes': len(data[object_path]), 'status': STATUS})
        session = state.get('session_id')
        if session is not None and (not isinstance(session, str) or len(session) > 256):
            raise IntakeError('Invalid session identifier')
        summaries.append({'task_id': tid, 'session_id': session, 'runner_status': status,
                          'runner_reason': state.get('reason'), 'changed_after_acceptance': changed,
                          'missing_required_outputs': missing, 'snapshot_complete': not incomplete,
                          'partial': status != 'done' or bool(missing) or changed or incomplete,
                          'status': STATUS})
        if incomplete:
            warnings.append(tid + ': current output was not completely captured; only preserved versions are available')
        if changed:
            warnings.append(tid + ': output changed after mechanical acceptance; both versions are preserved')
    if set(states) - task_ids or set(integrity) - task_ids:
        raise IntakeError('Collection refers to undeclared tasks')
    if any(name.startswith('snapshots/') and name not in {'snapshots/' + tid + '.json' for tid in task_ids} for name in files):
        raise IntakeError('Collection contains an undeclared task snapshot')
    for name, digest in files.items():
        if name.startswith('objects/') and name != 'objects/' + digest:
            raise IntakeError('Object filename differs from content hash')
    report = {'schema_version': 1, 'packet_id': packet, 'collection': collection,
              'collection_sha256': collection_sha256, 'manifest_sha256': files['manifest.json'],
              'runner_sha256': manifest['runner_sha256'], 'release_binding_present': released,
              'status': STATUS, 'canonical_import': 'pending', 'partial': any(item['partial'] for item in summaries),
              'tasks': summaries, 'artifacts': artifacts, 'warnings': warnings,
              'assurance': 'Internal byte consistency only; no runner code executed, no mathematical verification or external provenance certified.'}
    # One checkpoint path per object; named/versioned references stay in artifacts.
    unique = {item['path']: {'path': item['path'], 'sha256': item['sha256'],
                           'role': 'Collected Claude output; see intake report for task/name/version', 'status': STATUS}
              for item in artifacts}
    report['checkpoint_artifacts'] = [
        {'path': collection + '/' + name, 'sha256': _sha(data[name]),
         'role': 'Claude collection ' + name, 'status': STATUS}
        for name in ('collection.json', 'manifest.json')] + list(unique.values())
    _checkpoint_selection(report)
    return report, data



def _checkpoint_selection(report):
    # The memory envelope is compact (64 artifacts, paths <=512 characters).
    # Keep every detailed binding in artifacts; select safe pointers for it.
    candidates = report['checkpoint_artifacts']
    eligible = [item for item in candidates if len(item['path']) <= 512
                and item['path'] == item['path'].strip()]
    report['checkpoint_artifacts'] = eligible[:64]
    omitted = len(candidates) - len(report['checkpoint_artifacts'])
    report['checkpoint_artifacts_omitted'] = omitted
    warning = 'Checkpoint pointers are a bounded selection; all named artifacts remain in the intake report. Select additional evidence if relevant.'
    report['warnings'] = [item for item in report['warnings'] if item != warning]
    if omitted:
        report['warnings'].append(warning)


def inspect_collection(root, collection, collection_sha256, **limits):
    """Return a read-only report; root is the canonical installed laboratory root."""
    return _inspect(root, collection, collection_sha256, **limits)[0]


def _rename_exclusive(parent_fd, old, new):
    """Atomic directory publication that cannot replace even an empty directory."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        function = libc.renameatx_np
        flag = 4  # RENAME_EXCL
    elif sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        function = libc.renameat2
        flag = 1  # RENAME_NOREPLACE
    else:
        raise IntakeError('Atomic no-clobber directory publication is unsupported on this platform')
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent_fd, os.fsencode(old), parent_fd, os.fsencode(new), flag):
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise IntakeError('Materialization destination already exists')
        raise OSError(code, os.strerror(code))


def materialize_collection(root, collection, collection_sha256, output, **limits):
    """Publish validated bytes in a new directory; never mutate canonical memory."""
    output_path = _relative(output)
    output = str(output_path)
    collection_path = _relative(collection)
    if output_path == collection_path or collection_path in output_path.parents or output_path in collection_path.parents:
        raise IntakeError('Materialization must be separate from the source collection')
    report, data = _inspect(root, collection, collection_sha256, **limits)
    parent = str(output_path.parent)
    with _directory(root, None if parent == '.' else parent) as parent_fd:
        try:
            os.stat(output_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise IntakeError('Materialization destination already exists')
        stage = '.claude-intake-' + uuid.uuid4().hex
        os.mkdir(stage, mode=0o700, dir_fd=parent_fd)
        stage_fd = os.open(stage, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            report['materialized_directory'] = output
            report['checkpoint_artifacts'] = [
                {'path': output + '/' + name, 'sha256': _sha(data[name]),
                 'role': 'Claude collection ' + name, 'status': STATUS}
                for name in ('collection.json', 'manifest.json')]
            for artifact in report['artifacts']:
                rel = 'tasks/' + artifact['task_id'] + '/' + artifact['version'] + '/' + artifact['name']
                content = data['objects/' + artifact['sha256']]
                _write_new(stage_fd, rel, content)
                artifact['path'] = output + '/' + rel
                report['checkpoint_artifacts'].append({
                    'path': artifact['path'], 'sha256': artifact['sha256'],
                    'role': 'Claude ' + artifact['version'] + ' output; see intake.json for task/name',
                    'status': STATUS})
            _checkpoint_selection(report)
            _write_new(stage_fd, 'intake.json', _canonical(report))
            _write_new(stage_fd, 'collection.json', data['collection.json'])
            _write_new(stage_fd, 'manifest.json', data['manifest.json'])
            os.fsync(stage_fd)
            _rename_exclusive(parent_fd, stage, output_path.name)
            os.fsync(parent_fd)
        finally:
            os.close(stage_fd)
            # Only our unpredictable staging directory is eligible for cleanup.
            try:
                _remove_stage(parent_fd, stage)
            except FileNotFoundError:
                pass
    return report



def _remove_stage(parent_fd, name):
    # dir_fd-based cleanup also works on Python 3.9. Never follow a replaced link.
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        for child in os.listdir(fd):
            info = os.stat(child, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                _remove_stage(fd, child)
            else:
                os.unlink(child, dir_fd=fd)
    finally:
        os.close(fd)
    os.rmdir(name, dir_fd=parent_fd)


def _write_new(parent_fd, relative, data):
    parts = _relative(relative).parts
    fd = os.dup(parent_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        target = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444, dir_fd=fd)
        with os.fdopen(target, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    for command in ('inspect', 'materialize'):
        sub = subparsers.add_parser(command)
        sub.add_argument('--collection', required=True, help='Laboratory-relative collected packet directory')
        sub.add_argument('--collection-sha256', required=True, help='SHA-256 of its collection.json receipt')
        sub.add_argument('--max-total-bytes', type=int, default=DEFAULT_MAX_TOTAL_BYTES)
        sub.add_argument('--max-file-bytes', type=int, default=DEFAULT_MAX_FILE_BYTES)
        sub.add_argument('--max-files', type=int, default=DEFAULT_MAX_FILES)
        if command == 'materialize':
            sub.add_argument('--output', required=True, help='New laboratory-relative evidence directory; parent must exist')
    args = parser.parse_args()
    try:
        limits = {'max_total_bytes': args.max_total_bytes, 'max_file_bytes': args.max_file_bytes,
                  'max_files': args.max_files}
        if args.command == 'inspect':
            result = inspect_collection(ROOT, args.collection, args.collection_sha256, **limits)
        else:
            result = materialize_collection(ROOT, args.collection, args.collection_sha256, args.output, **limits)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    except (IntakeError, OSError) as exc:
        print(json.dumps({'error': str(exc), 'status': 'INTAKE_REJECTED'}), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
