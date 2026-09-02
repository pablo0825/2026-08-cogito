"""Finalization record agreement can be checked without Git or filesystem access."""

from __future__ import annotations

import copy
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_finalization_rules import FinalizationContext, validate_finalization_records
from test_runtime_contract import minimal_package
from test_v3_safety_regressions import package as mini_package


def context(kind: str = "feature") -> FinalizationContext:
    package = minimal_package() if kind == "feature" else mini_package("maintenance")
    run_id = package["run_id"]
    owned = {item["id"] for item in package["slices"]}
    approved = {
        "schema_version": "3.0", "active_run_id": run_id,
        "slices": {"FS-OLD": {"disposition": "accepted", "completed_by": "DEV-old"}},
        "dependencies": [],
    }
    for slice_id in owned:
        approved["slices"][slice_id] = {"disposition": "active"}
        approved["dependencies"].append({"from": "FS-OLD", "to": slice_id})
    graph = copy.deepcopy(approved)
    graph["active_run_id"] = None
    for slice_id in owned:
        graph["slices"][slice_id] = {"disposition": "accepted", "completed_by": run_id}
    summaries = [{"id": "TA-1", "commit_id": "c" * 40}, {"id": "TA-2", "commit_id": "d" * 40}]
    events = [
        {"type": "package-approved", "payload": {"project_graph_snapshot": approved}},
        {"type": "start-gate-passed", "payload": {"delivery_head": "a" * 40}},
        {"type": "technical-amendment-added", "payload": {"amendment": {"id": "TA-1"}}},
        {"type": "technical-correction-complete", "payload": {"amendment_id": "TA-1", "commit_id": "c" * 40}},
        {"type": "technical-amendment-added", "payload": {"amendment": {"id": "TA-2"}}},
        {"type": "review-fix-complete", "payload": {"amendment_id": "TA-2", "commit_id": "d" * 40}},
        {"type": "slice-integration-complete", "payload": {"commit_id": "a" * 40}},
        {"type": "integration-complete", "payload": {"commit_id": "b" * 40}},
        {"type": "auto-accept-ready", "payload": {"evidence": ["/evidence/C-1.json"], "delivery_head": "b" * 40}},
    ]
    state = {
        "effective_contract_hash": "e" * 64,
        "agent_results": [{"role": "reviewer", "status": "complete", "agent_id": "reviewer-1"}],
    }
    result = {
        "schema_version": "3.0", "run_id": run_id, "status": "accepted",
        "package_hash": package_hash(package), "effective_contract_hash": state["effective_contract_hash"],
        "integration_commits": ["a" * 40, "b" * 40],
        "slice_dispositions": {slice_id: "accepted" for slice_id in owned},
        "checks": [{"id": "C-1", "status": "passed", "evidence": "/evidence/C-1.json"}],
        "reviews": [{"reviewer": "reviewer-1"}] if kind == "feature" else [],
        "amendments": summaries, "human_gate": {"required": False, "outcome": "not-required"},
        "remaining_risks": [],
    }
    return FinalizationContext(
        run_id=run_id, package=package, state=state, events=events,
        result=result, graph=graph, effective_contract={"checks": [{"id": "C-1"}]},
    )


