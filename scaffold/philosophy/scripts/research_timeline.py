#!/usr/bin/env python3
"""Typed provenance and derived weekly chronology over immutable archive events."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import uuid

from research_archive import Archive, ArchiveError, BINDINGS, canonical, _read, _safe_path, _require_id

VERSION = 1
TASK_TYPES = ('infrastructure', 'planning', 'idea_generation', 'essay_generation',
              'source_reading', 'critique', 'selection', 'methodology', 'other')
KINDS = {'lab.epoch', 'candidate.created', 'candidate.decision',
         'candidate.independence_assessed', 'activity.observed'}
VERSION_BINDINGS = ('method', 'instruction', 'config')


def unknown(reason):
    return {'status': 'unknown', 'reason': reason}


def instant(value):
    if not isinstance(value, str):
        raise ArchiveError('timestamp must be a string')
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp
    except ValueError as exc:
        raise ArchiveError('timestamp requires an ISO 8601 timezone') from exc


def observation(value, timestamp=False):
    if not isinstance(value, dict) or value.get('status') not in ('known', 'unknown'):
        raise ArchiveError('observation requires explicit known/unknown status')
    if value['status'] == 'unknown':
        if set(value) != {'status', 'reason'} or not isinstance(value['reason'], str) or not value['reason'].strip():
            raise ArchiveError('unknown observation requires reason only')
    else:
        if set(value) != {'status', 'value', 'source'} or any(
                not isinstance(value[k], str) or not value[k].strip() for k in ('value', 'source')):
            raise ArchiveError('known observation requires value and source')
        if timestamp:
            instant(value['value'])
    return value


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ArchiveError(name + ' must be nonempty text')


def _binding_match(left, right):
    return all(left[k] == right[k] for k in VERSION_BINDINGS)


def _ref(event, seen, ref, kind):
    if ref not in seen or seen[ref]['kind'] != kind or seen[ref]['payload'].get('timeline_version') != VERSION:
        raise ArchiveError('missing typed ' + kind + ' reference')
    if ref not in event['parents']:
        raise ArchiveError(kind + ' reference must be a causal parent')
    return seen[ref]


def _validate_one(event, seen):
    p = event['payload']
    if p.get('timeline_version') != VERSION:
        if 'timeline_version' in p:
            raise ArchiveError('unsupported timeline version')
        return
    kind = event['kind']
    if kind not in KINDS:
        raise ArchiveError('unsupported typed timeline event kind')
    if kind == 'lab.epoch':
        _require_id(p['epoch_id'], 'epoch_id')
        if event['id'] != 'epoch:' + p['epoch_id']:
            raise ArchiveError('epoch event ID must bind stable epoch_id')
        for key in ('label', 'rationale', 'comparability'):
            _text(p[key], key)
        if p['predecessor_epoch'] is not None:
            _ref(event, seen, p['predecessor_epoch'], 'lab.epoch')
        if set(p['availability']) != set(VERSION_BINDINGS):
            raise ArchiveError('epoch availability must describe all version bindings')
        for key in VERSION_BINDINGS:
            state = p['availability'][key]
            observation(state)
            if bool(event['bindings'][key]) != (state['status'] == 'known'):
                raise ArchiveError('epoch availability contradicts exact bindings')
        return
    if kind in ('candidate.created', 'activity.observed'):
        epoch = _ref(event, seen, p['epoch_event_id'], 'lab.epoch')
        if not _binding_match(event['bindings'], epoch['bindings']):
            raise ArchiveError('epoch/version bindings mismatch')
        for key in ('stage_id', 'selection_round_id'):
            _require_id(p[key], key)
        start_id = p.get('run_start_event_id')
        if start_id is not None:
            start = seen.get(start_id)
            if not start or start['kind'] != 'operation.started' or start_id not in event['parents']:
                raise ArchiveError('run_start_event_id must reference a causal operation.started')
            if epoch['id'] not in start['parents']:
                raise ArchiveError('run start must causally reference its epoch')
            if any(event[k] != start[k] for k in ('run_id', 'operation_id', 'attempt_id')):
                raise ArchiveError('candidate/activity run provenance mismatch')
            if not _binding_match(event['bindings'], start['bindings']):
                raise ArchiveError('run/version bindings mismatch')
            for key in ('epoch_event_id', 'stage_id', 'selection_round_id'):
                if start['payload'].get(key) != p[key]:
                    raise ArchiveError('run/' + key + ' mismatch')
    if kind == 'candidate.created':
        expected = {'timeline_version', 'candidate_id', 'artifact_type', 'artifact_sha256', 'epoch_event_id',
                    'run_start_event_id', 'stage_id', 'selection_round_id', 'actor_origin', 'genesis',
                    'parent_candidate_events', 'birth', 'independence'}
        if set(p) != expected:
            raise ArchiveError('candidate birth fields differ from schema')
        _require_id(p['candidate_id'], 'candidate_id')
        if event['id'] != 'candidate:' + p['candidate_id']:
            raise ArchiveError('candidate event ID must bind stable candidate_id')
        if p['artifact_type'] not in ('essay', 'thesis', 'idea', 'other'):
            raise ArchiveError('unsupported candidate artifact type')
        if p['actor_origin'] not in ('AI', 'HUMAN') or event['actor']['role'] != p['actor_origin']:
            raise ArchiveError('candidate actor origin must match actor role')
        if p['genesis'] not in ('ORIGINAL', 'DERIVED', 'MERGED', 'IMPORTED'):
            raise ArchiveError('unsupported genesis')
        if event['outputs'] != [p['artifact_sha256']]:
            raise ArchiveError('candidate original artifact must be exact output object')
        if p['run_start_event_id'] is None:
            raise ArchiveError('candidate needs a run start binding')
        observation(p['birth'], timestamp=True)
        observation(event.get('model', unknown('model not exposed by source')))
        if p['birth']['status'] == 'known' and event.get('timestamp') != p['birth']['value']:
            raise ArchiveError('candidate event time must equal observed birth')
        if p['independence'] != 'UNASSESSED':
            raise ArchiveError('birth does not establish independence; use separate sourced assessment')
        parents = p['parent_candidate_events']
        if not isinstance(parents, list) or len(parents) != len(set(parents)):
            raise ArchiveError('candidate parents must be a unique list')
        if p['genesis'] == 'ORIGINAL' and parents:
            raise ArchiveError('original candidate cannot declare derived candidate parents')
        if p['genesis'] == 'DERIVED' and len(parents) != 1:
            raise ArchiveError('derived candidate requires exactly one candidate parent')
        if p['genesis'] == 'MERGED' and len(parents) < 2:
            raise ArchiveError('merged candidate requires at least two candidate parents')
        for parent in parents:
            _ref(event, seen, parent, 'candidate.created')
    elif kind in ('candidate.decision', 'candidate.independence_assessed'):
        created = _ref(event, seen, p['candidate_event_id'], 'candidate.created')
        if p['candidate_id'] != created['payload']['candidate_id']:
            raise ArchiveError('candidate decision/assessment ID mismatch')
        _text(p['rationale'], 'rationale')
        if kind == 'candidate.decision':
            if p['decision'] not in ('REJECT', 'REOPEN', 'SHORTLIST', 'SELECT', 'SET_ASIDE'):
                raise ArchiveError('unsupported candidate decision')
            _require_id(p['selection_round_id'], 'selection_round_id')
        else:
            if p['assessment'] not in ('SUPPORTED', 'NOT_SUPPORTED', 'INCONCLUSIVE'):
                raise ArchiveError('unsupported independence assessment')
            if not p['evidence_events'] or not p['evidence_objects']:
                raise ArchiveError('independence assessment needs sourced events and exact evidence objects')
            if any(e not in seen or e not in event['parents'] for e in p['evidence_events']):
                raise ArchiveError('independence evidence must be causal parents')
            if not set(p['evidence_objects']).issubset(event['inputs']):
                raise ArchiveError('independence evidence objects must be exact inputs')
            source_objects = {obj for ref in p['evidence_events'] for obj in
                              seen[ref]['inputs'] + seen[ref]['outputs']}
            if not set(p['evidence_objects']).issubset(source_objects):
                raise ArchiveError('independence evidence objects must occur in cited evidence events')
    elif kind == 'activity.observed':
        if p['task_type'] not in TASK_TYPES:
            raise ArchiveError('unsupported task type')
        if p['status'] not in ('complete', 'incomplete', 'interrupted'):
            raise ArchiveError('unsupported activity status')
        _require_id(p['activity_id'], 'activity_id')
        earlier = [e for e in seen.values() if e['kind'] == 'activity.observed'
                   and e['payload'].get('timeline_version') == VERSION
                   and e['payload'].get('activity_id') == p['activity_id']]
        if earlier:
            previous = _ref(event, seen, p['previous_observation'], 'activity.observed')
            if previous['id'] != earlier[-1]['id']:
                raise ArchiveError('activity update must reference its latest observation')
            for field in ('activity_id', 'task_type', 'epoch_event_id', 'stage_id',
                          'selection_round_id', 'run_start_event_id'):
                if previous['payload'][field] != p[field]:
                    raise ArchiveError('activity identity/context changed; use a distinct activity ID')
            if any(previous[field] != event[field] for field in ('run_id', 'operation_id', 'attempt_id')):
                raise ArchiveError('activity run identity changed')
        elif p['previous_observation'] is not None:
            raise ArchiveError('first activity observation cannot supersede another activity')
        for key in ('start', 'end'):
            observation(p[key], timestamp=True)
        observation(p['model'])
        if event['model'] != p['model']:
            raise ArchiveError('activity model observation mismatch')
        if p['internal_reasoning_time'] != unknown('not observable from wall-clock intervals'):
            raise ArchiveError('internal reasoning time cannot be inferred from interval')
        for ref in p['evidence_events']:
            if ref not in seen or ref not in event['parents']:
                raise ArchiveError('activity evidence must be causal parents')
        if all(p[k]['status'] == 'known' for k in ('start', 'end')):
            if instant(p['end']['value']) < instant(p['start']['value']):
                raise ArchiveError('activity ends before it starts')


class Timeline:
    def __init__(self, archive):
        self.archive = archive

    def _records(self):
        records, seen = self.archive.events(), {}
        for event in records:
            try:
                _validate_one(event, seen)
            except (KeyError, TypeError, ValueError) as exc:
                raise ArchiveError('invalid timeline event ' + event['id'] + ': ' + str(exc)) from exc
            seen[event['id']] = event
        return records

    def validate(self):
        try:
            records = self._records()
            return {'ok': True, 'typed_events': sum(e['payload'].get('timeline_version') == VERSION for e in records)}
        except (ArchiveError, OSError) as exc:
            return {'ok': False, 'error': str(exc)}

    def validate_epoch(self, event_id, bindings=None):
        event = next((e for e in self._records() if e['id'] == event_id), None)
        if not event or event['kind'] != 'lab.epoch' or event['payload'].get('timeline_version') != VERSION:
            raise ArchiveError('unknown typed epoch')
        if bindings is not None and not _binding_match(bindings, event['bindings']):
            raise ArchiveError('epoch/version bindings mismatch')
        return event

    def _emit(self, kind, event_id, payload, bindings, parents, context, outputs=None,
              inputs=None, timestamp=None, model=None, delivery_key=None):
        if not isinstance(context, dict) or set(context) != {'actor', 'session_id', 'run_id', 'operation_id', 'attempt_id'}:
            raise ArchiveError('context requires actor/session_id/run_id/operation_id/attempt_id')
        event = dict(context, kind=kind, id=event_id, payload=dict(payload, timeline_version=VERSION),
                     bindings=bindings, parents=list(dict.fromkeys(parents)), outputs=outputs or [], inputs=inputs or [])
        if timestamp is not None:
            event['timestamp'] = timestamp
        if model is not None:
            event['model'] = model
        seen = {}
        for previous in self._records():
            if previous['id'] == event_id:
                break  # Replay is validated in its original causal context.
            seen[previous['id']] = previous
        _validate_one(event, seen)
        return self.archive.append(event, delivery_key or event_id)

    def epoch(self, epoch_id, label, bindings, rationale, comparability, context,
              predecessor_epoch=None, availability=None, timestamp=None, delivery_key=None):
        availability = availability or {
            k: {'status': 'known', 'value': 'exact archived objects', 'source': 'operator-supplied snapshot'}
            if bindings[k] else unknown('no available bytes supplied') for k in VERSION_BINDINGS}
        return self._emit('lab.epoch', 'epoch:' + epoch_id,
            {'epoch_id': epoch_id, 'label': label, 'predecessor_epoch': predecessor_epoch,
             'rationale': rationale, 'comparability': comparability, 'availability': availability},
            bindings, [predecessor_epoch] if predecessor_epoch else [], context,
            timestamp=timestamp, delivery_key=delivery_key)

    def candidate(self, candidate_id, artifact_type, artifact_sha256, epoch_event_id,
                  run_start_event_id, stage_id, selection_round_id, actor_origin,
                  genesis, context, parent_candidate_events=None, birth=None, model=None, delivery_key=None):
        epoch = self.validate_epoch(epoch_event_id)
        birth = birth if birth is not None else unknown('original birth time not observed')
        parents = list(parent_candidate_events or [])
        return self._emit('candidate.created', 'candidate:' + candidate_id,
            {'candidate_id': candidate_id, 'artifact_type': artifact_type, 'artifact_sha256': artifact_sha256,
             'epoch_event_id': epoch_event_id, 'run_start_event_id': run_start_event_id,
             'stage_id': stage_id, 'selection_round_id': selection_round_id, 'actor_origin': actor_origin,
             'genesis': genesis, 'parent_candidate_events': parents, 'birth': birth, 'independence': 'UNASSESSED'},
            epoch['bindings'], [epoch_event_id, run_start_event_id] + parents, context,
            outputs=[artifact_sha256], timestamp=birth.get('value'), model=model,
            delivery_key=delivery_key)

    def decision(self, decision_id, candidate_event_id, decision, rationale,
                 selection_round_id, context, timestamp=None, delivery_key=None):
        created = next((e for e in self._records() if e['id'] == candidate_event_id), None)
        if not created or created['kind'] != 'candidate.created':
            raise ArchiveError('unknown candidate')
        return self._emit('candidate.decision', 'decision:' + decision_id,
            {'candidate_event_id': candidate_event_id, 'candidate_id': created['payload']['candidate_id'],
             'decision': decision, 'rationale': rationale, 'selection_round_id': selection_round_id},
            created['bindings'], [candidate_event_id], context, timestamp=timestamp, delivery_key=delivery_key)

    def assess(self, assessment_id, candidate_event_id, assessment, rationale,
               evidence_events, evidence_objects, context, timestamp=None, delivery_key=None):
        created = next((e for e in self._records() if e['id'] == candidate_event_id), None)
        if not created or created['kind'] != 'candidate.created':
            raise ArchiveError('unknown candidate')
        return self._emit('candidate.independence_assessed', 'assessment:' + assessment_id,
            {'candidate_event_id': candidate_event_id, 'candidate_id': created['payload']['candidate_id'],
             'assessment': assessment, 'rationale': rationale, 'evidence_events': evidence_events,
             'evidence_objects': evidence_objects}, created['bindings'], [candidate_event_id] + evidence_events,
            context, inputs=evidence_objects, timestamp=timestamp, delivery_key=delivery_key)

    def activity(self, activity_id, observation_id, task_type, epoch_event_id,
                 stage_id, selection_round_id, context, run_start_event_id=None,
                 start=None, end=None, model=None, status='incomplete', evidence_events=None,
                 timestamp=None, delivery_key=None):
        epoch = self.validate_epoch(epoch_event_id)
        evidence_events = evidence_events or []
        prior = None
        for event in self._records():
            if event['id'] == 'activity:' + observation_id:
                break
            if event['kind'] == 'activity.observed' and event['payload'].get('activity_id') == activity_id:
                prior = event['id']
        return self._emit('activity.observed', 'activity:' + observation_id,
            {'activity_id': activity_id, 'task_type': task_type, 'epoch_event_id': epoch_event_id,
             'stage_id': stage_id, 'selection_round_id': selection_round_id,
             'run_start_event_id': run_start_event_id, 'start': start or unknown('start not observed'),
             'end': end or unknown('end not observed'), 'model': model or unknown('model not exposed by source'),
             'status': status, 'evidence_events': evidence_events,
             'previous_observation': prior,
             'internal_reasoning_time': unknown('not observable from wall-clock intervals')},
            epoch['bindings'], [epoch_event_id] + ([run_start_event_id] if run_start_event_id else []) + evidence_events
            + ([prior] if prior else []),
            context, timestamp=timestamp, model=model or unknown('model not exposed by source'), delivery_key=delivery_key)

    def weekly(self, timezone='UTC'):
        if timezone == 'UTC':
            tz = dt.timezone.utc
        else:
            import re
            if not re.fullmatch(r'[+-](?:0[0-9]|1[0-3]):[0-5][0-9]|[+-]14:00', timezone):
                raise ArchiveError('timezone must be UTC or a fixed offset such as -07:00')
            sign = -1 if timezone[0] == '-' else 1
            tz = dt.timezone(sign * dt.timedelta(hours=int(timezone[1:3]), minutes=int(timezone[4:])))
        records = self._records()
        weeks, candidates, activities = {}, {}, {}
        def week_for(stamp):
            day = instant(stamp).astimezone(tz).date()
            monday = (day - dt.timedelta(days=day.weekday())).isoformat()
            return weeks.setdefault(monday, {'week_start': monday, 'events': [], 'candidate_births': [],
                                            'activities': [], 'task_counts': {}, 'known_wall_clock_seconds': 0.0})
        for e in records:
            p = e['payload']
            known = e['timestamp_source'] == 'supplied-event-time'
            stamp = e['timestamp'] if known else e['recorded_at']
            week_for(stamp)['events'].append({'id': e['id'], 'kind': e['kind'], 'sequence': e['sequence'],
                'time': stamp, 'time_basis': 'supplied_event_time' if known else 'recorded_at_event_time_unknown',
                'recorded_at': e['recorded_at'], 'run_id': e['run_id']})
            if p.get('timeline_version') != VERSION:
                continue
            if e['kind'] == 'candidate.created':
                item = dict(p, event_id=e['id'], recorded_at=e['recorded_at'], bindings=e['bindings'],
                            model=e['model'], run_id=e['run_id'], current_status='ACTIVE', decisions=[], assessments=[])
                candidates[p['candidate_id']] = item
                birth_stamp = p['birth'].get('value', e['recorded_at'])
                week_for(birth_stamp)['candidate_births'].append({'candidate_id': p['candidate_id'],
                    'epoch_event_id': p['epoch_event_id'], 'method_objects': e['bindings']['method'],
                    'birth': p['birth'], 'bucket_basis': 'birth' if p['birth']['status'] == 'known' else 'recorded_at_birth_unknown'})
            elif e['kind'] == 'candidate.decision':
                item = candidates[p['candidate_id']]
                item['current_status'] = {'REJECT': 'REJECTED', 'REOPEN': 'ACTIVE', 'SHORTLIST': 'SHORTLISTED',
                                          'SELECT': 'SELECTED', 'SET_ASIDE': 'SET_ASIDE'}[p['decision']]
                item['decisions'].append({'event_id': e['id'], **p})
            elif e['kind'] == 'candidate.independence_assessed':
                candidates[p['candidate_id']]['assessments'].append({'event_id': e['id'], **p})
            elif e['kind'] == 'activity.observed':
                # A later observation updates this derived view, never the old record.
                activities[p['activity_id']] = {'event_id': e['id'], 'recorded_at': e['recorded_at'], **p}
        for item in activities.values():
            complete = item['status'] == 'complete' and all(item[k]['status'] == 'known' for k in ('start', 'end'))
            duration = (instant(item['end']['value']) - instant(item['start']['value'])).total_seconds() if complete else None
            item['wall_clock_seconds'] = duration
            item['duration_status'] = 'known' if complete else 'incomplete'
            start = item['start'].get('value', item['recorded_at'])
            week = week_for(start)
            week['activities'].append(item['activity_id'])
            counts = week['task_counts']
            counts[item['task_type']] = counts.get(item['task_type'], 0) + 1
            # Split complete intervals at local Monday boundaries for honest weekly totals.
            if duration is not None:
                cursor = instant(item['start']['value']).astimezone(tz)
                end = instant(item['end']['value']).astimezone(tz)
                while cursor < end:
                    boundary_date = cursor.date() + dt.timedelta(days=7 - cursor.weekday())
                    boundary = dt.datetime.combine(boundary_date, dt.time(), tzinfo=tz)
                    until = min(boundary, end)
                    week_for(cursor.isoformat())['known_wall_clock_seconds'] += (until - cursor).total_seconds()
                    cursor = until
        for week in weeks.values():
            week['events'].sort(key=lambda e: (instant(e['time']), e['sequence']))
        return {'schema_version': VERSION, 'timezone': timezone, 'week_rule': 'Monday inclusive; next Monday exclusive',
                'notice': 'Derived private view; unknown birth/model/timing remain unknown. Overlapping activity intervals sum and do not measure person-hours or internal model reasoning.',
                'weeks': [weeks[k] for k in sorted(weeks)], 'candidates': list(candidates.values()),
                'activities': list(activities.values()),
                'epochs': [e for e in records if e['kind'] == 'lab.epoch' and e['payload'].get('timeline_version') == VERSION]}


def markdown(report):
    def cell(value):
        return str(value).replace('|', '\\|').replace('\n', ' ')
    lines = ['# Weekly research chronology', '', 'Timezone: ' + report['timezone'] + '. ' + report['week_rule'] + '.',
             '', report['notice'], '', '| Week starting | Activity types | Candidates recorded/born | Known wall-clock seconds |',
             '| --- | --- | --- | ---: |']
    for w in report['weeks']:
        tasks = ', '.join(k + ': ' + str(v) for k, v in sorted(w['task_counts'].items())) or 'unclassified/none observed'
        lines.append('| ' + ' | '.join(map(cell, [w['week_start'], tasks, len(w['candidate_births']), w['known_wall_clock_seconds']])) + ' |')
    lines += ['', '## Candidate provenance', '', '| Candidate | Type | Birth observation | Epoch / method objects | State | Genesis / parents |', '| --- | --- | --- | --- | --- | --- |']
    for c in report['candidates']:
        birth = c['birth'].get('value', 'UNKNOWN: ' + c['birth'].get('reason', ''))
        lines.append('| ' + ' | '.join(map(cell, [c['candidate_id'], c['artifact_type'], birth,
            c['epoch_event_id'] + ' / ' + ', '.join(c['bindings']['method']), c['current_status'],
            c['genesis'] + ' / ' + ', '.join(c['parent_candidate_events'])])) + ' |')
    lines += ['', '## Model and timing observations', '', '| Activity | Type | Model / source | Start / end | Wall-clock seconds | Status |', '| --- | --- | --- | --- | ---: | --- |']
    for a in report['activities']:
        model = a['model'].get('value', 'UNKNOWN') + ' / ' + a['model'].get('source', a['model'].get('reason', ''))
        lines.append('| ' + ' | '.join(map(cell, [a['activity_id'], a['task_type'], model,
            a['start'].get('value', 'UNKNOWN') + ' / ' + a['end'].get('value', 'UNKNOWN'),
            a['wall_clock_seconds'] if a['wall_clock_seconds'] is not None else 'UNKNOWN', a['status']])) + ' |')
    return '\n'.join(lines) + '\n'


def refresh(root, archive, timezone='UTC'):
    """Write replaceable reports only under lab research/views, outside archive."""
    root = _safe_path(root)
    output = _safe_path(root / 'research/views')
    archive_root = archive.root
    if output == archive_root or archive_root in output.parents:
        raise ArchiveError('derived timeline must remain outside canonical archive')
    report = Timeline(archive).weekly(timezone)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in [('timeline.json', canonical(report)), ('timeline.md', markdown(report).encode())]:
        target = _safe_path(output / name)
        temp = output / ('.timeline-' + uuid.uuid4().hex)
        with temp.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(str(temp), str(target))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    subs = parser.add_subparsers(dest='command', required=True)
    for command in ('epoch', 'candidate', 'decision', 'assess', 'activity'):
        sub = subs.add_parser(command)
        sub.add_argument('--request', required=True, help='JSON keyword arguments with explicit provenance')
    subs.add_parser('validate')
    sub = subs.add_parser('weekly')
    sub.add_argument('--timezone', default='UTC')
    args = parser.parse_args()
    try:
        root = _safe_path(args.root)
        archive = Archive(root / 'research/archive')
        timeline = Timeline(archive)
        if args.command == 'validate':
            result = timeline.validate()
        elif args.command == 'weekly':
            result = refresh(root, archive, args.timezone)
        else:
            result = getattr(timeline, args.command)(**json.loads(_read(args.request)))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get('ok') is False:
            sys.exit(1)
    except (ArchiveError, OSError, TypeError, ValueError, KeyError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == '__main__':
    main()
