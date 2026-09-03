"""Correction completion rules operate on records without a Git repository."""

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_correction_rules import validate_correction_completion, validate_review_fix_completion


class CorrectionCompletionTests(unittest.TestCase):
    def setUp(self):
        self.commit = "a" * 40
        self.amendment = {"id": "TA-1", "added_tasks": [{"id": "T-1"}, {"id": "T-2"}]}
        self.state = {
            "tasks": {"T-1": {"status": "complete"}, "T-2": {"status": "complete"}, "unrelated": {"status": "pending"}},
            "agent_results": [
                {"task_id": "T-1", "role": "implementer", "status": "complete", "head_commit": self.commit},
                {"task_id": "T-2", "role": "implementer", "status": "complete", "head_commit": "b" * 40},
            ],
        }

    def history(self, review=False):
        amendment = {"type": "technical-amendment-added", "payload": {"amendment": copy.deepcopy(self.amendment)}}
        start = {"type": "review-fix-required" if review else "verification-correction-required", "payload": {"amendment_id": "TA-1"}}
        events = [start, amendment] if review else [amendment, start]
        return [{**event, "sequence": index} for index, event in enumerate(events, 1)]

    def call(self, review=False, *, state=None, events=None, commit=None):
        state = self.state if state is None else state
        events = self.history(review) if events is None else events
        before = copy.deepcopy((state, events))
        operation = validate_review_fix_completion if review else validate_correction_completion
        try:
            with mock.patch("builtins.open", side_effect=AssertionError("rules must not read files")):
                return operation(state, events, "TA-1", commit or self.commit)
        finally:
            self.assertEqual((state, events), before)

    def test_complete_tasks_can_have_distinct_heads_and_ignore_unrelated_tasks(self):
        added = self.call()
        self.assertEqual(added, {"T-1", "T-2"})
        added.clear()
        self.assertEqual(self.call(), {"T-1", "T-2"})
        self.assertIsNone(self.call(True))
        self.assertEqual(self.call(commit="b" * 40), {"T-1", "T-2"})

    def test_only_correction_can_complete_without_added_tasks(self):
        self.amendment.pop("added_tasks")
        self.assertEqual(self.call(), set())
        with self.assertRaisesRegex(CogitoError, "completed amendment tasks"):
            self.call(True)

    def test_every_added_task_must_exist_and_be_exactly_complete(self):
        for review in (False, True):
            for status in (None, "pending", "running", "blocked", "verified", "reviewed", "integrated"):
                with self.subTest(review=review, status=status):
                    state = copy.deepcopy(self.state)
                    if status is None:
                        del state["tasks"]["T-2"]
                    else:
                        state["tasks"]["T-2"]["status"] = status
                    with self.assertRaises(CogitoError):
                        self.call(review, state=state)

    def test_each_added_task_needs_a_completed_implementer_result(self):
        for review in (False, True):
            for mutation in ({"role": "reviewer"}, {"status": "needs-fix"}, {"task_id": "unrelated"}):
                with self.subTest(review=review, mutation=mutation):
                    state = copy.deepcopy(self.state)
                    state["agent_results"][1].update(mutation)
                    with self.assertRaisesRegex(CogitoError, "Implementer Results"):
                        self.call(review, state=state)
            with self.assertRaisesRegex(CogitoError, "Implementer Results"):
                self.call(review, commit="f" * 40)

    def test_correction_must_match_the_latest_opened_cycle(self):
        events = self.history()
        events.append({"type": "post-verification-correction-required", "sequence": 3, "payload": {"amendment_id": "TA-2"}})
        with self.assertRaisesRegex(CogitoError, "opened this correction cycle"):
            self.call(events=events)
        with self.assertRaisesRegex(CogitoError, "opened this correction cycle"):
            self.call(events=events[:1])
        events = self.history()
        events[-1]["type"] = "post-verification-correction-required"
        self.assertEqual(self.call(events=events), {"T-1", "T-2"})

    def test_review_fix_requires_an_amendment_after_the_latest_finding(self):
        events = self.history(True)
        with self.assertRaisesRegex(CogitoError, "no recorded Reviewer finding"):
            self.call(True, events=events[1:])
        for sequence in (1, 0):
            older = copy.deepcopy(events)
            older[1]["sequence"] = sequence
            with self.assertRaisesRegex(CogitoError, "new Technical Amendment"):
                self.call(True, events=older)
        events.append({"type": "review-fix-required", "sequence": 3, "payload": {}})
        with self.assertRaisesRegex(CogitoError, "new Technical Amendment"):
            self.call(True, events=events)

    def test_missing_and_ambiguous_amendments_are_rejected(self):
        for review in (False, True):
            for duplicate in (False, True):
                with self.subTest(review=review, duplicate=duplicate):
                    events = self.history(review)
                    amendment = next(event for event in events if event["type"] == "technical-amendment-added")
                    if duplicate:
                        events.append({**copy.deepcopy(amendment), "sequence": 3})
                    else:
                        amendment["payload"]["amendment"]["id"] = "TA-other"
                    with self.assertRaisesRegex(CogitoError, "Technical Amendment"):
                        self.call(review, events=events)


if __name__ == "__main__":
    unittest.main()
