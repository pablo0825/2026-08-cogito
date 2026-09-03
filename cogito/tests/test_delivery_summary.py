"""Final delivery receipts must be complete, truthful, and reproducible."""

import copy
import unittest

from cogito_test_support import COGITO  # Establish the scripts import path.
from cogito_common import CogitoError
from cogito_delivery_summary import (
    build_delivery_summary, validate_delivery_summary, validate_delivery_summary_records,
)


A, B, C, TREE, HASH = (character * 40 for character in "abcde")
HASH = "f" * 64


def event(sequence, kind, **payload):
    return {"sequence": sequence, "type": kind, "payload": payload}


def agent(role="implementer", status="complete", **extra):
    return {"role": role, "status": status, "task_id": "T-1", "agent_id": role,
            "base_commit": A, "head_commit": B, "changed_paths": ["app.py"],
            "evidence": ["check.json"], **extra}


class DeliverySummaryTests(unittest.TestCase):
    def setUp(self):
        self.state = {"kind": "feature", "stage_commits": True}
        self.binding = {"head": C, "content_tree": TREE, "effective_contract_hash": HASH}
        self.events = [
            event(2, "stage-committed", stage="shared-understanding", stage_sequence=1,
                  commit_id=A, base_commit=B, branch="main", files={"shared.md": HASH}),
            event(4, "agent-result-recorded", result=agent()),
            event(5, "check-evidence-recorded", check_id="C-1", evidence_path="check.json",
                  evidence_hash=HASH, head_commit=B, effective_contract_hash=HASH),
            event(6, "verification-passed", passed=True, evidence=["check.json"]),
            event(7, "agent-result-recorded", result=agent("reviewer", "needs-fix", reviewed_implementer="implementer")),
            event(8, "review-fix-complete", amendment_id="TA-1", commit_id=B),
            event(9, "agent-result-recorded", result=agent("reviewer", reviewed_implementer="implementer")),
            event(10, "integration-complete", commit_id=B, previous_delivery_head=A,
                  task_ids=["T-1"], source_heads=[B], slice_id="S-1"),
            event(11, "human-review-required", passed=True, human_required=True,
                  evidence=["post.json"], delivery_head=B),
            event(12, "human-feedback-recorded", feedback={"id": "FB-1", "message": "private raw feedback",
                  "items": [{"id": "F-1", "description": "raw detail"}],
                  "acceptance_complete": False, "close_after_fixes": False},
                  feedback_hash=HASH, binding=self.binding),
            event(13, "human-correction-complete", amendment_id="TA-2", commit_id=C,
                  resolution={"feedback_id": "FB-1", "resolved_item_ids": ["F-1"], "summary": "Fixed label"},
                  binding=self.binding),
            event(14, "human-correction-reviewed", approved=True, conditional=False,
                  reviews=["T-1"], evidence=["fresh.json"], feedback_hash=HASH, binding=self.binding),
            event(15, "human-approved", approved=True, feedback_hash=HASH, binding=self.binding),
        ]

    def test_complete_history_preserves_failed_review_and_fresh_acceptance(self):
        result = build_delivery_summary(self.state, self.events)
        validate_delivery_summary_records(self.state, self.events, {"delivery_summary": result})
        self.assertEqual([r["status"] for r in result["reviews"]], ["needs-fix", "complete"])
        self.assertEqual([r["commit_id"] for r in result["corrections"]], [B, C])
        self.assertEqual(result["human_acceptance"][-1]["binding"], self.binding)
        self.assertNotIn("passed", result["verification"][0])
        self.assertNotIn("private raw feedback", str(result))

    def test_missing_summary_is_required_only_for_new_runs(self):
        with self.assertRaisesRegex(CogitoError, "requires delivery_summary"):
            validate_delivery_summary_records(self.state, self.events, {})
        validate_delivery_summary_records({"kind": "feature"}, self.events, {})

    def test_optional_legacy_summary_still_must_match(self):
        summary = build_delivery_summary(self.state, self.events)
        summary["integration"][0]["commit_id"] = C
        with self.assertRaisesRegex(CogitoError, "does not match"):
            validate_delivery_summary_records({"kind": "feature"}, self.events, {"delivery_summary": summary})

    def test_omitted_preparation_implementation_or_human_round_is_rejected(self):
        for section in ("preparation", "implementation", "reviews", "verification", "human_acceptance", "corrections"):
            with self.subTest(section=section):
                summary = build_delivery_summary(self.state, self.events)
                summary[section].pop(0)
                with self.assertRaisesRegex(CogitoError, "does not match"):
                    validate_delivery_summary_records(self.state, self.events, {"delivery_summary": summary})

    def test_relabelled_review_and_stale_acceptance_are_rejected(self):
        for section, key, value in (("reviews", "status", "complete"), ("human_acceptance", "delivery_head", C)):
            with self.subTest(section=section):
                summary = build_delivery_summary(self.state, self.events)
                summary[section][0][key] = value
                with self.assertRaisesRegex(CogitoError, "does not match"):
                    validate_delivery_summary_records(self.state, self.events, {"delivery_summary": summary})

    def test_no_mutation_or_shared_nested_values(self):
        before = copy.deepcopy((self.state, self.events))
        summary = build_delivery_summary(self.state, self.events)
        validate_delivery_summary(summary)
        self.assertEqual(before, (self.state, self.events))
        summary["preparation"][0]["files"]["shared.md"] = "changed"
        summary["human_acceptance"][-1]["binding"]["head"] = "changed"
        self.assertEqual(before, (self.state, self.events))

    def test_maintenance_records_snapshots_instead_of_fake_commits(self):
        state = {"kind": "maintenance", "stage_commits": True}
        events = [event(1, "agent-result-recorded", result=agent(head_commit=A),
                        maintenance_end_tree=TREE, maintenance_end_index_tree=B),
                  event(2, "technical-correction-complete", amendment_id="TA-1", commit_id=A,
                        completion_mode="working-tree", content_tree=TREE),
                  event(3, "human-correction-complete", amendment_id="TA-2", commit_id=A,
                        binding=self.binding)]
        summary = build_delivery_summary(state, events)
        validate_delivery_summary_records(state, events, {"delivery_summary": summary})
        implementation = summary["implementation"][0]
        self.assertEqual(implementation["base_commit"], A)
        self.assertEqual(implementation["content_tree"], TREE)
        self.assertNotIn("head_commit", implementation)
        for receipt in summary["corrections"]:
            self.assertNotIn("commit_id", receipt)
            self.assertEqual(receipt["content_tree"], TREE)

    def test_old_maintenance_events_do_not_invent_missing_snapshots(self):
        summary = build_delivery_summary({"kind": "maintenance"}, [event(1, "agent-result-recorded", result=agent(head_commit=A))])
        validate_delivery_summary(summary)
        self.assertNotIn("content_tree", summary["implementation"][0])

    def test_review_gate_exemption_and_conditional_acceptance_remain_explicit(self):
        events = [event(1, "review-approved", approved=True, independent=False, reviews=["T-1"]),
                  event(2, "human-correction-accepted", approved=True, independent=True,
                        conditional=True, reviews=["T-2"], evidence=["fresh.json"],
                        feedback_hash=HASH, binding=self.binding)]
        summary = build_delivery_summary({"kind": "maintenance"}, events)
        validate_delivery_summary(summary)
        self.assertFalse(summary["verification"][0]["independent"])
        self.assertTrue(summary["human_acceptance"][0]["conditional"])
        self.assertEqual(summary["reviews"], [])

    def test_shape_rejects_bad_ids_duplicate_order_and_nonindependent_review(self):
        changes = [lambda s: s["preparation"][0].update(commit_id="wrong"),
                   lambda s: s["reviews"][0].update(reviewer="implementer"),
                   lambda s: s["reviews"].reverse(),
                   lambda s: s["human_acceptance"][-1].update(approved="yes"),
                   lambda s: s["implementation"][0].update(completion_mode="working-tree")]
        for change in changes:
            summary = build_delivery_summary(self.state, self.events)
            change(summary)
            with self.assertRaises(CogitoError):
                validate_delivery_summary(summary)

    def test_later_finalization_event_does_not_change_summary(self):
        summary = build_delivery_summary(self.state, self.events)
        self.events.append(event(16, "finalization-complete", final_commit=A))
        self.assertEqual(summary, build_delivery_summary(self.state, self.events))


if __name__ == "__main__":
    unittest.main()
