"""Executable contracts, compatible JSON handoff, and fail-closed boundaries."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cogito_common import CogitoError, hash_json
from cogito_contracts import (
    effective_contract_hash, materialize_contract, package_hash,
    validate_agent_result, validate_amendment, validate_package,
    validate_project_policy,
)
from cogito_finalization import validate_finalization
from cogito_gate_validation import validate_policy
from cogito_project_graph import (
    formalize_project_graph, render_project_graph_mermaid, validate_project_graph,
)
from cogito_result_contract import validate_result
from cogito_run_store import RunStore
from cogito_runner import run_check
from cogito_test_support import minimal_package


def agent_result() -> dict:
    return {
        "schema_version": "3.0", "run_id": "DEV-20260901-001", "task_id": "T-1",
        "agent_id": "worker-1", "role": "implementer", "status": "complete",
        "base_commit": "a" * 40, "head_commit": "b" * 40,
        "changed_paths": ["src/code.py"], "evidence": [], "risks": [],
        "requested_transition": "verifying",
    }


def project_graph() -> dict:
    return {
        "schema_version": "3.0", "active_run_id": None,
        "slices": {"FS-001": {"disposition": "active"}}, "dependencies": [],
    }


def final_result() -> dict:
    return {
        "schema_version": "3.0", "run_id": "DEV-20260901-001", "status": "accepted",
        "package_hash": package_hash(minimal_package()),
        "effective_contract_hash": package_hash(minimal_package()),
        "integration_commits": ["b" * 40], "slice_dispositions": {"FS-001": "accepted"},
        "checks": [{"id": "C-1", "status": "passed", "evidence": "/tmp/check.json"}],
        "reviews": [{"reviewer": "reviewer-1"}], "amendments": [],
        "human_gate": {"required": False, "outcome": "not-required"}, "remaining_risks": [],
    }


def replace_at(value: dict, path: tuple, replacement: object) -> None:
    parent = value
    for key in path[:-1]:
        parent = parent[key]
    parent[path[-1]] = copy.deepcopy(replacement)


class ShapeContractTests(unittest.TestCase):
    def assert_rejected_variants(self, factory, validator, variants) -> None:
        for path, replacement in variants:
            with self.subTest(path=path, replacement=replacement):
                value = factory()
                replace_at(value, path, replacement)
                before = copy.deepcopy(value)
                with self.assertRaises(CogitoError):
                    validator(value)
                self.assertEqual(value, before, "failed validation must not mutate input")

    def test_wrong_top_level_types_fail_with_domain_errors(self) -> None:
        validators = [validate_package, validate_agent_result, validate_project_graph,
                      validate_project_policy, validate_result]
        for validator in validators:
            for value in (None, False, 1, "bad", [], [1]):
                with self.subTest(validator=validator.__name__, value=value):
                    with self.assertRaises(CogitoError):
                        validator(value)

    def test_required_package_and_agent_fields_are_enforced(self) -> None:
        for factory, validator in ((minimal_package, validate_package), (agent_result, validate_agent_result)):
            for field in factory():
                if field == "mini_package":  # Existing feature Packages may omit false.
                    continue
                with self.subTest(validator=validator.__name__, field=field):
                    value = factory()
                    del value[field]
                    with self.assertRaises(CogitoError):
                        validator(value)

    def test_package_shapes_reject_malformed_consumed_fields(self) -> None:
        self.assert_rejected_variants(minimal_package, validate_package, [
            (("kind",), []), (("run_id",), 123), (("delivery_branch",), 123),
            (("baseline_commit",), 1234567), (("mini_package",), "false"),
            (("shared_understanding", "hash"), None), (("slices",), {}),
            (("slices", 0), 42), (("slices", 0, "id"), "bad id"),
            (("slices", 0, "id"), []), (("slices", 0, "type"), {}),
            (("slices", 0, "spec", "path"), None),
            (("slices", 0, "worker", "branch"), 42),
            (("slices", 0, "worker", "allowed_paths"), [None]),
            (("boundary", "evidence"), [None]),
            (("approved_paths",), [None]), (("stop_conditions",), [None]),
            (("stop_conditions",), [{"id": "STOP", "condition": "x", "outcome": []}]),
            (("source_registry",), [{"path": "src/a", "hash": "a" * 64, "relevance": {}, "disposition": "adopted"}]),
            (("execution_dag", "tasks"), [None]),
            (("execution_dag", "tasks", 0, "id"), {}),
            (("execution_dag", "tasks", 0, "slice_id"), []),
            (("execution_dag", "tasks", 0, "paths"), [1]),
            (("execution_dag", "tasks", 0, "status"), {}),
            (("execution_dag", "edges"), [{"from": [], "to": "T-1"}]),
            (("human_gate", "predicates"), [{"id": [], "applicable": True}]),
            (("human_gate", "predicates"), [{"id": "HI", "applicable": "false"}]),
            (("human_gate", "high_risk_hotspots"), [None]),
            (("limits", "format_repairs"), True),
            (("policy_snapshot", "max_workers"), True),
            (("policy_snapshot", "required_checks"), [{}]),
            (("policy_snapshot", "allowed_environment"), ["NAME=value"]),
        ])

    def test_checks_use_one_contract_in_packages_and_amendments(self) -> None:
        malformed = [
            {"id": "C:1"}, {"id": []}, {"argv": "echo ok"}, {"argv": [123]},
            {"argv": ["bad\0argument"]}, {"required": "false"},
            {"cwd": 1}, {"cwd": "../outside"},
            {"timeout_seconds": "5"}, {"timeout_seconds": True},
            {"timeout_seconds": 0}, {"timeout_seconds": 3601},
            {"redact_patterns": [123]}, {"redact_patterns": ["["]},
            {"redact_patterns": ["a{99999999999999999999}"]},
            {"env_allowlist": [None]},
        ]
        for fields in malformed:
            with self.subTest(fields=fields):
                package = minimal_package()
                package["checks"][0].update(fields)
                with self.assertRaises(CogitoError):
                    validate_package(package)
                amendment = {"id": "TA-001", "reason": "補檢查", "added_checks": [
                    {"id": "C-2", "argv": ["python3", "-V"], **fields},
                ]}
                with self.assertRaises(CogitoError):
                    validate_amendment(minimal_package(), [], amendment)

    def test_amendment_shapes_fail_before_materialization(self) -> None:
        factory = lambda: {"id": "TA-001", "reason": "fix", "path_fixes": ["src/code.py"]}
        self.assert_rejected_variants(factory, lambda a: validate_amendment(minimal_package(), [], a), [
            (("id",), []), (("reason",), None), (("added_checks",), None),
            (("added_tasks",), [42]), (("path_fixes",), [None]),
        ])
        with self.assertRaises(CogitoError):
            validate_amendment(minimal_package(), [None], factory())

    def test_agent_result_nested_shapes(self) -> None:
        self.assert_rejected_variants(agent_result, validate_agent_result, [
            (("run_id",), "wrong"), (("task_id",), []), (("agent_id",), None),
            (("role",), []), (("status",), {}), (("base_commit",), 1234567),
            (("changed_paths",), [None]), (("evidence",), [123]),
            (("risks",), [{}]), (("requested_transition",), []),
            (("reviewed_implementer",), []), (("repair_attempt",), True),
        ])

    def test_graph_rejects_bad_nodes_and_edges_before_render_or_formalization(self) -> None:
        variants = [
            (("slices",), []), (("slices", "FS-001"), 42),
            (("slices", "FS-001", "disposition"), []),
            (("slices", "FS-001", "spec"), {"path": None, "hash": "a" * 64}),
            (("slices", "FS-001", "lineage"), [None]),
            (("dependencies",), [None]), (("dependencies",), [{"from": "FS-001"}]),
            (("dependencies",), [{"from": [], "to": "FS-001"}]),
            (("dependencies",), [{"from": "FS-001", "to": "missing"}]),
            (("active_run_id",), []),
        ]
        for validator in (validate_project_graph, render_project_graph_mermaid,
                          lambda g: formalize_project_graph(g, minimal_package(), "DEV-1")):
            self.assert_rejected_variants(project_graph, validator, variants)

    def test_policy_fields_fail_before_comparison(self) -> None:
        self.assert_rejected_variants(lambda: {"schema_version": "3.0"}, validate_project_policy, [
            (("max_workers",), "3"), (("max_workers",), 0),
            (("fetch_allowed",), "false"), (("allowed_environment",), [123]),
            (("required_checks",), [{}]), (("max_check_output_bytes",), True),
            (("max_check_output_bytes",), 1023), (("human_gate",), []),
            (("human_gate",), {"predicates": [None]}),
            (("human_gate",), {"required": 1}),
        ])

    def test_result_shapes_fail_before_git_history_checks(self) -> None:
        for field in final_result():
            with self.subTest(missing=field):
                value = final_result()
                del value[field]
                with self.assertRaises(CogitoError):
                    validate_result(value)
        self.assert_rejected_variants(final_result, validate_result, [
            (("status",), "pending"), (("run_id",), []), (("package_hash",), "bad"),
            (("integration_commits",), [None]), (("slice_dispositions",), []),
            (("slice_dispositions", "FS-001"), {}), (("checks",), [42]),
            (("checks", 0, "evidence"), []), (("reviews",), [None]),
            (("reviews", 0, "reviewer"), []), (("reviews", 0, "outcome"), []),
            (("amendments",), [{"id": "TA-1"}]),
            (("human_gate", "required"), "false"), (("remaining_risks",), [{}]),
        ])

    def test_successful_validation_preserves_json_extensions_and_hashes(self) -> None:
        for factory, validator in ((minimal_package, validate_package),
                                   (agent_result, validate_agent_result),
                                   (project_graph, validate_project_graph),
                                   (final_result, validate_result),
                                   (lambda: {"schema_version": "3.0"}, validate_project_policy)):
            with self.subTest(validator=validator.__name__):
                value = factory()
                value["display_metadata"] = {"title": "核准摘要", "notes": ["保留順序", "原始內容"]}
                before = json.dumps(value, ensure_ascii=False)
                digest = hash_json(value)
                validator(value)
                validator(json.loads(before))
                self.assertEqual(json.dumps(value, ensure_ascii=False), before)
                self.assertEqual(hash_json(value), digest)

    def test_existing_defaults_and_sparse_records_are_not_filled_in(self) -> None:
        package = minimal_package()
        del package["mini_package"]
        del package["human_gate"]["high_risk_hotspots"]
        package["checks"][0]["extensions"] = {"display": "test"}
        package["approved_paths"].append(package["approved_paths"][0])
        before = copy.deepcopy(package)
        validate_package(package)
        self.assertEqual(package, before)
        graph = project_graph()
        del graph["active_run_id"]
        before_graph = copy.deepcopy(graph)
        render_project_graph_mermaid(graph)
        self.assertEqual(graph, before_graph)
        result = final_result()  # Established E2E summaries omit review.outcome.
        validate_result(result)
        self.assertNotIn("outcome", result["reviews"][0])

    def test_existing_package_and_effective_contract_hashes_are_unchanged(self) -> None:
        package = minimal_package()
        amendment = {"id": "TA-001", "reason": "新增檢查", "added_checks": [{"id": "C-2", "argv": ["python3", "-V"]}]}
        self.assertEqual(package_hash(package), "af2a97173b49399e650552df824f5597208ade9676a303e18f60498958417392")
        self.assertEqual(effective_contract_hash(package, [amendment]), "aebcd0e87686ca3057205b15ab12120350656eebf57097e844335ec57b5bafee")
        before = copy.deepcopy((package, amendment))
        effective = materialize_contract(package, [amendment])
        self.assertEqual((package, amendment), before)
        self.assertEqual(effective["checks"][-1], amendment["added_checks"][0])


class ContractBoundaryTests(unittest.TestCase):
    def test_invalid_check_never_starts_a_process(self) -> None:
        for amendments in (False, True):
            with self.subTest(amendments=amendments):
                package = minimal_package()
                bad = {"id": "C-2", "argv": ["python3", "-V"], "redact_patterns": [123]}
                prior = [{"id": "TA-1", "reason": "check", "added_checks": [bad]}] if amendments else []
                if not amendments:
                    package["checks"] = [bad]
                with mock.patch("cogito_runner.run_bounded_process") as process:
                    with self.assertRaises(CogitoError):
                        run_check(package, "C-2", "/path/never/read", prior)
                    process.assert_not_called()

    def test_invalid_package_preparation_does_not_append_or_publish(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = minimal_package()
            store = RunStore(directory, package["run_id"])
            store.create("feature")
            before = store.events_path.read_bytes()
            package["checks"][0]["timeout_seconds"] = "5"
            with self.assertRaises(CogitoError):
                store.prepare_package(package, "bad-package")
            self.assertEqual(store.events_path.read_bytes(), before)
            self.assertFalse((Path(directory) / "docs/cogito/packages").exists())

    def test_approval_keeps_spec_plan_and_extensions_bound_to_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            package = minimal_package()
            package["display_metadata"] = {"title": "核准內容"}
            before = copy.deepcopy(package)
            store = RunStore(directory, package["run_id"])
            store.create("feature")
            store.transition("shared-understanding-ready", {"shared_understanding_hash": package["shared_understanding"]["hash"]})
            store.transition("shared-understanding-confirmed", {"confirmed": True})
            store.transition("boundary-complete", package["boundary"])
            state = store.prepare_package(package, "candidate")
            digest = state["candidate_package_hash"]
            changed = copy.deepcopy(package)
            changed["slices"][0]["spec"]["hash"] = "f" * 64
            with self.assertRaises(CogitoError):
                store.approve_package(changed, "changed-candidate")
            state = store.approve_package(package, "approved")
            persisted = store.approved_package()
            self.assertEqual(state["package_hash"], digest)
            self.assertEqual(persisted, {**before, "package_hash": digest})
            self.assertEqual(package, before)

    def test_invalid_policy_is_rejected_as_domain_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "docs/cogito/project-policy.json"
            path.parent.mkdir(parents=True)
            policy = {"schema_version": "3.0", "required_checks": [None]}
            path.write_text(json.dumps(policy))
            package = minimal_package()
            package["policy_snapshot"]["hash"] = hash_json(policy)
            with self.assertRaises(CogitoError):
                validate_policy(root, package)

    def test_finalization_validates_committed_artifacts_before_reading_events(self) -> None:
        result, graph = final_result(), project_graph()
        for broken in ("result", "graph", "json"):
            def git(*args):
                if args[0] == "branch":
                    return "main"
                if args[0] == "rev-parse":
                    return "b" * 40
                if args[0] == "show":
                    if "results/" in args[1]:
                        if broken == "json":
                            return "{bad"
                        return json.dumps({**result, "checks": [42]} if broken == "result" else result)
                    return json.dumps({**graph, "slices": {"FS-001": 42}} if broken == "graph" else graph)
                return ""
            with self.subTest(broken=broken), mock.patch("cogito_finalization.materialize_contract") as materialize:
                load_events = mock.Mock()
                with self.assertRaises(CogitoError):
                    validate_finalization(
                        run_id=result["run_id"], package=minimal_package(),
                        state={"effective_contract_hash": result["effective_contract_hash"]},
                        load_events=load_events, result_path=f"docs/cogito/results/{result['run_id']}.json",
                        project_graph_path="docs/cogito/project-graph.json", final_commit="b" * 40, git=git,
                    )
                load_events.assert_not_called()
                materialize.assert_not_called()

    def test_cli_reports_contract_failures_as_json_without_tracebacks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "package.json"
            package = minimal_package()
            package["checks"][0]["redact_patterns"] = [123]
            path.write_text(json.dumps(package))
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "cogito_gate.py"), "validate", "--type", "package", "--input", str(path)],
                capture_output=True, text=True,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertEqual(completed.stdout, "")
            error = json.loads(completed.stderr)
            self.assertFalse(error["ok"])
            self.assertIn("redact_patterns", error["error"])


if __name__ == "__main__":
    unittest.main()
