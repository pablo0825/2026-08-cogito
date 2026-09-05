"""Task receipts remain historical; review and delivery bind current content."""

import json
import copy
import sys
from pathlib import Path

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
from cogito_contracts import package_hash
import test_atomic_task_execution as execution_tests


class AtomicVerificationTests(GitTestCase):
    executing = execution_tests.AtomicTaskTests.executing
    lease = staticmethod(execution_tests.AtomicTaskTests.lease)
    commit = staticmethod(execution_tests.AtomicTaskTests.commit)
    check = staticmethod(execution_tests.AtomicTaskTests.check)
    result = staticmethod(execution_tests.AtomicTaskTests.result)
    implement = execution_tests.AtomicTaskTests.implement

    def wave(self, *, precommit=False):
        repo, worker, store, draft = self.executing()
        first, early = self.implement(store, worker)
        last, evidence = self.implement(store, worker, 'b', precommit=precommit)
        store.transition('implementation-complete', {})
        return repo, worker, store, draft, [first, last], [early, evidence]

    @staticmethod
    def review(store, results):
        for result in results:
            store.submit_agent_result({**result, 'role': 'reviewer', 'agent_id': 'reviewer',
                                       'reviewed_implementer': 'worker', 'changed_paths': [],
                                       'evidence': [], 'requested_transition': 'review-approved'})
        store.transition('review-approved', {})

    def integrated(self):
        repo, worker, store, draft, results, evidence = self.wave()
        store.complete_verification([evidence[-1]])
        self.review(store, results)
        git(repo, 'merge', '--no-ff', '-qm', 'integrate tasks', draft['slices'][0]['worker']['branch'])
        head = git(repo, 'rev-parse', 'HEAD')
        store.complete_integration(head, 'FS-1')
        return repo, worker, store, draft, results, evidence, head

    def test_two_tasks_finalize_with_only_related_integration_check(self):
        repo, _, store, _, _, _, integration = self.integrated()
        post = self.check(store, repo, 'C-b', 'post-related')
        store.decide_post_verification([post])
        events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
        check_ids = [event['payload']['check_id'] for event in events if event['type'] == 'check-evidence-recorded']
        self.assertEqual(check_ids, ['C-a', 'C-b', 'C-b'])
        graph_path = repo / 'docs/cogito/project-graph.json'
        graph = json.loads(graph_path.read_text())
        graph['active_run_id'] = None
        graph['slices']['FS-1'].update(disposition='accepted', completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        relative = f'docs/cogito/results/{store.run_id}.json'
        result_path = repo / relative
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps({
            'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': package_hash(store.approved_package()),
            'effective_contract_hash': store.load()['effective_contract_hash'],
            'integration_commits': [integration], 'slice_dispositions': {'FS-1': 'accepted'},
            'checks': [{'id': 'C-b', 'status': 'passed', 'evidence': post['evidence_path']}],
            'reviews': [{'reviewer': 'reviewer'}], 'amendments': [],
            'human_gate': {'required': False, 'outcome': 'not-required'}, 'remaining_risks': [],
        }))
        git(repo, 'add', relative, 'docs/cogito/project-graph.json')
        git(repo, 'commit', '-qm', 'record delivery')
        store.finalize(relative, 'docs/cogito/project-graph.json', git(repo, 'rev-parse', 'HEAD'))
        self.assertEqual(store.completion_report()['status'], 'accepted')

    def test_precommit_last_task_evidence_can_verify_current_contents(self):
        _, _, store, _, results, evidence = self.wave(precommit=True)
        self.assertNotEqual(evidence[-1]['head_commit'], results[-1]['head_commit'])
        store.complete_verification([evidence[-1]])
        self.review(store, results)

    def test_integration_cannot_rewrite_an_earlier_task_inside_approved_paths(self):
        repo, _, store, draft, results, evidence = self.wave()
        store.complete_verification([evidence[-1]])
        self.review(store, results)
        git(repo, 'merge', '--no-ff', '-qm', 'integrate tasks', draft['slices'][0]['worker']['branch'])
        (repo / 'src/a.txt').write_text('before\n')
        git(repo, 'add', 'src/a.txt')
        git(repo, 'commit', '--amend', '-qm', 'silently undo earlier Task during integration')
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'atomic integration'):
            store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_parallel_slices_merge_without_repeating_task_checks(self):
        def parallel(draft):
            second = copy.deepcopy(draft['slices'][0])
            second['id'] = 'FS-2'
            second['worker'].update(branch='codex/fs-2', worktree='.cogito/worktrees/FS-2')
            draft['slices'].append(second)
            draft['execution_dag']['tasks'][1]['slice_id'] = 'FS-2'
            draft['execution_dag']['edges'] = []
        repo, first_worker, store, draft = self.executing(parallel)
        second_worker = repo / '.cogito/worktrees/FS-2'
        git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-2', str(second_worker), draft['baseline_commit'])
        first, ea = self.implement(store, first_worker)
        second, eb = self.implement(store, second_worker, 'b')
        store.transition('implementation-complete', {})
        store.complete_verification([ea, eb])
        self.review(store, [first, second])
        for slice_id, branch in (('FS-1', 'codex/fs-1'), ('FS-2', 'codex/fs-2')):
            git(repo, 'merge', '--no-ff', '-qm', 'integrate ' + slice_id, branch)
            store.complete_integration(git(repo, 'rev-parse', 'HEAD'), slice_id)
        post = self.check(store, repo, 'C-b', 'post-parallel')
        self.assertEqual(store.decide_post_verification([post])['state'], 'finalizing')
        self.assertEqual((repo / 'src/a.txt').read_text(), 'after\n')
        self.assertEqual((repo / 'src/b.txt').read_text(), 'after\n')
        self.assertEqual(len(store.load()['evidence']), 3)

    def test_fast_forward_reuses_identical_head_tree_and_contract_evidence(self):
        repo, worker, store, draft = self.executing()
        # The frozen graph is a control document, present in both snapshots.
        relative = 'docs/cogito/project-graph.json'
        (worker / relative).parent.mkdir(parents=True, exist_ok=True)
        (worker / relative).write_bytes((repo / relative).read_bytes())
        first, _ = self.implement(store, worker)
        last, evidence = self.implement(store, worker, 'b')
        store.transition('implementation-complete', {})
        store.complete_verification([evidence])
        self.review(store, [first, last])
        git(repo, 'merge', '--ff-only', draft['slices'][0]['worker']['branch'])
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        self.assertEqual(store.decide_post_verification([evidence])['state'], 'finalizing')
        self.assertEqual(len(store.load()['evidence']), 2)

    def test_early_task_evidence_cannot_replace_current_content_evidence(self):
        _, _, store, _, _, evidence = self.wave()
        with self.assertRaises(CogitoError):
            store.complete_verification([evidence[0]])

    def test_tampered_historical_task_evidence_blocks_wave(self):
        _, _, store, _, _, evidence = self.wave()
        path = Path(evidence[0]['evidence_path'])
        path.chmod(0o600)
        evidence[0]['stdout'] = 'tampered'
        path.write_text(json.dumps(evidence[0]))
        with self.assertRaisesRegex(CogitoError, 'Task evidence changed'):
            store.complete_verification([evidence[-1]])

    def test_changed_checkout_after_verification_blocks_review(self):
        _, worker, store, _, results, evidence = self.wave()
        store.complete_verification([evidence[-1]])
        (worker / 'src/a.txt').write_text('unreviewed\n')
        with self.assertRaises(CogitoError):
            self.review(store, results)

    def test_delivery_requires_integration_check_current_head_and_tree(self):
        for mode in ('missing', 'wrong-head', 'wrong-tree'):
            with self.subTest(mode=mode):
                repo, _, store, _, _, _, _ = self.integrated()
                if mode == 'missing':
                    post = []
                else:
                    post = [self.check(store, repo, 'C-b', 'post-related')]
                    if mode == 'wrong-head':
                        git(repo, 'commit', '--allow-empty', '-qm', 'later head')
                    else:
                        (repo / 'src/a.txt').write_text('unverified\n')
                with self.assertRaises(CogitoError):
                    store.decide_post_verification(post)

    def test_correction_keeps_original_receipts_and_reviews_new_task(self):
        _, worker, store, _, original, evidence = self.wave()
        original_hashes = [item['effective_contract_hash'] for item in evidence]
        store.add_amendment({
            'id': 'TA-fix', 'reason': 'Correct affected behavior',
            'added_checks': [{'id': 'C-fix', 'phase': 'task', 'argv': [sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('src/a.txt').read_text() == 'fixed\\n'"]}],
            'added_tasks': [{'id': 'T-fix', 'slice_id': 'FS-1', 'paths': ['src/a.txt'],
                             'responsibility': 'Correct a', 'check_ids': ['C-fix']}],
        })
        store.enter_correction()
        self.lease(store, 'T-fix')
        (worker / 'src/a.txt').write_text('fixed\n')
        head = self.commit(worker, 'fix a\n\nCogito-Amendment: TA-fix')
        fixed = self.check(store, worker, 'C-fix', 'fix-check')
        result = self.result(store, worker, [fixed], 'T-fix')
        store.submit_agent_result(result)
        store.update_task('T-fix', 'complete', 'worker')
        store.complete_correction('TA-fix', head)
        self.assertNotIn(fixed['effective_contract_hash'], original_hashes)
        store.complete_verification([fixed])
        self.review(store, [*original, result])
        self.assertEqual(store.load()['tasks']['T-fix']['status'], 'reviewed')
