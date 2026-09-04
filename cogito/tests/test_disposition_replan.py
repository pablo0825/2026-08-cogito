"""Replanning exits preserve receipts and preflight irreversible decisions."""
import unittest
from unittest import mock

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
from cogito_replan_state import project_replan, TERMINAL
from cogito_replan_store import ReplanStore
from cogito_disposition_store import DispositionStore
from cogito_run_store import RunStore
import test_human_acceptance as human_support
import test_replan_store as replan_support


class DispositionReplanStateTests(unittest.TestCase):
    def initial(self):
        return [{'type': 'replan-created', 'payload': {
            'replan_id': 'RP-1', 'source_run_id': 'DEV-old',
            'successor_run_id': 'DEV-new', 'source_package_hash': 'a' * 64,
            'reason': 'Human requested change'}}]

    def test_legacy_stuck_decision_can_delegate_without_rewriting_intent(self):
        decision = {'disposition': 'resume-source', 'reason': 'Withdraw proposal', 'action_id': 'old'}
        history = self.initial() + [
            {'type': 'replan-abandon-started', 'payload': decision},
            {'type': 'replan-disposition-started', 'payload': {'disposition_id': 'DP-recovery'}},
        ]
        state = project_replan(history)
        self.assertEqual(state['decision'], decision)
        self.assertEqual(state['state'], 'disposition')


class DispositionReplanPreflightTests(GitTestCase):
    def test_human_escalation_rejects_resume_before_abandon_intent(self):
        fixture = human_support.HumanAcceptanceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        repo, source = fixture.fixture()
        fixture.begin(source, close=True)
        source.human_escalate({'reason': 'Shared date logic changes contract'}, 'escalate')
        replan = ReplanStore(repo, 'RP-resume-preflight')
        replan.begin(source.run_id, 'DEV-resume-next', 'Human change', 'begin')
        replan.stop('stop')
        before = replan.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'human feedback requires replanning'):
            replan.abandon('resume-source', 'New proposal rejected', 'resume')
        self.assertEqual(replan.events_path.read_bytes(), before)
        self.assertEqual(replan.load()['state'], 'analyzing')
        self.assertEqual(source.load()['state'], 'blocked')


class DispositionReplanIntegrationTests(GitTestCase):
    fixture = replan_support.ReplanStoreTests.fixture
    result = staticmethod(replan_support.ReplanStoreTests.result)
    setup_replan = replan_support.ReplanStoreTests.setup_replan
    approve_replan = replan_support.ReplanStoreTests.approve_replan

    def test_cancel_retries_disposition_without_legacy_abandon_intent(self):
        repo, _, source, _, replan, _ = self.setup_replan()
        transition = RunStore.transition
        def interrupted(store, event, *args, **kwargs):
            if event == 'cancel': raise CogitoError('interrupted cancellation')
            return transition(store, event, *args, **kwargs)
        with mock.patch.object(RunStore, 'transition', new=interrupted):
            with self.assertRaisesRegex(CogitoError, 'interrupted cancellation'):
                replan.abandon('cancel-source', 'Feature unwanted', 'cancel')
        disposition = DispositionStore(repo, 'DP-RP-api')
        self.assertEqual(disposition.load()['state'], 'stopping')
        self.assertNotEqual(replan.load()['state'], 'resolving-decision')
        replan.abandon('cancel-source', 'Feature unwanted', 'cancel')
        self.assertEqual(source.load()['state'], 'cancelled')
        self.assertEqual(disposition.load()['state'], 'analyzing')
        self.assertEqual(replan.load()['state'], 'disposition')
        before = replan.events_path.read_bytes()
        replan.abandon('cancel-source', 'Feature unwanted', 'cancel')
        self.assertEqual(replan.events_path.read_bytes(), before)

    def test_approved_replan_can_stop_into_disposition(self):
        repo, _, source, successor, replan, _ = self.setup_replan()
        self.approve_replan(replan)
        disposition = DispositionStore(repo, 'DP-withdraw-approved')
        disposition.begin(source.run_id, 'Reconsider approved change', 'begin', replan_id=replan.replan_id)
        with self.assertRaisesRegex(CogitoError, 'stop and snapshots'):
            replan.delegate_disposition(disposition.disposition_id, 'too-early')
        disposition.stop('stop')
        state = replan.load()
        self.assertEqual(state['state'], 'disposition')
        self.assertIn(successor.run_id, disposition.load()['snapshot']['runs'])
        self.assertEqual(source.load()['state'], 'blocked')
        with self.assertRaises(CogitoError): replan.handoff('original-handoff')

    def test_partial_handoff_saves_transferred_successor_worktree(self):
        repo, _, source, _, replan, _ = self.setup_replan()
        self.approve_replan(replan)
        transfer = replan._transfer
        def interrupted(row):
            transfer(row)
            raise CogitoError('interrupted after transfer')
        with mock.patch.object(replan, '_transfer', side_effect=interrupted):
            with self.assertRaisesRegex(CogitoError, 'interrupted after transfer'):
                replan.handoff('handoff')
        before = replan.load()
        self.assertEqual(before['state'], 'handing-off')
        self.assertTrue(before['transfers'])
        disposition = DispositionStore(repo, 'DP-partial-handoff')
        disposition.begin(source.run_id, 'Restore original behavior', 'begin', replan_id=replan.replan_id)
        disposition.stop('stop')
        saved = disposition.load()['snapshot']
        for receipt in before['transfers'].values():
            if receipt.get('worktree'):
                self.assertEqual(saved['worktrees'][receipt['worktree']]['content_tree'],
                                 receipt['binding']['content_tree'])
        self.assertEqual(replan.load()['transfers'], before['transfers'])
        self.assertEqual(replan.load()['state'], 'disposition')


if __name__ == '__main__':
    unittest.main()
