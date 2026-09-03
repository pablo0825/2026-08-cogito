"""Independent, append-only replanning lifecycle; never rewrites a run."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from cogito_common import CogitoError

TERMINAL = {'completed', 'abandoned'}
TRANSITIONS = {
    'replan-created': ({None}, 'stopping'),
    'replan-stopped': ({'stopping'}, 'analyzing'),
    'proposal-prepared': ({'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}, 'reviewing'),
    'proposal-reviewed': ({'reviewing'}, 'awaiting-approval'),
    'proposal-rejected': ({'reviewing', 'awaiting-approval'}, 'awaiting-decision'),
    'successor-approved': ({'awaiting-approval'}, 'ready-for-handoff'),
    'handoff-started': ({'ready-for-handoff'}, 'handing-off'),
    'work-transfer-planned': ({'handing-off'}, 'handing-off'),
    'work-transferred': ({'handing-off'}, 'handing-off'),
    'handoff-completed': ({'handing-off'}, 'completed'),
    'replan-abandon-started': ({'stopping', 'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}, 'resolving-decision'),
    'replan-abandoned': ({'resolving-decision'}, 'abandoned'),
}
NEXT = {
    'stopping': 'stop executors, collect executor receipts and capture stable snapshots',
    'analyzing': 'clarify changed requirements, prepare successor Package and impact manifest',
    'reviewing': 'independent reviewer checks impact, reuse and revalidation evidence',
    'awaiting-approval': 'present exact proposal hash, differences, cost and reuse manifest for human approval',
    'awaiting-decision': 'remain paused; ask for another proposal, original-contract resumption or cancellation',
    'ready-for-handoff': 'apply approved handoff; successor dispatch remains fenced',
    'handing-off': 'reconcile recorded checkpoints and continue the same approved handoff',
    'completed': 'continue the successor run through its regular Gates',
    'resolving-decision': 'reconcile the authorized source disposition before releasing the fence',
    'abandoned': 'follow the explicitly selected original-run disposition',
}

def project_replan(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {'state': None, 'transfers': {}, 'transfer_plans': {}}
    for event in events:
        kind, payload = event.get('type'), event.get('payload')
        if kind not in TRANSITIONS or not isinstance(payload, dict):
            raise CogitoError('invalid replan event')
        allowed, target = TRANSITIONS[kind]
        if result['state'] not in allowed:
            raise CogitoError(f"illegal replan transition: {result['state']} -> {kind}")
        if kind == 'replan-created':
            for key in ('replan_id', 'source_run_id', 'successor_run_id', 'source_package_hash', 'reason'):
                if not isinstance(payload.get(key), str) or not payload[key]:
                    raise CogitoError(f'replan-created requires {key}')
            result.update(payload)
        elif kind == 'replan-stopped':
            result['snapshot'] = payload['snapshot']
        elif kind == 'proposal-prepared':
            result.update(proposal=payload['proposal'], proposal_hash=payload['proposal_hash'], review=None)
        elif kind == 'proposal-reviewed':
            if payload['proposal_hash'] != result['proposal_hash']:
                raise CogitoError('review is not bound to current proposal')
            result['review'] = payload
        elif kind == 'proposal-rejected':
            result['rejection'] = payload
        elif kind == 'successor-approved':
            if payload['proposal_hash'] != result['proposal_hash']:
                raise CogitoError('approval is not bound to current proposal')
            result['approval'] = payload
        elif kind == 'handoff-started':
            result['handoff'] = payload
        elif kind == 'work-transfer-planned':
            result['transfer_plans'][payload['task_id']] = payload
        elif kind == 'work-transferred':
            key = payload['task_id']
            if key in result['transfers']:
                raise CogitoError('duplicate work transfer')
            result['transfers'][key] = payload
        elif kind == 'replan-abandon-started':
            result['decision'] = payload
        elif kind == 'replan-abandoned':
            result['disposition'] = payload['disposition']
        result.update(state=target, sequence=event.get('sequence'), last_event_hash=event.get('event_hash'))
    if result['state'] is None:
        raise CogitoError('replan event history is empty')
    result['next_action'] = NEXT[result['state']]
    return result
