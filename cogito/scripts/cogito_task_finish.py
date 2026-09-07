"""Two fixed receipt operations reuse the existing Gate through a preflight store."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, cast

from cogito_actions import (fixed_action_authority, fixed_action_path, fixed_steps_done,
    pending_fixed_action, request_fingerprint, require_same_request)
from cogito_common import CogitoError, atomic_create_json, hash_json, load_json
from cogito_event_repository import EventRepository, EventSnapshot
from cogito_replan_lock import run_mutation

if TYPE_CHECKING:
    from cogito_run_store import RunStore


class PreflightEvents(EventRepository):
    """Use the normal validation and projection without publishing any receipts."""
    def __init__(self, store):
        super().__init__(store.events_path, store.state_path, store.workflow)
        self.events = deepcopy(store._events.read())
        self.steps: list[dict[str, Any]] = []

    def read(self):
        return deepcopy(self.events)

    def refresh_cache(self, projection):
        pass

    def append(self, event, *, expected_previous_hash=None):
        previous = self.events[-1]['event_hash']
        if expected_previous_hash is not None and previous != expected_previous_hash:
            raise CogitoError('preflight history changed')
        body = {**deepcopy(event), 'sequence': len(self.events) + 1,
                'previous_event_hash': previous, 'timestamp': 'preflight'}
        body['event_hash'] = hash_json(body)
        from cogito_projection import project_events
        state = project_events([*self.events, body], self.workflow)
        self.events.append(body)
        self.steps.append(deepcopy(dict(event)))
        return state


def preflight_store(store):
    from cogito_run_store import RunStore
    events = PreflightEvents(store)
    preview = RunStore(store.root, store.run_id, store.workflow, event_repository=events,
                       git_repository=store._git_repo)
    return preview, events


def load_fixed_request(store, operation, request, action_id):
    if not isinstance(action_id, str) or not action_id.strip():
        raise CogitoError('fixed operation requires an action_id')
    fingerprint = request_fingerprint(operation, request=request)
    path = fixed_action_path(store.root, store.run_id, action_id)
    pending = pending_fixed_action(store.root, store.run_id)
    if pending and (pending['action_id'] != action_id or pending['operation'] != operation):
        raise CogitoError('finish the prior fixed operation with its original action_id')
    if path.exists():
        binding = load_json(path)
        require_same_request(binding, fingerprint, action_id)
        return binding
    if any(e.get('action_id') == action_id for e in store._events.read()):
        raise CogitoError('action_id was already used by another operation')
    return None


def save_fixed_request(store, operation, request, action_id, prepared, steps):
    if not steps:
        raise CogitoError('fixed operation has no pending receipt')
    binding = {'operation': operation, 'request': deepcopy(request), 'action_id': action_id,
               'request_hash': request_fingerprint(operation, request=request),
               'base_event_hash': store.load()['last_event_hash'],
               'effective_contract_hash': store.load()['effective_contract_hash'],
               'prepared': prepared, 'steps': steps}
    path = fixed_action_path(store.root, store.run_id, action_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not atomic_create_json(path, binding):
        raise CogitoError('fixed action was concurrently created; retry the same action')
    return binding


def check_fixed_history(store, binding):
    events = store._events.read()
    if fixed_steps_done(binding, events):
        return True
    base = next((i for i, e in enumerate(events) if e['event_hash'] == binding['base_event_hash']), None)
    if base is None:
        raise CogitoError('fixed action baseline event is missing')
    tail = [e for e in events[base + 1:] if e['type'] not in {'block', 'resume'}]
    if len(tail) >= len(binding['steps']) or any(
        any(e.get(k) != step.get(k) for k in ('type', 'payload', 'action_id', 'request_hash'))
        for e, step in zip(tail, binding['steps'])
    ):
        raise CogitoError('fixed action history changed; inspect before recovery')
    return False


def select_task_evidence(store, task):
    """Pick the latest recorded attempt per targeted ID; validation decides validity."""
    snapshot = store._events.snapshot()
    # Unknown attempts must be resolved even if an older matching check passed.
    completed = {e.get('action_id') for e in snapshot.events if e['type'] == 'check-evidence-recorded'}
    from cogito_check_retry import superseded_attempts
    completed.update(superseded_attempts(store, snapshot.events))
    for path in (store.run_dir / 'check-actions').glob('*/started.json'):
        request = load_json(path.parent / 'request.json')
        if request['action_id'] not in completed:
            raise CogitoError('resolve unfinished controlled check before task-finish: ' + request['action_id'])
    latest: dict[str, tuple[datetime, str]] = {}
    for event in snapshot.events:
        if event['type'] != 'check-evidence-recorded':
            continue
        payload = event['payload']
        if payload['check_id'] not in task['check_ids']:
            continue
        expected = request_fingerprint('run-check', check_id=payload['check_id'],
                                       worktree=str(Path(task['worktree']).resolve()))
        if event.get('request_hash') != expected:
            continue
        evidence = load_json(Path(payload['evidence_path']))
        if hash_json(evidence) != payload['evidence_hash']:
            raise CogitoError('controlled evidence differs from its recorded hash: ' + payload['check_id'])
        try:
            started = datetime.fromisoformat(evidence['started_at'])
            if started.tzinfo is None:
                raise ValueError('missing timezone')
        except (KeyError, TypeError, ValueError) as exc:
            raise CogitoError('controlled check has invalid start time') from exc
        previous = latest.get(payload['check_id'])
        if previous and previous[0] == started:
            raise CogitoError('ambiguous controlled check attempts: ' + payload['check_id'])
        if previous is None or previous[0] < started:
            latest[payload['check_id']] = (started, evidence['evidence_path'])
    missing = [key for key in task['check_ids'] if key not in latest]
    if missing:
        raise CogitoError('missing controlled checks: ' + ', '.join(missing))
    return [latest[key][1] for key in task['check_ids']]


class TaskFinishMixin:
    @run_mutation
    def finish_task(self, task_id: str, request: Mapping[str, Any], action_id: str):
        store = cast('RunStore', self)
        if not isinstance(request, dict) or set(request) != {'risks'}:
            raise CogitoError('task-finish input must contain only risks')
        if not isinstance(request['risks'], list) or any(not isinstance(r, str) for r in request['risks']):
            raise CogitoError('task-finish risks must be an array of strings')
        supplied = {'task_id': task_id, **request}
        binding = load_fixed_request(store, 'task-finish', supplied, action_id)
        if binding is None:
            state = store.load()
            if store.approved_package().get('task_delivery') != 'atomic':
                raise CogitoError('task-finish requires an atomic Development Package')
            task = state['tasks'].get(task_id)
            if not task or task['status'] != 'running':
                raise CogitoError('task-finish requires a running Task')
            worktree = Path(task['worktree'])
            head = store._git_at(worktree, 'rev-parse', 'HEAD')
            paths = store._git_at(worktree, 'diff', '--name-only', '--no-renames', '--no-ext-diff',
                                  '-z', task['base_commit'], head, '--').split('\0')
            result = {'schema_version': '3.0', 'run_id': store.run_id, 'task_id': task_id,
                      'agent_id': task['agent_id'], 'role': 'implementer', 'status': 'complete',
                      'base_commit': task['base_commit'], 'head_commit': head,
                      'changed_paths': list(filter(None, paths)), 'evidence': select_task_evidence(store, task),
                      'risks': deepcopy(request['risks']), 'requested_transition': 'verifying'}
            prior = [r for r in state['agent_results'] if r['task_id'] == task_id and r['role'] == 'implementer']
            reuse = bool(prior and prior[-1] == result)
            if prior and prior[-1]['status'] == 'complete' and not reuse:
                raise CogitoError('recorded Result differs; cannot replace it through task-finish')
            preview, receipts = preflight_store(store)
            result_action = 'task-finish-result:' + hash_json(action_id)
            if not reuse:
                preview.submit_agent_result(result, result_action)
            preview.update_task(task_id, 'complete', task['agent_id'], action_id)
            binding = save_fixed_request(store, 'task-finish', supplied, action_id,
                {'result': result, 'reuse_result': reuse, 'result_action': result_action}, receipts.steps)
        result = binding['prepared']['result']
        if not check_fixed_history(store, binding):
            state = store.load()
            if state['effective_contract_hash'] != binding['effective_contract_hash']:
                raise CogitoError('task-finish contract changed since preflight')
            store._validate_atomic_result(result, state['tasks'][task_id], store._events.snapshot())
            with fixed_action_authority(store.root, store.run_id, action_id):
                if not binding['prepared']['reuse_result']:
                    store.submit_agent_result(result, binding['prepared']['result_action'])
                store.update_task(task_id, 'complete', result['agent_id'], action_id)
        return {'operation': 'task-finish', 'task_id': task_id, 'status': 'complete',
                'commit_id': result['head_commit'], 'evidence': result['evidence'],
                'next': store.next_action()}
