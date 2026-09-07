"""Read-only validation for one historical auxiliary check-resolution record."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError, hash_json
from cogito_contract_fields import CONTENT_HASH_RE, require_string
from cogito_event_repository import EventSnapshot
from cogito_projection import project_events


EVENT = "controlled-check-attempt-resolved"
PAYLOAD_FIELDS = {
    "interrupted_action_id", "replacement_action_id", "resolver_id", "reason",
    "request_hash", "check_id", "evidence_path", "evidence_hash", "check_hash",
    "effective_contract_hash",
}


def _text(value: Any, name: str) -> str:
    require_string(value, f"historical check resolution {name}")
    return str(value)


def _hash(value: Any, name: str) -> str:
    text = _text(value, name)
    if not CONTENT_HASH_RE.fullmatch(text):
        raise CogitoError(f"historical check resolution requires a valid {name}")
    return text


def _validate_resolution(
    events_before: Sequence[Mapping[str, Any]], payload: Mapping[str, Any],
) -> None:
    if set(payload) != PAYLOAD_FIELDS:
        raise CogitoError("invalid historical check resolution payload")
    interrupted = _text(payload.get("interrupted_action_id"), "interrupted_action_id")
    replacement = _text(payload.get("replacement_action_id"), "replacement_action_id")
    _text(payload.get("resolver_id"), "resolver_id")
    _text(payload.get("reason"), "reason")
    request_hash = _hash(payload.get("request_hash"), "request_hash")
    check_id = _text(payload.get("check_id"), "check_id")
    evidence_path = _text(payload.get("evidence_path"), "evidence_path")
    evidence_hash = _hash(payload.get("evidence_hash"), "evidence_hash")
    _hash(payload.get("check_hash"), "check_hash")
    contract_hash = _hash(payload.get("effective_contract_hash"), "effective_contract_hash")
    if interrupted == replacement:
        raise CogitoError("historical check resolution requires distinct actions")
    if any(
        event.get("type") == EVENT
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("interrupted_action_id") == interrupted
        for event in events_before
    ):
        raise CogitoError("historical check attempt was resolved more than once")
    if any(
        event.get("type") == EVENT
        and isinstance(event.get("payload"), Mapping)
        and event["payload"].get("replacement_action_id") == replacement
        for event in events_before
    ):
        raise CogitoError("historical replacement evidence was reused")
    if any(
        event.get("type") == "check-evidence-recorded"
        and event.get("action_id") == interrupted
        for event in events_before
    ):
        raise CogitoError("historical interrupted check already recorded evidence")
    replacements = [
        event for event in events_before
        if event.get("type") == "check-evidence-recorded"
        and event.get("action_id") == replacement
    ]
    if len(replacements) != 1 or replacements[0].get("request_hash") != request_hash:
        raise CogitoError("historical replacement check evidence is missing or mismatched")
    replacement_payload = replacements[0].get("payload", {})
    expected = {
        "check_id": check_id,
        "evidence_path": evidence_path,
        "evidence_hash": evidence_hash,
        "effective_contract_hash": contract_hash,
    }
    if any(replacement_payload.get(key) != value for key, value in expected.items()):
        raise CogitoError("historical check resolution differs from its replacement evidence")


def compatible_snapshot(
    events: Sequence[Mapping[str, Any]], workflow: Mapping[str, Any],
) -> EventSnapshot:
    """Project after validating and removing this non-transition historical record."""
    resolutions = [event for event in events if event.get("type") == EVENT]
    if not resolutions:
        raise CogitoError("no supported historical inventory records")
    final_positions = [index for index, event in enumerate(events) if event.get("type") == "finalization-complete"]
    if len(final_positions) != 1:
        raise CogitoError("historical inventory source requires one finalization event")
    for index, event in enumerate(events):
        if event.get("type") != EVENT:
            continue
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise CogitoError("invalid historical check resolution payload")
        if index > final_positions[0]:
            raise CogitoError("historical check resolution is not legal after finalization")
        _validate_resolution(events[:index], payload)
        prefix = [item for item in events[:index] if item.get("type") != EVENT]
        state_before = project_events(prefix, workflow)
        if (state_before["state"] in workflow["terminal_states"]
                or state_before.get("effective_contract_hash") != payload["effective_contract_hash"]):
            raise CogitoError("historical check resolution is not bound to its run state")
        interrupted = payload["interrupted_action_id"]
        if any(
            item.get("type") == "check-evidence-recorded"
            and item.get("action_id") == interrupted
            for item in events[index + 1:]
        ):
            raise CogitoError("resolved historical check later recorded evidence")
    filtered = [item for item in events if item.get("type") != EVENT]
    return EventSnapshot([dict(item) for item in events], project_events(filtered, workflow))


def compatible_result(
    result: Mapping[str, Any], events: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Remove only exact historical resolution receipts for current validation."""
    value = copy.deepcopy(dict(result))
    summary = value.get("delivery_summary")
    if not isinstance(summary, dict) or not isinstance(summary.get("verification"), list):
        raise CogitoError("historical Result lacks its check resolution receipt")
    expected = [
        {"event_sequence": event["sequence"], "event": EVENT, **event["payload"]}
        for event in events if event.get("type") == EVENT
    ]
    actual = [
        record for record in summary["verification"]
        if isinstance(record, Mapping) and record.get("event") == EVENT
    ]
    if actual != expected:
        raise CogitoError("historical Result check resolution receipt does not match the ledger")
    summary["verification"] = [
        record for record in summary["verification"]
        if not isinstance(record, Mapping) or record.get("event") != EVENT
    ]
    return value


def validate_resolution_checks(
    events: Sequence[Mapping[str, Any]], effective_contract: Mapping[str, Any],
) -> None:
    """Bind historical resolution check hashes to the materialized contract."""
    checks = {item["id"]: item for item in effective_contract["checks"]}
    for event in events:
        if event.get("type") != EVENT:
            continue
        payload = event["payload"]
        check = checks.get(payload["check_id"])
        if check is None or hash_json(check) != payload["check_hash"]:
            raise CogitoError("historical check resolution does not match its check contract")
