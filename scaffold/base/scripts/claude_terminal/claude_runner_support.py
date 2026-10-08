"""Bounded source receipts, native observations and mechanical acceptance.

No hidden reasoning or native envelopes are exported. Selected explicit markers
are screened only in .txt/.md/.json/.html payloads. Exact-byte privacy review is
still required; this is not anonymization or a universal personal-data detector.
"""
import hashlib
import json
from pathlib import Path
import re
import stat
import claude_source_capture as sources


def _capture_directory(path, create=False):
    """Reject static symlinks/special ancestors in the reserved capture paths."""
    for component in [*reversed(path.parents), path]:
        if component.is_symlink():
            raise ValueError('Symlink in source capture path')
        if component.exists() and not stat.S_ISDIR(component.stat().st_mode):
            raise ValueError('Special ancestor in source capture path')
    if create:
        path.mkdir(parents=True, exist_ok=True)


def _capture_authority(r, folder, path, expected_url=None):
    """Check output against the runner-owned authority, never against itself."""
    authority = r.load(path)
    if (not isinstance(authority, dict)
            or set(authority) != {'schema_version', 'url', 'receipt_sha256', 'files'}
            or type(authority['schema_version']) is not int or authority['schema_version'] != 1
            or not isinstance(authority['url'], str)
            or (expected_url is not None and authority['url'] != expected_url)
            or not isinstance(authority['files'], dict)):
        raise ValueError('Invalid source capture authority')
    key = r.digest(authority['url'].encode())
    if path.name != key + '.json':
        raise ValueError('Source capture authority URL binding differs')
    receipt_bytes = r.regular(folder / path.name)
    if r.digest(receipt_bytes) != authority['receipt_sha256']:
        raise ValueError('Source capture receipt changed')
    receipt = json.loads(receipt_bytes)
    if not isinstance(receipt, dict) or receipt.get('url') != authority['url']:
        raise ValueError('Source capture receipt URL differs')
    bindings = {}
    for kind in ('raw', 'text'):
        name = receipt.get(kind)
        if name:
            allowed = {key + '.txt'} if kind == 'text' else {key + suffix for suffix in ('.pdf', '.html', '.bin')}
            digest = receipt.get(kind + '_sha256')
            if name not in allowed or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
                raise ValueError('Invalid source capture artifact binding')
            bindings[name] = digest
    if bindings != authority['files']:
        raise ValueError('Source capture artifact inventory differs')
    for name, digest in bindings.items():
        if r.digest(r.regular(folder / name)) != digest:
            raise ValueError('Source capture artifact changed')
    return authority


def source_capture(r, root, tid, url):
    folder = root / 'work' / tid / 'output' / 'sources'
    _capture_directory(folder, create=True)
    # This lives outside the assigned model work directory. The runner owns it;
    # records/ is already included in resource accounting and collected evidence.
    authority_folder = root / 'records' / 'source-captures' / r.identifier(tid)
    _capture_directory(authority_folder, create=True)
    key = r.digest(url.encode())
    receipt = folder / (key + '.json')
    authority_path = authority_folder / receipt.name
    if authority_path.exists() or authority_path.is_symlink():
        _capture_authority(r, folder, authority_path, expected_url=url)
        return
    # A model-writable receipt alone is never a retrieval cache hit. Fetch and
    # replace the reserved output mirror with the actual runner observation.
    entry = {'url': url, 'status': 'unavailable', 'raw': None, 'text': None}
    try:
        raw, kind, charset, meta = sources.fetch(url)
        # Preserve bytes even if text extraction fails.
        ext = 'pdf' if raw.startswith(b'%PDF-') else 'html' if 'html' in kind else 'bin'
        raw_name = key + '.' + ext
        r.atomic(folder / raw_name, raw)
        entry.update(status='raw_saved', raw=raw_name, raw_sha256=r.digest(raw), retrieval=meta)
        try:
            text, _, method = sources.extract(raw, kind, charset)
            text_name = key + '.txt'
            r.atomic(folder / text_name, text)
            entry.update(status='raw_and_text_saved', text=text_name, text_sha256=r.digest(text), extraction=method)
        except Exception as exc:
            entry['extraction_error'] = type(exc).__name__
    except Exception as exc:
        entry['retrieval_error'] = type(exc).__name__
    receipt_bytes = r.canonical(entry)
    r.atomic(receipt, receipt_bytes)
    authority = {'schema_version': 1, 'url': url, 'receipt_sha256': r.digest(receipt_bytes),
                 'files': {entry[kind]: entry[kind + '_sha256']
                           for kind in ('raw', 'text') if entry.get(kind)}}
    # Commit the authority last. An interrupted copy without it is untrusted.
    r.atomic(authority_path, r.canonical(authority))
    r.event(root, 'source.capture', task=tid, receipt=entry)


