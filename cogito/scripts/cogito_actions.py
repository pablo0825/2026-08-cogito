"""Request identity and exclusive execution of controlled-check attempts."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

from cogito_common import CogitoError, atomic_create_json, hash_json, load_json


def request_fingerprint(command: str, **arguments: Any) -> str:
    """Hash the command's inputs, never the verdict derived from mutable state."""
    return hash_json({"command": command, "arguments": arguments})


def require_same_request(recorded: Mapping[str, Any], request_hash: str, action_id: str) -> None:
    if recorded.get("request_hash") is None:
        raise CogitoError(
            f"legacy action_id {action_id!r} has no request fingerprint; "
            "inspect its recorded outcome before issuing another action"
        )
    if recorded["request_hash"] != request_hash:
        raise CogitoError(f"action_id {action_id!r} was already used for different content")


@contextmanager
def controlled_check_attempt(run_dir: Path, action_id: str, request_hash: str) -> Iterator[Path]:
    """Serialize one action and retain its request across an event-append crash.

    The started marker lets the caller distinguish a fresh attempt from an
    interrupted process whose outcome is unknown. Published evidence can be
    registered on retry; an interrupted attempt without evidence is not rerun.
    """
    directory = run_dir / "check-actions" / hash_json(action_id)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "lock").open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        request_path = directory / "request.json"
        request = {"action_id": action_id, "request_hash": request_hash}
        atomic_create_json(request_path, request)
        require_same_request(load_json(request_path), request_hash, action_id)
        yield directory / "started.json"
