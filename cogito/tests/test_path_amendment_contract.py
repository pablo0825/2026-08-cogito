"""Scope additions preserve frozen inputs and reject ownership broadening."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_contracts import materialize_contract, package_hash, validate_agent_result
from test_atomic_task_contract import atomic_package
from cogito_path_amendment_state import path_targets, project_path_amendment, apply_path_projection, ASSESSMENTS
from cogito_common import hash_json


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
    @staticmethod
    def correction():
        amendment = path_amendment()
        amendment['path_additions'][0]['task_id'] = 'T-fix'
        amendment['added_tasks'] = [{'id': 'T-fix', 'slice_id': 'FS-1',
            'paths': ['src/original.py', 'src/mapper.py', 'tests/test_mapper.py'],
            'responsibility': 'Complete approved response', 'check_ids': ['C-1'],
            'depends_on': ['T-1']}]
        # Use the owning Slice ID from the fixture, not a second responsibility.
        amendment['added_tasks'][0]['slice_id'] = path_package()['slices'][0]['id']
        return amendment

    def test_new_correction_materializes_without_changing_original_task(self):
        package, amendment = path_package(), self.correction()
        before = copy.deepcopy((package, amendment))
        effective = materialize_contract(package, [amendment])
        self.assertEqual(effective['execution_dag']['tasks'][0], package['execution_dag']['tasks'][0])
        self.assertEqual(effective['execution_dag']['tasks'][-1], amendment['added_tasks'][0])
        self.assertIn('src/mapper.py', effective['approved_paths'])
        self.assertIn('src/mapper.py', effective['slices'][0]['worker']['allowed_paths'])
        self.assertEqual((package, amendment), before)
        changed = copy.deepcopy(amendment)
        changed['added_tasks'][0]['responsibility'] = 'Revised explanation'
        self.assertNotEqual(effective['effective_contract_hash'],
                            materialize_contract(package, [changed])['effective_contract_hash'])

    def test_correction_rejects_missing_grants_and_unrelated_or_reused_tasks(self):
        for field, value in [('paths', ['src/original.py']), ('paths', ['src/mapper.py', 'tests/test_mapper.py', 'unapproved.py']),
                             ('check_ids', ['C-missing']), ('id', 'T-1'), ('slice_id', 'FS-missing')]:
            with self.subTest(field=field, value=value):
                amendment = self.correction()
                amendment['added_tasks'][0][field] = value
                with self.assertRaises(CogitoError):
                    materialize_contract(path_package(), [amendment])
        amendment = self.correction()
        extra = {**amendment['added_tasks'][0], 'id': 'T-extra'}
        amendment['added_tasks'].append(extra)
        with self.assertRaisesRegex(CogitoError, 'exactly'):
            materialize_contract(path_package(), [amendment])

    def test_review_projection_checks_stage_and_preserves_completed_task(self):
        original = {**path_package()['execution_dag']['tasks'][0], 'status': 'complete'}
        state = {'state': 'review-fix', 'package_hash': 'a' * 64,
                 'effective_contract_hash': 'a' * 64, 'tasks': {'T-1': original}, 'agent_results': []}
        amendment = self.correction()
        proposal = {'amendment': amendment, 'author_id': 'coordinator', 'executor_ids': ['worker'],
                    'base_contract_hash': 'a' * 64}
        proposal['proposal_hash'] = hash_json(proposal)
        with self.assertRaisesRegex(CogitoError, 'review-fix'):
            path_targets({**state, 'state': 'executing'}, amendment)
        with self.assertRaisesRegex(CogitoError, 'new correction'):
            path_targets(state, path_amendment())
        project_path_amendment(state, 'path-amendment-proposed', proposal)
        before = copy.deepcopy(state['tasks'])
        review = {'proposal_hash': proposal['proposal_hash'], 'reviewer_id': 'reviewer',
                  'decision': 'within-approved-scope', 'assessment': {k: 'unchanged' for k in ASSESSMENTS}, 'findings': []}
        apply_path_projection(state, {'amendment': amendment, 'scope_review': review})
        self.assertEqual(state['tasks'], before)
        self.assertNotIn('path_amendment', state)
        with self.assertRaisesRegex(CogitoError, 'pending'):
            apply_path_projection(state, {'amendment': amendment, 'scope_review': review})

    def test_review_targets_reject_unintegrated_cross_slice_dependency(self):
        amendment = self.correction()
        amendment['added_tasks'][0]['depends_on'] = ['T-other']
        state = {'state': 'review-fix', 'tasks': {'T-other': {
            'id': 'T-other', 'slice_id': 'FS-other', 'paths': ['other.py'], 'status': 'reviewed'}}, 'agent_results': []}
        with self.assertRaisesRegex(CogitoError, 'already be integrated'):
            path_targets(state, amendment)
        state['tasks']['T-other']['status'] = 'integrated'
        self.assertIn('T-fix', path_targets(state, amendment))

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

    def test_same_slice_contract_reuse_requires_runtime_review(self):
        package = path_package()
        package["approved_paths"].append("src/mapper.py")
        package["slices"][0]["worker"]["allowed_paths"].append("src/mapper.py")
        other = copy.deepcopy(package["execution_dag"]["tasks"][0])
        other.update(id="T-2", paths=["src/mapper.py"])
        package["execution_dag"]["tasks"].append(other)
        effective = materialize_contract(package, [path_amendment()])
        self.assertIn('src/mapper.py', effective['execution_dag']['tasks'][0]['paths'])
        state = {'state': 'executing', 'tasks': {
            task['id']: {**task, 'status': 'running'} for task in package['execution_dag']['tasks']}}
        with self.assertRaisesRegex(CogitoError, 'current review Slice'):
            path_targets(state, path_amendment())
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
