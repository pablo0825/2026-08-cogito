"""Explicit workflow data keeps contract and projection rules independent of files."""

import copy
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest import mock

from cogito_test_support import minimal_package, package as package_fixture
import cogito_contracts as contracts
import cogito_projection as projection
from cogito_common import CogitoError, hash_json
from cogito_run_store import RunStore
from cogito_workflow import load_workflow


@contextmanager
def without_workflow_io():
    with ExitStack() as stack:
        for target in (
            "cogito_contracts.load_workflow", "cogito_projection.load_workflow",
            "cogito_workflow.load_workflow", "builtins.open", "pathlib.Path.open",
            "pathlib.Path.read_text", "pathlib.Path.resolve", "subprocess.run",
        ):
            stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected workflow IO")))
        yield


class ExplicitWorkflowContractTests(unittest.TestCase):
    def setUp(self):
        self.package = minimal_package()
        self.limits = {
            "max_workers": 3, "transient_retries": 5,
            "verification_corrections": 6, "review_fix_cycles": 7, "format_repairs": 8,
        }
        # Exceed the bundled transient limit so a hidden default cannot pass.
        self.package["limits"]["transient_retries"] = 4
        self.amendments = [{
            "id": "TA-1", "reason": "additional verification",
            "added_checks": [{"id": "C-2", "argv": ["python3", "-V"]}],
        }]

    def result(self):
        return {
            "schema_version": "3.0", "run_id": self.package["run_id"],
            "task_id": "T-1", "agent_id": "worker", "role": "implementer",
            "status": "complete", "base_commit": "a" * 40, "head_commit": "b" * 40,
            "changed_paths": ["src/main.py"], "evidence": [], "risks": [],
            "requested_transition": "verifying",
        }

    def test_explicit_limits_validate_and_materialize_without_loading_a_workflow(self):
        before = copy.deepcopy((self.package, self.amendments, self.limits))
        with without_workflow_io():
            self.assertIsNone(contracts.validate_package_with_limits(self.package, self.limits))
            effective = contracts.materialize_contract_with_limits(self.package, self.amendments, self.limits)
            base = contracts.materialize_contract_with_limits(self.package, [], self.limits)
            expected_hash = hash_json({
                "base_package_hash": contracts.package_hash(self.package),
                "amendments": self.amendments,
            })
        self.assertEqual(effective["effective_contract_hash"], expected_hash)
        self.assertEqual(base["effective_contract_hash"], contracts.package_hash(self.package))
        self.assertEqual(effective["checks"], self.package["checks"] + self.amendments[0]["added_checks"])
        self.assertEqual((self.package, self.amendments, self.limits), before)

    def test_each_stricter_limit_rejects_the_package_and_materialization_without_io(self):
        for name, requested in self.package["limits"].items():
            with self.subTest(limit=name):
                limits = {**self.limits, name: requested - 1}
                before = copy.deepcopy((self.package, self.amendments, limits))
                with without_workflow_io():
                    with self.assertRaisesRegex(CogitoError, f"limits.{name}"):
                        contracts.validate_package_with_limits(self.package, limits)
                    with self.assertRaisesRegex(CogitoError, f"limits.{name}"):
                        contracts.materialize_contract_with_limits(self.package, self.amendments, limits)
                self.assertEqual((self.package, self.amendments, limits), before)

    def test_agent_result_uses_explicit_limits_for_its_package_validation(self):
        result = self.result()
        before = copy.deepcopy((result, self.package, self.limits))
        with without_workflow_io():
            self.assertIsNone(contracts.validate_agent_result(result, self.package, workflow_limits=self.limits))
            with self.assertRaisesRegex(CogitoError, "limits.transient_retries"):
                contracts.validate_agent_result(result, self.package, workflow_limits={**self.limits, "transient_retries": 1})
        self.assertEqual((result, self.package, self.limits), before)

    def test_compatibility_wrappers_match_explicit_results_and_load_only_once(self):
        expected = contracts.materialize_contract_with_limits(self.package, self.amendments, self.limits)
        workflow = {"limits": self.limits}
        operations = (
            (lambda: contracts.validate_package(self.package), None),
            (lambda: contracts.materialize_contract(self.package, self.amendments), expected),
            (lambda: contracts.effective_contract_hash(self.package, self.amendments), expected["effective_contract_hash"]),
            (lambda: contracts.validate_agent_result(self.result(), self.package), None),
        )
        for operation, expected_value in operations:
            with self.subTest(operation=operation):
                with mock.patch.object(contracts, "load_workflow", return_value=workflow) as load:
                    self.assertEqual(operation(), expected_value)
                load.assert_called_once_with()

    def test_run_store_preserves_its_custom_workflow_during_package_operations(self):
        workflow = load_workflow()
        workflow["limits"]["transient_retries"] = 5
        package = package_fixture("maintenance")
        package["limits"]["transient_retries"] = 4
        before = copy.deepcopy((package, workflow))
        with tempfile.TemporaryDirectory() as directory:
            with ExitStack() as stack:
                for target in (
                    "cogito_contracts.load_workflow", "cogito_projection.load_workflow",
                    "cogito_run_store.load_workflow", "cogito_workflow.load_workflow",
                ):
                    stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected default workflow")))
                store = RunStore(Path(directory), package["run_id"], workflow)
                self.assertEqual(store.create("maintenance")["limits"]["transient_retries"], 5)
                self.assertEqual(store.prepare_package(package)["state"], "awaiting-package-approval")
                self.assertEqual(store.approve_package(package)["state"], "start-gate")
                self.assertEqual(store.load()["limits"]["transient_retries"], 4)
                self.assertEqual(store.approved_package()["limits"]["transient_retries"], 4)
        self.assertEqual((package, workflow), before)


class ExplicitWorkflowProjectionTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {
            "initial_state": "custom-preparing", "terminal_states": ["custom-finished"],
            "limits": {
                "max_workers": 1, "transient_retries": 1,
                "verification_corrections": 2, "review_fix_cycles": 2, "format_repairs": 1,
            },
            "transitions": [{
                "from": "custom-preparing", "event": "mini-package-ready",
                "to": "custom-ready", "guard": "mini_package_valid",
            }],
        }
        self.events = [
            {"type": "run-created", "sequence": 1, "event_hash": "a" * 64,
             "payload": {"run_id": "DEV-custom", "kind": "maintenance"}},
            {"type": "mini-package-ready", "sequence": 2, "event_hash": "b" * 64,
             "payload": {"package_valid": True, "candidate_package_hash": "c" * 64}},
            {"type": "transient-retry", "sequence": 3, "event_hash": "d" * 64,
             "payload": {"reason": "temporary issue"}},
        ]

    def test_projection_uses_custom_states_and_limits_without_loading_or_mutating_inputs(self):
        before = copy.deepcopy((self.events, self.workflow))
        with without_workflow_io():
            initial = projection.project_events(self.events[:1], self.workflow)
            state = projection.project_events(iter(self.events), self.workflow)
        self.assertEqual(initial["state"], "custom-preparing")
        self.assertEqual(state["state"], "custom-ready")
        self.assertEqual(state["max_workers"], 1)
        self.assertEqual(state["limits"], self.workflow["limits"])
        self.assertEqual(state["counters"], {"transient_retries": 1})
        self.assertEqual(state["sequence"], 3)
        self.assertEqual(state["last_event_hash"], "d" * 64)
        self.assertEqual((self.events, self.workflow), before)

    def test_custom_retry_limit_rejects_an_additional_attempt(self):
        events = [*self.events, {"type": "transient-retry", "payload": {"reason": "retry again"}}]
        before = copy.deepcopy((events, self.workflow))
        with without_workflow_io(), self.assertRaisesRegex(CogitoError, "retry limit exhausted"):
            projection.project_events(events, self.workflow)
        self.assertEqual((events, self.workflow), before)

    def test_projection_wrapper_uses_explicit_workflow_or_loads_once_when_omitted(self):
        expected = projection.project_events(self.events, self.workflow)
        with without_workflow_io():
            self.assertEqual(projection.reduce_events(self.events, self.workflow), expected)
        with mock.patch.object(projection, "load_workflow", return_value=self.workflow) as load:
            self.assertEqual(projection.reduce_events(self.events), expected)
        load.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
