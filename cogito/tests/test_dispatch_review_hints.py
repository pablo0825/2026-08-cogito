"""Execute advisory drafts through the existing CLI and retain Gate safeguards."""
import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
from cogito_next_operations import dispatch_hints, reviewer_hints
import test_atomic_task_verification as verification


class DispatchReviewHintTests(GitTestCase):
    def fixture(self):
        fixture = verification.AtomicVerificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def invoke(self, operation, repo, *, payload=None, action='hint-action', success=True):
        path = repo / '.cogito/hint-input.json'
        if payload is not None:
            path.write_text(json.dumps(payload))
        values = {'<action-id>': action, '<input.json>': str(path), '<agent-id>': 'real-worker'}
        command = [values.get(arg, arg) for arg in operation['argv']]
        result = subprocess.run(command, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout + result.stderr)
        return result

    @staticmethod
    def reviewed(draft):
        return {**draft, 'agent_id': 'independent-reviewer', 'status': 'complete',
                'changed_paths': [], 'evidence': [], 'risks': [], 'requested_transition': 'review-approved'}

    def test_dispatch_context_is_read_only_and_lease_command_uses_existing_gate(self):
        fixture = self.fixture()
        repo, worker, store, draft = fixture.executing()
        before = store.events_path.read_bytes()
        package_bytes = (repo / store.load()['package_path']).read_bytes()
        output = store.next_action()
        task, = output['dispatch_tasks']
        self.assertEqual(task['id'], 'T-a')
        self.assertEqual(task['paths'], ['src/a.txt'])
        self.assertEqual(task['check_ids'], ['C-a'])
        self.assertEqual(task['worktree'], str(worker.resolve()))
        self.assertEqual(task['documents']['spec'], draft['slices'][0]['spec'])
        task['paths'].append('unauthorized')
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual((repo / store.load()['package_path']).read_bytes(), package_bytes)
        self.assertEqual(store.next_action()['dispatch_tasks'][0]['paths'], ['src/a.txt'])
        self.invoke(task['operations'][0], repo)
        self.assertEqual(store.load()['tasks']['T-a']['agent_id'], 'real-worker')
        self.assertNotIn('dispatch_tasks', store.next_action())
        self.invoke(task['operations'][0], repo, action='stale-lease', success=False)

    def test_review_drafts_name_each_task_range_and_execute_without_fabricated_judgments(self):
        fixture = self.fixture()
        repo, _, store, _, results, evidence = fixture.wave()
        store.complete_verification([evidence[-1]])
        before = store.events_path.read_bytes()
        contexts = store.next_action()['review_tasks']
        self.assertEqual(len(contexts), 2)
        self.assertEqual(store.events_path.read_bytes(), before)
        for i, (context, result) in enumerate(zip(contexts, results)):
            operation, = context['operations']
            draft = operation['input']
            self.assertEqual(draft['head_commit'], result['head_commit'])
            self.assertEqual(draft['base_commit'], result['base_commit'])
            self.assertEqual(draft['reviewed_implementer'], 'worker')
            self.assertTrue(set(operation['required_inputs']).isdisjoint(draft))
            self.invoke(operation, repo, payload=draft, action=f'incomplete-{i}', success=False)
            self.invoke(operation, repo, payload=self.reviewed(draft), action=f'review-{i}')
            self.assertNotIn(context['id'], [t['id'] for t in store.next_action()['review_tasks']])
        store.transition('review-approved', {})
        self.assertEqual(store.load()['state'], 'integrating')

    def test_review_draft_does_not_bypass_independence_or_content_drift(self):
        fixture = self.fixture()
        repo, worker, store, _, _, evidence = fixture.wave()
        store.complete_verification([evidence[-1]])
        operation = store.next_action()['review_tasks'][0]['operations'][0]
        payload = self.reviewed(operation['input'])
        before = store.events_path.read_bytes()
        self.invoke(operation, repo, payload={**payload, 'agent_id': 'worker'}, success=False)
        (worker / 'src/a.txt').write_text('unverified change\n')
        self.invoke(operation, repo, payload=payload, action='stale-review', success=False)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_review_fix_overrides_normal_review_draft(self):
        fixture = self.fixture()
        _, _, store, _, _, evidence = fixture.wave()
        store.complete_verification([evidence[-1]])
        draft = store.next_action()['review_tasks'][0]['operations'][0]['input']
        store.submit_agent_result({**self.reviewed(draft), 'status': 'needs-fix',
                                  'requested_transition': 'review-fix', 'risks': ['fix implementation']})
        output = store.next_action()
        self.assertEqual(output['next_action'], 'prepare-review-fix')
        self.assertNotIn('review_tasks', output)

    def test_old_review_does_not_close_new_cycle_and_missing_records_are_not_invented(self):
        fixture = self.fixture()
        _, _, store, _, _, evidence = fixture.wave()
        store.complete_verification([evidence[-1]])
        state = store.load()
        result = self.reviewed(store.next_action()['review_tasks'][0]['operations'][0]['input'])
        events = [{'type': 'agent-result-recorded', 'sequence': 1, 'payload': {'result': result}},
                  {'type': 'verification-passed', 'sequence': 2, 'payload': {}}]
        view = SimpleNamespace(root=store.root, run_id=store.run_id,
            _approved_package_from_state=store._approved_package_from_state,
            _events=SimpleNamespace(read=lambda: events))
        self.assertEqual(len(reviewer_hints(view, state)['review_tasks']), 2)
        state = copy.deepcopy(state)
        state['agent_results'] = []
        hints = reviewer_hints(view, state)['review_tasks']
        self.assertTrue(all(t['blockers'] and not t['operations'] for t in hints))

    def test_historical_mini_context_does_not_invent_atomic_fields(self):
        package = {'kind': 'maintenance', 'delivery_branch': 'main', 'slices': []}
        task = {'id': 'T-old', 'paths': ['src/old.py']}
        store = SimpleNamespace(root=Path('/example'), run_id='DEV-old',
                                _approved_package_from_state=lambda state: package)
        context = dispatch_hints(store, {'tasks': {'T-old': task}}, ['T-old'])['dispatch_tasks'][0]
        self.assertEqual(context['worktree'], '/example')
        self.assertNotIn('responsibility', context)
        self.assertNotIn('check_ids', context)

    def test_recovery_takes_precedence_over_ready_dispatch(self):
        fixture = self.fixture()
        _, _, store, _ = fixture.executing()
        for category in ('unknown_outcome', 'published_evidence', 'proven_pre_execution_failure'):
            with self.subTest(category=category), patch('cogito_next_operations.check_recovery_hints',
                    return_value={'check_recovery': [{'category': category}], 'operations': []}):
                self.assertEqual(store.next_action()['dispatch_tasks'], [])
        with patch('cogito_next_operations.check_recovery_hints', side_effect=CogitoError('unreadable')):
            self.assertEqual(store.next_action()['dispatch_tasks'], [])
        with patch('cogito_next_operations.check_recovery_hints',
                return_value={'check_recovery': [{'category': 'not_started'}], 'operations': []}):
            self.assertEqual(len(store.next_action()['dispatch_tasks']), 1)

    def test_maintenance_head_failure_is_a_task_blocker(self):
        package = {'kind': 'maintenance', 'delivery_branch': 'main', 'slices': []}
        task = {'id': 'T-old', 'paths': [], 'status': 'verified', 'agent_id': 'worker',
                'worktree': '/example', 'branch': 'main', 'base_commit': 'a' * 40}
        state = {'tasks': {'T-old': task}, 'agent_results': [
            {'task_id': 'T-old', 'role': 'implementer', 'status': 'complete',
             'base_commit': 'a' * 40, 'head_commit': 'a' * 40}]}
        store = SimpleNamespace(root=Path('/example'), run_id='DEV-old',
            _approved_package_from_state=lambda state: package,
            _events=SimpleNamespace(read=lambda: []), _git_at=lambda *args: 'b' * 40)
        context, = reviewer_hints(store, state)['review_tasks']
        self.assertEqual(context['operations'][0]['input']['head_commit'], 'b' * 40)
        with patch.object(store, '_git_at', side_effect=CogitoError('checkout unavailable')):
            context, = reviewer_hints(store, state)['review_tasks']
        self.assertEqual(context['operations'], [])
        self.assertEqual(context['blockers'], ['checkout unavailable'])
