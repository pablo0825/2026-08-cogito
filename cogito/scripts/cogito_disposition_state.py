"""Pure contracts and append-only projection for cancelled-work dispositions."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError, hash_json
from cogito_contract_fields import RUN_ID_RE, require_paths, require_strings, require_string

TERMINAL = {'completed'}
TRANSITIONS = {
    'disposition-created': ({None}, 'stopping'),
    'disposition-stop-started': ({'stopping'}, 'stopping'),
    'stop-started': ({'stopping'}, 'stopping'),
    'disposition-stopped': ({'stopping'}, 'analyzing'),
    'proposal-prepared': ({'analyzing', 'reviewing', 'awaiting-approval'}, 'reviewing'),
    'proposal-reviewed': ({'reviewing'}, 'awaiting-approval'),
    'proposal-rejected': ({'reviewing', 'awaiting-approval'}, 'analyzing'),
    'disposition-approved': ({'awaiting-approval'}, 'executing'),
    'disposition-pause-started': ({'executing'}, 'pausing'),
    'disposition-pause-saved': ({'pausing'}, 'pausing'),
    'disposition-paused': ({'pausing'}, 'analyzing'),
    'disposition-delivery-released': ({'analyzing', 'reviewing', 'awaiting-approval'}, None),
    'disposition-completed': ({'executing'}, 'completed'),
}
NEXT = {
    'pausing': 'stop the approved follow-up and capture changes before revising the decision',
    'stopping': 'stop executors and preserve stable committed and uncommitted work',
    'analyzing': 'analyze removal, retention or restoration and prepare a disposition proposal',
    'reviewing': 'independently review the current proposal and its affected scope',
    'awaiting-approval': 'request human approval of the exact disposition proposal',
    'executing': 'complete the approved follow-up and its verification and human acceptance',
    'completed': 'disposition is complete; retained history remains available',
}


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise CogitoError(f'{name} must be nonempty text')


def validate_scope(scope: Any) -> None:
    if not isinstance(scope, dict):
        raise CogitoError('impact must be an object')
    require_paths(scope.get('paths'), 'impact.paths')
    require_strings(scope.get('slice_ids'), 'impact.slice_ids')
    _text(scope.get('reason'), 'impact.reason')
    if 'unknown' in scope and type(scope['unknown']) is not bool:
        raise CogitoError('impact.unknown must be boolean')


def validate_proposal(proposal: Any) -> None:
    if not isinstance(proposal, dict):
        raise CogitoError('disposition proposal must be an object')
    allowed = {'action', 'author_id', 'summary', 'impact', 'followup_run_id', 'followup_package_hash',
               'acceptance', 'withdrawal_authorization', 'no_change_evidence', 'human_acceptance'}
    if set(proposal) - allowed:
        raise CogitoError('unknown disposition proposal fields: ' + str(sorted(set(proposal) - allowed)))
    if proposal.get('action') not in {'remove', 'retain', 'restore', 'resume'}:
        raise CogitoError('disposition action must be remove, retain, restore or resume')
    for name in ('author_id', 'summary'):
        _text(proposal.get(name), name)
    validate_scope(proposal.get('impact'))
    acceptance = proposal.get('acceptance')
    if isinstance(acceptance, list):
        require_strings(acceptance, 'acceptance', nonempty=True)
    else:
        _text(acceptance, 'acceptance')
    followup = proposal.get('followup_run_id')
    if followup is not None:
        require_string(followup, 'followup_run_id', RUN_ID_RE)
        digest = proposal.get('followup_package_hash')
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise CogitoError('follow-up must be bound to an exact followup_package_hash')
    if proposal['action'] == 'resume':
        authorization = proposal.get('withdrawal_authorization')
        if isinstance(authorization, dict):
            if authorization.get('authorized') is not True:
                raise CogitoError('resume requires explicit withdrawal authorization')
            _text(authorization.get('reason'), 'withdrawal_authorization.reason')
        else:
            raise CogitoError('resume requires structured explicit withdrawal authorization')


def validate_review(review: Any, proposal: Mapping[str, Any], proposal_hash: str) -> None:
    if not isinstance(review, dict):
        raise CogitoError('review must be an object')
    _text(review.get('reviewer_id'), 'reviewer_id')
    if review['reviewer_id'] == proposal['author_id']:
        raise CogitoError('proposal author cannot independently review it')
    if review.get('proposal_hash') != proposal_hash:
        raise CogitoError('review is not bound to current proposal')
    verdict = review.get('verdict', 'approved')
    if verdict not in {'approved', 'rejected'}:
        raise CogitoError('review verdict must be approved or rejected')
    if verdict == 'approved' and review.get('findings') != []:
        raise CogitoError('resolve review findings before human approval')
    assessment = review.get('assessment', review.get('summary'))
    if isinstance(assessment, dict):
        if not assessment:
            raise CogitoError('review assessment must be nonempty')
        for key, value in assessment.items():
            _text(value, f'assessment.{key}')
    else:
        _text(assessment, 'review assessment')


def project_disposition(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {'state': None, 'proposal_history': [], 'decisions': []}
    for event in events:
        kind, payload = event.get('type'), event.get('payload')
        if kind not in TRANSITIONS or not isinstance(payload, dict):
            raise CogitoError('invalid disposition event')
        allowed, target = TRANSITIONS[kind]
        if result['state'] not in allowed:
            raise CogitoError(f"illegal disposition transition: {result['state']} -> {kind}")
        if kind == 'disposition-created':
            for key in ('disposition_id', 'source_run_id', 'reason'):
                _text(payload.get(key), key)
            result.update(deepcopy(payload))
        elif kind in {'stop-started', 'disposition-stop-started', 'disposition-stopped'}:
            if not isinstance(payload.get('snapshot'), dict):
                raise CogitoError('disposition stopping requires a snapshot')
            result['snapshot'] = deepcopy(payload['snapshot'])
            scope = payload.get('scope', payload['snapshot'].get('scope'))
            if scope is not None:
                validate_scope(scope)
                result['scope'] = deepcopy(scope)
        elif kind == 'disposition-pause-started':
            result['pause_request'] = deepcopy(payload)
        elif kind == 'disposition-pause-saved':
            result['pause_snapshot'] = deepcopy(payload['snapshot'])
        elif kind == 'disposition-paused':
            result.setdefault('pause_history', []).append(deepcopy(payload))
            result.setdefault('retired_followup_run_ids', [])
            retired = payload.get('retired_followup_run_id')
            if retired and retired not in result['retired_followup_run_ids']:
                result['retired_followup_run_ids'].append(retired)
            if payload.get('scope'):
                validate_scope(payload['scope'])
                result.setdefault('additional_scopes', []).append(deepcopy(payload['scope']))
            result.update(approval=None, review=None)
        elif kind == 'proposal-prepared':
            proposal = payload.get('proposal')
            validate_proposal(proposal)
            if payload.get('proposal_hash') != hash_json(proposal):
                raise CogitoError('disposition proposal hash mismatch')
            result['proposal_history'].append(deepcopy(payload))
            result.update(proposal=deepcopy(proposal), proposal_hash=payload['proposal_hash'], review=None, approval=None)
        elif kind == 'proposal-reviewed':
            review = payload.get('review', payload)
            validate_review(review, result['proposal'], result['proposal_hash'])
            if review.get('verdict', 'approved') != 'approved':
                raise CogitoError('only an approved review can advance to human approval')
            result['review'] = deepcopy(review)
        elif kind == 'proposal-rejected':
            if payload.get('proposal_hash', result['proposal_hash']) != result['proposal_hash']:
                raise CogitoError('rejection is not bound to current proposal')
            _text(payload.get('reason'), 'rejection reason')
            result['decisions'].append(deepcopy(payload))
            result.update(rejection=deepcopy(payload), approval=None, review=None)
        elif kind == 'disposition-approved':
            if payload.get('proposal_hash') != result['proposal_hash'] or payload.get('authorized') is not True:
                raise CogitoError('approval requires authorization of the exact current proposal')
            result['approval'] = deepcopy(payload)
            result['decisions'].append(deepcopy(payload))
        elif kind == 'disposition-delivery-released':
            result.setdefault('delivery_releases', []).append(deepcopy(payload))
            target = result['state']
        elif kind == 'disposition-completed':
            if not payload.get('resolution'):
                raise CogitoError('completion requires a recorded resolution')
            result['resolution'] = deepcopy(payload['resolution'])
        result.update(state=target, sequence=event.get('sequence'), last_event_hash=event.get('event_hash'))
    if result['state'] is None:
        raise CogitoError('disposition event history is empty')
    result['next_action'] = NEXT[result['state']]
    return result