class FinalizationRecordTests(unittest.TestCase):
    def assert_rejected_unchanged(self, value: FinalizationContext) -> None:
        before = copy.deepcopy(value)
        with self.assertRaises(CogitoError):
            validate_finalization_records(value)
        self.assertEqual(value, before)

    def test_feature_and_maintenance_return_detached_evidence_without_mutation(self) -> None:
        for kind in ("feature", "maintenance"):
            with self.subTest(kind=kind):
                value = context(kind)
                before = copy.deepcopy(value)
                evidence = validate_finalization_records(value)
                self.assertEqual(evidence, {"/evidence/C-1.json"})
                evidence.add("edited output")
                self.assertEqual(value, before)
                self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
                with self.assertRaises(FrozenInstanceError):
                    value.run_id = "DEV-replaced"

    def test_result_must_match_run_package_and_effective_contract(self) -> None:
        for field, different in (("run_id", "DEV-other"), ("package_hash", "f" * 64), ("effective_contract_hash", "f" * 64)):
            with self.subTest(field=field):
                value = context()
                value.result[field] = different
                self.assert_rejected_unchanged(value)

    def test_graph_preserves_dependencies_unrelated_history_and_clears_active_run(self) -> None:
        for field in ("dependencies", "unrelated-history", "active-run"):
            with self.subTest(field=field):
                value = context()
                if field == "dependencies":
                    value.graph["dependencies"] = []
                elif field == "unrelated-history":
                    value.graph["slices"]["FS-OLD"]["completed_by"] = "DEV-other"
                else:
                    value.graph["active_run_id"] = value.run_id
                self.assert_rejected_unchanged(value)

    def test_every_owned_slice_must_be_accepted_by_this_run(self) -> None:
        for field in ("missing-result-slice", "result-disposition", "graph-disposition", "completed-by"):
            with self.subTest(field=field):
                value = context()
                if field == "missing-result-slice":
                    value.result["slice_dispositions"] = {}
                elif field == "result-disposition":
                    value.result["slice_dispositions"]["FS-001"] = "cancelled"
                elif field == "graph-disposition":
                    value.graph["slices"]["FS-001"]["disposition"] = "active"
                else:
                    value.graph["slices"]["FS-001"]["completed_by"] = "DEV-other"
                self.assert_rejected_unchanged(value)

    def test_amendment_order_and_completion_commits_match_history(self) -> None:
        for field in ("order", "missing", "commit"):
            with self.subTest(field=field):
                value = context()
                if field == "order":
                    value.result["amendments"].reverse()
                elif field == "missing":
                    value.result["amendments"].pop()
                else:
                    value.result["amendments"][0]["commit_id"] = "f" * 40
                self.assert_rejected_unchanged(value)

    def test_required_checks_default_to_required_and_optional_checks_may_be_absent(self) -> None:
        value = context()
        value.effective_contract["checks"].append({"id": "C-optional", "required": False})
        self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
        for problem in ("failed", "missing-required-check"):
            with self.subTest(problem=problem):
                invalid = copy.deepcopy(value)
                if problem == "failed":
                    invalid.result["checks"][0]["status"] = "failed"
                else:
                    invalid.effective_contract["checks"].append({"id": "C-new-required"})
                self.assert_rejected_unchanged(invalid)

    def test_integration_commits_match_the_exact_history_order(self) -> None:
        for commits in (["b" * 40, "a" * 40], ["a" * 40], ["a" * 40, "b" * 40, "f" * 40]):
            with self.subTest(commits=commits):
                value = context()
                value.result["integration_commits"] = commits
                self.assert_rejected_unchanged(value)

    def test_evidence_paths_match_the_latest_final_gate_set(self) -> None:
        value = context()
        value.events.insert(-1, {"type": "auto-accept-ready", "payload": {"evidence": ["/old/evidence.json"]}})
        self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
        value.result["checks"][0]["evidence"] = "/old/evidence.json"
        self.assert_rejected_unchanged(value)

    def test_required_human_approval_needs_an_event_and_a_matching_summary(self) -> None:
        value = context()
        value.events[-1]["type"] = "human-review-required"
        value.result["human_gate"] = {"required": True, "outcome": "approved"}
        self.assert_rejected_unchanged(value)
        value.events.append({"type": "human-approved", "payload": {"approved": True}})
        self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
        value.result["human_gate"] = {"required": False, "outcome": "not-required"}
        self.assert_rejected_unchanged(value)

    def test_reviewer_set_matches_only_recorded_completed_reviewers(self) -> None:
        value = context()
        value.state["agent_results"].extend([
            {"role": "implementer", "status": "complete", "agent_id": "implementer-1"},
            {"role": "reviewer", "status": "needs-fix", "agent_id": "reviewer-unfinished"},
        ])
        self.assertEqual(validate_finalization_records(value), {"/evidence/C-1.json"})
        for reviews in ([], [{"reviewer": "someone-else"}], value.result["reviews"] + [{"reviewer": "reviewer-unfinished"}]):
            with self.subTest(reviews=reviews):
                self.assert_rejected_unchanged(replace(value, result={**value.result, "reviews": reviews}))


if __name__ == "__main__":
    unittest.main()
