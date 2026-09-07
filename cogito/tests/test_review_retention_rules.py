"""Pure retention rules reject unsafe reuse without rewriting recorded inputs."""
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from cogito_common import CogitoError
from cogito_review_retention_rules import (
    source_review, validate_candidate, validate_impact, validate_reviewer,
)


def impact():
    return {
        'author_id': 'coordinator',
        'retained': [{'task_id': 'T-001', 'reason': 'Estimate has no display dependency',
                      'dependency_paths': ['src/shared/rules.py']}],
        'affected_task_ids': ['T-003'], 'check_ids': ['display'],
        'assessment': 'Only reviewer display wording changed',
    }


def approval(sequence=10, **changes):
    return {'sequence': sequence, 'event_hash': f'hash-{sequence}',
            'type': 'agent-result-recorded', 'payload': {'result': {
                'task_id': 'T-001', 'role': 'reviewer', 'status': 'complete',
                'agent_id': 'reviewer', 'reviewed_implementer': 'worker',
                'requested_transition': 'review-approved', **changes}}}


class ReviewRetentionContractTests(unittest.TestCase):
    def test_impact_validation_preserves_input(self):
        value = impact()
        before = copy.deepcopy(value)
        validate_impact(value)
        self.assertEqual(value, before)

    def test_malformed_impact_is_rejected_without_mutation(self):
        invalid = [
            {'extra': True}, {'author_id': None}, {'assessment': ''},
            {'affected_task_ids': []}, {'affected_task_ids': ['T-003', 'T-003']},
            {'affected_task_ids': ['T-001']}, {'check_ids': []},
            {'check_ids': ['display', 'display']}, {'retained': []},
            {'retained': impact()['retained'] * 2},
        ]
        for replacement in invalid:
            with self.subTest(replacement=replacement):
                value = {**impact(), **replacement}
                before = copy.deepcopy(value)
                with self.assertRaises(CogitoError):
                    validate_impact(value)
                self.assertEqual(value, before)

    def test_malformed_retained_entry_is_rejected(self):
        for replacement in (
            {'reason': ''}, {'task_id': 1}, {'extra': True},
            {'dependency_paths': ['../escape']}, {'dependency_paths': ['/absolute']},
            {'dependency_paths': ['src/shared.py', 'src/shared.py']},
        ):
            with self.subTest(replacement=replacement):
                value = impact()
                value['retained'][0].update(replacement)
                with self.assertRaises(CogitoError):
                    validate_impact(value)

    def test_reviewer_must_be_independent_of_author_and_all_implementers(self):
        value = impact()
        implementers = ['original-worker', 'fix-worker']
        validate_reviewer(value, 'independent-reviewer', 'Dependencies checked', implementers)
        for reviewer in ['coordinator', *implementers]:
            with self.subTest(reviewer=reviewer), self.assertRaises(CogitoError):
                validate_reviewer(value, reviewer, 'Dependencies checked', implementers)
        with self.assertRaises(CogitoError):
            validate_reviewer(value, 'independent-reviewer', '', implementers)


class ReviewRetentionSourceTests(unittest.TestCase):
    def test_original_approval_survives_multiple_retention_rounds(self):
        original = approval()
        events = [original, {'type': 'review-retention-recorded', 'sequence': 25,
                            'payload': {}}, {'type': 'verification-passed', 'sequence': 40,
                                            'payload': {}}]
        before = copy.deepcopy(events)
        self.assertEqual(source_review(events, 'T-001', 40), original)
        self.assertEqual(events, before)

    def test_missing_or_current_cycle_review_is_not_a_prior_approval(self):
        for events in ([], [approval(40)], [approval(41)], [approval(task_id='T-002')]):
            with self.subTest(events=events), self.assertRaises(CogitoError):
                source_review(events, 'T-001', 40)

    def test_newer_invalid_review_cannot_fall_back_to_original(self):
        for changes in (
            {'status': 'needs-fix', 'requested_transition': 'review-fix'},
            {'status': 'blocked'}, {'requested_transition': 'executing'},
            {'agent_id': 'worker'},
        ):
            with self.subTest(changes=changes):
                events = [approval(), approval(20, **changes)]
                before = copy.deepcopy(events)
                with self.assertRaises(CogitoError):
                    source_review(events, 'T-001', 40)
                self.assertEqual(events, before)

    def test_fresh_real_approval_supersedes_previous_finding(self):
        newest = approval(30)
        self.assertEqual(source_review([
            approval(), approval(20, status='needs-fix'), newest], 'T-001', 40), newest)


