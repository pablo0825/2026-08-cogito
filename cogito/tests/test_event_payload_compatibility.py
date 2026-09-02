"""Producer annotations preserve legacy JSON payloads and projection behavior."""

import copy
import unittest

from cogito_test_support import SCRIPTS  # Makes script modules importable.
from cogito_common import canonical_json, hash_json
from cogito_projection import project_events
from cogito_workflow import load_workflow


class EventPayloadCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.workflow = load_workflow()
        self.events = [
            {"type": "run-created", "payload": {"run_id": "DEV-legacy", "kind": "maintenance"}},
            {"type": "mini-package-ready", "payload": {"package_valid": True}},
            {"type": "package-approved", "payload": {
                "approved": True, "package_path": "docs/package.json", "package_hash": "a" * 64,
                "max_workers": 1, "project_graph_hash": "b" * 64, "limits": {},
                "tasks": [{"id": "T-1", "extension": {"labels": ["legacy"]}}],
            }},
            {"type": "start-gate-passed", "payload": {
                "baseline_valid": True, "contract_valid": True, "worktrees_valid": True,
            }},
        ]

    def project_unchanged(self, events):
        # Use a deterministic historical envelope, including extension metadata.
        previous = "0" * 64
        history = []
        for sequence, event in enumerate(events, 1):
            body = {
                **copy.deepcopy(event), "sequence": sequence,
                "timestamp": "2026-09-02T14:00:00+00:00", "action_id": None,
                "previous_event_hash": previous, "legacy_metadata": {"version": 1},
            }
            previous = hash_json(body)
            history.append({**body, "event_hash": previous})
        before = canonical_json(history)
        state = project_events(history, self.workflow)
        self.assertEqual(canonical_json(history), before)
        for event in history:
            self.assertEqual(event["event_hash"], hash_json({key: value for key, value in event.items() if key != "event_hash"}))
        self.assertEqual(state["last_event_hash"], previous)
        return state

    def test_task_lease_accepts_omitted_optional_fields_and_preserves_extensions(self):
        state = self.project_unchanged([
            *self.events,
            {"type": "task-updated", "payload": {
                "task_id": "T-1", "status": "leased", "agent_id": "worker",
                "legacy_detail": {"attempts": [1, 2]},
            }},
        ])
        task = state["tasks"]["T-1"]
        self.assertEqual(task["status"], "leased")
        self.assertEqual(task["extension"], {"labels": ["legacy"]})
        self.assertEqual(task["legacy_detail"], {"attempts": [1, 2]})
        for optional in ("worktree", "branch", "base_commit"):
            self.assertNotIn(optional, task)

    def test_evidence_and_agent_results_retain_legacy_payload_extensions(self):
        result = {
            "schema_version": "3.0", "run_id": "DEV-legacy", "task_id": "T-1",
            "agent_id": "worker", "role": "implementer", "status": "complete",
            "base_commit": "a" * 40, "head_commit": "b" * 40,
            "changed_paths": [], "evidence": [], "risks": [], "requested_transition": "verifying",
            "extension": {"notes": ["preserve"]},
        }
        evidence = {
            "check_id": "C-1", "evidence_path": "evidence/C-1.json", "evidence_hash": "e" * 64,
            "extension": {"format": "legacy"},
        }
        state = self.project_unchanged([
            *self.events,
            {"type": "agent-result-recorded", "payload": {"result": result, "legacy_extra": True}},
            {"type": "check-evidence-recorded", "payload": evidence},
        ])
        self.assertEqual(state["agent_results"], [result])
        ledger = state["evidence"]["evidence/C-1.json"]
        self.assertEqual(ledger, {**evidence, "event_sequence": 6})
        self.assertNotIn("head_commit", ledger)
        self.assertNotIn("effective_contract_hash", ledger)

    def test_historical_integration_does_not_require_new_producer_metadata(self):
        events = [*self.events]
        for status in ("leased", "running", "complete"):
            events.append({"type": "task-updated", "payload": {"task_id": "T-1", "status": status, "agent_id": "worker"}})
        events.extend([
            {"type": "implementation-complete", "payload": {"tasks_complete": True}},
            {"type": "verification-passed", "payload": {"passed": True, "evidence": ["evidence/C-1.json"]}},
            {"type": "review-approved", "payload": {"approved": True, "independent": True, "reviews": ["T-1"]}},
            {"type": "integration-complete", "payload": {"commit_id": "c" * 40, "task_ids": ["T-1"], "extension": "legacy"}},
        ])
        state = self.project_unchanged(events)
        self.assertEqual(state["state"], "post-integration-verification")
        self.assertEqual(state["tasks"]["T-1"]["status"], "integrated")


if __name__ == "__main__":
    unittest.main()
