"""Delivery and human corrections reuse exact-content atomic Task evidence."""

import json
import sys

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
import test_atomic_task_verification as verification_tests
import test_human_acceptance as human_tests


class AtomicCorrectionTests(GitTestCase):
    executing = verification_tests.AtomicVerificationTests.executing
    lease = staticmethod(verification_tests.AtomicVerificationTests.lease)
    commit = staticmethod(verification_tests.AtomicVerificationTests.commit)
    check = staticmethod(verification_tests.AtomicVerificationTests.check)
    result = staticmethod(verification_tests.AtomicVerificationTests.result)
    implement = verification_tests.AtomicVerificationTests.implement
    wave = verification_tests.AtomicVerificationTests.wave
    review = staticmethod(verification_tests.AtomicVerificationTests.review)
    integrated = verification_tests.AtomicVerificationTests.integrated

    @staticmethod
    def amendment(phase='task'):
        return {
            'id': 'TA-delivery', 'reason': 'Fix related delivery behavior',
            'added_tasks': [{'id': 'T-fix', 'slice_id': 'FS-1', 'paths': ['src/a.txt'],
                             'responsibility': 'Correct a', 'check_ids': ['C-fix', 'C-b']}],
            'added_checks': [{'id': 'C-fix', 'phase': phase, 'argv': [sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('src/a.txt').read_text() == 'fixed\\n'"]}],
        }

    def correct_delivery(self, repo, store):
        self.lease(store, 'T-fix')
        base = store.load()['tasks']['T-fix']['base_commit']
        self.assertEqual(store.load()['tasks']['T-fix']['worktree'], str(repo.resolve()))
        (repo / 'src/a.txt').write_text('fixed\n')
        head = self.commit(repo, 'fix a\n\nCogito-Amendment: TA-delivery')
        evidence = [self.check(store, repo, check_id, 'fix-' + check_id)
                    for check_id in ('C-fix', 'C-b')]
        result = self.result(store, repo, evidence, 'T-fix')
        store.submit_agent_result(result)
        store.update_task('T-fix', 'complete', 'worker')
        self.assertEqual(git(repo, 'rev-list', '--count', base + '..' + head), '1')
        return result, evidence

    @staticmethod
    def check_count(store):
        return sum(json.loads(line)['type'] == 'check-evidence-recorded'
                   for line in store.events_path.read_text().splitlines())

    def test_post_integration_correction_reuses_task_integration_evidence(self):
        repo, _, store, _, _, _, _ = self.integrated()
        store.add_amendment(self.amendment())
        store.enter_correction('start-delivery-fix')
        result, evidence = self.correct_delivery(repo, store)
        count = self.check_count(store)
        store.complete_correction('TA-delivery', result['head_commit'], 'finish-delivery-fix')
        self.assertEqual(store.load()['state'], 'post-integration-verification')
        store.decide_post_verification([evidence[-1]], action_id='verify-delivery-fix')
        self.assertEqual(store.load()['state'], 'finalizing')
        self.assertEqual(self.check_count(store), count)

    def test_reviewing_rejects_new_tasks_before_start_without_appending(self):
        _, _, store, _, results, evidence = self.wave()
        store.complete_verification([evidence[-1]])
        store.submit_agent_result({**results[0], 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'status': 'needs-fix', 'changed_paths': [],
            'evidence': [], 'risks': ['fix a'], 'requested_transition': 'review-fix'})
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'start review-fix'):
            store.add_amendment(self.amendment())
        self.assertEqual(store.events_path.read_bytes(), before)
        store.enter_review_fix()
        store.add_amendment(self.amendment())
        self.assertIn('T-fix', store.load()['tasks'])

    def test_human_local_correction_reuses_task_evidence_and_gets_independent_review(self):
        for close in (False, True):
            with self.subTest(close=close):
                repo, _, store, _, _, _, _ = self.integrated()
                post = self.check(store, repo, 'C-b', 'before-human')
                store.decide_post_verification([post], reviewer_escalation=True)
                store.human_feedback(human_tests.HumanAcceptanceTests.feedback(close=close), 'feedback')
                store.human_triage({
                    'feedback_id': 'HF-1', 'assessments': [
                        {'id': 'I-1', 'disposition': 'local', 'reason': 'Bounded internal correction'},
                    ],
                }, 'triage')
                store.add_amendment(self.amendment('integration'))
                store.human_correction_start({'amendment_id': 'TA-delivery'}, 'human-start')
                result, evidence = self.correct_delivery(repo, store)
                count = self.check_count(store)
                store.human_correction_complete({
                    'feedback_id': 'HF-1', 'amendment_id': 'TA-delivery',
                    'commit_id': result['head_commit'], 'resolved_item_ids': ['I-1'],
                    'summary': 'Corrected bounded behavior',
                }, 'human-complete')
                store.human_verify(evidence, 'human-verify')
                self.assertEqual(store.load()['state'], 'human-correction-reviewing')
                store.submit_agent_result({
                    **result, 'role': 'reviewer', 'agent_id': 'human-reviewer',
                    'reviewed_implementer': 'worker', 'changed_paths': [], 'evidence': [],
                    'requested_transition': 'review-approved',
                })
                store.human_review('human-review')
                self.assertEqual(store.load()['state'], 'finalizing' if close else 'awaiting-human')
                self.assertEqual(self.check_count(store), count)
