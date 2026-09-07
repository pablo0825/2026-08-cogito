"""Pure completion rules for technical corrections and review fixes."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cogito_state_types import RunState
from cogito_common import CogitoError


def _tasks_complete(state: RunState, task_ids: set[str]) -> bool:
    missing_task: Mapping[str, Any] = {}
    return all(
        state["tasks"].get(task_id, missing_task).get("status") == "complete"
        for task_id in task_ids
    )


def _results_bind_commit(
    state: RunState, task_ids: set[str], commit_id: str,
) -> bool:
    results = [
        item for item in state["agent_results"]
        if item.get("task_id") in task_ids
        and item.get("role") == "implementer"
        and item.get("status") == "complete"
    ]
    return (
        {item.get("task_id") for item in results} == task_ids
        and commit_id in {item.get("head_commit") for item in results}
    )


def validate_correction_completion(
    state: RunState, events: Sequence[Mapping[str, Any]],
    amendment_id: str, commit_id: str,
) -> set[str]:
    """Bind completion to the opened correction and return its added task IDs.

    Inputs are recorded state and chronological events. The caller validates
    the current phase and Git commit; an amendment without tasks is permitted.
    """
    started = [
        item for item in events
        if item["type"] in {
            "verification-correction-required", "post-verification-correction-required",
        }
    ]
    if not started or started[-1]["payload"].get("amendment_id") != amendment_id:
        raise CogitoError("correction completion does not match the amendment that opened this correction cycle")
    amendments = [
        item["payload"]["amendment"] for item in events
        if item["type"] == "technical-amendment-added"
    ]
    matching = [item for item in amendments if item["id"] == amendment_id]
    if len(matching) != 1:
        raise CogitoError("correction commit references an unknown Technical Amendment")
    added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
    if not _tasks_complete(state, added_ids):
        raise CogitoError("correction cannot finish before amendment tasks complete")
    if added_ids and not _results_bind_commit(state, added_ids, commit_id):
        raise CogitoError("correction tasks require Gate-recorded Implementer Results")
    return added_ids


def validate_review_fix_completion(
    state: RunState, events: Sequence[Mapping[str, Any]],
    amendment_id: str, commit_id: str,
) -> None:
    """Require a new amendment and completed tasks for the latest review finding.

    Inputs are recorded state and chronological events. The caller validates
    the review-fix phase and Git commit before recording the transition.
    """
    started = [item for item in events if item["type"] == "review-fix-required"]
    if not started:
        raise CogitoError("review fix has no recorded Reviewer finding")
    start = started[-1]
    if any(item['type'] == 'review-fix-complete' and item['sequence'] > start['sequence']
           for item in events):
        raise CogitoError('review fix cycle was already completed')
    if any(item['type'].endswith('correction-complete') or item['type'] == 'review-fix-complete'
           for item in events if item.get('payload', {}).get('amendment_id') == amendment_id):
        raise CogitoError('Technical Amendment was already consumed by a correction')
    amendment_events = [item for item in events if item["type"] == "technical-amendment-added"]
    matching = [
        item for item in amendment_events
        if item["payload"]["amendment"].get("id") == amendment_id
    ]
    if len(matching) != 1:
        raise CogitoError("review fix requires a new Technical Amendment bound to the current finding")
    amendment_event = matching[0]
    amendment = amendment_event['payload']['amendment']
    added_ids = {task["id"] for task in amendment.get("added_tasks", [])}
    if amendment_event['sequence'] <= start['sequence']:
        _validate_legacy_review_order(events, start, amendment_event, added_ids)
    if not added_ids or not _tasks_complete(state, added_ids):
        raise CogitoError("review fix requires completed amendment tasks")
    if not _results_bind_commit(state, added_ids, commit_id):
        raise CogitoError("review fix commit is not bound to its Implementer Results")


def _validate_legacy_review_order(events, start, amendment, task_ids):
    """Recognize only an unambiguous, unconsumed finding → amendment → start."""
    boundary = max((e['sequence'] for e in events if e['type'] == 'review-fix-complete'
                    and e['sequence'] < start['sequence']), default=0)
    binding = start['payload']
    reviews = [e for e in events if boundary < e['sequence'] < start['sequence']
               and e['type'] == 'agent-result-recorded'
               and e['payload']['result'].get('role') == 'reviewer'
               and e['payload']['result'].get('task_id') == binding.get('review_task_id')]
    candidates = [e for e in reviews if e['payload']['result'].get('status') == 'needs-fix'
                  and e['payload']['result'].get('requested_transition') == 'review-fix'
                  and e['payload']['result'].get('agent_id') == binding.get('reviewer')
                  and e['payload']['result'].get('head_commit') == binding.get('review_head')]
    if (len(candidates) != 1 or reviews[-1] != candidates[0]
            or not candidates[0]['sequence'] < amendment['sequence'] < start['sequence']):
        raise CogitoError('review fix requires a new Technical Amendment bound to one current finding')
    if any(e['type'] == 'agent-result-recorded' and e['sequence'] > start['sequence']
           and e['payload']['result'].get('role') == 'reviewer'
           and e['payload']['result'].get('task_id') == binding.get('review_task_id')
           for e in events):
        raise CogitoError('review finding was replaced after correction start')
    for task_id in task_ids:
        lifecycle = [e for e in events if e['type'] == 'task-updated'
                     and e['payload'].get('task_id') == task_id]
        results = [e for e in events if e['type'] == 'agent-result-recorded'
                   and e['payload']['result'].get('task_id') == task_id
                   and e['payload']['result'].get('role') == 'implementer']
        if (any(e['sequence'] <= start['sequence'] for e in [*lifecycle, *results])
                or not results or results[-1]['payload']['result'].get('status') != 'complete'):
            raise CogitoError('legacy review fix tasks must execute entirely after correction start')
        phases = [next((e['sequence'] for e in lifecycle if e['payload']['status'] == status), 0)
                  for status in ('leased', 'running', 'complete')]
        if not start['sequence'] < phases[0] < phases[1] < results[-1]['sequence'] < phases[2]:
            raise CogitoError('legacy review fix tasks require ordered lease, running, Result and complete')
