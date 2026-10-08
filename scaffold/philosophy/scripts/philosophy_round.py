#!/usr/bin/env python3
"""Version-bound, locally executed philosophy rounds; no model/network launcher."""
import argparse
import hashlib
import datetime
import json
import os
from pathlib import Path
import re
import sys
import uuid
from research_archive import Archive, ArchiveError, canonical, _read, _safe_path

STAGES = ['question', 'sources', 'contribution', 'critique', 'decision']


def local(root, name):
    parts = Path(name).parts
    if Path(name).is_absolute() or not parts or '..' in parts:
        raise ArchiveError('artifact path must be lab-relative and cannot traverse')
    return _safe_path(root / name)


def records(archive, run):
    return [e for e in archive.events() if e['run_id'] == run]


def start_record(archive, run):
    starts = [e for e in records(archive, run) if e['kind'] == 'operation.started'
              and e['payload'].get('protocol') == 'philosophy-round.v1']
    if len(starts) != 1:
        raise ArchiveError('run requires exactly one philosophy round start')
    return starts[0]


def envelope(start, kind, session=None, role='AI', parents=None, payload=None):
    return {'kind': kind, 'actor': {'id': session or start['session_id'], 'role': role},
            'session_id': session or start['session_id'], 'run_id': start['run_id'],
            'operation_id': start['operation_id'], 'attempt_id': start['attempt_id'],
            'bindings': start['bindings'], 'parents': parents or [start['id']],
            'payload': payload or {}}


def start(root, archive, run, session, purpose, method, inputs,
          epoch_event_id=None, stage_id='INITIAL', selection_round_id='NONE'):
    if json.loads(_read(root / 'LAB_PROFILE.json'))['lab']['kind'] != 'PHILOSOPHY_PROGRAM':
        raise ArchiveError('requires a philosophy laboratory')
    method_data = _read(local(root, method))
    protocol = json.loads(method_data)
    if protocol.get('stages') != STAGES or not protocol.get('id'):
        raise ArchiveError('method must bind the five supported stages')
    bindings = {'method': [archive.put(method_data)],
                'instruction': [archive.put(_read(root / p)) for p in
                                ('AGENTS.md', 'AGENT_POLICY.md', 'USER_PREFERENCES.md', 'workflows/ROUND.md')],
                'config': [archive.put(_read(root / p)) for p in
                           ('LAB_PROFILE.json', '.codex/config.toml', '.lab/philosophy.json')],
                'input': [archive.put(_read(local(root, p))) for p in inputs]}
    for name in ('research_archive.py','philosophy_round.py','research_timeline.py','capture_codex.py','validate_lab.py'):
        installed = root / 'scripts' / name
        if installed.exists():
            bindings['config'].append(archive.put(_read(installed)))
    if records(archive, run):
        old = start_record(archive, run)
        if (old['session_id'] != session or old['bindings'] != bindings or old['payload']['purpose'] != purpose
                or old['payload'].get('stage_id') != stage_id
                or old['payload'].get('selection_round_id') != selection_round_id
                or (epoch_event_id is not None and old['payload'].get('epoch_event_id') != epoch_event_id)):
            raise ArchiveError('run ID conflict; use a new run for changed configuration')
        return old
    from research_timeline import Timeline
    timeline = Timeline(archive)
    if epoch_event_id is None:
        epoch_id = 'config-' + hashlib.sha256(canonical({k: bindings[k] for k in
                                    ('method', 'instruction', 'config')})).hexdigest()[:24]
        expected_id = 'epoch:' + epoch_id
        if any(e['id'] == expected_id for e in archive.events()):
            epoch = timeline.validate_epoch(expected_id, bindings)
        else:
            predecessors = [e for e in archive.events() if e['kind'] == 'lab.epoch']
            epoch = timeline.epoch(epoch_id, 'Configuration ' + epoch_id, bindings,
                'First observed round using these exact local method/instruction/configuration bytes.',
                'Changed configurations are separate epochs; no causal superiority claim.',
                context={'actor': {'id': session, 'role': 'AI'}, 'session_id': session,
                         'run_id': 'epoch-' + epoch_id, 'operation_id': 'epoch-' + epoch_id,
                         'attempt_id': 'epoch-' + epoch_id},
                predecessor_epoch=predecessors[-1]['id'] if predecessors else None)
        epoch_event_id = epoch['id']
    else:
        timeline.validate_epoch(epoch_event_id, bindings)
    event = {'kind': 'operation.started', 'actor': {'id': session, 'role': 'AI'},
             'session_id': session, 'run_id': run, 'operation_id': 'round-' + run,
             'attempt_id': 'attempt-' + uuid.uuid4().hex, 'bindings': bindings,
             'parents': [epoch_event_id],
             'payload': {'protocol': 'philosophy-round.v1', 'purpose': purpose,
                         'epoch_event_id': epoch_event_id, 'stage_id': stage_id,
                         'selection_round_id': selection_round_id,
                         'method_id': protocol['id'], 'stage_order': STAGES,
                         'coverage': 'NOT_YET_CAPTURED', 'model_observation': 'UNKNOWN',
                         'created_at_source': 'local wall clock; no independent time attestation'}}
    return archive.append(event, 'round-start:' + run)


