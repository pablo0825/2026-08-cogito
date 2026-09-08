"""Only proven preparation failures can be superseded by bound transient retries."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cogito_common import CogitoError, hash_json
from cogito_test_support import GitTestCase
import test_atomic_task_execution as execution
import cogito_runner


class CheckRetryTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    commit = staticmethod(execution.AtomicTaskTests.commit)

    def ready(self, configure=None):
        repo, worker, store, _ = self.executing(configure)
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        return repo, worker, store

    def preparation_failure(self, store, worker, action='original'):
        with patch('cogito_runner._working_tree_binding', side_effect=CogitoError('snapshot denied')):
            with patch('cogito_runner.run_bounded_process') as process:
                with self.assertRaises(CogitoError):
                    store.run_controlled_check('C-a', worker, action)
                process.assert_not_called()
        return store.run_dir / 'check-actions' / hash_json(action)

    def retry(self, store, original='original', replacement='replacement', action='retry'):
        return store.record_retry('transient', 'snapshot unavailable', action,
                                  check_action_id=original, replacement_action_id=replacement)

    def test_preflight_rejection_preserves_request_and_index_without_started_marker(self):
        for target in ('cogito_execution_registry.process_identity',
                       'cogito_execution_registry._group_alive',
                       'cogito_evidence_binding.working_tree_binding'):
            with self.subTest(target=target):
                _, worker, store = self.ready()
                index = Path(subprocess.check_output(
                    ['git', '-C', str(worker), 'rev-parse', '--git-path', 'index'], text=True).strip())
                before = index.read_bytes()
                with patch(target, side_effect=CogitoError('capability denied')):
                    with patch('cogito_runner.run_bounded_process') as process:
                        with self.assertRaisesRegex(CogitoError, 'preflight rejected before start'):
                            store.run_controlled_check('C-a', worker, 'probe')
                        process.assert_not_called()
                directory = store.run_dir / 'check-actions' / hash_json('probe')
                self.assertTrue((directory / 'request.json').exists())
                self.assertFalse((directory / 'started.json').exists())
                self.assertEqual(index.read_bytes(), before)
                with self.assertRaises(CogitoError):
                    store.run_controlled_check('C-b', worker, 'probe')
                store.run_controlled_check('C-a', worker, 'probe')
                self.assertFalse(any(e['type'] in ('transient-retry', 'check-preparation-failed')
                                     for e in store._events.read()))

    def test_completed_replay_skips_probe_and_reports_exact_action(self):
        _, worker, store = self.ready()
        store.run_controlled_check('C-a', worker, 'first')
        expected = store.check_evidence_receipt_payload('C-a', 'first')
        self.assertEqual(expected['check_status'], 'passed')
        with patch('cogito_runner.preflight_check', side_effect=AssertionError('must not probe')):
            store.run_controlled_check('C-a', worker, 'first')
        self.assertEqual(store.check_evidence_receipt_payload('C-a', 'first'), expected)

    def test_preparation_retry_finishes_task_and_allows_next_lease(self):
        _, worker, store = self.ready()
        directory = self.preparation_failure(store, worker)
        original_bytes = {p.name: p.read_bytes() for p in directory.glob('*.json')}
        self.assertEqual(sum(e['type'] == 'check-preparation-failed' for e in store._events.read()), 1)
        self.retry(store)
        store.run_controlled_check('C-a', worker, 'replacement')
        store.finish_task('T-a', {'risks': []}, 'finish')
        self.lease(store, 'T-b')
        for name, value in original_bytes.items():
            self.assertEqual((directory / name).read_bytes(), value)

    def test_preparation_failure_without_retry_still_blocks_after_later_success(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        store.run_controlled_check('C-a', worker, 'unrelated-success')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')

    def test_post_snapshot_failure_is_unknown_and_cannot_be_bound(self):
        _, worker, store = self.ready()
        binding = cogito_runner._working_tree_binding
        calls = []
        def snapshot(path):
            calls.append(path)
            if len(calls) == 2:
                raise CogitoError('snapshot denied')
            return binding(path)
        with patch('cogito_runner._working_tree_binding', side_effect=snapshot):
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-a', worker, 'original')
        self.assertEqual(len(calls), 2)
        self.assertFalse(any(e['type'] == 'check-preparation-failed' for e in store._events.read()))
        before = store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            self.retry(store)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_historical_unknown_marker_and_reason_only_retry_do_not_clear_block(self):
        _, worker, store = self.ready()
        with patch('cogito_runner.run_check', side_effect=CogitoError('historical interruption')):
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-a', worker, 'original')
        store.record_retry('transient', 'claims process never started', 'legacy-retry')
        store.run_controlled_check('C-a', worker, 'replacement')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')
        with self.assertRaises(CogitoError):
            self.retry(store)

    def test_failed_replacement_cannot_clear_old_marker(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        (worker / 'src/a.txt').write_text('bad\n')
        store.run_controlled_check('C-a', worker, 'replacement')
        (worker / 'src/a.txt').write_text('after\n')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')

    def test_other_required_failure_remains_blocking(self):
        def configure(draft):
            draft['execution_dag']['tasks'][0]['check_ids'].append('C-b')
        _, worker, store = self.ready(configure)
        self.preparation_failure(store, worker)
        self.retry(store)
        store.run_controlled_check('C-a', worker, 'replacement')
        store.run_controlled_check('C-b', worker, 'other-failed')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish')

    def test_retry_and_successful_attempt_replay_without_execution_or_events(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        retry_bytes = store.events_path.read_bytes()
        self.retry(store)
        self.assertEqual(store.events_path.read_bytes(), retry_bytes)
        store.run_controlled_check('C-a', worker, 'replacement')
        success_bytes = store.events_path.read_bytes()
        with patch('cogito_runner.run_check') as run:
            store.run_controlled_check('C-a', worker, 'replacement')
            run.assert_not_called()
        self.assertEqual(store.events_path.read_bytes(), success_bytes)

    def test_retry_cannot_claim_an_attempt_that_already_succeeded(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        store.run_controlled_check('C-a', worker, 'replacement')
        before = store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            self.retry(store)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_new_lease_does_not_inherit_preparation_failure_authority(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        store.update_task('T-a', 'blocked', 'worker')
        store.update_task('T-a', 'pending', 'worker')
        self.lease(store)
        with self.assertRaises(CogitoError):
            self.retry(store)

    def test_replacement_cannot_execute_different_check(self):
        def configure(draft):
            draft['execution_dag']['tasks'][0]['check_ids'].append('C-b')
        _, worker, store = self.ready(configure)
        self.preparation_failure(store, worker)
        self.retry(store)
        with patch('cogito_runner.run_check') as run:
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-b', worker, 'replacement')
            run.assert_not_called()

    def test_two_preparation_failures_require_terminal_success(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        self.preparation_failure(store, worker, 'replacement')
        self.retry(store, 'replacement', 'terminal', 'retry-terminal')
        with self.assertRaises(CogitoError):
            store.finish_task('T-a', {'risks': []}, 'finish-before-success')
        store.run_controlled_check('C-a', worker, 'terminal')
        store.finish_task('T-a', {'risks': []}, 'finish')

    def test_failure_receipt_cache_crash_replay_preserves_receipt_and_never_runs(self):
        _, worker, store = self.ready()
        count = len(store._events.read())
        refresh = store._events.refresh_cache
        def fail_after_append(state):
            if len(store._events.read()) > count:
                raise CogitoError('cache unavailable')
            return refresh(state)
        with patch.object(store._events, 'refresh_cache', side_effect=fail_after_append):
            with patch('cogito_runner._working_tree_binding', side_effect=CogitoError('snapshot denied')):
                with self.assertRaises(CogitoError):
                    store.run_controlled_check('C-a', worker, 'original')
        before = store.events_path.read_bytes()
        self.assertTrue(any(e['type'] == 'check-preparation-failed' for e in store._events.read()))
        with patch('cogito_runner.run_check') as run:
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-a', worker, 'original')
            run.assert_not_called()
        self.assertEqual(store.events_path.read_bytes(), before)
        self.retry(store)
        store.run_controlled_check('C-a', worker, 'replacement')
        store.finish_task('T-a', {'risks': []}, 'finish')

    def test_failure_before_receipt_append_remains_unknown(self):
        _, worker, store = self.ready()
        with patch.object(store._events, 'append', side_effect=OSError('event storage unavailable')):
            with patch('cogito_runner._working_tree_binding', side_effect=CogitoError('snapshot denied')):
                with self.assertRaises(OSError):
                    store.run_controlled_check('C-a', worker, 'original')
        self.assertFalse(any(e['type'] == 'check-preparation-failed' for e in store._events.read()))
        with self.assertRaises(CogitoError):
            self.retry(store)

    def test_cli_retry_success_task_finish_and_next_lease(self):
        repo, worker, store = self.ready()
        self.preparation_failure(store, worker)
        entry = Path(__file__).resolve().parents[1] / 'scripts/cogito_gate.py'
        def cli(command, *args):
            result = subprocess.run([sys.executable, str(entry), '--repo', str(repo), command,
                                     '--run-id', store.run_id, *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return json.loads(result.stdout)
        cli('retry', '--kind', 'transient', '--reason', 'snapshot failed before execution',
            '--action-id', 'retry', '--check-action-id', 'original',
            '--replacement-action-id', 'replacement')
        cli('run-check', '--check-id', 'C-a', '--worktree', str(worker), '--action-id', 'replacement')
        request = store.run_dir / 'finish.json'
        request.write_text(json.dumps({'risks': []}))
        result = cli('task-finish', '--task-id', 'T-a', '--input', str(request), '--action-id', 'finish')
        self.assertEqual(result['data']['next']['ready_tasks'], ['T-b'])
        cli('task', '--task-id', 'T-b', '--status', 'leased', '--agent-id', 'worker', '--action-id', 'lease-b')
        self.assertEqual(store.load()['tasks']['T-b']['status'], 'leased')

    def test_failed_replacement_can_be_formally_retried_from_same_source(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        (worker / 'src/a.txt').write_text('bad\n')
        store.run_controlled_check('C-a', worker, 'replacement')
        (worker / 'src/a.txt').write_text('after\n')
        self.retry(store, 'original', 'replacement-c', 'retry-c')
        store.run_controlled_check('C-a', worker, 'replacement-c')
        store.finish_task('T-a', {'risks': []}, 'finish')
        self.lease(store, 'T-b')

    def test_pending_unknown_and_successful_replacements_cannot_be_rebound(self):
        for outcome in ('pending', 'unknown', 'passed'):
            with self.subTest(outcome=outcome):
                _, worker, store = self.ready()
                self.preparation_failure(store, worker)
                self.retry(store)
                if outcome == 'unknown':
                    with patch('cogito_runner.run_check', side_effect=CogitoError('interrupted')):
                        with self.assertRaises(CogitoError):
                            store.run_controlled_check('C-a', worker, 'replacement')
                elif outcome == 'passed':
                    store.run_controlled_check('C-a', worker, 'replacement')
                before = store.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    self.retry(store, 'original', 'replacement-c', 'retry-c')
                self.assertEqual(store.events_path.read_bytes(), before)

    def test_replacement_request_or_started_tampering_rejects_supersession(self):
        for filename in ('request.json', 'started.json'):
            with self.subTest(filename=filename):
                _, worker, store = self.ready()
                self.preparation_failure(store, worker)
                self.retry(store)
                store.run_controlled_check('C-a', worker, 'replacement')
                path = store.run_dir / 'check-actions' / hash_json('replacement') / filename
                value = json.loads(path.read_text())
                value['request_hash'] = 'f' * 64
                path.chmod(0o600)
                path.write_text(json.dumps(value))
                with self.assertRaisesRegex(CogitoError, 'replacement attempt files changed'):
                    store.finish_task('T-a', {'risks': []}, 'finish')

    def test_foreign_run_evidence_rejected_even_with_matching_supplied_hash(self):
        from cogito_check_retry import replacement_evidence
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        store.run_controlled_check('C-a', worker, 'replacement')
        events = store._events.read()
        event = next(e for e in events if e['type'] == 'check-evidence-recorded')
        path = Path(event['payload']['evidence_path'])
        value = json.loads(path.read_text())
        value['run_id'] = 'DEV-foreign'
        path.chmod(0o600)
        path.write_text(json.dumps(value))
        # Synthetic adapter input isolates the run-binding check from hash checks.
        event['payload']['evidence_hash'] = hash_json(value)
        retry = next(e for e in events if e['type'] == 'transient-retry')
        with self.assertRaisesRegex(CogitoError, 'does not match'):
            replacement_evidence(store, events, retry)

    def test_replacement_lease_drift_after_execution_prevents_evidence_registration(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        run = cogito_runner.run_check
        def execute_then_reassign(*args, **kwargs):
            evidence = run(*args, **kwargs)
            store.update_task('T-a', 'blocked', 'worker')
            store.update_task('T-a', 'pending', 'worker')
            self.lease(store)
            return evidence
        with patch('cogito_runner.run_check', side_effect=execute_then_reassign):
            with self.assertRaisesRegex(CogitoError, 'lease, checkout or contract changed'):
                store.run_controlled_check('C-a', worker, 'replacement')
        self.assertFalse(any(e['type'] == 'check-evidence-recorded' for e in store._events.read()))

    def test_replacement_contract_drift_after_execution_prevents_evidence_registration(self):
        from copy import deepcopy
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        run = cogito_runner.run_check
        load = store.load
        completed = False
        def execute(*args, **kwargs):
            nonlocal completed
            evidence = run(*args, **kwargs)
            completed = True
            return evidence
        def state_after_execution():
            state = deepcopy(load())
            if completed:
                state['effective_contract_hash'] = 'f' * 64
            return state
        with patch('cogito_runner.run_check', side_effect=execute):
            with patch.object(store, 'load', side_effect=state_after_execution):
                with self.assertRaisesRegex(CogitoError, 'lease, checkout or contract changed'):
                    store.run_controlled_check('C-a', worker, 'replacement')
        self.assertFalse(any(e['type'] == 'check-evidence-recorded' for e in store._events.read()))

    def test_failed_replacement_tamper_or_unstopped_executor_prevents_rebinding(self):
        from cogito_execution_registry import snapshot
        for mode in ('tampered-evidence', 'unstopped-executor'):
            with self.subTest(mode=mode):
                _, worker, store = self.ready()
                self.preparation_failure(store, worker)
                self.retry(store)
                (worker / 'src/a.txt').write_text('bad\n')
                store.run_controlled_check('C-a', worker, 'replacement')
                (worker / 'src/a.txt').write_text('after\n')
                if mode == 'tampered-evidence':
                    event = next(e for e in store._events.read() if e['type'] == 'check-evidence-recorded')
                    path = Path(event['payload']['evidence_path'])
                    value = json.loads(path.read_text())
                    value['duration_seconds'] += 1
                    path.chmod(0o600)
                    path.write_text(json.dumps(value))
                    with self.assertRaisesRegex(CogitoError, 'retry evidence changed'):
                        self.retry(store, 'original', 'replacement-c', 'retry-c')
                else:
                    entries = snapshot(store.root, store.run_id)
                    record_id = 'C-a-' + hash_json({'action_id': 'replacement'})[:16]
                    entries['entries'][record_id]['terminated'] = False
                    with patch('cogito_execution_registry.snapshot', return_value=entries):
                        with self.assertRaisesRegex(CogitoError, 'not proven stopped'):
                            self.retry(store, 'original', 'replacement-c', 'retry-c')

    def test_failure_event_cannot_be_forged_through_public_record(self):
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        payload = next(e['payload'] for e in store._events.read() if e['type'] == 'check-preparation-failed')
        before = store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            store.record('check-preparation-failed', payload, 'forged-failure')
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_retry_link_missing_field_or_wrong_reference_is_rejected(self):
        from copy import deepcopy
        from cogito_check_retry_rules import validate_link
        _, worker, store = self.ready()
        self.preparation_failure(store, worker)
        self.retry(store)
        events = store._events.read()
        original = next(e['payload']['check_retry'] for e in events if e['type'] == 'transient-retry')
        for malformed in ('missing', 'hash'):
            with self.subTest(malformed=malformed):
                link = deepcopy(original)
                if malformed == 'missing':
                    del link['failure']
                else:
                    link['failure']['event_hash'] = 'f' * 64
                with self.assertRaises(CogitoError):
                    validate_link(store.load(), events, link)
