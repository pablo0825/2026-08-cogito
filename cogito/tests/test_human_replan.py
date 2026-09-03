"""Real Git simulation of human change feedback through RP and fresh acceptance."""
import json

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
from cogito_projection import project_events
from cogito_run_store import RunStore
import test_replan_e2e as replan_support
import test_human_acceptance as human_support


class HumanReplanTests(GitTestCase):
    fixture = replan_support.ReplanEndToEndTests.fixture
    result = staticmethod(replan_support.ReplanEndToEndTests.result)
    check = staticmethod(replan_support.ReplanEndToEndTests.check)
    _successor = replan_support.ReplanEndToEndTests._successor

    def _finish(self, repo, worktree, store, ranges, slice_id, branch):
        """Finish actual implementation; successor must require a new human decision."""
        for index, (base, head) in enumerate(ranges, 1):
            store.submit_agent_result(self.result(store, f'T-{index}', base, head))
        store.transition('review-approved', {})
        git(repo, 'merge', '--no-ff', '-qm', 'Integrate human change', branch)
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), slice_id)
        post = self.check(store, repo, 'human-rp-post')
        self.assertTrue(post['passed'], post['stderr'])
        # Only the original delivery uses reviewer escalation. The successor's
        # package has no human predicates and must still honor the RP mandate.
        is_original = store.run_id == 'DEV-feature-multitask'
        state = store.decide_post_verification([post], reviewer_escalation=is_original)
        self.assertEqual(state['state'], 'awaiting-human')

    def test_mixed_feedback_rp_successor_requires_fresh_human_acceptance(self):
        repo, worktree, source, ranges = self.fixture()
        self._finish(repo, worktree, source, ranges, 'FS-1', 'codex/fs-1')
        feedback = human_support.HumanAcceptanceTests.feedback(close=True, mixed=True)
        source.human_feedback(feedback, 'mixed-human-feedback')
        state = source.human_triage({
            'feedback_id': 'HF-1',
            'assessments': [
                {'id': 'I-1', 'disposition': 'local', 'reason': 'Single label typo'},
                {'id': 'I-2', 'disposition': 'change', 'reason': 'Automatic query changes the interaction'},
            ],
        }, 'mixed-human-triage')
        self.assertEqual(state['state'], 'human-feedback-triage')
        self.assertEqual(state['human']['triage']['route'], 'change')
        self.assertFalse(any(t['status'] in {'leased', 'running'} for t in state['tasks'].values()))
        with self.assertRaises(CogitoError):
            source.human_correction_start({'amendment_id': 'TA-bypass'}, 'bypass-change')
        original_events = source.events_path.read_bytes()
        original_package = source.approved_package()
        original_feedback_hash = state['human']['feedback_hash']
        successor, replan = self._successor(repo, source, cli=True)
        self.assertEqual(replan.load()['source_state'], 'human-feedback-triage')
        self.assertEqual(source.load()['state'], 'superseded')
        self.assertTrue(source.events_path.read_bytes().startswith(original_events))
        self.assertEqual(source.approved_package(), original_package)
        self.assertEqual(source.load()['human']['feedback_hash'], original_feedback_hash)
        state = successor.load()
        self.assertEqual(successor.approved_package()['human_gate']['predicates'], [])
        self.assertEqual(state['state'], 'awaiting-human')
        self.assertEqual(state['human_review_mandate']['source_run_id'], source.run_id)
        self.assertEqual(state['human_review_mandate']['source_feedback_hash'], original_feedback_hash)
        # Source conditional approval is historical context, never successor consent.
        self.assertFalse(state.get('human'))
        events = [json.loads(line) for line in successor.events_path.read_text().splitlines()]
        mandates = [event for event in events if event['type'] == 'human-review-mandated']
        self.assertEqual(len(mandates), 1)
        self.assertEqual(project_events(events, successor.workflow)['human_review_mandate'],
                         state['human_review_mandate'])
        self.assertEqual(RunStore(repo, successor.run_id).load()['state'], 'awaiting-human')
        saved = successor.events_path.read_bytes()
        replan.handoff('handoff')
        self.assertEqual(successor.events_path.read_bytes(), saved)
        successor.approve_human_gate('fresh-successor-acceptance')
        self.assertEqual(successor.load()['state'], 'finalizing')

    def test_scope_escalation_cannot_resume_as_ordinary_local_correction(self):
        fixture = human_support.HumanAcceptanceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        _, source = fixture.fixture()
        fixture.begin(source, close=True)
        source.human_escalate({'reason': 'Shared date logic affects other pages'}, 'scope-expanded')
        self.assertEqual(source.load()['state'], 'blocked')
        with self.assertRaises(CogitoError):
            source.resume_gate('ordinary-resume')
        self.assertEqual(source.load()['state'], 'blocked')


if __name__ == '__main__':
    import unittest
    unittest.main()
