"""Same-run scope repair preserves atomic history and requires fresh review/evidence."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git, COGITO
from cogito_common import CogitoError
from cogito_execution_registry import register_external, record_external_receipt
from cogito_path_amendment_state import ASSESSMENTS
from cogito_run_store import RunStore
import test_atomic_task_execution as execution
import test_atomic_task_verification as verification


class PathAmendmentFlowTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    commit = staticmethod(execution.AtomicTaskTests.commit)
    check = staticmethod(execution.AtomicTaskTests.check)
    result = staticmethod(execution.AtomicTaskTests.result)
    implement = execution.AtomicTaskTests.implement

    def fixture(self):
        repo, worker, store, draft = self.executing()
        first, old = self.implement(store, worker)
        self.lease(store, 'T-b')
        (worker / 'src/b.txt').write_text('after\n')
        register_external(repo, store.run_id, 'worker', 'worker-handle')
        receipt = dict(provider='test', control_tool='interrupt_agent', event_id='stopped',
                       handle='worker-handle', status='interrupted',
                       raw_response=dict(handle='worker-handle', status='interrupted'))
        record_external_receipt(repo, store.run_id, 'worker', 'worker-handle', receipt)
        request = dict(author_id='coordinator', amendment=dict(id='TA-path', reason='漏列必要 mapper 與測試',
            path_additions=[dict(task_id='T-b', paths=['mapping/value.py'], reason='完成原定輸出',
                                 check_ids=['C-map'])],
            added_checks=[dict(id='C-map', phase='task', argv=[sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('mapping/value.py').read_text() == 'mapped\\n'"])]))
        return repo, worker, store, draft, first, old, request

    @staticmethod
    def review(store):
        pending = store.load()['path_amendment']
        return dict(proposal_hash=pending['proposal_hash'], reviewer_id='scope-reviewer', decision='within-approved-scope',
                    assessment={key:'確認符合核准規格，檢查涵蓋新增 mapper' for key in ASSESSMENTS}, findings=[])

    def apply(self, store, request):
        store.path_amendment_propose(request, 'propose-path')
        return store.path_amendment_review(self.review(store), 'review-path')

    def test_real_cli_repair_preserves_first_task_and_finalizes(self):
        repo, worker, store, draft, first, old, request = self.fixture()
        frozen = Path(store.load()['package_path'])
        if not frozen.is_absolute(): frozen = repo / frozen
        before_package = frozen.read_bytes()
        old_bytes = Path(old['evidence_path']).read_bytes()
        old_task = copy.deepcopy(store.load()['tasks']['T-a'])
        def cli(operation, payload, action):
            path = store.run_dir / 'input.json'
            path.write_text(json.dumps(payload))
            result = subprocess.run([sys.executable, str(COGITO/'scripts/cogito_gate.py'), '--repo', str(repo),
                'amend-paths', operation, '--run-id', store.run_id, '--input', str(path), '--action-id', action],
                text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)['data']
        cli('propose', request, 'propose-path')
        self.assertEqual(store.next_action()['next_action'], 'review-path-amendment')
        review = self.review(store)
        cli('review', review, 'review-path')
        self.assertEqual(store.load()['tasks']['T-a'], old_task)
        self.assertEqual(frozen.read_bytes(), before_package)
        self.assertEqual(Path(old['evidence_path']).read_bytes(), old_bytes)
        self.assertIn('mapping/value.py', store.effective_package()['approved_paths'])
        (worker / 'mapping').mkdir()
        (worker / 'mapping/value.py').write_text('mapped\n')
        git(worker, 'add', 'src/b.txt', 'mapping/value.py')
        git(worker, 'commit', '-qm', 'implement query mapper')
        eb = self.check(store, worker, 'C-b', 'after-b')
        em = self.check(store, worker, 'C-map', 'after-map')
        last = self.result(store, worker, [eb, em], 'T-b')
        store.submit_agent_result(last, 'result-b')
        store.update_task('T-b', 'complete', 'worker', 'complete-b')
        store.transition('implementation-complete', {})
        store.complete_verification([eb])
        verification.AtomicVerificationTests.review(store, [first, last])
        git(repo, 'merge', '--no-ff', '-qm', 'integrate repaired tasks', draft['slices'][0]['worker']['branch'])
        integration = git(repo, 'rev-parse', 'HEAD')
        store.complete_integration(integration, 'FS-1')
        post = self.check(store, repo, 'C-b', 'post')
        store.decide_post_verification([post])
        graph_path = repo/'docs/cogito/project-graph.json'
        graph = json.loads(graph_path.read_text());graph['active_run_id'] = None
        graph['slices']['FS-1'].update(disposition='accepted', completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        relative = f'docs/cogito/results/{store.run_id}.json'
        path = repo/relative;path.parent.mkdir(parents=True, exist_ok=True)
        current = store.load()
        path.write_text(json.dumps(dict(schema_version='3.0', run_id=store.run_id, status='accepted',
            package_hash=current['package_hash'], effective_contract_hash=current['effective_contract_hash'],
            integration_commits=[integration], slice_dispositions={'FS-1':'accepted'},
            checks=[dict(id='C-b', status='passed', evidence=post['evidence_path'])],
            reviews=[dict(reviewer='reviewer')], amendments=[dict(id='TA-path', proposal_hash=review['proposal_hash'])],
            human_gate=dict(required=False, outcome='not-required'), remaining_risks=[])))
        git(repo, 'add', relative, 'docs/cogito/project-graph.json');git(repo, 'commit', '-qm', 'finalize')
        store.finalize(relative, 'docs/cogito/project-graph.json', git(repo, 'rev-parse', 'HEAD'), 'finalize')
        self.assertEqual(store.load()['state'], 'accepted')
        self.assertEqual(store.completion_report()['amendments'], [dict(id='TA-path', proposal_hash=review['proposal_hash'])])

    def test_review_must_be_independent_current_and_replayable(self):
        _, worker, store, _, _, _, request = self.fixture()
        with self.assertRaisesRegex(CogitoError, 'amend-paths'):
            store.add_amendment(request['amendment'])
        store.path_amendment_propose(request, 'propose')
        review = self.review(store)
        for field, value in [('reviewer_id','coordinator'), ('reviewer_id','worker'), ('proposal_hash','0'*64), ('findings',['unresolved'])]:
            with self.subTest(field=field, value=value), self.assertRaises(CogitoError):
                store.path_amendment_review({**review, field:value}, 'bad-review')
        with self.assertRaisesRegex(CogitoError, 'pending'):
            store.run_controlled_check('C-b', worker, 'fenced')
        with self.assertRaisesRegex(CogitoError, 'pending'):
            register_external(store.root, store.run_id, 'worker', 'resumed')
        (worker/'src/b.txt').write_text('changed after proposal\n')
        with self.assertRaisesRegex(CogitoError, 'inputs changed'):
            store.path_amendment_review(review, 'stale')
        store.path_amendment_propose(request, 'propose-again')
        updated = self.review(store)
        with self.assertRaises(CogitoError): store.path_amendment_review(review, 'old')
        store.path_amendment_review(updated, 'apply')
        events = store.events_path.read_bytes()
        register_external(store.root, store.run_id, 'worker', 'new-handle')
        store.path_amendment_review(updated, 'apply')
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(RunStore(store.root,store.run_id).load(), store.load())

    def test_live_worker_and_premature_out_of_scope_edits_rejected(self):
        _, worker, store, _, _, _, request = self.fixture()
        (worker/'mapping').mkdir();(worker/'mapping/value.py').write_text('too early')
        with self.assertRaisesRegex(CogitoError, 'outside'):
            store.path_amendment_propose(request, 'early')
        (worker/'mapping/value.py').unlink();(worker/'mapping').rmdir()
        registry = store.run_dir/'execution-registry.json'
        data = json.loads(registry.read_text());data['entries']['worker']['receipt'] = None
        registry.write_text(json.dumps(data))
        with self.assertRaisesRegex(CogitoError, 'must have stopped'):
            store.path_amendment_propose(request, 'live')

    def test_withdraw_restores_original_authorization(self):
        _, _, store, _, _, _, request = self.fixture()
        store.path_amendment_propose(request, 'propose')
        withdrawal = dict(proposal_hash=store.load()['path_amendment']['proposal_hash'], reason='補正不適用')
        store.path_amendment_withdraw(withdrawal, 'withdraw')
        self.assertNotIn('mapping/value.py', store.effective_package()['approved_paths'])
        self.assertNotIn('path_amendment', store.load())
        store.path_amendment_withdraw(withdrawal, 'withdraw')
        register_external(store.root, store.run_id, 'worker', 'after-withdraw')

    def test_completed_task_and_directory_grants_are_rejected(self):
        _, worker, store, _, _, _, request = self.fixture()
        bad = copy.deepcopy(request);bad['amendment']['path_additions'][0]['task_id'] = 'T-a'
        with self.assertRaisesRegex(CogitoError, 'completed'):
            store.path_amendment_propose(bad, 'completed')
        self.apply(store, request)
        (worker/'mapping/value.py').mkdir(parents=True)
        (worker/'mapping/value.py/extra').write_text('not an exact file')
        with self.assertRaisesRegex(CogitoError, 'exact files'):
            store._require_atomic_clean(worker, git(worker,'rev-parse','HEAD'), store.load())

    def test_review_event_survives_executor_archive_failure(self):
        _, _, store, _, _, _, request = self.fixture()
        store.path_amendment_propose(request, 'propose')
        review = self.review(store)
        with mock.patch('cogito_path_amendment.atomic_create_json', side_effect=OSError('archive unavailable')):
            with self.assertRaises(OSError):
                store.path_amendment_review(review, 'apply')
        self.assertNotIn('path_amendment', store.load())
        self.assertEqual(store.next_action()['next_action'], 'retry-path-amendment')
        self.assertEqual(store.next_action()['action_id'], 'apply')
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'pending'):
            register_external(store.root, store.run_id, 'worker', 'unsafe-resume')
        store.path_amendment_review(review, 'apply')
        self.assertEqual(store.events_path.read_bytes(), before)
        register_external(store.root, store.run_id, 'worker', 'safe-resume')

    def test_old_contract_check_cannot_complete_amended_task(self):
        _, worker, store, _, _, _, request = self.fixture()
        old_check = self.check(store, worker, 'C-b', 'old-b')
        self.apply(store, request)
        (worker/'mapping').mkdir();(worker/'mapping/value.py').write_text('mapped\n')
        git(worker,'add','src/b.txt','mapping/value.py');git(worker,'commit','-qm','mapper')
        fresh = self.check(store, worker, 'C-map', 'new-map')
        with self.assertRaises(CogitoError):
            store.submit_agent_result(self.result(store, worker, [old_check, fresh], 'T-b'))

    def test_proposal_and_withdraw_replay_after_append_failure(self):
        _, _, store, _, _, _, request = self.fixture()
        from cogito_event_repository import EventRepository
        append = EventRepository.append
        def fail_after_append(repository, *args, **kwargs):
            value = append(repository, *args, **kwargs)
            raise OSError('response lost after append')
        with mock.patch.object(EventRepository, 'append', fail_after_append):
            with self.assertRaises(OSError):
                store.path_amendment_propose(request, 'propose')
        events = store.events_path.read_bytes()
        store.path_amendment_propose(request, 'propose')
        self.assertEqual(store.events_path.read_bytes(), events)
        withdrawal = dict(proposal_hash=store.load()['path_amendment']['proposal_hash'], reason='撤回')
        with mock.patch('cogito_path_amendment.atomic_create_json', side_effect=OSError('archive unavailable')):
            with self.assertRaises(OSError):
                store.path_amendment_withdraw(withdrawal, 'withdraw')
        with self.assertRaises(CogitoError):
            register_external(store.root, store.run_id, 'worker', 'too-soon')
        store.path_amendment_withdraw(withdrawal, 'withdraw')
        register_external(store.root, store.run_id, 'worker', 'resumed')
