"""Cross-round and interrupted-preparation integrity with actual Git files."""
import copy
import json
import unittest
from unittest import mock

import test_planning_rounds as support
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_events import append_event
from cogito_common import atomic_write_json


class PlanningIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.f = support.PlanningRoundTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.store = self.f.store

    def test_confirmed_but_unfinished_round_can_restart_after_new_user_decision(self):
        f = self.f
        f.begin()
        digest = f.new['shared_understanding']['hash']
        self.store.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': digest,
            'document': f.new['shared_understanding']}, 'ready2')
        self.store.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'confirmed': True, 'shared_understanding_hash': digest}, 'confirm2')
        old_events = self.store.events_path.read_bytes()
        # A changed file is unknown on automatic recovery, but a new explicit
        # planning request can reconcile it without restoring obsolete content.
        (f.repo / f.new['shared_understanding']['path']).write_text('Unconfirmed external change\n')
        with self.assertRaises(CogitoError):
            self.store.planning_recover()
        newer = f.document('round3/shared', 'Only show unfinished items; omit all other filtering.\n')
        request = {**f.request(), 'round': 2, 'reason': 'User explicitly narrowed filtering again.'}
        self.store.planning_begin(request, 'begin3')
        self.assertEqual(self.store.load()['planning']['round'], 3)
        self.store.transition('shared-understanding-ready', {
            'planning_round': 3, 'shared_understanding_hash': newer['hash'], 'document': newer}, 'ready3')
        self.store.transition('shared-understanding-confirmed', {
            'planning_round': 3, 'confirmed': True, 'shared_understanding_hash': newer['hash']}, 'confirm3')
        self.store.transition('boundary-complete', {**f.new['boundary'], 'planning_round': 3}, 'boundary3')
        draft = {**f.new, 'planning_round': 3, 'shared_understanding': newer}
        self.store.prepare_package(draft, 'prepare3')
        review = {**f.review_request(), 'round': 3}
        self.store.planning_review(review, 'review3')
        self.store.approve_package(draft, 'approve3')
        self.assertTrue(self.store.events_path.read_bytes().startswith(old_events))

    def test_old_review_and_prepare_replay_cannot_restore_round_two_authority(self):
        f = self.f
        f.begin()
        f.prepare_revision()
        review2 = f.review_request()
        self.store.planning_review(review2, 'review2')
        request = {**f.request('plan'), 'round': 2, 'candidate_hash': package_hash(f.new)}
        self.store.planning_begin(request, 'begin3')
        before = self.store.events_path.read_bytes()
        self.store.planning_review(review2, 'review2')
        self.store.prepare_package(f.new, 'new-prepare')
        self.assertEqual(self.store.events_path.read_bytes(), before)
        self.assertIsNone(self.store.load()['planning']['review'])
        newer = {**f.new, 'planning_round': 3}
        self.store.prepare_package(newer, 'prepare3')
        with self.assertRaises(CogitoError):
            self.store.approve_package(newer, 'approve3-with-old-review')
        self.store.planning_review({**f.review_request(), 'round': 3}, 'review3')
        self.store.approve_package(newer, 'approve3')

    def test_block_resume_and_recover_refuse_changed_confirmed_document(self):
        f = self.f
        f.begin()
        f.prepare_revision()
        self.store.transition('block', {'reason': 'interrupted planning'}, 'block')
        path = f.repo / f.new['shared_understanding']['path']
        original = path.read_bytes()
        path.write_text('Someone restored JSON export to the confirmed scope.\n')
        before = self.store.events_path.read_bytes()
        for call in (self.store.planning_recover, lambda: self.store.resume_gate('resume')):
            with self.assertRaises(CogitoError):
                call()
            self.assertEqual(self.store.events_path.read_bytes(), before)
        path.write_bytes(original)
        self.store.resume_gate('resume')
        self.assertEqual(self.store.planning_recover()['next_action'], 'request-independent-planning-review')

    def test_snapshot_comparison_preserves_old_bytes_after_working_copy_changes(self):
        f = self.f
        f.begin()
        f.prepare_revision()
        old_path = f.old['slices'][0]['spec']['path']
        old_text = (f.repo / old_path).read_text()
        (f.repo / old_path).write_text('Overwritten later, without changing saved history.\n')
        result = self.store.planning_compare(1, 2)
        self.assertEqual(len(result['package_changes']['slices']['before']), 3)
        self.assertEqual(len(result['package_changes']['slices']['after']), 1)
        self.assertEqual(result['document_changes'][old_path]['before']['text'], old_text)
        self.store.state_path.write_text('{"state":"accepted"}')
        self.assertEqual(self.store.load()['state'], 'awaiting-package-approval')

    def test_boundary_level_reuses_scope_but_requires_new_boundary_event(self):
        f = self.f
        self.store.planning_begin(f.request('boundary'), 'begin-boundary')
        draft = {**f.old, 'planning_round': 2,
                 'boundary': {'decision': 'split-required', 'evidence': ['Reassessed three independent responsibilities.']}}
        with self.assertRaises(CogitoError):
            self.store.prepare_package(draft, 'skip-boundary')
        self.store.transition('boundary-complete', {**draft['boundary'], 'planning_round': 2}, 'boundary2')
        changed = copy.deepcopy(draft)
        changed['checks'][0]['argv'] = ['python3', '-V']
        with self.assertRaises(CogitoError):
            self.store.prepare_package(changed, 'changed-acceptance')
        self.store.prepare_package(draft, 'prepare2')
        self.store.planning_review(f.review_request(), 'review2')
        self.store.approve_package(draft, 'approve2')

    def test_protected_gate_event_and_round_schema_cannot_be_bypassed(self):
        f = self.f
        for request in ({}, {**f.request(), 'round': True}, {**f.request(), 'candidate_hash': []}):
            with self.assertRaises(CogitoError):
                self.store.planning_begin(request, 'bad-request')
        f.begin()
        f.prepare_revision()
        for event in ('planning-begun', 'planning-reviewed', 'planning-withdrawn'):
            with self.assertRaises(CogitoError):
                self.store.record(event, {}, 'direct-' + event)
        with self.assertRaises(CogitoError):
            self.store.record('package-approved', {'package_hash': package_hash(f.new)},
                              'internal-without-review', self.store._GATE_AUTHORITY)
        before = self.store.events_path.read_bytes()
        self.store.transition('shared-understanding-confirmed', {'confirmed': True}, 'old-confirm')
        self.assertEqual(self.store.events_path.read_bytes(), before)
        self.assertEqual(self.store.load()['planning']['round'], 2)

    def test_legacy_candidate_requires_exact_source_and_becomes_comparable(self):
        f = self.f
        # Reconstruct a historical journal in this disposable fixture, without
        # inventing a snapshot that the legacy runtime never captured.
        original = self.store._events.read()
        self.store.events_path.unlink()
        for event in original:
            body = {'type': event['type'], 'payload': copy.deepcopy(event['payload']),
                    'action_id': event.get('action_id'), 'request_hash': event.get('request_hash')}
            body['payload'].pop('candidate_snapshot', None)
            append_event(self.store.events_path, body)
        before = self.store.events_path.read_bytes()
        for request in (f.request(), {**f.request(), 'source_package': True}):
            with self.assertRaises(CogitoError):
                self.store.planning_begin(request, 'legacy-begin')
            self.assertEqual(self.store.events_path.read_bytes(), before)
        self.store.planning_begin({**f.request(), 'source_package': f.old}, 'legacy-begin')
        f.prepare_revision()
        result = self.store.planning_compare(1, 2)
        self.assertEqual(len(result['package_changes']['slices']['before']), 3)
        self.assertEqual(len(result['package_changes']['slices']['after']), 1)

    def test_document_change_during_approval_publication_rolls_back(self):
        f = self.f
        f.begin()
        f.prepare_revision()
        self.store.planning_review(f.review_request(), 'review2')
        graph = f.repo / 'docs/cogito/project-graph.json'
        canonical = f.repo / f'docs/cogito/packages/{self.store.run_id}.json'
        before = self.store.events_path.read_bytes()

        def change_document_after_graph(path, value):
            atomic_write_json(path, value)
            if path == graph:
                (f.repo / f.new['slices'][0]['spec']['path']).write_text('External edit during approval.\n')

        with mock.patch('cogito_approval.atomic_write_json', side_effect=change_document_after_graph):
            with self.assertRaisesRegex(CogitoError, 'drifted'):
                self.store.approve_package(f.new, 'approve-drift')
        self.assertFalse(graph.exists())
        self.assertFalse(canonical.exists())
        self.assertEqual(self.store.events_path.read_bytes(), before)

    def test_revised_boundary_must_match_slice_count(self):
        f = self.f
        f.begin()
        digest = f.new['shared_understanding']['hash']
        self.store.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': digest,
            'document': f.new['shared_understanding']}, 'ready2')
        self.store.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'confirmed': True, 'shared_understanding_hash': digest}, 'confirm2')
        self.store.transition('boundary-complete', {**f.old['boundary'], 'planning_round': 2}, 'bad-boundary2')
        draft = {**f.new, 'boundary': f.old['boundary']}
        with self.assertRaisesRegex(CogitoError, 'Slice structure'):
            self.store.prepare_package(draft, 'contradictory-candidate')


if __name__ == '__main__':
    unittest.main()
