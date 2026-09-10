"""Real Git tests for source preservation, exact approval and restartable handoff."""
import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest import mock
from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError, load_json
from cogito_run_store import RunStore
from cogito_replan_store import ReplanStore
import test_feature_multitask as feature_support

class ReplanStoreTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)
    # Reuse the real verified/reviewing fixture; inherited feature tests also run.
    def setup_replan(self, configure=None):
        repo,worktree,source,ranges=self.fixture()
        old=source.approved_package()
        rp=ReplanStore(repo,'RP-api')
        rp.begin(source.run_id,'DEV-next','shared API needs new contract','begin')
        rp.stop('stop')
        draft=copy.deepcopy(old);draft.pop('package_hash',None);draft['run_id']='DEV-next';draft['kind']='change'
        for sl in draft['slices']:
            oldid=sl['id'];sl['id']+='-V2';sl['type']='change';sl['lineage']=[oldid]
            sl['worker']['branch']+='-v2';sl['worker']['worktree']+='-v2'
        for task in draft['execution_dag']['tasks']: task['slice_id']+='-V2'
        if configure is not None:
            configure(repo, draft)
        new=RunStore(repo,'DEV-next');new.create('change')
        new.transition('shared-understanding-ready',{'shared_understanding_hash':draft['shared_understanding']['hash']})
        new.transition('shared-understanding-confirmed',{'confirmed':True})
        new.transition('boundary-complete',draft['boundary']);new.prepare_package(draft)
        proposal=dict(author_id='planner',package=draft,
            differences={k:'Explicit '+k+' assessment' for k in ('requirements','api','boundary','acceptance','cost','revalidation')},
            work=[dict(source_task_id=t,target_task_id=t,disposition='adapt',validation='rerun',reason='API changed') for t in source.load()['tasks']])
        rp.propose(proposal,'proposal')
        return repo,worktree,source,new,rp,proposal

    def approve_replan(self,rp):
        digest=rp.load()['proposal_hash']
        rp.review(dict(proposal_hash=digest,reviewer_id='independent',findings=[],assessment={k:'Reviewed evidence' for k in ('impact','reuse','revalidation','handoff')}),'review')
        return rp.approve(digest,'approve')

    def test_successor_approval_does_not_activate_graph_or_allow_dispatch(self):
        repo,wt,old,new,rp,_=self.setup_replan()
        before=(repo/'docs/cogito/project-graph.json').read_bytes()
        self.approve_replan(rp)
        self.assertEqual(before,(repo/'docs/cogito/project-graph.json').read_bytes())
        self.assertEqual(new.load()['state'],'start-gate')
        for operation in (lambda:new.start_gate(),lambda:old.resume_gate(),lambda:old.add_amendment({'id':'TA-new','reason':'change','path_fixes':['src/a.txt']})):
            with self.assertRaises(CogitoError):operation()

    def test_review_independence_and_revision_invalidate_previous_review(self):
        _,_,_,_,rp,proposal=self.setup_replan();digest=rp.load()['proposal_hash']
        review=dict(proposal_hash=digest,reviewer_id='planner',findings=[],assessment={k:'checked' for k in ('impact','reuse','revalidation','handoff')})
        with self.assertRaisesRegex(CogitoError,'author'):rp.review(review,'bad-review')
        review['reviewer_id']='other';rp.review(review,'review')
        proposal['differences']['cost']='revised extra work';rp.propose(proposal,'revision')
        with self.assertRaises(CogitoError):rp.approve(digest,'old-approval')
        self.assertEqual(rp.load()['state'],'reviewing')

    def test_handoff_preserves_source_and_imports_committed_work(self):
        repo,wt,old,new,rp,_=self.setup_replan()
        oldhead=git(wt,'rev-parse','HEAD');oldpackage=old.approved_package();self.approve_replan(rp)
        rp.handoff('handoff')
        self.assertEqual(rp.load()['state'],'completed');self.assertEqual(old.load()['state'],'superseded')
        self.assertEqual(oldhead,git(wt,'rev-parse','HEAD'));self.assertEqual(oldpackage,old.approved_package())
        target=repo/'.cogito/worktrees/FS-1-v2'
        self.assertEqual((target/'src/a.txt').read_text(),'a1\n');self.assertEqual((target/'src/b.txt').read_text(),'b1\n')
        self.assertTrue(all(t['status']=='pending' for t in new.load()['tasks'].values()))
        self.assertEqual(load_json(repo/'docs/cogito/project-graph.json')['active_run_id'],new.run_id)
        rp.handoff('handoff')
        new.update_task('T-1','leased','new-worker')

    @staticmethod
    def new_summary(repo, draft):
        relative = 'docs/cogito/understanding/DEV-next.md'
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Successor understanding\n')
        draft['shared_understanding'] = dict(
            path=relative, hash=hashlib.sha256(path.read_bytes()).hexdigest())

    def test_new_summary_survives_prepare_approval_and_handoff_replay(self):
        repo, worker, source, successor, rp, proposal = self.setup_replan(self.new_summary)
        relative = proposal['package']['shared_understanding']['path']
        content = (repo / relative).read_bytes()
        original_package = source.approved_package()
        original_head = git(worker, 'rev-parse', 'HEAD')
        self.approve_replan(rp)
        rp.handoff('handoff')
        events = rp.events_path.read_bytes()
        rp.handoff('handoff')
        self.assertEqual(rp.events_path.read_bytes(), events)
        self.assertEqual(successor.load()['state'], 'executing')
        self.assertEqual((repo / relative).read_bytes(), content)
        artifact = rp.load()['proposal']['start_artifact']
        self.assertEqual(git(repo, 'show', artifact['result_start_tree'] + ':' + relative),
                         content.decode().strip())
        self.assertEqual(source.approved_package(), original_package)
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), original_head)

    def test_new_summary_does_not_allow_unrelated_or_frozen_document_changes(self):
        for relative in ('docs/unrelated.md', 'docs/spec.md'):
            with self.subTest(path=relative):
                repo, _, _, _, rp, _ = self.setup_replan(self.new_summary)
                before = rp.events_path.read_bytes()
                (repo / relative).write_text('Unauthorized change\n')
                with self.assertRaises(CogitoError):
                    self.approve_replan(rp)
                self.assertEqual(rp.events_path.read_bytes(), before)

    def test_changed_successor_summary_is_rejected_before_approval(self):
        repo, _, _, _, rp, proposal = self.setup_replan(self.new_summary)
        digest = rp.load()['proposal_hash']
        rp.review(dict(proposal_hash=digest, reviewer_id='independent', findings=[],
            assessment={k: 'Reviewed evidence' for k in ('impact','reuse','revalidation','handoff')}), 'review')
        (repo / proposal['package']['shared_understanding']['path']).write_text('Unreviewed summary\n')
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.approve(digest, 'approve')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_summary_reference_cannot_authorize_product_or_existing_file_edits(self):
        for relative in ('src/a.txt', '.gitignore'):
            with self.subTest(path=relative):
                def alias(repo, draft):
                    path = repo / relative
                    path.write_text('Reclassified as a new summary\n')
                    draft['shared_understanding'] = dict(
                        path=relative, hash=hashlib.sha256(path.read_bytes()).hexdigest())
                with self.assertRaisesRegex(CogitoError, 'outside new control documents'):
                    self.setup_replan(alias)

    def test_recover_after_graph_write_before_start(self):
        repo,_,_,new,rp,_=self.setup_replan();self.approve_replan(rp)
        with mock.patch.object(RunStore,'start_gate_from_artifact',side_effect=CogitoError('injected crash')):
            with self.assertRaisesRegex(CogitoError,'injected'):rp.handoff('handoff')
        self.assertEqual(rp.load()['state'],'handing-off')
        with self.assertRaises(CogitoError):new.start_gate()
        rp.handoff('handoff');self.assertEqual(rp.load()['state'],'completed')

    def test_reject_keeps_original_paused_and_worktree_drift_blocks_approval(self):
        _,wt,old,_,rp,_=self.setup_replan()
        rp.reject(rp.load()['proposal_hash'],'cost too high','reject')
        self.assertEqual(old.load()['state'],'blocked')
        with self.assertRaises(CogitoError):old.resume_gate()
        (wt/'src/a.txt').write_text('unaccounted writer\n')
        with self.assertRaisesRegex(CogitoError,'drifted'):rp.abandon('resume-source','choose old','abandon')

    def test_recovery_after_source_closure(self):
        _,_,old,_,rp,_=self.setup_replan();self.approve_replan(rp)
        emit=rp._emit
        def fail(kind,*args,**kwargs):
            if kind=='handoff-completed':raise CogitoError('crash after close')
            return emit(kind,*args,**kwargs)
        with mock.patch.object(rp,'_emit',side_effect=fail):
            with self.assertRaises(CogitoError):rp.handoff('handoff')
        self.assertEqual(old.load()['state'],'superseded')
        rp.handoff('handoff');self.assertEqual(rp.load()['state'],'completed')

    def test_cancel_releases_graph_and_preserves_cancel_intent_during_failure(self):
        repo,_,old,_,rp,_=self.setup_replan()
        original=RunStore.transition
        def fail(store,event,*args,**kwargs):
            if event=='cancel':raise CogitoError('interrupted cancel')
            return original(store,event,*args,**kwargs)
        with mock.patch.object(RunStore,'transition',new=fail):
            with self.assertRaises(CogitoError):rp.abandon('cancel-source','infeasible','cancel-choice')
        from cogito_disposition_store import DispositionStore
        disposition=DispositionStore(repo,'DP-RP-api')
        self.assertEqual(disposition.load()['state'],'stopping')
        self.assertEqual(rp.load()['state'],'reviewing')
        with self.assertRaises(CogitoError):old.resume_gate()
        rp.abandon('cancel-source','infeasible','cancel-choice')
        self.assertEqual(old.load()['state'],'cancelled')
        self.assertEqual(rp.load()['state'],'disposition')
        self.assertEqual(disposition.load()['state'],'analyzing')
        graph=load_json(repo/'docs/cogito/project-graph.json')
        self.assertIsNone(graph['active_run_id'])
        self.assertEqual(graph['slices']['FS-1']['disposition'],'cancelled')

    def test_original_resume_archives_stop_generation(self):
        repo,_,old,_,rp,_=self.setup_replan()
        rp.abandon('resume-source','original feasible','resume-choice')
        self.assertEqual(old.load()['state'],'reviewing')
        registry=load_json(repo/'.cogito/runs'/old.run_id/'execution-registry.json')
        self.assertIsNone(registry['stop_request'])
        self.assertEqual(registry['generation'],'RP-api')

    def test_source_cannot_be_cancelled_before_stop_checkpoint(self):
        repo,_,source,_=self.fixture()
        replan=ReplanStore(repo,'RP-stop-required')
        replan.begin(source.run_id,'DEV-after-stop','API change','begin')
        with self.assertRaisesRegex(CogitoError,'confirm all executors'):
            replan.abandon('cancel-source','infeasible','cancel')
        self.assertEqual(replan.load()['state'],'stopping')
        self.assertEqual(source.load()['state'],'blocked')
