"""Exact, append-only retry relationships for proven pre-execution failures."""
from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json
from cogito_contract_fields import CONTENT_HASH_RE, require_string, require_id, require_integer


FAILURE_EVENT = 'check-preparation-failed'


def reference(event):
    return {'event_sequence': event['sequence'], 'event_hash': event['event_hash']}


def lease_reference(events, task_id):
    leases = [e for e in events if e['type'] == 'task-updated'
              and e['payload'].get('task_id') == task_id and e['payload'].get('status') == 'leased']
    if not leases:
        raise CogitoError('check retry requires a recorded Task lease')
    return reference(leases[-1])


def validate_reference(value):
    if not isinstance(value, dict) or set(value) != {'event_sequence', 'event_hash'}:
        raise CogitoError('check retry requires an exact event reference')
    require_integer(value['event_sequence'], 'check retry sequence', 1, 2**63 - 1)
    require_string(value['event_hash'], 'check retry event hash', CONTENT_HASH_RE)


def validate_failure(state, events, payload):
    fields = {'attempt_id', 'check_id', 'worktree', 'task_id', 'lease', 'request_hash',
              'check_hash', 'effective_contract_hash', 'started_hash', 'reason'}
    if not isinstance(payload, dict) or set(payload) != fields:
        raise CogitoError('invalid pre-execution failure record')
    for key in ('attempt_id', 'worktree', 'reason'):
        require_string(payload[key], 'check preparation ' + key)
    for key in ('check_id', 'task_id'):
        require_id(payload[key], 'check preparation ' + key)
    for key in ('request_hash', 'check_hash', 'effective_contract_hash', 'started_hash'):
        require_string(payload[key], key, CONTENT_HASH_RE)
    validate_reference(payload['lease'])
    task = state['tasks'].get(payload['task_id'], {})
    if (state.get('task_delivery') != 'atomic'
            or state['state'] not in {'executing', 'review-fix', 'technical-correction',
                                      'post-integration-correction', 'human-correction'}
            or task.get('status') != 'running' or task.get('worktree') != payload['worktree']
            or payload['check_id'] not in task.get('check_ids', [])
            or payload['effective_contract_hash'] != state['effective_contract_hash']
            or payload['lease'] != lease_reference(events, payload['task_id'])):
        raise CogitoError('check retry Task lease, checkout or contract changed')
    expected = request_fingerprint('run-check', check_id=payload['check_id'], worktree=payload['worktree'])
    execution = {k: payload[k] for k in ('request_hash', 'check_hash', 'effective_contract_hash')}
    if payload['request_hash'] != expected or payload['started_hash'] != hash_json(execution):
        raise CogitoError('check preparation request binding is invalid')


def source_failure(events, link):
    if not isinstance(link, dict) or set(link) != {'source_action_id', 'replacement_action_id', 'failure'}:
        raise CogitoError('invalid check retry link')
    for key in ('source_action_id', 'replacement_action_id'):
        require_string(link[key], 'check retry ' + key)
    if link['source_action_id'] == link['replacement_action_id']:
        raise CogitoError('check retry needs a fresh replacement action')
    validate_reference(link['failure'])
    matches = [e for e in events if e['type'] == FAILURE_EVENT and reference(e) == link['failure']
               and e['payload']['attempt_id'] == link['source_action_id']]
    if len(matches) != 1:
        raise CogitoError('check retry lacks a proven pre-execution failure')
    return matches[0]['payload']


def validate_link(state, events, link):
    failure = source_failure(events, link)
    validate_failure(state, events, failure)
    for e in events:
        if e['type'] == 'check-evidence-recorded' and e.get('action_id') in {
                link['source_action_id'], link['replacement_action_id']}:
            raise CogitoError('check retry cannot replace a recorded outcome')
        old = e['payload'].get('check_retry') if e['type'] == 'transient-retry' else None
        if old and old['replacement_action_id'] == link['replacement_action_id']:
            raise CogitoError('check retry action is already bound')
        if old and old['source_action_id'] == link['source_action_id']:
            if not any(item['type'] == 'check-evidence-recorded'
                       and item.get('action_id') == old['replacement_action_id'] for item in events):
                raise CogitoError('previous replacement outcome is unresolved')
    return failure
