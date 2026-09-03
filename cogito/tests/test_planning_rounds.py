"""Real-Git regressions for unapproved, same-run planning revisions."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_run_store import RunStore


class PlanningRoundTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="cogito-planning-rounds-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        init_repo(self.repo)
        (self.repo / '.gitignore').write_text('.cogito/\n')
        self.old = package('feature')
        self.old['slices'] = []
        self.old['execution_dag'] = {'tasks': [], 'edges': []}
        for feature in ('filter', 'statistics', 'export'):
            template = copy.deepcopy(package('feature')['slices'][0])
            template.update(id='FS-' + feature)
            template['worker'] = {'branch': 'codex/' + feature,
                'worktree': '.cogito/worktrees/' + feature,
                'allowed_paths': ['src/' + feature + '/**']}
            for field in ('spec', 'plan'):
                template[field] = self.document('round1/' + feature + '-' + field,
                                               feature + ' ' + field + '\n')
            self.old['slices'].append(template)
            self.old['execution_dag']['tasks'].append({'id': 'T-' + feature,
                'slice_id': template['id'], 'paths': ['src/' + feature]})
        self.old['boundary'] = {'decision': 'split-required',
            'evidence': ['Filter, statistics and JSON export are separate responsibilities.']}
        self.old['shared_understanding'] = self.document('round1/shared',
            'Deliver filtering, completion statistics and JSON export.\n')
        self.new = copy.deepcopy(self.old)
        self.new['planning_round'] = 2
        self.new['slices'] = self.new['slices'][:1]
        self.new['execution_dag']['tasks'] = self.new['execution_dag']['tasks'][:1]
        self.new['shared_understanding'] = self.document('round2/shared',
            'Deliver filtering only; defer statistics and JSON export.\n')
        self.new['boundary'] = {'decision': 'single-slice',
            'evidence': ['Only filtering remains in this delivery.']}
        for field in ('spec', 'plan'):
            self.new['slices'][0][field] = self.document('round2/filter-' + field,
                'Filtering only; statistics and export excluded from acceptance. ' + field + '\n')
        self.plan_only = self.document('round2/plan-only',
            'Implement filtering button and filtering logic together; preserve all original features.\n')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'planning inputs')
        baseline = git(self.repo, 'rev-parse', 'HEAD')
        self.old['baseline_commit'] = self.new['baseline_commit'] = baseline
        self.store = RunStore(self.repo, self.old['run_id'])
        self.store.create('feature')
        self.store.transition('shared-understanding-ready', {
            'shared_understanding_hash': self.old['shared_understanding']['hash'],
            'document': self.old['shared_understanding']}, 'old-ready')
        self.store.transition('shared-understanding-confirmed', {'confirmed': True}, 'old-confirm')
        self.store.transition('boundary-complete', self.old['boundary'], 'old-boundary')
        self.store.prepare_package(self.old, 'old-prepare')

    def document(self, name, content):
        path = self.repo / 'docs' / (name + '.md')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {'path': path.relative_to(self.repo).as_posix(),
                'hash': hashlib.sha256(path.read_bytes()).hexdigest()}

    def request(self, level='requirements'):
        dispositions = {key: 'redo' for key in ('requirements', 'boundary', 'spec', 'plan', 'dag', 'acceptance')}
        if level == 'boundary':
            dispositions.update(requirements='reuse', acceptance='reuse')
        if level == 'plan':
            dispositions.update(requirements='reuse', boundary='reuse', spec='reuse', acceptance='reuse')
        return {'round': 1, 'candidate_hash': package_hash(self.old), 'author_id': 'planner',
                'reason': 'User deferred statistics and JSON export.', 'level': level,
                'impact': {key: {'disposition': disposition, 'reason': 'Explicitly assessed ' + key}
                           for key, disposition in dispositions.items()}}

    def begin(self):
        self.store.planning_begin(self.request(), 'begin-round2')

    def prepare_revision(self):
        digest = self.new['shared_understanding']['hash']
        self.store.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': digest,
            'document': self.new['shared_understanding']}, 'new-ready')
        self.store.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'confirmed': True, 'shared_understanding_hash': digest}, 'new-confirm')
        self.store.transition('boundary-complete', {
            **self.new['boundary'], 'planning_round': 2}, 'new-boundary')
        self.store.prepare_package(self.new, 'new-prepare')

    def review_request(self):
        return {'round': 2, 'proposal_hash': self.store.load()['planning']['proposal_hash'],
                'reviewer_id': 'independent-reviewer', 'findings': [],
                'assessment': {key: 'Compared all old and new documents: ' + key
                               for key in ('consistency', 'impact', 'reuse')}}

    def test_three_features_to_one_reaches_start_with_history_preserved(self):
        original_events = self.store.events_path.read_bytes()
        self.begin()
        with self.assertRaises(CogitoError):
            self.store.approve_package(self.old, 'stale-approval')
        self.prepare_revision()
        with self.assertRaises(CogitoError):
            self.store.approve_package(self.new, 'premature-approval')
        self.store.planning_review(self.review_request(), 'review-round2')
        self.store.approve_package(self.new, 'approve-round2')
        self.store.start_gate('start-round2')
        state = self.store.load()
        self.assertEqual(state['state'], 'executing')
        self.assertEqual(set(state['tasks']), {'T-filter'})
        self.assertTrue(self.store.events_path.read_bytes().startswith(original_events))
        self.assertEqual(len(self.store.approved_package()['slices']), 1)
        history = json.dumps(self.store.planning_history())
        self.assertIn(package_hash(self.old), history)
        self.assertIn(package_hash(self.new), history)

    def test_direct_candidate_replacement_and_wrong_level_are_rejected(self):
        changed = copy.deepcopy(self.old)
        changed['slices'] = changed['slices'][:1]
        changed['execution_dag']['tasks'] = changed['execution_dag']['tasks'][:1]
        with self.assertRaises(CogitoError):
            self.store.prepare_package(changed, 'shortcut')
        bad = self.request()
        bad['impact']['requirements']['disposition'] = 'reuse'
        with self.assertRaises(CogitoError):
            self.store.planning_begin(bad, 'wrong-level')
        self.assertEqual(self.store.load()['state'], 'awaiting-package-approval')

    def test_round_and_confirmed_document_are_required(self):
        self.begin()
        payload = {'shared_understanding_hash': self.new['shared_understanding']['hash'],
                   'document': self.new['shared_understanding']}
        with self.assertRaises(CogitoError):
            self.store.transition('shared-understanding-ready', payload, 'missing-round')
        payload['planning_round'] = 1
        with self.assertRaises(CogitoError):
            self.store.transition('shared-understanding-ready', payload, 'old-round')
        payload['planning_round'] = 2
        payload['document'] = {**payload['document'], 'hash': 'f' * 64}
        with self.assertRaises(CogitoError):
            self.store.transition('shared-understanding-ready', payload, 'wrong-document')
        self.prepare_revision()

    def test_independent_review_and_exact_proposal_are_required(self):
        self.begin()
        self.prepare_revision()
        request = self.review_request()
        request['reviewer_id'] = 'planner'
        with self.assertRaises(CogitoError):
            self.store.planning_review(request, 'self-review')
        request = self.review_request()
        request['proposal_hash'] = '0' * 64
        with self.assertRaises(CogitoError):
            self.store.planning_review(request, 'old-review')
        request = self.review_request()
        request['findings'] = ['Acceptance still requires export.']
        with self.assertRaises(CogitoError):
            self.store.planning_review(request, 'unresolved-findings')
        request = self.review_request()
        request['assessment'].pop('reuse')
        with self.assertRaises(CogitoError):
            self.store.planning_review(request, 'incomplete-assessment')
        self.store.planning_review(self.review_request(), 'independent-review')
        spec_path = self.repo / self.new['slices'][0]['spec']['path']
        original = spec_path.read_bytes()
        spec_path.write_text('Unexpected requirement: JSON export required.\n')
        with self.assertRaises(CogitoError):
            self.store.approve_package(self.new, 'drifted-approval')
        spec_path.write_bytes(original)
        self.store.approve_package(self.new, 'clean-approval')

    def test_restart_after_confirmation_does_not_repeat_user_decision(self):
        self.begin()
        after_begin = self.store.events_path.read_bytes()
        self.store.planning_begin(self.request(), 'begin-round2')
        self.assertEqual(self.store.events_path.read_bytes(), after_begin)
        digest = self.new['shared_understanding']['hash']
        self.store.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': digest,
            'document': self.new['shared_understanding']}, 'new-ready')
        self.store.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'confirmed': True,
            'shared_understanding_hash': digest}, 'new-confirm')
        confirmed = self.store.events_path.read_bytes()
        self.store.state_path.unlink()
        self.store = RunStore(self.repo, self.store.run_id)
        self.assertEqual(self.store.load()['state'], 'boundary-analysis')
        self.store.transition('boundary-complete', {
            **self.new['boundary'], 'planning_round': 2}, 'new-boundary')
        self.store.prepare_package(self.new, 'new-prepare')
        self.store.planning_review(self.review_request(), 'review-round2')
        self.store.approve_package(self.new, 'approve-round2')
        self.assertTrue(self.store.events_path.read_bytes().startswith(confirmed))
        events = [json.loads(line) for line in self.store.events_path.read_text().splitlines()]
        self.assertEqual(sum(e['action_id'] == 'new-confirm' for e in events), 1)

    def test_plan_only_round_reuses_confirmed_scope_and_boundary(self):
        request = self.request('plan')
        request['reason'] = 'Improve filtering implementation sequence without changing scope.'
        self.store.planning_begin(request, 'begin-plan-round')
        self.assertEqual(self.store.load()['state'], 'package-preparing')
        draft = copy.deepcopy(self.old)
        draft['planning_round'] = 2
        draft['slices'][0]['plan'] = self.plan_only
        # Preserve all three Slices, their Specs, confirmed scope and Boundary.
        self.store.prepare_package(draft, 'prepare-plan-round')
        self.store.planning_review(self.review_request(), 'review-plan-round')
        self.store.approve_package(draft, 'approve-plan-round')
        self.store.start_gate('start-plan-round')
        self.assertEqual(len(self.store.load()['tasks']), 3)

    def test_withdraw_requires_authorization_and_unchanged_original_documents(self):
        self.begin()
        with self.assertRaises(CogitoError):
            self.store.planning_withdraw({'round': 2, 'reason': 'Unconfirmed retreat.'}, 'unauthorized-withdraw')
        path = self.repo / self.old['slices'][0]['spec']['path']
        original = path.read_bytes()
        path.write_text('Original specification was modified outside this revision.\n')
        request = {'round': 2, 'authorized': True, 'reason': 'User chooses original.'}
        with self.assertRaises(CogitoError):
            self.store.planning_withdraw(request, 'drifted-withdraw')
        self.assertNotEqual(self.store.load()['state'], 'awaiting-package-approval')
        path.write_bytes(original)
        self.store.planning_withdraw(request, 'clean-withdraw')
        self.assertEqual(self.store.load()['candidate_package_hash'], package_hash(self.old))

    def test_withdraw_and_cache_loss_preserve_original_candidate(self):
        original_events = self.store.events_path.read_bytes()
        self.begin()
        self.store.state_path.unlink()
        restored = RunStore(self.repo, self.store.run_id)
        self.assertEqual(restored.load()['planning']['round'], 2)
        with self.assertRaises(CogitoError):
            restored.approve_package(self.old, 'blocked-old')
        restored.planning_withdraw({'round': 2, 'authorized': True, 'reason': 'User chooses original scope.'}, 'withdraw')
        restored.state_path.unlink()
        restored = RunStore(self.repo, self.store.run_id)
        self.assertEqual(restored.load()['state'], 'awaiting-package-approval')
        self.assertEqual(restored.load()['candidate_package_hash'], package_hash(self.old))
        self.assertTrue(restored.events_path.read_bytes().startswith(original_events))
        restored.approve_package(self.old, 'approve-original')
        restored.start_gate('start-original')
        self.assertEqual(len(restored.load()['tasks']), 3)
