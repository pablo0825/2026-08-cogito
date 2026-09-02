"""Pure completion rules for technical corrections and review fixes."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cogito_common import CogitoError


def _tasks_complete(state: Mapping[str, Any], task_ids: set[str]) -> bool:
    return all(
        state["tasks"].get(task_id, {}).get("status") == "complete"
        for task_id in task_ids
    )


def _results_bind_commit(
    state: Mapping[str, Any], task_ids: set[str], commit_id: str,
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
    state: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
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
    state: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
    amendment_id: str, commit_id: str,
) -> None:
    """Require a new amendment and completed tasks for the latest review finding.

    Inputs are recorded state and chronological events. The caller validates
    the review-fix phase and Git commit before recording the transition.
    """
    started = [item for item in events if item["type"] == "review-fix-required"]
    if not started:
        raise CogitoError("review fix has no recorded Reviewer finding")
    amendment_events = [item for item in events if item["type"] == "technical-amendment-added"]
    matching = [
        item["payload"]["amendment"] for item in amendment_events
        if item["payload"]["amendment"].get("id") == amendment_id
        and item["sequence"] > started[-1]["sequence"]
    ]
    if len(matching) != 1:
        raise CogitoError("review fix requires a new Technical Amendment bound to the current finding")
    added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
    if not added_ids or not _tasks_complete(state, added_ids):
        raise CogitoError("review fix requires completed amendment tasks")
    if not _results_bind_commit(state, added_ids, commit_id):
        raise CogitoError("review fix commit is not bound to its Implementer Results")
