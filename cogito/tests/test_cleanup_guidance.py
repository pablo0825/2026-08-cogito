"""Cleanup guidance keeps acceptance, executor evidence and retry boundaries distinct."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cogito_common import CogitoError
from cogito_next_operations import cleanup_hints
from cogito_run_queries import build_finalization_receipt
from cogito_test_support import GitTestCase, SCRIPTS, git
import cogito_execution_registry as registry
import test_cleanup_finalization as finalization


def terminal_receipt(handle):
    # Synthetic executor tool response for this fixture, not product evidence.
    return {'provider': 'test', 'control_tool': 'wait', 'event_id': 'terminal-event',
            'handle': handle, 'status': 'completed',
            'raw_response': {'handle': handle, 'status': 'completed', 'output': 'x' * 10000}}


class CleanupGuidanceTests(GitTestCase):
    def finalizing(self):
        case = finalization.CleanupFinalizationTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case.finalizing()

    def invoke(self, operation, *, receipt_path=None, success=True):
        argv = [str(receipt_path) if arg == '<receipt-path>' else arg for arg in operation['argv']]
        result = subprocess.run(argv, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout + result.stderr)
        return json.loads(result.stdout)['data'] if success else result.stderr

    def test_receipt_query_registration_and_original_retry_preserve_history_and_local_data(self):
        repo, worker, store, args = self.finalizing()
        repo = repo.resolve()
        registry.register_external(repo, store.run_id, 'worker', 'worker-handle')
        registry.register_external(repo, store.run_id, 'finished', 'finished-handle')
        registry.record_external_receipt(repo, store.run_id, 'finished', 'finished-handle',
                                         terminal_receipt('finished-handle'))
        finalize = {'cwd': str(repo), 'argv': ['python3', str(SCRIPTS / 'cogito_gate.py'), '--repo', str(repo),
                    *finalization.CleanupFinalizationTests.finalize_cli_arguments(store, args)]}
        receipt = self.invoke(finalize)
        self.assertEqual(receipt['state'], 'accepted')
        self.assertEqual(receipt['cleanup']['status'], 'pending')
        self.assertTrue(worker.exists())
        events, report = store.events_path.read_bytes(), store.completion_report()
        (store.run_dir / 'execution-registry.lock').unlink()
        before = {str(p): p.read_bytes() for p in store.run_dir.rglob('*') if p.is_file()}
        refs = git(repo, 'for-each-ref', 'refs/cogito/cleanup')
        output = self.invoke(receipt['cleanup']['next_query'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in store.run_dir.rglob('*') if p.is_file()})
        self.assertEqual(refs, git(repo, 'for-each-ref', 'refs/cogito/cleanup'))
        self.assertFalse((store.run_dir / 'execution-registry.lock').exists())
        self.assertFalse((store.run_dir / 'cleanup.json').exists())
        self.assertEqual(output['next_action'], 'report-completion')
        self.assertEqual(self.invoke(output['report_query']), report)
        self.assertEqual(output['cleanup']['status'], 'pending')
        self.assertTrue(output['cleanup']['observation_only'])
        row, = output['cleanup']['retained']
        self.assertEqual((row['executor_id'], row['handle']), ('worker', 'worker-handle'))
        self.assertEqual(row['reason'], 'external_receipt_missing')
        self.assertNotIn('raw_response', row)
        self.assertNotIn('finished-handle', json.dumps(output))
        full = self.invoke(output['cleanup']['registry_query'])
        self.assertTrue({'worker', 'finished'} <= set(full['entries']))
        self.assertEqual({key for key, entry in full['entries'].items() if not entry['terminated']}, {'worker'})
        self.assertEqual(output['operations'][0]['argv'], finalize['argv'])
        receipt_file = store.run_dir / 'terminal.json'
        receipt_file.write_text(json.dumps({'status': 'completed'}))
        operation, = row['operations']
        self.invoke(operation, receipt_path=receipt_file, success=False)
        self.assertFalse(registry.observe_read_only(repo, store.run_id, allow_external_receipts=True)['quiescent'])
        receipt_file.write_text(json.dumps(terminal_receipt('worker-handle')))
        self.assertTrue(self.invoke(operation, receipt_path=receipt_file)['quiescent'])
        ready = store.next_action()
        self.assertEqual(ready['cleanup']['removable'], [str(worker)])
        self.assertEqual(ready['cleanup']['status'], 'pending')  # Preview is not removal.

        exclude = Path(git(worker, 'rev-parse', '--git-path', 'info/exclude'))
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text((exclude.read_text() if exclude.exists() else '') + '\n.env\n')
        (worker / '.env').write_text('local data\n')
        retained = self.invoke(ready['operations'][0])
        self.assertEqual(retained['cleanup']['status'], 'pending')
        self.assertIn('ignored data', retained['cleanup']['retained'][0]['reason'])
        self.assertTrue((worker / '.env').exists())
        (worker / '.env').unlink()
        removed = self.invoke(store.next_action()['operations'][0])
        self.assertEqual(removed['cleanup']['status'], 'complete')
        self.assertEqual(removed['cleanup']['removed'], [str(worker)])
        self.assertFalse(worker.exists())
        self.assertEqual(store.next_action()['cleanup']['status'], 'no_pending_cleanup')
        self.assertEqual(self.invoke(finalize)['cleanup']['removed'], [])
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(store.completion_report(), report)


class CleanupObservationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = {'state': 'accepted', 'tasks': {'T-1': {'agent_id': 'worker'}, 'T-2': {'agent_id': 'second'}}}
        self.store = SimpleNamespace(root=self.root, run_id='DEV-cleanup',
            run_dir=self.root / '.cogito/runs/DEV-cleanup',
            _events=SimpleNamespace(snapshot=lambda: SimpleNamespace(state=self.state)))

    def test_missing_executors_exclude_attested_and_unleased_entries_have_no_operation(self):
        for identifier in ('worker', 'second', 'orphan', 'finished'):
            registry.register_external(self.root, self.store.run_id, identifier, identifier + '-handle')
        registry.record_external_receipt(self.root, self.store.run_id, 'finished', 'finished-handle',
                                         terminal_receipt('finished-handle'))
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch.object(registry, '_locked', side_effect=AssertionError('query must not lock')):
            output = cleanup_hints(self.store, self.state)['cleanup']
        rows = {row['executor_id']: row for row in output['retained']}
        self.assertEqual(set(rows), {'worker', 'second', 'orphan'})
        self.assertEqual(len(rows['worker']['operations']), 1)
        self.assertEqual(len(rows['second']['operations']), 1)
        self.assertNotIn('operations', rows['orphan'])
        self.assertIn('No matching Worker lease', rows['orphan']['note'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_process_observations_never_offer_external_receipt(self):
        identity = {'pid': 100, 'pgid': 100, 'started': 'start', 'command_sha256': 'a' * 64}
        data = {'entries': {'process': {'identifier': 'process', 'kind': 'process', 'identity': identity}},
                'stop_request': None}
        for current, alive, pgid, observation in (
            (identity, True, 100, 'running'),
            (None, True, 100, 'descendants-running'),
            ({**identity, 'started': 'later'}, True, 100, 'identity-mismatch'),
            (None, False, 99, 'unverified-shared-group'),
        ):
            with self.subTest(observation=observation):
                snapshot = copy.deepcopy(data)
                snapshot['entries']['process']['identity']['pgid'] = pgid
                with patch.object(registry, 'process_identity', return_value=current), \
                        patch.object(registry, '_group_alive', return_value=alive):
                    observed = registry._observe(snapshot, allow_external_receipts=True)
                with patch.object(registry, 'observe_read_only', return_value=observed):
                    output = cleanup_hints(self.store, self.state)['cleanup']
                row, = output['retained']
                self.assertEqual(row['observation'], observation)
                self.assertEqual(row['pid'], 100)
                self.assertNotIn('operations', row)
                self.assertEqual(output['status'], 'pending')

    def test_unreadable_registry_or_process_observation_stays_pending(self):
        for error in (CogitoError('malformed execution registry'), CogitoError('cannot inspect executor processes')):
            with self.subTest(error=str(error)), patch.object(registry, 'observe_read_only', side_effect=error):
                output = cleanup_hints(self.store, self.state)['cleanup']
            self.assertEqual(output['status'], 'pending')
            self.assertEqual(output['removable'], [])
            self.assertEqual(output['retained'], [{'reason': str(error)}])

    def test_finalization_outcome_is_detached_and_error_cannot_be_complete(self):
        for cleanup, status in (({'removed': [], 'retained': []}, 'complete'),
                                ({'removed': [], 'retained': [], 'error': 'unavailable'}, 'pending')):
            projection = {'run_id': 'DEV-cleanup', 'state': 'accepted', 'sequence': 5,
                          'last_event_hash': 'a' * 64, 'cleanup': cleanup}
            before = copy.deepcopy(projection)
            receipt = build_finalization_receipt(projection, self.root)
            self.assertEqual(receipt['cleanup']['status'], status)
            self.assertEqual(projection, before)
            receipt['cleanup']['removed'].append('/other')
            self.assertEqual(projection, before)
