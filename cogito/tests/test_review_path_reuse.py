"""Focused regressions for same-cycle review correction path ownership."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cogito_common import CogitoError, hash_json
from cogito_path_amendment_contract import validate_path_additions, apply_path_additions
from cogito_path_amendment_state import path_targets, project_path_amendment, apply_path_projection, review_binding


class ReviewPathReuseTests(unittest.TestCase):
    def setUp(self):
        original = dict(id='T-003', slice_id='FS-046', paths=['tests/detail.py'], check_ids=['V-003'], status='complete')
        correction = dict(id='T-013', slice_id='FS-046', paths=['src/detail.py'], check_ids=['V-003'], status='running')
        self.state = dict(state='review-fix', tasks={'T-003': original, 'T-013': correction},
                          agent_results=[], package_hash='approved', effective_contract_hash='original')
        self.events = [dict(sequence=0, type='agent-result-recorded', payload=dict(result=dict(task_id='T-003', role='implementer', status='complete'))),
                       dict(sequence=1, type='task-updated', payload=dict(task_id='T-003', status='complete')),
                       dict(sequence=2, type='review-fix-required', payload=dict(review_task_id='T-003')),
                       dict(sequence=3, type='technical-amendment-added', payload=dict(amendment=dict(added_tasks=[correction])))]
        self.amendment = dict(id='TA-002', reason='修正原成功案例年度', path_additions=[
            dict(task_id='T-013', paths=['tests/detail.py'], reason='本輪 finding 必要 fixture', check_ids=['V-003'])])
        self.effective = dict(task_delivery='atomic', kind='change', execution_dag=dict(tasks=[original, correction], edges=[]),
                              slices=[dict(id='FS-046', spec=dict(path='docs/spec.md'), plan=dict(path='docs/plan.md'),
                                           worker=dict(allowed_paths=['src/detail.py', 'tests/detail.py']))],
                              checks=[dict(id='V-003', required=True)], approved_paths=['src/detail.py', 'tests/detail.py'],
                              human_gate=dict(high_risk_hotspots=[]), source_registry=[])

    def validate(self):
        validate_path_additions(self.effective, self.amendment)
        return path_targets(self.state, self.amendment, self.events)

    def test_completed_original_can_be_reused_without_mutating_history(self):
        old = copy.deepcopy(self.state)
        self.validate()
        self.assertEqual(self.state, old)
        effective = copy.deepcopy(self.effective)
        apply_path_additions(effective, self.amendment)
        self.assertEqual(effective['execution_dag']['tasks'][0], old['tasks']['T-003'])
        self.assertIn('tests/detail.py', effective['execution_dag']['tasks'][1]['paths'])
        self.assertNotEqual(hash_json(effective), hash_json(self.effective))

    def test_normal_execution_cannot_reuse_task_path(self):
        self.state['state'] = 'executing'
        with self.assertRaises(CogitoError): self.validate()

    def test_original_must_be_complete(self):
        for status in ['pending', 'leased', 'running', 'blocked', 'integrated']:
            with self.subTest(status=status):
                self.state['tasks']['T-003']['status'] = status
                with self.assertRaises(CogitoError): self.validate()

    def test_completion_must_precede_review(self):
        self.events[1]['sequence'] = 4
        with self.assertRaises(CogitoError): self.validate()

    def test_missing_completion_record_rejected(self):
        self.events.pop(1)
        with self.assertRaises(CogitoError): self.validate()

    def test_missing_finding_rejected(self):
        self.events.pop(2)
        with self.assertRaises(CogitoError): self.validate()

    def test_prior_cycle_target_rejected(self):
        self.events.append(dict(sequence=4, type='review-fix-required', payload=dict(review_task_id='T-003')))
        with self.assertRaises(CogitoError): self.validate()

    def test_completed_target_rejected(self):
        self.state['tasks']['T-013']['status'] = 'complete'
        with self.assertRaises(CogitoError): self.validate()

    def test_recorded_implementer_target_rejected(self):
        self.state['agent_results'] = [dict(task_id='T-013', role='implementer', status='complete')]
        with self.assertRaises(CogitoError): self.validate()

    def test_cross_slice_rejected(self):
        self.state['tasks']['T-003']['slice_id'] = 'FS-047'
        with self.assertRaises(CogitoError): self.validate()

    def test_wrong_finding_slice_rejected(self):
        self.state['tasks']['T-099'] = dict(id='T-099', slice_id='FS-047', paths=[], status='complete')
        self.events[2]['payload']['review_task_id'] = 'T-099'
        with self.assertRaises(CogitoError): self.validate()

    def test_protected_paths_rejected(self):
        for path in ['docs/cogito/secret.json', 'docs/spec.md', 'docs/plan.md', 'src/security.py']:
            with self.subTest(path=path):
                self.effective['human_gate']['high_risk_hotspots'] = ['src/security.py']
                self.amendment['path_additions'][0]['paths'] = [path]
                with self.assertRaises(CogitoError): self.validate()

    def test_existing_target_path_rejected(self):
        self.amendment['path_additions'][0]['paths'] = ['src/detail.py']
        with self.assertRaises(CogitoError): self.validate()

    def test_unrelated_new_path_keeps_existing_workflow(self):
        self.state['state'] = 'executing'
        self.amendment['path_additions'][0]['paths'] = ['src/new.py']
        self.validate()

    def test_verified_and_reviewed_originals_remain_completed(self):
        for status in ['verified', 'reviewed']:
            self.state['tasks']['T-003']['status'] = status
            self.validate()

    def test_completion_requires_recorded_result(self):
        self.events.pop(0)
        with self.assertRaises(CogitoError): self.validate()

    def shared_owner(self):
        owner = dict(id='T-011', slice_id='FS-048', paths=['tests/detail.py'], check_ids=['V-003'], status='pending')
        self.state['tasks']['T-011'] = owner
        self.effective['execution_dag']['tasks'].append(owner)
        self.effective['slices'].append(dict(id='FS-048', spec=dict(path='docs/later-spec.md'),
                                            plan=dict(path='docs/later-plan.md'), worker=dict(allowed_paths=['tests/detail.py'])))
        return owner

    def test_preexisting_shared_path_with_unstarted_later_owner(self):
        self.shared_owner()
        self.validate()

    def test_shared_owner_must_remain_unstarted(self):
        owner = self.shared_owner()
        for status in ['leased', 'running', 'blocked', 'complete', 'verified']:
            owner['status'] = status
            with self.assertRaises(CogitoError): self.validate()
        owner['status'] = 'pending'
        owner['base_commit'] = 'existing-lease'
        with self.assertRaises(CogitoError): self.validate()

    def test_shared_path_requires_existing_target_slice_scope(self):
        self.shared_owner()
        self.effective['slices'][0]['worker']['allowed_paths'] = ['src/detail.py']
        with self.assertRaises(CogitoError): self.validate()

    def proposal(self):
        proposal = dict(amendment=self.amendment, base_contract_hash='original', author_id='coordinator', executor_ids=['implementer'])
        proposal['proposal_hash'] = hash_json(proposal)
        return proposal

    def review(self, proposal):
        return dict(proposal_hash=proposal['proposal_hash'], reviewer_id='reviewer', decision='within-approved-scope',
                    assessment={k: '已核對原核准範圍與相關測試' for k in ['requirements', 'api', 'data_model', 'security', 'slice', 'checks']}, findings=[])

    def test_proposal_and_review_projection_replay_preserve_original(self):
        proposal = self.proposal()
        review = self.review(proposal)
        original = copy.deepcopy(self.state['tasks']['T-003'])
        for _ in range(2):
            state = copy.deepcopy(self.state)
            project_path_amendment(state, 'path-amendment-proposed', proposal, self.events)
            apply_path_projection(state, dict(amendment=self.amendment, scope_review=review), self.events)
            self.assertEqual(state['tasks']['T-003'], original)
            self.assertIn('tests/detail.py', state['tasks']['T-013']['paths'])
            self.assertNotIn('path_amendment', state)

    def test_replay_rejects_original_still_running(self):
        self.state['tasks']['T-003']['status'] = 'running'
        with self.assertRaises(CogitoError):
            project_path_amendment(self.state, 'path-amendment-proposed', self.proposal(), self.events)

    def test_nonindependent_reviewer_rejected(self):
        p = self.proposal()
        for identity in ['coordinator', 'implementer']:
            r = self.review(p)
            r['reviewer_id'] = identity
            with self.assertRaises(CogitoError): review_binding(p, r)

    def test_proposal_tampering_rejected(self):
        p = self.proposal()
        p['author_id'] = 'tampered'
        with self.assertRaises(CogitoError): project_path_amendment(self.state, 'path-amendment-proposed', p, self.events)

    def test_no_review_cannot_apply(self):
        with self.assertRaises(CogitoError): apply_path_projection(self.state, dict(amendment=self.amendment), self.events)


if __name__ == '__main__':
    unittest.main()
