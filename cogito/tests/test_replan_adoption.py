"""Cross-run adoption requires actual historical verification, not assertions."""
from copy import deepcopy
import unittest
from cogito_test_support import minimal_package
from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash
from cogito_replan_adoption import validate_adoption, validate_atomic_transfer
from test_evidence_contract import valid_evidence


class ReplanAdoptionTests(unittest.TestCase):
    def setUp(self):
        self.source = minimal_package()
        self.target = deepcopy(self.source)
        self.target['run_id'] = 'DEV-successor'
        self.target['slices'][0]['id'] = 'FS-new'
        self.target['slices'][0]['worker'].update(branch='codex/new', worktree='.cogito/worktrees/new')
        self.target['execution_dag']['tasks'][0].update(id='T-new', slice_id='FS-new')
        self.tree = 'e' * 40
        self.result = dict(schema_version='3.0', run_id=self.source['run_id'], task_id='T-1',
                           agent_id='worker', role='implementer', status='complete', base_commit='a'*40,
                           head_commit='b'*40, changed_paths=['src/a.py'], evidence=[], risks=[],
                           requested_transition='verifying')
        self.review = dict(self.result, agent_id='reviewer', role='reviewer',
                           reviewed_implementer='worker', requested_transition='review-approved')
        self.evidence = valid_evidence()
        self.evidence.update(run_id=self.source['run_id'],
                             effective_contract_hash=package_hash(self.source),
                             check_hash=hash_json(self.source['checks'][0]),
                             worktree_binding={'content_tree': self.tree})
        self.path = self.evidence['evidence_path']
        self.events = [
            dict(sequence=1, type='agent-result-recorded', payload={'result': self.result}),
            dict(sequence=2, type='implementation-complete', payload={}),
            dict(sequence=3, type='check-evidence-recorded', payload={
                'evidence_path': self.path, 'check_id': 'C-1', 'evidence_hash': hash_json(self.evidence)}),
            dict(sequence=4, type='verification-passed', payload={'evidence': [self.path], 'passed': True}),
            dict(sequence=5, type='agent-result-recorded', payload={'result': self.review}),
            dict(sequence=6, type='review-approved', payload={'reviews': ['T-1']}),
        ]
        self.state = dict(run_id=self.source['run_id'], package_hash=package_hash(self.source),
                          effective_contract_hash=package_hash(self.source),
                          tasks={'T-1': dict(status='reviewed', agent_id='worker')},
                          evidence={self.path: dict(evidence_hash=hash_json(self.evidence),
                                                    check_id='C-1', event_sequence=3)})

    def adopt(self, target_tree=None):
        return validate_adoption(self.source, self.target, self.state, self.events, 'T-1', 'T-new',
                                 {self.path: self.evidence}, self.tree, target_tree or self.tree)

    def test_success_preserves_all_original_objects_and_requires_integration(self):
        before = deepcopy((self.source, self.target, self.state, self.events, self.evidence))
        receipt = self.adopt()
        self.assertEqual(receipt['source_reviewers'], ['reviewer'])
        self.assertEqual(receipt['evidence'][0]['evidence_hash'], hash_json(self.evidence))
        self.assertTrue(receipt['integration_verification_required'])
        self.assertEqual(before, (self.source, self.target, self.state, self.events, self.evidence))
        self.state['tasks']['T-1']['status'] = 'integrated'
        self.adopt()

    def test_changed_tree_requires_rerun(self):
        with self.assertRaisesRegex(CogitoError, 'rerun'):
            self.adopt('f' * 40)

    def test_atomic_evidence_cannot_be_adopted_as_a_completed_successor_task(self):
        for side in ('source', 'target'):
            with self.subTest(side=side):
                self.setUp()
                getattr(self, side)['task_delivery'] = 'atomic'
                with self.assertRaisesRegex(CogitoError, 'atomic Task evidence'):
                    self.adopt()

    def test_atomic_transfer_requires_fresh_work_without_downgrading_contract(self):
        source = {**self.source, 'task_delivery': 'atomic'}
        target = {**self.target, 'task_delivery': 'atomic'}
        for disposition in ('retain', 'adapt'):
            with self.assertRaisesRegex(CogitoError, 'fresh Tasks'):
                validate_atomic_transfer(source, target, [{'disposition': disposition, 'validation': 'rerun'}])
        validate_atomic_transfer(source, target, [{'disposition': 'omit', 'validation': 'rerun'}])
        with self.assertRaisesRegex(CogitoError, 'cannot downgrade'):
            validate_atomic_transfer(source, self.target, [{'disposition': 'omit'}])
        validate_atomic_transfer(self.source, self.target, [{'disposition': 'adapt', 'validation': 'rerun'}])

    def test_changed_shared_understanding_checks_policy_or_spec_require_rerun(self):
        changes = [lambda: self.target['shared_understanding'].update(hash='f'*64),
                   lambda: self.target['checks'][0].update(argv=['false']),
                   lambda: self.target['policy_snapshot'].update(fetch_allowed=True),
                   lambda: self.target['slices'][0]['spec'].update(hash='f'*64)]
        for change in changes:
            self.setUp()
            change()
            with self.assertRaises(CogitoError): self.adopt()

    def test_claimed_review_without_historical_approval_rejected(self):
        self.events.pop()
        with self.assertRaisesRegex(CogitoError, 'actual review'): self.adopt()

    def test_ledger_and_evidence_tampering_rejected(self):
        self.evidence['stdout'] = 'forged'
        with self.assertRaises(CogitoError): self.adopt()

    def test_state_ledger_without_source_event_rejected(self):
        self.events[2]['payload'] = {}
        with self.assertRaises(CogitoError): self.adopt()

    def test_evidence_not_used_by_verification_rejected(self):
        self.events[3]['payload']['evidence'] = []
        with self.assertRaises(CogitoError): self.adopt()

    def test_stale_verification_or_review_range_rejected(self):
        self.state['evidence'][self.path]['event_sequence'] = 1
        with self.assertRaises(CogitoError): self.adopt()
        self.setUp()
        self.review['head_commit'] = 'c'*40
        with self.assertRaises(CogitoError): self.adopt()

    def test_self_review_failed_or_newer_result_rejected(self):
        for mutation in ('self', 'failed', 'newer'):
            self.setUp()
            if mutation == 'self': self.review['agent_id'] = 'worker'
            elif mutation == 'failed': self.review['status'] = 'needs-fix'
            else: self.events.append(dict(sequence=7, type='agent-result-recorded', payload={'result': self.review}))
            with self.assertRaises(CogitoError): self.adopt()

    def test_dependencies_and_amendments_require_rerun(self):
        self.target['execution_dag']['edges'] = [['other', 'T-new']]
        with self.assertRaisesRegex(CogitoError, 'dependent'): self.adopt()
        self.setUp()
        self.state['effective_contract_hash'] = 'd'*64
        with self.assertRaisesRegex(CogitoError, 'amended'): self.adopt()


if __name__ == '__main__': unittest.main()