class ReviewRetentionCandidateTests(unittest.TestCase):
    def setUp(self):
        self.tasks = {
            'T-001': {'paths': ['src/estimate/**'], 'check_ids': ['estimate'],
                      'depends_on': ['T-002'], 'acceptance_ids': ['AC-001']},
            'T-002': {'paths': ['src/domain/**'], 'check_ids': ['domain'], 'depends_on': []},
            'T-003': {'paths': ['src/display/**'], 'check_ids': ['display'], 'depends_on': []},
        }
        self.checks = {'estimate': {'command': ['python3', 'test_estimate.py']}}
        self.task = copy.deepcopy(self.tasks['T-001'])
        self.impact = impact()

    def validate(self, touched=(), **overrides):
        args = dict(task_id='T-001', tasks=self.tasks, touched_paths=touched,
                    impact=self.impact, old_task=self.task, new_task=self.task,
                    old_checks=self.checks, new_checks=self.checks)
        args.update(overrides)
        return validate_candidate(**args)

    def test_disjoint_change_preserves_all_inputs(self):
        before = copy.deepcopy((self.tasks, self.task, self.impact, self.checks))
        self.validate(['src/display/label.py'])
        self.assertEqual((self.tasks, self.task, self.impact, self.checks), before)

    def test_direct_transitive_and_declared_semantic_dependencies_reject(self):
        for path in ('src/estimate/api.py', 'src/domain/resolver.py', 'src/shared/rules.py'):
            with self.subTest(path=path), self.assertRaises(CogitoError):
                self.validate([path])

    def test_affected_ancestor_rejects_even_with_disjoint_diff(self):
        self.impact['affected_task_ids'].append('T-002')
        with self.assertRaises(CogitoError):
            self.validate(['src/display/label.py'])

    def test_unknown_dag_dependency_fails_closed(self):
        self.tasks['T-002']['depends_on'] = ['T-missing']
        with self.assertRaises(CogitoError):
            self.validate(['src/display/label.py'])

    def test_task_or_required_check_contract_drift_rejects(self):
        for changed in (
            {**self.task, 'acceptance_ids': ['AC-002']},
            {**self.task, 'check_ids': []}, {**self.task, 'paths': ['src/new/**']},
        ):
            with self.subTest(task=changed), self.assertRaises(CogitoError):
                self.validate(new_task=changed)
        for checks in ({}, {'estimate': {'command': ['python3', 'other_test.py']}}):
            with self.subTest(checks=checks), self.assertRaises(CogitoError):
                self.validate(new_checks=checks)
        with self.assertRaises(CogitoError):
            self.validate(old_checks={})

    def test_cumulative_touches_including_reverted_change_remain_unsafe(self):
        # The Git adapter supplies all historical touched paths, even if net diff
        # only contains display. Rules must not discard an earlier task touch.
        self.validate(['src/display/label.py'])
        with self.assertRaises(CogitoError):
            self.validate(['src/estimate/api.py', 'src/display/label.py'])

    def test_rename_or_delete_original_path_remains_unsafe(self):
        for touched in (['src/estimate/old.py', 'src/display/moved.py'], ['src/estimate/deleted.py']):
            with self.subTest(touched=touched), self.assertRaises(CogitoError):
                self.validate(touched)


if __name__ == '__main__':
    unittest.main()
