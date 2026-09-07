"""Exercise same-run planning through real CLI processes and Git repositories."""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from unittest import mock

from cogito_test_support import COGITO, GitTestCase
from cogito_contracts import package_hash
from cogito_common import CogitoError
from cogito_run_store import RunStore
import test_planning_rounds as round_fixture


class PlanningCliTests(GitTestCase):
    def setUp(self):
        super().setUp()
        # Reuse the repository builder without inheriting/discovering its tests.
        self.fixture = round_fixture.PlanningRoundTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.repo = self.fixture.repo
        self.store = self.fixture.store
        self.run_id = self.store.run_id
        self.input_number = 0

    def invoke(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(COGITO / 'scripts/cogito_gate.py'), '--repo', str(self.repo), *args],
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        return json.loads(result.stdout)['data'] if ok else result.stderr

    def input_file(self, value):
        self.input_number += 1
        path = self.repo / '.cogito' / f'cli-input-{self.input_number}.json'
        path.write_text(json.dumps(value))
        return str(path)

    def planning(self, operation, value=None, action=None, ok=True):
        args = ['planning', operation, '--run-id', self.run_id]
        if value is not None:
            args.extend(['--input', self.input_file(value)])
        if action is not None:
            args.extend(['--action-id', action])
        return self.invoke(*args, ok=ok)

    def transition(self, event, payload, action):
        return self.invoke('transition', '--run-id', self.run_id, '--event', event,
                           '--payload-json', json.dumps(payload), '--action-id', action)

    def prepare_second_round(self, begin=True):
        if begin:
            self.planning('begin', self.fixture.request(), 'cli-begin')
        package = self.fixture.new
        digest = package['shared_understanding']['hash']
        self.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': digest,
            'document': package['shared_understanding']}, 'cli-ready')
        self.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'confirmed': True,
            'shared_understanding_hash': digest}, 'cli-confirm')
        self.transition('boundary-complete', {**package['boundary'], 'planning_round': 2}, 'cli-boundary')
        return self.invoke('prepare-package', '--run-id', self.run_id,
                           '--package', self.input_file(package), '--action-id', 'cli-prepare')

    def test_cli_multiple_rounds_keep_history_and_reject_old_review_and_approval(self):
        original_events = self.store.events_path.read_bytes()
        self.prepare_second_round()
        second_review = self.fixture.review_request()
        self.planning('review', second_review, 'cli-review2')
        request = self.fixture.request('plan')
        request.update(round=2, candidate_hash=package_hash(self.fixture.new),
                       reason='Refine implementation stop conditions; preserve filtering scope.')
        self.planning('begin', request, 'cli-begin3')
        third = copy.deepcopy(self.fixture.new)
        third['planning_round'] = 3
        third['stop_conditions'].append('Stop if filtering behavior diverges from the confirmed requirement.')
        self.invoke('prepare-package', '--run-id', self.run_id,
                    '--package', self.input_file(third), '--action-id', 'cli-prepare3')
        before_rejection = self.store.events_path.read_bytes()
        self.planning('review', second_review, 'cli-stale-review', ok=False)
        self.invoke('approve', '--run-id', self.run_id, '--package',
                    self.input_file(self.fixture.new), '--action-id', 'cli-stale-approval', ok=False)
        self.assertEqual(self.store.events_path.read_bytes(), before_rejection)
        third_review = self.fixture.review_request()
        third_review['round'] = 3
        self.planning('review', third_review, 'cli-review3')
        result = self.invoke('approve', '--run-id', self.run_id, '--package',
                             self.input_file(third), '--action-id', 'cli-approve3')
        self.assertEqual(result['state'], 'start-gate')
        self.assertEqual(self.store.load()['package_hash'], package_hash(third))
        history = self.planning('history')
        self.assertEqual(history['planning']['round'], 3)
        entries = history['history']
        self.assertEqual(sum(e['type'] == 'planning-begun' for e in entries), 2)
        snapshots = [e['payload']['candidate_snapshot'] for e in entries
                     if e['type'] == 'package-ready']
        self.assertEqual([s['round'] for s in snapshots], [1, 2, 3])
        self.assertEqual([package_hash(s['package']) for s in snapshots],
                         [package_hash(self.fixture.old), package_hash(self.fixture.new), package_hash(third)])
        self.assertTrue(self.store.events_path.read_bytes().startswith(original_events))

    def test_cli_withdraw_survives_cache_loss_and_retry_without_duplicate_events(self):
        self.prepare_second_round()
        request = {'round': 2, 'authorized': True, 'reason': 'User explicitly keeps the original scope.'}
        self.store.state_path.unlink()
        restored = self.planning('withdraw', request, 'cli-withdraw')
        self.assertEqual(restored['state'], 'awaiting-package-approval')
        self.assertEqual(restored['next']['candidate_package_hash'], package_hash(self.fixture.old))
        recorded = self.store.events_path.read_bytes()
        self.store.state_path.unlink()
        replayed = self.planning('withdraw', request, 'cli-withdraw')
        self.assertEqual(replayed, restored)
        self.assertEqual(self.store.events_path.read_bytes(), recorded)
        history = self.planning('history')
        self.assertEqual(sum(e['type'] == 'planning-withdrawn' for e in history['history']), 1)
        self.assertIn(package_hash(self.fixture.new), json.dumps(history))
        approved = self.invoke('approve', '--run-id', self.run_id,
                               '--package', self.input_file(self.fixture.old), '--action-id', 'cli-original')
        self.assertEqual(approved['state'], 'start-gate')

    def test_cli_rejects_missing_arguments_and_invalid_request_shapes_without_mutation(self):
        before = self.store.events_path.read_bytes()
        self.planning('begin', ok=False)
        self.planning('begin', [], 'wrong-shape', ok=False)
        invalid = self.fixture.request()
        invalid['round'] = '1'
        self.planning('begin', invalid, 'wrong-round-type', ok=False)
        invalid = self.fixture.request()
        invalid['impact'].pop('requirements')
        self.planning('begin', invalid, 'missing-impact', ok=False)
        self.assertEqual(self.store.events_path.read_bytes(), before)
        self.planning('begin', self.fixture.request(), 'valid-begin')
        begun = self.store.events_path.read_bytes()
        self.planning('withdraw', {'round': 2, 'authorized': False, 'reason': 'No user decision.'},
                      'unauthorized-withdraw', ok=False)
        self.planning('review', {}, 'premature-review', ok=False)
        self.assertEqual(self.store.events_path.read_bytes(), begun)
        self.assertEqual(RunStore(self.repo, self.run_id).load()['state'], 'preparing')

    def test_durable_mutations_recover_via_cli_after_cache_write_failure(self):
        def fail_cache_then_retry(operation, request, action, expected_state):
            method = getattr(self.store, 'planning_' + operation)
            with mock.patch('cogito_event_repository.atomic_write_json',
                            side_effect=OSError('Injected cache write failure after durable event')):
                with self.assertRaisesRegex(CogitoError, 'state cache could not be refreshed'):
                    method(request, action)
            durable = self.store.events_path.read_bytes()
            entries = [json.loads(line) for line in durable.splitlines()]
            self.assertEqual(sum(e['action_id'] == action for e in entries), 1)
            restored = self.planning(operation, request, action)
            self.assertEqual(restored['state'], expected_state)
            self.assertEqual(self.store.events_path.read_bytes(), durable)
            self.assertEqual(json.loads(self.store.state_path.read_text()), self.store.load())

        fail_cache_then_retry('begin', self.fixture.request(), 'durable-begin', 'preparing')
        self.prepare_second_round(begin=False)
        fail_cache_then_retry('review', self.fixture.review_request(), 'durable-review',
                              'awaiting-package-approval')
        fail_cache_then_retry('withdraw', {
            'round': 2, 'authorized': True, 'reason': 'User explicitly withdraws this revision.'},
            'durable-withdraw', 'awaiting-package-approval')
        self.assertEqual(self.store.load()['candidate_package_hash'], package_hash(self.fixture.old))

    def test_cli_compare_uses_saved_versions_and_recover_rejects_document_drift(self):
        self.prepare_second_round()
        comparison_args = ('planning', 'compare', '--run-id', self.run_id,
                           '--from-round', '1', '--to-round', '2')
        comparison = self.invoke(*comparison_args)
        self.assertEqual(len(comparison['package_changes']['slices']['before']), 3)
        self.assertEqual(len(comparison['package_changes']['slices']['after']), 1)
        shared_path = self.fixture.new['shared_understanding']['path']
        self.assertIn('Deliver filtering only', comparison['document_changes'][shared_path]['diff'])
        before = self.store.events_path.read_bytes()
        self.store.state_path.unlink()
        recovered = self.planning('recover')
        self.assertEqual(recovered['planning_round'], 2)
        self.assertEqual(recovered['next_action'], 'request-independent-planning-review')
        path = self.repo / self.fixture.new['slices'][0]['spec']['path']
        path.write_text('Unexpected external change: add JSON export.\n')
        self.assertEqual(self.invoke(*comparison_args), comparison)
        self.planning('recover', ok=False)
        self.planning('compare', ok=False)
        self.invoke('planning', 'compare', '--run-id', self.run_id,
                    '--from-round', '1', '--to-round', '99', ok=False)
        self.assertEqual(self.store.events_path.read_bytes(), before)