def native_observations(r, root, task, state):
    """Exact job session only; safe projection, never store raw JSONL."""
    cwd = root / 'work' / task['id']
    sid = state['session_id']
    source = Path.home() / '.claude/projects' / re.sub('[^a-zA-Z0-9]', '-', str(cwd)) / (sid + '.jsonl')
    report = {'session_id': sid, 'observations': [], 'tool_calls': [],
              'coverage': 'Selected model/effort/version/time, tool argument projections and public PDF artifacts. No thinking, internal instructions or full tool results.',
              'orchestration_requested': 'fixed_sessions', 'child_agents_observed': []}
    if not source.exists():
        report['status'] = 'native_unavailable'
        return report
    for n, line in enumerate(r.regular(source).splitlines(), 1):
        try:
            record = json.loads(line)
        except ValueError:
            report['partial_native_tail'] = True
            continue
        if record.get('type') != 'assistant':
            continue
        if record.get('sessionId') != sid or record.get('cwd') != str(cwd):
            raise ValueError('Native session identity mismatch')
        msg = record.get('message', {})
        report['observations'].append({'line': n, 'model': msg.get('model'), 'effort': record.get('effort'),
                                       'timestamp': record.get('timestamp'), 'version': record.get('version')})
        for block in msg.get('content', []):
            if block.get('type') != 'tool_use':
                continue
            name = block.get('name'); args = block.get('input', {})
            # Whitelisted argument metadata only. Content bodies remain artifacts.
            selected = {k: v for k, v in args.items() if k in ('file_path', 'url', 'offset', 'limit', 'pages') and isinstance(v, (str, int))}
            report['tool_calls'].append({'line': n, 'id': block.get('id'), 'name': name, 'arguments': selected})
            if name in ('Agent', 'Task', 'Workflow'):
                report['child_agents_observed'].append({'line': n, 'name': name, 'id': block.get('id')})
            if name == 'Read' and isinstance(args.get('file_path'), str):
                p = Path(args['file_path'])
                if p.suffix.lower() == '.pdf' and p.is_relative_to(source.parent / sid / 'tool-results') and p.exists():
                    raw = r.regular(p)
                    if not raw.startswith(b'%PDF-'):
                        raise ValueError('Native PDF signature mismatch')
                    dest = cwd / 'output' / 'sources' / ('native-' + r.digest(raw) + '.pdf')
                    r.atomic(dest, raw)
                    r.event(root, 'source.native_pdf', task=task['id'], sha256=r.digest(raw), bytes=len(raw), source_line=n)
    report['status'] = 'observed' if report['observations'] else 'native_no_assistant'
    return report


def relay_screen(data, name):
    """Conservative explicit indicators, NOT semantic anonymization certification."""
    if Path(name).suffix.lower() not in ('.txt', '.md', '.json', '.html'):
        return []
    text = data.decode('utf-8', errors='replace')
    patterns = (r'(?<![A-Za-z0-9.])/(?:Users|home)/(?!Shared(?:/|\b))[^/\s]+',
                r'file://', r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
                r'\bsk-ant-[A-Za-z0-9_-]{16,}', r'\bBearer\s+[A-Za-z0-9._-]{32,}',
                r'<(?:user_instructions|environment_context|system-reminder)>',
                r'(?m)^# User-wide operating preferences\s*$',
                r'(?m)^# Claude export boundary')
    return ['restricted_export_marker'] if any(re.search(p, text) for p in patterns) else []


