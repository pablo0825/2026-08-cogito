"""Verification uses one history and rejects changes before publishing its verdict."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cogito_test_support import package
from cogito_common import CogitoError, hash_json
from cogito_contracts import materialize_contract
from cogito_events import append_event, read_events
from cogito_gate_validation import validate_evidence
from cogito_run_store import RunStore
from test_evidence_contract import valid_evidence


class VerificationSnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.package = package("maintenance")
        self.package["checks"].append({**self.package["checks"][0], "id": "C-2"})
        self.store = RunStore(self.root, self.package["run_id"])
        self.store.create("maintenance")
        self.store.prepare_package(self.package)
        self.store.approve_package(self.package)
        self.event("start-gate-passed", baseline_valid=True, contract_valid=True, worktrees_valid=True)
        for status in ("leased", "running", "complete"):
            self.event("task-updated", task_id="T-1", status=status, agent_id="worker")
        self.event("implementation-complete", tasks_complete=True, task_ids=["T-1"])
        self.head = "b" * 40
        self.evidence = self.capture("implementation")

    def event(self, event_type, **payload):
        append_event(self.store.events_path, {"type": event_type, "payload": payload})

    def capture(self, phase):
        effective = materialize_contract(self.package, [])
        items = []
        for check in self.package["checks"]:
            item = valid_evidence()
            path = self.store.run_dir / "evidence" / f"{phase}-{check['id']}.json"
            path.parent.mkdir(exist_ok=True)
            binding = {"head_commit": self.head, "content_tree": "c" * 40}
            digest = hash_json(binding)
            item.update({
                "run_id": self.store.run_id, "check_id": check["id"],
                "check_hash": hash_json(check), "argv": check["argv"],
                "effective_contract_hash": effective["effective_contract_hash"],
                "worktree_binding": {**binding, "snapshot_hash": digest},
                "evidence_path": str(path),
            })
            for field in ("tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash"):
                item[field] = digest
            path.write_text(json.dumps(item))
            self.event("check-evidence-recorded", check_id=check["id"], evidence_path=str(path), evidence_hash=hash_json(item))
            items.append(item)
        return items

    def post_integration(self):
        self.store.complete_verification(self.evidence, "verify")
        self.store.transition("review-approved", {"review_exemption": True})
        self.event("integration-complete", commit_id=self.head, task_ids=["T-1"])
        self.evidence = self.capture("post-integration")

    def test_multiple_checks_do_not_reload_state_and_missing_cache_is_repaired(self):
        self.store.state_path.unlink()
        with mock.patch.object(self.store, "load", side_effect=AssertionError("unexpected state reload")):
            state = self.store.complete_verification(self.evidence, "verify")
        self.assertEqual(state["state"], "reviewing")
        self.assertEqual(json.loads(self.store.state_path.read_text()), state)
        before = self.store.events_path.read_bytes()
        self.assertEqual(self.store.complete_verification(self.evidence, "verify"), state)
        self.assertEqual(self.store.events_path.read_bytes(), before)

    def test_both_phases_reject_an_event_appended_after_validation(self):
        for post in (False, True):
            with self.subTest(post=post):
                if post:
                    self.post_integration()

                def validate_then_compete(*args, **kwargs):
                    validate_evidence(*args, **kwargs)
                    # Legal in either phase, so transition validation alone
                    # cannot detect that the verdict used an older snapshot.
                    self.event("transient-retry", reason="concurrent operation")

                with mock.patch("cogito_run_store.validate_gate_evidence", side_effect=validate_then_compete), \
                     mock.patch.object(self.store, "_git", return_value=self.head):
                    with self.assertRaisesRegex(CogitoError, "history changed"):
                        if post:
                            self.store.decide_post_verification(self.evidence, action_id="post")
                        else:
                            self.store.complete_verification(self.evidence, "verify")
                history = read_events(self.store.events_path)
                self.assertEqual(history[-1]["type"], "transient-retry")
                self.assertFalse(any(item.get("action_id") == ("post" if post else "verify") for item in history))

    def test_post_verification_records_the_validated_head_and_detects_drift(self):
        self.post_integration()
        before = self.store.events_path.read_bytes()
        with mock.patch.object(self.store, "_git", side_effect=[self.head, "d" * 40]):
            with self.assertRaisesRegex(CogitoError, "HEAD changed"):
                self.store.decide_post_verification(self.evidence, action_id="post")
        self.assertEqual(self.store.events_path.read_bytes(), before)
        with mock.patch.object(self.store, "_git", return_value=self.head) as git, \
             mock.patch.object(self.store, "load", side_effect=AssertionError("unexpected state reload")):
            state = self.store.decide_post_verification(self.evidence, action_id="post")
        self.assertEqual(state["state"], "finalizing")
        self.assertEqual(git.call_args_list, [mock.call("rev-parse", "HEAD")] * 2)
        self.assertEqual(read_events(self.store.events_path)[-1]["payload"]["delivery_head"], self.head)

    def test_adapter_rejects_missing_outside_and_tampered_files_without_recording(self):
        for problem in ("missing", "outside", "tampered"):
            with self.subTest(problem=problem):
                supplied = copy.deepcopy(self.evidence)
                if problem == "missing":
                    supplied[0]["evidence_path"] = str(self.store.run_dir / "evidence" / "missing.json")
                elif problem == "outside":
                    supplied[0]["evidence_path"] = str(self.root / "outside.json")
                else:
                    supplied[0]["stdout"] = "changed"
                before = self.store.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    self.store.complete_verification(supplied, "verify")
                self.assertEqual(self.store.events_path.read_bytes(), before)

    def test_tampered_package_is_rejected_before_cache_repair(self):
        snapshot = self.store._events.snapshot()
        path = self.root / snapshot.state["package_path"]
        path.chmod(0o644)
        data = json.loads(path.read_text())
        data["description"] = "tampered"
        path.write_text(json.dumps(data))
        self.store.state_path.unlink()
        with self.assertRaises(CogitoError):
            self.store.complete_verification(self.evidence)
        self.assertFalse(self.store.state_path.exists())


if __name__ == "__main__":
    unittest.main()
