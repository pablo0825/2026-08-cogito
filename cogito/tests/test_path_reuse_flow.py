"""Reviewed ownership reuse through real Gate commands and immutable history."""
import copy
import hashlib
import sys
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
from cogito_execution_registry import register_external, record_external_receipt
from cogito_run_store import RunStore
import test_review_path_amendment as review_tests
import test_atomic_task_verification as verification_tests


class PathReuseFlowTests(GitTestCase):
    executing = review_tests.ReviewPathAmendmentTests.executing
    lease = staticmethod(review_tests.ReviewPathAmendmentTests.lease)
    commit = staticmethod(review_tests.ReviewPathAmendmentTests.commit)
    check = staticmethod(review_tests.ReviewPathAmendmentTests.check)
    result = staticmethod(review_tests.ReviewPathAmendmentTests.result)
    implement = review_tests.ReviewPathAmendmentTests.implement
    review = staticmethod(review_tests.ReviewPathAmendmentTests.review)
    fixture = review_tests.ReviewPathAmendmentTests.fixture
    cli = review_tests.ReviewPathAmendmentTests.cli

    @staticmethod
    def stop_worker(repo, store):
        register_external(repo, store.run_id, 'worker', 'reuse-worker')
        record_external_receipt(repo, store.run_id, 'worker', 'reuse-worker', {
            'provider': 'test', 'control_tool': 'interrupt_agent', 'event_id': 'stopped',
            'handle': 'reuse-worker', 'status': 'interrupted',
            'raw_response': {'handle': 'reuse-worker', 'status': 'interrupted'},
        })

    @staticmethod
    def reuse_request(task):
        return dict(author_id='coordinator', amendment=dict(
            id='TA-reuse', reason='同步原核准成果的必要消費者',
            path_additions=[dict(task_id=task, paths=['src/a.txt'],
                                 reason='完成原規格', check_ids=['C-reuse'])],
            added_checks=[dict(id='C-reuse', phase='task', argv=[sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('src/a.txt').read_text() == 'fixed\\n'"])]))

    def test_current_review_task_reuses_completed_path_and_recovers_archive(self):
        repo, worker, store, _, results, evidence, request = self.fixture()
        store.enter_review_fix('start')
        self.cli(store, ['amend-paths', 'propose'], request, 'new-correction')
        self.cli(store, ['amend-paths', 'review'], self.review(store), 'new-review')
        self.lease(store, 'T-map')
        original = copy.deepcopy(store.load()['tasks']['T-a'])
        package = (repo / store.load()['package_path']).read_bytes()
        old_evidence = Path(evidence[0]['evidence_path']).read_bytes()
        self.stop_worker(repo, store)
        self.cli(store, ['amend-paths', 'propose'], self.reuse_request('T-map'), 'reuse')
        review = self.review(store)
        with mock.patch('cogito_path_amendment.atomic_create_json', side_effect=OSError('archive failed')):
            with self.assertRaises(OSError):
                store.path_amendment_review(review, 'reuse-review')
        self.assertEqual(store.next_action()['next_action'], 'retry-path-amendment')
        events = store.events_path.read_bytes()
        self.cli(store, ['amend-paths', 'review'], review, 'reuse-review')
        self.assertEqual(store.events_path.read_bytes(), events)
        register_external(repo, store.run_id, 'worker', 'resumed-reuse-worker')
        self.assertEqual(store.load()['tasks']['T-a'], original)
        self.assertEqual((repo / store.load()['package_path']).read_bytes(), package)
        self.assertEqual(Path(evidence[0]['evidence_path']).read_bytes(), old_evidence)
        self.assertEqual(RunStore(repo, store.run_id).load(), store.load())
        (worker / 'mapping').mkdir()
        (worker / 'mapping/value.py').write_text('mapped\n')
        (worker / 'src/a.txt').write_text('fixed\n')
        git(worker, 'add', 'src/a.txt', 'mapping/value.py')
        git(worker, 'commit', '-qm', 'fix original finding\n\nCogito-Amendment: TA-map')
        checks = [self.check(store, worker, check, check) for check in ('C-map', 'C-reuse')]
        store.finish_task('T-map', {'risks': []}, 'finish')
        fixed = next(r for r in store.load()['agent_results'] if r['task_id'] == 'T-map')
        store.complete_review_fix('TA-map', fixed['head_commit'], 'complete')
        store.complete_verification(checks)
        verification_tests.AtomicVerificationTests.review(store, [*results, fixed])
        self.assertEqual(store.load()['state'], 'integrating')

    def predecessor_fixture(self):
        def sequential(draft):
            second = copy.deepcopy(draft['slices'][0])
            second['id'] = 'FS-2'
            second['worker'].update(branch='codex/fs-2', worktree='.cogito/worktrees/FS-2',
                                    allowed_paths=['src/b.txt'])
            draft['slices'][0]['worker']['allowed_paths'] = ['src/a.txt']
            draft['slices'].append(second)
            draft['approved_paths'] = ['src/a.txt', 'src/b.txt']
            draft['execution_dag']['tasks'][1]['slice_id'] = 'FS-2'
            # The approved contract intentionally uses edges without depends_on.
            draft['source_registry'] = [dict(path='src/a.txt',
                hash=hashlib.sha256(b'before\n').hexdigest(), relevance='既有產品來源',
                disposition='read-only-source')]
        repo, worker, store, draft = self.executing(sequential)
        first, evidence = self.implement(store, worker)
        store.transition('implementation-complete', {})
        store.complete_verification([evidence])
        verification_tests.AtomicVerificationTests.review(store, [first])
        git(repo, 'merge', '--no-ff', '-qm', 'integrate predecessor', 'codex/fs-1')
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        self.assertEqual(store.load()['state'], 'executing')
        target = repo / '.cogito/worktrees/FS-2'
        git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-2', str(target), 'HEAD')
        self.lease(store, 'T-b')
        self.stop_worker(repo, store)
        return repo, target, store, draft, first, evidence

    def test_predecessor_read_source_cli_replay_and_delivery(self):
        repo, target, store, _, first, evidence = self.predecessor_fixture()
        original = copy.deepcopy(store.load()['tasks']['T-a'])
        package = (repo / store.load()['package_path']).read_bytes()
        old_evidence = Path(evidence['evidence_path']).read_bytes()
        request = self.reuse_request('T-b')
        self.cli(store, ['amend-paths', 'propose'], request, 'reuse')
        pending = store.load()['path_amendment']
        self.assertEqual(pending['predecessor_deliveries'], [dict(
            task_id='T-b', base_commit=git(target, 'rev-parse', 'HEAD'),
            owner_heads=[first['head_commit']])])
        events = store.events_path.read_bytes()
        self.cli(store, ['amend-paths', 'propose'], request, 'reuse')
        self.assertEqual(store.events_path.read_bytes(), events)
        review = self.review(store)
        self.cli(store, ['amend-paths', 'review'], review, 'reuse-review')
        events = store.events_path.read_bytes()
        self.cli(store, ['amend-paths', 'review'], review, 'reuse-review')
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(RunStore(repo, store.run_id).load(), store.load())
        self.assertEqual(store.load()['tasks']['T-a'], original)
        self.assertEqual((repo / store.load()['package_path']).read_bytes(), package)
        self.assertEqual(Path(evidence['evidence_path']).read_bytes(), old_evidence)
        register_external(repo, store.run_id, 'worker', 'resumed-predecessor-worker')
        (target / 'src/a.txt').write_text('fixed\n')
        (target / 'src/b.txt').write_text('after\n')
        self.commit(target)
        checks = [self.check(store, target, check, check) for check in ('C-b', 'C-reuse')]
        store.finish_task('T-b', {'risks': []}, 'finish')
        last = next(r for r in store.load()['agent_results'] if r['task_id'] == 'T-b')
        store.transition('implementation-complete', {})
        store.complete_verification(checks)
        verification_tests.AtomicVerificationTests.review(store, [last])
        git(repo, 'merge', '--no-ff', '-qm', 'integrate successor', 'codex/fs-2')
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-2')
        post = self.check(store, repo, 'C-b', 'post')
        self.assertEqual(store.decide_post_verification([post])['state'], 'finalizing')

    def test_predecessor_proposal_rejects_missing_baseline_ancestry(self):
        _, target, store, draft, _, _ = self.predecessor_fixture()
        # Keep the real event store intact; supply a corrupted lease through
        # the adapter boundary to exercise publication's Git ancestry guard.
        state = store.load()
        state['tasks']['T-b']['base_commit'] = draft['baseline_commit']
        before = store.events_path.read_bytes()
        with mock.patch.object(store, 'load', return_value=state), mock.patch(
                'cogito_path_amendment.working_tree_changed_paths', return_value=set()), mock.patch(
                'cogito_path_amendment.capture_index_and_worktree_trees',
                return_value=(git(target, 'rev-parse', draft['baseline_commit'] + '^{tree}'),) * 2):
            with self.assertRaisesRegex(CogitoError, 'absent from the target lease baseline'):
                store.path_amendment_propose(self.reuse_request('T-b'), 'bad-baseline')
        self.assertEqual(store.events_path.read_bytes(), before)
