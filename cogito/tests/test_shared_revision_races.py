"""Shared Understanding publication and confirmation retain one history anchor."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_run_store import RunStore


class SharedRevisionRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = RunStore(self.root, "DEV-shared-races")
        self.store.create("feature")
        self.store.transition("shared-understanding-ready", {
            "shared_understanding_hash": "a" * 64,
        }, "initial-ready")

    def race(self, pending_event: str, pending_payload: dict,
             winner_event: str, winner_payload: dict) -> None:
        original_append = self.store._events.append
        competitor = RunStore(self.root, self.store.run_id)

        def append_after_competitor(event, *, expected_previous_hash=None):
            competitor.transition(winner_event, winner_payload, "winner")
            return original_append(event, expected_previous_hash=expected_previous_hash)

        with mock.patch.object(self.store._events, "append", side_effect=append_after_competitor):
            with self.assertRaisesRegex(CogitoError, "history changed"):
                self.store.transition(pending_event, pending_payload, "loser")
        history = self.store._events.read()
        self.assertEqual(history[-1]["action_id"], "winner")
        self.assertNotIn("loser", [event.get("action_id") for event in history])

    def test_confirmation_cannot_commit_over_a_newer_revision(self) -> None:
        self.race(
            "shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": "a" * 64},
            "shared-understanding-ready", {"shared_understanding_hash": "b" * 64},
        )
        state = self.store.load()
        self.assertEqual(state["state"], "awaiting-shared-confirmation")
        self.assertEqual(state["shared_understanding_hash"], "b" * 64)

    def test_revision_cannot_commit_after_confirmation(self) -> None:
        self.race(
            "shared-understanding-ready", {"shared_understanding_hash": "b" * 64},
            "shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": "a" * 64},
        )
        state = self.store.load()
        self.assertEqual(state["state"], "boundary-analysis")
        self.assertEqual(state["shared_understanding_hash"], "a" * 64)

    def test_delayed_revision_cannot_overwrite_a_competing_revision(self) -> None:
        self.race(
            "shared-understanding-ready", {"shared_understanding_hash": "b" * 64},
            "shared-understanding-ready", {"shared_understanding_hash": "c" * 64},
        )
        self.assertEqual(self.store.load()["shared_understanding_hash"], "c" * 64)
        # CAS rejection did not consume the action id: a deliberate fresh retry
        # can publish after reading the winner's state.
        retried = self.store.transition("shared-understanding-ready", {
            "shared_understanding_hash": "b" * 64,
        }, "loser")
        self.assertEqual(retried["shared_understanding_hash"], "b" * 64)

    def test_record_api_cannot_bypass_revision_confirmation_binding(self) -> None:
        self.store.transition("shared-understanding-ready", {
            "shared_understanding_hash": "b" * 64,
        }, "revised-ready")
        before = self.store.events_path.read_bytes()
        for payload in ({"confirmed": True},
                        {"confirmed": True, "shared_understanding_hash": "a" * 64}):
            with self.subTest(payload=payload):
                with self.assertRaises(CogitoError):
                    self.store.record("shared-understanding-confirmed", payload)
                self.assertEqual(self.store.events_path.read_bytes(), before)
        state = self.store.record("shared-understanding-confirmed", {
            "confirmed": True, "shared_understanding_hash": "b" * 64,
        })
        self.assertEqual(state["state"], "boundary-analysis")


if __name__ == "__main__":
    unittest.main()
