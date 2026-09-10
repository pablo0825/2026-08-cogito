"""Next directs the next operation and removes conflicting recovery commands."""
import subprocess
from unittest.mock import patch

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
import test_dispatch_review_hints as support


class NextHandoffTests(GitTestCase):
    fixture = support.DispatchReviewHintTests.fixture
    invoke = support.DispatchReviewHintTests.invoke

    def test_lease_register_running_round_trip(self):
        fixture = self.fixture()
        repo, _, store, _ = fixture.executing()
        self.invoke(store.next_action()['dispatch_tasks'][0]['operations'][0], repo)
        events = store.events_path.read_bytes()
        output = store.next_action()
        self.assertEqual(output['next_action'], 'start-leased-workers')
        task, = output['leased_tasks']
        self.assertEqual(task['operations'], [])
        self.assertEqual(len(task['registration_choices']), 2)
        command = [arg if arg != '<executor-handle>' else 'test-provider-handle'
                   for arg in task['registration_choices'][0]['argv']]
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(store.events_path.read_bytes(), events)
        output = store.next_action()
        task, = output['leased_tasks']
        self.assertNotIn('registration_choices', task)
        self.invoke(task['operations'][0], repo, action='start-worker')
        self.assertEqual(store.load()['tasks']['T-a']['status'], 'running')
        self.assertNotIn('leased_tasks', store.next_action())

    def test_executor_stop_and_unknown_identity_do_not_offer_running(self):
        fixture = self.fixture()
        repo, _, store, _ = fixture.executing()
        self.invoke(store.next_action()['dispatch_tasks'][0]['operations'][0], repo)
        for observation in ('attested', 'terminated', 'identity-mismatch', 'unverified-shared-group'):
            with self.subTest(observation=observation), patch('cogito_execution_registry.observe_read_only',
                    return_value={'stop_requested': False, 'entries': {'real-worker': {'observation': observation}}}):
                task, = store.next_action()['leased_tasks']
                self.assertTrue(task['blockers'])
                self.assertEqual(task['operations'], [])
        with patch('cogito_execution_registry.observe_read_only', return_value={'stop_requested': True}):
            output = store.next_action()
        self.assertEqual(output['next_action'], 'resolve-executor-registration')
        self.assertEqual(output['operations'], [])
        state = store.load()
        state['tasks']['T-b'].update(slice_id='FS-other', depends_on=[])
        with patch.object(store, 'load', return_value=state), patch(
                'cogito_next_operations.dispatch_hints', return_value={'dispatch_tasks': ['would-dispatch']}), patch(
                'cogito_execution_registry.observe_read_only', return_value={'stop_requested': True}):
            output = store.next_action()
        self.assertEqual(output['next_action'], 'resolve-executor-registration')
        self.assertNotIn('dispatch_tasks', output)

    def test_recovery_error_discards_prepared_verification_operation(self):
        fixture = self.fixture()
        _, _, store, _ = fixture.executing()
        state = store.load()
        state['state'] = 'verifying'
        with patch.object(store, 'load', return_value=state), patch(
                'cogito_next_operations.verification_hints', return_value={
                    'next_action': 'submit-verification', 'operations': [{'operation': 'verify'}]}), patch(
                'cogito_next_operations.check_recovery_hints', side_effect=CogitoError('unreadable outcome')):
            output = store.next_action()
        self.assertEqual(output['next_action'], 'resolve-check-recovery')
        self.assertEqual(output['operations'], [])
        self.assertEqual(output['check_recovery'][0]['category'], 'unknown_outcome')

    def test_large_recovery_scope_does_not_keep_normal_commands(self):
        fixture = self.fixture()
        _, _, store, _ = fixture.executing()
        fixture.lease(store)
        with patch('cogito_next_operations.check_recovery_hints', return_value={
                'check_recovery': [{'category': 'scope_too_large'}]}):
            output = store.next_action()
        self.assertEqual(output['next_action'], 'resolve-check-recovery')
        self.assertEqual(output['operations'], [])
        self.assertNotIn('leased_tasks', output)

    def test_known_recovery_exposes_only_original_recovery_operation(self):
        fixture = self.fixture()
        _, _, store, _ = fixture.executing()
        fixture.lease(store)
        recovery = {'operation': 'run-check', 'argv': ['original-action']}
        with patch('cogito_next_operations.check_recovery_hints', return_value={
                'check_recovery': [{'category': 'published_evidence'}], 'operations': [recovery]}):
            output = store.next_action()
        self.assertEqual(output['next_action'], 'resolve-check-recovery')
        self.assertEqual(output['operations'], [recovery])
