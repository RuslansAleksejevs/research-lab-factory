#!/usr/bin/env python3
"""Philosophy contracts and archive integrity; does not certify philosophy."""
import hashlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from research_archive import Archive


@contextmanager
def regular_file(root, relative):
    """Open each path component without following links, including raced replacements."""
    if (not isinstance(relative, str) or not relative or relative.startswith('/')
            or '\\' in relative or any(part in ('', '.', '..') for part in relative.split('/'))):
        raise ValueError('noncanonical relative path: ' + repr(relative))
    descriptors = []
    try:
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(root, directory_flags)
        descriptors.append(descriptor)
        for part in relative.split('/')[:-1]:
            descriptor = os.open(part, directory_flags, dir_fd=descriptor)
            descriptors.append(descriptor)
        descriptor = os.open(relative.split('/')[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor)
        descriptors.append(descriptor)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError('not a regular file: ' + relative)
        yield descriptor
        after = os.fstat(descriptor)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('file changed while validating: ' + relative)
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def control_bytes(root, relative):
    with regular_file(root, relative) as descriptor:
        if os.fstat(descriptor).st_size > 4 * 1024 * 1024:
            raise ValueError('oversized control file: ' + relative)
        chunks = []
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return b''.join(chunks)
            chunks.append(chunk)
            if sum(map(len, chunks)) > 4 * 1024 * 1024:
                raise ValueError('oversized control file: ' + relative)


def file_digest(root, relative):
    digest = hashlib.sha256()
    with regular_file(root, relative) as descriptor:
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)