def _open_round(archive, run, allow_paused=False):
    history = records(archive, run)
    first = start_record(archive, run)
    if any(e['kind'] in ('operation.completed', 'operation.failed', 'operation.interrupted')
           and e['attempt_id'] == first['attempt_id'] for e in history):
        raise ArchiveError('round attempt already has a terminal; start a linked new round')
    controls = [e for e in history if e['kind'] in ('round.pause', 'round.resume')]
    if controls and controls[-1]['kind'] == 'round.pause' and not allow_paused:
        raise ArchiveError('round paused; record explicit resume before dependent work')
    return first, history


def record(root, archive, run, stage, file, session, evidence, source_note=''):
    history = records(archive, run)
    first = start_record(archive, run)
    steps = [e for e in history if e['kind'] == 'round.stage']
    existing = next((e for e in steps if e['payload']['stage'] == stage), None)
    if not existing:
        _open_round(archive, run)
    if not existing and (len(steps) >= len(STAGES) or stage != STAGES[len(steps)]):
        raise ArchiveError('stage out of order; inspect history before continuing')
    if stage == 'critique' and session == first['session_id']:
        raise ArchiveError('critique needs a separate actual AI context/session')
    known = {e['id']: e for e in archive.events()}
    if not evidence or any(e not in known or known[e]['kind'] != 'capture.raw_record' for e in evidence):
        raise ArchiveError('stage needs original captured message/tool event evidence')
    if any(known[e]['session_id'] != session or known[e]['run_id'] != run for e in evidence):
        raise ArchiveError('capture evidence must match the actual stage session and run')
    roles = {known[e]['actor']['role'] for e in evidence}
    if not roles <= {'assistant', 'AI', 'tool'} or (stage != 'sources' and not roles & {'assistant', 'AI'}):
        raise ArchiveError('AI stage needs captured assistant authorship; user messages cannot certify AI origin')
    body = _read(local(root, file))
    if not body.strip():
        raise ArchiveError('empty artifact')
    if stage == 'sources' and not source_note.strip():
        raise ArchiveError('source stage needs an explicit retrieval/coverage note')
    artifact = archive.put(body)
    if existing:
        if (existing['session_id'] != session or existing['outputs'] != [artifact]
                or existing['payload']['source_note'] != source_note
                or not set(evidence).issubset(existing['parents'])):
            raise ArchiveError('stage replay conflict; append a new linked revision/round')
        return existing
    parents = [first['id']] + [e['id'] for e in steps[-1:]] + evidence
    event = envelope(first, 'round.stage', session, parents=list(dict.fromkeys(parents)),
                     payload={'stage': stage, 'artifact_name': Path(file).name,
                              'artifact_sha256': artifact, 'source_note': source_note,
                              'contribution_origin': 'AI', 'evidence_status': 'CAPTURE_LINKED',
                              'semantic_correspondence': 'Requires review; a link is not proof of authorship'})
    event['outputs'] = [artifact]
    return archive.append(event, 'round-stage:' + run + ':' + stage)


