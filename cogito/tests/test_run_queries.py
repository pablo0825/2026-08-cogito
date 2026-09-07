"""Run queries derive detached answers from snapshots without accessing storage."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_run_queries import build_completion_report, build_mutation_receipt, derive_next_action


class RunQueryTests(unittest.TestCase):
    def test_mutation_receipt_is_bounded_detached_and_uses_the_projection(self) -> None:
        projection = {
            "run_id": "DEV-receipt", "state": "awaiting-package-approval",
            "sequence": 12, "last_event_hash": "a" * 64, "kind": "feature",
            "candidate_package_hash": "b" * 64,
            "planning": {
                "round": 1, "proposal_hash": "c" * 64, "revision": None,
                "candidate": {"files": {
                    f"docs/plan-{index:02d}.md": {"content_base64": "eA==" * 10_000}
                    for index in range(30)
                }},
            },
            "tasks": {"T-1": {"id": "T-1", "status": "pending"}},
            "agent_results": [{"large": "result" * 10_000}],
            "evidence": {"large": "evidence" * 10_000},
        }
        before = copy.deepcopy(projection)
        receipt = build_mutation_receipt(projection)
        self.assertEqual(receipt, {
            "run_id": "DEV-receipt", "state": "awaiting-package-approval",
            "sequence": 12, "last_event_hash": "a" * 64,
            "next": {
                "state": "awaiting-package-approval",
                "next_action": "request-package-approval",
                "planning_round": 1,
                "candidate_package_hash": "b" * 64,
                "proposal_hash": "c" * 64,
            },
        })
        self.assertLess(len(json.dumps({"ok": True, "data": receipt}).encode()), 2 * 1024)
        self.assertNotIn("files", json.dumps(receipt))
        receipt["next"]["next_action"] = "changed"
        self.assertEqual(projection, before)

    def test_preparation_distinguishes_mini_packages_and_rejects_unknown_states(self) -> None:
        for kind, action in (
            ("feature", "draft-shared-understanding"),
            ("maintenance", "assess-mini-package-eligibility"),
            ("documentation", "assess-mini-package-eligibility"),
        ):
            with self.subTest(kind=kind):
                projection = {"state": "preparing", "kind": kind}
                before = copy.deepcopy(projection)
                self.assertEqual(derive_next_action(projection), {"state": "preparing", "next_action": action})
                self.assertEqual(projection, before)
        with self.assertRaises(CogitoError):
            derive_next_action({"state": "unknown"})
        self.assertEqual(derive_next_action({"state": "accepted"}), {"state": "accepted", "next_action": "report-completion"})

    def test_execution_answer_respects_occupied_slices_dependencies_and_capacity(self) -> None:
        projection = {"state": "executing", "max_workers": 2, "tasks": {
            "A": {"id": "A", "slice_id": "FS-A", "status": "running"},
            "B": {"id": "B", "slice_id": "FS-A", "status": "pending"},
            "C": {"id": "C", "slice_id": "FS-C", "status": "pending", "depends_on": ["D"]},
            "D": {"id": "D", "slice_id": "FS-D", "status": "complete"},
            "E": {"id": "E", "slice_id": "FS-E", "status": "pending"},
        }}
        before = copy.deepcopy(projection)
        self.assertEqual(derive_next_action(projection), {
            "state": "executing", "next_action": "dispatch-ready-workers",
            "ready_tasks": ["E"], "worker_capacity": 1,
        })
        self.assertEqual(projection, before)
        projection["tasks"]["D"]["status"] = "integrated"
        self.assertEqual(derive_next_action(projection)["ready_tasks"], ["C"])
        projection["max_workers"] = 1
        answer = derive_next_action(projection)
        self.assertEqual((answer["ready_tasks"], answer["worker_capacity"]), ([], 0))
        projection["tasks"]["C"]["depends_on"] = ["missing"]
        before = copy.deepcopy(projection)
        with self.assertRaises(CogitoError):
            derive_next_action(projection)
        self.assertEqual(projection, before)

    def test_completion_report_preserves_nested_extensions_in_a_deep_copy(self) -> None:
        result = {
            "schema_version": "3.0", "run_id": "DEV-query", "status": "accepted",
            "package_hash": "a" * 64, "effective_contract_hash": "b" * 64,
            "integration_commits": ["c" * 40], "slice_dispositions": {},
            "checks": [{"id": "C-1", "status": "passed", "evidence": "/evidence/C-1.json", "extension": {"notes": ["kept"]}}],
            "reviews": [{"reviewer": "reviewer-1", "extension": ["kept"]}],
            "amendments": [], "human_gate": {"required": False, "outcome": "not-required"},
            "remaining_risks": ["follow-up"],
        }
        before = copy.deepcopy(result)
        expected = {"run_id": "DEV-query", "status": "accepted", "final_commit": "d" * 40}
        expected.update({key: copy.deepcopy(result[key]) for key in ("checks", "reviews", "amendments", "human_gate", "remaining_risks")})
        report = build_completion_report("DEV-query", "d" * 40, result)
        self.assertEqual(report, expected)
        report["checks"][0]["extension"]["notes"].append("edited output")
        report["reviews"][0]["extension"].append("edited output")
        report["remaining_risks"].clear()
        self.assertEqual(result, before)
        self.assertEqual(build_completion_report("DEV-query", "d" * 40, result), expected)
        del result["checks"]
        before = copy.deepcopy(result)
        with self.assertRaises(CogitoError):
            build_completion_report("DEV-query", "d" * 40, result)
        self.assertEqual(result, before)


if __name__ == "__main__":
    unittest.main()
