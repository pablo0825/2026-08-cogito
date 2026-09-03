"""Human acceptance policy remains strict and independent of files or Git."""

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_human_rules import (
    can_close_after_fixes, validate_feedback, validate_human_budget,
    validate_resolution, validate_triage,
)


def feedback(**changes):
    value = {"id": "HF-1", "message": "Fix labels and date handling", "items": [
        {"id": "label", "description": "Correct label"},
        {"id": "date", "description": "Include final day"},
    ]}
    value.update(changes)
    return validate_feedback(value)


def request(*dispositions, **changes):
    value = {"feedback_id": "HF-1", "assessments": [
        {"id": key, "disposition": disposition, "reason": "Impact inspected"}
        for key, disposition in zip(("label", "date"), dispositions or ("local", "local"))
    ]}
    value.update(changes)
    return value


def human():
    batch = feedback(acceptance_complete=True, close_after_fixes=True)
    return {"feedback": batch, "triage": validate_triage(request(), batch), "resolution": {
        "feedback_id": "HF-1", "resolved_item_ids": ["label", "date"], "summary": "Both fixed",
    }}


class HumanRulesTests(unittest.TestCase):
    def test_unspecified_acceptance_never_grants_closure(self):
        batch = feedback()
        self.assertIs(batch["acceptance_complete"], False)
        self.assertIs(batch["close_after_fixes"], False)
        record = human()
        record["feedback"] = batch
        self.assertFalse(can_close_after_fixes(record))
        with self.assertRaisesRegex(CogitoError, "explicit acceptance_complete"):
            feedback(close_after_fixes=True)

    def test_feedback_rejects_malformed_or_ambiguous_input(self):
        for changes in (
            {"extra": True}, {"id": " "}, {"message": "\x00"}, {"items": []},
            {"items": [{"id": "x", "description": "x", "extra": True}]},
            {"items": [{"id": "x", "description": "x"}] * 2},
            {"items": [{"id": [], "description": "x"}]},
            {"acceptance_complete": 1}, {"close_after_fixes": "true"},
        ):
            with self.subTest(changes=changes), self.assertRaises(CogitoError):
                feedback(**changes)

    def test_whole_batch_routing_and_explicit_split(self):
        batch = feedback()
        self.assertEqual(validate_triage(request("local", "change"), batch)["route"], "change")
        self.assertEqual(validate_triage(request("clarify", "change"), batch)["route"], "change")
        self.assertEqual(validate_triage(request("local", "clarify"), batch)["route"], "clarify")
        split = validate_triage(request("local", "change", deferred_item_ids=["date"],
                                        split_authorized=True, split_reason="User requested next delivery"), batch)
        self.assertEqual(split["route"], "local")
        self.assertEqual(split["active_item_ids"], ["label"])

    def test_deferral_cannot_silently_hide_feedback(self):
        batch = feedback()
        for changes in (
            {"deferred_item_ids": ["date"]},
            {"deferred_item_ids": ["date"], "split_authorized": True},
            {"deferred_item_ids": ["missing"], "split_authorized": True, "split_reason": "explicit"},
            {"deferred_item_ids": ["label", "date"], "split_authorized": True, "split_reason": "explicit"},
            {"deferred_item_ids": ["date", "date"], "split_authorized": True, "split_reason": "explicit"},
            {"split_authorized": 1}, {"split_reason": ""}, {"feedback_id": "HF-0"},
        ):
            with self.subTest(changes=changes), self.assertRaises(CogitoError):
                validate_triage(request(**changes), batch)

    def test_triage_covers_each_issue_once_and_rejects_unknown_fields(self):
        for mutation in ("missing", "duplicate", "extra", "disposition", "reason", "unknown"):
            value = request()
            if mutation == "missing": value["assessments"].pop()
            elif mutation == "duplicate": value["assessments"][1]["id"] = "label"
            elif mutation == "extra": value["assessments"][1]["id"] = "other"
            elif mutation == "disposition": value["assessments"][0]["disposition"] = ["local"]
            elif mutation == "reason": value["assessments"][0]["reason"] = " "
            else: value["route"] = "local"
            with self.subTest(mutation=mutation), self.assertRaises(CogitoError):
                validate_triage(value, feedback())

    def test_budget_is_independent_and_cannot_exceed_three(self):
        state = {"counters": {"corrections": 3}, "limits": {}}
        self.assertEqual(validate_human_budget(state), 1)
        for prior in range(3):
            state["counters"]["human_corrections"] = prior
            self.assertEqual(validate_human_budget(state), prior + 1)
        state["counters"]["human_corrections"] = 3
        state["limits"]["human_corrections"] = 100
        with self.assertRaisesRegex(CogitoError, "exhausted"):
            validate_human_budget(state)
        for count, limit in ((True, 3), (-1, 3), (0, True), (0, 0), (0, "3")):
            with self.subTest(count=count, limit=limit), self.assertRaises(CogitoError):
                validate_human_budget({"counters": {"human_corrections": count}, "limits": {"human_corrections": limit}})
        with self.assertRaisesRegex(CogitoError, "exhausted"):
            validate_human_budget({"counters": {"human_corrections": 1}, "limits": {"human_corrections": 1}})

    def test_grant_requires_current_fully_resolved_local_batch(self):
        self.assertTrue(can_close_after_fixes(human()))
        for mutation in ("new-feedback", "new-triage", "incomplete", "duplicate", "escalated", "unresolved", "change", "missing"):
            record = human()
            if mutation == "new-feedback": record["feedback"]["id"] = "HF-2"
            elif mutation == "new-triage": record["triage"]["feedback_id"] = "HF-0"
            elif mutation == "incomplete": record["resolution"]["resolved_item_ids"].pop()
            elif mutation == "duplicate": record["resolution"]["resolved_item_ids"].append("date")
            elif mutation == "escalated": record["escalated"] = True
            elif mutation == "unresolved": record["unresolved_item_ids"] = ["date"]
            elif mutation == "change": record["triage"]["route"] = "change"
            else: record.pop("resolution")
            with self.subTest(mutation=mutation):
                self.assertFalse(can_close_after_fixes(record))

    def test_authorized_split_can_close_only_selected_batch(self):
        record = human()
        record["triage"] = validate_triage(request("local", "change", deferred_item_ids=["date"],
                                                   split_authorized=True, split_reason="Deferred by user"), record["feedback"])
        record["resolution"]["resolved_item_ids"] = ["label"]
        self.assertTrue(can_close_after_fixes(record))
        record["triage"]["split_authorized"] = False
        self.assertFalse(can_close_after_fixes(record))

    def test_resolution_requires_exact_ids_and_explanation(self):
        record = human()
        for changes in (
            {"feedback_id": "HF-0"}, {"feedback_id": []},
            {"resolved_item_ids": []}, {"resolved_item_ids": ["label"]},
            {"resolved_item_ids": ["label", "date", "other"]},
            {"resolved_item_ids": ["label", "label"]},
            {"summary": " "}, {"passed": True},
        ):
            value = {**record["resolution"], **changes}
            with self.subTest(changes=changes), self.assertRaises(CogitoError):
                validate_resolution(value, record)

    def test_rules_are_pure_and_return_detached_results(self):
        record = human()
        value = request()
        before = copy.deepcopy((record, value))
        with mock.patch("builtins.open", side_effect=AssertionError("pure rules must not read files")):
            batch = validate_feedback(record["feedback"])
            triage = validate_triage(value, batch)
            resolution = validate_resolution(record["resolution"], record)
            self.assertTrue(can_close_after_fixes(record))
        batch["items"].clear()
        triage["assessments"].clear()
        resolution["resolved_item_ids"].clear()
        self.assertEqual((record, value), before)


if __name__ == "__main__":
    unittest.main()