def parse_json(content):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result
    def reject_constant(value):
        raise ValueError('non-finite JSON constant: ' + value)
    return json.loads(content, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def report(errors, warnings=None):
    return {'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'warnings': warnings or [],
            'boundary': 'Structural, hash and workflow consistency only; no truth, novelty or complete provider capture claim.'}


def check_profile_shape(profile):
    """Validate the live portable profile independently of its historical hash.

    This checks usable values and references, not cosmetic identifier patterns.
    Exact origin, policy and source bindings are checked separately below.
    """
    def object_value(value, name):
        if not isinstance(value, dict):
            raise ValueError(name + ' must be an object')
        return value

    def text(value, name, nonempty=False):
        if not isinstance(value, str) or (nonempty and not value.strip()):
            raise ValueError(name + ' must be ' + ('a nonempty string' if nonempty else 'a string'))
        return value

    def array(value, name, item_type, nonempty=False):
        if not isinstance(value, list) or (nonempty and not value) or any(not isinstance(item, item_type) for item in value):
            raise ValueError(name + ' must be ' + ('a nonempty array' if nonempty else 'an array') + ' of ' + item_type.__name__)
        return value

    def choice(value, choices, name):
        if not isinstance(value, str) or value not in choices:
            raise ValueError(name + ' has an unsupported value')

    object_value(profile, 'LAB_PROFILE')
    if type(profile.get('schema_version')) not in (int, float) or profile['schema_version'] != 1:
        raise ValueError('LAB_PROFILE.schema_version must equal numeric 1, excluding booleans')
    choice(profile.get('profile_status'), ('READY', 'PROVISIONAL'), 'profile_status')
    template = object_value(profile.get('template'), 'template')
    if template.get('id') != 'math-research-lab-template':
        raise ValueError('template.id is unsupported')
    text(template.get('version'), 'template.version', True)
    lab = object_value(profile.get('lab'), 'lab')
    for key in ('id', 'directory_name', 'title', 'mission'):
        text(lab.get(key), 'lab.' + key, True)
    for key in ('article_title', 'language'):
        text(lab.get(key), 'lab.' + key)
    for key in ('owners', 'collaborators', 'research_areas', 'deliverables', 'in_scope', 'out_of_scope', 'modules'):
        array(lab.get(key), 'lab.' + key, str, nonempty=key == 'research_areas')
    if (lab.get('kind') != 'PHILOSOPHY_PROGRAM' or lab['modules']
            or lab.get('collaboration') is not None or 'areas' in lab):
        raise ValueError('profile must describe the standalone philosophy mode')

    research = object_value(profile.get('research'), 'research')
    for key in ('central_questions', 'terminology', 'conventions', 'required_checks', 'source_priorities'):
        array(research.get(key), 'research.' + key, str)
    tracks = array(research.get('tracks'), 'research.tracks', dict, nonempty=True)
    track_ids = []
    for index, track in enumerate(tracks):
        name = 'research.tracks[' + str(index) + ']'
        track_ids.append(text(track.get('id'), name + '.id', True))
        text(track.get('title'), name + '.title', True)
        text(track.get('description'), name + '.description')
    if len(set(track_ids)) != len(track_ids):
        raise ValueError('research.tracks IDs must be unique')
    default = text(research.get('default_track'), 'research.default_track', True)
    if default not in track_ids:
        raise ValueError('research.default_track must reference a declared track')
    for index, role in enumerate(array(research.get('specialist_roles'), 'research.specialist_roles', dict)):
        name = 'research.specialist_roles[' + str(index) + ']'
        text(role.get('id'), name + '.id', True)
        text(role.get('description'), name + '.description', True)
        array(role.get('checks'), name + '.checks', str)
    if 'initial_problem' not in research or research['initial_problem'] is not None:
        raise ValueError('philosophy research.initial_problem must be null')
    object_value(research.get('status_policy'), 'research.status_policy')
    object_value(profile.get('source_policy'), 'source_policy')
    object_value(profile.get('communication'), 'communication')
    for index, assumption in enumerate(array(profile.get('recorded_assumptions'), 'recorded_assumptions', dict)):
        name = 'recorded_assumptions[' + str(index) + ']'
        text(assumption.get('statement'), name + '.statement', True)
        text(assumption.get('basis'), name + '.basis')
        choice(assumption.get('confidence'), ('low', 'medium', 'high'), name + '.confidence')
    for index, decision in enumerate(array(profile.get('profile_decisions'), 'profile_decisions', dict, nonempty=True)):
        name = 'profile_decisions[' + str(index) + ']'
        text(decision.get('field'), name + '.field', True)
        text(decision.get('basis'), name + '.basis', True)
        choice(decision.get('classification'), ('user_confirmed', 'evidence_backed_inference', 'factory_default', 'assumption'), name + '.classification')
        choice(decision.get('confidence'), ('low', 'medium', 'high'), name + '.confidence')
    intake = object_value(profile.get('bootstrap_intake_report'), 'bootstrap_intake_report')
    for category in ('unreadable_items', 'unclassified_items', 'ignored_items'):
        for item in array(intake.get(category), 'bootstrap_intake_report.' + category, dict):
            text(item.get('name'), 'intake item.name', True)
            text(item.get('reason'), 'intake item.reason', True)
    array(profile.get('unresolved_profile_questions'), 'unresolved_profile_questions', str)
    for item in array(profile.get('bootstrap_materials'), 'bootstrap_materials', dict):
        for key in ('stored_name', 'kind', 'trust_tier', 'sha256'):
            text(item.get(key), 'bootstrap material.' + key)
        if not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('bootstrap material.sha256 is invalid')
    if 'integrations' in profile:
        integrations = object_value(profile['integrations'], 'integrations')
        terminal = object_value(integrations.get('claude_terminal'), 'integrations.claude_terminal')
        if type(terminal.get('enabled')) is not bool:
            raise ValueError('integrations.claude_terminal.enabled must be boolean')


def validate(root):
    errors = []
    warnings = []
    required = ['AGENTS.md', 'AGENT_POLICY.md', 'START_HERE.md', 'LAB_PROFILE.json',
                'USER_PREFERENCES.md', '.lab/user_policy.json', '.lab/philosophy.json',
                '.lab/manifest.json', '.lab/bootstrap_inputs.json',
                'methods/simple-v1.json', 'workflows/ROUND.md', 'scripts/capture_codex.py',
                'scripts/research_archive.py', 'scripts/philosophy_round.py',
                'docs/ARCHIVE_FORMAT.md', 'docs/CAPTURE.md', 'knowledge/resume.md']
    required.extend([
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
    ])
    for name in required:
        if not (root / name).is_file():
            errors.append('missing ' + name)
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                errors.append('unsafe filesystem type: ' + str(path.relative_to(root)))
        dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__')]
    if errors:
        return report(errors, warnings)
    try:
        profile_bytes = control_bytes(root, 'LAB_PROFILE.json')
        profile = parse_json(profile_bytes)
        check_profile_shape(profile)
        terminal = subprocess.run(
            [sys.executable, '-B', str(root / 'scripts/claude_terminal/claude_runner.py'), 'integration-status'],
            cwd=root, text=True, capture_output=True, timeout=30,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
        if terminal.returncode:
            errors.append('terminal integration setting: ' + (terminal.stdout + terminal.stderr)[-2000:])
        manifest = parse_json(control_bytes(root, '.lab/manifest.json'))
        if (type(manifest.get('schema_version')) is not int or manifest['schema_version'] != 1
                or manifest.get('template_id') != 'math-research-lab-template'
                or manifest.get('lab_kind') != 'PHILOSOPHY_PROGRAM'
                or manifest.get('lab_id') != profile['lab']['id']
                or manifest.get('directory_name') != profile['lab']['directory_name']
                or manifest.get('template_version') != profile['template']['version']
                or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('profile_sha256', ''))
                or not re.fullmatch(r'[0-9a-f]{64}', manifest.get('scaffold_sha256', ''))
                or manifest.get('modules') != [] or manifest.get('initial_dossier') is not None):
            errors.append('generation manifest/profile identity or digest mismatch')
        if manifest.get('profile_sha256') != hashlib.sha256(profile_bytes).hexdigest():
            warnings.append('LAB_PROFILE differs from its bootstrap digest; review the recorded change. '
                            'The manifest preserves the original generation record.')
        if profile['lab']['kind'] != 'PHILOSOPHY_PROGRAM' or not profile['lab'].get('research_areas'):
            errors.append('explicit philosophy profile/research areas required')
        if profile['lab']['modules'] or 'areas' in profile['lab']:
            errors.append('math modules are incompatible')
        policy = profile['research']['status_policy']
        expected_policy = {
            'initial_position_status': 'UNEXAMINED',
            'position_statuses': ['UNEXAMINED', 'EXPLORING', 'TENTATIVE', 'ADOPTED', 'REVISED', 'SUSPENDED'],
            'argument_statuses': ['DRAFT', 'RECONSTRUCTED', 'UNDER_CRITICISM', 'REVISED', 'SET_ASIDE'],
            'source_verification_required': True, 'disagreement_preserved': True,
        }
        if (policy != expected_policy or policy.get('source_verification_required') is not True
                or policy.get('disagreement_preserved') is not True):
            errors.append('philosophical assessment contract mismatch')
        forbidden = ('PROOF_I3', 'VERIFIED_PROOF', 'VERIFIED_COUNTEREXAMPLE')
        if any(s in json.dumps(policy) for s in forbidden):
            errors.append('mathematical status cannot certify philosophical assessments')
        method = parse_json(control_bytes(root, 'methods/simple-v1.json'))
        if method['stages'] != ['question','sources','contribution','critique','decision']:
            errors.append('unsupported baseline cycle')
        marker = parse_json(control_bytes(root, '.lab/philosophy.json'))
        if marker != {'schema_version': 1, 'kernel': 'philosophy.v1', 'archive_format': 'research-archive.v1', 'control_room_actions': []}:
            errors.append('philosophy marker mismatch')
        for excluded in ('.lab/control_room_actions.json', '.lab/durable_research_memory.json',
                         'research/formalization', 'knowledge/claim_ledger.yaml'):
            if (root / excluded).exists():
                errors.append('incompatible mathematical capability installed: ' + excluded)
        policy_bytes = control_bytes(root, 'USER_PREFERENCES.md')
        policy_hash = hashlib.sha256(policy_bytes).hexdigest()
        # The generator's sidecar uses a nested portable_view, pinned exactly.
        sidecar_bytes = control_bytes(root, '.lab/user_policy.json')
        sidecar = parse_json(sidecar_bytes)
        expected_manifest_policy = dict(sidecar)
        expected_manifest_policy.update(sidecar_path='.lab/user_policy.json', sidecar_sha256=hashlib.sha256(sidecar_bytes).hexdigest())
        if (sidecar != profile.get('user_policy') or manifest.get('user_policy') != expected_manifest_policy
                or sidecar.get('portable_view') != {'path': 'USER_PREFERENCES.md', 'sha256': policy_hash}):
            errors.append('portable user policy hash binding mismatch')
        if profile.get('repository_first') != {'enabled': False} or manifest.get('repository_first') != {'enabled': False}:
            errors.append('incompatible repository-first capability')
        input_records = parse_json(control_bytes(root, '.lab/bootstrap_inputs.json'))
        if input_records != manifest.get('bootstrap_inputs'):
            errors.append('bootstrap origin record mismatch')
        projected = [{key: item[key] for key in ('stored_name', 'kind', 'trust_tier', 'sha256')} for item in input_records]
        if projected != profile['bootstrap_materials']:
            errors.append('bootstrap profile projection mismatch')
        seen = set()
        for item in profile['bootstrap_materials']:
            relative = item['stored_name']
            if not relative.startswith('00_INBOX_TO_ANALYZE/') or relative in seen:
                raise ValueError('bootstrap path is outside intake or duplicated')
            seen.add(relative)
            if file_digest(root, relative) != item['sha256']:
                errors.append('bootstrap input mismatch: ' + item['stored_name'])
        if errors:
            return report(errors, warnings)
        archive_path = root / 'research/archive'
        if archive_path.exists():
            archive_report = Archive(archive_path).validate()
            if not archive_report['ok']:
                errors.append('archive integrity: ' + json.dumps(archive_report['errors']))
            from philosophy_round import validate_round_history
            errors.extend(validate_round_history(Archive(archive_path)))
            from research_timeline import Timeline
            timeline_report = Timeline(Archive(archive_path)).validate()
            if not timeline_report['ok']:
                errors.append(timeline_report['error'])
            from philosophy_round import STAGES
            grouped = {}
            for event in Archive(archive_path).events():
                grouped.setdefault(event['run_id'], []).append(event)
                if event['kind'] == 'checkpoint':
                    p = event['payload']
                    if p.get('protocol') != 'philosophy-checkpoint.v1' or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', p.get('research_date','')):
                        errors.append('invalid philosophy checkpoint')
                    if p.get('truth_status') != 'NOT_CERTIFIED':
                        errors.append('checkpoint cannot certify truth')
            for run, history in grouped.items():
                starts = [e for e in history if e['kind'] == 'operation.started' and e['payload'].get('protocol') == 'philosophy-round.v1']
                if not starts:
                    continue
                if len(starts) != 1:
                    errors.append('multiple round starts: ' + run)
                stages = [e for e in history if e['kind'] == 'round.stage']
                if [e['payload'].get('stage') for e in stages] != STAGES[:len(stages)]:
                    errors.append('stage order mismatch: ' + run)
                for e in stages:
                    if e['bindings'] != starts[0]['bindings']:
                        errors.append('stage version binding mismatch: ' + run)
    except (KeyError, ValueError, TypeError, OSError, AttributeError) as exc:
        errors.append('contract error: ' + str(exc))
    return report(errors, warnings)


if __name__ == '__main__':
    result = validate(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(result['status'] != 'PASS')
