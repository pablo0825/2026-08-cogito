"""RP hints create usable files and preserve existing proposal/approval gates."""
import copy
import json
import subprocess
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, atomic_package, git
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_replan_cli import run
from cogito_replan_draft import proposal_guidance, write_draft
from cogito_replan_store import ReplanStore
import test_replan_store as support


class ReplanDraftTests(GitTestCase):
    def fixture(self, *, proposed=False, configure=None):
        fixture = support.ReplanStoreTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        if proposed:
            result = fixture.setup_replan(configure)
        else:
            with mock.patch.object(ReplanStore, 'propose', return_value=None):
                result = fixture.setup_replan(configure)
        return fixture, result

    def invoke(self, operation, *, action='draft-proposal', success=True):
        command = [action if arg == '<action-id>' else arg for arg in operation['argv']]
        result = subprocess.run(command, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(result.returncode, 0 if success else 2, result.stdout + result.stderr)
        return json.loads(result.stdout)['data'] if success else result

    @staticmethod
    def fill(output, proposal):
        path = Path(output['draft_path'])
        draft = json.loads(path.read_text())
        draft.update(author_id=proposal['author_id'], differences=proposal['differences'], work=proposal['work'])
        path.write_text(json.dumps(draft))
        return draft

    def test_next_status_draft_cli_propose_and_handoff(self):
        fixture, (repo, worker, source, successor, rp, proposal) = self.fixture()
        expected = source.next_action()['proposal_draft']
        self.assertEqual(successor.next_action()['proposal_draft'], expected)
        self.assertEqual(run(repo, ['status', '--replan-id', rp.replan_id])['proposal_draft'], expected)
        events = {s.events_path: s.events_path.read_bytes() for s in (source, successor, rp)}
        head = git(worker, 'rev-parse', 'HEAD')
        output = self.invoke(expected['operations'][0])
        draft_path = Path(output['draft_path'])
        draft = json.loads(draft_path.read_text())
        self.assertEqual(draft['package'], proposal['package'])
        self.assertEqual(draft['work'], [{'source_task_id': t} for t in source.load()['tasks']])
        self.assertNotIn('author_id', draft)
        self.assertEqual(draft['differences'], {})
        for path, before in events.items():
            self.assertEqual(path.read_bytes(), before)
        self.invoke(output['operations'][0], success=False)
        self.fill(output, proposal)
        self.invoke(output['operations'][0])
        proposed_events = rp.events_path.read_bytes()
        self.invoke(output['operations'][0])
        self.assertEqual(rp.events_path.read_bytes(), proposed_events)
        self.assertNotIn('proposal_draft', source.next_action())
        fixture.approve_replan(rp)
        rp.handoff('handoff')
        self.assertEqual(successor.load()['state'], 'executing')
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), head)

    def test_repeated_draft_preserves_edited_file_and_stale_hash_creates_nothing(self):
        _, (_, _, _, successor, rp, proposal) = self.fixture()
        digest = successor.load()['candidate_package_hash']
        first = write_draft(rp, digest)
        self.fill(first, proposal)
        before = Path(first['draft_path']).read_bytes()
        second = write_draft(rp, digest)
        self.assertNotEqual(first['draft_path'], second['draft_path'])
        self.assertEqual(Path(first['draft_path']).read_bytes(), before)
        paths = list((rp.directory / 'drafts').iterdir())
        with self.assertRaisesRegex(CogitoError, 'candidate changed'):
            write_draft(rp, 'f' * 64)
        self.assertEqual(list((rp.directory / 'drafts').iterdir()), paths)

    def test_revised_candidate_requires_planning_review_and_rejects_old_input(self):
        _, (repo, _, source, successor, rp, proposal) = self.fixture(proposed=True)
        old = write_draft(rp, successor.load()['candidate_package_hash'])
        self.fill(old, proposal)
        draft = copy.deepcopy(proposal['package'])
        successor.planning_begin({'round': 1, 'candidate_hash': package_hash(draft), 'level': 'plan',
            'author_id': 'planner', 'reason': 'Revise stop conditions',
            'impact': {key: {'disposition': 'reuse', 'reason': 'Meaning unchanged'}
                       for key in ('requirements', 'boundary', 'spec', 'plan', 'dag', 'acceptance')}}, 'revise')
        draft['planning_round'] = 2
        draft['stop_conditions'].append('Stop for API drift')
        successor.prepare_package(draft, 'candidate2')
        blocked = source.next_action()['proposal_draft']
        self.assertEqual(blocked['operations'], [])
        self.assertIn('independent planning review', blocked['blockers'][0])
        with self.assertRaises(CogitoError):
            write_draft(rp, package_hash(draft))
        successor.planning_review({'round': 2, 'proposal_hash': successor.load()['planning']['proposal_hash'],
            'reviewer_id': 'planning-reviewer', 'findings': [],
            'assessment': {key: 'Checked' for key in ('consistency', 'impact', 'reuse')}}, 'planning-review')
        self.invoke(old['operations'][0], action='old-candidate', success=False)
        operation = successor.next_action()['proposal_draft']['operations'][0]
        output = self.invoke(operation)
        self.assertEqual(json.loads(Path(output['draft_path']).read_text())['package'], draft)
        self.fill(output, proposal)
        self.invoke(output['operations'][0], action='revised-proposal')
        next_output = successor.next_action()
        self.assertEqual(next_output['next_action'], 'continue-replan')
        self.assertIn('independent reviewer', next_output['replan_next_action'])
        self.assertNotIn('proposal_draft', next_output)
        rp.review({'proposal_hash': rp.load()['proposal_hash'], 'reviewer_id': 'rp-reviewer', 'findings': [],
            'assessment': {key: 'Checked' for key in ('impact', 'reuse', 'revalidation', 'handoff')}}, 'rp-review')
        self.assertIn('human approval', successor.next_action()['replan_next_action'])

    def test_toolchain_and_approved_phases_do_not_offer_draft(self):
        fixture, (_, _, _, successor, rp, _) = self.fixture(proposed=True)
        state = rp.load()
        state.update(state='analyzing', toolchain_status='reviewing')
        self.assertEqual(proposal_guidance(rp, state)['proposal_draft']['operations'], [])
        with mock.patch.object(rp, 'load', return_value=state):
            with self.assertRaisesRegex(CogitoError, 'toolchain'):
                write_draft(rp, successor.load()['candidate_package_hash'])
        fixture.approve_replan(rp)
        self.assertEqual(proposal_guidance(rp, rp.load()), {})
        with self.assertRaisesRegex(CogitoError, 'editable proposal phase'):
            write_draft(rp, successor.load()['candidate_package_hash'])

    def test_symlink_draft_directory_does_not_write_outside_runtime(self):
        _, (repo, _, _, successor, rp, _) = self.fixture()
        outside = repo / 'unrelated'
        outside.mkdir()
        (rp.directory / 'drafts').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(CogitoError, 'symlinks'):
            write_draft(rp, successor.load()['candidate_package_hash'])
        self.assertEqual(list(outside.iterdir()), [])

    def test_atomic_successor_keeps_omit_decision_explicit(self):
        _, (_, _, _, successor, rp, proposal) = self.fixture(configure=lambda repo, draft: atomic_package(draft))
        output = write_draft(rp, successor.load()['candidate_package_hash'])
        draft = json.loads(Path(output['draft_path']).read_text())
        self.assertTrue(all(set(row) == {'source_task_id'} for row in draft['work']))
        draft = self.fill(output, proposal)
        self.invoke(output['operations'][0], action='invalid-adapt', success=False)
        for row in draft['work']:
            row.update(target_task_id=None, disposition='omit', validation='rerun', reason='Plan fresh successor tasks')
        Path(output['draft_path']).write_text(json.dumps(draft))
        self.invoke(output['operations'][0], action='atomic-proposal')
        self.assertEqual(rp.load()['state'], 'reviewing')

    def test_document_drift_and_missing_snapshot_do_not_generate_draft(self):
        _, (repo, _, _, successor, rp, proposal) = self.fixture()
        current = successor.load()
        missing = copy.deepcopy(current)
        missing['planning']['candidate'] = None
        with mock.patch.object(type(successor), 'load', return_value=missing):
            hint = proposal_guidance(rp, rp.load())['proposal_draft']
        self.assertEqual(hint['operations'], [])
        self.assertIn('frozen successor candidate snapshot', hint['blockers'][0])
        (repo / proposal['package']['slices'][0]['spec']['path']).write_text('changed after preparation')
        with self.assertRaises(CogitoError):
            write_draft(rp, current['candidate_package_hash'])
        self.assertFalse((rp.directory / 'drafts').exists())

    def test_interrupted_file_write_can_restart_without_overwriting(self):
        _, (_, _, source, successor, rp, _) = self.fixture()
        digest = successor.load()['candidate_package_hash']
        before = {s.events_path: s.events_path.read_bytes() for s in (source, successor, rp)}
        with mock.patch('cogito_replan_draft.json.dump', side_effect=OSError('interrupted write')):
            with self.assertRaises(OSError):
                write_draft(rp, digest)
        partial, = (rp.directory / 'drafts').iterdir()
        partial_bytes = partial.read_bytes()
        complete = write_draft(rp, digest)
        self.assertNotEqual(complete['draft_path'], str(partial))
        self.assertEqual(partial.read_bytes(), partial_bytes)
        self.assertEqual(package_hash(json.loads(Path(complete['draft_path']).read_text())['package']), digest)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_draft_cli_storage_error_explains_recovery_without_action_id(self):
        with mock.patch('cogito_replan_draft.write_draft', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(CogitoError, 'no proposal was submitted.*rerun draft.*disk full'):
                run('/unused', ['draft', '--replan-id', 'RP-example', '--candidate-hash', 'a' * 64])
