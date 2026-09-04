"""Actual cancellation release and interrupted follow-up withdrawal."""
import copy
import json
import subprocess
import sys

from cogito_test_support import GitTestCase, git, package
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_run_store import RunStore
from cogito_execution_registry import register_process
import test_human_acceptance as human_support


class DispositionPauseTests(GitTestCase):
    fixture = human_support.HumanAcceptanceTests.fixture
    result = staticmethod(human_support.HumanAcceptanceTests.result)
    check = staticmethod(human_support.HumanAcceptanceTests.check)

    def decision(self, repo, source):
        store = DispositionStore(repo, 'DP-pause-test')
        store.begin(source.run_id, 'User cancels original', 'begin')
        store.stop('stop')
        return store

    def followup(self, repo, source, disposition):
        draft = copy.deepcopy(source.approved_package())
        draft.pop('package_hash', None)
        draft.update(run_id='DEV-outcome-new', kind='change', baseline_commit=git(repo, 'rev-parse', 'HEAD'))
        draft['slices'][0].update(id='FS-new', type='change')
        draft['slices'][0]['worker'].update(branch='codex/new', worktree='.cogito/worktrees/new')
        draft['execution_dag']['tasks'][0]['slice_id'] = 'FS-new'
        followup = RunStore(repo, draft['run_id'])
        followup.create('change')
        followup.transition('shared-understanding-ready', {'shared_understanding_hash':'b'*64})
        followup.transition('shared-understanding-confirmed', {'confirmed':True})
        followup.transition('boundary-complete', draft['boundary'])
        followup.prepare_package(draft)
        proposal = dict(action='remove', author_id='analyst', summary='Remove rejected behavior',
            impact=dict(paths=['src/note.txt'],slice_ids=['FS-1'],reason='Behavior is being removed'),
            acceptance='Removal is verified and human accepted', followup_run_id=followup.run_id,
            followup_package_hash=followup.load()['candidate_package_hash'])
        state = disposition.propose(proposal, 'proposal')
        disposition.review(dict(reviewer_id='reviewer',proposal_hash=state['proposal_hash'],
            findings=[],assessment='Affected behavior and removal checks covered'), 'review')
        disposition.approve(state['proposal_hash'],True,'approve')
        return followup,draft,proposal

    def test_maintenance_release_preserves_artifacts_and_allows_unrelated_start(self):
        repo,source = self.fixture('maintenance')
        disposition = self.decision(repo,source)
        saved = disposition.load()['snapshot']
        disposition.release('release')
        self.assertEqual((repo/'src/note.txt').read_text(),'before\n')
        refs = git(repo,'for-each-ref','--format=%(refname)','refs/cogito/dispositions/DP-pause-test').splitlines()
        content = next(ref for ref in refs if ref.endswith('/delivery/content'))
        self.assertEqual(git(repo,'show',content+':src/note.txt'),'after with typo')
        self.assertEqual(git(repo,'rev-parse','HEAD'),saved['delivery']['head'])
        draft = package('maintenance')
        draft.update(run_id='MNT-unrelated',baseline_commit=git(repo,'rev-parse','HEAD'),approved_paths=['login.txt'],
            execution_dag={'tasks':[{'id':'T-1','paths':['login.txt']}],'edges':[]})
        unrelated = RunStore(repo,draft['run_id'])
        unrelated.create('maintenance'); unrelated.prepare_package(draft); unrelated.approve_package(draft)
        unrelated.start_gate()
        self.assertEqual(unrelated.load()['state'],'executing')
        # A successful release retry never restores over later unrelated work.
        (repo/'login.txt').write_text('new login text')
        disposition.release('release')
        self.assertEqual((repo/'login.txt').read_text(),'new login text')

    def test_pause_stops_worker_preserves_partial_commits_and_retires_old_approval(self):
        repo,source = self.fixture('feature')
        disposition = self.decision(repo,source)
        followup,draft,proposal = self.followup(repo,source,disposition)
        followup.approve_package(draft); followup.start_gate()
        self.assertEqual(followup.next_action()['next_action'],'dispatch-ready-workers')
        worker = repo/'.cogito/worktrees/new'
        git(repo,'worktree','add','-q','-b','codex/new',str(worker),draft['baseline_commit'])
        followup.update_task('T-1','leased','worker')
        followup.update_task('T-1','running','worker')
        (worker/'src/note.txt').write_text('partly removed\n')
        git(worker,'add','src/note.txt');git(worker,'commit','-qm','Partial removal')
        process = subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'], start_new_session=True)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        register_process(repo,followup.run_id,'worker',process.pid)
        before = disposition.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError,'confirmed stopped'):
            disposition.pause('User wants a restoration proposal','pause')
        self.assertEqual(disposition.load()['state'],'pausing')
        self.assertTrue(disposition.events_path.read_bytes().startswith(before))
        process.terminate();process.wait(timeout=5)
        # The saved-work validator must classify only the pause-owned runtime,
        # even when the repository exposes every other .cogito file as product.
        (repo/'.gitignore').write_text('docs/cogito/packages/\n')
        state = disposition.pause('User wants a restoration proposal','pause')
        self.assertEqual(state['state'],'analyzing')
        self.assertEqual(followup.load()['state'],'cancelled')
        self.assertIn(followup.run_id,state['retired_followup_run_ids'])
        self.assertEqual(state['pause_snapshot']['worktrees'][str(worker.resolve())]['head'],git(worker,'rev-parse','HEAD'))
        self.assertIsNone(json.loads((repo/'docs/cogito/project-graph.json').read_text())['active_run_id'])
        with self.assertRaises(CogitoError): followup.resume_gate('invalid-revival')
        old = disposition.events_path.read_bytes()
        disposition.pause('User wants a restoration proposal','pause')
        self.assertEqual(disposition.events_path.read_bytes(),old)
        revised = {**proposal,'action':'restore','summary':'Propose restoration instead'}
        disposition.propose(revised,'new-proposal')
        self.assertIsNone(disposition.load()['approval'])