def checkpoint(root, archive, run, summary_file, coverage, incomplete=False):
    first = start_record(archive, run)
    history = records(archive, run)
    existing = next((e for e in history if e['kind'] == 'checkpoint'), None)
    if not existing:
        _open_round(archive, run, allow_paused=incomplete)
    steps = [e for e in history if e['kind'] == 'round.stage']
    if [e['payload']['stage'] for e in steps] != STAGES and not incomplete:
        raise ArchiveError('all five stages are required for a complete checkpoint')
    raw = _read(local(root, summary_file))
    summary = json.loads(raw)
    required = ('question', 'outcome', 'contribution', 'criticism', 'limitations',
                'next_step', 'method_change', 'comparability', 'coverage_boundary')
    if any(not isinstance(summary.get(k), str) or not summary[k].strip() for k in required):
        raise ArchiveError('checkpoint needs semantically complete core fields: ' + ', '.join(required))
    if summary['outcome'] not in ('CONTINUE', 'REVISE', 'SET_ASIDE', 'COMPLETE_TECHNICAL'):
        raise ArchiveError('unsupported workflow outcome (no philosophical truth certification)')
    known = {e['id']: e for e in archive.events()}
    if not coverage or any(e not in known or known[e]['kind'] != 'capture.coverage'
                           or known[e]['run_id'] != run for e in coverage):
        raise ArchiveError('checkpoint needs exact run-bound collector coverage records')
    if not incomplete and any(known[e]['payload'].get('status') != 'BOUNDED_COMPLETE' for e in coverage):
        raise ArchiveError('coverage incomplete; repair or explicitly checkpoint an incomplete segment')
    stage_sessions = {e['session_id'] for e in steps}
    if not stage_sessions.issubset({known[e]['session_id'] for e in coverage}):
        raise ArchiveError('coverage required for every stage session, including critic')
    stage_evidence = {p for step in steps for p in step['parents']
                      if known[p]['kind'] == 'capture.raw_record'}
    covered_evidence = {p for c in coverage for p in known[c]['parents']}
    if not stage_evidence.issubset(covered_evidence):
        raise ArchiveError('coverage must include the exact captured evidence for every stage')
    if summary['outcome'] == 'COMPLETE_TECHNICAL' and first['payload']['purpose'] != 'technical':
        raise ArchiveError('technical outcome only applies to technical round')
    artifact = archive.put(raw)
    stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    event = envelope(first, 'checkpoint', parents=[first['id']] + [e['id'] for e in steps] + coverage,
                     payload={'protocol': 'philosophy-checkpoint.v1', 'research_date': stamp[:10],
                              'summary': summary, 'capture_status': 'INCOMPLETE' if incomplete else 'BOUNDED_COMPLETE',
                              'purpose': first['payload']['purpose'], 'truth_status': 'NOT_CERTIFIED'})
    event['outputs'] = [artifact]
    if existing:
        if (existing['outputs'] != [artifact] or existing['parents'] != event['parents']
                or existing['payload']['capture_status'] != event['payload']['capture_status']):
            raise ArchiveError('checkpoint replay conflict; original checkpoint remains immutable')
        cp = existing
    else:
        cp = archive.append(event, 'checkpoint:' + run)
    terminal = envelope(first, 'operation.interrupted' if incomplete else 'operation.completed',
                        parents=[first['id'], cp['id']],
                        payload={'checkpoint': cp['id'], 'outcome': summary['outcome'],
                                 'scope': 'Recorded workflow completion, never philosophical truth'})
    archive.append(terminal, 'round-terminal:' + run)
    refresh(root, archive)
    return cp


def _derived(path, data):
    path = _safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.parent / ('.view-' + uuid.uuid4().hex)
    with temp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.replace(str(temp), str(path))


