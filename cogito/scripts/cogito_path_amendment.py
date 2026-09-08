"""Same-run path corrections with exact independent review and frozen inputs."""
from __future__ import annotations

from typing import TYPE_CHECKING, cast
from pathlib import Path

if TYPE_CHECKING:
    from cogito_run_store import RunStore
from contextlib import contextmanager

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json, atomic_create_json, atomic_write_json, load_json
from cogito_evidence_binding import capture_index_and_worktree_trees, working_tree_changed_paths
from cogito_path_amendment_state import path_targets, review_binding
from cogito_replan_lock import run_mutation


def pending_from_events(root, run_id):
    from cogito_events import read_events
    pending = None
    for event in read_events(Path(root) / '.cogito/runs' / run_id / 'events.jsonl'):
        if event['type'] == 'path-amendment-proposed':
            pending = event['payload']
        elif event['type'] == 'path-amendment-withdrawn' or (event['type'] == 'technical-amendment-added' and event['payload'].get('scope_review')):
            from cogito_execution_registry import _load, _path
            data = _load(_path(root, run_id), run_id)
            digest = event['payload'].get('scope_review', event['payload'])['proposal_hash']
            if digest in data.get('path_generations', []):
                pending = None
            elif pending:
                pending = {**pending, 'recovery': {
                    'operation': 'withdraw' if event['type'] == 'path-amendment-withdrawn' else 'review',
                    'action_id': event.get('action_id'),
                    'input': event['payload'].get('scope_review', event['payload']),
                }}
    return pending


def guard_executor_admission(root, run_id, identifier):
    pending = pending_from_events(root, run_id)
    if pending and identifier not in pending['unaffected_executor_ids']:
        raise CogitoError('path amendment review pending; affected executor and checks cannot start')


@contextmanager
def stopped_executors(store, executor_ids, active_ids):
    from cogito_execution_registry import _locked, _observe
    with _locked(store.root, store.run_id) as (path, data):
        observed = _observe(data, allow_external_receipts=True)
        if not set(active_ids) <= set(observed['entries']):
            raise CogitoError('register and stop affected Workers before proposing path correction')
        worker_ids = {t.get('agent_id') for t in store.load()['tasks'].values()}
        for identifier, entry in observed['entries'].items():
            if (identifier in executor_ids or identifier not in worker_ids) and not entry['terminated']:
                raise CogitoError('affected Workers and controlled checks must have stopped')
        yield path, data


