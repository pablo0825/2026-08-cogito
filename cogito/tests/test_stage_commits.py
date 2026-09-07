"""Confirmed preparation must survive checkout through separate Git commits."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

from cogito_test_support import COGITO, GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_run_store import RunStore


class StageCommitTests(GitTestCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name).resolve()
        init_repo(self.repo)
        (self.repo / '.gitignore').write_text('.cogito/\n')
        git(self.repo, 'add', '.gitignore')
        git(self.repo, 'commit', '-qm', 'baseline')
        self.base = git(self.repo, 'rev-parse', 'HEAD')
        self.value = package()
        self.value['baseline_commit'] = self.base
        self.store = RunStore(self.repo, self.value['run_id'])
        self.store.create('feature', stage_commits=True)
        self.value['shared_understanding'] = self.document('docs/cogito/shared.md', '已確認的需求\r\n')
        for sl in self.value['slices']:
            for key in ('spec', 'plan'):
                sl[key] = self.document(sl[key]['path'], key + '\n')

    def document(self, path, text):
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        data = text.encode('utf-8')
        target.write_bytes(data)
        return {'path': path, 'hash': hashlib.sha256(data).hexdigest()}

    def confirm(self, suffix='', round_number=None):
        shared = self.value['shared_understanding']
        payload = {'shared_understanding_hash': shared['hash'], 'document': shared}
        confirmation = {'confirmed': True, 'shared_understanding_hash': shared['hash']}
        if round_number:
            payload['planning_round'] = confirmation['planning_round'] = round_number
        self.store.transition('shared-understanding-ready', payload, 'ready' + suffix)
        self.store.transition('shared-understanding-confirmed', confirmation, 'confirm' + suffix)

    def commit(self, action):
        result = self.store.prepare_checkpoint()
        git(self.repo, 'add', '--', *result['paths'])
        git(self.repo, 'commit', '-qm', result['commit_message'], '--only', '--', *result['paths'])
        head = git(self.repo, 'rev-parse', 'HEAD')
        self.store.record_checkpoint(head, action)
        return head

    def boundary(self, suffix='', round_number=None):
        payload = dict(self.value['boundary'])
        if round_number:
            payload['planning_round'] = round_number
        self.store.transition('boundary-complete', payload, 'boundary' + suffix)
        return self.commit('boundary-commit' + suffix)

    def approved(self):
        self.confirm()
        self.commit('shared-commit')
        self.boundary()
        self.store.prepare_package(self.value, 'prepare')
        self.store.approve_package(self.value, 'approve')

    def test_each_stage_is_a_separate_commit_before_start(self):
        self.confirm()
        self.assertEqual(self.store.next_action()['next_action'], 'commit-stage-artifacts')
        with self.assertRaisesRegex(CogitoError, 'not committed'):
            self.store.transition('boundary-complete', self.value['boundary'], 'too-soon')
        shared = self.commit('shared-commit')
        self.assertEqual(self.store.next_action()['next_action'], 'run-boundary-gate')
        boundary = self.boundary()
        self.store.prepare_package(self.value, 'prepare')
        self.store.approve_package(self.value, 'approve')
        with self.assertRaisesRegex(CogitoError, 'not committed'):
            self.store.start_gate('premature-start')
        approved = self.commit('package-commit')
        self.assertEqual(git(self.repo, 'rev-parse', shared + '^'), self.base)
        self.assertEqual(git(self.repo, 'rev-parse', boundary + '^'), shared)
        self.assertEqual(git(self.repo, 'rev-parse', approved + '^'), boundary)
        self.store.start_gate('start')
        self.assertEqual(self.store.load()['state'], 'executing')
        for path in ('docs/cogito/shared.md', 'docs/spec.md', 'docs/plan.md',
                     f'docs/cogito/packages/{self.store.run_id}.json', 'docs/cogito/project-graph.json'):
            self.assertEqual(self.store._git_repo.read_blob(approved, path), (self.repo / path).read_bytes())
        self.assertEqual(len(self.store.load()['checkpoints']), 3)

    def test_unrelated_staged_file_is_preserved_by_selective_commit(self):
        (self.repo / 'personal.txt').write_text('personal work')
        git(self.repo, 'add', 'personal.txt')
        self.confirm()
        self.commit('shared-commit')
        self.assertEqual(git(self.repo, 'diff', '--cached', '--name-only'), 'personal.txt')
        self.assertNotIn('personal.txt', git(self.repo, 'ls-tree', '-r', '--name-only', 'HEAD'))

    def test_unrelated_file_in_commit_is_rejected_without_recording(self):
        self.confirm()
        self.store.prepare_checkpoint()
        (self.repo / 'unrelated.txt').write_text('unrelated')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'incorrect broad commit')
        before = self.store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'unrelated paths'):
            self.store.record_checkpoint(git(self.repo, 'rev-parse', 'HEAD'), 'bad-commit')
        self.assertEqual(before, self.store.events_path.read_bytes())

    def test_omitted_package_document_is_rejected(self):
        self.approved()
        paths = self.store.prepare_checkpoint()['paths']
        paths.remove('docs/spec.md')
        git(self.repo, 'add', '--', *paths)
        git(self.repo, 'commit', '-qm', 'incomplete package', '--only', '--', *paths)
        with self.assertRaises(CogitoError):
            self.store.record_checkpoint(git(self.repo, 'rev-parse', 'HEAD'), 'omitted')
        self.assertIsNotNone(self.store.load()['pending_checkpoint'])

    def test_confirmation_freezes_bytes_and_manifest_preparation_is_repeatable(self):
        self.confirm()
        first = self.store.prepare_checkpoint()
        self.assertEqual(first, self.store.prepare_checkpoint())
        (self.repo / 'docs/cogito/shared.md').write_text('changed after confirmation')
        with self.assertRaisesRegex(CogitoError, 'drifted'):
            self.store.prepare_checkpoint()

    def test_commit_record_recovers_after_event_cache_failure(self):
        self.confirm()
        paths = self.store.prepare_checkpoint()['paths']
        git(self.repo, 'add', '--', *paths)
        git(self.repo, 'commit', '-qm', 'shared', '--only', '--', *paths)
        head = git(self.repo, 'rev-parse', 'HEAD')
        with mock.patch.object(self.store._events, '_project_and_refresh', side_effect=CogitoError('cache failed')):
            with self.assertRaisesRegex(CogitoError, 'cache failed'):
                self.store.record_checkpoint(head, 'receipt')
        before = self.store.events_path.read_bytes()
        self.store.record_checkpoint(head, 'receipt')
        self.assertEqual(before, self.store.events_path.read_bytes())
        self.assertEqual(len(self.store.load()['checkpoints']), 1)
        with self.assertRaises(CogitoError):
            self.store.transition('stage-committed', {}, 'forged')

    def test_new_runs_require_real_shared_document_outside_runtime(self):
        with self.assertRaises(CogitoError):
            self.store.transition('shared-understanding-ready', {'shared_understanding_hash': 'a' * 64}, 'missing')
        document = self.document('.cogito/draft.md', 'draft')
        with self.assertRaisesRegex(CogitoError, 'versioned repository path'):
            self.store.transition('shared-understanding-ready', {
                'shared_understanding_hash': document['hash'], 'document': document}, 'runtime-path')

    def test_package_cannot_omit_shared_document_reference(self):
        self.confirm()
        self.commit('shared-commit')
        self.boundary()
        self.value['shared_understanding'].pop('path')
        with self.assertRaisesRegex(CogitoError, 'committed Shared Understanding'):
            self.store.prepare_package(self.value, 'missing-reference')

    def test_requirements_revision_records_new_stage_commits(self):
        self.confirm()
        self.commit('shared-commit')
        self.boundary()
        self.store.prepare_package(self.value, 'prepare')
        original = copy.deepcopy(self.value)
        self.store.planning_begin({
            'round': 1, 'candidate_hash': package_hash(original), 'author_id': 'planner',
            'reason': 'User changed requirements', 'level': 'requirements',
            'impact': {key: {'disposition': 'redo', 'reason': 'Recheck revised scope'}
                       for key in ('requirements', 'boundary', 'spec', 'plan', 'dag', 'acceptance')},
        }, 'revision')
        self.value['shared_understanding'] = self.document('docs/cogito/shared.md', '修訂後確認的需求\n')
        self.value['planning_round'] = 2
        self.confirm('-2', 2)
        self.commit('shared-commit-2')
        self.boundary('-2', 2)
        self.store.prepare_package(self.value, 'prepare-2')
        self.store.planning_review({
            'round': 2, 'proposal_hash': self.store.load()['planning']['proposal_hash'],
            'reviewer_id': 'reviewer', 'findings': [],
            'assessment': {key: 'Reviewed old and new scope' for key in ('consistency', 'impact', 'reuse')},
        }, 'review-2')
        self.store.approve_package(self.value, 'approve-2')
        self.commit('package-commit-2')
        self.store.start_gate('start')
        self.assertEqual(len(self.store.load()['checkpoints']), 5)

    def test_mini_package_checkpoint_precedes_single_commit_baseline(self):
        value = package('maintenance')
        value['run_id'] = 'DEV-mini-checkpoints'
        value['baseline_commit'] = self.base
        store = RunStore(self.repo, value['run_id'])
        store.create('maintenance', stage_commits=True)
        # Remove unused feature fixture documents from the checkout.
        for path in ('docs/cogito/shared.md', 'docs/spec.md', 'docs/plan.md'):
            (self.repo / path).unlink()
        store.prepare_package(value, 'prepare')
        store.approve_package(value, 'approve')
        self.store = store
        head = self.commit('package-commit')
        store.start_gate('start')
        starts = [e for e in store._events.read() if e['type'] == 'start-gate-passed']
        self.assertEqual(starts[0]['payload']['delivery_head'], head)
        self.assertNotEqual(head, self.base)

    def test_cli_stage_mode_and_checkpoint_commands(self):
        run_id = 'DEV-cli-checkpoint'
        gate = COGITO / 'scripts/cogito_gate.py'
        def invoke(*args):
            result = subprocess.run([sys.executable, str(gate), '--repo', str(self.repo), *args],
                                    text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)['data']
        state = invoke('init', '--run-id', run_id, '--kind', 'feature')
        self.assertEqual(state['state'], 'preparing')
        self.assertTrue(invoke('status', '--run-id', run_id)['stage_commits'])
        shared = self.value['shared_understanding']
        for event, payload in (
            ('shared-understanding-ready', {'shared_understanding_hash': shared['hash'], 'document': shared}),
            ('shared-understanding-confirmed', {'confirmed': True, 'shared_understanding_hash': shared['hash']}),
        ):
            invoke('transition', '--run-id', run_id, '--event', event, '--payload-json', json.dumps(payload), '--action-id', event)
        info = invoke('checkpoint', 'prepare', '--run-id', run_id)
        git(self.repo, 'add', '--', *info['paths'])
        git(self.repo, 'commit', '-qm', info['commit_message'], '--only', '--', *info['paths'])
        state = invoke('checkpoint', 'record', '--run-id', run_id,
                       '--commit-id', git(self.repo, 'rev-parse', 'HEAD'), '--action-id', 'receipt')
        self.assertEqual(state['next']['next_action'], 'run-boundary-gate')
        self.assertIsNone(invoke('status', '--run-id', run_id)['pending_checkpoint'])


class ReplanStageCompatibilityTests(GitTestCase):
    def test_cli_preserves_frozen_successor_protocol(self):
        from test_feature_multitask import FeatureMultitaskTests
        from cogito_replan_store import ReplanStore
        fixture = FeatureMultitaskTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        repo, _, source, _ = fixture.fixture()
        rp = ReplanStore(repo, 'RP-stage-compatibility')
        rp.begin(source.run_id, 'DEV-frozen-successor', 'Reassess scope', 'begin')
        rp.stop('stop')
        before = git(repo, 'rev-parse', 'HEAD')
        command = [sys.executable, str(COGITO / 'scripts/cogito_gate.py'), '--repo', str(repo),
                   'init', '--run-id', 'DEV-frozen-successor', '--kind', 'change']
        rejected = subprocess.run([*command, '--stage-commits'], text=True, capture_output=True)
        self.assertEqual(rejected.returncode, 2)
        self.assertIn('frozen-delivery', rejected.stderr)
        initialized = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        receipt = json.loads(initialized.stdout)['data']
        self.assertEqual(receipt['state'], 'preparing')
        status = subprocess.run([*command[:4], 'status', '--run-id', 'DEV-frozen-successor'],
                                text=True, capture_output=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertFalse(json.loads(status.stdout)['data'].get('stage_commits', False))
        self.assertEqual(git(repo, 'rev-parse', 'HEAD'), before)
