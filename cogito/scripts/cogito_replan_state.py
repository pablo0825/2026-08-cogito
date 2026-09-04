"""Independent, append-only replanning lifecycle; never rewrites a run."""
from __future__ import annotations
from typing import Any, Mapping, Sequence
from cogito_common import CogitoError, hash_json

TERMINAL = {'completed', 'abandoned', 'disposition'}
TRANSITIONS = {
    'replan-created': ({None}, 'stopping'),
    'replan-stopped': ({'stopping'}, 'analyzing'),
    'proposal-prepared': ({'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}, 'reviewing'),
    'proposal-reviewed': ({'reviewing'}, 'awaiting-approval'),
    'proposal-rejected': ({'reviewing', 'awaiting-approval'}, 'awaiting-decision'),
    'successor-approved': ({'awaiting-approval'}, 'ready-for-handoff'),
    'handoff-started': ({'ready-for-handoff'}, 'handing-off'),
    'handoff-start-isolated': ({'handing-off'}, 'handing-off'),
    'handoff-start-validated': ({'handing-off'}, 'handing-off'),
    'work-transfer-planned': ({'handing-off'}, 'handing-off'),
    'work-transferred': ({'handing-off'}, 'handing-off'),
    'handoff-completed': ({'handing-off'}, 'completed'),
    'replan-abandon-started': ({'stopping', 'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}, 'resolving-decision'),
    'replan-abandoned': ({'resolving-decision'}, 'abandoned'),
    'replan-disposition-started': ({'stopping', 'analyzing', 'reviewing', 'awaiting-approval',
        'awaiting-decision', 'ready-for-handoff', 'handing-off', 'resolving-decision'}, 'disposition'),
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
    'disposition': 'follow the linked disposition; this replan cannot resume handoff',
}

def project_replan(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {'state': None, 'transfers': {}, 'transfer_plans': {}}
    for event in events:
        kind, payload = event.get('type'), event.get('payload')
        if kind in {'handoff-tool-proposed', 'handoff-tool-reviewed', 'handoff-tool-approved', 'handoff-tool-rejected'}:
            from cogito_replan_handoff_tool import validate_proposal
            from cogito_replan_toolchain_rules import validate_review, text
            if result.get('state') != 'handing-off' or not isinstance(payload, dict):
                raise CogitoError('handoff tool repair requires handing-off state')
            if kind == 'handoff-tool-proposed':
                proposal = payload.get('proposal'); validate_proposal(proposal, result)
                if payload.get('proposal_hash') != hash_json(proposal):
                    raise CogitoError('handoff tool proposal hash mismatch')
                result.update(handoff_tool_proposal=proposal,
                              handoff_tool_proposal_hash=payload['proposal_hash'],
                              handoff_tool_review=None, handoff_tool_status='reviewing')
            elif kind == 'handoff-tool-reviewed':
                if result.get('handoff_tool_status') != 'reviewing':
                    raise CogitoError('handoff tool review requires a current proposal')
                validate_review(payload, result['handoff_tool_proposal'], result['handoff_tool_proposal_hash'])
                result.update(handoff_tool_review=payload, handoff_tool_status='awaiting-approval')
            elif kind == 'handoff-tool-approved':
                if result.get('handoff_tool_status') != 'awaiting-approval' or payload.get('proposal_hash') != result['handoff_tool_proposal_hash']:
                    raise CogitoError('handoff tool approval requires exact reviewed proposal')
                text(payload.get('approver_id'), 'approver_id')
                result.update(runtime_toolchain={'proposal_hash': payload['proposal_hash'],
                    'proposal': result['handoff_tool_proposal'], 'review': result['handoff_tool_review'],
                    'approver_id': payload['approver_id']}, handoff_tool_status='approved')
            else:
                if result.get('handoff_tool_status') not in {'reviewing', 'awaiting-approval'} or payload.get('proposal_hash') != result.get('handoff_tool_proposal_hash'):
                    raise CogitoError('handoff tool rejection must reference pending proposal')
                text(payload.get('reason'), 'reason'); result.update(handoff_tool_status='rejected', handoff_tool_rejection=payload)
            result.update(sequence=event.get('sequence'), last_event_hash=event.get('event_hash'))
            continue
        if kind in {'toolchain-proposed', 'toolchain-reviewed', 'toolchain-approved', 'toolchain-rejected'}:
            from cogito_replan_toolchain_rules import project_toolchain
            if not isinstance(payload, dict):
                raise CogitoError('invalid toolchain event payload')
            project_toolchain(result, kind, payload)
            result.update(sequence=event.get('sequence'), last_event_hash=event.get('event_hash'))
            continue
        if ((result.get('toolchain_status') in {'reviewing', 'awaiting-approval'}
             or result.get('handoff_tool_status') in {'reviewing', 'awaiting-approval'}) and kind in {
                'proposal-prepared', 'proposal-reviewed', 'successor-approved', 'handoff-started',
                'work-transfer-planned', 'work-transferred', 'handoff-completed', 'replan-abandon-started'}):
            raise CogitoError('finish or reject the pending toolchain proposal before advancing the RP')
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
        elif kind == 'handoff-start-isolated':
            result['start_isolation'] = payload
        elif kind == 'handoff-start-validated':
            result['start_validation'] = payload
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
        elif kind == 'replan-disposition-started':
            disposition_id = payload.get('disposition_id')
            if not isinstance(disposition_id, str) or not disposition_id.startswith('DP-'):
                raise CogitoError('replan disposition requires a DP-* identifier')
            result['disposition_id'] = disposition_id
        result.update(state=target, sequence=event.get('sequence'), last_event_hash=event.get('event_hash'))
    if result['state'] is None:
        raise CogitoError('replan event history is empty')
    result['next_action'] = NEXT[result['state']]
    if result['state'] in {'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'} and result.get('toolchain_status') == 'reviewing':
        result['next_action'] = 'independently review the exact toolchain proposal; product RP remains paused'
    elif result['state'] in {'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'} and result.get('toolchain_status') == 'awaiting-approval':
        result['next_action'] = 'obtain human approval of the exact toolchain proposal hash'
    return result
