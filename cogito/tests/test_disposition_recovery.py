"""Recovery decisions must preserve completed work and record rejected reviews."""
import json
import unittest

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_replan_store import ReplanStore
import test_maintenance_multitask as maintenance_support


class DispositionRecoveryTests(GitTestCase):
    fixture = maintenance_support.MaintenanceMultitaskTests.fixture
    first_task = maintenance_support.MaintenanceMultitaskTests.first_task
    lease = maintenance_support.MaintenanceMultitaskTests.lease
    result = staticmethod(maintenance_support.MaintenanceMultitaskTests.result)

    def stopped_maintenance(self):
        repo, source, baseline = self.fixture()
        self.first_task(repo, source, baseline)
        replan = ReplanStore(repo, 'RP-recovery')
        replan.begin(source.run_id, 'MNT-recovery-next', 'User requests a change', 'begin')
        replan.stop('stop')
        disposition = DispositionStore(repo, 'DP-recovery')
        disposition.begin(source.run_id, 'Review withdrawing the change', 'begin',
                          replan_id=replan.replan_id)
        disposition.stop('stop')
        return repo, source, disposition

    @staticmethod
    def proposal():
        return {
            'action': 'resume', 'author_id': 'analyst',
            'summary': 'Continue the original completed and pending work',
            'impact': {'paths': ['first.txt', 'second.txt'], 'slice_ids': [],
                       'reason': 'Preserve original task results'},
            'acceptance': 'Original checks and required acceptance',
            'withdrawal_authorization': {
                'authorized': True, 'reason': 'User explicitly withdrew the requested change'},
        }

    def reviewed(self, disposition):
        state = disposition.propose(self.proposal(), 'proposal')
        disposition.review({
            'reviewer_id': 'independent-reviewer', 'proposal_hash': state['proposal_hash'],
            'findings': [], 'assessment': 'Original work must remain intact'}, 'review')
        return state['proposal_hash']

    def test_released_maintenance_work_cannot_resume_as_completed_work(self):
        repo, source, disposition = self.stopped_maintenance()
        self.assertEqual((repo / 'first.txt').read_text(), 'after\n')
        disposition.release('release')
        self.assertEqual((repo / 'first.txt').read_text(), 'before\n')
        digest = self.reviewed(disposition)
        source_before = source.events_path.read_bytes()
        decision_before = disposition.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'saved original delivery changed'):
            disposition.approve(digest, True, 'approve')
        self.assertEqual(source.events_path.read_bytes(), source_before)
        self.assertEqual(disposition.events_path.read_bytes(), decision_before)
        self.assertEqual(source.load()['state'], 'blocked')
        self.assertEqual(disposition.load()['state'], 'awaiting-approval')

    def test_delivery_change_after_approval_cannot_release_resume_holds(self):
        repo, source, disposition = self.stopped_maintenance()
        digest = self.reviewed(disposition)
        disposition.approve(digest, True, 'approve')
        (repo / 'first.txt').write_text('changed after approval\n')
        source_before = source.events_path.read_bytes()
        decision_before = disposition.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'saved original delivery changed'):
            disposition.complete('complete')
        self.assertEqual(source.events_path.read_bytes(), source_before)
        self.assertEqual(disposition.events_path.read_bytes(), decision_before)
        self.assertEqual(source.load()['state'], 'blocked')
        self.assertEqual(disposition.load()['state'], 'executing')

    def test_assessment_only_rejection_is_recorded_and_can_be_revised(self):
        _, source, disposition = self.stopped_maintenance()
        for number, assessment in enumerate([
                'The restoration impact is incomplete',
                {'impact': 'A shared consumer has not been assessed'}]):
            with self.subTest(assessment=assessment):
                state = disposition.propose(self.proposal(), f'proposal-{number}')
                review = {
                    'reviewer_id': 'independent-reviewer', 'proposal_hash': state['proposal_hash'],
                    'verdict': 'rejected', 'findings': ['Missing impact assessment'],
                    'assessment': assessment,
                }
                state = disposition.review(review, f'review-{number}')
                self.assertEqual(state['state'], 'analyzing')
                self.assertEqual(state['rejection']['review'], review)
                reason = state['rejection']['reason']
                self.assertEqual(json.loads(reason) if isinstance(assessment, dict) else reason,
                                 assessment)
                self.assertEqual(source.load()['state'], 'blocked')
                recorded = disposition.events_path.read_bytes()
                disposition.review(review, f'review-{number}')
                self.assertEqual(disposition.events_path.read_bytes(), recorded)


if __name__ == '__main__':
    unittest.main()
