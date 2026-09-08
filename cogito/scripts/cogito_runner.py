#!/usr/bin/env python3
"""Controlled argv-only verification runner for Cogito 3.0."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cogito_common import ID_RE, CogitoError, atomic_create_json, hash_json
from cogito_contracts import (
    DEFAULT_MAX_CHECK_OUTPUT_BYTES,
    materialize_contract_with_limits,
    validate_check_environment,
)
from cogito_evidence_binding import (
    safe_cwd as _safe_cwd,
    working_tree_binding as _working_tree_binding,
)
from cogito_evidence_contract import validate_check_evidence
from cogito_process_capture import run_bounded_process
from cogito_runner_evidence import build_evidence
from cogito_workflow import load_workflow

OUTPUT_CAP = 64 * 1024
BASE_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PATHEXT")


class EvidenceAlreadyExists(CogitoError):
    """Raised when another writer has already published an evidence record."""

    def __init__(self, path: Path):
        super().__init__("immutable evidence record already exists")
        self.path = path


class PreExecutionSnapshotError(CogitoError):
    """Only the snapshot before invoking the check may produce this proof."""


def validate_check_target(package, state, check_id, worktree, root):
    """Shared legal checkout selection for execution and advisory recovery."""
    if state['state'] in {'post-integration-verification', 'human-correction-verifying'}:
        if worktree != root:
            raise CogitoError('post-integration checks must run in the delivery checkout')
    elif state['state'] == 'verifying':
        eligible = {Path(str(t.get('worktree', ''))).resolve() for t in state['tasks'].values()
                    if t.get('status') == 'complete'}
        if worktree not in eligible:
            raise CogitoError('verification checks must run in a completed Package Slice worktree')
    elif package.get('task_delivery') == 'atomic' and state['state'] in {
            'executing', 'technical-correction', 'review-fix', 'post-integration-correction', 'human-correction'}:
        active = [t for t in state['tasks'].values() if t.get('status') == 'running'
                  and Path(str(t.get('worktree', ''))).resolve() == worktree and check_id in t.get('check_ids', [])]
        if len(active) != 1:
            raise CogitoError("task checks require the running task's checkout and targeted check ID")
    else:
        raise CogitoError('controlled checks are not legal in the current state')


def preflight_check(package: Mapping[str, Any], check: Mapping[str, Any], worktree: Path) -> None:
    """Probe required capabilities before an attempt is marked as started.

    This is not execution evidence. The runner must repeat its snapshots and
    register the actual child at launch. Optional environment names are not
    interpreted as required settings.
    """
    from cogito_evidence_binding import working_tree_binding
    from cogito_execution_registry import process_identity, _group_alive

    try:
        validate_check_environment(check, package["policy_snapshot"].get("allowed_environment", []))
        _safe_cwd(worktree, str(check.get("cwd", ".")))
        identity = process_identity(os.getpid())
        if identity is None or not _group_alive(identity["pgid"]):
            raise CogitoError("runner process identity/group is unavailable")
        working_tree_binding(worktree)
    except (CogitoError, OSError) as exc:
        raise CogitoError("check preflight rejected before start; repair the environment and resend "
                          "the same action ID and inputs: " + str(exc)) from exc


def run_check(
    package: Mapping[str, Any], check_id: str, worktree: str | Path,
    amendments: Sequence[Mapping[str, Any]] = (), output_cap: int = OUTPUT_CAP,
    *, workflow_limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    limits = load_workflow()["limits"] if workflow_limits is None else workflow_limits
    effective = materialize_contract_with_limits(package, amendments, limits)
    matching = [item for item in effective["checks"] if item.get("id") == check_id]
    if len(matching) != 1:
        raise CogitoError(f"expected exactly one check named {check_id!r}")
    check = matching[0]
    validate_check_environment(
        check, package["policy_snapshot"].get("allowed_environment", [])
    )
    # Package and Amendment checks passed the same executable check contract.
    argv = check["argv"]
    timeout = check.get("timeout_seconds", 300)
    cap = max(1024, min(int(output_cap), 1024 * 1024))
    worktree = Path(worktree).resolve()
    cwd = _safe_cwd(worktree, str(check.get("cwd", ".")))
    allowed = set(BASE_ENV) | set(check.get("env_allowlist", []))
    env = {key: value for key, value in os.environ.items() if key in allowed}
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    try:
        pre_binding = _working_tree_binding(worktree)
    except (CogitoError, OSError) as exc:
        raise PreExecutionSnapshotError('pre-execution snapshot failed; check command was not started: ' + str(exc)) from exc
    output_limit = int(
        package["policy_snapshot"].get(
            "max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES
        )
    )
    capture = run_bounded_process(
        argv,
        cwd=cwd,
        env=env,
        timeout_seconds=timeout,
        evidence_cap=cap,
        output_limit=output_limit,
    )
    duration = time.monotonic() - start
    post_binding = _working_tree_binding(worktree)
    return build_evidence(
        run_id=package["run_id"], check_id=check_id, check=check,
        effective_contract_hash=effective["effective_contract_hash"], capture=capture,
        pre_binding=pre_binding, post_binding=post_binding,
        started_at=started_at, duration_seconds=duration,
        cwd=str(cwd.relative_to(worktree)) or ".", output_limit_bytes=output_limit,
    )


def write_evidence_once(directory: str | Path, record_id: str, evidence: Mapping[str, Any]) -> Path:
    if not ID_RE.fullmatch(record_id):
        raise CogitoError("evidence record id is not a safe filename")
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / f"{record_id}.json").resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:  # defensive in case identifier policy changes
        raise CogitoError("evidence path escapes evidence directory") from exc
    value = dict(evidence)
    value["evidence_path"] = str(destination)
    validate_check_evidence(value)
    if not atomic_create_json(destination, value):
        raise EvidenceAlreadyExists(destination)
    return destination


def _object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CogitoError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CogitoError(f"{path} must contain an object")
    return value


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-check")
    run.add_argument("--package", required=True)
    run.add_argument("--check-id", required=True)
    run.add_argument("--worktree", required=True)
    run.add_argument("--evidence-dir", required=True)
    run.add_argument("--amendment", action="append", default=[])
    run.add_argument("--output-cap", type=int, default=OUTPUT_CAP)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        evidence = run_check(
            _object(args.package), args.check_id, args.worktree,
            [_object(path) for path in args.amendment], args.output_cap,
        )
        destination = Path(args.evidence_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if not ID_RE.fullmatch(args.check_id):
            raise CogitoError("check id is not safe for evidence storage")
        content_hash = hash_json(evidence)
        record_id = f"{args.check_id}-{evidence['head_commit'][:12]}-{evidence['effective_contract_hash'][:12]}-{content_hash[:12]}"
        evidence_path = write_evidence_once(destination, record_id, evidence)
    except CogitoError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "evidence": str(evidence_path), "status": evidence["status"]}, ensure_ascii=False))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