def refresh(root, archive):
    events = archive.events()
    cps = [e for e in events if e['kind'] == 'checkpoint']
    _derived(root / 'research/views/index.md', archive.markdown().encode())
    _derived(root / 'research/views/index.json', canonical(archive.view()))
    _derived(root / 'knowledge/checkpoint_index.json', canonical([
        {'id': e['id'], 'sha256': e['sha256'], 'run_id': e['run_id'],
         'research_date': e['payload']['research_date'], 'summary': e['payload']['summary']}
        for e in cps]))
    starts = [e for e in events if e['kind'] == 'operation.started'
              and e['payload'].get('protocol') == 'philosophy-round.v1']
    lines = ['# Текущее состояние', '', 'Производная навигация; канонические события находятся в research/archive.', '']
    if starts:
        latest = starts[-1]
        history = records(archive, latest['run_id'])
        steps = [e['payload']['stage'] for e in history if e['kind'] == 'round.stage']
        lines += ['- Раунд: `' + latest['run_id'] + '` (' + latest['payload']['purpose'] + ').',
                  '- Метод: `' + latest['payload']['method_id'] + '`, точные байты связаны в событии старта.',
                  '- Зафиксированные стадии: ' + ', '.join(steps)]
        controls = [e['kind'] for e in history if e['kind'] in
                    ('round.pause','round.resume','operation.completed','operation.interrupted')]
        lines += ['- Состояние: ' + (controls[-1] if controls else 'active')]
        current_cps = [e for e in cps if e['run_id'] == latest['run_id']]
    else:
        lines += ['- Раунд: ещё не начат.', '- Метод: methods/simple-v1.json.']
        current_cps = []
    if current_cps:
        last = current_cps[-1]
        lines += ['- Последний checkpoint: `' + last['id'] + '`.',
                  '- Результат: ' + last['payload']['summary']['outcome'],
                  '- Следующий шаг: ' + last['payload']['summary']['next_step'],
                  '- Ограничения: ' + last['payload']['summary']['limitations']]
    else:
        lines += ['- Следующий шаг: проверить захват и продолжить первую отсутствующую стадию.',
                  '- Ограничения: готовность захвата текущей сессии ещё не установлена.']
    lines += ['', 'Материалы: LAB_PROFILE.json, выбранные первоисточники и точные объекты архива.',
              'Исторические каталоги не являются автоматически действующими инструкциями.', '']
    _derived(root / 'knowledge/resume.md', '\n'.join(lines).encode())
    from research_timeline import refresh as timeline_refresh
    timeline_refresh(root, archive)
    return {'events': len(events), 'checkpoints': len(cps)}


