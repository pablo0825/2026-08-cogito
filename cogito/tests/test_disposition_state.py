"""Disposition decisions retain history and require fresh independent approval."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cogito_common import CogitoError, hash_json
from cogito_disposition_state import project_disposition, validate_proposal, validate_review


def proposal():
    return dict(action='retain', author_id='agent', summary='Retain verified delivery',
                impact=dict(paths=['src/export/**'], slice_ids=['export'], reason='Shared API'),
                followup_run_id='DEV-retain', followup_package_hash='a'*64, acceptance=['Human accepts retained behavior'])


def history():
    p = proposal(); h = hash_json(p)
    return [dict(type='disposition-created',payload=dict(disposition_id='DP-test',source_run_id='DEV-test',reason='Cancel')),
            dict(type='disposition-stopped',payload=dict(snapshot={'scope':p['impact']})),
            dict(type='proposal-prepared',payload=dict(proposal=p,proposal_hash=h))]


class DispositionStateTests(unittest.TestCase):
    def test_rejection_and_revision_invalidate_review_and_preserve_history(self):
        events = history(); digest = events[-1]['payload']['proposal_hash']
        review = dict(reviewer_id='reviewer',proposal_hash=digest,findings=[],summary='Impact covered')
        events.extend([dict(type='proposal-reviewed',payload={'review':review}),
                       dict(type='disposition-approved',payload=dict(proposal_hash=digest,authorized=True))])
        revised = proposal(); revised['summary'] = 'Restore instead'; revised['action'] = 'restore'
        with self.assertRaisesRegex(CogitoError, 'illegal'):
            project_disposition(events + [dict(type='proposal-prepared', payload=dict(proposal=revised, proposal_hash=hash_json(revised)))])
        events.extend([dict(type='disposition-pause-started', payload={'reason':'Change direction'}),
                       dict(type='disposition-paused', payload={'snapshot':{}, 'retired_followup_run_id':'DEV-retain'})])
        events.append(dict(type='proposal-prepared',payload=dict(proposal=revised,proposal_hash=hash_json(revised))))
        state = project_disposition(events)
        self.assertEqual(state['state'], 'reviewing')
        self.assertIsNone(state['approval'])
        self.assertIsNone(state['review'])
        self.assertEqual(len(state['proposal_history']), 2)
        self.assertEqual(len(state['decisions']), 1)
        with self.assertRaisesRegex(CogitoError,'current proposal'):
            validate_review(review,revised,hash_json(revised))

    def test_review_independence_and_resume_withdrawal(self):
        p = proposal()
        with self.assertRaisesRegex(CogitoError,'independently'):
            validate_review(dict(reviewer_id='agent',proposal_hash=hash_json(p),findings=[],summary='OK'),p,hash_json(p))
        p['action'] = 'resume'
        for authorization in (None, 'user said yes', {'authorized':False,'reason':'withdraw'}):
            p['withdrawal_authorization'] = authorization
            with self.assertRaises(CogitoError): validate_proposal(p)
        p['withdrawal_authorization'] = {'authorized':True,'reason':'User withdrew simplification request'}
        validate_proposal(p)

    def test_unreviewed_or_implicit_approval_is_rejected(self):
        events = history(); digest = events[-1]['payload']['proposal_hash']
        with self.assertRaisesRegex(CogitoError,'illegal'):
            project_disposition(events+[dict(type='disposition-approved',payload=dict(proposal_hash=digest,authorized=True))])
        tampered = copy.deepcopy(events); tampered[-1]['payload']['proposal']['summary'] = 'Changed'
        with self.assertRaisesRegex(CogitoError,'hash mismatch'): project_disposition(tampered)


if __name__ == '__main__': unittest.main()
