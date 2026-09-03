"""Integration decisions depend on recorded tasks and history, without Git or files."""

import copy
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_integration_rules import derive_integration_decision


class IntegrationRulesTests(unittest.TestCase):
    def setUp(self):
        self.state = {
            "state": "integrating",
            "tasks": {
                "T-2": {"id": "T-2", "slice_id": "FS-1", "status": "reviewed"},
                "T-1": {"id": "T-1", "slice_id": "FS-1", "status": "reviewed"},
                "T-other": {"id": "T-other", "slice_id": "FS-2", "status": "integrated"},
            },
            "agent_results": [
                {"task_id": "T-2", "role": "implementer", "status": "complete", "head_commit": "b" * 40},
                {"task_id": "T-1", "role": "implementer", "status": "complete", "head_commit": "a" * 40},
            ],
        }
        self.events = [{"type": "start-gate-passed", "payload": {"delivery_head": "c" * 40}}]

    def decide(self, slice_id="FS-1", *, state=None, events=None):
        state = self.state if state is None else state
        events = self.events if events is None else events
        before = copy.deepcopy((state, events))
        try:
            return derive_integration_decision(state, events, slice_id)
        finally:
            self.assertEqual((state, events), before, "integration rules must not mutate inputs")

    def test_remaining_tasks_choose_slice_wave_or_final_completion(self):
        for remaining_status, expected in (
            ("reviewed", "slice-integration-complete"),
            ("pending", "wave-integration-complete"),
            ("running", "wave-integration-complete"),
            ("integrated", "integration-complete"),
        ):
            with self.subTest(remaining_status=remaining_status):
                state = copy.deepcopy(self.state)
                state["tasks"]["T-other"]["status"] = remaining_status
                decision = self.decide(state=state)
                self.assertEqual(decision.event, expected)
                self.assertEqual(decision.task_ids, ("T-1", "T-2"))
                self.assertEqual(decision.source_heads, ("a" * 40, "b" * 40))

    def test_reviewed_work_takes_precedence_over_pending_work_in_another_slice(self):
        self.state["tasks"]["T-other"]["status"] = "reviewed"
        self.state["tasks"]["T-later"] = {"id": "T-later", "slice_id": "FS-3", "status": "pending"}
        self.assertEqual(self.decide().event, "slice-integration-complete")

    def test_omitted_and_empty_task_slice_ids_belong_to_the_mini_package(self):
        self.state["tasks"]["T-1"].pop("slice_id")
        self.state["tasks"]["T-2"]["slice_id"] = ""
        decision = self.decide(None)
        self.assertEqual(decision.event, "integration-complete")
        self.assertEqual(decision.task_ids, ("T-1", "T-2"))
        self.assertEqual(decision.previous_delivery_head, "c" * 40)

    def test_target_slice_must_exist_and_every_target_task_must_be_reviewed(self):
        with self.assertRaisesRegex(CogitoError, "independently reviewed"):
            self.decide("FS-missing")
        for status in ("pending", "leased", "running", "blocked", "complete", "verified", "integrated"):
            with self.subTest(status=status):
                state = copy.deepcopy(self.state)
                state["tasks"]["T-2"]["status"] = status
                with self.assertRaisesRegex(CogitoError, "independently reviewed"):
                    self.decide(state=state)

    def test_each_target_task_needs_a_successful_implementer_result(self):
        for mutation in ({"role": "reviewer"}, {"status": "blocked"}, {"task_id": "T-other"}):
            with self.subTest(mutation=mutation):
                state = copy.deepcopy(self.state)
                state["agent_results"][0].update(mutation)
                with self.assertRaisesRegex(CogitoError, "implementation Result"):
                    self.decide(state=state)
        self.state["agent_results"] = []
        with self.assertRaisesRegex(CogitoError, "implementation Result"):
            self.decide()

    def test_latest_successful_implementer_wins_over_older_and_non_success_results(self):
        self.state["agent_results"].extend([
            {"task_id": "T-1", "role": "implementer", "status": "complete", "head_commit": "d" * 40},
            {"task_id": "T-1", "role": "reviewer", "status": "complete", "head_commit": "e" * 40},
            {"task_id": "T-1", "role": "implementer", "status": "blocked", "head_commit": "f" * 40},
        ])
        self.assertEqual(self.decide().source_heads, ("b" * 40, "d" * 40))

    def test_first_integration_uses_the_latest_start_gate_delivery_head(self):
        self.events.extend([
            {"type": "start-gate-passed", "payload": {"delivery_head": "d" * 40}},
            {"type": "task-updated", "payload": {"head_commit": "e" * 40}},
        ])
        self.assertEqual(self.decide().previous_delivery_head, "d" * 40)

    def test_latest_integration_commit_is_the_anchor_for_each_integration_event(self):
        for event in ("slice-integration-complete", "wave-integration-complete", "integration-complete"):
            with self.subTest(event=event):
                events = [
                    *self.events,
                    {"type": "slice-integration-complete", "payload": {"commit_id": "d" * 40}},
                    {"type": event, "payload": {"commit_id": "e" * 40}},
                    {"type": "task-updated", "payload": {"head_commit": "f" * 40}},
                ]
                self.assertEqual(self.decide(events=events).previous_delivery_head, "e" * 40)

    def test_decision_needs_no_filesystem_or_process_access(self):
        with ExitStack() as stack:
            for target in ("builtins.open", "pathlib.Path.open", "pathlib.Path.resolve", "subprocess.run", "subprocess.Popen"):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected IO")))
            decision = self.decide()
        self.assertEqual(decision.event, "integration-complete")


if __name__ == "__main__":
    unittest.main()
