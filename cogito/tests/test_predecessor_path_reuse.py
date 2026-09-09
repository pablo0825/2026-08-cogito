"""Narrow integrated-predecessor scope reuse and replay guards."""
import copy
from pathlib import Path
import sys
import tempfile
import subprocess
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cogito_common import CogitoError, hash_json
from cogito_path_amendment_contract import validate_path_additions, apply_path_additions
from cogito_path_amendment_state import path_targets, predecessor_deliveries, project_path_amendment, apply_path_projection
from cogito_path_amendment import validate_predecessor_ancestry
from cogito_test_support import GitTestCase, init_repo, git
from cogito_contracts import materialize_contract
import test_review_path_reuse as review_tests
import test_path_amendment_contract as contract_tests


class PredecessorPathReuseTests(GitTestCase):
    def setUp(self):
        super().setUp()
        review_tests.ReviewPathReuseTests.setUp(self)
        owner = self.state['tasks']['T-003']
        owner['status'] = 'integrated'
        target = self.state['tasks']['T-013']
        target.update(slice_id='FS-048', base_commit='baseline', depends_on=['T-009'])
        middle = dict(id='T-009', slice_id='FS-047', paths=['src/middle.py'], check_ids=['V-003'], depends_on=['T-003'], status='integrated')
        self.state['tasks']['T-009'] = middle
        self.effective['execution_dag']['tasks'].append(middle)
        self.effective['execution_dag']['edges'] = [
            {'from': 'T-003', 'to': 'T-009'}, {'from': 'T-009', 'to': 'T-013'}]
        for slice_id in ['FS-047', 'FS-048']:
            self.effective['slices'].append(dict(id=slice_id, spec=dict(path=f'docs/{slice_id}-spec.md'), plan=dict(path=f'docs/{slice_id}-plan.md'), worker=dict(allowed_paths=['src/middle.py' if slice_id == 'FS-047' else 'src/detail.py'])))
        self.state.update(state='executing', task_delivery='atomic', agent_results=[dict(task_id='T-003', role='implementer', status='complete', head_commit='delivered')])
        self.events = []

    def validate(self):
        validate_path_additions(self.effective, self.amendment, ['tests/detail.py','src/detail.py'])
        return path_targets(self.state, self.amendment, self.events)

    def test_transitive_predecessor_and_immutable_owner(self):
        original = copy.deepcopy(self.state['tasks']['T-003'])
        self.validate()
        effective = copy.deepcopy(self.effective)
        apply_path_additions(effective, self.amendment)
        self.assertEqual(effective['execution_dag']['tasks'][0], original)
        self.assertEqual(predecessor_deliveries(self.state,self.amendment), [dict(task_id='T-013',base_commit='baseline',owner_heads=['delivered'])])
        self.assertNotEqual(hash_json(effective),hash_json(self.effective))

    def test_original_package_scope_required(self):
        with self.assertRaises(CogitoError): validate_path_additions(self.effective,self.amendment,['src/detail.py'])

    def test_exact_originally_approved_read_source_allows_predecessor_only(self):
        self.effective['source_registry']=[dict(path='tests/detail.py',disposition='read-only-source')]
        self.validate()
        self.state['tasks']['T-003']['status']='running'
        with self.assertRaises(CogitoError): self.validate()

    def test_read_source_without_original_scope_or_predecessor_rejected(self):
        self.effective['source_registry']=[dict(path='tests/detail.py',disposition='read-only-source')]
        with self.assertRaises(CogitoError): validate_path_additions(self.effective,self.amendment,['src/detail.py'])
        with self.assertRaises(CogitoError): validate_path_additions(self.effective,self.amendment)
        self.state['tasks']['T-009']['depends_on']=[]
        with self.assertRaises(CogitoError): self.validate()

    def test_other_source_dispositions_and_broad_source_stay_protected(self):
        for source in [dict(path='tests/detail.py',disposition='adopted'),
                       dict(path='tests/detail.py',disposition='updated'),
                       dict(path='tests',disposition='read-only-source')]:
            self.effective['source_registry']=[source]
            with self.subTest(source=source), self.assertRaises(CogitoError): self.validate()

    def test_read_source_never_overrides_control_or_safety_protection(self):
        self.effective['source_registry']=[dict(path='tests/detail.py',disposition='read-only-source')]
        self.effective['human_gate']['high_risk_hotspots']=['tests/detail.py']
        with self.assertRaises(CogitoError): self.validate()
        self.effective['human_gate']['high_risk_hotspots']=[]
        self.effective['slices'][0]['spec']['path']='tests/detail.py'
        with self.assertRaises(CogitoError): self.validate()

    def test_non_atomic_and_missing_baseline_rejected(self):
        for key in ['task_delivery']:
            self.state.pop(key)
            with self.assertRaises(CogitoError): self.validate()
        self.state['task_delivery']='atomic'
        self.state['tasks']['T-013'].pop('base_commit')
        with self.assertRaises(CogitoError): self.validate()

    def test_all_owners_must_be_integrated_with_delivery(self):
        for status in ['pending','leased','running','blocked','complete','verified','reviewed']:
            self.state['tasks']['T-003']['status']=status
            with self.subTest(status=status), self.assertRaises(CogitoError): self.validate()
        self.state['tasks']['T-003']['status']='integrated'
        self.state['agent_results']=[]
        with self.assertRaises(CogitoError): self.validate()

    def test_parallel_or_nonpredecessor_owner_rejected(self):
        self.state['tasks']['T-009']['depends_on']=[]
        with self.assertRaises(CogitoError): self.validate()

    def test_one_unintegrated_shared_owner_rejected(self):
        self.state['tasks']['T-009']['paths'].append('tests/detail.py')
        with self.assertRaises(CogitoError): self.validate()

    def test_completed_target_and_protected_scope_still_rejected(self):
        self.state['tasks']['T-013']['status']='complete'
        with self.assertRaises(CogitoError): self.validate()
        self.state['tasks']['T-013']['status']='running'
        self.effective['human_gate']['high_risk_hotspots']=['tests/detail.py']
        with self.assertRaises(CogitoError): self.validate()

    def proposal(self):
        proposal=review_tests.ReviewPathReuseTests.proposal(self)
        proposal['predecessor_deliveries']=predecessor_deliveries(self.state,self.amendment)
        proposal['proposal_hash']=hash_json({k:v for k,v in proposal.items() if k!='proposal_hash'})
        return proposal

    def test_replay_checks_exact_delivery_baseline_and_preserves_history(self):
        p=self.proposal()
        review=review_tests.ReviewPathReuseTests.review(self,p)
        for _ in range(2):
            state=copy.deepcopy(self.state)
            project_path_amendment(state,'path-amendment-proposed',p)
            apply_path_projection(state,dict(amendment=self.amendment,scope_review=review))
            self.assertEqual(state['tasks']['T-003'],self.state['tasks']['T-003'])
            self.assertIn('tests/detail.py',state['tasks']['T-013']['paths'])
        p['predecessor_deliveries'][0]['base_commit']='other'
        p['proposal_hash']=hash_json({k:v for k,v in p.items() if k!='proposal_hash'})
        with self.assertRaises(CogitoError): project_path_amendment(self.state,'path-amendment-proposed',p)

    def test_state_drift_after_proposal_rejected(self):
        p=self.proposal()
        project_path_amendment(self.state,'path-amendment-proposed',p)
        self.state['tasks']['T-013']['base_commit']='other'
        with self.assertRaises(CogitoError): apply_path_projection(self.state,dict(amendment=self.amendment,scope_review=review_tests.ReviewPathReuseTests.review(self,p)))

    def test_parent_path_overlap_still_binds_predecessor_delivery(self):
        self.amendment['path_additions'][0]['paths'] = ['tests']
        validate_path_additions(self.effective, self.amendment, ['tests'])
        self.assertEqual(predecessor_deliveries(self.state, self.amendment), [
            dict(task_id='T-013', base_commit='baseline', owner_heads=['delivered'])])
        proposal = self.proposal()
        proposal.pop('predecessor_deliveries')
        proposal['proposal_hash'] = hash_json({k: v for k, v in proposal.items() if k != 'proposal_hash'})
        with self.assertRaisesRegex(CogitoError, 'baseline binding'):
            project_path_amendment(self.state, 'path-amendment-proposed', proposal)

    def test_materialization_uses_edges_and_original_not_amended_scope(self):
        package = contract_tests.path_package()
        owner = package['execution_dag']['tasks'][0]
        previous_id = owner['id']
        for number in (2, 3):
            slice_id = f'FS-next-{number}'
            path = f'src/next-{number}.py'
            successor = copy.deepcopy(package['slices'][0])
            successor['id'] = slice_id
            successor['worker'].update(branch=f'codex/next-{number}',
                worktree=f'.cogito/worktrees/next-{number}', allowed_paths=[path])
            package['slices'].append(successor)
            package['approved_paths'].append(path)
            task = {**owner, 'id': f'T-next-{number}', 'slice_id': slice_id, 'paths': [path]}
            package['execution_dag']['tasks'].append(task)
            package['execution_dag']['edges'].append({'from': previous_id, 'to': task['id']})
            previous_id = task['id']
        amendment = contract_tests.path_amendment()
        amendment['path_additions'][0].update(task_id=previous_id, paths=['src/original.py'])
        frozen = copy.deepcopy((package, amendment))
        effective = materialize_contract(package, [amendment])
        self.assertIn('src/original.py', effective['execution_dag']['tasks'][-1]['paths'])
        self.assertEqual((package, amendment), frozen)
        self.assertEqual(effective['execution_dag']['tasks'][0], owner)
        first = contract_tests.path_amendment()
        first['path_additions'][0]['paths'] = ['src/later.py']
        second = copy.deepcopy(amendment)
        second['id'] = 'AM-2'
        second['path_additions'][0]['paths'] = ['src/later.py']
        with self.assertRaisesRegex(CogitoError, 'another Task'):
            materialize_contract(package, [first, second])

    def test_real_git_requires_delivered_commit_in_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            def git_at(root,*args):
                return git(Path(root), *args)
            init_repo(Path(directory))
            git_at(directory,'commit','--allow-empty','-qm','owner')
            owner=git_at(directory,'rev-parse','HEAD')
            git_at(directory,'commit','--allow-empty','-qm','target baseline')
            baseline=git_at(directory,'rev-parse','HEAD')
            validate_predecessor_ancestry(git_at,directory,[dict(base_commit=baseline,owner_heads=[owner])])
            git_at(directory,'checkout','-q','--orphan','unrelated')
            git_at(directory,'commit','--allow-empty','-qm','unrelated')
            unrelated=git_at(directory,'rev-parse','HEAD')
            with self.assertRaises((CogitoError,subprocess.CalledProcessError)):
                validate_predecessor_ancestry(git_at,directory,[dict(base_commit=owner,owner_heads=[baseline])])
            with self.assertRaises((CogitoError,subprocess.CalledProcessError)):
                validate_predecessor_ancestry(git_at,directory,[dict(base_commit=unrelated,owner_heads=[owner])])

if __name__=='__main__': unittest.main()
