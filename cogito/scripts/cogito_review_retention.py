"""Prepare a read-only retention proposal; commit it with ordinary review closure."""
from copy import deepcopy
import hashlib
from pathlib import Path

from cogito_common import CogitoError, hash_json, load_json
from cogito_contracts import materialize_contract_with_limits, path_allowed
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_review_retention_rules import (
    reference, source_review, validate_candidate, validate_impact, validate_reviewer,
)
from cogito_task_finish import select_task_evidence


def runtime_binding(workflow):
    """New verification receipts bind the executor; old receipts remain readable."""
    scripts = Path(__file__).resolve().parent
    return hash_json({'workflow': workflow, 'scripts': {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(scripts.glob('*.py'))}})


def _effective(store, events):
    return materialize_contract_with_limits(store.approved_package(),
        [e['payload']['amendment'] for e in events if e['type'] == 'technical-amendment-added'],
        store.workflow['limits'])


def _last(events, kind):
    values = [e for e in events if e['type'] == kind]
    if not values:
        raise CogitoError('retention requires recorded ' + kind)
    return values[-1]


def _evidence(store, events, path):
    recorded = [e for e in events if e['type'] == 'check-evidence-recorded'
                and e['payload']['evidence_path'] == path]
    root = (store.run_dir / 'evidence').resolve()
    try:
        Path(path).resolve().relative_to(root)
    except ValueError as exc:
        raise CogitoError('retention evidence is outside this Run') from exc
    item = load_json(Path(path))
    if not recorded or recorded[-1]['payload']['evidence_hash'] != hash_json(item):
        raise CogitoError('retention evidence changed or is missing')
    return item


def _touches(store, worktree, base, head, old_tree, tree):
    store._git_at(worktree, 'merge-base', '--is-ancestor', base, head)
    commits = store._git_at(worktree, 'rev-list', '--reverse', base + '..' + head).splitlines()
    touched = set()
    for commit in commits:
        parents = store._git_at(worktree, 'rev-list', '--parents', '-n', '1', commit).split()
        if len(parents) != 2:
            raise CogitoError('retention requires an unambiguous linear correction history')
        touched.update(filter(None, store._git_at(worktree, 'diff', '--name-only', '--no-renames',
            '--no-ext-diff', '--ignore-submodules=none', '-z', parents[1], commit, '--').split('\0')))
    touched.update(filter(None, store._git_at(worktree, 'diff', '--name-only', '--no-renames',
        '--no-ext-diff', '--ignore-submodules=none', '-z', old_tree, tree, '--').split('\0')))
    return touched


def _sensitive(path):
    """Small explicit conservative filter, not a language dependency analyser."""
    name = Path(path).name.lower()
    return (path.startswith(('.codex/', '.agents/', '.github/', 'cogito/'))
            or name in {'package.json', 'pyproject.toml', 'setup.py', 'setup.cfg', 'dockerfile',
                        'makefile', 'conftest.py', 'go.mod', 'go.sum', 'cargo.toml'}
            or 'lock' in name or name.startswith(('.env', 'requirements'))
            or 'config' in name or name.endswith(('.yaml', '.yml', '.toml')))


