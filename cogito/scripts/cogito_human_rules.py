"""Pure validation for feedback and bounded human acceptance corrections.

Classification is an accountable Coordinator declaration, not proof that a
change is safe: the caller must still enforce the effective contract and Gates.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from cogito_common import CogitoError


HUMAN_STATES = frozenset({
    "human-feedback-triage", "human-correction", "human-correction-verifying",
    "human-correction-reviewing",
})


def _object(value: Any, required: set[str], optional: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CogitoError(f"{name} must be an object")
    if not required <= value.keys() or value.keys() - required - optional:
        raise CogitoError(f"{name} has missing or unknown fields")
    return copy.deepcopy(value)


def _text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CogitoError(f"{name} must be nonempty text")


def _boolean(value: Any, name: str) -> None:
    if type(value) is not bool:
        raise CogitoError(f"{name} must be a boolean")


def _ids(value: Any, name: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise CogitoError(f"{name} must be {'a nonempty' if nonempty else 'a'} list")
    for item in value:
        _text(item, name)
    if len(set(value)) != len(value):
        raise CogitoError(f"{name} must not contain duplicate IDs")
    return list(value)


def validate_feedback(request: Any) -> dict[str, Any]:
    """Normalize a human's feedback; missing acceptance never grants closure."""
    feedback = _object(request, {"id", "message", "items"},
                       {"acceptance_complete", "close_after_fixes"}, "feedback")
    for key in ("id", "message"):
        _text(feedback[key], f"feedback.{key}")
    if not isinstance(feedback["items"], list) or not feedback["items"]:
        raise CogitoError("feedback.items must be a nonempty list")
    item_ids = []
    for raw in feedback["items"]:
        item = _object(raw, {"id", "description"}, set(), "feedback item")
        for key in ("id", "description"):
            _text(item[key], f"feedback item.{key}")
        item_ids.append(item["id"])
    _ids(item_ids, "feedback item IDs", nonempty=True)
    for key in ("acceptance_complete", "close_after_fixes"):
        feedback.setdefault(key, False)
        _boolean(feedback[key], key)
    if feedback["close_after_fixes"] and not feedback["acceptance_complete"]:
        raise CogitoError("close_after_fixes requires explicit acceptance_complete")
    return feedback


def validate_triage(request: Any, feedback: Mapping[str, Any]) -> dict[str, Any]:
    """Require full classification and explicit authorization before deferral."""
    triage = _object(request, {"feedback_id", "assessments"},
                     {"deferred_item_ids", "split_authorized", "split_reason"}, "triage")
    _text(triage["feedback_id"], "triage.feedback_id")
    if triage["feedback_id"] != feedback["id"]:
        raise CogitoError("triage feedback_id does not match the current feedback")
    assessments = triage["assessments"]
    if not isinstance(assessments, list) or not assessments:
        raise CogitoError("triage assessments must be a nonempty list")
    ids = []
    for raw in assessments:
        item = _object(raw, {"id", "disposition", "reason"}, set(), "assessment")
        _text(item["id"], "assessment.id")
        _text(item["reason"], "assessment.reason")
        if not isinstance(item["disposition"], str) or item["disposition"] not in {"local", "change", "clarify"}:
            raise CogitoError("assessment disposition must be local, change or clarify")
        ids.append(item["id"])
    _ids(ids, "assessment IDs", nonempty=True)
    if set(ids) != {item["id"] for item in feedback["items"]}:
        raise CogitoError("assessments must cover every feedback item exactly once")
    deferred = _ids(triage.setdefault("deferred_item_ids", []), "deferred_item_ids")
    triage.setdefault("split_authorized", False)
    _boolean(triage["split_authorized"], "split_authorized")
    if "split_reason" in triage:
        _text(triage["split_reason"], "split_reason")
    if deferred and (not triage["split_authorized"] or not triage.get("split_reason")):
        raise CogitoError("deferral requires explicit split authorization and reason")
    if not set(deferred) < set(ids):
        raise CogitoError("deferred items must be a subset and cannot defer every item")
    triage["active_item_ids"] = [item["id"] for item in feedback["items"] if item["id"] not in deferred]
    active = {item["disposition"] for item in assessments if item["id"] not in deferred}
    triage["route"] = "change" if "change" in active else "clarify" if "clarify" in active else "local"
    return triage


def validate_human_budget(state: Mapping[str, Any]) -> int:
    """Return the next run-total round; neither recovery nor a batch resets it."""
    count = state.get("counters", {}).get("human_corrections", 0)
    limit = state.get("limits", {}).get("human_corrections", 3)
    if type(count) is not int or count < 0 or type(limit) is not int or limit < 1:
        raise CogitoError("invalid human correction budget")
    if count >= min(limit, 3):
        raise CogitoError("human correction budget exhausted; stop and request a decision")
    return count + 1


def validate_resolution(request: Any, human: Mapping[str, Any]) -> dict[str, Any]:
    """Bind correction completion to every active item in the current batch."""
    resolution = _object(request, {"feedback_id", "resolved_item_ids", "summary"}, set(), "resolution")
    _text(resolution["feedback_id"], "resolution.feedback_id")
    feedback = human.get("feedback", {})
    triage = human.get("triage", {})
    if resolution["feedback_id"] != feedback.get("id"):
        raise CogitoError("resolution feedback_id does not match the current feedback")
    _text(resolution["summary"], "resolution.summary")
    resolved = _ids(resolution["resolved_item_ids"], "resolved_item_ids", nonempty=True)
    if triage.get("route") != "local" or human.get("escalated"):
        raise CogitoError("only local, un-escalated feedback can be resolved")
    if set(resolved) != set(triage.get("active_item_ids", [])):
        raise CogitoError("resolution must cover every active feedback item exactly once")
    return resolution


def can_close_after_fixes(human: Mapping[str, Any]) -> bool:
    """Check the conditional human grant, after fresh verification and review.

    This predicate does not establish that checks or review passed: the caller
    must prove those against the current corrected content before closing.
    """
    feedback = human.get("feedback", {})
    triage = human.get("triage", {})
    if (feedback.get("acceptance_complete") is not True
            or feedback.get("close_after_fixes") is not True
            or triage.get("route") != "local"
            or triage.get("feedback_id") != feedback.get("id")
            or human.get("escalated") or human.get("unresolved_item_ids")):
        return False
    if triage.get("deferred_item_ids") and (
        triage.get("split_authorized") is not True or not triage.get("split_reason")
    ):
        return False
    try:
        validate_resolution(human.get("resolution"), human)
    except CogitoError:
        return False
    return True
