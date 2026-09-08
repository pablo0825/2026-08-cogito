"""Pure review bindings and event projection for additive path corrections."""
from cogito_common import CogitoError, hash_json

EVENTS = {'path-amendment-proposed', 'path-amendment-withdrawn'}
ASSESSMENTS = {'requirements', 'api', 'data_model', 'security', 'slice', 'checks'}


def path_targets(state, amendment):
    """Resolve unfinished execution tasks or new review correction tasks."""
    from cogito_path_amendment_contract import validate_path_additions_shape
    validate_path_additions_shape(amendment)
    added = amendment.get('added_tasks', [])
    if state['state'] == 'review-fix':
        if not added:
            raise CogitoError('review path correction requires new correction tasks')
    elif state['state'] != 'executing' or added:
        raise CogitoError('path correction requires executing tasks or new review-fix tasks')
    tasks = dict(state['tasks'])
    for task in added:
        if task['id'] in tasks:
            raise CogitoError('path correction cannot change a completed Task or reuse task ids')
        tasks[task['id']] = {**task, 'status': 'pending'}
    for task in added:
        for dependency in task.get('depends_on', []):
            predecessor = tasks.get(dependency)
            if predecessor is None or (predecessor['slice_id'] != task['slice_id']
                                       and predecessor['status'] != 'integrated'):
                raise CogitoError('amendment cross-Slice dependencies must already be integrated')
    for row in amendment['path_additions']:
        task = tasks.get(row['task_id'])
        if not task or task['status'] not in {'pending', 'leased', 'running', 'blocked'} or any(
                r['task_id'] == row['task_id'] and r['role'] == 'implementer'
                and r['status'] == 'complete' for r in state.get('agent_results', [])):
            raise CogitoError('path correction cannot change a completed Task or recorded commit')
    return tasks


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
        if not state.get('package_hash'):
            raise CogitoError('path correction requires an approved package')
        body = {k: v for k, v in payload.items() if k != 'proposal_hash'}
        if hash_json(body) != payload.get('proposal_hash') or payload.get('base_contract_hash') != state['effective_contract_hash']:
            raise CogitoError('invalid path proposal binding')
        path_targets(state, payload['amendment'])
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
    if (not pending or amendment != pending['amendment']
            or pending['base_contract_hash'] != state['effective_contract_hash']):
        raise CogitoError('path additions require the exact pending reviewed proposal')
    review_binding(pending, payload.get('scope_review'))
    path_targets(state, amendment)
    added_ids = {task['id'] for task in amendment.get('added_tasks', [])}
    for row in amendment['path_additions']:
        if row['task_id'] in added_ids:
            # The complete new definition is appended by the normal projection.
            continue
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