def execute_with_repairs(r, execute, root, task, state, work, exe):
    """Bounded same-session correction, never automatic quota/provider retries.

    Counters are persisted before dispatch and survive process restarts.
    Only explicit output-contract errors are eligible; mixed failures stop.
    """
    eligible = {'missing_or_empty', 'invalid_json', 'source_status_missing_or_invalid'}
    while True:
        if (root / 'STOP.json').exists():
            return state
        feedback = ''
        resumed_correction = (state.get('reason') == 'quota'
                              and state.get('output_repair_attempts', 0) > 0
                              and bool(state.get('validation_errors')))
        if state.get('reason') == 'validation_failed' or resumed_correction:
            errors = state.get('validation_errors', [])
            if not errors or any(e.split(':', 1)[0] not in eligible for e in errors):
                return state
            count = state.get('output_repair_attempts', 0)
            if count >= 3 and not resumed_correction:
                r.event(root, 'output.repair_exhausted', task=task['id'], errors=errors, attempts=count)
                return state
            state['output_repair_attempts'] = count if resumed_correction else count + 1
            r.atomic(root / 'state.json', r.canonical(r.load_state_current(root, task['id'], state)))
            r.snapshot(root, task['id'])
            feedback = ('\nOUTPUT CORRECTION REQUIRED. The previous response finished, but local '
                        'acceptance failed: ' + json.dumps(errors) + '.\n'
                        'Continue this same task and correct these issues, not a new research round. '
                        'Preserve the mathematical scope, arguments, references, and explicit gaps. '
                        'Do not fabricate sources or access claims to satisfy validation. '
                        'Prior output bytes have been archived by the caller. Save a numbered backup '
                        'before updating the required output filenames with the corrected versions.\n')
            r.event(root, 'output.repair_requested', task=task['id'],
                    session_id=state['session_id'], number=state['output_repair_attempts'],
                    resumed_after_quota=resumed_correction, errors=errors, feedback=feedback)
        previous_policy = r.POLICY
        try:
            r.POLICY = previous_policy + feedback
            state = execute(root, task, state, work, exe)
        finally:
            r.POLICY = previous_policy
        r.atomic(root / 'state.json', r.canonical(r.load_state_current(root, task['id'], state)))
        if state.get('status') != 'paused' or state.get('reason') != 'validation_failed':
            return state


def validate(r, root, task, state, native):
    work = root / 'work' / task['id']; out = work / 'output'
    errors = []; checks = {}
    authority_folder = root / 'records' / 'source-captures' / r.identifier(task['id'])
    authorities = set()
    try:
        _capture_directory(authority_folder)
        _capture_directory(out/'sources')
        for authority in authority_folder.glob('*.json'):
            authorities.add(authority.name)
            try:
                _capture_authority(r, out/'sources', authority)
            except (ValueError, KeyError, OSError, TypeError):
                errors.append('source_authority_mismatch:' + authority.name)
    except (ValueError, OSError):
        errors.append('invalid_source_authority_directory')
    checks['source_capture_authorities'] = len(authorities)
    for p in (out/'sources').glob('*.json'):
        if p.name not in authorities:
            errors.append('untrusted_source_receipt:' + p.name)
        try:
            receipt = r.load(p)
            if not isinstance(receipt, dict):
                raise ValueError()
            for key in ('raw', 'text'):
                if receipt.get(key):
                    artifact = out/'sources'/r.relative(receipt[key])
                    if r.digest(r.regular(artifact)) != receipt[key+'_sha256']:
                        errors.append('source_changed:' + p.name)
        except (ValueError, KeyError, OSError, TypeError):
            errors.append('invalid_source_receipt:' + p.name)
    for name in task['required_outputs']:
        p = out / name
        if not p.exists() or not r.regular(p).strip():
            errors.append('missing_or_empty:' + name)
            continue
        data = r.regular(p)
        if name.endswith('.json'):
            try:
                json.loads(data)
            except ValueError:
                errors.append('invalid_json:' + name)
        errors.extend(relay_screen(data, name))
    if task.get('research_checks'):
        obs = [o for o in native.get('observations', []) if o.get('model') != '<synthetic>']
        if not obs or any(o.get('model') != task['model'] or o.get('effort') != task['effort'] for o in obs):
            errors.append('native_configuration_unverified_or_changed')
        if native.get('child_agents_observed'):
            errors.append('unexpected_child_agent')
        p = out / 'source-status.json'
        try:
            status = r.load(p)
            if not isinstance(status, dict) or not isinstance(status.get('sources'), list):
                raise ValueError()
            if not status['sources']:
                reason = status.get('no_external_sources_reason')
                if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
                    raise ValueError()
            for s in status['sources']:
                if not isinstance(s, dict) or not isinstance(s.get('url'), str) or s.get('coverage') not in ('full', 'excerpt', 'summary', 'unavailable') or not isinstance(s.get('note'), str):
                    raise ValueError()
                if s['coverage'] in ('full', 'excerpt'):
                    artifact = work / r.relative(s['artifact'])
                    if not (artifact.is_relative_to(work/'input') or artifact.is_relative_to(out)) or not r.regular(artifact):
                        raise ValueError()
        except (ValueError, KeyError, OSError, TypeError):
            errors.append('source_status_missing_or_invalid')
    return {'passed': not errors, 'errors': sorted(set(errors)), 'checks': checks,
            'boundary': 'Mechanical acceptance only. No mathematical correctness, novelty, independent verification or ledger promotion.'}
