"""One unfinished correction Task can handle related findings and path omissions."""
import copy
import sys
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))

from cogito_common import CogitoError
from cogito_execution_registry import register_external, record_external_receipt
from cogito_path_amendment_state import path_targets
from cogito_test_support import GitTestCase, git
import test_review_path_amendment as review_tests
import test_atomic_task_verification as verification_tests


class BatchedCorrectionRulesTests(unittest.TestCase):
    def test_only_this_cycles_unfinished_correction_can_expand(self):
        task = {'id': 'T-fix', 'slice_id': 'FS-1', 'status': 'running'}
        state = {'state': 'review-fix', 'tasks': {'T-fix': task}, 'agent_results': []}
        amendment = {'path_additions': [{'task_id': 'T-fix', 'paths': ['new.py'],
                                        'check_ids': ['C-fix'], 'reason': 'Related finding'}]}
        events = [
            {'type': 'review-fix-required', 'sequence': 10, 'payload': {}},
            {'type': 'technical-amendment-added', 'sequence': 11,
             'payload': {'amendment': {'added_tasks': [task]}}},
        ]
        original = copy.deepcopy((state, amendment, events))
        self.assertEqual(path_targets(state, amendment, events)['T-fix'], task)
        self.assertEqual((state, amendment, events), original)
        with self.assertRaisesRegex(CogitoError, 'this review cycle'):
            path_targets(state, amendment, [*events, {'type': 'review-fix-required', 'sequence': 20, 'payload': {}}])
        with self.assertRaisesRegex(CogitoError, 'completed'):
            path_targets({**state, 'tasks': {'T-fix': {**task, 'status': 'complete'}}}, amendment, events)
        with self.assertRaisesRegex(CogitoError, 'completed'):
            path_targets({**state, 'agent_results': [{'task_id': 'T-fix', 'role': 'implementer', 'status': 'complete'}]}, amendment, events)


class BatchedCorrectionFlowTests(GitTestCase):
    executing = review_tests.ReviewPathAmendmentTests.executing
    lease = staticmethod(review_tests.ReviewPathAmendmentTests.lease)
    commit = staticmethod(review_tests.ReviewPathAmendmentTests.commit)
    check = staticmethod(review_tests.ReviewPathAmendmentTests.check)
    result = staticmethod(review_tests.ReviewPathAmendmentTests.result)
    implement = review_tests.ReviewPathAmendmentTests.implement
    review = staticmethod(review_tests.ReviewPathAmendmentTests.review)
    fixture = review_tests.ReviewPathAmendmentTests.fixture

    def test_related_failure_and_missing_file_stay_in_one_task_and_branch(self):
        repo, worker, store, _, results, _, request = self.fixture()
        # A second Reviewer finding is handled in the same correction Task.
        store.submit_agent_result({**results[1], 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'status': 'needs-fix', 'changed_paths': [],
            'evidence': [], 'risks': ['Related response formatting'], 'requested_transition': 'review-fix'})
        store.enter_review_fix('start')
        store.path_amendment_propose(request, 'propose')
        store.path_amendment_review(self.review(store), 'apply')
        self.lease(store, 'T-map')
        original_task = copy.deepcopy(store.load()['tasks']['T-map'])
        branch = git(worker, 'branch', '--show-current')
        (worker/'mapping').mkdir()
        (worker/'mapping/value.py').write_text('wrong\n')
        failed = self.check(store, worker, 'C-map', 'failed-map')
        self.assertEqual(failed['status'], 'failed')
        register_external(repo, store.run_id, 'worker', 'batch-worker')
        record_external_receipt(repo, store.run_id, 'worker', 'batch-worker', {
            'provider': 'test', 'control_tool': 'interrupt_agent', 'event_id': 'stopped',
            'handle': 'batch-worker', 'status': 'interrupted',
            'raw_response': {'handle': 'batch-worker', 'status': 'interrupted'},
        })
        extra = {'author_id': 'coordinator', 'amendment': {
            'id': 'TA-format', 'reason': 'Related formatting helper omitted during this correction',
            'path_additions': [{'task_id': 'T-map', 'paths': ['mapping/format.py'],
                                'reason': 'Complete original response', 'check_ids': ['C-format']}],
            'added_checks': [{'id': 'C-format', 'phase': 'task', 'argv': [sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('mapping/format.py').read_text() == 'year\\n'"]}],
        }}
        store.path_amendment_propose(extra, 'expand')
        review = self.review(store)
        with mock.patch('cogito_path_amendment.atomic_create_json', side_effect=OSError('archive failed')):
            with self.assertRaises(OSError):
                store.path_amendment_review(review, 'review-expand')
        self.assertEqual(store.next_action()['next_action'], 'retry-path-amendment')
        events = store.events_path.read_bytes()
        store.path_amendment_review(review, 'review-expand')
        self.assertEqual(store.events_path.read_bytes(), events)
        task = store.load()['tasks']['T-map']
        self.assertEqual(task['base_commit'], original_task['base_commit'])
        self.assertEqual(task['agent_id'], original_task['agent_id'])
        self.assertEqual(task['status'], 'running')
        self.assertEqual(git(worker, 'branch', '--show-current'), branch)
        self.assertEqual(set(store.load()['tasks']), {'T-a', 'T-b', 'T-map'})
        (worker/'mapping/value.py').write_text('mapped\n')
        (worker/'mapping/format.py').write_text('year\n')
        git(worker, 'add', 'mapping')
        git(worker, 'commit', '-qm', 'fix related findings\n\nCogito-Amendment: TA-map')
        with self.assertRaises(CogitoError):
            store.finish_task('T-map', {'risks': []}, 'finish')
        checks = [self.check(store, worker, c, 'fresh-'+c) for c in ('C-map', 'C-format')]
        store.finish_task('T-map', {'risks': []}, 'finish')
        fixed = [r for r in store.load()['agent_results'] if r['task_id'] == 'T-map'][0]
        store.complete_review_fix('TA-map', fixed['head_commit'], 'complete')
        count = len(store.load()['evidence'])
        store.complete_verification(checks)
        verification_tests.AtomicVerificationTests.review(store, [*results, fixed])
        self.assertEqual(store.load()['state'], 'integrating')
        self.assertEqual(len(store.load()['evidence']), count)
        self.assertFalse((repo/'.cogito/replans').exists())
