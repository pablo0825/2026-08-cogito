"""Append-only event-log persistence with hash-chain and CAS protection."""

from __future__ import annotations

import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from cogito_common import CogitoError, canonical_json, hash_json
from cogito_actions import require_same_request


def read_events(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CogitoError(f"cannot read event log: {exc}") from exc
    for expected, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CogitoError(f"invalid event JSON on line {expected}") from exc
        if not isinstance(event, dict):
            raise CogitoError(f"event JSON on line {expected} must be an object")
        supplied_hash = event.get("event_hash")
        body = {key: value for key, value in event.items() if key != "event_hash"}
        if event.get("sequence") != expected or event.get("previous_event_hash") != previous:
            raise CogitoError(f"broken event chain on line {expected}")
        if supplied_hash != hash_json(body):
            raise CogitoError(f"invalid event hash on line {expected}")
        previous = supplied_hash
        events.append(event)
    return events


def append_event(path: str | Path, event: Mapping[str, Any], expected_previous_hash: str | None = None) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        events = read_events(path)
        actual_previous = events[-1]["event_hash"] if events else "0" * 64
        action_id = event.get("action_id")
        if action_id:
            matches = [item for item in events if item.get("action_id") == action_id]
            if matches:
                if event.get("request_hash") is not None:
                    require_same_request(matches[0], event["request_hash"], action_id)
                elif matches[0].get("request_hash") is not None:
                    raise CogitoError("cannot replay a request-bound event without its request fingerprint")
                requested = {"type": event.get("type"), "payload": event.get("payload", {})}
                recorded = {"type": matches[0].get("type"), "payload": matches[0].get("payload", {})}
                if hash_json(requested) != hash_json(recorded):
                    raise CogitoError(f"action_id {action_id!r} was already used for different content")
                return matches[0]
        if expected_previous_hash is not None and actual_previous != expected_previous_hash:
            raise CogitoError("event history changed during transition; retry with the same action_id")
        body = {
            "sequence": len(events) + 1,
            "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "type": event.get("type"),
            "payload": event.get("payload", {}),
            "action_id": action_id,
            "previous_event_hash": actual_previous,
        }
        if not isinstance(body["type"], str) or not body["type"]:
            raise CogitoError("event type is required")
        if not isinstance(body["payload"], dict):
            raise CogitoError("event payload must be an object")
        if "request_hash" in event:
            body["request_hash"] = event["request_hash"]
        body["event_hash"] = hash_json(body)
        line = canonical_json(body) + "\n"
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return body
