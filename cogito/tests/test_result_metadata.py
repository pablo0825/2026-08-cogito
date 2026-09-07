"""Recovery tests never open a repository's real run or product checkout."""
import copy
import json
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

from result_metadata_fixture import FourTasks, git, write_json
from cogito_contracts import materialize_contract, package_hash
from cogito_common import CogitoError, hash_json
from cogito_delivery_summary import build_delivery_summary, validate_delivery_summary
from cogito_execution_registry import register_external
from cogito_projection import project_events
from cogito_result_metadata import EVENT, require_recovery_state, validate_correction
from cogito_test_support import GitTestCase


class ResultMetadataTests(GitTestCase):
    def setUp(self):
        super().setUp()
        self.fixture = FourTasks()
        self.addCleanup(self.fixture.close)
        self.store = self.fixture.store

    def correct(self, index=0, action=None):
        return self.store.correct_result_metadata(self.fixture.request(index), action or f"repair-{index}")

    def assert_rejected(self, request):
        before = self.store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            self.store.correct_result_metadata(request, "rejected")
        self.assertEqual(before, self.store.events_path.read_bytes())

    def test_four_tasks_reverse_order_preserve_tip_and_resume_verify(self):
        original_hashes = [event["event_hash"] for event in self.store._events.read()]
        for i in (3, 2, 1, 0):
            result = self.correct(i)
            self.assertEqual(result["state"], "blocked")
            self.assertEqual(result["agent_results"][-1]["head_commit"], self.fixture.results[-1]["head_commit"])
        self.assertTrue(self.store.events_path.read_bytes().startswith(self.fixture.prefix))
        self.assertEqual(original_hashes, [e["event_hash"] for e in self.store._events.read()[:len(original_hashes)]])
        self.assertEqual(self.store.load(), project_events(self.store._events.read(), self.store.workflow))
        summary = build_delivery_summary(self.store.load(), self.store._events.read())
        validate_delivery_summary(summary)
        self.assertEqual(len(summary["implementation"]), 4)
        self.assertEqual(len(summary["corrections"]), 4)
        self.assertTrue(all(item["event"] == EVENT for item in summary["corrections"]))
        self.store.resume_gate("resume")
        self.store.transition("implementation-complete", {}, "implementation")
        evidence = [json.loads(Path(self.fixture.results[-1]["evidence"][0]).read_text())]
        self.store.complete_verification(evidence, "verify")
        self.assertEqual(self.store.load()["state"], "reviewing")

    def test_first_task_overlay_keeps_last_tip_and_completion_guard(self):
        self.correct(0)
        self.assertEqual(self.store.load()["agent_results"][-1], self.fixture.results[-1])
        self.store.resume_gate("resume")
        with self.assertRaises(CogitoError):
            self.store.transition("implementation-complete", {}, "incomplete-recovery")

    def test_unmodified_hints_still_fail_completion(self):
        self.store.resume_gate("resume")
        with self.assertRaises(CogitoError):
            self.store.transition("implementation-complete", {}, "unchanged")

    def test_exact_replay_is_idempotent_and_payload_conflict_rejected(self):
        result = self.correct()
        data = self.store.events_path.read_bytes()
        self.assertEqual(self.correct(), result)
        self.assertEqual(data, self.store.events_path.read_bytes())
        changed = self.fixture.request()
        changed["result"]["risks"] = ["changed"]
        with self.assertRaises(CogitoError):
            self.store.correct_result_metadata(changed, "repair-0")
        with self.assertRaises(CogitoError):
            self.store.correct_result_metadata(self.fixture.request(), "another-action")

    def test_all_result_fields_are_immutable(self):
        original = self.fixture.request()
        for field in original["result"]:
            value = copy.deepcopy(original)
            value["result"][field] = ["different"] if isinstance(value["result"][field], list) else "different"
            with self.subTest(field=field):
                self.assert_rejected(value)
        value = copy.deepcopy(original)
        value["result"]["extra"] = True
        self.assert_rejected(value)

    def test_wrong_reference_unaccepted_event_and_extra_input_rejected(self):
        for change in ({"original_event_sequence": 9999}, {"original_event_hash": "0" * 64},
                       {"original_event_sequence": True}, {"unknown": 1}):
            self.assert_rejected({**self.fixture.request(), **change})
        first = self.store._events.read()[0]
        self.assert_rejected({**self.fixture.request(), "original_event_sequence": first["sequence"],
                              "original_event_hash": first["event_hash"]})

    def test_non_atomic_wrong_role_status_and_transition_rejected_on_replay(self):
        original = self.fixture.results[0]
        for fields in ({"role": "reviewer"}, {"status": "blocked"}, {"requested_transition": "reviewing"}):
            with self.assertRaises(CogitoError):
                validate_correction({**original, **fields}, self.fixture.request()["result"])
        events = copy.deepcopy(self.store._events.read())
        events[0]["payload"].pop("task_delivery")
        with self.assertRaises(CogitoError):
            project_events([*events, {"type": EVENT, "payload": self.fixture.request()}], self.store.workflow)

    def test_projection_rejects_wrong_identity_task_and_uncompleted_result(self):
        for field, value in (("agent_id", "other"), ("task_id", "T-999"), ("head_commit", "0" * 40)):
            payload = self.fixture.request()
            payload["result"][field] = value
            with self.assertRaises(CogitoError):
                project_events([*self.store._events.read(), {"type": EVENT, "payload": payload}], self.store.workflow)
        events = [e for e in self.store._events.read()
                  if not (e["type"] == "task-updated" and e["payload"].get("task_id") == "T-004" and e["payload"].get("status") == "complete")]
        with self.assertRaises(CogitoError):
            project_events([*events, {"type": EVENT, "payload": self.fixture.request(3)}], self.store.workflow)

    def test_state_active_task_and_human_fences(self):
        state = self.store.load()
        for fields in ({"state": "executing"}, {"blocked_from": "reviewing"}, {"human": {"escalated": True}},
                       {"tasks": {"T-active": {"status": "running"}}}, {"tasks": {"T-active": {"status": "leased"}}}):
            with self.assertRaises(CogitoError):
                require_recovery_state({**state, **fields})
        with patch("cogito_replan_lock.replans", return_value=iter([{
            "replan_id": "RP-test", "source_run_id": "DEV-test", "successor_run_id": "DEV-next", "state": "proposed",
        }])):
            self.assert_rejected(self.fixture.request())
        with patch("cogito_disposition_scope.dispositions", return_value=iter([{
            "disposition_id": "DP-test", "source_run_id": "DEV-test", "successor_run_id": None, "state": "proposed",
        }])):
            self.assert_rejected(self.fixture.request())

    def test_active_external_worker_and_unknown_started_attempt(self):
        register_external(self.fixture.root, "DEV-test", "worker", "fixture-handle")
        self.assert_rejected(self.fixture.request())

    def test_unknown_check_without_a_live_process_is_not_complete(self):
        write_json(self.store.run_dir / "check-actions/unknown/started.json", {"request_hash": "unknown"})
        self.assert_rejected(self.fixture.request())

    def test_tampered_or_missing_historical_and_last_tip_evidence(self):
        for index in (0, 3):
            path = Path(self.fixture.results[index]["evidence"][0])
            data = path.read_bytes()
            path.unlink()
            self.assert_rejected(self.fixture.request())
            path.write_bytes(data)
            value = json.loads(data)
            value["stdout"] += "tamper"
            write_json(path, value)
            self.assert_rejected(self.fixture.request())
            path.write_bytes(data)

    def test_dirty_index_untracked_branch_and_nonlast_tip(self):
        worker = self.fixture.worker
        path = worker / "task1.txt"
        path.write_text("dirty\n")
        self.assert_rejected(self.fixture.request())
        git(worker, "add", "task1.txt")
        path.write_text("task 1\n")
        self.assert_rejected(self.fixture.request())
        git(worker, "reset", "--hard", "HEAD")
        unknown = worker / "untracked"
        unknown.write_text("unknown")
        self.assert_rejected(self.fixture.request())
        unknown.unlink()
        git(worker, "checkout", "-b", "codex/wrong")
        self.assert_rejected(self.fixture.request())
        git(worker, "checkout", "codex/worker")
        git(worker, "reset", "--hard", self.fixture.results[0]["head_commit"])
        self.assert_rejected(self.fixture.request())

    def test_commit_parent_graft_is_rejected(self):
        head = self.fixture.results[0]["head_commit"]
        git(self.fixture.worker, "replace", "--graft", head)
        self.assert_rejected(self.fixture.request())

    def test_protected_event_cannot_be_recorded_or_transitioned_directly(self):
        for action in (self.store.record, self.store.transition):
            with self.assertRaises(CogitoError):
                action(EVENT, self.fixture.request(), "bypass")

    def test_later_effective_contract_does_not_rebind_historical_evidence(self):
        amendment = {"id": "TA-001", "reason": "additional verification", "added_checks": [
            {"id": "V-002", "argv": [sys.executable, "-c", "print('extra')"], "phase": "integration"},
        ]}
        # A frozen, shape-validated accepted Amendment is part of the historical fixture.
        effective = materialize_contract(self.fixture.package, [amendment])
        self.store._events.append({"type": "technical-amendment-added", "payload": {
            "amendment": amendment, "effective_contract_hash": effective["effective_contract_hash"],
        }})
        path = Path(self.fixture.results[0]["evidence"][0])
        original = path.read_bytes()
        self.assertNotEqual(json.loads(original)["effective_contract_hash"], effective["effective_contract_hash"])
        state = self.correct()
        self.assertEqual(state["effective_contract_hash"], effective["effective_contract_hash"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(state["agent_results"][0]["requested_transition"], "verifying")

    def test_real_cli_uses_explicit_repo_and_rejects_format_reference_and_action_conflicts(self):
        script = Path(__file__).resolve().parents[1] / "scripts/cogito_gate.py"
        input_path = self.fixture.root / ".cogito/request.json"
        def invoke(payload, action):
            write_json(input_path, payload)
            return subprocess.run([sys.executable, str(script), "--repo", str(self.fixture.root),
                "correct-result-metadata", "--run-id", "DEV-test", "--input", str(input_path),
                "--action-id", action], cwd=script.parent, capture_output=True, text=True)
        for payload in ({}, {**self.fixture.request(), "original_event_hash": "0" * 64}):
            result = invoke(payload, "invalid-cli")
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertFalse(json.loads(result.stderr)["ok"])
        result = invoke(self.fixture.request(), "cli-success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["data"]["state"], "blocked")
        before = self.store.events_path.read_bytes()
        self.assertEqual(invoke(self.fixture.request(), "cli-success").returncode, 0)
        self.assertEqual(before, self.store.events_path.read_bytes())
        changed = self.fixture.request(1)
        self.assertEqual(invoke(changed, "cli-success").returncode, 2)
        self.assertEqual(before, self.store.events_path.read_bytes())

    def test_superseded_same_task_result_cannot_be_revived(self):
        superseding = {**self.fixture.results[0], "status": "blocked", "requested_transition": "blocked"}
        self.store._events.append({"type": "agent-result-recorded", "payload": {"result": superseding}})
        self.assert_rejected(self.fixture.request())
        with self.assertRaisesRegex(CogitoError, "superseded"):
            project_events([*self.store._events.read(), {"type": EVENT, "payload": self.fixture.request()}], self.store.workflow)

    def test_rp_successor_without_init_hint_recovers_through_real_cli(self):
        fixture = FourTasks(successor=True)
        self.addCleanup(fixture.close)
        self.assertNotIn("task_delivery", fixture.store._events.read()[0]["payload"])
        self.assertEqual(fixture.store.load()["task_delivery"], "atomic")
        script = Path(__file__).resolve().parents[1] / "scripts/cogito_gate.py"
        request_path = fixture.root / ".cogito/request.json"
        for index in (3, 0, 2, 1):
            write_json(request_path, fixture.request(index))
            result = subprocess.run([sys.executable, str(script), "--repo", str(fixture.root),
                "correct-result-metadata", "--run-id", "DEV-test", "--input", str(request_path),
                "--action-id", f"rp-repair-{index}"], cwd=script.parent, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(fixture.store.events_path.read_bytes().startswith(fixture.prefix))
        fixture.store.resume_gate("rp-resume")
        fixture.store.transition("implementation-complete", {}, "rp-complete")
        fixture.store.complete_verification([json.loads(Path(fixture.results[-1]["evidence"][0]).read_text())], "rp-verify")
        self.assertEqual(fixture.store.load()["state"], "reviewing")

    def test_successor_candidate_cannot_grant_atomic_without_matching_approval(self):
        fixture = FourTasks(successor=True)
        self.addCleanup(fixture.close)
        events = copy.deepcopy(fixture.store._events.read())
        ready = next(event for event in events if event["type"] == "package-ready")
        approved = next(event for event in events if event["type"] == "package-approved")
        approved["payload"]["package_hash"] = "0" * 64
        with self.assertRaisesRegex(CogitoError, "candidate snapshot"):
            project_events(events, self.store.workflow)
        # A valid, approved non-atomic snapshot must not grant the recovery mode.
        candidate = ready["payload"]["candidate_snapshot"]
        package = candidate["package"]
        package.pop("task_delivery")
        for check in package["checks"]:
            check.pop("phase", None)
        package["package_hash"] = package_hash(package)
        candidate["hash"] = hash_json({key: value for key, value in candidate.items() if key != "hash"})
        ready["payload"]["candidate_package_hash"] = package["package_hash"]
        approved["payload"]["package_hash"] = package["package_hash"]
        state = project_events(events, self.store.workflow)
        self.assertNotIn("task_delivery", state)
        with self.assertRaisesRegex(CogitoError, "atomic Result"):
            project_events([*events, {"type": EVENT, "payload": fixture.request()}], self.store.workflow)

    def test_new_atomic_complete_wrong_hint_is_rejected_before_recording(self):
        # Restore a historical running fixture prefix, not the production ledger.
        event = self.fixture.events[-1]
        lines = self.store.events_path.read_bytes().splitlines(keepends=True)
        self.store.events_path.write_bytes(b"".join(lines[:event["sequence"] - 1]))
        before = self.store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "must request verifying"):
            self.store.submit_agent_result(self.fixture.results[-1], "new-invalid")
        self.assertEqual(before, self.store.events_path.read_bytes())
        valid = {**self.fixture.results[-1], "requested_transition": "verifying"}
        self.store.submit_agent_result(valid, "new-valid")


if __name__ == "__main__":
    unittest.main()
