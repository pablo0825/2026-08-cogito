"""Collect immutable attempt files; derive supersession only after success."""
from pathlib import Path

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json, load_json
from cogito_check_retry_rules import (FAILURE_EVENT, lease_reference, reference, source_failure,
                                      validate_failure, validate_link)
from cogito_evidence_contract import validate_check_evidence


def _attempt_dir(store, action_id):
    return store.run_dir / 'check-actions' / hash_json(action_id)


def check_source_files(store, failure):
    directory = _attempt_dir(store, failure['attempt_id'])
    request = load_json(directory / 'request.json')
    started = load_json(directory / 'started.json')
    expected = {k: failure[k] for k in ('request_hash', 'check_hash', 'effective_contract_hash')}
    if (request != {'action_id': failure['attempt_id'], 'request_hash': failure['request_hash']}
            or started != expected or hash_json(started) != failure['started_hash']):
        raise CogitoError('pre-execution attempt files changed')


def failure_payload(store, state, check_id, worktree, action_id, execution, reason):
    tasks = [t for t in state['tasks'].values() if t.get('status') == 'running'
             and t.get('worktree') == str(worktree) and check_id in t.get('check_ids', [])]
    if state.get('task_delivery') != 'atomic' or len(tasks) != 1:
        return None  # Other phases retain the existing unknown-outcome policy.
    return {'attempt_id': action_id, 'check_id': check_id, 'worktree': str(worktree),
            'task_id': tasks[0]['id'], 'lease': lease_reference(store._events.read(), tasks[0]['id']),
            **execution, 'started_hash': hash_json(execution), 'reason': reason}


def prepare_link(store, old, new, *, read_only=False):
    events = store._events.read()
    failures = [e for e in events if e['type'] == FAILURE_EVENT and e['payload']['attempt_id'] == old]
    if len(failures) != 1:
        raise CogitoError('check retry requires a proven pre-execution failure; historical unknown attempts remain blocked')
    link = {'source_action_id': old, 'replacement_action_id': new, 'failure': reference(failures[0])}
    failure = validate_link(store.load(), events, link)
    check_source_files(store, failure)
    if _attempt_dir(store, new).exists() or any(e.get('action_id') == new for e in events):
        raise CogitoError('replacement check action must be unused')
    _check_contract(store, failure)
    previous = [e for e in events if e['type'] == 'transient-retry'
                and e['payload'].get('check_retry', {}).get('source_action_id') == old]
    if previous:
        prior = previous[-1]
        item = replacement_evidence(store, events, prior)
        if item is None or item['passed'] is not False:
            raise CogitoError('previous replacement must have a recorded failed outcome')
        from cogito_execution_registry import snapshot, observe_read_only
        target = prior['payload']['check_retry']['replacement_action_id']
        record_id = failure['check_id'] + '-' + hash_json({'action_id': target})[:16]
        observe = observe_read_only if read_only else snapshot
        entry = observe(store.root, store.run_id)['entries'].get(record_id, {})
        if not entry.get('terminated'):
            raise CogitoError('previous replacement executor is not proven stopped')
    return link


def _check_contract(store, failure):
    checks = {c['id']: c for c in store.effective_package()['checks']}
    if hash_json(checks.get(failure['check_id'])) != failure['check_hash']:
        raise CogitoError('retry check definition changed')


def validate_replacement(store, check_id, worktree, action_id):
    events = store._events.read()
    for event in events:
        link = event['payload'].get('check_retry') if event['type'] == 'transient-retry' else None
        if link and link['replacement_action_id'] == action_id:
            failure = source_failure(events, link)
            validate_failure(store.load(), events, failure)
            check_source_files(store, failure)
            _check_contract(store, failure)
            if request_fingerprint('run-check', check_id=check_id, worktree=str(worktree)) != failure['request_hash']:
                raise CogitoError('replacement check does not match its registered retry')


def replacement_evidence(store, events, retry):
    link = retry['payload']['check_retry']
    failure = source_failure(events, link)
    target = link['replacement_action_id']
    matches = [e for e in events if e['type'] == 'check-evidence-recorded'
               and e.get('action_id') == target and e['sequence'] > retry['sequence']]
    if not matches:
        return None
    success = matches[-1]
    directory = _attempt_dir(store, target)
    if (load_json(directory / 'request.json') != {
            'action_id': target, 'request_hash': failure['request_hash']}
            or load_json(directory / 'started.json') != {
                k: failure[k] for k in ('request_hash', 'check_hash', 'effective_contract_hash')}):
        raise CogitoError('replacement attempt files changed')
    payload = success['payload']
    path = Path(payload['evidence_path']).resolve()
    try:
        path.relative_to((store.run_dir / 'evidence').resolve())
    except ValueError as exc:
        raise CogitoError('retry evidence escaped this Run') from exc
    item = load_json(path)
    validate_check_evidence(item)
    if hash_json(item) != payload['evidence_hash']:
        raise CogitoError('retry evidence changed')
    if (success.get('request_hash') != failure['request_hash']
            or item['run_id'] != store.run_id
            or item['check_id'] != failure['check_id']
            or item['check_hash'] != failure['check_hash']
            or item['effective_contract_hash'] != failure['effective_contract_hash']):
        raise CogitoError('retry evidence does not match the registered replacement')
    return item


def superseded_attempts(store, events):
    """A retry chain resolves only when its terminal replacement has valid success."""
    resolved = set()
    for event in reversed(events):
        link = event['payload'].get('check_retry') if event['type'] == 'transient-retry' else None
        if not link:
            continue
        failure = source_failure(events, link)
        check_source_files(store, failure)
        if link['replacement_action_id'] in resolved:
            resolved.add(link['source_action_id'])
            continue
        item = replacement_evidence(store, events, event)
        if item is not None and item['passed'] is True:
            resolved.add(link['source_action_id'])
    return resolved
