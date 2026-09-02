"""Materialization validates each amendment prefix once without changing JSON contracts."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cogito_contracts as contracts
from cogito_common import CogitoError, hash_json
from cogito_scheduler import edge_pair
from cogito_test_support import minimal_package


class ContractMaterializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = minimal_package()
        self.package["extension"] = {"nested": [{"tag": "original"}], "values": [None, True, 1, ""]}
        del self.package["checks"][0]["required"]
        self.amendments = [
            {
                "id": f"TA-{i}", "reason": f"verification finding {i}",
                "added_checks": [{"id": f"C-{i + 1}", "argv": ["python3", "-V"]}],
                "added_tasks": [{
                    "id": f"T-{i + 1}", "slice_id": "FS-001", "paths": ["src"],
                    "depends_on": [f"T-{i}"], "extension": {"notes": [f"task {i}"]},
                }],
            }
            for i in range(1, 4)
        ]

    def test_one_materialization_validates_the_base_and_each_amendment_once(self) -> None:
        with mock.patch.object(contracts, "validate_package", wraps=contracts.validate_package) as package_validation, \
             mock.patch.object(contracts, "load_workflow", wraps=contracts.load_workflow) as workflow_load, \
             mock.patch.object(contracts, "_validate_amendment_shape", wraps=contracts._validate_amendment_shape) as shape_validation:
            contracts.materialize_contract(self.package, self.amendments)
        package_validation.assert_called_once_with(self.package)
        workflow_load.assert_called_once_with()
        self.assertEqual(shape_validation.call_args_list, [mock.call(item) for item in self.amendments])

    def test_public_amendment_validation_checks_the_entire_history_and_returns_none(self) -> None:
        self.assertIsNone(contracts.validate_amendment(self.package, tuple(self.amendments[:-1]), self.amendments[-1]))
        self.amendments[0]["added_checks"][0]["id"] = "C-1"
        with self.assertRaisesRegex(CogitoError, "added checks require new ids"):
            contracts.validate_amendment(self.package, self.amendments[:-1], self.amendments[-1])

    def test_hash_extensions_omitted_defaults_and_deep_copy_stay_compatible(self) -> None:
        before = copy.deepcopy((self.package, self.amendments))
        base_hash = contracts.package_hash(self.package)
        expected_hash = hash_json({"base_package_hash": base_hash, "amendments": self.amendments})
        effective = contracts.materialize_contract(self.package, self.amendments)
        self.assertEqual(effective["effective_contract_hash"], expected_hash)
        self.assertEqual(contracts.effective_contract_hash(self.package, self.amendments), expected_hash)
        self.assertEqual(contracts.materialize_contract(self.package, [])["effective_contract_hash"], base_hash)
        self.assertEqual(effective["extension"], self.package["extension"])
        self.assertEqual(effective["checks"], self.package["checks"] + [item["added_checks"][0] for item in self.amendments])
        for check in effective["checks"]:
            self.assertNotIn("required", check)
            self.assertNotIn("timeout_seconds", check)
        self.assertEqual((self.package, self.amendments), before)

        effective["extension"]["nested"][0]["tag"] = "edited result"
        effective["checks"][1]["argv"].append("edited result")
        effective["execution_dag"]["tasks"][1]["extension"]["notes"].append("edited result")
        self.assertEqual((self.package, self.amendments), before)
        self.assertEqual(contracts.package_hash(self.package), base_hash)

    def test_an_earlier_amendment_cannot_depend_on_a_later_amendment_task(self) -> None:
        self.amendments[0]["added_tasks"][0]["depends_on"] = ["T-4"]
        self.amendments[2]["added_tasks"][0]["depends_on"] = []
        # The combined graph is acyclic, but T-4 did not exist at the first prefix.
        for operation in (contracts.materialize_contract, contracts.effective_contract_hash):
            with self.subTest(operation=operation.__name__), self.assertRaises(CogitoError):
                operation(self.package, self.amendments)

    def test_invalid_earlier_amendments_are_not_hidden_by_a_valid_final_amendment(self) -> None:
        cases = (
            ("duplicate-check", (0, "added_checks", 0, "id"), "C-1"),
            ("duplicate-task", (0, "added_tasks", 0, "id"), "T-1"),
            ("duplicate-amendment", (1, "id"), "TA-1"),
            ("path-scope", (0, "added_tasks", 0, "paths"), ["outside/contract"]),
            ("environment-scope", (0, "added_checks", 0, "env_allowlist"), ["UNAPPROVED_SECRET"]),
        )
        for name, path, value in cases:
            changes = copy.deepcopy(self.amendments)
            target = changes
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            if name == "duplicate-task":
                # Keep every reference valid so only the duplicate ID is invalid.
                changes[1]["added_tasks"][0]["depends_on"] = ["T-1"]
            before = copy.deepcopy(changes)
            for operation in (contracts.materialize_contract, contracts.effective_contract_hash):
                with self.subTest(invalid_prefix=name, operation=operation.__name__), self.assertRaises(CogitoError):
                    operation(self.package, changes)
            self.assertEqual(changes, before)

    def test_forward_references_inside_one_amendment_remain_valid(self) -> None:
        self.amendments[1]["added_tasks"] = [
            {"id": "T-3", "slice_id": "FS-001", "paths": ["src"], "depends_on": ["T-helper"]},
            {"id": "T-helper", "slice_id": "FS-001", "paths": ["src"], "depends_on": ["T-2"]},
        ]
        effective = contracts.materialize_contract(self.package, self.amendments)
        self.assertEqual(
            set(map(edge_pair, effective["execution_dag"]["edges"])),
            {("T-1", "T-2"), ("T-2", "T-helper"), ("T-helper", "T-3"), ("T-3", "T-4")},
        )


if __name__ == "__main__":
    unittest.main()
