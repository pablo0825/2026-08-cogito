"""Approval publication preserves artifacts across uncertain commit boundaries."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_approval import ApprovalArtifacts, publish_approval
from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_contracts import package_hash
from cogito_events import append_event, read_events
from cogito_project_graph import formalize_project_graph
from cogito_run_store import RunStore
from test_runtime_contract import minimal_package


class ApprovalPublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = minimal_package()
        self.store = RunStore(self.root, self.package["run_id"])
        self.store.create("feature")
        self.store.transition("shared-understanding-ready", {"shared_understanding_hash": self.package["shared_understanding"]["hash"]})
        self.store.transition("shared-understanding-confirmed", {"confirmed": True})
        self.store.transition("boundary-complete", self.package["boundary"])
        self.store.prepare_package(self.package)
        self.prior = self.store.load()
        self.package["package_hash"] = package_hash(self.package)
        self.package_path = self.root / "package.json"
        self.graph_path = self.root / "graph.json"
        old_graph = {"schema_version": "3.0", "active_run_id": None, "slices": {}, "dependencies": []}
        atomic_write_json(self.graph_path, old_graph)
        self.before_graph = self.graph_path.read_bytes()
        self.graph = formalize_project_graph(old_graph, self.package, self.package["run_id"])
        self.artifacts = ApprovalArtifacts(
            package_path=self.package_path, package=self.package,
            graph_path=self.graph_path, graph=self.graph, graph_before=self.before_graph,
        )

    def publish(self, record, load_events=None):
        return publish_approval(
            self.artifacts, prior_state=self.prior, workflow=self.store.workflow,
            load_events=load_events or (lambda: read_events(self.store.events_path)),
            record_approval=record,
        )

    def record(self):
        append_event(self.store.events_path, {"type": "package-approved", "payload": {
            "approved": True, "package_path": "package.json", "package_hash": self.package["package_hash"],
            "tasks": self.package["execution_dag"]["tasks"], "max_workers": 3,
            "project_graph_hash": hash_json(self.graph), "project_graph_snapshot": self.graph,
            "limits": self.package["limits"],
        }})
        return {"state": "start-gate"}

    def test_success_publishes_both_artifacts_and_makes_the_package_read_only(self) -> None:
        self.assertEqual(self.publish(self.record), {"state": "start-gate"})
        self.assertEqual(load_json(self.package_path), self.package)
        self.assertEqual(load_json(self.graph_path), self.graph)
        self.assertEqual(self.package_path.stat().st_mode & 0o222, 0)

    def test_a_different_existing_package_is_preserved_without_recording(self) -> None:
        atomic_write_json(self.package_path, {"existing": "belongs to another approval"})
        before = self.package_path.read_bytes()
        before_mode = self.package_path.stat().st_mode
        record = mock.Mock()
        with self.assertRaises(CogitoError):
            self.publish(record)
        record.assert_not_called()
        self.assertEqual(self.package_path.read_bytes(), before)
        self.assertEqual(self.package_path.stat().st_mode, before_mode)
        self.assertEqual(self.graph_path.read_bytes(), self.before_graph)

    def test_chmod_failure_after_recording_does_not_roll_back_published_artifacts(self) -> None:
        with mock.patch.object(Path, "chmod", side_effect=OSError("injected chmod failure")):
            with self.assertRaisesRegex(CogitoError, "approval is recorded"):
                self.publish(self.record)
        self.assertEqual(read_events(self.store.events_path)[-1]["type"], "package-approved")
        self.assertEqual(load_json(self.package_path), self.package)
        self.assertEqual(load_json(self.graph_path), self.graph)

    def test_replaced_history_anchor_preserves_artifacts_for_manual_recovery(self) -> None:
        replacement = self.root / "replacement-events.jsonl"
        for event in read_events(self.store.events_path):
            append_event(replacement, {
                "type": event["type"], "payload": event["payload"],
                "timestamp": "2000-01-01T00:00:00+00:00",
            })
        replacement_history = read_events(replacement)
        self.assertEqual(len(replacement_history), self.prior["sequence"])
        self.assertNotEqual(replacement_history[-1]["event_hash"], self.prior["last_event_hash"])
        with self.assertRaisesRegex(CogitoError, "cannot determine Package approval outcome"):
            self.publish(mock.Mock(side_effect=OSError("injected recording failure")), lambda: read_events(replacement))
        self.assertEqual(load_json(self.package_path), self.package)
        self.assertEqual(load_json(self.graph_path), self.graph)


if __name__ == "__main__":
    unittest.main()
