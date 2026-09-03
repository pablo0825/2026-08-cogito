"""Review verdicts are pure decisions over the current verified task wave."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_gate_validation import derive_review_decision


def reviewer_result(task_id: str, implementer: str) -> dict:
    return {
        "task_id": task_id, "role": "reviewer", "status": "complete",
        "agent_id": f"reviewer-{task_id}", "reviewed_implementer": implementer,
        "requested_transition": "review-approved",
    }


class ReviewDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = {"kind": "feature"}
        self.state = {
            "tasks": {
                "T-B": {"status": "verified", "agent_id": "implementer-b"},
                "T-A": {"status": "verified", "agent_id": "implementer-a"},
            },
            "agent_results": [
                reviewer_result("T-B", "implementer-b"),
                reviewer_result("T-A", "implementer-a"),
            ],
        }

    def test_decision_is_sorted_and_detached_from_its_unchanged_inputs(self) -> None:
        before = copy.deepcopy((self.package, self.state))
        expected = {"reviews": ["T-A", "T-B"], "approved": True, "independent": True}
        decision = derive_review_decision(self.package, self.state)
        self.assertEqual(decision, expected)
        self.assertEqual((self.package, self.state), before)
        decision["reviews"].append("edited output")
        decision["approved"] = False
        self.assertEqual((self.package, self.state), before)
        self.assertEqual(derive_review_decision(self.package, self.state), expected)

    def test_latest_reviewer_result_for_each_task_supersedes_older_findings(self) -> None:
        older = {**reviewer_result("T-A", "implementer-a"), "status": "needs-fix"}
        self.state["agent_results"].insert(0, older)
        self.state["agent_results"].append({"task_id": "T-A", "role": "implementer", "status": "complete"})
        decision = derive_review_decision(self.package, self.state)
        self.assertEqual(decision["reviews"], ["T-A", "T-B"])

    def test_invalid_latest_review_cannot_fall_back_to_an_older_approval(self) -> None:
        for invalid in (
            {"agent_id": "implementer-a"},
            {"reviewed_implementer": "another-implementer"},
            {"status": "needs-fix"},
            {"requested_transition": "review-fix"},
        ):
            with self.subTest(latest_review=invalid):
                state = copy.deepcopy(self.state)
                state["agent_results"].append({**reviewer_result("T-A", "implementer-a"), **invalid})
                before = copy.deepcopy((self.package, state))
                with self.assertRaises(CogitoError):
                    derive_review_decision(self.package, state)
                self.assertEqual((self.package, state), before)

    def test_every_verified_task_needs_a_review_but_other_task_states_do_not(self) -> None:
        for index, status in enumerate(("pending", "leased", "running", "complete", "reviewed", "integrated", "blocked")):
            self.state["tasks"][f"outside-wave-{index}"] = {"status": status}
        self.state["agent_results"].append({
            "task_id": "outside-wave-0", "role": "reviewer", "status": "needs-fix",
        })
        self.assertEqual(derive_review_decision(self.package, self.state)["reviews"], ["T-A", "T-B"])
        self.state["agent_results"] = [item for item in self.state["agent_results"] if item["task_id"] != "T-A"]
        before = copy.deepcopy(self.state)
        with self.assertRaises(CogitoError):
            derive_review_decision(self.package, self.state)
        self.assertEqual(self.state, before)

    def test_regular_review_requires_a_nonempty_verified_wave(self) -> None:
        for task in self.state["tasks"].values():
            task["status"] = "integrated"
        before = copy.deepcopy(self.state)
        with self.assertRaises(CogitoError):
            derive_review_decision(self.package, self.state)
        self.assertEqual(self.state, before)

    def test_maintenance_exemption_returns_only_verified_tasks_without_reviews(self) -> None:
        package = {"kind": "maintenance", "maintenance_guards": {"behavior_unchanged": True}}
        state = {"tasks": {
            "T-B": {"status": "verified"}, "T-A": {"status": "verified"},
            "T-C": {"status": "integrated"},
        }}
        before = copy.deepcopy((package, state))
        self.assertEqual(
            derive_review_decision(package, state, review_exemption=True),
            {"reviews": ["T-A", "T-B"], "approved": True, "independent": False},
        )
        self.assertEqual((package, state), before)
        state["tasks"] = {"T-C": {"status": "integrated"}}
        before = copy.deepcopy((package, state))
        with self.assertRaises(CogitoError):
            derive_review_decision(package, state, review_exemption=True)
        self.assertEqual((package, state), before)

    def test_feature_documentation_and_unguarded_maintenance_cannot_claim_exemption(self) -> None:
        for package in (
            {"kind": "feature"},
            {"kind": "documentation"},
            {"kind": "maintenance", "maintenance_guards": {"behavior_unchanged": False}},
        ):
            with self.subTest(package=package):
                before = copy.deepcopy((package, self.state))
                with self.assertRaises(CogitoError):
                    derive_review_decision(package, self.state, review_exemption=True)
                self.assertEqual((package, self.state), before)


if __name__ == "__main__":
    unittest.main()
