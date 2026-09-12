"""Bounded preparation inputs; existing gates remain the mutation authority."""
from copy import deepcopy

from cogito_common import CogitoError, atomic_create_json
from cogito_contracts import package_hash, package_document_refs
from cogito_planning import document_snapshot, validate_snapshot
from cogito_replan_lock import project_lock
from cogito_run_queries import operation_hint


def _transition(store, event, payload, required=()):
    hint = operation_hint(store.root, store.run_id, 'transition', ['--event', event])
    hint.update(input=deepcopy(payload), required_inputs=list(required))
    hint['argv'].extend(['--payload-json', '<payload-json>'])
    hint['note'] = 'Complete input and encode it as one JSON argument for --payload-json. '
    return hint


def _candidate(state):
    if state.get('package_hash') or state['state'] != 'awaiting-package-approval':
        raise CogitoError('candidate export requires the current unapproved Package')
    candidate = (state.get('planning') or {}).get('candidate')
    if not candidate:
        raise CogitoError('current candidate snapshot is unavailable; inspect planning history, do not invent a Package')
    validate_snapshot(candidate)
    if package_hash(candidate['package']) != state['candidate_package_hash']:
        raise CogitoError('candidate snapshot does not match current Package hash')
    return candidate


def _candidate_path(store, digest):
    return store.run_dir / 'drafts' / f'candidate-{digest}.json'


def export_candidate(store, digest):
    """Export exact saved JSON for reading/approval without copying all history."""
    with project_lock(store.root):
        state = store.load()
        candidate = _candidate(state)
        if digest != state['candidate_package_hash']:
            raise CogitoError('candidate changed; query next for the current candidate hash')
        target = _candidate_path(store, digest)
        if target.resolve() != target:
            raise CogitoError('candidate export path cannot contain symlinks')
        from cogito_checkpoints import json_bytes
        expected = json_bytes(candidate['package'])
        if not atomic_create_json(target, candidate['package']) and target.read_bytes() != expected:
            raise CogitoError('candidate export already exists with different content; preserve it and inspect the path')
        return {'run_id': store.run_id, 'candidate_package_hash': digest,
                'planning_round': candidate['round'], 'package_path': str(target),
                'documents': deepcopy(package_document_refs(candidate['package'], include_sources=True)),
                'unavailable_documents': deepcopy(candidate['unavailable']),
                'note': 'Read this exact candidate and its referenced documents. Export is not approval. '
                        'Query next for review/approval; do not edit this frozen export to revise the Package.'}


def checkpoint_commit_operations(store, paths, message):
    operations = [{'operation': 'git-add', 'cwd': str(store.root),
                   'argv': ['git', '-C', str(store.root), 'add', '--', *paths]},
                  {'operation': 'git-commit', 'cwd': str(store.root),
                   'argv': ['git', '-C', str(store.root), 'commit', '--only', '-m', message, '--', *paths]}]
    return {'operations': operations,
            'note': 'Inspect the listed files and preserve unrelated staging. Execute in order; after commit query next '
                    'for the exact checkpoint record command. If commit already exists, do not commit again.'}


def checkpoint_hints(store, state):
    try:
        head = store._git('rev-parse', 'HEAD')
        if head != state['checkpoint_head']:
            store._validate_checkpoint_commit(head)
            return {'operations': [operation_hint(store.root, store.run_id, 'checkpoint',
                ['record', '--commit-id', head])],
                'note': 'The stage commit is already present. Record it; do not create another commit. '
                        'If recovering an interrupted record, use its original action ID.'}
        store._checkpoint_baseline(state)
        return {'operations': [operation_hint(store.root, store.run_id, 'checkpoint', ['prepare'], action_id=None)]}
    except (CogitoError, OSError) as exc:
        return {'operations': [], 'blockers': [str(exc)[:600]]}


