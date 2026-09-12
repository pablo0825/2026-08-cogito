"""Fixed Task completion exercises real Git, controlled evidence and replay."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cogito_common import CogitoError
from cogito_execution_registry import register_external
from cogito_test_support import GitTestCase, git
import test_atomic_task_execution as execution


class TaskFinishTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    check = staticmethod(execution.AtomicTaskTests.check)
    commit = staticmethod(execution.AtomicTaskTests.commit)
    result = staticmethod(execution.AtomicTaskTests.result)

    def ready(self, precommit=False):
        repo, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        if precommit:
            evidence = self.check(store, worker)
        self.commit(worker)
        if not precommit:
            evidence = self.check(store, worker)
        return repo, worker, store, evidence

    def test_cli_derives_result_and_finishes_precommit_evidence(self):
        repo, worker, store, evidence = self.ready(True)
        request = store.run_dir / 'finish.json'
        request.write_text(json.dumps({'risks': []}))
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/cogito_gate.py'),
            '--repo', str(repo), 'task-finish', '--run-id', store.run_id, '--task-id', 'T-a',
            '--input', str(request), '--action-id', 'finish']
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
        output = json.loads(first.stdout)['data']
        self.assertEqual(output['commit_id'], git(worker, 'rev-parse', 'HEAD'))
        self.assertEqual(output['evidence'], [evidence['evidence_path']])
        self.assertEqual(output['next']['ready_tasks'], ['T-b'])
        prefix = store.events_path.read_bytes()
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(store.events_path.read_bytes(), prefix)
        self.lease(store, 'T-b')

    def test_existing_identical_result_needs_only_completion(self):
        _, worker, store, evidence = self.ready()
        store.submit_agent_result(self.result(store, worker, [evidence]))
        before = len(store._events.read())
        store.finish_task('T-a', {'risks': []}, 'finish')
        self.assertEqual(len(store._events.read()), before + 1)

    def test_failed_latest_check_cannot_fall_back_to_older_success(self):
        _, worker, store, _ = self.ready()
        (worker / 'src/a.txt').write_text('bad\n')
        failed = self.check(store, worker, action='failed-latest')
        self.assertFalse(failed['passed'])
        (worker / 'src/a.txt').write_text('after\n')
        before = store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertFalse(list((store.run_dir / 'fixed-actions').glob('*.json')))

    def test_partial_append_and_cache_failure_replay_without_duplicate_receipts(self):
        for fail_after in (1, 2):
            with self.subTest(fail_after=fail_after):
                repo, worker, store, _ = self.ready()
                append = store._events.append
                count = 0
                def crash(event, **kwargs):
                    nonlocal count
                    value = append(event, **kwargs)
                    count += 1
                    if count == fail_after:
                        raise OSError('lost response after durable append')
                    return value
                with patch.object(store._events, 'append', side_effect=crash):
                    with self.assertRaises(OSError):
                        store.finish_task('T-a', {'risks': []}, 'finish')
                if fail_after == 1:
                    self.assertEqual(store.next_action()['next_action'], 'retry-fixed-action')
                    for operation in (
                        lambda: store.update_task('T-b', 'leased', 'worker'),
                        lambda: store.run_controlled_check('C-a', worker, 'other-check'),
                        lambda: register_external(repo, store.run_id, 'other', 'handle'),
                        lambda: store.finish_task('T-a', {'risks': []}, 'different'),
                    ):
                        with self.assertRaises(CogitoError):
                            operation()
                with self.assertRaises(CogitoError):
                    store.finish_task('T-a', {'risks': ['different']}, 'finish')
                store.finish_task('T-a', {'risks': []}, 'finish')
                events = store._events.read()
                self.assertEqual(sum(e['type'] == 'agent-result-recorded' for e in events), 1)
                self.assertEqual(store.load()['tasks']['T-a']['status'], 'complete')

    def test_resume_does_not_rebind_modified_checkout(self):
        _, worker, store, _ = self.ready()
        with patch.object(store._events, 'append', side_effect=OSError('before append')):
            with self.assertRaises(OSError):
                store.finish_task('T-a', {'risks': []}, 'finish')
        (worker / 'src/a.txt').write_text('changed\n')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')
        (worker / 'src/a.txt').write_text('after\n')
        store.finish_task('T-a', {'risks': []}, 'finish')

    def test_unknown_check_attempt_and_missing_evidence_are_rejected(self):
        for mode in ('unknown', 'missing'):
            with self.subTest(mode=mode):
                _, worker, store, evidence = self.ready()
                if mode == 'unknown':
                    directory = store.run_dir / 'check-actions' / 'interrupted'
                    directory.mkdir()
                    (directory / 'request.json').write_text(json.dumps({'action_id': 'unknown'}))
                    (directory / 'started.json').write_text('{}')
                else:
                    Path(evidence['evidence_path']).unlink()
                with self.assertRaises(CogitoError):
                    store.finish_task('T-a', {'risks': []}, 'finish')

    def test_preflight_rejection_does_not_publish_result(self):
        _, worker, store, _ = self.ready()
        (worker / 'src/b.txt').write_text('unowned\n')
        before = store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_real_cache_refresh_failure_recovers_from_authoritative_receipt(self):
        _, _, store, _ = self.ready()
        size = len(store._events.read())
        refresh = store._events.refresh_cache
        def cache_failure(state):
            if len(store._events.read()) > size:
                raise CogitoError('state cache could not be refreshed')
            return refresh(state)
        with patch.object(store._events, 'refresh_cache', side_effect=cache_failure):
            with self.assertRaisesRegex(CogitoError, 'cache'):
                store.finish_task('T-a', {'risks': []}, 'finish-cache')
        self.assertEqual(len(store._events.read()), size + 1)
        store.finish_task('T-a', {'risks': []}, 'finish-cache')
        self.assertEqual(len(store._events.read()), size + 2)

    def test_tampered_latest_attempt_time_cannot_expose_an_older_success(self):
        _, worker, store, original = self.ready()
        (worker / 'src/a.txt').write_text('bad\n')
        failed = self.check(store, worker, action='newer-failure')
        (worker / 'src/a.txt').write_text('after\n')
        failed['started_at'] = '2000-01-01T00:00:00+00:00'
        path = Path(failed['evidence_path'])
        path.chmod(0o600)
        path.write_text(json.dumps(failed))
        with self.assertRaisesRegex(CogitoError, 'recorded hash'):
            store.finish_task('T-a', {'risks': []}, 'finish')

    def test_next_provides_command_and_missing_check_reason_without_appending(self):
        _, _, store, _ = self.executing()
        self.lease(store)
        before = store.events_path.read_bytes()
        hint = store.next_action()['operations'][0]
        self.assertEqual(hint['operation'], 'run-check')
        self.assertIn('C-a', hint['argv'])
        self.assertEqual(hint['task_id'], 'T-a')
        self.assertIn('<new-action-id>', hint['argv'])
        self.assertEqual(store.events_path.read_bytes(), before)
