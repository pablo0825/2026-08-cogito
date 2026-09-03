"""Unapproved successor rounds retain the approved-run RP authorization gates."""
import copy
import unittest
from unittest import mock

import test_replan_store as support
from cogito_common import CogitoError
from cogito_contracts import package_hash


class PlanningReplanInteropTests(unittest.TestCase):
    def setUp(self):
        self.f = support.ReplanStoreTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.repo, _, self.old, self.new, self.rp, self.proposal = self.f.setup_replan()

    def revise(self):
        draft = copy.deepcopy(self.proposal['package'])
        self.new.planning_begin({
            'round': 1, 'candidate_hash': package_hash(draft), 'level': 'plan',
            'author_id': 'successor-planner', 'reason': 'Improve implementation stop conditions.',
            'impact': {key: {'disposition': 'reuse', 'reason': 'Existing meaning remains valid.'}
                       for key in ('requirements','boundary','spec','plan','dag','acceptance')},
        }, 'successor-round2')
        draft['planning_round'] = 2
        draft['stop_conditions'].append('Stop for unexpected dependent API consumers.')
        self.new.prepare_package(draft, 'successor-candidate2')
        self.new.planning_review({
            'round': 2, 'proposal_hash': self.new.load()['planning']['proposal_hash'],
            'reviewer_id': 'successor-reviewer', 'findings': [],
            'assessment': {key: 'Checked old and new package.' for key in ('consistency','impact','reuse')},
        }, 'successor-review2')
        self.assertEqual(self.new.next_action()['next_action'], 'prepare-replan-proposal')
        return draft

    def test_successor_round_invalidates_old_rp_proposal_then_handoff_succeeds(self):
        old_digest = self.rp.load()['proposal_hash']
        self.rp.review({'proposal_hash': old_digest, 'reviewer_id': 'rp-reviewer', 'findings': [],
                        'assessment': {key: 'Checked' for key in ('impact','reuse','revalidation','handoff')}}, 'old-rp-review')
        source_before = self.old.events_path.read_bytes()
        draft = self.revise()
        self.assertTrue(self.rp.load()['proposal_stale'])
        with self.assertRaises(CogitoError):
            self.rp.approve(old_digest, 'stale-rp-approval')
        with self.assertRaises(CogitoError):
            self.new.approve_package(draft, 'bypass-rp-approval')
        self.proposal['package'] = draft
        self.rp.propose(self.proposal, 'new-rp-proposal')
        self.assertFalse(self.rp.load()['proposal_stale'])
        self.f.approve_replan(self.rp)
        self.rp.handoff('handoff')
        self.assertEqual(self.new.load()['state'], 'executing')
        self.assertEqual(self.new.load()['planning']['round'], 2)
        self.assertTrue(self.old.events_path.read_bytes().startswith(source_before))

    def test_durable_rp_approval_fences_preparation_before_publication(self):
        draft = self.revise()
        self.proposal['package'] = draft
        self.rp.propose(self.proposal, 'new-rp-proposal')
        with mock.patch.object(self.rp, '_publish_successor', side_effect=CogitoError('interrupted publication')):
            with self.assertRaisesRegex(CogitoError, 'interrupted publication'):
                self.f.approve_replan(self.rp)
        self.assertEqual(self.rp.load()['state'], 'ready-for-handoff')
        self.assertEqual(self.new.load()['state'], 'awaiting-package-approval')
        for operation in (
            lambda: self.new.prepare_package(draft, 'new-candidate'),
            lambda: self.new.planning_withdraw({'round': 2, 'authorized': True, 'reason': 'too late'}, 'withdraw'),
        ):
            with self.assertRaisesRegex(CogitoError, 'frozen'):
                operation()
        self.rp.approve(self.rp.load()['proposal_hash'], 'approve')
        self.assertEqual(self.new.load()['state'], 'start-gate')


if __name__ == '__main__':
    unittest.main()
