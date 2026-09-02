"""Executable shape and internal-consistency contract for check evidence."""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

from cogito_common import ID_RE, CogitoError
from cogito_contracts import MAX_MAX_CHECK_OUTPUT_BYTES, MIN_MAX_CHECK_OUTPUT_BYTES


REQUIRED_FIELDS = frozenset({
    "schema_version", "run_id", "check_id", "status", "passed", "exit_code",
    "timed_out", "output_limit_exceeded", "termination_degraded",
    "output_limit_bytes", "stdout_bytes", "stderr_bytes", "duration_seconds",
    "started_at", "head_commit", "tree_hash", "worktree_snapshot_hash",
    "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash",
    "worktree_changed_during_check", "worktree_binding", "check_hash",
    "effective_contract_hash", "argv", "cwd", "stdout", "stderr", "truncated",
    "evidence_path",
})
ALLOWED_FIELDS = REQUIRED_FIELDS
RUN_ID_RE = re.compile(r"^(?:DEV|MNT)-[A-Za-z0-9._-]+$")
GIT_OBJECT_RE = re.compile(r"^[0-9a-f]{7,64}$")
CONTENT_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _require_boolean(evidence: Mapping[str, Any], field: str) -> None:
    if type(evidence[field]) is not bool:
        raise CogitoError(f"check evidence {field} must be a boolean")


def _require_integer(
    evidence: Mapping[str, Any], field: str, minimum: int, maximum: int | None = None
) -> None:
    value = evidence[field]
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        suffix = f" through {maximum}" if maximum is not None else f" or greater"
        raise CogitoError(f"check evidence {field} must be an integer {minimum}{suffix}")


def _require_string(evidence: Mapping[str, Any], field: str, *, nonempty: bool = False) -> None:
    value = evidence[field]
    if not isinstance(value, str) or (nonempty and not value):
        raise CogitoError(f"check evidence {field} must be a{' non-empty' if nonempty else ''} string")


def validate_check_evidence(evidence: Any) -> None:
    """Validate one final controlled-runner evidence record without external state."""
    if not isinstance(evidence, dict):
        raise CogitoError("check evidence must be an object")
    missing = REQUIRED_FIELDS - set(evidence)
    if missing:
        raise CogitoError(f"check evidence is missing fields: {sorted(missing)}")
    unknown = set(evidence) - ALLOWED_FIELDS
    if unknown:
        raise CogitoError(f"check evidence has unknown fields: {sorted(unknown)}")

    if evidence["schema_version"] != "3.0":
        raise CogitoError("check evidence schema_version must be 3.0")
    if not isinstance(evidence["run_id"], str) or not RUN_ID_RE.fullmatch(evidence["run_id"]):
        raise CogitoError("check evidence run_id is invalid")
    if not isinstance(evidence["check_id"], str) or not ID_RE.fullmatch(evidence["check_id"]):
        raise CogitoError("check evidence check_id is invalid")
    if not isinstance(evidence["status"], str) or evidence["status"] not in {"passed", "failed"}:
        raise CogitoError("check evidence status must be passed or failed")

    for field in (
        "passed", "timed_out", "output_limit_exceeded", "termination_degraded",
        "worktree_changed_during_check", "truncated",
    ):
        _require_boolean(evidence, field)
    exit_code = evidence["exit_code"]
    if exit_code is not None and type(exit_code) is not int:
        raise CogitoError("check evidence exit_code must be an integer or null")
    _require_integer(
        evidence, "output_limit_bytes", MIN_MAX_CHECK_OUTPUT_BYTES,
        MAX_MAX_CHECK_OUTPUT_BYTES,
    )
    _require_integer(evidence, "stdout_bytes", 0)
    _require_integer(evidence, "stderr_bytes", 0)
    duration = evidence["duration_seconds"]
    if type(duration) not in {int, float} or duration < 0 or not math.isfinite(duration):
        raise CogitoError("check evidence duration_seconds must be a finite non-negative number")

    for field in ("started_at", "evidence_path"):
        _require_string(evidence, field, nonempty=True)
    for field in ("cwd", "stdout", "stderr"):
        _require_string(evidence, field)
    if not isinstance(evidence["head_commit"], str) or not GIT_OBJECT_RE.fullmatch(evidence["head_commit"]):
        raise CogitoError("check evidence head_commit is invalid")
    for field in (
        "tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash",
        "post_worktree_snapshot_hash", "check_hash", "effective_contract_hash",
    ):
        if not isinstance(evidence[field], str) or not CONTENT_HASH_RE.fullmatch(evidence[field]):
            raise CogitoError(f"check evidence {field} is invalid")
    if not isinstance(evidence["worktree_binding"], dict):
        raise CogitoError("check evidence worktree_binding must be an object")
    argv = evidence["argv"]
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) for arg in argv):
        raise CogitoError("check evidence argv must be a non-empty string array")

    passed = evidence["passed"]
    if (evidence["status"] == "passed") != passed:
        raise CogitoError("check evidence status and passed disagree")
    if evidence["worktree_changed_during_check"] != (
        evidence["pre_worktree_snapshot_hash"] != evidence["post_worktree_snapshot_hash"]
    ):
        raise CogitoError("check evidence worktree change flag disagrees with its snapshots")
    if evidence["post_worktree_snapshot_hash"] != evidence["worktree_snapshot_hash"]:
        raise CogitoError("check evidence final worktree snapshots disagree")
    if evidence["worktree_snapshot_hash"] != evidence["tree_hash"]:
        raise CogitoError("check evidence tree hash disagrees with its worktree snapshot")
    if passed and (
        exit_code != 0
        or evidence["timed_out"]
        or evidence["output_limit_exceeded"]
        or evidence["termination_degraded"]
        or evidence["worktree_changed_during_check"]
    ):
        raise CogitoError("passed check evidence contains a failing execution condition")