def validate_round_history(archive):
    """Validate the complete workflow projection even after low-level appends."""
    errors = []
    events = archive.events(); known = {e['id']: e for e in events}
    starts = [e for e in events if e['kind'] == 'operation.started'
              and e['payload'].get('protocol') == 'philosophy-round.v1']
    from research_timeline import Timeline
    for first in starts:
        run = first['run_id']; history = [e for e in events if e['run_id'] == run]
        try:
            epoch = Timeline(archive).validate_epoch(first['payload']['epoch_event_id'], first['bindings'])
            if epoch['id'] not in first['parents']:
                errors.append(run + ': epoch missing causal parent')
        except (KeyError, ValueError) as exc:
            errors.append(run + ': invalid epoch binding: ' + str(exc))
        steps = [e for e in history if e['kind'] == 'round.stage']
        if [e['payload'].get('stage') for e in steps] != STAGES[:len(steps)]:
            errors.append(run + ': invalid stage order')
        evidence = set()
        for step in steps:
            refs = [known[p] for p in step['parents'] if known[p]['kind'] == 'capture.raw_record']
            evidence.update(e['id'] for e in refs)
            roles = {e['actor']['role'] for e in refs}
            if (not refs or not roles <= {'assistant','AI','tool'}
                    or (step['payload'].get('stage') != 'sources' and not roles & {'assistant','AI'})
                    or any(e['run_id'] != run or e['session_id'] != step['session_id'] for e in refs)
                    or step['bindings'] != first['bindings']
                    or step['payload'].get('artifact_sha256') not in step['outputs']):
                errors.append(run + ': invalid captured stage provenance')
            if step['payload'].get('stage') == 'critique' and step['session_id'] == first['session_id']:
                errors.append(run + ': critic session is not separate')
        cps = [e for e in history if e['kind'] == 'checkpoint']
        terminals = [e for e in history if e['kind'] in ('operation.completed','operation.interrupted')
                     and e['attempt_id'] == first['attempt_id']]
        if len(cps) > 1:
            errors.append(run + ': multiple checkpoints')
        for terminal in terminals:
            matching = [cp for cp in cps if cp['id'] == terminal['payload'].get('checkpoint')
                        and cp['id'] in terminal['parents']]
            if len(matching) != 1:
                errors.append(run + ': terminal requires exact checkpoint'); continue
            cp = matching[0]
            coverage = [known[p] for p in cp['parents'] if known[p]['kind'] == 'capture.coverage']
            if not evidence <= {p for c in coverage for p in c['parents']}:
                errors.append(run + ': checkpoint coverage omits stage evidence')
            if cp['bindings'] != first['bindings'] or not {s['id'] for s in steps} <= set(cp['parents']):
                errors.append(run + ': checkpoint version or stage binding mismatch')
            if terminal['kind'] == 'operation.completed' and (
                    [s['payload'].get('stage') for s in steps] != STAGES
                    or not coverage or any(c['payload'].get('status') != 'BOUNDED_COMPLETE' for c in coverage)
                    or cp['payload'].get('capture_status') != 'BOUNDED_COMPLETE'):
                errors.append(run + ': completed workflow has missing stages or incomplete capture')
    return errors


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    sub = p.add_subparsers(dest='cmd', required=True)
    q = sub.add_parser('start'); q.add_argument('--run', required=True); q.add_argument('--session', required=True)
    q.add_argument('--purpose', choices=['technical', 'research'], required=True)
    q.add_argument('--method', default='methods/simple-v1.json'); q.add_argument('--input', action='append', default=[])
    q.add_argument('--epoch-event'); q.add_argument('--stage-id', default='INITIAL')
    q.add_argument('--selection-round-id', default='NONE')
    q = sub.add_parser('record'); q.add_argument('--run', required=True); q.add_argument('--stage', choices=STAGES, required=True)
    q.add_argument('--file', required=True); q.add_argument('--session', required=True)
    q.add_argument('--evidence', action='append', required=True); q.add_argument('--source-note', default='')
    for cmd in ('pause', 'resume'):
        q = sub.add_parser(cmd); q.add_argument('--run', required=True); q.add_argument('--reason', required=True)
    q = sub.add_parser('checkpoint'); q.add_argument('--run', required=True); q.add_argument('--summary', required=True)
    q.add_argument('--coverage', action='append', required=True); q.add_argument('--incomplete', action='store_true')
    sub.add_parser('refresh')
    a = p.parse_args(); root = _safe_path(a.root); archive = Archive(root / 'research/archive').init()
    try:
        if a.cmd == 'start': result = start(root, archive, a.run, a.session, a.purpose, a.method, a.input,
                                            a.epoch_event, a.stage_id, a.selection_round_id)
        elif a.cmd == 'record': result = record(root, archive, a.run, a.stage, a.file, a.session, a.evidence, a.source_note)
        elif a.cmd == 'checkpoint': result = checkpoint(root, archive, a.run, a.summary, a.coverage, a.incomplete)
        elif a.cmd == 'refresh': result = refresh(root, archive)
        else:
            first, history = _open_round(archive, a.run, allow_paused=True)
            controls = [e for e in history if e['kind'] in ('round.pause','round.resume')]
            if controls and controls[-1]['kind'] == 'round.' + a.cmd and controls[-1]['payload']['reason'] == a.reason:
                result = controls[-1]
            else:
                parent = history[-1]['id']
                key = hashlib.sha256(canonical([a.run,a.cmd,a.reason,parent])).hexdigest()
                result = archive.append(envelope(first, 'round.' + a.cmd,
                    parents=list(dict.fromkeys([first['id'],parent])), payload={'reason': a.reason}), key)
            refresh(root, archive)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ArchiveError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'BLOCKED', 'error': str(exc)}, ensure_ascii=False)); sys.exit(1)


if __name__ == '__main__':
    main()
