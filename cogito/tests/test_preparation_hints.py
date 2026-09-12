"""Preparation guidance executes existing gates without replacing their authority."""
import copy
import json
import subprocess
from pathlib import Path

from cogito_test_support import GitTestCase, git, package
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_run_store import RunStore
from cogito_preparation_hints import export_candidate, preparation_hints
import test_stage_commits as stages
import test_planning_rounds as rounds


class PreparationHintTests(GitTestCase):
    def fixture(self, cls=stages.StageCommitTests):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def invoke(self, hint, *, payload=None, values=None, success=True):
        self.serial = getattr(self, 'serial', 0) + 1
        replacements = {'<action-id>': f'hint-{self.serial}', '<payload-json>': json.dumps(payload or {})}
        replacements.update(values or {})
        command = [replacements.get(arg, arg) for arg in hint['argv']]
        result = subprocess.run(command, cwd=hint['cwd'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout + result.stderr)
        if success and hint['operation'] not in {'git-add', 'git-commit'}:
            return json.loads(result.stdout)['data']

    def checkpoint(self, fixture):
        store = fixture.store
        prepared = self.invoke(store.next_action()['operations'][0])
        for operation in prepared['operations']:
            self.invoke(operation)
        hint, = store.next_action()['operations']
        self.assertIn('record', hint['argv'])
        self.assertIn(git(fixture.repo, 'rev-parse', 'HEAD'), hint['argv'])
        self.invoke(hint)

    def prepared(self):
        f = self.fixture()
        f.confirm(); f.commit('shared'); f.boundary()
        f.store.prepare_package(f.value, 'candidate')
        return f

    def test_cli_first_round_through_three_checkpoints_and_start(self):
        f = self.fixture()
        store = f.store
        before = store.events_path.read_bytes()
        initial = store.next_action()
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertIn('readiness', initial['operations'][0]['note'])
        shared = f.value['shared_understanding']
        self.invoke(initial['operations'][0], payload={'document': shared, 'shared_understanding_hash': shared['hash']})
        out = store.next_action()
        self.assertEqual(out['preparation_context']['shared_understanding'], shared)
        self.assertNotIn('confirmed', out['operations'][0]['input'])
        self.invoke(out['operations'][0], payload={**out['operations'][0]['input'], 'confirmed': True})
        (f.repo / 'personal.txt').write_text('keep staged')
        git(f.repo, 'add', 'personal.txt')
        self.checkpoint(f)
        self.assertEqual(git(f.repo, 'diff', '--cached', '--name-only'), 'personal.txt')
        self.invoke(store.next_action()['operations'][0], payload=f.value['boundary'])
        self.checkpoint(f)
        out = store.next_action()
        self.assertEqual(out['preparation_context']['boundary'], f.value['boundary'])
        path = f.repo / '.cogito/candidate-input.json'
        path.write_text(json.dumps(f.value))
        self.invoke(out['operations'][0], values={'<package.json>': str(path)})
        out = store.next_action()
        exported = self.invoke(out['operations'][0])
        self.assertEqual(json.loads(Path(exported['package_path']).read_text()), f.value)
        self.invoke(out['operations'][1])  # Explicit simulated user approval.
        self.checkpoint(f)
        self.invoke(store.next_action()['operations'][0], success=False)
        self.assertEqual(git(f.repo, 'diff', '--cached', '--name-only'), 'personal.txt')
        git(f.repo, 'rm', '--cached', 'personal.txt')
        (f.repo / 'personal.txt').unlink()  # Remove this test's staged-work fixture, not real user files.
        self.invoke(store.next_action()['operations'][0])
        self.assertEqual(store.load()['state'], 'executing')

    def test_old_confirmation_hint_rejects_new_summary(self):
        f = self.fixture()
        shared = f.value['shared_understanding']
        f.store.transition('shared-understanding-ready', {'document': shared, 'shared_understanding_hash': shared['hash']}, 'first')
        old = f.store.next_action()['operations'][0]
        new = f.document('docs/cogito/revised.md', 'changed requirement')
        f.store.transition('shared-understanding-ready', {'document': new, 'shared_understanding_hash': new['hash']}, 'revised')
        self.invoke(old, payload={**old['input'], 'confirmed': True}, success=False)
        self.assertEqual(f.store.next_action()['preparation_context']['shared_understanding'], new)

    def test_candidate_export_is_exact_repeatable_and_does_not_overwrite(self):
        f = self.prepared()
        events = f.store.events_path.read_bytes()
        hint = f.store.next_action()['operations'][0]
        a = self.invoke(hint); b = self.invoke(hint)
        self.assertEqual(a, b)
        self.assertEqual(f.store.events_path.read_bytes(), events)
        path = Path(a['package_path']); path.chmod(0o644); path.write_text('{}')
        self.invoke(hint, success=False)
        self.assertEqual(path.read_text(), '{}')

    def test_revised_candidate_needs_review_and_old_approval_is_rejected(self):
        f = self.fixture(rounds.PlanningRoundTests)
        old = f.store.next_action()
        self.invoke(old['operations'][0])
        f.store.planning_begin({'round': 1, 'candidate_hash': package_hash(f.old), 'level': 'plan',
            'author_id': 'author', 'reason': 'change execution detail',
            'impact': {key: {'disposition': 'reuse', 'reason': 'same meaning'}
                       for key in ('requirements', 'boundary', 'spec', 'plan', 'dag', 'acceptance')}}, 'begin')
        value = copy.deepcopy(f.old); value['planning_round'] = 2
        value['stop_conditions'].append('Stop on changed API')
        f.store.prepare_package(value, 'new-candidate')
        self.invoke(old['operations'][0], success=False)
        self.invoke(old['operations'][1], success=False)
        out = f.store.next_action()
        self.assertEqual(out['next_action'], 'request-independent-planning-review')
        self.assertFalse(any('approve' in op['argv'] for op in out['operations']))
        self.invoke(out['operations'][0])
        self.invoke(out['operations'][1])
        review = out['operations'][2]
        path = f.repo / '.cogito/review.json'
        path.write_text(json.dumps({**review['input'], 'reviewer_id': 'other', 'findings': [],
            'assessment': {key: 'Checked' for key in ('consistency', 'impact', 'reuse')}}))
        self.invoke(review, values={'<input.json>': str(path)})
        self.invoke(f.store.next_action()['operations'][1])
        self.assertEqual(f.store.load()['state'], 'start-gate')

    def test_checkpoint_drift_blocks_instead_of_suggesting_another_commit(self):
        f = self.fixture(); f.confirm(); f.store.prepare_checkpoint()
        (f.repo / 'wrong.txt').write_text('wrong scope')
        git(f.repo, 'add', 'wrong.txt'); git(f.repo, 'commit', '-qm', 'unrelated')
        out = f.store.next_action()
        self.assertEqual(out['operations'], [])
        self.assertTrue(out['blockers'])

    def test_mini_uses_only_package_checkpoint(self):
        f = self.fixture()
        value = package('maintenance'); value['run_id'] = 'DEV-mini-hints'; value['baseline_commit'] = f.base
        store = RunStore(f.repo, value['run_id']); store.create('maintenance', stage_commits=True)
        out = store.next_action()
        self.assertEqual(out['next_action'], 'assess-mini-package-eligibility')
        self.assertNotIn('shared_understanding', out['preparation_context'])
        store.prepare_package(value); self.invoke(store.next_action()['operations'][0])
        self.invoke(store.next_action()['operations'][1])
        self.assertEqual(store.load()['pending_checkpoint']['stage'], 'package')

    def test_legacy_missing_snapshot_and_hash_only_summary_remain_explicit(self):
        f = self.fixture()
        state = f.store.load()
        state.update(stage_commits=False, shared_understanding_hash='a' * 64, state='awaiting-shared-confirmation')
        out = preparation_hints(f.store, state, 'request-shared-confirmation')
        self.assertNotIn('path', out['preparation_context']['shared_understanding'])
        state.update(state='awaiting-package-approval', planning=None)
        out = preparation_hints(f.store, state, 'request-package-approval')
        self.assertEqual(out['operations'], [])
        self.assertIn('unavailable', out['blockers'][0])

    def test_export_symlink_is_rejected_without_touching_target(self):
        f = self.prepared()
        digest = f.store.load()['candidate_package_hash']
        drafts = f.store.run_dir / 'drafts'; drafts.mkdir(exist_ok=True)
        target = f.repo / 'unrelated.json'; target.write_text('unchanged')
        (drafts / f'candidate-{digest}.json').symlink_to(target)
        with self.assertRaisesRegex(CogitoError, 'symlinks'):
            export_candidate(f.store, digest)
        self.assertEqual(target.read_text(), 'unchanged')

    def test_changed_summary_file_blocks_confirmation_guidance(self):
        f = self.fixture()
        shared = f.value['shared_understanding']
        f.store.transition('shared-understanding-ready', {'document': shared, 'shared_understanding_hash': shared['hash']}, 'ready')
        (f.repo / shared['path']).write_text('unpublished changes')
        output = f.store.next_action()
        self.assertEqual(output['operations'], [])
        self.assertIn('drifted', output['blockers'][0])
