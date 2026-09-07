"""Conservative, pure eligibility rules for same-run review retention."""
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError
from cogito_contract_fields import require_id, require_paths, require_string
from cogito_contracts import path_allowed


def _text(value, name):
    require_string(value, name)
    if not value.strip():
        raise CogitoError(name + ' must describe the assessment')


def _ids(value, name, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise CogitoError(name + ' must be an array')
    for item in value:
        require_id(item, name)
    if len(set(value)) != len(value):
        raise CogitoError(name + ' must be distinct')


def validate_impact(value):
    fields = {'author_id', 'retained', 'affected_task_ids', 'check_ids', 'assessment'}
    if not isinstance(value, dict) or set(value) != fields:
        raise CogitoError('retention impact requires exact author, retained, affected tasks, checks and assessment')
    require_id(value['author_id'], 'retention author')
    _text(value['assessment'], 'retention impact assessment')
    _ids(value['affected_task_ids'], 'affected tasks', nonempty=True)
    _ids(value['check_ids'], 'related checks', nonempty=True)
    if not isinstance(value['retained'], list) or not value['retained']:
        raise CogitoError('retention requires candidates')
    ids = []
    for item in value['retained']:
        if not isinstance(item, dict) or set(item) != {'task_id', 'reason', 'dependency_paths'}:
            raise CogitoError('retained entry requires task_id, reason and dependency_paths')
        require_id(item['task_id'], 'retained task')
        _text(item['reason'], 'retention reason')
        require_paths(item['dependency_paths'], 'dependency paths')
        if len(set(item['dependency_paths'])) != len(item['dependency_paths']):
            raise CogitoError('dependency paths must be distinct')
        ids.append(item['task_id'])
    _ids(ids, 'retained tasks', nonempty=True)
    if set(ids) & set(value['affected_task_ids']):
        raise CogitoError('affected Task cannot be retained')


def validate_reviewer(impact, reviewer_id, assessment, implementers):
    require_id(reviewer_id, 'retention reviewer')
    _text(assessment, 'retention reviewer assessment')
    if reviewer_id in {impact['author_id'], *implementers}:
        raise CogitoError('retention reviewer must be independent of author and implementers')


def reference(event):
    return {'event_sequence': event['sequence'], 'event_hash': event['event_hash']}


def source_review(events, task_id, cycle):
    """Never fall back past a replacement, including an unresolved finding."""
    reviews = [e for e in events if e['type'] == 'agent-result-recorded'
               and e['payload']['result'].get('role') == 'reviewer'
               and e['payload']['result'].get('task_id') == task_id]
    if not reviews:
        raise CogitoError('retention requires an original approval: ' + task_id)
    event = reviews[-1]
    result = event['payload']['result']
    if (event['sequence'] >= cycle or result.get('status') != 'complete'
            or result.get('requested_transition') != 'review-approved'
            or result.get('agent_id') == result.get('reviewed_implementer')):
        raise CogitoError('retention requires an unreplaced prior independent approval: ' + task_id)
    return event


def validate_candidate(task_id: str, tasks: Mapping[str, Any], touched_paths: Sequence[str],
                       impact: Mapping[str, Any], old_task: Mapping[str, Any],
                       new_task: Mapping[str, Any], old_checks: Mapping[str, Any],
                       new_checks: Mapping[str, Any]) -> None:
    """Use declared paths/DAG only; semantic dependency assessment stays human/agent work."""
    validate_impact(impact)
    entry = next((i for i in impact['retained'] if i['task_id'] == task_id), None)
    if entry is None or task_id not in tasks or old_task != new_task:
        raise CogitoError('retained Task contract changed or is missing')
    if any(old_checks.get(key) is None or old_checks[key] != new_checks.get(key)
           for key in old_task['check_ids']):
        raise CogitoError('retained Task check definition changed')
    ancestors, pending = set(), [task_id]
    while pending:
        key = pending.pop()
        if key in ancestors:
            continue
        if key not in tasks:
            raise CogitoError('retained Task dependency is unknown')
        ancestors.add(key)
        pending.extend(tasks[key].get('depends_on', []))
    if ancestors & set(impact['affected_task_ids']):
        raise CogitoError('retained Task depends on affected work')
    paths = [p for key in ancestors for p in tasks[key]['paths']]
    paths.extend(entry['dependency_paths'])
    if any(path_allowed(path, paths) for path in touched_paths):
        raise CogitoError('retained Task or dependency was touched')
