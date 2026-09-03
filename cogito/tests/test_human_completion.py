"""Real Git simulations for controlled document adjustment and exhaustion."""
from __future__ import annotations

import base64
import hashlib
import json
import unittest

from cogito_test_support import GitTestCase, git
import cogito_runtime as runtime
import test_human_acceptance as acceptance


class HumanCompletionTests(GitTestCase):
    def setUp(self):
        super().setUp()
        self.sim = acceptance.HumanAcceptanceTests()
        self.addCleanup(self.sim.doCleanups)

    def product_result(self, repo, store, number=1, text=None):
        task, agent = f'T-H-{number}', f'human-worker-{number}'
        base = git(repo, 'rev-parse', 'HEAD')
        store.update_task(task, 'leased', agent)
        store.update_task(task, 'running', agent)
        (repo / 'src/note.txt').write_text(text or f'after corrected {number}\n')
        if store.load()['kind'] == 'feature':
            git(repo, 'add', 'src/note.txt')
            git(repo, 'commit', '-qm', f'correct label\n\nCogito-Amendment: TA-{number}')
        head = git(repo, 'rev-parse', 'HEAD')
        store.submit_agent_result(self.sim.result(store, task, agent, base, head))
        store.update_task(task, 'complete', agent)
        return base, head

    def completion(self, repo, number=1, **extra):
        return {'feedback_id': f'HF-{number}', 'amendment_id': f'TA-{number}',
                'commit_id': git(repo, 'rev-parse', 'HEAD'), 'resolved_item_ids': ['I-1'],
                'summary': 'Corrected local presentation', **extra}

    def test_feedback_during_repair_revokes_closure_and_is_processed_without_reasking(self):
        repo, store = self.sim.fixture()
        self.sim.begin(store, close=True)
        pending = self.sim.feedback(2, close=False)
        state = store.human_feedback(pending, 'queue-new-feedback')
        self.assertEqual(state['state'], 'human-correction')
        self.assertTrue(state['human']['grant_revoked'])
        self.assertEqual(store.human_feedback(pending, 'queue-new-feedback'), state)
        self.assertEqual(state['counters']['human_corrections'], 1)
        base, head = self.sim.implement(repo, store)
        self.assertEqual(self.sim.review(repo, store, 1, base, head)['state'], 'awaiting-human')
        self.assertEqual(store.next_action()['next_action'], 'record-pending-human-feedback')
        with self.assertRaisesRegex(runtime.CogitoError, 'pending human feedback'):
            store.approve_human_gate('cannot-ignore-pending')
        self.sim.begin(store, 2, close=False)
        self.assertEqual(store.load()['human']['pending_feedback'], [])
        base, head = self.sim.implement(repo, store, 2)
        self.assertEqual(self.sim.review(repo, store, 2, base, head)['state'], 'awaiting-human')
        store.approve_human_gate('accept-latest-delivery')
        self.sim.finalize_delivery(repo, store)

    def test_declared_document_adjustment_preserves_contract_and_closes(self):
        repo, store = self.sim.fixture('feature')
        package_path = repo / store.load()['package_path']
        package_before = package_path.read_bytes()
        hash_before = store.load()['package_hash']
        spec_before = (repo / 'docs/spec.md').read_bytes()
        self.sim.begin(store, close=True)
        base, product_head = self.product_result(repo, store)
        spec_after = b'# spec\nKeep the label beside the date input.\n'
        (repo / 'docs/spec.md').write_bytes(spec_after)
        git(repo, 'add', 'docs/spec.md')
        git(repo, 'commit', '-qm', 'Document local position\n\nCogito-Amendment: TA-1')
        doc_head = git(repo, 'rev-parse', 'HEAD')
        self.assertNotEqual(doc_head, product_head)
        request = self.completion(repo, document_updates=[{'path': 'docs/spec.md', 'reason': 'local position'}])
        state = store.human_correction_complete(request, 'complete-doc-adjustment')
        self.assertEqual(state['state'], 'human-correction-verifying')
        events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
        completion = next(e['payload'] for e in reversed(events) if e['type'] == 'human-correction-complete')
        update, = completion['document_updates']
        self.assertEqual(base64.b64decode(update['before_base64']), spec_before)
        self.assertEqual(base64.b64decode(update['after_base64']), spec_after)
        self.assertEqual(update['before_hash'], hashlib.sha256(spec_before).hexdigest())
        self.assertEqual(update['after_hash'], hashlib.sha256(spec_after).hexdigest())
        self.assertEqual(package_path.read_bytes(), package_before)
        self.assertEqual(store.load()['package_hash'], hash_before)
        self.assertEqual(store.approved_package()['slices'][0]['spec']['hash'], update['before_hash'])
        # Review names the product task's commit, while checks cover the newer
        # Coordinator document commit and the complete delivery content.
        self.assertEqual(self.sim.review(repo, store, 1, base, product_head)['state'], 'finalizing')
        self.sim.finalize_delivery(repo, store)
        self.assertEqual(package_path.read_bytes(), package_before)

    def test_undeclared_or_arbitrary_document_adjustment_is_rejected(self):
        for path, declared in [('docs/spec.md', []), ('docs/unrelated.md', [{'path': 'docs/unrelated.md', 'reason': 'local'}])]:
            with self.subTest(path=path):
                repo, store = self.sim.fixture('feature')
                self.sim.begin(store, close=True)
                self.product_result(repo, store)
                (repo / path).write_text('Unapproved document adjustment\n')
                git(repo, 'add', path)
                git(repo, 'commit', '-qm', 'Change documentation\n\nCogito-Amendment: TA-1')
                before = store.events_path.read_bytes()
                with self.assertRaises(runtime.CogitoError):
                    store.human_correction_complete(self.completion(repo, document_updates=declared), 'bad-doc-update')
                self.assertEqual(store.events_path.read_bytes(), before)
                self.assertEqual(store.load()['state'], 'human-correction')

    def two_rounds(self, repo, store):
        for number in (1, 2):
            self.sim.begin(store, number)
            base, head = self.sim.implement(repo, store, number)
            self.assertEqual(self.sim.review(repo, store, number, base, head)['state'], 'awaiting-human')
        self.sim.begin(store, 3, close=True)

    def assert_exhausted(self, repo, store, state):
        self.assertEqual(state['state'], 'blocked')
        self.assertEqual(state['counters']['human_corrections'], 3)
        self.assertEqual(json.loads(store.events_path.read_text().splitlines()[-1])['type'], 'human-correction-exhausted')
        restored = runtime.RunStore(repo, store.run_id)
        with self.assertRaises(runtime.CogitoError):
            restored.human_correction_start({'amendment_id': 'TA-4'}, 'illegal-fourth-start')
        self.assertEqual(restored.load()['counters']['human_corrections'], 3)

    def test_third_failed_controlled_check_blocks_immediately(self):
        repo, store = self.sim.fixture()
        self.two_rounds(repo, store)
        self.product_result(repo, store, 3, 'after still wrong\n')
        store.human_correction_complete(self.completion(repo, 3), 'third-complete')
        general = self.sim.check(store, repo, 'third-general')
        failed = self.sim.check(store, repo, 'third-label', 'C-human-label')
        self.assertTrue(general['passed'])
        self.assertFalse(failed['passed'])
        state = store.human_verify([general, failed], 'third-verification')
        self.assert_exhausted(repo, store, state)
        events = store.events_path.read_bytes()
        self.assertEqual(store.human_verify([general, failed], 'third-verification'), state)
        self.assertEqual(store.events_path.read_bytes(), events)

    def test_third_failed_independent_review_blocks_immediately(self):
        repo, store = self.sim.fixture()
        self.two_rounds(repo, store)
        base, head = self.sim.implement(repo, store, 3)
        evidence = [self.sim.check(store, repo, 'third-general'),
                    self.sim.check(store, repo, 'third-label', 'C-human-label')]
        store.human_verify(evidence, 'third-verification')
        result = self.sim.result(store, 'T-H-3', 'human-reviewer-3', base, head, reviewer_of='human-worker-3')
        result.update(status='needs-fix', requested_transition='review-fix', risks=['Label still misleading'])
        store.submit_agent_result(result)
        state = store.human_review('third-review')
        self.assert_exhausted(repo, store, state)
        events = store.events_path.read_bytes()
        self.assertEqual(store.human_review('third-review'), state)
        self.assertEqual(store.events_path.read_bytes(), events)


if __name__ == '__main__':
    unittest.main()
