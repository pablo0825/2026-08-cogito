"""Pure review bindings and event projection for additive path corrections."""
from cogito_common import CogitoError, hash_json

EVENTS = {'path-amendment-proposed', 'path-amendment-withdrawn'}
ASSESSMENTS = {'requirements', 'api', 'data_model', 'security', 'slice', 'checks'}


def review_binding(pending, review):
    if not isinstance(review, dict) or set(review) != {'proposal_hash', 'reviewer_id', 'decision', 'assessment', 'findings'}:
        raise CogitoError('path review requires proposal_hash, reviewer_id, assessment and findings')
    if review['decision'] != 'within-approved-scope':
        raise CogitoError('path review must explicitly find the correction within approved scope')
    reviewer = review['reviewer_id']
    if (review['proposal_hash'] != pending['proposal_hash'] or not isinstance(reviewer, str)
            or not reviewer.strip() or reviewer in {pending['author_id'], *pending['executor_ids']}):
        raise CogitoError('path review must bind this proposal and an independent reviewer')
    assessment = review['assessment']
    if not isinstance(assessment, dict) or set(assessment) != ASSESSMENTS or any(
            not isinstance(v, str) or not v.strip() for v in assessment.values()):
        raise CogitoError('path review requires concrete assessments of unchanged scope and checks')
    if not isinstance(review['findings'], list) or review['findings']:
        raise CogitoError('resolve path review findings before applying; revise or withdraw proposal')


def project_path_amendment(state, event, payload):
    if event == 'path-amendment-proposed':
        if state['state'] != 'executing' or not state.get('package_hash'):
            raise CogitoError('path correction requires executing')
        body = {k: v for k, v in payload.items() if k != 'proposal_hash'}
        if hash_json(body) != payload.get('proposal_hash') or payload.get('base_contract_hash') != state['effective_contract_hash']:
            raise CogitoError('invalid path proposal binding')
        for row in payload['amendment']['path_additions']:
            task = state['tasks'].get(row['task_id'])
            if not task or task['status'] not in {'pending', 'leased', 'running', 'blocked'}:
                raise CogitoError('path correction cannot change completed tasks')
        state['path_amendment'] = dict(payload)
        return True
    if event == 'path-amendment-withdrawn':
        pending = state.get('path_amendment')
        if not pending or payload.get('proposal_hash') != pending['proposal_hash']:
            raise CogitoError('withdrawal must identify pending path proposal')
        state.pop('path_amendment', None)
        return True
    return False


def apply_path_projection(state, payload):
    amendment = payload.get('amendment', {})
    if not amendment.get('path_additions'):
        return
    pending = state.get('path_amendment')
    if (not pending or state['state'] != 'executing' or amendment != pending['amendment']
            or pending['base_contract_hash'] != state['effective_contract_hash']):
        raise CogitoError('path additions require the exact pending reviewed proposal')
    review_binding(pending, payload.get('scope_review'))
    for row in amendment['path_additions']:
        task = state['tasks'][row['task_id']]
        if task['status'] not in {'pending', 'leased', 'running', 'blocked'}:
            raise CogitoError('completed task cannot receive path additions')
        for field in ('paths', 'check_ids'):
            task[field] = [*task[field], *(v for v in row[field] if v not in task[field])]
    state.pop('path_amendment', None)


def guard_pending(state, event, payload):
    pending = state.get('path_amendment')
    if not pending or event in EVENTS or (event == 'technical-amendment-added' and payload.get('scope_review')):
        return
    if event in {'block', 'cancel'}:
        return
    task_id = payload.get('task_id') if event == 'task-updated' else payload.get('result', {}).get('task_id')
    if event in {'task-updated', 'agent-result-recorded'} and state['tasks'].get(task_id, {}).get('slice_id') != pending['slice_id']:
        return
    raise CogitoError('path amendment review pending; revise, review or withdraw before continuing this operation')
