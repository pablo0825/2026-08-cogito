"""Execute generated argv and preserve query/recovery safety boundaries."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
import test_atomic_task_verification as verification
import test_cleanup_finalization as finalization
import test_check_retry as retry
import test_action_replay as replay


class NextOperationTests(GitTestCase):
    def test_optional_only_checks_explain_the_missing_selection(self):
        from cogito_next_operations import verification_hints
        package = {'task_delivery': 'atomic', 'checks': [{'id': 'C-optional', 'required': False}]}
        state = {'state': 'post-integration-verification', 'tasks': {}}
        store = SimpleNamespace(root=Path('/unused'), _events=SimpleNamespace(snapshot=lambda: None),
            _approved_package_from_state=lambda state: package, effective_package=lambda: package)
        output = verification_hints(store, state)
        self.assertEqual(output['operations'], [])
        self.assertIn('optional_check_selection_required', output['blockers'][0])

    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def invoke(self, operation, action='next-action'):
        argv = [action if arg == '<new-action-id>' else arg for arg in operation['argv']]
        result = subprocess.run(argv, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_atomic_precommit_wave_next_argv_and_query_objects_are_unchanged(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        repo, worker, store, _, _, evidence = fixture.wave(precommit=True)
        objects = repo / '.git/objects'
        before = {str(p): p.read_bytes() for p in objects.rglob('*') if p.is_file()}
        events = store.events_path.read_bytes()
        index = Path(git(worker, 'rev-parse', '--git-path', 'index'))
        staging = index.read_bytes()
        output = store.next_action()
        self.assertEqual(output['eligible_evidence'], [evidence[-1]['evidence_path']])
        self.assertEqual(output['next_action'], 'submit-verification')
        self.assertEqual(before, {str(p): p.read_bytes() for p in objects.rglob('*') if p.is_file()})
        self.assertEqual(index.read_bytes(), staging)
        self.assertEqual(store.events_path.read_bytes(), events)
        self.invoke(output['operations'][0])
        self.assertEqual(store.load()['state'], 'reviewing')

    def test_newer_failed_check_does_not_fall_back(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        _, worker, store, _, _, _ = fixture.wave()
        (worker / 'src/b.txt').write_text('wrong\n')
        store.run_controlled_check('C-b', worker, 'failed-latest')
        (worker / 'src/b.txt').write_text('after\n')
        output = store.next_action()
        self.assertTrue(output['stale_checks'])
        self.assertNotIn('verify', [op['operation'] for op in output['operations']])

    def test_nonatomic_missing_then_next_argv_verifies(self):
        fixture = self.fixture(replay.ActionReplayTests)
        output = fixture.store.next_action()
        self.assertEqual(output['missing_checks'][0]['check_id'], 'C-1')
        self.invoke(output['operations'][0], 'from-next-check')
        output = fixture.store.next_action()
        self.assertEqual(output['operations'][0]['operation'], 'verify')
        self.invoke(output['operations'][0], 'from-next-verify')

    def test_same_check_on_two_worktrees_is_not_deduplicated_and_nonff_is_explicit(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        def parallel(draft):
            second = copy.deepcopy(draft['slices'][0])
            second['id'] = 'FS-2'
            second['worker'].update(branch='codex/fs-2', worktree='.cogito/worktrees/FS-2')
            draft['slices'].append(second)
            draft['execution_dag']['tasks'][1]['slice_id'] = 'FS-2'
            draft['execution_dag']['edges'] = []
            for task in draft['execution_dag']['tasks']:
                task['check_ids'] = ['C-shared']
            draft['checks'] = [{'id': 'C-shared', 'phase': 'integration',
                                'argv': [sys.executable, '-I', '-c', 'pass']}]
        repo, first, store, draft = fixture.executing(parallel)
        second = repo / '.cogito/worktrees/FS-2'
        git(repo, 'worktree', 'add', '-qb', 'codex/fs-2', str(second), draft['baseline_commit'])
        for name, worker in (('a', first), ('b', second)):
            fixture.lease(store, 'T-' + name)
            (worker / f'src/{name}.txt').write_text('after\n')
            fixture.commit(worker)
            store.run_controlled_check('C-shared', worker, 'check-' + name)
            store.finish_task('T-' + name, {'risks': []}, 'finish-' + name)
        store.transition('implementation-complete', {})
        output = store.next_action()
        self.assertEqual(len(output['eligible_evidence']), 2)
        self.invoke(output['operations'][0])
        fixture.review(store, [r for r in store.load()['agent_results'] if r['role'] == 'implementer'])
        choice = store.next_action()['integration_choices'][0]
        for operation in choice['operations']:
            self.invoke(operation, 'first-integration')
        choice = store.next_action()['integration_choices'][0]
        self.assertEqual(choice['operations'], [])
        self.assertIn('non_fast_forward', choice['blockers'][0])

    def test_post_head_drift_reports_stale_check_and_rerun_not_closure(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        repo, _, store, _, _, _, _ = fixture.integrated()
        fixture.check(store, repo, 'C-b', 'post-before-drift')
        hint = store.next_action()['operations'][0]
        git(repo, 'commit', '--allow-empty', '-qm', 'later delivery')
        output = store.next_action()
        self.assertEqual(output['stale_checks'][0]['check_id'], 'C-b')
        self.assertEqual(output['operations'][0]['operation'], 'run-check')
        command = [arg if arg != '<new-action-id>' else 'stale-hint' for arg in hint['argv']]
        result = subprocess.run(command, cwd=hint['cwd'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 2)

    def test_unstarted_old_request_does_not_hide_valid_verification(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        _, worker, store, _, _, _ = fixture.wave()
        from cogito_actions import controlled_check_attempt, request_fingerprint
        fingerprint = request_fingerprint('run-check', check_id='C-a', worktree=str(worker.resolve()))
        with controlled_check_attempt(store.run_dir, 'abandoned-preflight', fingerprint):
            pass
        output = store.next_action()
        self.assertEqual(output['operations'][0]['operation'], 'verify')

    def test_legal_retry_and_unknown_recovery_are_distinct(self):
        fixture = self.fixture(retry.CheckRetryTests)
        _, worker, store = fixture.ready()
        fixture.preparation_failure(store, worker)
        output = store.next_action()
        self.assertEqual(output['check_recovery'][0]['category'], 'proven_pre_execution_failure')
        self.assertEqual(output['operations'][0]['operation'], 'retry')
        fixture.retry(store)
        output = store.next_action()
        self.assertEqual(output['operations'][0]['argv'][-1], 'replacement')
        with patch('cogito_runner.run_check', side_effect=CogitoError('interrupted')):
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-a', worker, 'replacement')
        output = store.next_action()
        self.assertEqual(output['operations'], [])

    def test_fast_forward_hints_are_executable_then_post_checks(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        repo, _, store, _, results, evidence = fixture.wave()
        store.complete_verification([evidence[-1]])
        fixture.review(store, results)
        output = store.next_action()
        choice = output['integration_choices'][0]
        self.assertNotIn('blockers', choice, choice)
        self.assertEqual(choice['mode'], 'fast-forward')
        for operation in choice['operations']:
            self.invoke(operation, 'integrate-next')
        self.assertEqual(git(repo, 'rev-parse', 'HEAD'), choice['expected_head'])
        output = store.next_action()
        self.assertEqual((output['missing_checks'] + output['stale_checks'])[0]['check_id'], 'C-b')
        self.invoke(output['operations'][0], 'post-check-next')
        output = store.next_action()
        self.assertEqual(output['operations'][0]['operation'], 'post-verify')
        self.assertEqual(output['next_action'], 'submit-post-verification')
        self.invoke(output['operations'][0], 'post-verify-next')
        self.assertEqual(store.load()['state'], 'finalizing')

    def test_post_hint_reuses_exact_content_equivalent_worker_evidence(self):
        fixture = self.fixture(verification.AtomicVerificationTests)
        repo, worker, store, _ = fixture.executing()
        graph = 'docs/cogito/project-graph.json'
        (worker / graph).parent.mkdir(parents=True, exist_ok=True)
        (worker / graph).write_bytes((repo / graph).read_bytes())
        first, _ = fixture.implement(store, worker)
        last, evidence = fixture.implement(store, worker, 'b')
        store.transition('implementation-complete', {})
        self.invoke(store.next_action()['operations'][0], 'verify-reuse')
        fixture.review(store, [first, last])
        for operation in store.next_action()['integration_choices'][0]['operations']:
            self.invoke(operation, 'integrate-reuse')
        output = store.next_action()
        self.assertEqual(output['eligible_evidence'], [evidence['evidence_path']])
        self.invoke(output['operations'][0], 'post-reuse')
        self.assertEqual(len(store.load()['evidence']), 2)

    def test_accepted_observation_does_not_remove_or_publish_and_apply_rechecks(self):
        fixture = self.fixture(finalization.CleanupFinalizationTests)
        repo, worker, store, args = fixture.finalizing()
        with patch('cogito_cleanup.cleanup_accepted', return_value={'removed': [], 'retained': []}):
            store.finalize(*args)
        registry_lock = store.run_dir / 'execution-registry.lock'
        if registry_lock.exists():
            registry_lock.unlink()
        before_refs = git(repo, 'for-each-ref', 'refs/cogito/cleanup')
        output = store.next_action()
        self.assertEqual(output['cleanup']['removable'], [str(worker)])
        self.assertFalse((store.run_dir / 'cleanup.json').exists())
        self.assertFalse(registry_lock.exists())
        self.assertEqual(git(repo, 'for-each-ref', 'refs/cogito/cleanup'), before_refs)
        self.assertTrue(worker.exists())
        (worker / 'secret.txt').write_text('do not delete')
        self.invoke(output['operations'][0])
        self.assertTrue((worker / 'secret.txt').exists())
        self.assertTrue(store.next_action()['cleanup']['retained'])
        (worker / 'secret.txt').unlink()
        self.invoke(store.next_action()['operations'][0])
        self.assertFalse(worker.exists())

    def test_finalize_hint_requires_exact_original_fingerprint(self):
        from cogito_next_operations import accepted_hints
        fixture = self.fixture(finalization.CleanupFinalizationTests)
        _, _, store, args = fixture.finalizing()
        store.finalize(*args)
        events = copy.deepcopy(store._events.read())
        events[-1].pop('request_hash', None)
        with patch.object(store._events, 'read', return_value=events):
            output = accepted_hints(store, store.load())
        self.assertNotIn('operations', output)
        self.assertIn('fingerprint', output['blockers'][0])
