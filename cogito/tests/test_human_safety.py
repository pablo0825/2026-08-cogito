"""Adversarial human-return Gates against real delivery trees and evidence."""
from __future__ import annotations

import json
import sys
from unittest import mock

from cogito_test_support import GitTestCase, git
import cogito_runtime as runtime
import test_human_acceptance as acceptance


class HumanSafetyTests(GitTestCase):
    # Reuse scenario construction without inheriting/discovering its test cases.
    fixture = acceptance.HumanAcceptanceTests.fixture
    begin = acceptance.HumanAcceptanceTests.begin
    implement = acceptance.HumanAcceptanceTests.implement
    result = staticmethod(acceptance.HumanAcceptanceTests.result)
    check = staticmethod(acceptance.HumanAcceptanceTests.check)
    feedback = staticmethod(acceptance.HumanAcceptanceTests.feedback)

    def classify(self, store, mixed=False):
        store.human_feedback(self.feedback(mixed=mixed), 'feedback')
        assessments = [{'id': 'I-1', 'disposition': 'local', 'reason': 'Bounded label repair'}]
        if mixed:
            assessments.append({'id': 'I-2', 'disposition': 'change', 'reason': 'Changes interaction flow'})
        return store.human_triage({'feedback_id': 'HF-1', 'assessments': assessments}, 'triage')

    @staticmethod
    def amendment(number):
        return {'id': f'TA-{number}', 'reason': 'Bounded label repair', 'added_tasks': [
            {'id': f'T-H-{number}', 'slice_id': 'mini-package', 'paths': ['src/note.txt']},
        ]}

    def record_implementation(self, repo, store, number=1):
        task, agent = f'T-H-{number}', f'human-worker-{number}'
        base = git(repo, 'rev-parse', 'HEAD')
        store.update_task(task, 'leased', agent)
        store.update_task(task, 'running', agent)
        (repo / 'src/note.txt').write_text(f'after corrected {number}\n')
        if store.load()['kind'] == 'feature':
            git(repo, 'add', 'src/note.txt')
            git(repo, 'commit', '-qm', f'Repair label\n\nCogito-Amendment: TA-{number}')
        head = git(repo, 'rev-parse', 'HEAD')
        store.submit_agent_result(self.result(store, task, agent, base, head))
        store.update_task(task, 'complete', agent)
        return base, head

    @staticmethod
    def completion(head, number=1):
        return {'feedback_id': 'HF-1', 'amendment_id': f'TA-{number}', 'commit_id': head,
                'resolved_item_ids': ['I-1'], 'summary': 'Corrected label'}

    def test_optional_only_stale_and_failed_evidence_cannot_verify(self):
        original_prepare = runtime.RunStore.prepare_package

        def prepare_optional(store, draft, *args, **kwargs):
            for check in draft['checks']:
                check['required'] = False
            draft['checks'].append({'id': 'C-optional-failing', 'required': False, 'argv': [
                sys.executable, '-I', '-c', 'raise SystemExit(1)',
            ]})
            return original_prepare(store, draft, *args, **kwargs)

        with mock.patch.object(runtime.RunStore, 'prepare_package', prepare_optional):
            repo, store = self.fixture()
        stale = json.loads(sorted((store.run_dir / 'evidence').glob('C-1-*.json'))[-1].read_text())
        self.classify(store)
        store.add_amendment(self.amendment(1), 'amendment')
        store.human_correction_start({'amendment_id': 'TA-1'}, 'start')
        self.implement(repo, store)
        failed = self.check(store, repo, 'optional-fail', 'C-optional-failing')
        self.assertFalse(failed['passed'])
        for name, evidence in [('stale', stale), ('failed', failed)]:
            with self.subTest(evidence=name):
                before = store.events_path.read_bytes()
                with self.assertRaises(runtime.CogitoError):
                    store.human_verify([evidence], f'reject-{name}')
                self.assertEqual(before, store.events_path.read_bytes())
        fresh = self.check(store, repo, 'optional-pass')
        self.assertEqual(store.human_verify([fresh], 'accept-fresh')['state'], 'human-correction-reviewing')

    def test_content_drift_after_implementer_result_prevents_completion(self):
        for kind in ('maintenance', 'feature'):
            with self.subTest(kind=kind):
                repo, store = self.fixture(kind)
                self.begin(store)
                _, head = self.record_implementation(repo, store)
                (repo / 'src/note.txt').write_text('after unreported extra modification\n')
                before = store.events_path.read_bytes()
                with self.assertRaises(runtime.CogitoError):
                    store.human_correction_complete(self.completion(head), 'drift-complete')
                self.assertEqual(before, store.events_path.read_bytes())
                self.assertEqual(store.load()['state'], 'human-correction')

    def test_retry_requires_reviews_for_all_tasks_in_current_feedback(self):
        repo, store = self.fixture()
        self.begin(store, close=True)
        base1, head1 = self.implement(repo, store)
        store.add_amendment(self.amendment(2), 'retry-amendment')
        store.human_correction_start({'amendment_id': 'TA-2'}, 'retry-start')
        base2, head2 = self.record_implementation(repo, store, 2)
        store.human_correction_complete(self.completion(head2, 2), 'retry-complete')
        self.assertEqual(set(store.load()['human']['cohort_task_ids']), {'T-H-1', 'T-H-2'})
        store.human_verify([self.check(store, repo, 'retry-base-check'),
                            self.check(store, repo, 'retry-label-check', 'C-human-label')], 'retry-verify')
        store.submit_agent_result(self.result(store, 'T-H-2', 'reviewer-2', base2, head2,
                                             reviewer_of='human-worker-2'))
        with self.assertRaises(runtime.CogitoError):
            store.human_review('missing-earlier-review')
        self.assertEqual(store.load()['state'], 'human-correction-reviewing')
        store.submit_agent_result(self.result(store, 'T-H-1', 'reviewer-1', base1, head1,
                                             reviewer_of='human-worker-1'))
        self.assertEqual(store.human_review('all-reviews')['state'], 'finalizing')

    def test_mixed_feedback_cannot_be_relabelled_local_without_deferring_changes(self):
        repo, store = self.fixture()
        self.classify(store, mixed=True)
        assessments = [{'id': item, 'disposition': 'local', 'reason': 'Reclassification attempt'}
                       for item in ('I-1', 'I-2')]
        for extra in ({}, {'deferred_item_ids': ['I-1'], 'split_authorized': True,
                          'split_reason': 'User only authorized the typo repair now'}):
            with self.subTest(split=extra):
                before = store.events_path.read_bytes()
                with self.assertRaises(runtime.CogitoError):
                    store.human_triage({'feedback_id': 'HF-1', 'assessments': assessments, **extra},
                                       'reject-' + str(len(extra)))
                self.assertEqual(before, store.events_path.read_bytes())
        state = store.human_triage({'feedback_id': 'HF-1', 'assessments': assessments,
                                   'deferred_item_ids': ['I-2'], 'split_authorized': True,
                                   'split_reason': 'User explicitly postpones auto-query'}, 'explicit-split')
        self.assertEqual(state['human']['triage']['route'], 'local')
        self.assertEqual(state['human']['triage']['active_item_ids'], ['I-1'])
        self.assertEqual(state['human']['triage']['deferred_item_ids'], ['I-2'])

    def test_only_one_unconsumed_human_amendment_can_exist(self):
        repo, store = self.fixture()
        self.classify(store)
        store.add_amendment(self.amendment(1), 'first-amendment')
        before = store.events_path.read_bytes()
        with self.assertRaises(runtime.CogitoError):
            store.add_amendment(self.amendment(2), 'second-amendment')
        self.assertEqual(before, store.events_path.read_bytes())
        self.assertNotIn('T-H-2', store.load()['tasks'])

    def test_human_correction_cannot_dispatch_unrelated_task(self):
        repo, store = self.fixture()
        self.begin(store)
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(runtime.CogitoError, 'only its current amendment tasks'):
            store.update_task('T-1', 'leased', 'unrelated-worker')
        self.assertEqual(before, store.events_path.read_bytes())


if __name__ == '__main__':
    import unittest
    unittest.main()
