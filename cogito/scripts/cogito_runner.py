#!/usr/bin/env python3
"""Controlled argv-only verification runner for Cogito 3.0."""

from __future__ import annotations

import argparse
import json
import os
import re
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
    materialize_contract,
    validate_check_environment,
    validate_package,
)
from cogito_evidence_binding import (
    safe_cwd as _safe_cwd,
    safe_file as _safe_file,
    working_tree_binding as _working_tree_binding,
)
from cogito_evidence_contract import validate_check_evidence
from cogito_process_capture import run_bounded_process

OUTPUT_CAP = 64 * 1024
BASE_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PATHEXT")


class EvidenceAlreadyExists(CogitoError):
    """Raised when another writer has already published an evidence record."""

    def __init__(self, path: Path):
        super().__init__("immutable evidence record already exists")
        self.path = path


def _redact(text: str, patterns: Sequence[str]) -> str:
    for pattern in patterns:
        try:
            text = re.sub(pattern, "[REDACTED]", text)
        except re.error as exc:
            raise CogitoError(f"invalid redaction pattern: {exc}") from exc
    return text


def run_check(
    package: Mapping[str, Any], check_id: str, worktree: str | Path,
    amendments: Sequence[Mapping[str, Any]] = (), output_cap: int = OUTPUT_CAP,
) -> dict[str, Any]:
    validate_package(package)
    effective = materialize_contract(package, amendments)
    matching = [item for item in effective["checks"] if item.get("id") == check_id]
    if len(matching) != 1:
        raise CogitoError(f"expected exactly one check named {check_id!r}")
    check = matching[0]
    validate_check_environment(
        check, package["policy_snapshot"].get("allowed_environment", [])
    )
    argv = check.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise CogitoError("check argv must be a non-empty string array")
    timeout = int(check.get("timeout_seconds", 300))
    if not 1 <= timeout <= 3600:
        raise CogitoError("timeout_seconds must be between 1 and 3600")
    cap = max(1024, min(int(output_cap), 1024 * 1024))
    worktree = Path(worktree).resolve()
    cwd = _safe_cwd(worktree, str(check.get("cwd", ".")))
    allowed = set(BASE_ENV) | set(check.get("env_allowlist", []))
    env = {key: value for key, value in os.environ.items() if key in allowed}
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    pre_binding = _working_tree_binding(worktree)
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
    stdout = capture.stdout.decode("utf-8", errors="replace")
    stderr = capture.stderr.decode("utf-8", errors="replace")
    patterns = check.get("redact_patterns", [])
    if not isinstance(patterns, list):
        raise CogitoError("redact_patterns must be an array")
    stdout, stderr = _redact(stdout, patterns), _redact(stderr, patterns)
    post_binding = _working_tree_binding(worktree)
    worktree_changed = pre_binding["snapshot_hash"] != post_binding["snapshot_hash"]
    passed = (
        capture.exit_code == 0
        and not capture.timed_out
        and not capture.output_limit_exceeded
        and not worktree_changed
    )
    evidence = {
        "schema_version": "3.0", "run_id": package["run_id"], "check_id": check_id,
        "status": "passed" if passed else "failed", "passed": passed,
        "exit_code": capture.exit_code, "timed_out": capture.timed_out,
        "output_limit_exceeded": capture.output_limit_exceeded,
        "termination_degraded": capture.termination_degraded,
        "output_limit_bytes": output_limit,
        "stdout_bytes": capture.stdout_bytes, "stderr_bytes": capture.stderr_bytes,
        "duration_seconds": round(duration, 6),
        "started_at": started_at, "head_commit": post_binding["head_commit"],
        "tree_hash": post_binding["snapshot_hash"],
        "worktree_snapshot_hash": post_binding["snapshot_hash"],
        "pre_worktree_snapshot_hash": pre_binding["snapshot_hash"],
        "post_worktree_snapshot_hash": post_binding["snapshot_hash"],
        "worktree_changed_during_check": worktree_changed,
        "worktree_binding": post_binding, "check_hash": hash_json(check),
        "effective_contract_hash": effective["effective_contract_hash"],
        "argv": argv, "cwd": str(cwd.relative_to(worktree)) or ".",
        "stdout": stdout, "stderr": stderr,
        "truncated": capture.stdout_truncated or capture.stderr_truncated or capture.output_limit_exceeded,
    }
    return evidence


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
    except (OSError, json.JSONDecodeError) as exc:
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