def preparation_hints(store, state, action, *, rp=False):
    if action == 'commit-stage-artifacts':
        return checkpoint_hints(store, state)
    supported = {'draft-shared-understanding', 'request-shared-confirmation', 'run-boundary-gate',
                 'author-development-package', 'assess-mini-package-eligibility',
                 'request-package-approval', 'request-independent-planning-review', 'validate-latest-baseline'}
    if action not in supported:
        return {}
    planning = state.get('planning') or {}
    round_payload = {'planning_round': planning['round']} if planning.get('revision') else {}
    context = {'kind': state['kind']}
    document = state.get('shared_document') or planning.get('shared_document')
    if not document and state.get('shared_understanding_hash'):
        for event in reversed(store._events.read()):
            if (event['type'] == 'shared-understanding-ready'
                    and event['payload'].get('shared_understanding_hash') == state['shared_understanding_hash']):
                document = event['payload'].get('document')
                break
    if document and document.get('hash') == state.get('shared_understanding_hash'):
        context['shared_understanding'] = deepcopy(document)
    elif state.get('shared_understanding_hash'):
        context['shared_understanding'] = {'hash': state['shared_understanding_hash'],
            'note': 'No current document reference is recorded; do not invent the original text.'}
    if state.get('boundary'):
        context['boundary'] = deepcopy(state['boundary'])
    output = {'preparation_context': context, 'operations': []}
    if action in {'request-shared-confirmation', 'run-boundary-gate', 'author-development-package'} and document:
        try:
            document_snapshot(store.root, document)
        except (CogitoError, OSError) as exc:
            output['blockers'] = [str(exc)[:600]]
            return output
    if action == 'draft-shared-understanding':
        hint = _transition(store, 'shared-understanding-ready', round_payload,
                           ['document.path', 'document.hash', 'shared_understanding_hash'])
        hint['note'] += 'Continue requirement questions first; publish only when readiness is ready. Document hash and summary hash must match.'
        output['operations'] = [hint]
    elif action == 'request-shared-confirmation':
        hint = _transition(store, 'shared-understanding-confirmed',
            {**round_payload, 'shared_understanding_hash': state['shared_understanding_hash']}, ['confirmed'])
        hint['note'] += 'Present the exact summary; confirmed must reflect actual user confirmation, never a default.'
        output['operations'] = [hint]
    elif action == 'run-boundary-gate':
        output['operations'] = [_transition(store, 'boundary-complete', round_payload, ['decision', 'evidence'])]
        output['operations'][0]['note'] += 'Assess single-slice or split-required and supply supporting evidence.'
    elif action in {'author-development-package', 'assess-mini-package-eligibility'}:
        output['operations'] = [operation_hint(store.root, store.run_id, 'prepare-package', ['--package', '<package.json>'])]
        context['package_guidance'] = 'Author scope, policy, tasks and checks using the existing Package contract. '
        context['package_guidance'] += ('Mini requires eligibility assessment and has no Slice/Spec/Plan.'
            if action == 'assess-mini-package-eligibility' else 'Include Spec/Plan, DAG and consistent Package/Worker/Task paths.')
    elif action == 'validate-latest-baseline':
        output['operations'] = [operation_hint(store.root, store.run_id, 'start')]
    else:
        try:
            candidate = _candidate(state)
            digest = state['candidate_package_hash']
            context['candidate'] = {'hash': digest, 'round': candidate['round'],
                'documents': deepcopy(package_document_refs(candidate['package'], include_sources=True))}
            output['operations'] = [operation_hint(store.root, store.run_id, 'planning',
                ['candidate', '--candidate-hash', digest], action_id=None)]
            if action == 'request-independent-planning-review':
                source_round = planning['revision']['source']['candidate']['round']
                output['operations'].append(operation_hint(store.root, store.run_id, 'planning',
                    ['compare', '--from-round', str(source_round), '--to-round', str(planning['round'])], action_id=None))
                hint = operation_hint(store.root, store.run_id, 'planning', ['review'],
                    input_value={'round': planning['round'], 'proposal_hash': planning['proposal_hash']},
                    required_inputs=['reviewer_id', 'findings', 'assessment.consistency', 'assessment.impact', 'assessment.reuse'])
                hint['note'] = 'Read the exported candidate and the supplied comparison before independent review; do not infer a clean review.'
                output['operations'].append(hint)
            elif not rp:
                store._planning_approval_binding(state)
                hint = operation_hint(store.root, store.run_id, 'approve',
                    ['--package', str(_candidate_path(store, digest))])
                hint['note'] = 'Export and present the exact candidate first. Execute approve only after explicit user approval.'
                output['operations'].append(hint)
        except (CogitoError, OSError) as exc:
            output['blockers'] = [str(exc)[:600]]
    return output
