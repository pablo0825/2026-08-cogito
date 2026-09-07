"""Scope additions preserve frozen inputs and reject ownership broadening."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_contracts import materialize_contract, package_hash, validate_agent_result
from test_atomic_task_contract import atomic_package


def path_package():
    package = atomic_package()
    package["approved_paths"] = ["src/original.py"]
    package["slices"][0]["worker"]["allowed_paths"] = ["src/original.py"]
    package["execution_dag"]["tasks"][0]["paths"] = ["src/original.py"]
    return package


def path_amendment():
    return {"id": "AM-1", "reason": "Omitted mapper dependency", "path_additions": [
        {"task_id": "T-1", "paths": ["src/mapper.py", "tests/test_mapper.py"],
         "reason": "Implement the approved response", "check_ids": ["C-1"]}]}


class PathAmendmentContractTests(unittest.TestCase):
    def test_materializes_three_scopes_without_mutating_inputs(self):
        package, amendment = path_package(), path_amendment()
        original = copy.deepcopy((package, amendment))
        effective = materialize_contract(package, [amendment])
        expected = ["src/original.py", "src/mapper.py", "tests/test_mapper.py"]
        self.assertEqual(effective["approved_paths"], expected)
        self.assertEqual(effective["slices"][0]["worker"]["allowed_paths"], expected)
        self.assertEqual(effective["execution_dag"]["tasks"][0]["paths"], expected)
        self.assertEqual((package, amendment), original)
        self.assertNotEqual(effective["effective_contract_hash"], package_hash(package))
        amended = copy.deepcopy(amendment)
        amended["path_additions"][0]["reason"] = "Different explanation"
        self.assertNotEqual(materialize_contract(package, [amended])["effective_contract_hash"], effective["effective_contract_hash"])

    def test_adds_existing_required_check_without_duplicates(self):
        package, amendment = path_package(), path_amendment()
        package["checks"].append({"id": "C-2", "argv": ["true"]})
        amendment["path_additions"][0]["check_ids"] = ["C-2", "C-1"]
        effective = materialize_contract(package, [amendment])
        self.assertEqual(effective["execution_dag"]["tasks"][0]["check_ids"], ["C-1", "C-2"])

    def test_adds_new_targeted_check_in_same_amendment(self):
        package, amendment = path_package(), path_amendment()
        amendment["added_checks"] = [{"id": "C-mapper", "argv": ["python3", "tests/test_mapper.py"],
                                       "required": True, "phase": "task"}]
        amendment["path_additions"][0]["check_ids"] = ["C-mapper"]
        before = copy.deepcopy(amendment)
        effective = materialize_contract(package, [amendment])
        self.assertEqual(effective["execution_dag"]["tasks"][0]["check_ids"], ["C-1", "C-mapper"])
        self.assertEqual(effective["checks"][-1], amendment["added_checks"][0])
        self.assertEqual(amendment, before)
        for change in ({"id": "C-1"}, {"required": False}, {"env_allowlist": ["SECRET"]}):
            with self.subTest(change=change):
                malformed = copy.deepcopy(amendment)
                malformed["added_checks"][0].update(change)
                with self.assertRaises(CogitoError):
                    materialize_contract(package, [malformed])
        amendment["commit_id"] = "a" * 40
        with self.assertRaisesRegex(CogitoError, "cannot mix"):
            materialize_contract(package, [amendment])

    def test_rejects_nonexact_and_protected_paths(self):
        for path in ["src/", "src/**", "src/a?.py", "src/[a].py", "./src/a", "src//a", "../a", "/a", ".", ".git/config", "src/.git/config", ".cogito/runs/a", "docs/cogito/results/a.json", "docs/spec.md", "docs/plan.md", "src\\a", "src/original.py"]:
            with self.subTest(path=path):
                amendment = path_amendment()
                amendment["path_additions"][0]["paths"] = [path]
                with self.assertRaises(CogitoError):
                    materialize_contract(path_package(), [amendment])

    def test_rejects_shape_duplicates_and_unknown_fields(self):
        for field, value in [("paths", []), ("paths", ["new.py", "new.py"]), ("paths", ["new", "new/file.py"]), ("task_id", "T-missing"), ("check_ids", []), ("check_ids", ["C-1", "C-1"]), ("check_ids", ["C-missing"]), ("reason", ""), ("unreviewed", True)]:
            with self.subTest(field=field, value=value):
                amendment = path_amendment()
                amendment["path_additions"][0][field] = value
                with self.assertRaises(CogitoError):
                    materialize_contract(path_package(), [amendment])
        amendment = path_amendment()
        amendment["path_additions"].append(copy.deepcopy(amendment["path_additions"][0]))
        with self.assertRaises(CogitoError):
            materialize_contract(path_package(), [amendment])

    def test_rejects_legacy_mixed_changes_and_optional_checks(self):
        package, amendment = path_package(), path_amendment()
        del package["task_delivery"]
        with self.assertRaisesRegex(CogitoError, "atomic"):
            materialize_contract(package, [amendment])
        package = path_package()
        package["checks"].append({"id": "C-optional", "argv": ["true"], "required": False})
        amendment["path_additions"][0]["check_ids"] = ["C-optional"]
        with self.assertRaisesRegex(CogitoError, "required checks"):
            materialize_contract(package, [amendment])
        amendment = path_amendment()
        amendment["path_fixes"] = ["src/original.py"]
        with self.assertRaisesRegex(CogitoError, "cannot mix"):
            materialize_contract(path_package(), [amendment])

    def test_rejects_other_task_and_slice_ownership(self):
        package = path_package()
        package["approved_paths"].append("src/mapper.py")
        package["slices"][0]["worker"]["allowed_paths"].append("src/mapper.py")
        other = copy.deepcopy(package["execution_dag"]["tasks"][0])
        other.update(id="T-2", paths=["src/mapper.py"])
        package["execution_dag"]["tasks"].append(other)
        with self.assertRaisesRegex(CogitoError, "another Task"):
            materialize_contract(package, [path_amendment()])
        package["execution_dag"]["tasks"].pop()
        other_slice = copy.deepcopy(package["slices"][0])
        other_slice["id"] = "FS-002"
        other_slice["worker"].update(branch="codex/fs-002", worktree=".cogito/worktrees/FS-002", allowed_paths=["src/mapper.py"])
        package["slices"].append(other_slice)
        with self.assertRaisesRegex(CogitoError, "another Slice"):
            materialize_contract(package, [path_amendment()])

    def test_agent_result_override_preserves_original_package_validation(self):
        package = path_package()
        result = {"schema_version": "3.0", "run_id": package["run_id"],
                  "task_id": "T-1", "agent_id": "worker", "role": "implementer",
                  "status": "complete", "base_commit": "a" * 40, "head_commit": "b" * 40,
                  "changed_paths": ["src/mapper.py"], "evidence": [], "risks": [],
                  "requested_transition": "verifying"}
        with self.assertRaisesRegex(CogitoError, "outside"):
            validate_agent_result(result, package)
        validate_agent_result(result, package, approved_paths=["src/mapper.py"])
        with self.assertRaisesRegex(CogitoError, "outside"):
            validate_agent_result(result, package, approved_paths=[])
        package["schema_version"] = "invalid"
        with self.assertRaises(CogitoError):
            validate_agent_result(result, package, approved_paths=["src/mapper.py"])

    def test_rejects_multiple_target_slices(self):
        package = path_package()
        other = copy.deepcopy(package["slices"][0])
        other["id"] = "FS-002"
        other["worker"].update(branch="codex/fs-002", worktree=".cogito/worktrees/FS-002", allowed_paths=["other/original.py"])
        package["slices"].append(other)
        package["approved_paths"].append("other/original.py")
        task = copy.deepcopy(package["execution_dag"]["tasks"][0])
        task.update(id="T-2", slice_id="FS-002", paths=["other/original.py"])
        package["execution_dag"]["tasks"].append(task)
        amendment = path_amendment()
        amendment["path_additions"].append({"task_id": "T-2", "paths": ["other/new.py"],
                                            "reason": "Other missing mapper", "check_ids": ["C-1"]})
        with self.assertRaisesRegex(CogitoError, "one Slice"):
            materialize_contract(package, [amendment])

    def test_rejects_prior_addition_repeated_with_new_id(self):
        first, second = path_amendment(), path_amendment()
        second["id"] = "AM-2"
        with self.assertRaisesRegex(CogitoError, "already within"):
            materialize_contract(path_package(), [first, second])


if __name__ == "__main__":
    unittest.main()
