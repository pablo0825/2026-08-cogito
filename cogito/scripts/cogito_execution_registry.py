"""Track executors and verify quiescence before handing off a run.

OS evidence is queried, never inferred from a caller's ``stopped`` flag.
External receipts are executor attestations, not mechanical proof: consumers
must explicitly opt into that trust boundary. This module does not sleep.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Iterator

from cogito_common import CogitoError, ID_RE, atomic_write_json, load_json


def _path(root: str | Path, run_id: str) -> Path:
    if not isinstance(run_id, str) or not ID_RE.fullmatch(run_id):
        raise CogitoError("unsafe execution registry run identifier")
    base = Path(root).resolve()
    path = base / ".cogito" / "runs" / run_id / "execution-registry.json"
    if path.resolve() != path:
        raise CogitoError("execution registry must not traverse symlinks")
    return path


def _safe_id(identifier: str) -> None:
    if not isinstance(identifier, str) or not ID_RE.fullmatch(identifier):
        raise CogitoError("unsafe executor identifier")


def _number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate_receipt(receipt: Any, handle: str) -> None:
    if not isinstance(receipt, dict):
        raise CogitoError("external receipt must be an object")
    for key in ("provider", "control_tool", "event_id"):
        if not isinstance(receipt.get(key), str) or not receipt[key].strip():
            raise CogitoError(f"external receipt requires {key}")
    if receipt.get("handle") != handle or receipt.get("status") not in ("completed", "interrupted"):
        raise CogitoError("external receipt must identify the matching terminal executor")
    raw = receipt.get("raw_response")
    if not isinstance(raw, dict) or raw.get("handle") != handle or raw.get("status") != receipt["status"]:
        raise CogitoError("external raw response must match the handle and terminal status")


def _load(path: Path, run_id: str) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": 1, "run_id": run_id, "stop_request": None, "entries": {}}
    data = load_json(path)
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("run_id") != run_id or not isinstance(data.get("entries"), dict) or "stop_request" not in data:
        raise CogitoError("malformed execution registry")
    stop = data.get("stop_request")
    if stop is not None and (not isinstance(stop, dict) or not _number(stop.get("requested_at")) or not _number(stop.get("deadline")) or stop["deadline"] < stop["requested_at"]):
        raise CogitoError("malformed execution stop request")
    for identifier, entry in data["entries"].items():
        _safe_id(identifier)
        if not isinstance(entry, dict) or entry.get("identifier") != identifier:
            raise CogitoError("malformed executor entry")
        if entry.get("kind") == "process":
            identity = entry.get("identity")
            if not isinstance(identity, dict) or type(identity.get("pid")) is not int or identity["pid"] <= 0 or type(identity.get("pgid")) is not int or identity["pgid"] <= 0 or not isinstance(identity.get("started"), str) or not identity["started"] or not isinstance(identity.get("command_sha256"), str) or len(identity["command_sha256"]) != 64:
                raise CogitoError("malformed process identity")
        elif entry.get("kind") == "external":
            if not isinstance(entry.get("handle"), str) or not entry["handle"].strip():
                raise CogitoError("malformed external handle")
            if entry.get("receipt") is not None:
                _validate_receipt(entry["receipt"], entry["handle"])
        else:
            raise CogitoError("unknown executor kind")
    return data


@contextmanager
def _locked(root: str | Path, run_id: str) -> Iterator[tuple[Path, dict[str, Any]]]:
    path = _path(root, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    if lock.is_symlink():
        raise CogitoError("execution registry lock must not be a symlink")
    with lock.open("a") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        yield path, _load(path, run_id)


def _ps(*args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(["ps", *args], capture_output=True, text=True, timeout=5,
                              env={**os.environ, "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CogitoError(f"cannot inspect executor processes: {exc}") from exc


def process_identity(pid: int) -> dict[str, Any] | None:
    if type(pid) is not int or pid <= 0:
        raise CogitoError("executor PID must be a positive integer")
    result = _ps("-p", str(pid), "-o", "pid=,pgid=,lstart=,command=")
    if not result.stdout.strip():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        except OSError as exc:
            raise CogitoError("cannot establish executor termination") from exc
        raise CogitoError("process exists but identity cannot be inspected")
    if result.returncode != 0:
        raise CogitoError("cannot read executor identity")
    fields = result.stdout.strip().split(None, 7)
    if len(fields) != 8:
        raise CogitoError("malformed ps process identity")
    try:
        observed_pid, pgid = int(fields[0]), int(fields[1])
    except ValueError as exc:
        raise CogitoError("malformed ps process identifiers") from exc
    if observed_pid != pid:
        raise CogitoError("ps returned a different executor PID")
    return {"pid": pid, "pgid": pgid, "started": " ".join(fields[2:7]),
            "command_sha256": hashlib.sha256(fields[7].encode()).hexdigest()}


def _group_alive(pgid: int) -> bool:
    result = _ps("-axo", "pid=,pgid=,stat=")
    if result.returncode:
        raise CogitoError("cannot inspect executor process group")
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) != 3:
            raise CogitoError("malformed ps process group listing")
        try:
            if int(fields[1]) == pgid and not fields[2].startswith("Z"):
                return True
        except ValueError as exc:
            raise CogitoError("malformed ps process group identifier") from exc
    return False


def register_process(root: str | Path, run_id: str, identifier: str, pid: int) -> dict[str, Any]:
    _safe_id(identifier)
    with _locked(root, run_id) as (path, data):
        from cogito_path_amendment import guard_executor_admission
        guard_executor_admission(root, run_id, identifier)
        if data["stop_request"] is not None:
            raise CogitoError("cannot register new work after stop was requested")
        identity = process_identity(pid)
        if identity is None:
            raise CogitoError("cannot register a terminated process")
        entry = {"identifier": identifier, "kind": "process", "identity": identity}
        existing = data["entries"].get(identifier)
        if existing is not None and existing != entry:
            raise CogitoError("executor identifier is already bound")
        data["entries"][identifier] = entry
        atomic_write_json(path, data)
        return entry


@contextmanager
def managed_process(root: str | Path, run_id: str, identifier: str, pid: int) -> Iterator[dict[str, Any]]:
    """Register the actual child PID; leaving the context does not prove exit."""
    yield register_process(root, run_id, identifier, pid)


def register_external(root: str | Path, run_id: str, identifier: str, handle: str) -> dict[str, Any]:
    _safe_id(identifier)
    if not isinstance(handle, str) or not handle.strip():
        raise CogitoError("external executor requires a handle")
    with _locked(root, run_id) as (path, data):
        from cogito_path_amendment import guard_executor_admission
        guard_executor_admission(root, run_id, identifier)
        if data["stop_request"] is not None:
            raise CogitoError("cannot register new work after stop was requested")
        entry = {"identifier": identifier, "kind": "external", "handle": handle, "receipt": None}
        existing = data["entries"].get(identifier)
        if existing is not None and existing != entry:
            raise CogitoError("executor identifier is already bound")
        data["entries"][identifier] = entry
        atomic_write_json(path, data)
        return entry


def record_external_receipt(root: str | Path, run_id: str, identifier: str, handle: str, receipt: dict[str, Any]) -> None:
    """Record an executor attestation; this does not authenticate its provider."""
    _validate_receipt(receipt, handle)
    with _locked(root, run_id) as (path, data):
        entry = data["entries"].get(identifier)
        if not entry or entry["kind"] != "external" or entry["handle"] != handle:
            raise CogitoError("receipt does not match a registered external executor")
        if entry["receipt"] is not None and entry["receipt"] != receipt:
            raise CogitoError("external stop receipt is already recorded")
        entry["receipt"] = receipt
        atomic_write_json(path, data)


def request_stop(root: str | Path, run_id: str, deadline_seconds: float = 60, *, now: float | None = None) -> dict[str, Any]:
    instant = time.time() if now is None else now
    if not _number(instant) or not _number(deadline_seconds) or not 0 <= deadline_seconds <= 60:
        raise CogitoError("stop deadline must be between zero and 60 seconds")
    with _locked(root, run_id) as (path, data):
        if data["stop_request"] is None:
            data["stop_request"] = {"requested_at": instant, "deadline": instant + deadline_seconds}
            atomic_write_json(path, data)
    return snapshot(root, run_id)


def _observe(data: dict[str, Any], *, allow_external_receipts: bool) -> dict[str, Any]:
    for entry in data["entries"].values():
        if entry["kind"] == "external":
            entry["terminated"] = bool(allow_external_receipts and entry["receipt"])
            entry["observation"] = "attested" if entry["terminated"] else "unverified-external"
            continue
        identity = entry["identity"]
        current = process_identity(identity["pid"])
        if current is not None and current != identity:
            entry["terminated"] = False
            entry["observation"] = "identity-mismatch"
        elif current is not None:
            entry["terminated"] = False
            entry["observation"] = "running"
        else:
            # Only independently created groups belong to this executor.
            dedicated = identity["pgid"] == identity["pid"]
            alive = _group_alive(identity["pgid"]) if dedicated else True
            entry["terminated"] = not alive
            entry["observation"] = ("unverified-shared-group" if not dedicated else
                                    "descendants-running" if alive else "terminated")
    data["stop_requested"] = data["stop_request"] is not None
    data["quiescent"] = all(entry["terminated"] for entry in data["entries"].values())
    return data


def snapshot(root: str | Path, run_id: str, *, allow_external_receipts: bool = False) -> dict[str, Any]:
    with _locked(root, run_id) as (_, data):
        return _observe(data, allow_external_receipts=allow_external_receipts)


@contextmanager
def quiescent_guard(root: str | Path, run_id: str, *, allow_external_receipts: bool = False) -> Iterator[bool]:
    """Keep executor admission locked while the caller removes unused resources."""
    with _locked(root, run_id) as (_, data):
        yield bool(_observe(data, allow_external_receipts=allow_external_receipts)["quiescent"])


def quiescent(root: str | Path, run_id: str, *, allow_external_receipts: bool = False) -> bool:
    return bool(snapshot(root, run_id, allow_external_receipts=allow_external_receipts)["quiescent"])


def terminate_overdue(root: str | Path, run_id: str, *, now: float | None = None) -> dict[str, Any]:
    """SIGKILL only a still-matching dedicated group after the grace deadline.

    A shared group, absent leader, or changed identity must be resolved by its
    executor adapter; blindly signaling those can kill unrelated processes.
    """
    instant = time.time() if now is None else now
    if not _number(instant):
        raise CogitoError("invalid stop time")
    with _locked(root, run_id) as (_, data):
        stop = data["stop_request"]
        if stop is None or instant < stop["deadline"]:
            return {"signaled": [], "unresolved": []}
        signaled, unresolved = [], []
        for identifier, entry in data["entries"].items():
            if entry["kind"] != "process":
                unresolved.append(identifier)
                continue
            identity = entry["identity"]
            current = process_identity(identity["pid"])
            if current is None:
                if identity["pgid"] == identity["pid"] and _group_alive(identity["pgid"]):
                    unresolved.append(identifier)
                continue
            if current != identity or identity["pgid"] != identity["pid"] or identity["pgid"] == os.getpgrp():
                unresolved.append(identifier)
                continue
            try:
                os.killpg(identity["pgid"], signal.SIGKILL)
                signaled.append(identifier)
            except ProcessLookupError:
                pass
            except OSError:
                unresolved.append(identifier)
        return {"signaled": signaled, "unresolved": unresolved}

# Controlled runner shares the same admission fence as Worker registration.
from contextvars import ContextVar
_execution_context: ContextVar[tuple[str | Path, str, str] | None] = ContextVar('cogito_controlled_execution', default=None)

@contextmanager
def controlled_executor(root, run_id, identifier):
    token = _execution_context.set((root, run_id, identifier))
    try:
        yield
    finally:
        _execution_context.reset(token)

def execution_context():
    return _execution_context.get()

def stop_deadline(root, run_id):
    data = _load(_path(root, run_id), run_id)
    return data['stop_request']['deadline'] if data['stop_request'] else None

def begin_generation(root, run_id, recovery_id):
    """Archive terminal executor identities before an explicitly authorized resume."""
    from cogito_common import atomic_create_json
    _safe_id(recovery_id)
    archive = _path(root, run_id).parent / 'execution-generations' / (recovery_id+'.json')
    with _locked(root, run_id) as (path, data):
        if data.get('generation') == recovery_id:
            return
        # No lock recursion: inspect each registered executor through a copied record.
        for entry in data['entries'].values():
            if entry['kind']=='external':
                if not entry.get('receipt'): raise CogitoError('external executor has not stopped')
            else:
                identity=entry['identity']
                if process_identity(identity['pid']) is not None or identity['pid']!=identity['pgid'] or _group_alive(identity['pgid']):
                    raise CogitoError('executor has not stopped')
        if not atomic_create_json(archive,data) and load_json(archive)!=data:
            raise CogitoError('executor generation changed during recovery')
        atomic_write_json(path,dict(schema_version=1,run_id=run_id,stop_request=None,entries={},generation=recovery_id))
