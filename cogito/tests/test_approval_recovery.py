"""Approval commit boundary and recovery of disposable state caches."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_events import append_event, read_events
from cogito_run_store import RunStore
from cogito_test_support import minimal_package


class ApprovalRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cogito-approval-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = minimal_package()
        self.store = RunStore(self.root, self.package["run_id"])
        self.store.create("feature")
        self.store.transition("shared-understanding-ready", {
            "shared_understanding_hash": self.package["shared_understanding"]["hash"],
        })
        self.store.transition("shared-understanding-confirmed", {"confirmed": True})
        self.store.transition("boundary-complete", self.package["boundary"])
        self.store.prepare_package(self.package, "candidate")
        self.graph_path = self.root / "docs/cogito/project-graph.json"
        self.package_path = self.root / "docs/cogito/packages" / f"{self.store.run_id}.json"
        self.old_graph = {
            "schema_version": "3.0", "active_run_id": None,
            "slices": {}, "dependencies": [],
        }
        atomic_write_json(self.graph_path, self.old_graph)
        self.graph_before = self.graph_path.read_bytes()
        self.events_before = self.store.events_path.read_bytes()

    def assert_approved_artifacts(self) -> dict:
        state = self.store.load()
        self.assertEqual(state["state"], "start-gate")
        self.assertEqual(hash_json(load_json(self.graph_path)), state["project_graph_hash"])
        self.assertEqual(self.store.approved_package()["package_hash"], state["package_hash"])
        return state

    def test_cache_write_failure_does_not_undo_committed_approval(self) -> None:
        def fail_cache(path, value):
            if path == self.store.state_path and value["state"] == "start-gate":
                raise OSError("injected cache write failure")
            atomic_write_json(path, value)

        with mock.patch("cogito_event_repository.atomic_write_json", side_effect=fail_cache):
            with self.assertRaisesRegex(CogitoError, "approval.*recorded"):
                self.store.approve_package(self.package, "approve")
        self.assertEqual(read_events(self.store.events_path)[-1]["type"], "package-approved")
        self.assertNotEqual(self.graph_path.read_bytes(), self.graph_before)
        state = self.store.approve_package(self.package, "approve")
        self.assertEqual(load_json(self.store.state_path), state)
        self.assertEqual(sum(e["type"] == "package-approved" for e in read_events(self.store.events_path)), 1)
        self.assertEqual(self.package_path.stat().st_mode & 0o222, 0)
        self.assert_approved_artifacts()

    def test_event_append_failure_before_commit_rolls_back_new_artifacts(self) -> None:
        with mock.patch("cogito_event_repository.append_event", side_effect=OSError("injected append failure")):
            with self.assertRaises(CogitoError):
                self.store.approve_package(self.package, "approve")
        self.assertFalse(self.package_path.exists())
        self.assertEqual(self.graph_path.read_bytes(), self.graph_before)
        self.assertEqual(self.store.events_path.read_bytes(), self.events_before)
        self.assertEqual(self.store.load()["state"], "awaiting-package-approval")
        self.store.approve_package(self.package, "approve")
        self.assert_approved_artifacts()

    def test_rollback_preserves_preexisting_package_bytes_and_permissions(self) -> None:
        atomic_write_json(self.package_path, self.package)
        package_before = self.package_path.read_bytes()
        mode_before = self.package_path.stat().st_mode
        with mock.patch("cogito_event_repository.append_event", side_effect=OSError("injected append failure")):
            with self.assertRaises(CogitoError):
                self.store.approve_package(self.package, "approve")
        self.assertEqual(self.package_path.read_bytes(), package_before)
        self.assertEqual(self.package_path.stat().st_mode, mode_before)
        self.assertEqual(self.graph_path.read_bytes(), self.graph_before)

    def test_append_that_records_then_raises_preserves_approval(self) -> None:
        def append_then_fail(*args, **kwargs):
            append_event(*args, **kwargs)
            raise OSError("injected error after append")

        with mock.patch("cogito_event_repository.append_event", side_effect=append_then_fail):
            with self.assertRaisesRegex(CogitoError, "approval.*recorded"):
                self.store.approve_package(self.package, "approve")
        self.store.approve_package(self.package, "approve")
        self.assert_approved_artifacts()

    def test_unknown_commit_outcome_leaves_artifacts_for_recovery(self) -> None:
        append_attempted = False

        def fail_append(*args, **kwargs):
            nonlocal append_attempted
            append_attempted = True
            raise OSError("injected append failure")

        def fail_read_after_append(path):
            if append_attempted:
                raise CogitoError("injected unreadable event history")
            return read_events(path)

        with mock.patch("cogito_event_repository.append_event", side_effect=fail_append), \
                mock.patch("cogito_run_store.read_events", side_effect=fail_read_after_append):
            with self.assertRaisesRegex(CogitoError, "cannot determine.*approval"):
                self.store.approve_package(self.package, "approve")
        self.assertTrue(self.package_path.exists())
        self.assertNotEqual(self.graph_path.read_bytes(), self.graph_before)

    def test_graph_write_failure_cleans_new_package_before_commit(self) -> None:
        def fail_graph(path, value):
            if path == self.graph_path:
                raise OSError("injected graph write failure")
            atomic_write_json(path, value)

        with mock.patch("cogito_approval.atomic_write_json", side_effect=fail_graph):
            with self.assertRaises(CogitoError):
                self.store.approve_package(self.package, "approve")
        self.assertFalse(self.package_path.exists())
        self.assertEqual(self.graph_path.read_bytes(), self.graph_before)
        self.assertEqual(self.store.events_path.read_bytes(), self.events_before)

    def test_missing_event_history_is_an_unknown_outcome_not_a_rollback(self) -> None:
        append_attempted = False

        def fail_append(*args, **kwargs):
            nonlocal append_attempted
            append_attempted = True
            raise OSError("injected append failure")

        def missing_history(path):
            return [] if append_attempted else read_events(path)

        with mock.patch("cogito_event_repository.append_event", side_effect=fail_append), \
                mock.patch("cogito_run_store.read_events", side_effect=missing_history):
            with self.assertRaisesRegex(CogitoError, "cannot determine.*approval"):
                self.store.approve_package(self.package, "approve")
        self.assertTrue(self.package_path.exists())
        self.assertNotEqual(self.graph_path.read_bytes(), self.graph_before)

    def test_error_after_graph_publication_still_rolls_back_before_commit(self) -> None:
        def write_then_fail(path, value):
            atomic_write_json(path, value)
            if path == self.graph_path:
                raise OSError("injected error after graph publication")

        with mock.patch("cogito_approval.atomic_write_json", side_effect=write_then_fail):
            with self.assertRaisesRegex(CogitoError, "approval was not recorded"):
                self.store.approve_package(self.package, "approve")
        self.assertFalse(self.package_path.exists())
        self.assertEqual(self.graph_path.read_bytes(), self.graph_before)
        self.assertEqual(self.store.events_path.read_bytes(), self.events_before)

    def test_unrelated_graph_replacement_is_not_overwritten_by_rollback(self) -> None:
        other_graph = {**self.old_graph, "active_run_id": "DEV-another-run"}

        def replace_graph_then_fail(*args, **kwargs):
            atomic_write_json(self.graph_path, other_graph)
            raise OSError("injected competing graph update")

        with mock.patch("cogito_event_repository.append_event", side_effect=replace_graph_then_fail):
            with self.assertRaisesRegex(CogitoError, "cleanup is incomplete"):
                self.store.approve_package(self.package, "approve")
        self.assertEqual(load_json(self.graph_path), other_graph)
        self.assertTrue(self.package_path.exists())

    def test_invalid_graph_is_rejected_before_package_publication(self) -> None:
        atomic_write_json(self.graph_path, {"schema_version": "3.0", "slices": []})
        with self.assertRaises(CogitoError):
            self.store.approve_package(self.package, "approve")
        self.assertFalse(self.package_path.exists())
        self.assertEqual(self.store.events_path.read_bytes(), self.events_before)

    def test_replay_permission_failure_preserves_approval_and_can_be_retried(self) -> None:
        self.store.approve_package(self.package, "approve")
        events_before = self.store.events_path.read_bytes()
        with mock.patch.object(Path, "chmod", side_effect=OSError("injected chmod failure")):
            with self.assertRaisesRegex(CogitoError, "approval is recorded"):
                self.store.approve_package(self.package, "approve")
        self.store.approve_package(self.package, "approve")
        self.assertEqual(self.store.events_path.read_bytes(), events_before)
        self.assert_approved_artifacts()

    def test_rollback_removes_graph_only_when_created_by_this_approval(self) -> None:
        self.graph_path.unlink()
        with mock.patch("cogito_event_repository.append_event", side_effect=OSError("injected append failure")):
            with self.assertRaises(CogitoError):
                self.store.approve_package(self.package, "approve")
        self.assertFalse(self.graph_path.exists())
        self.assertFalse(self.package_path.exists())

    def test_load_rebuilds_missing_malformed_and_modified_caches(self) -> None:
        expected = self.store.load()
        for cache in (None, [], {**expected, "state": "accepted"}):
            with self.subTest(cache=cache):
                atomic_write_json(self.store.state_path, cache)
                self.assertEqual(self.store.load(), expected)
                self.assertEqual(load_json(self.store.state_path), expected)
        self.store.state_path.unlink()
        self.assertEqual(self.store.load(), expected)
        self.assertEqual(load_json(self.store.state_path), expected)
        original_load = load_json

        def malformed_cache(path):
            if path == self.store.state_path:
                raise CogitoError("injected invalid JSON")
            return original_load(path)

        with mock.patch("cogito_event_repository.load_json", side_effect=malformed_cache), \
                mock.patch("cogito_event_repository.atomic_write_json", wraps=atomic_write_json) as write:
            self.assertEqual(self.store.load(), expected)
            write.assert_called_once_with(self.store.state_path, expected)

    def test_invalid_event_history_is_not_treated_as_cache_damage(self) -> None:
        with mock.patch("cogito_event_repository.read_events", side_effect=CogitoError("broken event chain")), \
                mock.patch("cogito_event_repository.atomic_write_json") as write:
            with self.assertRaisesRegex(CogitoError, "broken event chain"):
                self.store.load()
            write.assert_not_called()

    def test_tampered_package_is_not_treated_as_cache_damage(self) -> None:
        self.store.approve_package(self.package, "approve")
        original_load = load_json

        def tampered_package(path):
            value = original_load(path)
            if path == self.package_path:
                value["display_title"] = "unapproved change"
            return value

        with mock.patch("cogito_run_store._load_json", side_effect=tampered_package), \
                mock.patch("cogito_event_repository.atomic_write_json") as write:
            with self.assertRaises(CogitoError):
                self.store.load()
            write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
