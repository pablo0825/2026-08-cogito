"""Maintenance amendments retain snapshots until their sole final commit."""

from __future__ import annotations

import copy
import unittest

from test_finalization_rules import context
from cogito_common import CogitoError
from cogito_finalization_rules import validate_finalization_records
from cogito_result_contract import validate_result
from cogito_run_queries import build_completion_report


def snapshot_context(kind: str = "maintenance"):
    value = context(kind)
    completions = {
        event["payload"]["amendment_id"]: event["payload"]
        for event in value.events
        if event["type"] in {"technical-correction-complete", "review-fix-complete"}
    }
    for index, amendment in enumerate(value.result["amendments"]):
        amendment.pop("commit_id")
        amendment.update({"base_commit": "a" * 40, "content_tree": str(index + 1) * 40})
        completions[amendment["id"]].update({
            "commit_id": amendment["base_commit"],
            "completion_mode": "working-tree",
            "content_tree": amendment["content_tree"],
        })
    return value


class MaintenanceAmendmentRecordTests(unittest.TestCase):
    def test_multiple_corrections_keep_distinct_snapshots_without_mutation(self):
        value = snapshot_context()
        before = copy.deepcopy(value)
        validate_result(value.result)
        self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
        self.assertNotEqual(
            value.result["amendments"][0]["content_tree"],
            value.result["amendments"][1]["content_tree"],
        )
        self.assertEqual(value, before)

    def test_feature_cannot_use_working_tree_amendments(self):
        value = snapshot_context("feature")
        validate_result(value.result)
        with self.assertRaisesRegex(CogitoError, "Maintenance correction history"):
            validate_finalization_records(value)

    def test_result_cannot_mix_commit_with_either_snapshot_field(self):
        for snapshot_fields in (
            {"base_commit": "a" * 40},
            {"content_tree": "1" * 40},
            {"base_commit": "a" * 40, "content_tree": "1" * 40},
        ):
            with self.subTest(fields=snapshot_fields):
                value = context("maintenance")
                value.result["amendments"][0].update(snapshot_fields)
                before = copy.deepcopy(value.result)
                with self.assertRaisesRegex(CogitoError, "cannot mix"):
                    validate_result(value.result)
                self.assertEqual(value.result, before)

    def test_snapshot_requires_valid_base_and_tree(self):
        for field in ("base_commit", "content_tree"):
            for invalid in (None, "not-an-object-id", ""):
                with self.subTest(field=field, invalid=invalid):
                    value = snapshot_context()
                    if invalid is None:
                        del value.result["amendments"][0][field]
                    else:
                        value.result["amendments"][0][field] = invalid
                    with self.assertRaises(CogitoError):
                        validate_result(value.result)

    def test_snapshot_must_match_completion_base_and_tree(self):
        for field in ("base_commit", "content_tree"):
            with self.subTest(field=field):
                value = snapshot_context()
                value.result["amendments"][0][field] = "f" * 40
                before = copy.deepcopy(value)
                with self.assertRaisesRegex(CogitoError, "Maintenance correction history"):
                    validate_finalization_records(value)
                self.assertEqual(value, before)

    def test_matching_snapshot_and_completion_still_require_start_head(self):
        value = snapshot_context()
        value.result["amendments"][0]["base_commit"] = "f" * 40
        value.events[3]["payload"]["commit_id"] = "f" * 40
        with self.assertRaisesRegex(CogitoError, "Maintenance correction history"):
            validate_finalization_records(value)

    def test_snapshot_cannot_replace_a_recorded_commit_completion(self):
        value = snapshot_context()
        del value.events[3]["payload"]["completion_mode"]
        with self.assertRaisesRegex(CogitoError, "correction history"):
            validate_finalization_records(value)

    def test_report_adds_final_commit_to_detached_snapshot_records(self):
        value = snapshot_context()
        before = copy.deepcopy(value.result)
        final_commit = "e" * 40
        report = build_completion_report(value.run_id, final_commit, value.result)
        self.assertEqual(
            [item["commit_id"] for item in report["amendments"]],
            [final_commit, final_commit],
        )
        for source, presented in zip(value.result["amendments"], report["amendments"]):
            self.assertEqual(presented, {**source, "commit_id": final_commit})
        self.assertEqual(value.result, before)
        report["amendments"][0]["content_tree"] = "f" * 40
        self.assertEqual(value.result, before)


if __name__ == "__main__":
    unittest.main()
