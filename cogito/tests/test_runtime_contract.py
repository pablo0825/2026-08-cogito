"""Behavioral contract for the Cogito 3.0 gate runtime.

These tests intentionally exercise policy through public runtime functions instead
of searching prose.  That keeps the skill instructions small and makes the gate
the executable source of truth for state, retry, DAG, and amendment rules.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]
RUNTIME_PATH = COGITO / "scripts" / "cogito_runtime.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("cogito_runtime", RUNTIME_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNTIME_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def minimal_package() -> dict:
    return {
        "schema_version": "3.0",
        "run_id": "DEV-20260901-001",
        "kind": "feature",
        "delivery_branch": "main",
        "baseline_commit": "a" * 40,
        "shared_understanding": {"hash": "a" * 64},
        "boundary": {"decision": "single-slice", "evidence": ["small surface"]},
        "mini_package": False,
        "slices": [{
            "id": "FS-001", "type": "feature",
            "spec": {"path": "docs/spec.md", "hash": "b" * 64},
            "plan": {"path": "docs/plan.md", "hash": "c" * 64},
            "worker": {"branch": "codex/fs-001", "worktree": ".cogito/worktrees/FS-001", "allowed_paths": ["src/**", "tests/**"]},
        }],
        "approved_paths": ["src/**", "tests/**"],
        "checks": [{"id": "C-1", "argv": ["python3", "-m", "unittest"], "required": True}],
        "execution_dag": {
            "tasks": [{"id": "T-1", "slice_id": "FS-001", "paths": ["src"]}],
            "edges": [],
        },
        "human_gate": {"predicates": [], "high_risk_hotspots": []},
        "policy_snapshot": {"max_workers": 3, "fetch_allowed": False},
        "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
        "stop_conditions": ["contract boundary change"],
        "source_registry": [],
    }


class StateAndEventContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()
        self.workflow = self.runtime.load_workflow()

    def test_runtime_facade_loads_from_an_arbitrary_working_directory(self) -> None:
        source = (
            "import importlib.util; "
            f"p={str(RUNTIME_PATH)!r}; "
            "s=importlib.util.spec_from_file_location('cogito_runtime_smoke', p); "
            "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "assert m.RunStore and m.validate_package and m.validate_check_evidence and m.render_workflow_mermaid; "
            "assert m.DEFAULT_WORKFLOW == m.ROOT / 'workflows' / 'cogito-v3.json'"
        )
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-c", source],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_illegal_transition_fails_closed(self) -> None:
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_transition(
                self.workflow, "preparing", "package-approved", {}, {}
            )

    def test_shared_confirmation_is_not_package_approval(self) -> None:
        transition = self.runtime.validate_transition(
            self.workflow,
            "awaiting-shared-confirmation",
            "shared-understanding-confirmed",
            {"confirmed": True},
            {},
        )
        self.assertEqual(transition["to"], "boundary-analysis")
        self.assertNotEqual(transition["to"], "start-gate")
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_transition(
                self.workflow, transition["to"], "start-gate-passed", {}, {}
            )

    def test_finalizing_is_mandatory_before_accepted(self) -> None:
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_transition(
                self.workflow, "post-integration-verification", "finalization-complete", {}, {}
            )
        transition = self.runtime.validate_transition(
            self.workflow,
            "finalizing",
            "finalization-complete",
            {"result_path": "docs/cogito/results/DEV-20260901-001.json", "final_commit": "b" * 40, "project_graph_updated": True},
            {},
        )
        self.assertEqual(transition["to"], "accepted")

    def test_retry_limits_are_enforced_and_projection_preserves_them(self) -> None:
        limits = [
            ("verification_corrections", 3, "verifying", "verification-correction-required"),
            ("review_fix_cycles", 3, "reviewing", "review-fix-required"),
        ]
        for counter, limit, state, event in limits:
            with self.subTest(counter=counter), self.assertRaises(self.runtime.CogitoError):
                self.runtime.validate_transition(
                    self.workflow, state, event, {"scope_within_contract": True}, {counter: limit}
                )
        self.assertEqual(self.workflow["limits"]["transient_retries"], 2)
        self.assertEqual(self.workflow["limits"]["verification_corrections"], 3)
        self.assertEqual(self.workflow["limits"]["review_fix_cycles"], 3)

        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore(directory, "DEV-resume")
            store.create("feature")
            state = store.load()
            state["counters"] = {"verification_corrections": 2}
            self.runtime.atomic_write_json(store.state_path, state)
            # A stale/mutated projection is rebuilt from events; resume cannot reset
            # authoritative counters in the append-only log.
            rebuilt = store.load()
            self.assertEqual(rebuilt["counters"].get("verification_corrections", 0), 0)

    def test_append_only_event_log_has_hash_chain_and_rebuilds_projection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            first = self.runtime.append_event(
                path, {"type": "run-created", "payload": {"kind": "feature"}}
            )
            second = self.runtime.append_event(
                path, {"type": "transitioned", "payload": {"to": "preparing"}}
            )
            lines = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(lines, [first, second])
            self.assertEqual(second["previous_event_hash"], first["event_hash"])
            self.assertEqual(second["sequence"], first["sequence"] + 1)
            self.runtime.read_events(path)
            lines[0]["payload"] = {"kind": "maintenance"}
            path.write_text("\n".join(json.dumps(item) for item in lines) + "\n")
            with self.assertRaises(self.runtime.CogitoError):
                self.runtime.read_events(path)


class DagAndProfileContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()

    def test_ready_tasks_obey_dependencies_and_worker_cap(self) -> None:
        tasks = [
            {"id": "A", "slice_id": "FS-A", "status": "integrated"},
            {"id": "B", "slice_id": "FS-B", "status": "pending"},
            {"id": "C", "slice_id": "FS-C", "status": "pending"},
            {"id": "D", "slice_id": "FS-D", "status": "pending"},
            {"id": "E", "slice_id": "FS-E", "status": "pending"},
        ]
        edges = [
            {"from": "A", "to": "B"},
            {"from": "B", "to": "E"},
        ]
        ready = self.runtime.ready_tasks(tasks, edges, max_workers=3)
        self.assertEqual([task["id"] for task in ready], ["B", "C", "D"])
        self.assertNotIn("E", {task["id"] for task in ready})

    def test_cross_slice_dependency_waits_for_integration_not_implementation(self) -> None:
        tasks = [
            {"id": "A", "slice_id": "FS-A", "status": "complete"},
            {"id": "D", "slice_id": "FS-D", "status": "pending"},
        ]
        edges = [{"from": "A", "to": "D"}]
        self.assertEqual(self.runtime.ready_tasks(tasks, edges), [])
        tasks[0]["status"] = "integrated"
        self.assertEqual([item["id"] for item in self.runtime.ready_tasks(tasks, edges)], ["D"])

    def test_same_slice_exposes_only_one_worker_at_a_time(self) -> None:
        tasks = [
            {"id": "A", "slice_id": "FS-A", "status": "pending"},
            {"id": "B", "slice_id": "FS-A", "status": "pending"},
        ]
        self.assertEqual(len(self.runtime.ready_tasks(tasks, [], max_workers=3)), 1)

    def test_ready_tasks_use_only_unoccupied_worker_slots(self) -> None:
        cases = [
            (1, ("leased",), []),
            (1, ("running",), []),
            (2, ("leased", "running"), []),
            (2, ("leased",), ["P0"]),
            (2, ("running",), ["P0"]),
            (3, ("leased", "running", "leased"), []),
            (3, ("running", "leased"), ["P0"]),
            (3, ("running",), ["P0", "P1"]),
        ]
        for max_workers, active_statuses, expected in cases:
            with self.subTest(max_workers=max_workers, active=active_statuses):
                tasks = [
                    {"id": f"A{i}", "slice_id": f"FS-A{i}", "status": status}
                    for i, status in enumerate(active_statuses)
                ] + [
                    {"id": f"P{i}", "slice_id": f"FS-P{i}", "status": "pending"}
                    for i in range(3)
                ]
                ready = self.runtime.ready_tasks(tasks, [], max_workers)
                self.assertEqual([task["id"] for task in ready], expected)

    def test_active_and_new_slices_each_receive_at_most_one_worker(self) -> None:
        for status in ("leased", "running"):
            with self.subTest(active_status=status):
                tasks = [
                    {"id": "A", "slice_id": "FS-A", "status": status},
                    {"id": "B", "slice_id": "FS-A", "status": "pending"},
                    {"id": "C", "slice_id": "FS-B", "status": "pending"},
                    {"id": "D", "slice_id": "FS-B", "status": "pending"},
                    {"id": "E", "slice_id": "FS-C", "status": "pending"},
                ]
                ready = self.runtime.ready_tasks(tasks, [], max_workers=3)
                self.assertEqual([task["id"] for task in ready], ["C", "E"])

    def test_full_worker_capacity_does_not_skip_dag_validation(self) -> None:
        tasks = [
            {"id": "A", "slice_id": "FS-A", "status": "leased"},
            {"id": "B", "slice_id": "FS-B", "status": "pending"},
        ]
        for name, edges in (
            ("self-reference", [("A", "A")]),
            ("unknown-task", [("A", "missing")]),
            ("cycle", [("A", "B"), ("B", "A")]),
        ):
            with self.subTest(invalid_graph=name), self.assertRaises(self.runtime.CogitoError):
                self.runtime.ready_tasks(tasks, edges, max_workers=1)

    def test_dag_rejects_cycles(self) -> None:
        tasks = [{"id": "A", "status": "pending"}, {"id": "B", "status": "pending"}]
        edges = [{"from": "A", "to": "B"}, {"from": "B", "to": "A"}]
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.ready_tasks(tasks, edges)

    def test_package_rejects_cross_task_slice_cycle(self) -> None:
        package = minimal_package()
        second = json.loads(json.dumps(package["slices"][0]))
        second["id"] = "FS-002"
        second["worker"]["branch"] = "codex/fs-002"
        second["worker"]["worktree"] = ".cogito/worktrees/FS-002"
        package["slices"].append(second)
        package["execution_dag"] = {
            "tasks": [
                {"id": "A1", "slice_id": "FS-001", "paths": ["src"]},
                {"id": "A2", "slice_id": "FS-001", "paths": ["src"]},
                {"id": "B1", "slice_id": "FS-002", "paths": ["src"]},
                {"id": "B2", "slice_id": "FS-002", "paths": ["src"]},
            ],
            "edges": [{"from": "A1", "to": "B1"}, {"from": "B2", "to": "A2"}],
        }
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_package(package)

    def test_mermaid_views_are_derived_from_authoritative_graphs(self) -> None:
        workflow_view = self.runtime.render_workflow_mermaid()
        self.assertIn("verifying --> technical-correction", workflow_view)
        self.assertIn("post-integration-correction --> post-integration-verification", workflow_view)
        project_view = self.runtime.render_project_graph_mermaid({
            "schema_version": "3.0",
            "active_run_id": "DEV-1",
            "slices": {"FS-001": {"disposition": "active"}, "FS-002": {"disposition": "planned"}},
            "dependencies": [{"from": "FS-001", "to": "FS-002"}],
        })
        self.assertIn("FS_001 --> FS_002", project_view)

    def test_maintenance_uses_same_engine_with_skipped_nodes(self) -> None:
        workflow = self.runtime.load_workflow()
        with tempfile.TemporaryDirectory() as directory:
            feature = self.runtime.RunStore(directory, "DEV-feature", workflow)
            maintenance = self.runtime.RunStore(directory, "DEV-maintenance", workflow)
            feature.create("feature")
            maintenance.create("maintenance")
            self.assertEqual(feature.next_action()["next_action"], "draft-shared-understanding")
            self.assertEqual(maintenance.next_action()["next_action"], "assess-mini-package-eligibility")
            self.assertEqual(feature.workflow, maintenance.workflow)


class AmendmentAndAgentContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load_runtime()
        self.package = minimal_package()

    def test_amendment_may_add_checks_and_tasks(self) -> None:
        amendment = {
            "id": "TA-001",
            "reason": "verification exposed a missing deterministic check",
            "added_checks": [{"id": "C-2", "argv": ["python3", "-m", "compileall", "src"], "required": True}],
            "added_tasks": [{"id": "T-2", "slice_id": "FS-001", "paths": ["tests"]}],
        }
        self.assertIsNone(self.runtime.validate_amendment(self.package, [], amendment))
        first_hash = self.runtime.effective_contract_hash(self.package, [])
        amended_hash = self.runtime.effective_contract_hash(self.package, [amendment])
        self.assertNotEqual(first_hash, amended_hash)

    def test_amendment_check_environment_stays_within_frozen_policy(self) -> None:
        self.package["policy_snapshot"]["allowed_environment"] = ["PATH"]
        approved = {
            "id": "TA-001", "reason": "check needs the approved executable path",
            "added_checks": [{"id": "C-2", "argv": ["python3", "-V"], "env_allowlist": ["PATH"]}],
        }
        self.assertIsNone(self.runtime.validate_amendment(self.package, [], approved))

        unapproved = {
            "id": "TA-002", "reason": "later check requests a new host secret",
            "added_checks": [{"id": "C-3", "argv": ["python3", "-V"], "env_allowlist": ["API_TOKEN"]}],
        }
        with self.assertRaisesRegex(
            self.runtime.CogitoError, "environment exceeds its frozen policy snapshot"
        ):
            self.runtime.validate_amendment(self.package, [approved], unapproved)

    def test_rejected_amendment_does_not_append_an_event(self) -> None:
        self.package["policy_snapshot"]["allowed_environment"] = ["PATH"]
        amendment = {
            "id": "TA-001", "reason": "requests an unapproved host secret",
            "added_checks": [{"id": "C-2", "argv": ["python3", "-V"], "env_allowlist": ["API_TOKEN"]}],
        }
        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore(directory, self.package["run_id"])
            store.approved_package = lambda: self.package
            store.load = lambda: {"state": "verifying"}
            self.assertFalse(store.events_path.exists())
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "environment exceeds its frozen policy snapshot"
            ):
                store.add_amendment(amendment)
            self.assertFalse(store.events_path.exists())

    def test_amendment_cannot_relax_or_widen_contract(self) -> None:
        forbidden = [
            {"id": "TA-001", "reason": "x", "remove_checks": ["C-1"]},
            {"id": "TA-001", "reason": "x", "downgrade_checks": ["C-1"]},
            {"id": "TA-001", "reason": "x", "approved_paths": ["**"]},
            {"id": "TA-001", "reason": "x", "acceptance": []},
            {"id": "TA-001", "reason": "x", "dependencies": [{"from": "T-1", "to": "T-9"}]},
        ]
        for amendment in forbidden:
            with self.subTest(amendment=amendment):
                with self.assertRaises(self.runtime.CogitoError):
                    self.runtime.validate_amendment(self.package, [], amendment)

    def test_agent_result_repair_is_limited_to_two_format_attempts(self) -> None:
        valid = {
            "schema_version": "3.0",
            "run_id": "DEV-20260901-001",
            "task_id": "T-1",
            "agent_id": "worker-1",
            "role": "implementer",
            "status": "complete",
            "base_commit": "a" * 40,
            "head_commit": "c" * 40,
            "changed_paths": ["src/greeting.py"],
            "evidence": [],
            "risks": [],
            "requested_transition": "verifying",
            "repair_attempt": 2,
        }
        self.assertIsNone(self.runtime.validate_agent_result(valid, self.package))
        invalid = dict(valid, repair_attempt=3)
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_agent_result(invalid, self.package)


if __name__ == "__main__":
    unittest.main()
