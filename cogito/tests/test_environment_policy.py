"""Environment permissions must narrow from Project Policy to Package to check."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, atomic_write_json, hash_json
from cogito_contracts import package_hash, validate_amendment, validate_package
from cogito_gate_validation import validate_policy
from cogito_run_store import RunStore
from cogito_test_support import minimal_package


class EnvironmentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="cogito-environment-policy-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.policy_path = self.root / "docs/cogito/project-policy.json"
        self.package = minimal_package()

    def set_project_environment(self, names: list[str] | None) -> None:
        policy = {"schema_version": "3.0"}
        if names is not None:
            policy["allowed_environment"] = names
        atomic_write_json(self.policy_path, policy)
        self.package["policy_snapshot"]["hash"] = hash_json(policy)

    def amendment(self, name: str) -> dict:
        return {"id": "TA-1", "reason": "additional check", "added_checks": [{
            "id": "C-2", "argv": ["python3", "-V"], "env_allowlist": [name],
        }]}

    def test_unused_snapshot_permission_cannot_exceed_project_policy(self) -> None:
        self.set_project_environment(["COGITO_ALLOWED"])
        self.package["policy_snapshot"]["allowed_environment"] = ["COGITO_ALLOWED", "COGITO_FORBIDDEN"]
        self.package["checks"][0]["env_allowlist"] = ["COGITO_ALLOWED"]
        validate_package(self.package)
        # The old Amendment protection trusts the snapshot; the Gate must reject it first.
        validate_amendment(self.package, [], self.amendment("COGITO_FORBIDDEN"))
        with self.assertRaisesRegex(CogitoError, "snapshot environment exceeds Project Policy"):
            validate_policy(self.root, self.package)

    def test_empty_or_omitted_project_allowlist_grants_no_extra_permissions(self) -> None:
        for names in ([], None):
            with self.subTest(names=names):
                self.set_project_environment(names)
                self.package["policy_snapshot"]["allowed_environment"] = ["COGITO_FORBIDDEN"]
                with self.assertRaisesRegex(CogitoError, "snapshot environment exceeds Project Policy"):
                    validate_policy(self.root, self.package)

    def test_no_project_file_grants_no_extra_permissions(self) -> None:
        self.package["policy_snapshot"]["allowed_environment"] = ["COGITO_FORBIDDEN"]
        validate_package(self.package)
        with self.assertRaisesRegex(CogitoError, "snapshot environment exceeds Project Policy"):
            validate_policy(self.root, self.package)

    def test_default_empty_permissions_remain_valid_without_project_file(self) -> None:
        for explicit in (False, True):
            with self.subTest(explicit=explicit):
                if explicit:
                    self.package["policy_snapshot"]["allowed_environment"] = []
                validate_package(self.package)
                validate_policy(self.root, self.package)

    def test_equal_or_narrower_snapshot_preserves_original_data_and_hash(self) -> None:
        self.set_project_environment(["COGITO_A", "COGITO_B"])
        for allowed in ([], ["COGITO_A"], ["COGITO_B", "COGITO_A"]):
            with self.subTest(allowed=allowed):
                self.package["policy_snapshot"]["allowed_environment"] = allowed
                self.package["checks"][0]["env_allowlist"] = allowed[:1]
                before, digest = copy.deepcopy(self.package), package_hash(self.package)
                validate_package(self.package)
                validate_policy(self.root, self.package)
                self.assertEqual(self.package, before)
                self.assertEqual(package_hash(self.package), digest)

    def test_amendment_still_cannot_exceed_narrower_approved_snapshot(self) -> None:
        self.set_project_environment(["COGITO_A", "COGITO_B"])
        self.package["policy_snapshot"]["allowed_environment"] = ["COGITO_A"]
        validate_package(self.package)
        validate_policy(self.root, self.package)
        validate_amendment(self.package, [], self.amendment("COGITO_A"))
        with self.assertRaisesRegex(CogitoError, "environment exceeds its frozen policy snapshot"):
            validate_amendment(self.package, [], self.amendment("COGITO_B"))

    def test_direct_project_check_validation_is_not_removed(self) -> None:
        for project_exists in (False, True):
            with self.subTest(project_exists=project_exists):
                if project_exists:
                    self.set_project_environment([])
                self.package["checks"][0]["env_allowlist"] = ["COGITO_FORBIDDEN"]
                with self.assertRaisesRegex(CogitoError, "check environment exceeds Project Policy"):
                    validate_policy(self.root, self.package)

    def test_gate_rejects_bad_permissions_before_preparation_or_publication(self) -> None:
        self.set_project_environment([])
        self.package["policy_snapshot"]["allowed_environment"] = ["COGITO_FORBIDDEN"]
        store = RunStore(self.root, self.package["run_id"])
        store.create("feature")
        store.transition("shared-understanding-ready", {
            "shared_understanding_hash": self.package["shared_understanding"]["hash"],
        })
        store.transition("shared-understanding-confirmed", {"confirmed": True})
        store.transition("boundary-complete", self.package["boundary"])
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "snapshot environment exceeds Project Policy"):
            store.prepare_package(self.package, "candidate")
        self.assertEqual(store.events_path.read_bytes(), before)
        # Simulate a candidate admitted by the old Project Policy validation.
        with mock.patch.object(store, "_validate_policy"):
            store.prepare_package(self.package, "legacy-candidate")
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "snapshot environment exceeds Project Policy"):
            store.approve_package(self.package, "approve")
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertFalse((self.root / "docs/cogito/packages").exists())
        self.assertFalse((self.root / "docs/cogito/project-graph.json").exists())


if __name__ == "__main__":
    unittest.main()
