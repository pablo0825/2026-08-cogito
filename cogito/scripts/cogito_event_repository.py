"""Run event persistence and reconstruction of the disposable state cache."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cogito_state_types import RunState
from cogito_common import CogitoError, atomic_write_json, load_json
from cogito_events import append_event, read_events
from cogito_projection import project_events


@dataclass(frozen=True)
class EventSnapshot:
    """History and state derived from the same read of the event log."""

    events: list[dict[str, Any]]
    state: RunState


class EventRepository:
    def __init__(self, events_path: Path, state_path: Path, workflow: Mapping[str, Any]):
        self.events_path = events_path
        self.state_path = state_path
        self.workflow = workflow

    def read(self) -> list[dict[str, Any]]:
        return read_events(self.events_path)

    def exists(self) -> bool:
        """Preserve the distinction between absent and existing empty storage."""
        return self.events_path.exists()

    def is_initialized(self) -> bool:
        """A file is initialized storage, even if its event history is empty."""
        return self.events_path.is_file()

    def project(self) -> RunState:
        """Rebuild authoritative state without reading or repairing the cache."""
        return self.snapshot().state

    def snapshot(self) -> EventSnapshot:
        """Collect one authoritative view without repairing the state cache."""
        events = self.read()
        return EventSnapshot(events, project_events(events, self.workflow))

    def refresh_cache(self, projection: RunState) -> None:
        """Repair only disposable state; callers first validate any frozen artifacts."""
        try:
            cached = load_json(self.state_path)
        except CogitoError:
            cached = None
        if cached != projection:
            try:
                atomic_write_json(self.state_path, projection)
            except OSError as exc:
                raise CogitoError(
                    "state cache could not be refreshed; event history is unchanged; "
                    "retry with the same action_id after resolving the storage error"
                ) from exc

    def create(self, event: Mapping[str, Any]) -> RunState:
        """Record the initial event after the coordinator creates the run directory."""
        append_event(self.events_path, event)
        return self._project_and_refresh()

    def append(self, event: Mapping[str, Any], *, expected_previous_hash: str | None = None) -> RunState:
        """Validate against current history, append with CAS, then rebuild the cache.

        A failure after append can leave a committed event. Recovery must inspect
        authoritative history rather than treating cache failure as rollback.
        """
        existing = self.read()
        expected = existing[-1]["event_hash"] if existing else "0" * 64
        if expected_previous_hash is not None and expected != expected_previous_hash:
            raise CogitoError("event history changed during validation; retry with the same action_id")
        project_events([*existing, dict(event)], self.workflow)
        append_event(self.events_path, event, expected)
        return self._project_and_refresh()

    def _project_and_refresh(self) -> RunState:
        projection = self.project()
        self.refresh_cache(projection)
        return projection
