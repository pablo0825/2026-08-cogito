"""RunStore uses its injected boundaries without a real event log or Git repo."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_actions import request_fingerprint
from cogito_common import CogitoError
from cogito_event_repository import EventRepository
from cogito_git import GitRepository
from cogito_run_store import RunStore
from cogito_workflow import load_workflow


class FalseyDependency:
    """An empty adapter is still a deliberately supplied dependency."""

    def __init__(self, delegate):
        self.delegate = delegate

    def __bool__(self):
        return False

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class RunStoreDependencyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.events = mock.create_autospec(EventRepository, instance=True)
        self.git = mock.create_autospec(GitRepository, instance=True)
        self.events.read.return_value = []
        self.events.project.return_value = {"state": "preparing", "kind": "maintenance"}
        self.store = RunStore(
            self.root, "DEV-injected", event_repository=FalseyDependency(self.events),
            git_repository=FalseyDependency(self.git),
        )

    def test_completed_request_replays_from_the_adapter_without_a_disk_log(self):
        payload = {"reason": "pause"}
        self.events.read.return_value = [{
            "type": "block", "payload": payload, "action_id": "pause",
            "request_hash": request_fingerprint("transition", event="block", payload=payload),
        }]
        self.events.project.return_value = {"state": "blocked", "blocked_from": "preparing"}
        self.assertFalse(self.store.events_path.exists())
        self.assertEqual(self.store.transition("block", payload, "pause")["state"], "blocked")
        self.events.append.assert_not_called()
        with self.assertRaisesRegex(CogitoError, "different content"):
            self.store.transition("block", {"reason": "different"}, "pause")
        self.assertFalse(self.store.run_dir.exists())

    def test_committed_report_uses_both_injected_adapters_even_if_falsey(self):
        commit = "a" * 40
        result_path = "docs/cogito/results/DEV-injected.json"
        self.events.project.return_value = {"state": "accepted"}
        self.events.read.return_value = [{"type": "finalization-complete", "payload": {
            "final_commit": commit, "result_path": result_path,
        }}]
        self.git.run.return_value = json.dumps({
            "schema_version": "3.0", "run_id": "DEV-injected", "status": "accepted",
            "package_hash": "b" * 64, "effective_contract_hash": "c" * 64,
            "integration_commits": [], "slice_dispositions": {}, "checks": [],
            "reviews": [], "amendments": [], "remaining_risks": [],
            "human_gate": {"required": False, "outcome": "not-required"},
        })
        report = self.store.completion_report()
        self.assertEqual(report["final_commit"], commit)
        self.git.run.assert_called_once_with("show", f"{commit}:{result_path}")
        self.events.read.assert_called_once_with()
        self.assertFalse(self.store.run_dir.exists())

    def test_repository_controls_existence_and_initialization_checks(self):
        self.events.exists.return_value = True
        with self.assertRaisesRegex(CogitoError, "run already exists"):
            self.store.create("maintenance")
        self.events.create.assert_not_called()
        self.events.is_initialized.return_value = False
        with self.assertRaisesRegex(CogitoError, "must be initialized"):
            self.store.run_controlled_check("C-1", self.root, "check")
        self.assertFalse(self.store.run_dir.exists())

    def test_storage_failures_propagate_without_falling_back_to_local_files(self):
        self.events.read.side_effect = CogitoError("remote history unavailable")
        with self.assertRaisesRegex(CogitoError, "remote history unavailable"):
            self.store.transition("block", {"reason": "pause"}, "pause")
        self.events.append.assert_not_called()
        self.events.refresh_cache.assert_not_called()
        self.assertFalse(self.store.events_path.exists())

    def test_record_forwards_the_snapshot_version_to_the_repository(self):
        version = "d" * 64
        self.events.append.side_effect = CogitoError("event history changed")
        with self.assertRaisesRegex(CogitoError, "history changed"):
            self.store.record("block", {"reason": "pause"}, expected_previous_hash=version)
        self.assertEqual(self.events.append.call_args.kwargs["expected_previous_hash"], version)

    def test_default_repository_keeps_custom_workflow_and_existing_empty_log_rules(self):
        workflow = load_workflow()
        workflow["initial_state"] = "custom-preparation"
        store = RunStore(self.root, "DEV-default", workflow)
        self.assertEqual(store.create("maintenance")["state"], "custom-preparation")
        self.assertEqual(store.load()["state"], "custom-preparation")
        for directory in (False, True):
            with self.subTest(directory=directory):
                other = RunStore(self.root, f"DEV-existing-{directory}")
                other.run_dir.mkdir(parents=True)
                if directory:
                    other.events_path.mkdir()
                else:
                    other.events_path.touch()
                with self.assertRaisesRegex(CogitoError, "run already exists"):
                    other.create("maintenance")


if __name__ == "__main__":
    unittest.main()
