"""Run event persistence and reconstruction of the disposable state cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cogito_common import CogitoError, atomic_write_json, load_json
from cogito_events import append_event, read_events
from cogito_projection import reduce_events


class EventRepository:
    def __init__(self, events_path: Path, state_path: Path, workflow: Mapping[str, Any]):
        self.events_path = events_path
        self.state_path = state_path
        self.workflow = workflow

    def read(self) -> list[dict[str, Any]]:
        return read_events(self.events_path)

    def project(self) -> dict[str, Any]:
        """Rebuild authoritative state without reading or repairing the cache."""
        return reduce_events(self.read(), self.workflow)

    def refresh_cache(self, projection: Mapping[str, Any]) -> None:
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

    def create(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Record the initial event after the coordinator creates the run directory."""
        append_event(self.events_path, event)
        return self._project_and_refresh()

    def append(self, event: Mapping[str, Any]) -> dict[str, Any]:
        """Validate against current history, append with CAS, then rebuild the cache.

        A failure after append can leave a committed event. Recovery must inspect
        authoritative history rather than treating cache failure as rollback.
        """
        existing = self.read()
        reduce_events([*existing, dict(event)], self.workflow)
        expected = existing[-1]["event_hash"] if existing else "0" * 64
        append_event(self.events_path, event, expected)
        return self._project_and_refresh()

    def _project_and_refresh(self) -> dict[str, Any]:
        projection = self.project()
        self.refresh_cache(projection)
        return projection