def prepare_retention(store, impact):
    """Derive facts for Reviewer inspection without adding any authority event."""
    validate_impact(impact)
    state, events = store.load(), store._events.read()
    package = store.approved_package()
    if (state['state'] != 'reviewing' or package.get('task_delivery') != 'atomic'
            or package['kind'] not in {'feature', 'change', 'correction'}):
        raise CogitoError('retention requires reviewing Atomic Development')
    verification = _last(events, 'verification-passed')
    correction = _last(events, 'review-fix-complete')
    if not correction['sequence'] < verification['sequence']:
        raise CogitoError('retention requires verification after review fix')
    if any(e['type'] in {'integration-complete', 'slice-integration-complete',
                        'wave-integration-complete', 'human-review-required',
                        'technical-correction-complete', 'post-integration-correction-complete'}
           for e in events):
        raise CogitoError('retention is limited to pre-integration review fixes')
    current_runtime = runtime_binding(store.workflow)
    if verification['payload'].get('review_runtime') != current_runtime:
        raise CogitoError('retention requires verification with the current executor binding')
    tasks = state['tasks']
    worktrees = {t.get('worktree') for t in tasks.values()}
    if None in worktrees or len(worktrees) != 1:
        raise CogitoError('retention requires one completed correction checkout; use normal reviews')
    worktree = Path(next(iter(worktrees)))
    if any(t['status'] != 'verified' for t in tasks.values()):
        raise CogitoError('retention requires verified Tasks only')
    retained = {i['task_id'] for i in impact['retained']}
    affected = set(impact['affected_task_ids'])
    if not retained <= tasks.keys() or not affected <= tasks.keys():
        raise CogitoError('retention references unknown Tasks')
    head = store._git_at(worktree, 'rev-parse', 'HEAD')
    _, tree = capture_index_and_worktree_trees(worktree)
    store._validate_review_content(worktree, tree)
    contract = store.effective_package()
    new_tasks = {t['id']: t for t in contract['execution_dag']['tasks']}
    checks = {c['id']: c for c in contract['checks']}
    # Select the latest attempt; never silently fall back to a prior success.
    required = set(impact['check_ids'])
    required.update(k for task_id in affected for k in new_tasks[task_id]['check_ids'])
    if not required <= checks.keys():
        raise CogitoError('retention references unknown checks')
    evidence_paths = select_task_evidence(store, {'check_ids': sorted(required), 'worktree': str(worktree)})
    evidence = [_evidence(store, events, p) for p in evidence_paths]
    store._validate_evidence(package, evidence, snapshot=store._events.snapshot(), phase='implementation')
    if any(e['worktree_binding']['content_tree'] != tree for e in evidence):
        raise CogitoError('affected checks must cover current correction contents')
    # Also inspect latest attempts for retained checks: a new failure cannot hide
    # behind an old approval even when that check was omitted from impact input.
    for task_id in retained:
        for p in select_task_evidence(store, {'check_ids': new_tasks[task_id]['check_ids'], 'worktree': str(worktree)}):
            if _evidence(store, events, p)['passed'] is not True:
                raise CogitoError('retained Task has a newer failed check')
    sources = []
    for task_id in sorted(retained):
        approval = source_review(events, task_id, verification['sequence'])
        prior = [e for e in events if e['sequence'] < approval['sequence']]
        original_wave = _last(prior, 'verification-passed')
        if original_wave['payload'].get('review_runtime') != current_runtime:
            raise CogitoError('original review lacks an unchanged executor binding; use normal review')
        original_contract = _effective(store, prior)
        old_tasks = {t['id']: t for t in original_contract['execution_dag']['tasks']}
        old_checks = {c['id']: c for c in original_contract['checks']}
        original_results = [e for e in prior if e['type'] == 'agent-result-recorded'
                            and e['payload']['result'].get('role') == 'implementer']
        originals = {e['payload']['result']['task_id']: e for e in original_results}
        impl = originals.get(task_id)
        latest = [e for e in events if e['type'] == 'agent-result-recorded'
                  and e['payload']['result'].get('role') == 'implementer'
                  and e['payload']['result'].get('task_id') == task_id]
        review = approval['payload']['result']
        if (not impl or not latest or impl != latest[-1]
                or review['reviewed_implementer'] != tasks[task_id]['agent_id']
                or any(review[k] != impl['payload']['result'][k] for k in ('base_commit', 'head_commit'))):
            raise CogitoError('retention source no longer binds the Task implementation')
        before_wave = [e for e in original_results if e['sequence'] < original_wave['sequence']]
        if not before_wave:
            raise CogitoError('retention original wave lacks an implementation head')
        base = before_wave[-1]['payload']['result']['head_commit']
        old_evidence = [_evidence(store, prior, p) for p in original_wave['payload']['evidence']]
        old_trees = {e['worktree_binding']['content_tree'] for e in old_evidence}
        if len(old_trees) != 1:
            raise CogitoError('retention original wave content is ambiguous')
        old_tree = next(iter(old_trees))
        touched = _touches(store, worktree, base, head, old_tree, tree)
        # Only exact control artifacts already exempted by atomic cleanliness.
        touched -= {state['package_path'], 'docs/cogito/project-graph.json'}
        protected = [i['path'] for i in package['source_registry']]
        protected += package['human_gate']['high_risk_hotspots']
        protected += [s[k]['path'] for s in package['slices'] for k in ('spec', 'plan')]
        if any(_sensitive(p) or path_allowed(p, protected) for p in touched):
            raise CogitoError('shared configuration or frozen scope changed; use normal review')
        changed_tasks = {key for key, t in tasks.items() if any(path_allowed(p, t['paths']) for p in touched)}
        added = set(new_tasks) - set(old_tasks)
        if not (changed_tasks | added) <= affected:
            raise CogitoError('impact must include every touched and added Task')
        if any(not path_allowed(p, [v for key in affected for v in tasks[key]['paths']]) for p in touched):
            raise CogitoError('correction touched paths outside the assessed Tasks')
        validate_candidate(task_id, tasks, sorted(touched), impact, old_tasks.get(task_id, {}),
                           new_tasks[task_id], old_checks, checks)
        sources.append({'task_id': task_id, 'review': reference(approval), 'implementation': reference(impl),
                        'verification': reference(original_wave), 'base_head': base, 'base_tree': old_tree,
                        'touched_paths': sorted(touched)})
    binding = {'run_id': store.run_id, 'verification': reference(verification),
               'correction': reference(correction), 'effective_contract_hash': state['effective_contract_hash'],
               'runtime': current_runtime, 'head': head, 'tree': tree, 'sources': sources,
               'checks': [{'path': e['evidence_path'], 'hash': hash_json(e)} for e in evidence]}
    return {'impact': deepcopy(impact), 'binding': binding,
            'binding_hash': hash_json({'impact': impact, 'binding': binding})}


def validate_retention(store, request):
    if not isinstance(request, dict) or set(request) != {'impact', 'binding', 'binding_hash', 'reviewer_id', 'assessment'}:
        raise CogitoError('retention requires prepared proposal plus reviewer_id and assessment')
    prepared = prepare_retention(store, request['impact'])
    if any(request[k] != v for k, v in prepared.items()):
        raise CogitoError('retention proposal or verified contents changed; prepare and review again')
    validate_reviewer(request['impact'], request['reviewer_id'], request['assessment'],
                      [t['agent_id'] for t in store.load()['tasks'].values()])
    return deepcopy(request)
