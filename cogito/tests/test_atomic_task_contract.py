"""Atomic delivery is explicit, bounded, and valid at every amendment prefix."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, atomic_write_json, hash_json
from cogito_contracts import materialize_contract, package_hash, validate_package
from cogito_gate_validation import validate_policy
from cogito_test_support import minimal_package, package as package_for_kind


def atomic_package() -> dict:
    package = minimal_package()
    package["task_delivery"] = "atomic"
    package["execution_dag"]["tasks"][0].update(
        responsibility="Validate one behavior", check_ids=["C-1"],
    )
    return package


class AtomicTaskContractTests(unittest.TestCase):
    def test_legacy_contract_and_hash_are_preserved(self) -> None:
        package = minimal_package()
        before = copy.deepcopy(package)
        effective = materialize_contract(package, [])
        self.assertEqual(effective["effective_contract_hash"], package_hash(before))
        self.assertEqual(package, before)
        self.assertNotIn("task_delivery", effective)
        self.assertNotIn("phase", effective["checks"][0])

    def test_integration_check_can_also_be_a_task_target_without_mutation(self) -> None:
        package = atomic_package()
        before = copy.deepcopy(package)
        validate_package(package)
        self.assertEqual(package, before)

    def test_atomic_tasks_require_responsibility_paths_and_distinct_required_checks(self) -> None:
        for field, value in (
            ("responsibility", ""), ("responsibility", None), ("paths", []),
            ("check_ids", []), ("check_ids", ["C-1", "C-1"]),
            ("check_ids", ["C-unknown"]), ("check_ids", "C-1"),
        ):
            with self.subTest(field=field, value=value):
                package = atomic_package()
                package["execution_dag"]["tasks"][0][field] = value
                with self.assertRaises(CogitoError):
                    validate_package(package)
        package = atomic_package()
        package["checks"].append({"id": "C-optional", "argv": ["true"], "required": False})
        package["execution_dag"]["tasks"][0]["check_ids"] = ["C-optional"]
        with self.assertRaisesRegex(CogitoError, "reference required checks"):
            validate_package(package)

    def test_task_phase_requires_atomic_and_a_final_integration_check(self) -> None:
        package = atomic_package()
        package["checks"][0]["phase"] = "task"
        with self.assertRaisesRegex(CogitoError, "required integration check"):
            validate_package(package)
        package["checks"].append({"id": "C-final", "argv": ["true"], "phase": "integration"})
        validate_package(package)
        del package["task_delivery"]
        with self.assertRaisesRegex(CogitoError, "requires atomic"):
            validate_package(package)

    def test_unknown_mode_and_phase_are_rejected(self) -> None:
        package = atomic_package()
        package["task_delivery"] = "batch"
        with self.assertRaises(CogitoError):
            validate_package(package)
        for phase in ("ci", "", None, [], {}, True):
            with self.subTest(phase=phase):
                package = atomic_package()
                package["checks"][0]["phase"] = phase
                with self.assertRaises(CogitoError):
                    validate_package(package)

    def test_atomic_delivery_is_development_only(self) -> None:
        for kind in ("feature", "change", "correction", "maintenance", "documentation"):
            with self.subTest(kind=kind):
                package = package_for_kind(kind)
                package["task_delivery"] = "atomic"
                package["execution_dag"]["tasks"][0].update(
                    responsibility="Deliver one behavior", check_ids=["C-1"],
                )
                if kind in {"maintenance", "documentation"}:
                    with self.assertRaisesRegex(CogitoError, "requires feature, change, or correction"):
                        validate_package(package)
                else:
                    validate_package(package)
    def test_added_task_can_reference_check_added_in_same_amendment(self) -> None:
        package = atomic_package()
        amendment = self.amendment()
        effective = materialize_contract(package, [amendment])
        self.assertEqual(effective["execution_dag"]["tasks"][-1]["check_ids"], ["C-2"])
        amendment["added_tasks"][0]["check_ids"] = ["C-1", "C-2"]
        materialize_contract(package, [amendment])

    def test_later_amendment_cannot_repair_missing_check_reference(self) -> None:
        first = self.amendment()
        checks = first.pop("added_checks")
        second = {"id": "TA-2", "reason": "Late check", "added_checks": checks}
        with self.assertRaisesRegex(CogitoError, "reference required checks"):
            materialize_contract(atomic_package(), [first, second])

    def test_amendments_enforce_atomic_fields_and_legacy_phase_boundary(self) -> None:
        amendment = self.amendment()
        del amendment["added_tasks"][0]["responsibility"]
        with self.assertRaisesRegex(CogitoError, "responsibility"):
            materialize_contract(atomic_package(), [amendment])
        with self.assertRaisesRegex(CogitoError, "requires atomic"):
            materialize_contract(minimal_package(), [self.amendment()])

    def test_required_task_check_cannot_be_orphaned(self) -> None:
        package = atomic_package()
        package["checks"].append({"id": "C-orphan", "argv": ["true"], "phase": "task"})
        with self.assertRaisesRegex(CogitoError, "referenced by a task.*C-orphan"):
            validate_package(package)
        package["checks"][-1]["required"] = False
        validate_package(package)

    def test_later_task_cannot_repair_orphaned_check_amendment(self) -> None:
        first = self.amendment()
        tasks = first.pop("added_tasks")
        second = {"id": "TA-2", "reason": "Late task", "added_tasks": tasks}
        with self.assertRaisesRegex(CogitoError, "referenced by a task.*C-2"):
            materialize_contract(atomic_package(), [first, second])

    def test_policy_required_checks_cannot_move_to_task_phase(self) -> None:
        policy = {"schema_version": "3.0", "required_checks": ["C-1"]}
        package = atomic_package()
        package["checks"][0]["phase"] = "task"
        package["checks"].append({"id": "C-final", "argv": ["true"]})
        package["policy_snapshot"]["hash"] = hash_json(policy)
        validate_package(package)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            atomic_write_json(root / "docs/cogito/project-policy.json", policy)
            with self.assertRaisesRegex(CogitoError, "Project Policy.*integration-scoped"):
                validate_policy(root, package)
        package["policy_snapshot"]["required_checks"] = ["C-1"]
        with self.assertRaisesRegex(CogitoError, "policy snapshot.*integration-scoped"):
            validate_package(package)
        package["checks"][0]["phase"] = "integration"
        validate_package(package)

    @staticmethod
    def amendment() -> dict:
        return {
            "id": "TA-1", "reason": "Related correction",
            "added_checks": [{"id": "C-2", "argv": ["true"], "phase": "task"}],
            "added_tasks": [{"id": "T-2", "slice_id": "FS-001", "paths": ["src"],
                             "depends_on": ["T-1"], "responsibility": "Fix behavior",
                             "check_ids": ["C-2"]}],
        }


if __name__ == "__main__":
    unittest.main()
