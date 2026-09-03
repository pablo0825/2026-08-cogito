"""Narrow structural interfaces for the Gate's event and Git dependencies."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Protocol

from cogito_event_repository import EventSnapshot
from cogito_state_types import RunState


class EventRepositoryPort(Protocol):
    def exists(self) -> bool:
        """Whether backing storage exists, including an empty event log."""
        ...

    def is_initialized(self) -> bool:
        """Whether backing storage can hold events; an empty log still qualifies."""
        ...

    def read(self) -> list[dict[str, Any]]: ...

    def project(self) -> RunState: ...

    def snapshot(self) -> EventSnapshot: ...

    def refresh_cache(self, projection: RunState) -> None: ...

    def create(self, event: Mapping[str, Any]) -> RunState: ...

    def append(
        self, event: Mapping[str, Any], *, expected_previous_hash: str | None = None,
    ) -> RunState: ...


class GitRepositoryPort(Protocol):
    def read_blob(self, commit_id: str, path: str) -> bytes: ...

    def run(self, *args: str) -> str: ...

    def run_at(self, directory: str | Path, *args: str) -> str: ...
