"""Pure evidence construction from captured process and worktree facts."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from cogito_common import hash_json
from cogito_process_capture import ProcessCapture


def _redact(text: str, patterns: Sequence[str]) -> str:
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def build_evidence(
    *, run_id: str, check_id: str, check: Mapping[str, Any],
    effective_contract_hash: str, capture: ProcessCapture,
    pre_binding: Mapping[str, Any], post_binding: Mapping[str, Any],
    started_at: str, duration_seconds: float, cwd: str, output_limit_bytes: int,
) -> dict[str, Any]:
    """Derive a detached evidence record without executing or reading anything.

    The runner supplies a validated check, bounded output, both worktree
    snapshots, and timing facts. Output byte counts describe capture before
    decoding and redaction; diagnostic truncation alone does not fail a check.
    """
    stdout = capture.stdout.decode("utf-8", errors="replace")
    stderr = capture.stderr.decode("utf-8", errors="replace")
    patterns = check.get("redact_patterns", [])
    stdout, stderr = _redact(stdout, patterns), _redact(stderr, patterns)
    worktree_changed = pre_binding["snapshot_hash"] != post_binding["snapshot_hash"]
    passed = (
        capture.exit_code == 0
        and not capture.timed_out
        and not capture.output_limit_exceeded
        and not capture.termination_degraded
        and not worktree_changed
    )
    return {
        "schema_version": "3.0", "run_id": run_id, "check_id": check_id,
        "status": "passed" if passed else "failed", "passed": passed,
        "exit_code": capture.exit_code, "timed_out": capture.timed_out,
        "output_limit_exceeded": capture.output_limit_exceeded,
        "termination_degraded": capture.termination_degraded,
        "output_limit_bytes": output_limit_bytes,
        "stdout_bytes": capture.stdout_bytes, "stderr_bytes": capture.stderr_bytes,
        "duration_seconds": round(duration_seconds, 6),
        "started_at": started_at, "head_commit": post_binding["head_commit"],
        "tree_hash": post_binding["snapshot_hash"],
        "worktree_snapshot_hash": post_binding["snapshot_hash"],
        "pre_worktree_snapshot_hash": pre_binding["snapshot_hash"],
        "post_worktree_snapshot_hash": post_binding["snapshot_hash"],
        "worktree_changed_during_check": worktree_changed,
        "worktree_binding": deepcopy(dict(post_binding)), "check_hash": hash_json(check),
        "effective_contract_hash": effective_contract_hash,
        "argv": deepcopy(check["argv"]), "cwd": cwd,
        "stdout": stdout, "stderr": stderr,
        "truncated": capture.stdout_truncated or capture.stderr_truncated or capture.output_limit_exceeded,
    }
