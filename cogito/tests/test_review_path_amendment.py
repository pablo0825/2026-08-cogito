"""Review findings can add exact missing files without replacing completed work."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git, COGITO
from cogito_common import CogitoError
from cogito_run_store import RunStore
import test_path_amendment_flow as path_tests
import test_atomic_task_verification as verification_tests


class ReviewPathAmendmentTests(GitTestCase):
    executing = verification_tests.AtomicVerificationTests.executing
    lease = staticmethod(verification_tests.AtomicVerificationTests.lease)
    commit = staticmethod(verification_tests.AtomicVerificationTests.commit)
    check = staticmethod(verification_tests.AtomicVerificationTests.check)
    result = staticmethod(verification_tests.AtomicVerificationTests.result)
    implement = verification_tests.AtomicVerificationTests.implement
    review = staticmethod(path_tests.PathAmendmentFlowTests.review)

    def fixture(self, configure=None):
        repo, worker, store, draft = self.executing(configure)
        first, early = self.implement(store, worker)
        last, latest = self.implement(store, worker, 'b')
        results, evidence = [first, last], [early, latest]
        store.transition('implementation-complete', {})
        store.complete_verification([evidence[-1]])
        store.submit_agent_result({**results[0], 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'status': 'needs-fix', 'changed_paths': [],
            'evidence': [], 'risks': ['Missing approved mapper'], 'requested_transition': 'review-fix'})
        request = dict(author_id='coordinator', amendment=dict(
            id='TA-map', reason='補齊原需求的 mapper',
            added_tasks=[dict(id='T-map', slice_id='FS-1', paths=['mapping/value.py'],
                              responsibility='補齊原需求', check_ids=['C-map'], depends_on=['T-a'])],
            path_additions=[dict(task_id='T-map', paths=['mapping/value.py'],
                                 reason='原核准欄位缺漏', check_ids=['C-map'])],
            added_checks=[dict(id='C-map', phase='task', argv=[sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('mapping/value.py').read_text() == 'mapped\\n'"])]))
        return repo, worker, store, draft, results, evidence, request

    def cli(self, store, command, payload, action):
        path = store.run_dir / 'input.json'
        path.write_text(json.dumps(payload))
        result = subprocess.run([sys.executable, str(COGITO/'scripts/cogito_gate.py'),
            '--repo', str(store.root), *command, '--run-id', store.run_id,
            '--input', str(path), '--action-id', action], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cli_same_run_correction_preserves_history_and_related_checks(self):
        repo, worker, store, draft, results, evidence, request = self.fixture()
        original_tasks = copy.deepcopy(store.load()['tasks'])
        original_package = (repo / store.load()['package_path']).read_bytes()
        original_evidence = {e['evidence_path']: Path(e['evidence_path']).read_bytes() for e in evidence}
        finding = store.next_action()['operations'][0]['input']
        self.cli(store, ['review-fix-start'], finding, 'start')
        self.cli(store, ['amend-paths', 'propose'], request, 'propose')
        self.assertEqual(store.next_action()['next_action'], 'review-path-amendment')
        review = {**self.review(store), 'reviewer_id': 'reviewer'}
        self.cli(store, ['amend-paths', 'review'], review, 'apply')
        before = store.events_path.read_bytes()
        self.cli(store, ['amend-paths', 'review'], review, 'apply')
        self.assertEqual(store.events_path.read_bytes(), before)
        for task_id, task in original_tasks.items():
            self.assertEqual(store.load()['tasks'][task_id], task)
        self.assertEqual((repo / store.load()['package_path']).read_bytes(), original_package)
        self.assertEqual(RunStore(repo, store.run_id).load(), store.load())
        self.lease(store, 'T-map')
        (worker/'mapping').mkdir()
        (worker/'mapping/value.py').write_text('mapped\n')
        git(worker, 'add', 'mapping/value.py')
        git(worker, 'commit', '-qm', 'fix mapper\n\nCogito-Amendment: TA-map')
        related = self.check(store, worker, 'C-map', 'map-check')
        store.finish_task('T-map', {'risks': []}, 'finish-map')
        fixed = [r for r in store.load()['agent_results'] if r['task_id'] == 'T-map'][0]
        store.complete_review_fix('TA-map', fixed['head_commit'], 'complete-fix')
        count = len(store.load()['evidence'])
        store.complete_verification([related])
        verification_tests.AtomicVerificationTests.review(store, [*results, fixed])
        self.assertEqual(len(store.load()['evidence']), count)
        git(repo, 'merge', '--no-ff', '-qm', 'integrate', draft['slices'][0]['worker']['branch'])
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        post = self.check(store, repo, 'C-b', 'post')
        store.decide_post_verification([post])
        self.assertEqual(store.load()['state'], 'finalizing')
        self.assertEqual([e['check_id'] for e in store.load()['evidence'].values()],
                         ['C-a', 'C-b', 'C-map', 'C-b'])
        for path, content in original_evidence.items():
            self.assertEqual(Path(path).read_bytes(), content)
        graph_path = repo/'docs/cogito/project-graph.json'
        graph = json.loads(graph_path.read_text())
        graph['active_run_id'] = None
        graph['slices']['FS-1'].update(disposition='accepted', completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        relative = f'docs/cogito/results/{store.run_id}.json'
        destination = repo/relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = store.load()
        destination.write_text(json.dumps(dict(schema_version='3.0', run_id=store.run_id, status='accepted',
            package_hash=current['package_hash'], effective_contract_hash=current['effective_contract_hash'],
            integration_commits=[git(repo, 'rev-parse', 'HEAD')], slice_dispositions={'FS-1': 'accepted'},
            checks=[dict(id='C-b', status='passed', evidence=post['evidence_path'])],
            reviews=[dict(reviewer='reviewer')], amendments=[dict(id='TA-map', proposal_hash=review['proposal_hash'])],
            human_gate=dict(required=False, outcome='not-required'), remaining_risks=[])))
        git(repo, 'add', relative, 'docs/cogito/project-graph.json')
        git(repo, 'commit', '-qm', 'record delivery')
        store.finalize(relative, 'docs/cogito/project-graph.json', git(repo, 'rev-parse', 'HEAD'))
        self.assertEqual(store.load()['state'], 'accepted')

    def test_state_completed_task_and_premature_edits_are_rejected(self):
        _, worker, store, _, _, _, request = self.fixture()
        with self.assertRaisesRegex(CogitoError, 'review-fix'):
            store.path_amendment_propose(request, 'too-early')
        store.enter_review_fix('start')
        original = store.events_path.read_bytes()
        bad = copy.deepcopy(request)
        bad['amendment'].pop('added_tasks')
        bad['amendment']['path_additions'][0]['task_id'] = 'T-a'
        with self.assertRaisesRegex(CogitoError, 'new correction tasks'):
            store.path_amendment_propose(bad, 'old-task')
        (worker/'mapping').mkdir()
        (worker/'mapping/value.py').write_text('unauthorized')
        with self.assertRaisesRegex(CogitoError, 'outside'):
            store.path_amendment_propose(request, 'premature')
        self.assertEqual(store.events_path.read_bytes(), original)

    def test_pending_independence_drift_and_archive_recovery(self):
        _, worker, store, _, _, _, request = self.fixture()
        store.enter_review_fix('start')
        store.path_amendment_propose(request, 'propose')
        review = self.review(store)
        for identity in ('coordinator', 'worker'):
            with self.assertRaisesRegex(CogitoError, 'independent'):
                store.path_amendment_review({**review, 'reviewer_id': identity}, 'bad')
        with self.assertRaisesRegex(CogitoError, 'pending'):
            self.check(store, worker, 'C-b', 'fenced')
        # A harmless Git head change still invalidates the reviewed snapshot.
        git(worker, 'commit', '--allow-empty', '-qm', 'unreviewed head')
        with self.assertRaises(CogitoError):
            store.path_amendment_review(review, 'drifted')
        git(worker, 'reset', '--hard', 'HEAD~1')
        with mock.patch('cogito_path_amendment.atomic_create_json', side_effect=OSError('archive failed')):
            with self.assertRaises(OSError):
                store.path_amendment_review(review, 'apply')
        self.assertEqual(store.next_action()['next_action'], 'retry-path-amendment')
        before = store.events_path.read_bytes()
        store.path_amendment_review(review, 'apply')
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual(list(store.load()['tasks']).count('T-map'), 1)

    def test_withdraw_does_not_publish_task_or_authorization(self):
        _, _, store, _, _, _, request = self.fixture()
        store.enter_review_fix('start')
        store.path_amendment_propose(request, 'propose')
        store.path_amendment_withdraw(dict(proposal_hash=self.review(store)['proposal_hash'], reason='revise'), 'withdraw')
        self.assertNotIn('T-map', store.load()['tasks'])
        self.assertNotIn('mapping/value.py', store.effective_package()['approved_paths'])
        self.assertEqual(store.load()['state'], 'review-fix')

    def test_malformed_finding_does_not_start_correction(self):
        _, _, store, _, _, _, _ = self.fixture()
        before = store.events_path.read_bytes()
        for reference in ({}, [], {'event_sequence': True, 'event_hash': 'a'},
                          {'event_sequence': 1, 'event_hash': '0' * 64}):
            with self.subTest(reference=reference), self.assertRaises(CogitoError):
                store.enter_review_fix('bad-finding', finding_reference=reference)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_other_slice_cannot_use_this_finding_for_path_expansion(self):
        def second_slice(draft):
            other = copy.deepcopy(draft['slices'][0])
            other['id'] = 'FS-2'
            other['worker'].update(branch='codex/fs-2', worktree='.cogito/worktrees/FS-2',
                                   allowed_paths=['other/original.py'])
            draft['slices'].append(other)
            draft['approved_paths'].append('other/original.py')
        _, _, store, _, _, _, request = self.fixture(second_slice)
        store.enter_review_fix('start')
        task = request['amendment']['added_tasks'][0]
        task.update(slice_id='FS-2', depends_on=[])
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'finding Slice'):
            store.path_amendment_propose(request, 'other-slice')
        self.assertEqual(store.events_path.read_bytes(), before)
