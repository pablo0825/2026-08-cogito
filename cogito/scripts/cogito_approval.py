"""Publication transaction for an already validated Package approval."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cogito_state_types import RunState
from cogito_common import (
    CogitoError, atomic_create_json, atomic_write_json, load_json,
)
from cogito_contracts import package_hash
from cogito_projection import reduce_events


@dataclass(frozen=True)
class ApprovalArtifacts:
    """Canonical artifacts and the Project Graph state before publication."""

    package_path: Path
    package: Mapping[str, Any]
    graph_path: Path
    graph: Mapping[str, Any]
    graph_before: bytes | None


def restore_approval_permissions(package_path: Path) -> None:
    """Finish the recoverable permission step for a recorded approval."""
    try:
        package_path.chmod(0o444)
    except OSError as exc:
        raise CogitoError(
            "Package approval is recorded, but its file could not be made read-only; "
            "retry with the same action_id after resolving the storage error"
        ) from exc


def publish_approval(
    artifacts: ApprovalArtifacts,
    *,
    prior_state: RunState,
    workflow: Mapping[str, Any],
    load_events: Callable[[], Sequence[Mapping[str, Any]]],
    record_approval: Callable[[], RunState],
) -> RunState:
    """Publish artifacts, record the commit point, and recover conservatively."""
    package_created = False
    graph_write_attempted = False
    try:
        package_created = atomic_create_json(artifacts.package_path, artifacts.package)
        if (not package_created
                and package_hash(load_json(artifacts.package_path))
                != package_hash(artifacts.package)):
            raise CogitoError("canonical immutable Package already exists with different content")
        graph_write_attempted = True
        atomic_write_json(artifacts.graph_path, artifacts.graph)
        state = record_approval()
        artifacts.package_path.chmod(0o444)
        return state
    except Exception as exc:
        # The event may already be durable even if the callback failed while
        # refreshing its cache. Only authoritative history can permit rollback.
        try:
            history = list(load_events())
            reduce_events(history, workflow)
            sequence = prior_state["sequence"]
            if (len(history) < sequence
                    or history[sequence - 1]["event_hash"] != prior_state["last_event_hash"]):
                raise CogitoError("event history no longer contains the pre-approval state")
        except Exception as history_error:
            raise CogitoError(
                "cannot determine Package approval outcome; artifacts were preserved; "
                "inspect event history before retrying"
            ) from history_error
        if any(item["type"] == "package-approved" for item in history):
            raise CogitoError(
                "Package approval is recorded; artifacts were preserved, but follow-up "
                "work failed; retry with the same action_id after resolving the error: "
                f"{exc}"
            ) from exc
        _rollback_uncommitted_approval(
            artifacts, package_created,
            artifacts.graph if graph_write_attempted else None,
        )
        raise CogitoError(f"Package approval was not recorded: {exc}") from exc


def _rollback_uncommitted_approval(
    artifacts: ApprovalArtifacts,
    package_created: bool,
    attempted_graph: Mapping[str, Any] | None,
) -> None:
    """Undo only artifacts that still match this uncommitted transaction."""
    try:
        if attempted_graph is not None:
            actual = artifacts.graph_path.read_bytes() if artifacts.graph_path.exists() else None
            if actual != artifacts.graph_before:
                if actual is None or json.loads(actual) != attempted_graph:
                    raise CogitoError("Project Graph changed during approval recovery")
                if artifacts.graph_before is None:
                    artifacts.graph_path.unlink()
                else:
                    artifacts.graph_path.write_bytes(artifacts.graph_before)
        if package_created:
            artifacts.package_path.unlink()
    except (OSError, ValueError) as exc:
        raise CogitoError(
            f"Package approval was not recorded, but cleanup is incomplete; inspect artifacts: {exc}"
        ) from exc
