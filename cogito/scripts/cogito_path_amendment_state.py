"""Pure review bindings and event projection for additive path corrections."""
from cogito_common import CogitoError, hash_json
from cogito_path_amendment_contract import paths_overlap, predecessor_slices

EVENTS = {'path-amendment-proposed', 'path-amendment-withdrawn'}
ASSESSMENTS = {'requirements', 'api', 'data_model', 'security', 'slice', 'checks'}


def path_targets(state, amendment, events=()):
    """Resolve unfinished execution tasks or new review correction tasks."""
    from cogito_path_amendment_contract import validate_path_additions_shape
    validate_path_additions_shape(amendment)
    added = amendment.get('added_tasks', [])
    if state['state'] == 'review-fix':
        if not added:
            start = max((e['sequence'] for e in events if e['type'] == 'review-fix-required'), default=0)
            correction_ids = {task['id'] for e in events
                              if e['type'] == 'technical-amendment-added' and e['sequence'] > start
                              for task in e['payload']['amendment'].get('added_tasks', [])}
            if not start or any(row['task_id'] not in correction_ids for row in amendment['path_additions']):
                raise CogitoError('review path correction requires new correction tasks or unfinished tasks from this review cycle')
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
    starts = [e for e in events if e['type'] == 'review-fix-required']
    current_start = starts[-1] if starts else None
    finding_task = state['tasks'].get(
        current_start['payload'].get('review_task_id')) if current_start else None
    completed_before_review = {e['payload'].get('task_id') for e in events
                              if current_start and e['sequence'] < current_start['sequence']
                              and e['type'] == 'task-updated'
                              and e['payload'].get('status') == 'complete'}
    completed_results = {e['payload']['result']['task_id'] for e in events
                         if current_start and e['sequence'] < current_start['sequence']
                         and e['type'] == 'agent-result-recorded'
                         and e['payload']['result'].get('role') == 'implementer'
                         and e['payload']['result'].get('status') == 'complete'}
    for row in amendment['path_additions']:
        target = tasks[row['task_id']]
        for path in row['paths']:
            owners = [other for other in tasks.values() if other['id'] != target['id']
                      and paths_overlap(path, other['paths'])]
            if not owners:
                continue
            predecessors = predecessor_slices(tasks.values(), target['slice_id'])
            if state['state'] == 'executing' and all(other['slice_id'] in predecessors for other in owners):
                if state.get('task_delivery') != 'atomic' or not target.get('base_commit'):
                    raise CogitoError('predecessor path reuse requires an atomic target lease baseline')
                for other in owners:
                    if other['status'] != 'integrated' or not any(
                            r['task_id'] == other['id'] and r['role'] == 'implementer'
                            and r['status'] == 'complete' and r.get('head_commit')
                            for r in state.get('agent_results', [])):
                        raise CogitoError('predecessor path owners must have integrated delivery results')
                continue
            originals = [other for other in owners if other['slice_id'] == target['slice_id']]
            if (state['state'] != 'review-fix' or not finding_task
                    or finding_task['slice_id'] != target['slice_id'] or not originals
                    or any(other['status'] not in {'complete', 'verified', 'reviewed'}
                           or other['id'] not in completed_before_review or other['id'] not in completed_results
                           for other in originals)):
                raise CogitoError('path reuse requires a completed original Task in the current review Slice')
            # A file may already be declared by a later Slice in the approved
            # Package. Reusing our own existing scope grants that Slice nothing;
            # it must remain unstarted so no concurrent ownership is introduced.
            for other in owners:
                if other['slice_id'] != target['slice_id'] and (
                        other['status'] != 'pending' or other.get('base_commit') or any(
                            r['task_id'] == other['id'] for r in state.get('agent_results', []))):
                    raise CogitoError('shared path reuse requires other Slice owners to remain unstarted')
    return tasks


def predecessor_deliveries(state, amendment, events=()):
    """Replayable binding; Git ancestry is verified by the command before publication."""
    tasks = path_targets(state, amendment, events)
    bindings = []
    for row in amendment['path_additions']:
        target = tasks[row['task_id']]
        predecessors = predecessor_slices(tasks.values(), target['slice_id'])
        owners = {other['id'] for other in tasks.values() if other['slice_id'] in predecessors
                  and any(paths_overlap(path, other['paths']) for path in row['paths'])}
        if state['state'] == 'executing' and owners:
            heads = sorted({r['head_commit'] for r in state.get('agent_results', [])
                            if r['task_id'] in owners and r['role'] == 'implementer' and r['status'] == 'complete'})
            bindings.append(dict(task_id=target['id'], base_commit=target['base_commit'], owner_heads=heads))
    return bindings


def validate_predecessor_binding(state, amendment, proposal, events):
    expected = predecessor_deliveries(state, amendment, events)
    if expected != proposal.get('predecessor_deliveries', []):
        raise CogitoError('predecessor delivery baseline binding changed')


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


def project_path_amendment(state, event, payload, events=()):
    if event == 'path-amendment-proposed':
        if not state.get('package_hash'):
            raise CogitoError('path correction requires an approved package')
        body = {k: v for k, v in payload.items() if k != 'proposal_hash'}
        if hash_json(body) != payload.get('proposal_hash') or payload.get('base_contract_hash') != state['effective_contract_hash']:
            raise CogitoError('invalid path proposal binding')
        path_targets(state, payload['amendment'], events)
        validate_predecessor_binding(state, payload['amendment'], payload, events)
        state['path_amendment'] = dict(payload)
        return True
    if event == 'path-amendment-withdrawn':
        pending = state.get('path_amendment')
        if not pending or payload.get('proposal_hash') != pending['proposal_hash']:
            raise CogitoError('withdrawal must identify pending path proposal')
        state.pop('path_amendment', None)
        return True
    return False


def apply_path_projection(state, payload, events=()):
    amendment = payload.get('amendment', {})
    if not amendment.get('path_additions'):
        return
    pending = state.get('path_amendment')
    if (not pending or amendment != pending['amendment']
            or pending['base_contract_hash'] != state['effective_contract_hash']):
        raise CogitoError('path additions require the exact pending reviewed proposal')
    review_binding(pending, payload.get('scope_review'))
    path_targets(state, amendment, events)
    validate_predecessor_binding(state, amendment, pending, events)
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
