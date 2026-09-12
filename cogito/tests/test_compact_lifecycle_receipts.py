"""CLI receipts stay small while authoritative queries and recovery stay available."""
import copy
import io
import json
import tempfile
from pathlib import Path
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
from cogito_gate import main
from cogito_run_queries import build_replan_receipt, build_disposition_receipt
import cogito_execution_registry as registry
import test_atomic_task_execution as atomic
import test_replan_store as replan
import test_cleanup_finalization as cleanup


class CompactLifecycleTests(GitTestCase):
    def fixture(self, cls):
        case = cls()
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    def cli(self, repo, *args, success=True):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(['--repo', str(repo), *args])
        self.assertEqual(code, 0 if success else 2, stderr.getvalue())
        return json.loads(stdout.getvalue())['data'] if success else stderr.getvalue()

    def test_executor_receipt_retains_global_stop_and_full_read_only_query(self):
        case = self.fixture(atomic.AtomicTaskTests)
        repo, _, store, _ = case.executing()
        case.lease(store)
        registry.register_external(repo, store.run_id, 'other', 'other-handle')
        receipt = self.cli(repo, 'replan', 'register-executor', '--run-id', store.run_id,
                           '--agent-id', 'worker', '--handle', 'worker-handle')
        self.assertEqual(receipt['executor']['handle'], 'worker-handle')
        self.assertNotIn('entries', receipt)
        self.assertFalse(receipt['quiescent'])
        self.assertFalse(receipt['stop_requested'])
        registry.request_stop(repo, store.run_id, now=100)
        raw = {'provider': 'test', 'control_tool': 'stop', 'event_id': 'E-stop',
               'handle': 'worker-handle', 'status': 'interrupted',
               'raw_response': {'handle': 'worker-handle', 'status': 'interrupted', 'log': 'x' * 10000}}
        path = store.run_dir / 'stop-receipt.json'
        path.write_text(json.dumps(raw))
        args = ('replan', 'executor-receipt', '--run-id', store.run_id,
                '--agent-id', 'worker', '--handle', 'worker-handle', '--input', str(path))
        stopped = self.cli(repo, *args)
        self.assertTrue(stopped['executor']['terminated'])
        self.assertTrue(stopped['stop_requested'])
        self.assertFalse(stopped['quiescent'])  # Other executor is still unresolved.
        self.assertEqual(stopped['stop_request']['deadline'], 160)
        self.assertNotIn('raw_response', stopped['executor']['receipt'])
        self.assertEqual(self.cli(repo, *args), stopped)
        before = {str(p): p.read_bytes() for p in store.run_dir.rglob('*') if p.is_file()}
        query = stopped['registry_query']['argv']
        with patch.object(registry, '_locked', side_effect=AssertionError('query created lock')):
            full = self.cli(repo, *query[4:])
        self.assertEqual(set(full['entries']), {'worker', 'other'})
        self.assertEqual(full['entries']['worker']['receipt'], raw)
        self.assertEqual(before, {str(p): p.read_bytes() for p in store.run_dir.rglob('*') if p.is_file()})
        self.cli(repo, 'replan', 'register-executor', '--run-id', store.run_id,
                 '--agent-id', 'worker', '--handle', 'worker-handle', success=False)

    def test_replan_review_approval_handoff_receipts_and_exact_replay(self):
        case = self.fixture(replan.ReplanStoreTests)
        repo, _, source, successor, rp, _ = case.setup_replan()
        status = self.cli(repo, 'replan', 'status', '--replan-id', rp.replan_id)
        self.assertIn('snapshot', status)
        self.assertIn('package', status['proposal'])
        digest = status['proposal_hash']
        review = dict(proposal_hash=digest, reviewer_id='independent', findings=[],
                      assessment={k: 'Reviewed' for k in ('impact', 'reuse', 'revalidation', 'handoff')})
        inputs = tempfile.TemporaryDirectory()
        self.addCleanup(inputs.cleanup)
        path = Path(inputs.name) / 'review-cli.json'
        path.write_text(json.dumps(review))
        args = ('replan', 'review', '--replan-id', rp.replan_id, '--input', str(path), '--action-id', 'review-cli')
        receipt = self.cli(repo, *args)
        self.assertEqual(receipt['proposal_hash'], digest)
        self.assertNotIn('proposal', receipt)
        self.assertNotIn('snapshot', receipt)
        events = rp.events_path.read_bytes()
        self.assertEqual(self.cli(repo, *args), receipt)
        self.assertEqual(rp.events_path.read_bytes(), events)
        self.cli(repo, 'replan', 'approve', '--replan-id', rp.replan_id,
                 '--proposal-hash', '0' * 64, '--action-id', 'bad-approve', success=False)
        approved = self.cli(repo, 'replan', 'approve', '--replan-id', rp.replan_id,
                            '--proposal-hash', digest, '--action-id', 'approve-cli')
        self.assertEqual(approved['state'], 'ready-for-handoff')
        args = ('replan', 'handoff', '--replan-id', rp.replan_id, '--action-id', 'handoff-cli')
        handed = self.cli(repo, *args)
        self.assertEqual(handed['state'], 'completed')
        self.assertEqual(handed['successor_run_id'], successor.run_id)
        events = rp.events_path.read_bytes()
        self.assertEqual(self.cli(repo, *args), handed)
        self.assertEqual(rp.events_path.read_bytes(), events)
        self.assertIn('transfers', rp.load())

    def test_presentation_drops_bulk_but_preserves_tool_and_followup_bindings(self):
        state = dict(replan_id='RP-1', disposition_id='DP-1', state='handing-off', sequence=12,
                     last_event_hash='a' * 64, source_run_id='DEV-old', successor_run_id='DEV-new',
                     next_action='review tool', proposal_hash='b' * 64,
                     handoff_tool_status='reviewing', handoff_tool_proposal_hash='c' * 64,
                     toolchain_status='approved', toolchain_proposal_hash='d' * 64,
                     proposal_stale=True, snapshot={'large': 'x' * 100000},
                     proposal={'followup_run_id': 'DEV-follow', 'package': 'x' * 100000},
                     proposal_history=['x' * 100000])
        before = copy.deepcopy(state)
        rp, dp = build_replan_receipt(state), build_disposition_receipt(state)
        self.assertEqual(rp['handoff_tool_proposal_hash'], state['handoff_tool_proposal_hash'])
        self.assertTrue(rp['proposal_stale'])
        self.assertEqual(dp['followup_run_id'], 'DEV-follow')
        self.assertLess(len(json.dumps(rp)) + len(json.dumps(dp)), 2000)
        self.assertEqual(state, before)

    def test_replan_cancel_source_returns_disposition_receipt_and_keeps_query(self):
        case = self.fixture(replan.ReplanStoreTests)
        repo, _, source, _, rp, _ = case.setup_replan()
        args = ('replan', 'abandon', '--replan-id', rp.replan_id, '--disposition', 'cancel-source',
                '--reason', 'cancel approved scope', '--action-id', 'cancel-cli')
        receipt = self.cli(repo, *args)
        self.assertEqual(receipt['disposition_id'], 'DP-' + rp.replan_id)
        self.assertEqual(receipt['source_run_id'], source.run_id)
        self.assertEqual(receipt['state'], 'analyzing')
        self.assertNotIn('snapshot', receipt)
        self.assertEqual(self.cli(repo, *args), receipt)
        full = self.cli(repo, 'disposition', 'status', '--disposition-id', receipt['disposition_id'])
        self.assertIn('snapshot', full)

    def test_accepted_query_separates_report_from_cleanup_and_keeps_report_validation(self):
        case = self.fixture(cleanup.CleanupFinalizationTests)
        repo, _, store, args = case.finalizing()
        store.finalize(*args)
        expected = store.completion_report()
        events = store.events_path.read_bytes()
        with patch.object(store, '_load_completion_report', wraps=store._load_completion_report) as read_report:
            out = store.next_action()
        # Cleanup still validates the committed report internally; only stdout is reduced.
        read_report.assert_called()
        self.assertNotIn('report', out)
        self.assertEqual(out['operations'][0]['operation'], 'finalize')
        self.assertEqual(out['report_query']['operation'], 'report')
        report = self.cli(repo, *out['report_query']['argv'][4:])
        self.assertEqual(report, expected)
        self.assertEqual(store.events_path.read_bytes(), events)
        with patch('cogito_run_store.RunStore._load_completion_report', side_effect=CogitoError('damaged committed report')):
            error = self.cli(repo, *out['report_query']['argv'][4:], success=False)
            self.assertIn('damaged committed report', error)
