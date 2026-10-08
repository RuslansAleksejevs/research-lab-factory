"""Synthetic chronology fixtures, not research or independence evidence."""
import json
import multiprocessing
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from research_archive import Archive, ArchiveError
from research_timeline import Timeline, markdown, refresh, unknown


def known(value, source='synthetic source clock'):
    return {'status': 'known', 'value': value, 'source': source}


def context(run='r1'):
    return {'actor': {'id': 'synthetic-ai', 'role': 'AI'}, 'session_id': 's1',
            'run_id': run, 'operation_id': 'operation-' + run, 'attempt_id': 'attempt-' + run}


def append_competing_observation(root, request, gate, results):
    """Both workers prepared an update from the same immutable predecessor."""
    gate.wait(timeout=10)
    try:
        event = Archive(root).append(request, request['id'])
        results.put(('committed', event['id']))
    except ArchiveError as exc:
        results.put(('rejected', str(exc)))


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='synthetic-timeline-')
        self.root = Path(self.temp.name).resolve()
        self.archive = Archive(self.root / 'research/archive').init()
        self.timeline = Timeline(self.archive)
        self.bindings = {'method': [self.archive.put(b'synthetic method v1')],
                         'instruction': [self.archive.put(b'synthetic instructions v1')],
                         'config': [self.archive.put(b'synthetic config v1')], 'input': []}
        self.epoch = self.timeline.epoch('v1', 'Synthetic epoch 1', self.bindings,
            'Initial synthetic protocol', 'No earlier comparable run', context(),
            timestamp='2026-09-01T00:00:00Z')
        self.start = self.run_start('r1', self.epoch)

    def tearDown(self):
        self.temp.cleanup()

    def run_start(self, run, epoch, stage='discovery', selection='selection-1'):
        return self.archive.append(dict(context(run), kind='operation.started',
            parents=[epoch['id']], bindings=epoch['bindings'],
            payload={'epoch_event_id': epoch['id'], 'stage_id': stage, 'selection_round_id': selection}),
            'start:' + run)

    def candidate(self, name='a', epoch=None, start=None, **kwargs):
        epoch = epoch or self.epoch
        start = start or self.start
        values = {'candidate_id': name, 'artifact_type': 'essay',
            'artifact_sha256': self.archive.put(('synthetic candidate ' + name).encode()),
            'epoch_event_id': epoch['id'], 'run_start_event_id': start['id'],
            'stage_id': start['payload']['stage_id'], 'selection_round_id': start['payload']['selection_round_id'],
            'actor_origin': 'AI', 'genesis': 'ORIGINAL', 'context': context(start['run_id']),
            'birth': known('2026-09-02T03:04:05Z')}
        values.update(kwargs)
        return self.timeline.candidate(**values)

    def activity(self, activity='prompt-1', observation='obs-1', **updates):
        values = {'activity_id': activity, 'observation_id': observation, 'task_type': 'essay_generation',
            'epoch_event_id': self.epoch['id'], 'stage_id': 'discovery', 'selection_round_id': 'selection-1',
            'context': context(), 'run_start_event_id': self.start['id']}
        values.update(updates)
        return self.timeline.activity(**values)

    def test_birth_exact_artifact_observed_time_recorded_time_and_unknown_independence(self):
        c = self.candidate(model=known('synthetic-model', 'synthetic runtime label'))
        self.assertEqual(c['id'], 'candidate:a')
        self.assertEqual(self.archive.get(c['payload']['artifact_sha256']), b'synthetic candidate a')
        self.assertEqual(c['timestamp'], '2026-09-02T03:04:05Z')
        self.assertNotEqual(c['recorded_at'], c['timestamp'])
        self.assertEqual(c['payload']['independence'], 'UNASSESSED')
        self.assertEqual(c['model']['source'], 'synthetic runtime label')
        self.assertTrue(self.timeline.validate()['ok'])

    def test_exact_redelivery_idempotent_conflicting_candidate_id_fails(self):
        a = self.candidate()
        self.assertEqual(self.candidate(), a)
        with self.assertRaisesRegex(ArchiveError, 'conflict'):
            self.candidate(artifact_sha256=self.archive.put(b'changed candidate'))
        self.assertEqual(len([e for e in self.archive.events() if e['kind'] == 'candidate.created']), 1)

    def test_epoch_versions_branch_merge_reject_reopen_and_no_three_candidate_cap(self):
        a = self.candidate('a')
        b = self.candidate('b', genesis='DERIVED', parent_candidate_events=[a['id']])
        c = self.candidate('c', genesis='DERIVED', parent_candidate_events=[a['id']])
        next_bindings = dict(self.bindings, method=[self.archive.put(b'synthetic method v2')])
        epoch2 = self.timeline.epoch('v2', 'Synthetic epoch 2', next_bindings,
            'Synthetic protocol change', 'Method differs; compare with caution', context('r2'),
            predecessor_epoch=self.epoch['id'], timestamp='2026-09-07T00:00:00Z')
        start2 = self.run_start('r2', epoch2, stage='synthesis', selection='selection-2')
        d = self.candidate('d', epoch=epoch2, start=start2, genesis='MERGED',
            parent_candidate_events=[b['id'], c['id']], birth=known('2026-09-08T00:00:00Z'))
        self.timeline.decision('reject-b', b['id'], 'REJECT', 'Synthetic assessment', 'selection-1', context())
        self.timeline.decision('reopen-b', b['id'], 'REOPEN', 'Synthetic new evidence', 'selection-2', context('r2'))
        self.timeline.decision('reject-c', c['id'], 'REJECT', 'Synthetic rejection', 'selection-2', context('r2'))
        report = self.timeline.weekly()
        candidates = {c['candidate_id']: c for c in report['candidates']}
        self.assertEqual(len(candidates), 4)
        self.assertEqual(candidates['b']['current_status'], 'ACTIVE')
        self.assertEqual(len(candidates['b']['decisions']), 2)
        self.assertEqual(candidates['c']['current_status'], 'REJECTED')
        self.assertEqual(candidates['d']['parent_candidate_events'], [b['id'], c['id']])
        self.assertEqual(candidates['d']['bindings']['method'], next_bindings['method'])
        self.assertEqual(candidates['a']['bindings']['method'], self.bindings['method'])
        self.assertEqual(len(report['epochs']), 2)
        self.assertIn('2026-08-31', [w['week_start'] for w in report['weeks']])
        self.assertIn('2026-09-07', [w['week_start'] for w in report['weeks']])
        self.assertEqual(self.archive.get(c['payload']['artifact_sha256']), b'synthetic candidate c')
        self.assertTrue(self.timeline.validate()['ok'])

    def test_unknown_birth_is_not_archive_commit_time(self):
        self.candidate(birth=unknown('pre-existing candidate; no source birth clock'))
        report = self.timeline.weekly()
        self.assertEqual(report['candidates'][0]['birth']['status'], 'unknown')
        births = [b for w in report['weeks'] for b in w['candidate_births']]
        self.assertEqual(births[0]['bucket_basis'], 'recorded_at_birth_unknown')
        self.assertIn('UNKNOWN:', markdown(report))

    def test_invalid_parent_and_epoch_or_stage_binding_rejected_before_birth_commit(self):
        with self.assertRaisesRegex(ArchiveError, 'candidate.created'):
            self.candidate(genesis='DERIVED', parent_candidate_events=[self.start['id']])
        with self.assertRaisesRegex(ArchiveError, 'at least two'):
            self.candidate(genesis='MERGED')
        with self.assertRaisesRegex(ArchiveError, 'stage_id'):
            self.candidate(stage_id='different-stage')
        other = self.timeline.epoch('v2', 'Synthetic second epoch', self.bindings,
            'Another paradigm with unchanged executable bytes', 'Conceptual differences matter', context('r2'))
        with self.assertRaisesRegex(ArchiveError, 'epoch'):
            self.candidate(epoch=other)
        changed = dict(self.bindings, method=[self.archive.put(b'different method')])
        with self.assertRaisesRegex(ArchiveError, 'bindings mismatch'):
            self.timeline.validate_epoch(self.epoch['id'], changed)
        self.assertFalse(any(e['kind'] == 'candidate.created' for e in self.archive.events()))

    def test_actor_origin_and_naive_time_fail(self):
        with self.assertRaisesRegex(ArchiveError, 'actor origin'):
            self.candidate(actor_origin='HUMAN')
        with self.assertRaisesRegex(ArchiveError, 'timezone'):
            self.candidate(birth=known('2026-09-02T03:04:05'))
        with self.assertRaisesRegex(ArchiveError, 'source'):
            self.candidate(model={'status': 'known', 'value': 'invented'})

    def test_sourced_independence_assessment_is_separate_and_does_not_mutate_birth(self):
        c = self.candidate()
        evidence = self.archive.put(b'synthetic critique evidence')
        e = self.archive.append(dict(context(), kind='synthetic.review', outputs=[evidence]), 'review-1')
        with self.assertRaisesRegex(ArchiveError, 'sourced'):
            self.timeline.assess('bad', c['id'], 'SUPPORTED', 'Unsupported synthetic assertion', [], [], context())
        self.timeline.assess('review', c['id'], 'INCONCLUSIVE', 'Synthetic comparison has limits',
                             [e['id']], [evidence], context())
        report = self.timeline.weekly()
        self.assertEqual(report['candidates'][0]['independence'], 'UNASSESSED')
        self.assertEqual(report['candidates'][0]['assessments'][0]['assessment'], 'INCONCLUSIVE')
        self.assertEqual(next(e for e in self.archive.events() if e['id'] == c['id']), c)

    def test_week_split_fixed_offset_known_model_and_wall_clock_only(self):
        self.activity(start=known('2026-09-06T23:59:00Z'), end=known('2026-09-07T00:01:00Z'),
            status='complete', model=known('synthetic-model-v1', 'synthetic metadata'))
        utc = self.timeline.weekly()
        weeks = {w['week_start']: w for w in utc['weeks']}
        self.assertEqual(weeks['2026-08-31']['known_wall_clock_seconds'], 60)
        self.assertEqual(weeks['2026-09-07']['known_wall_clock_seconds'], 60)
        activity = utc['activities'][0]
        self.assertEqual(activity['wall_clock_seconds'], 120)
        self.assertEqual(activity['internal_reasoning_time']['status'], 'unknown')
        local = {w['week_start']: w for w in self.timeline.weekly('-07:00')['weeks']}
        self.assertEqual(local['2026-08-31']['known_wall_clock_seconds'], 120)
        self.assertEqual(weeks['2026-08-31']['task_counts']['essay_generation'], 1)

    def test_unknown_open_and_interrupted_durations_never_assume_success(self):
        self.activity()
        self.activity(activity='interrupted', observation='obs-2', status='interrupted',
            start=known('2026-09-02T01:00:00Z'), end=known('2026-09-02T01:02:00Z'))
        self.activity(activity='missing-end', observation='obs-3', status='complete',
            start=known('2026-09-02T01:00:00Z'))
        for activity in self.timeline.weekly()['activities']:
            self.assertIsNone(activity['wall_clock_seconds'])
            self.assertEqual(activity['duration_status'], 'incomplete')
            self.assertEqual(activity['model']['status'], 'unknown')
        self.assertEqual(sum(w['known_wall_clock_seconds'] for w in self.timeline.weekly()['weeks']), 0)

    def test_updated_observation_counts_activity_once_preserving_original_event(self):
        first = self.activity(start=known('2026-09-02T00:00:00Z'))
        final = self.activity(observation='obs-2', start=known('2026-09-02T00:00:00Z'),
            end=known('2026-09-02T00:00:03Z'), status='complete')
        self.assertEqual(final['payload']['previous_observation'], first['id'])
        self.assertIn(first['id'], final['parents'])
        self.assertEqual(self.activity(start=known('2026-09-02T00:00:00Z')), first)
        with self.assertRaisesRegex(ArchiveError, 'identity/context'):
            self.activity(observation='obs-3', task_type='critique')
        report = self.timeline.weekly()
        self.assertEqual(len(report['activities']), 1)
        self.assertEqual(report['activities'][0]['wall_clock_seconds'], 3)
        self.assertEqual(next(e for e in self.archive.events() if e['id'] == first['id']), first)

    def test_invalid_timing_and_unknown_task_fail(self):
        with self.assertRaisesRegex(ArchiveError, 'before'):
            self.activity(start=known('2026-09-02T01:00:00Z'), end=known('2026-09-01T01:00:00Z'))
        with self.assertRaisesRegex(ArchiveError, 'task type'):
            self.activity(task_type='invented-task-type')
        with self.assertRaisesRegex(ArchiveError, 'timezone'):
            self.timeline.weekly('imaginary-zone')

    def test_derived_reports_outside_archive_have_no_export_side_effect(self):
        self.candidate()
        before = {p.relative_to(self.archive.root): p.read_bytes() for p in self.archive.root.rglob('*') if p.is_file()}
        report = refresh(self.root, self.archive)
        self.assertEqual(json.loads((self.root / 'research/views/timeline.json').read_text()), report)
        self.assertIn('Candidate provenance', (self.root / 'research/views/timeline.md').read_text())
        refresh(self.root, self.archive)
        after = {p.relative_to(self.archive.root): p.read_bytes() for p in self.archive.root.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((self.root / 'public').exists())

    def test_generic_archive_write_cannot_fake_typed_birth_validation(self):
        c = self.candidate()
        payload = dict(c['payload'], candidate_id='bad', epoch_event_id=self.start['id'])
        before = self.archive.events()
        with self.assertRaisesRegex(ArchiveError, 'lab.epoch'):
            self.archive.append(dict(context(), kind='candidate.created', id='candidate:bad', payload=payload,
                bindings=self.bindings, parents=[self.start['id']], outputs=c['outputs'], timestamp=c['timestamp']), 'bad-typed')
        self.assertEqual(self.archive.events(), before)
        self.assertTrue(self.timeline.validate()['ok'])

    def test_concurrent_stale_activity_update_is_rejected_under_archive_lock(self):
        first = self.activity(start=known('2026-09-02T00:00:00Z'))
        process_context = multiprocessing.get_context('fork')
        gate, results = process_context.Barrier(2), process_context.Queue()
        workers = []
        for n in range(2):
            payload = dict(first['payload'], previous_observation=first['id'],
                           end=known('2026-09-02T00:00:03Z'), status='complete')
            request = dict(context(), kind='activity.observed', id='activity:competing-' + str(n),
                parents=first['parents'] + [first['id']], bindings=first['bindings'], model=first['model'],
                payload=payload)
            worker = process_context.Process(target=append_competing_observation,
                args=(self.archive.root, request, gate, results))
            worker.start()
            workers.append(worker)
        try:
            for worker in workers:
                worker.join(15)
                self.assertFalse(worker.is_alive())
                self.assertEqual(worker.exitcode, 0)
            outcomes = [results.get(timeout=2), results.get(timeout=2)]
            self.assertEqual(sorted(outcome[0] for outcome in outcomes), ['committed', 'rejected'])
            rejection = next(outcome[1] for outcome in outcomes if outcome[0] == 'rejected')
            self.assertIn('latest observation', rejection)
            self.assertTrue(self.archive.validate()['ok'])
            self.assertTrue(self.timeline.validate()['ok'])
            activity_events = [e for e in self.archive.events() if e['kind'] == 'activity.observed']
            self.assertEqual(len(activity_events), 2)
            self.assertEqual(activity_events[0], first)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            results.close()
            results.join_thread()

    def test_unknown_epoch_material_is_explicit_and_predecessor_must_be_typed(self):
        bindings = {k: [] for k in self.bindings}
        epoch = self.timeline.epoch('unknown', 'Synthetic unavailable versions', bindings,
            'Import with unavailable config', 'Comparability is unknown', context('r2'))
        self.assertEqual(epoch['payload']['availability']['method']['status'], 'unknown')
        with self.assertRaisesRegex(ArchiveError, 'lab.epoch'):
            self.timeline.epoch('bad', 'Bad predecessor', bindings, 'Synthetic', 'Synthetic',
                context('r2'), predecessor_epoch=self.start['id'])


if __name__ == '__main__':
    unittest.main()
