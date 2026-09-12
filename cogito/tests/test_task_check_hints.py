"""Missing Task checks get executable hints without turning blockers into reruns."""
import copy
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
import test_atomic_task_execution as execution


class TaskCheckHintTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    check = staticmethod(execution.AtomicTaskTests.check)
    commit = staticmethod(execution.AtomicTaskTests.commit)

    def invoke(self, operation):
        command = ['from-hint' if arg == '<new-action-id>' else arg for arg in operation['argv']]
        process = subprocess.run(command, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_missing_command_runs_then_commit_blocker_then_finish(self):
        repo, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        git(worker, 'add', 'src/a.txt')
        events = store.events_path.read_bytes()
        index = Path(git(worker, 'rev-parse', '--git-path', 'index'))
        before_index = index.read_bytes()
        before_objects = {str(p): p.read_bytes() for p in (repo / '.git/objects').rglob('*') if p.is_file()}
        operation, = store.next_action()['operations']
        self.assertEqual(operation['operation'], 'run-check')
        self.assertIn(str(worker.resolve()), operation['argv'])
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(index.read_bytes(), before_index)
        self.assertEqual(before_objects, {str(p): p.read_bytes() for p in (repo / '.git/objects').rglob('*') if p.is_file()})
        self.invoke(operation)
        hint, = store.next_action()['operations']
        self.assertEqual(hint['operation'], 'task-finish')
        self.assertIn('commit', hint['blockers'][0])
        self.assertNotIn('check_evidence', hint)
        self.commit(worker)
        hint, = store.next_action()['operations']
        self.assertNotIn('blockers', hint)
        self.assertNotIn('check_evidence', hint)
        store.finish_task('T-a', {'risks': []}, 'finish-after-check')
        self.assertEqual(store.load()['tasks']['T-a']['status'], 'complete')

    def test_failed_stale_and_tampered_evidence_do_not_become_missing(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        failed = self.check(store, worker)
        self.assertFalse(failed['passed'])
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        self.assert_no_rerun(store)
        passed = self.check(store, worker, action='passed')
        self.assertTrue(passed['passed'])
        (worker / 'src/a.txt').write_text('changed after check\n')
        self.assert_no_rerun(store)
        self.assertNotIn('check_evidence', store.next_action()['operations'][0])
        latest = self.check(store, worker, action='newer-failed')
        (worker / 'src/a.txt').write_text('after\n')
        self.assert_no_rerun(store)
        row, = store.next_action()['operations'][0]['check_evidence']
        self.assertEqual(row['evidence_path'], latest['evidence_path'])
        self.assertEqual(row['recorded_status'], 'failed')
        path = Path(latest['evidence_path'])
        path.chmod(0o600)
        path.write_text('{}')
        self.assert_no_rerun(store)
        self.assertNotIn('check_evidence', store.next_action()['operations'][0])

    def test_failed_record_has_readable_pointer_without_output_or_state_changes(self):
        repo, worker, store, _ = self.executing()
        self.lease(store)
        failed = self.check(store, worker)
        events = store.events_path.read_bytes()
        index = Path(git(worker, 'rev-parse', '--git-path', 'index'))
        index_bytes = index.read_bytes()
        objects = {str(p): p.read_bytes() for p in (repo / '.git/objects').rglob('*') if p.is_file()}
        hint, = store.next_action()['operations']
        self.assertIn('evidence binding failed for C-a', hint['blockers'][0])
        row, = hint['check_evidence']
        self.assertEqual(row['check_id'], 'C-a')
        self.assertEqual(row['evidence_path'], failed['evidence_path'])
        self.assertEqual(row['recorded_status'], 'failed')
        self.assertIn('stdout/stderr', row['note'])
        self.assertNotIn('stdout', row)
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(index.read_bytes(), index_bytes)
        self.assertEqual(objects, {str(p): p.read_bytes() for p in (repo / '.git/objects').rglob('*') if p.is_file()})
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'reject-failed')
        original = {'operation': 'run-check', 'argv': ['original-recovery-action']}
        with patch('cogito_next_operations.check_recovery_hints', return_value={
                'check_recovery': [{'category': 'unknown_outcome'}], 'operations': [original]}):
            self.assertEqual(store.next_action()['operations'], [original])

    def test_mixed_results_are_not_all_classified_as_failed(self):
        def configure(draft):
            draft['execution_dag']['tasks'][0]['check_ids'] = ['C-a', 'C-b']
        _, worker, store, _ = self.executing(configure)
        self.lease(store)
        (worker / 'src/b.txt').write_text('after\n')
        self.check(store, worker, 'C-a', 'failed-a')
        self.check(store, worker, 'C-b', 'passed-b')
        hint, = store.next_action()['operations']
        rows = {r['check_id']: r for r in hint['check_evidence']}
        self.assertEqual(rows['C-a']['recorded_status'], 'failed')
        self.assertEqual(rows['C-b']['recorded_status'], 'passed')
        self.assertIn('does not establish current validity', rows['C-b']['note'])

    def test_content_mismatch_points_only_to_old_content_and_preserves_finish_guard(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        passed = self.check(store, worker)
        (worker / 'src/a.txt').write_text('new content\n')
        self.commit(worker)
        hint, = store.next_action()['operations']
        self.assertIn('do not match current checkout content', hint['blockers'][0])
        row, = hint['check_evidence']
        self.assertEqual(row['evidence_path'], passed['evidence_path'])
        self.assertEqual(row['recorded_status'], 'passed')
        self.assertIn('different checkout content', row['note'])
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'reject-stale')

    def assert_no_rerun(self, store):
        hints = store.next_action()['operations']
        self.assertFalse(any(o['operation'] == 'run-check' for o in hints))
        self.assertTrue(hints[0]['blockers'])

    def test_same_check_id_on_other_checkout_does_not_satisfy_missing_check(self):
        def parallel(draft):
            second = copy.deepcopy(draft['slices'][0])
            second['id'] = 'FS-2'
            second['worker'].update(branch='codex/fs-2', worktree='.cogito/worktrees/FS-2')
            draft['slices'].append(second)
            draft['execution_dag']['edges'] = []
            draft['execution_dag']['tasks'][1]['slice_id'] = 'FS-2'
            draft['checks'] = [check for check in draft['checks'] if check['phase'] == 'integration'] + [
                {'id': 'C-shared', 'phase': 'task', 'argv': [sys.executable, '-I', '-c', 'pass']}]
            for task in draft['execution_dag']['tasks']:
                task['check_ids'] = ['C-shared']
        repo, first, store, draft = self.executing(parallel)
        second = repo / '.cogito/worktrees/FS-2'
        git(repo, 'worktree', 'add', '-qb', 'codex/fs-2', str(second), draft['baseline_commit'])
        self.lease(store, 'T-a')
        self.lease(store, 'T-b')
        self.check(store, first, 'C-shared', 'first-only')
        operations = [o for o in store.next_action()['operations'] if o['operation'] == 'run-check']
        self.assertEqual(len(operations), 1)
        self.assertEqual(operations[0]['task_id'], 'T-b')
        self.assertIn(str(second.resolve()), operations[0]['argv'])

    def test_recovery_overrides_missing_commands_and_preserves_original_action(self):
        _, _, store, _ = self.executing()
        self.lease(store)
        original = {'operation': 'run-check', 'argv': ['original-recovery-action']}
        for category in ('published_evidence', 'bound_replacement', 'unknown_outcome', 'scope_too_large'):
            with self.subTest(category=category), patch('cogito_next_operations.check_recovery_hints',
                    return_value={'check_recovery': [{'category': category}], 'operations': [original]}):
                out = store.next_action()
                self.assertEqual(out['next_action'], 'resolve-check-recovery')
                self.assertEqual(out['operations'], [original])
        with patch('cogito_next_operations.check_recovery_hints', side_effect=OSError('unreadable registry')):
            out = store.next_action()
            self.assertEqual(out['operations'], [])
            self.assertEqual(out['next_action'], 'resolve-check-recovery')
        with patch('cogito_next_operations.check_recovery_hints',
                return_value={'check_recovery': [{'category': 'not_started'}], 'operations': [original]}):
            out = store.next_action()
            self.assertIn('<new-action-id>', out['operations'][0]['argv'])
            self.assertEqual(out['optional_recovery_operations'], [original])

    def test_candidate_read_failure_keeps_blocker_without_new_check(self):
        _, _, store, _ = self.executing()
        self.lease(store)
        with patch('cogito_task_finish.collect_check_candidates', side_effect=OSError('evidence unreadable')):
            self.assert_no_rerun(store)
