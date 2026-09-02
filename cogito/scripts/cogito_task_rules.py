"""Shared pure rules for task Slice identity, activity, and prerequisites."""

from __future__ import annotations

from typing import Any, Mapping


def effective_slice_id(task: Mapping[str, Any]) -> str:
    """Treat omitted or empty Slice IDs as the single Mini Package Slice."""
    return task.get("slice_id") or "mini-package"


def is_active_task(task: Mapping[str, Any]) -> bool:
    """A leased or running task occupies its Slice's worker slot."""
    return task.get("status") in {"leased", "running"}


def dependency_satisfied(
    predecessor: Mapping[str, Any], task: Mapping[str, Any],
) -> bool:
    """Same-Slice work may follow completion; cross-Slice work needs integration."""
    if effective_slice_id(predecessor) == effective_slice_id(task):
        return predecessor.get("status") in {"complete", "verified", "reviewed", "integrated"}
    return predecessor.get("status") == "integrated"
