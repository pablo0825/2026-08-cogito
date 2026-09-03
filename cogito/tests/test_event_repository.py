"""Event history is authoritative; cache updates and competing writers cannot rewrite it."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, load_json
from cogito_event_repository import EventRepository
from cogito_events import append_event
from cogito_workflow import load_workflow


class EventRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.events_path = root / "events.jsonl"
        self.state_path = root / "state.json"
        self.repository = EventRepository(self.events_path, self.state_path, load_workflow())
        self.initial = self.repository.create({
            "type": "run-created", "payload": {"run_id": "DEV-repository", "kind": "feature"},
        })
        self.candidate = {
            "type": "shared-understanding-ready", "payload": {"shared_understanding_hash": "a" * 64},
        }

    def test_invalid_candidate_does_not_change_history_or_cache(self) -> None:
        history_before = self.events_path.read_bytes()
        cache_before = self.state_path.read_bytes()
        with self.assertRaises(CogitoError):
            self.repository.append({"type": "human-approved", "payload": {"approved": True}})
        self.assertEqual(self.events_path.read_bytes(), history_before)
        self.assertEqual(self.state_path.read_bytes(), cache_before)

    def test_matching_cache_is_not_rewritten_and_project_does_not_repair_missing_cache(self) -> None:
        self.assertEqual(load_json(self.state_path), self.initial)
        with mock.patch("cogito_event_repository.atomic_write_json") as write:
            self.repository.refresh_cache(self.initial)
            write.assert_not_called()
            self.state_path.unlink()
            self.assertEqual(self.repository.project(), self.initial)
            write.assert_not_called()
            self.assertFalse(self.state_path.exists())
        self.repository.refresh_cache(self.initial)
        self.assertEqual(load_json(self.state_path), self.initial)

    def test_competing_event_wins_cas_without_appending_the_stale_candidate(self) -> None:
        cache_before = self.state_path.read_bytes()
        winner = {"type": "block", "payload": {"reason": "another writer blocked the run"}}

        def append_after_competitor(path, event, expected_previous_hash=None):
            append_event(path, winner)
            return append_event(path, event, expected_previous_hash)

        with mock.patch("cogito_event_repository.append_event", side_effect=append_after_competitor):
            with self.assertRaisesRegex(CogitoError, "history changed"):
                self.repository.append(self.candidate)
        self.assertEqual([item["type"] for item in self.repository.read()], ["run-created", "block"])
        self.assertEqual(self.repository.project()["state"], "blocked")
        self.assertEqual(self.state_path.read_bytes(), cache_before)

    def test_cache_write_failure_leaves_a_durable_event_that_can_be_projected_and_repaired(self) -> None:
        cache_before = self.state_path.read_bytes()
        with mock.patch("cogito_event_repository.atomic_write_json", side_effect=OSError("injected cache failure")):
            with self.assertRaisesRegex(CogitoError, "cache"):
                self.repository.append(self.candidate)
        history_before_repair = self.events_path.read_bytes()
        self.assertEqual([item["type"] for item in self.repository.read()], ["run-created", "shared-understanding-ready"])
        self.assertEqual(self.state_path.read_bytes(), cache_before)
        projection = self.repository.project()
        self.assertEqual(projection["state"], "awaiting-shared-confirmation")
        self.assertEqual(self.state_path.read_bytes(), cache_before)
        self.repository.refresh_cache(projection)
        self.assertEqual(load_json(self.state_path), projection)
        self.assertEqual(self.events_path.read_bytes(), history_before_repair)


if __name__ == "__main__":
    unittest.main()
