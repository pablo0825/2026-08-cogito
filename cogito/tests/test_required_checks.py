"""Project and frozen policy requirements cannot be downgraded to optional."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, atomic_write_json, hash_json
from cogito_contracts import package_hash, validate_amendment, validate_package
from cogito_gate_validation import validate_evidence, validate_policy
from cogito_run_store import RunStore
from test_runtime_contract import minimal_package


class RequiredChecksTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cogito-required-checks-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.policy = {"schema_version": "3.0", "required_checks": ["C-1"]}
        self.policy_path = self.root / "docs/cogito/project-policy.json"
        atomic_write_json(self.policy_path, self.policy)
        self.package = minimal_package()
        self.package["policy_snapshot"]["hash"] = hash_json(self.policy)
        # A different mandatory check must not compensate for downgrading C-1.
        self.package["checks"].append({"id": "C-2", "argv": ["python3", "-V"]})

    def test_project_required_check_cannot_be_optional(self) -> None:
        self.package["checks"][0]["required"] = False
        validate_package(self.package)  # Project requirements need not be copied into the snapshot.
        with self.assertRaisesRegex(CogitoError, "Project Policy.*optional.*C-1"):
            validate_policy(self.root, self.package)

    def test_frozen_required_check_cannot_be_optional_without_project_file(self) -> None:
        self.policy_path.unlink()
        self.package["policy_snapshot"]["required_checks"] = ["C-1"]
        self.package["checks"][0]["required"] = False
        with self.assertRaisesRegex(CogitoError, "policy snapshot.*optional.*C-1"):
            validate_package(self.package)

    def test_missing_required_check_is_rejected_by_both_policies(self) -> None:
        self.package["checks"] = self.package["checks"][1:]
        with self.assertRaisesRegex(CogitoError, "omits checks.*Project Policy"):
            validate_policy(self.root, self.package)
        self.package["policy_snapshot"]["required_checks"] = ["C-1"]
        with self.assertRaisesRegex(CogitoError, "omits checks.*policy snapshot"):
            validate_package(self.package)

    def test_explicit_and_default_required_preserve_data_and_hash(self) -> None:
        self.package["policy_snapshot"]["required_checks"] = ["C-1"]
        self.package["checks"][1]["required"] = False  # Unrequired checks may remain optional.
        for explicit in (True, False):
            with self.subTest(explicit=explicit):
                package = copy.deepcopy(self.package)
                if not explicit:
                    del package["checks"][0]["required"]
                before, digest = copy.deepcopy(package), package_hash(package)
                validate_package(package)
                validate_policy(self.root, package)
                self.assertEqual(package, before)
                self.assertEqual(package_hash(package), digest)

    def test_unrequired_checks_can_still_be_optional(self) -> None:
        self.policy["required_checks"] = []
        atomic_write_json(self.policy_path, self.policy)
        self.package["policy_snapshot"]["hash"] = hash_json(self.policy)
        self.package["checks"][0]["required"] = False
        validate_package(self.package)
        validate_policy(self.root, self.package)

    def test_invalid_frozen_requirement_is_rejected_before_evidence_or_amendments(self) -> None:
        self.package["policy_snapshot"]["required_checks"] = ["C-1"]
        self.package["checks"][0]["required"] = False
        with self.assertRaisesRegex(CogitoError, "policy snapshot.*optional.*C-1"):
            validate_evidence(self.package, [], [], lambda: {}, self.root / "run")
        with self.assertRaisesRegex(CogitoError, "policy snapshot.*optional.*C-1"):
            validate_amendment(self.package, [], {
                "id": "TA-1", "reason": "extra check",
                "added_checks": [{"id": "C-3", "argv": ["python3", "-V"]}],
            })

    def preparing_store(self) -> RunStore:
        store = RunStore(self.root, self.package["run_id"])
        store.create("feature")
        store.transition("shared-understanding-ready", {
            "shared_understanding_hash": self.package["shared_understanding"]["hash"],
        })
        store.transition("shared-understanding-confirmed", {"confirmed": True})
        store.transition("boundary-complete", self.package["boundary"])
        return store

    def assert_no_publication(self, store: RunStore, events_before: bytes) -> None:
        self.assertEqual(store.events_path.read_bytes(), events_before)
        self.assertFalse((self.root / "docs/cogito/packages").exists())
        self.assertFalse((self.root / "docs/cogito/project-graph.json").exists())

    def test_preparation_rejects_downgrade_without_appending_events(self) -> None:
        store = self.preparing_store()
        self.package["checks"][0]["required"] = False
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "Project Policy.*optional.*C-1"):
            store.prepare_package(self.package, "candidate")
        self.assert_no_publication(store, before)

    def test_approval_rechecks_project_requirement_before_publication(self) -> None:
        store = self.preparing_store()
        self.package["checks"][0]["required"] = False
        self.policy_path.unlink()
        store.prepare_package(self.package, "candidate")
        # A candidate prepared before Project Policy existed cannot bypass its requirements.
        atomic_write_json(self.policy_path, self.policy)
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "Project Policy.*optional.*C-1"):
            store.approve_package(self.package, "approve")
        self.assert_no_publication(store, before)


if __name__ == "__main__":
    unittest.main()