class PathAmendmentMixin:
    def _validate_path_files(self, worktree):
        store = cast("RunStore", self)
        worktree = Path(worktree).resolve()
        for event in store._events.read():
            if event['type'] != 'technical-amendment-added':
                continue
            for row in event['payload']['amendment'].get('path_additions', []):
                for relative in row['paths']:
                    path = Path(worktree) / relative
                    if path.resolve() != path or path.is_dir():
                        raise CogitoError('amended paths must remain exact files without symlinks')

    def _path_inputs(self, amendment):
        store = cast("RunStore", self)
        from cogito_contracts import materialize_contract_with_limits, path_allowed
        current = store.load()
        if pending_from_events(store.root, store.run_id) and not current.get('path_amendment'):
            raise CogitoError('retry the applied path review to complete executor recovery first')
        prior = [e['payload']['amendment'] for e in store._events.read() if e['type'] == 'technical-amendment-added']
        effective = store.effective_package()
        materialize_contract_with_limits(store.approved_package(), [*prior, amendment], store.workflow['limits'])
        if not amendment.get('path_additions'):
            raise CogitoError('path correction requires path_additions')
        target_tasks = path_targets(current, amendment)
        ids = [r['task_id'] for r in amendment['path_additions']]
        slice_id = target_tasks[ids[0]]['slice_id']
        finding_binding = {}
        if current['state'] == 'review-fix':
            starts = [e for e in store._events.read() if e['type'] == 'review-fix-required']
            if not starts or current['tasks'][starts[-1]['payload']['review_task_id']]['slice_id'] != slice_id:
                raise CogitoError('review path correction must belong to the current finding Slice')
            finding_binding = {'review_finding': starts[-1]['payload']}
        if current.get('path_amendment') and current['path_amendment']['slice_id'] != slice_id:
            raise CogitoError('withdraw the existing Slice proposal before correcting another Slice')
        tasks = {k: v for k, v in target_tasks.items() if v.get('slice_id') == slice_id}
        owner = next(s for s in effective['slices'] if s['id'] == slice_id)
        declared = store.root / owner['worker']['worktree']
        if declared.resolve() != declared:
            raise CogitoError('path correction worktree must not traverse symlinks')
        worktree, branch = store._task_worktree(target_tasks[ids[0]], effective)
        if worktree.resolve() != worktree:
            raise CogitoError('path correction worktree must not traverse symlinks')
        binding = None
        if worktree.exists():
            if store._git_at(worktree, 'branch', '--show-current') != branch:
                raise CogitoError('path correction checkout branch changed')
            active = [t for t in tasks.values() if t['status'] in {'leased', 'running', 'blocked'} and t.get('base_commit')]
            allowed = [p for t in active for p in t['paths']]
            head = store._git_at(worktree, 'rev-parse', 'HEAD')
            base = active[0]['base_commit'] if active else head
            changes = working_tree_changed_paths(worktree, base)
            index, tree = capture_index_and_worktree_trees(worktree)
            for value in (index, tree):
                changes.update(filter(None, store._git_at(worktree, 'diff', '--name-only',
                    '--no-renames', '--no-ext-diff', '-z', base, value, '--').split('\0')))
            controls = {current.get("package_path"), "docs/cogito/project-graph.json"}
            if any(not path_allowed(p, allowed) for p in changes if p not in controls and not p.startswith('.cogito/')):
                raise CogitoError('checkout already contains changes outside the existing Task paths')
            binding = dict(head=head, index_tree=index, content_tree=tree)
            if current['state'] == 'review-fix':
                store._validate_review_content(worktree, tree)
        for row in amendment['path_additions']:
            for relative in row['paths']:
                path = worktree / relative
                if path.exists() and not store._git_at(worktree, 'ls-tree', 'HEAD', '--', relative):
                    raise CogitoError('checkout already contains a file outside its authorized paths')
                if path.resolve() != path or path.is_dir():
                    raise CogitoError('path additions must identify exact files without symlinks')
        executors = sorted({t['agent_id'] for t in tasks.values() if t.get('agent_id')})
        active_ids = sorted({t['agent_id'] for t in tasks.values() if t['status'] in {'leased', 'running'}})
        return current, dict(slice_id=slice_id, tasks=tasks, worktree=str(worktree), binding=binding,
                             executor_ids=executors, active_executor_ids=active_ids, **finding_binding)

    @run_mutation
    def path_amendment_propose(self, request, action_id):
        store = cast("RunStore", self)
        if not isinstance(request, dict) or set(request) != {'amendment', 'author_id'} or not isinstance(request['author_id'], str) or not request['author_id'].strip():
            raise CogitoError('path proposal requires amendment and author_id')
        fingerprint = request_fingerprint('amend-paths-propose', request=request)
        replay = store._replay(action_id, 'path-amendment-proposed', fingerprint)
        if replay is not None:
            return replay
        from cogito_disposition_lock import check_disposition_fence
        current, inputs = store._path_inputs(request['amendment'])
        check_disposition_fence(store, 'add_amendment', (request['amendment'],), {})
        with stopped_executors(store, inputs['executor_ids'], inputs['active_executor_ids']):
            unaffected = sorted({t['agent_id'] for t in current['tasks'].values()
                                 if t.get('agent_id') and t.get('slice_id') != inputs['slice_id']} - set(inputs['executor_ids']))
            proposal = dict(**request, **inputs, base_contract_hash=current['effective_contract_hash'],
                            base_event_hash=current['last_event_hash'],
                            unaffected_executor_ids=unaffected)
            proposal['proposal_hash'] = hash_json(proposal)
            return store.record('path-amendment-proposed', proposal, action_id, store._GATE_AUTHORITY, request_hash=fingerprint)

    @run_mutation
    def path_amendment_review(self, review, action_id):
        store = cast("RunStore", self)
        fingerprint = request_fingerprint('amend-paths-review', review=review)
        replay = store._replay(action_id, 'technical-amendment-added', fingerprint)
        if replay is not None:
            store._renew_path_executors(review['proposal_hash'])
            return replay
        pending = store.load().get('path_amendment')
        if not pending:
            raise CogitoError('no pending path amendment')
        review_binding(pending, review)
        current, inputs = store._path_inputs(pending['amendment'])
        if pending['base_contract_hash'] != current['effective_contract_hash'] or any(pending[k] != v for k, v in inputs.items()):
            raise CogitoError('path proposal inputs changed; propose and review again')
        from cogito_disposition_lock import check_disposition_fence
        check_disposition_fence(store, 'add_amendment', (pending['amendment'],), {})
        with stopped_executors(store, inputs['executor_ids'], inputs['active_executor_ids']) as registry:
            from cogito_contracts import materialize_contract_with_limits
            prior = [e['payload']['amendment'] for e in store._events.read() if e['type'] == 'technical-amendment-added']
            effective = materialize_contract_with_limits(store.approved_package(), [*prior, pending['amendment']], store.workflow['limits'])
            state = store.record('technical-amendment-added', dict(amendment=pending['amendment'],
                effective_contract_hash=effective['effective_contract_hash'], scope_review=review),
                action_id, store._GATE_AUTHORITY, request_hash=fingerprint)
            store._renew_path_executors(pending['proposal_hash'], registry)
        return state

    def _renew_path_executors(self, proposal_hash, registry=None):
        store = cast("RunStore", self)
        from cogito_execution_registry import _locked
        proposal = next(e['payload'] for e in store._events.read()
                        if e['type'] == 'path-amendment-proposed' and e['payload']['proposal_hash'] == proposal_hash)
        from contextlib import nullcontext
        with (nullcontext(registry) if registry is not None else _locked(store.root, store.run_id)) as (path, data):
            generations = data.setdefault('path_generations', [])
            if proposal_hash in generations:
                return
            entries = {key: data['entries'][key] for key in proposal['executor_ids'] if key in data['entries']}
            archive = store.run_dir / 'execution-generations' / ('path-' + proposal_hash + '.json')
            if not atomic_create_json(archive, entries) and load_json(archive) != entries:
                raise CogitoError('path executor archive changed')
            for key in entries:
                del data['entries'][key]
            generations.append(proposal_hash)
            atomic_write_json(path, data)

    @run_mutation
    def path_amendment_withdraw(self, request, action_id):
        store = cast("RunStore", self)
        if not isinstance(request, dict) or set(request) != {'proposal_hash', 'reason'} or not isinstance(request['reason'], str) or not request['reason'].strip():
            raise CogitoError('withdrawal requires proposal_hash and reason')
        fingerprint = request_fingerprint('amend-paths-withdraw', request=request)
        replay = store._replay(action_id, 'path-amendment-withdrawn', fingerprint)
        if replay is not None:
            store._renew_path_executors(request['proposal_hash'])
            return replay
        pending = store.load().get('path_amendment')
        if not pending or pending['proposal_hash'] != request['proposal_hash']:
            raise CogitoError('withdrawal must identify the pending proposal')
        with stopped_executors(store, pending['executor_ids'], pending['active_executor_ids']) as registry:
            state = store.record('path-amendment-withdrawn', request, action_id, store._GATE_AUTHORITY, request_hash=fingerprint)
            store._renew_path_executors(request['proposal_hash'], registry)
        return state
