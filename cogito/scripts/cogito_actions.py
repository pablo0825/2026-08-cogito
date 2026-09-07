"""Request identity and exclusive execution of controlled-check attempts."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator, Mapping

from cogito_common import CogitoError, atomic_create_json, hash_json, load_json

_fixed_authority: ContextVar[tuple[str, str, str] | None] = ContextVar('fixed_action', default=None)


def fixed_action_path(root, run_id, action_id):
    return Path(root) / '.cogito' / 'runs' / run_id / 'fixed-actions' / (hash_json(action_id) + '.json')


def fixed_steps_done(binding, events):
    """Completion comes from receipts, never a mutable 'done' marker."""
    for step in binding['steps']:
        matches = [e for e in events if e.get('action_id') == step['action_id']]
        if not matches:
            return False
        if len(matches) != 1 or any(matches[0].get(k) != step.get(k)
                                    for k in ('type', 'payload', 'request_hash')):
            raise CogitoError('fixed action receipt differs from its frozen input')
    return True


def pending_fixed_action(root, run_id):
    from cogito_events import read_events
    directory = Path(root) / '.cogito' / 'runs' / run_id
    pending = []
    files = sorted((directory / 'fixed-actions').glob('*.json'))
    if not files:
        return None
    events = read_events(directory / 'events.jsonl')
    for path in files:
        binding = load_json(path)
        if binding.get('operation') not in {'task-finish', 'review-fix-start'} or not binding.get('steps'):
            raise CogitoError('invalid fixed action binding')
        if not fixed_steps_done(binding, events):
            pending.append(binding)
    if len(pending) > 1:
        raise CogitoError('multiple unfinished fixed actions require inspection')
    return pending[0] if pending else None


def guard_fixed_action(root, run_id, operation, *, stopping=False):
    pending = pending_fixed_action(root, run_id)
    if not pending or stopping:
        return
    if _fixed_authority.get() == (str(Path(root).resolve()), run_id, pending['action_id']):
        return
    if operation in {'finish_task', 'start_review_fix_with_amendment'}:
        return  # The entry point must match the exact pending action before writing.
    raise CogitoError('retry unfinished ' + pending['operation'] + ' with its original input and action_id')


@contextmanager
def fixed_action_authority(root, run_id, action_id):
    token = _fixed_authority.set((str(Path(root).resolve()), run_id, action_id))
    try:
        yield
    finally:
        _fixed_authority.reset(token)


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
