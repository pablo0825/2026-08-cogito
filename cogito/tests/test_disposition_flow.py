"""Real Git / public Gate simulations of cancellation and human re-acceptance."""
from __future__ import annotations

import contextlib
import copy
import io
import json

from cogito_test_support import GitTestCase, git, package
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_disposition_scope import dispositions
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import cogito_gate
import test_human_acceptance as human_support


class DispositionFlowTests(GitTestCase):
    fixture = human_support.HumanAcceptanceTests.fixture
    result = staticmethod(human_support.HumanAcceptanceTests.result)
    check = staticmethod(human_support.HumanAcceptanceTests.check)
    feedback = staticmethod(human_support.HumanAcceptanceTests.feedback)
    finalize_delivery = human_support.HumanAcceptanceTests.finalize_delivery

    def cli(self, repo, operation, identifier='DP-human-flow', action=None, **options):
        arguments = ['--repo', str(repo), 'disposition', operation,
                     '--disposition-id', identifier]
        if action is not None:
            arguments.extend(['--action-id', action])
        for key, value in options.items():
            flag = '--' + key.replace('_', '-')
            if value is True:
                arguments.append(flag)
            elif value is not False and value is not None:
                arguments.extend([flag, str(value)])
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cogito_gate.main(arguments)
        self.assertEqual(code, 0, stderr.getvalue())
        output = json.loads(stdout.getvalue())
        self.assertTrue(output['ok'])
        return output['data']

    def input_file(self, store, name, value):
        path = store.run_dir / (name + '.json')
        path.write_text(json.dumps(value))
        return path

    def review_and_approve(self, repo, source, proposal, identifier='DP-human-flow'):
        state = self.cli(repo, 'propose', identifier, 'proposal',
                         input=self.input_file(source, 'disposition-proposal', proposal))
        review = {'reviewer_id': 'independent-reviewer', 'proposal_hash': state['proposal_hash'],
                  'findings': [], 'assessment': 'Scope and preserved delivery verified; acceptance remains explicit.'}
        state = self.cli(repo, 'review', identifier, 'review',
                         input=self.input_file(source, 'disposition-review', review))
        self.assertEqual(state['state'], 'awaiting-approval')
        state = self.cli(repo, 'approve', identifier, 'approve',
                         proposal_hash=state['proposal_hash'], authorized=True)
        self.assertEqual(state['state'], 'executing')
        return state

    def test_cancel_then_retain_requires_fresh_explicit_acceptance(self):
        repo, source = self.fixture('feature')
        before = source.events_path.read_bytes()
        self.cli(repo, 'begin', action='begin', source_run=source.run_id,
                 reason='User cancelled export, pending outcome decision')
        stopped = self.cli(repo, 'stop', action='stop')
        self.assertEqual(stopped['state'], 'analyzing')
        self.assertEqual(source.load()['state'], 'cancelled')
        self.assertIsNone(json.loads((repo / 'docs/cogito/project-graph.json').read_text())['active_run_id'])
        self.assertEqual((repo / 'src/note.txt').read_text(), 'after with typo\n')
        self.assertTrue(source.events_path.read_bytes().startswith(before))
        anchors = [json.loads(line) for line in source.events_path.read_text().splitlines()
                   if json.loads(line)['type'] == 'human-review-required']
        evidence = anchors[-1]['payload']['evidence']
        proposal = {
            'action': 'retain', 'author_id': 'outcome-analyst',
            'summary': 'User elects to retain the original verified text without changes',
            'impact': {'paths': ['src/note.txt'], 'slice_ids': ['FS-1'], 'reason': 'Retain existing text'},
            'acceptance': 'Human confirms the retained text is acceptable',
            'human_acceptance': True,
            'no_change_evidence': {'head': git(repo, 'rev-parse', 'HEAD'),
                                  'content_tree': capture_index_and_worktree_trees(repo)[1],
                                  'evidence_paths': [str(path) for path in evidence]},
        }
        self.review_and_approve(repo, source, proposal)
        disposition = DispositionStore(repo, 'DP-human-flow')
        saved = disposition.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'human acceptance'):
            disposition.complete('missing-human-consent')
        self.assertEqual(disposition.events_path.read_bytes(), saved)
        state = self.cli(repo, 'complete', action='complete', human_accepted=True)
        self.assertEqual(state['state'], 'completed')
        self.assertTrue(state['resolution']['human_accepted'])
        self.assertEqual(source.load()['state'], 'cancelled')
        completed = disposition.events_path.read_bytes()
        self.cli(repo, 'complete', action='complete', human_accepted=True)
        self.assertEqual(disposition.events_path.read_bytes(), completed)

    def test_withdrawn_human_change_returns_through_fresh_checks_and_human_gate(self):
        repo, source = self.fixture('feature')
        source.human_feedback(self.feedback(close=True, mixed=True), 'feedback')
        source.human_triage({'feedback_id': 'HF-1', 'assessments': [
            {'id': 'I-1', 'disposition': 'local', 'reason': 'One typo'},
            {'id': 'I-2', 'disposition': 'change', 'reason': 'New interaction behavior'},
        ]}, 'triage')
        source.human_escalate({'reason': 'User requested interaction change'}, 'escalate')
        original_human = source.load()['human']
        replan = ReplanStore(repo, 'RP-human-withdrawal')
        replan.begin(source.run_id, 'DEV-withdrawal-next', 'Review interaction change', 'begin')
        replan.stop('stop')
        identifier = 'DP-withdrawal'
        self.cli(repo, 'begin', identifier, 'begin', source_run=source.run_id,
                 replan_id=replan.replan_id, reason='User withdraws requested interaction change')
        self.cli(repo, 'stop', identifier, 'stop')
        proposal = {
            'action': 'resume', 'author_id': 'outcome-analyst',
            'summary': 'Resume unchanged original delivery after user withdrawal',
            'impact': {'paths': ['src/note.txt'], 'slice_ids': ['FS-1'], 'reason': 'Original delivery unchanged'},
            'acceptance': 'Rerun post-integration checks and obtain fresh human acceptance',
            'withdrawal_authorization': {'authorized': True, 'reason': 'User explicitly withdraws the change request'},
        }
        self.review_and_approve(repo, source, proposal, identifier)
        self.cli(repo, 'complete', identifier, 'complete')
        self.assertEqual(replan.load()['state'], 'disposition')
        self.assertEqual(source.load()['state'], 'post-integration-verification')
        self.assertNotEqual(source.load()['state'], 'accepted')
        post = self.check(source, repo, 'resumed-post')
        self.assertTrue(post['passed'])
        source.decide_post_verification([post])
        self.assertEqual(source.load()['state'], 'awaiting-human')
        source.approve_human_gate('fresh-acceptance')
        self.assertEqual(source.load()['state'], 'finalizing')
        self.assertIn(original_human['feedback_hash'], source.events_path.read_text())
        self.finalize_delivery(repo, source)
        self.assertEqual(source.load()['state'], 'accepted')

    def test_ordinary_cancel_releases_graph_but_fences_related_packages(self):
        repo, source = self.fixture('feature')
        source.transition('cancel', {'authorized': True, 'reason': 'Cancel export'}, 'cancel')
        self.assertEqual(source.load()['state'], 'cancelled')
        self.assertIsNone(json.loads((repo / 'docs/cogito/project-graph.json').read_text())['active_run_id'])
        pending, = list(dispositions(repo))
        self.assertEqual(pending['state'], 'analyzing')
        for suffix, path in [('overlap', 'src/note.txt'), ('unrelated', 'login/copy.txt')]:
            draft = package('maintenance')
            draft.update(run_id='MNT-' + suffix, baseline_commit=git(repo, 'rev-parse', 'HEAD'),
                         approved_paths=[path], execution_dag={'tasks': [{'id': 'T-1', 'paths': [path]}], 'edges': []})
            candidate = RunStore(repo, draft['run_id'])
            candidate.create('maintenance')
            candidate.prepare_package(draft)
            if suffix == 'overlap':
                with self.assertRaisesRegex(CogitoError, 'disposition'):
                    candidate.approve_package(draft)
                self.assertEqual(candidate.load()['state'], 'awaiting-package-approval')
            else:
                candidate.approve_package(draft)
                self.assertEqual(candidate.load()['state'], 'start-gate')

    def test_retention_followup_acceptance_can_return_for_correction(self):
        repo, source = self.fixture('feature')
        self.cli(repo, 'begin', action='begin', source_run=source.run_id, reason='Cancel original and analyze retention')
        self.cli(repo, 'stop', action='stop')
        draft = copy.deepcopy(source.approved_package())
        draft.pop('package_hash', None)
        draft.update(run_id='DEV-retain-followup', kind='change', baseline_commit=git(repo, 'rev-parse', 'HEAD'))
        draft['slices'][0].update(id='FS-retain', type='change')
        draft['slices'][0]['worker'].update(branch='codex/fs-retain', worktree='.cogito/worktrees/FS-retain')
        draft['execution_dag']['tasks'][0]['slice_id'] = 'FS-retain'
        draft['human_gate']['predicates'] = []
        followup = RunStore(repo, draft['run_id'])
        followup.create('change')
        followup.transition('shared-understanding-ready', {'shared_understanding_hash': 'b' * 64})
        followup.transition('shared-understanding-confirmed', {'confirmed': True})
        followup.transition('boundary-complete', draft['boundary'])
        followup.prepare_package(draft)
        proposal = {
            'action': 'retain', 'author_id': 'outcome-analyst', 'summary': 'Retain with an independently implemented repair',
            'impact': {'paths': ['src/note.txt'], 'slice_ids': ['FS-1'], 'reason': 'Original label requires repair'},
            'acceptance': 'New delivery must pass fresh human acceptance',
            'followup_run_id': followup.run_id, 'followup_package_hash': followup.load()['candidate_package_hash'],
        }
        self.review_and_approve(repo, source, proposal)
        disposition = DispositionStore(repo, 'DP-human-flow')
        with self.assertRaisesRegex(CogitoError, 'acceptance'):
            disposition.complete('premature')
        followup.approve_package(draft)
        followup.start_gate()
        worker = repo / '.cogito/worktrees/FS-retain'
        base = git(repo, 'rev-parse', 'HEAD')
        git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-retain', str(worker), base)
        followup.update_task('T-1', 'leased', 'repair-worker')
        followup.update_task('T-1', 'running', 'repair-worker')
        (worker / 'src/note.txt').write_text('after retained repair\n')
        git(worker, 'add', 'src/note.txt')
        git(worker, 'commit', '-qm', 'Repair retained feature')
        head = git(worker, 'rev-parse', 'HEAD')
        followup.submit_agent_result(self.result(followup, 'T-1', 'repair-worker', base, head))
        followup.update_task('T-1', 'complete', 'repair-worker')
        followup.transition('implementation-complete', {})
        followup.complete_verification([self.check(followup, worker, 'retention-pre')])
        followup.submit_agent_result(self.result(followup, 'T-1', 'repair-reviewer', base, head, reviewer_of='repair-worker'))
        followup.transition('review-approved', {})
        git(repo, 'merge', '--no-ff', '-qm', 'Integrate retained feature repair', 'codex/fs-retain')
        followup.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-retain')
        followup.decide_post_verification([self.check(followup, repo, 'retention-post')])
        self.assertEqual(followup.load()['state'], 'awaiting-human')
        followup.human_feedback(self.feedback(close=True), 'followup-feedback')
        followup.human_triage({'feedback_id': 'HF-1', 'assessments': [
            {'id': 'I-1', 'disposition': 'local', 'reason': 'Only label text remains'}]}, 'followup-triage')
        followup.add_amendment({'id': 'TA-label', 'reason': 'Human requested label correction',
            'added_tasks': [{'id': 'T-label', 'slice_id': 'FS-retain', 'paths': ['src/note.txt']}]}, 'label-amendment')
        followup.human_correction_start({'amendment_id': 'TA-label'}, 'label-start')
        base = git(repo, 'rev-parse', 'HEAD')
        followup.update_task('T-label', 'leased', 'label-worker')
        followup.update_task('T-label', 'running', 'label-worker')
        (repo / 'src/note.txt').write_text('after corrected label\n')
        git(repo, 'add', 'src/note.txt')
        git(repo, 'commit', '-qm', 'Correct label\n\nCogito-Amendment: TA-label')
        head = git(repo, 'rev-parse', 'HEAD')
        followup.submit_agent_result(self.result(followup, 'T-label', 'label-worker', base, head))
        followup.update_task('T-label', 'complete', 'label-worker')
        followup.human_correction_complete({'feedback_id': 'HF-1', 'amendment_id': 'TA-label',
            'commit_id': head, 'resolved_item_ids': ['I-1'], 'summary': 'Label corrected'}, 'label-complete')
        followup.human_verify([self.check(followup, repo, 'label-check')], 'label-verify')
        followup.submit_agent_result(self.result(followup, 'T-label', 'label-reviewer', base, head, reviewer_of='label-worker'))
        followup.human_review('label-reviewed')
        self.assertEqual(followup.load()['state'], 'finalizing')
        self.assertEqual(disposition.load()['state'], 'executing')
        self.finalize_delivery(repo, followup)
        self.cli(repo, 'complete', action='complete')
        self.assertEqual(disposition.load()['state'], 'completed')
        self.assertEqual(source.load()['state'], 'cancelled')
        self.assertEqual(followup.load()['state'], 'accepted')


if __name__ == '__main__':
    import unittest
    unittest.main()
