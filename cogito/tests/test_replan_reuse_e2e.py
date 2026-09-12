"""Adoption skips only approved per-task checks/review, never final verification."""
import copy
import hashlib
import json
import tempfile
from pathlib import Path
from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_run_store import RunStore
from cogito_replan_store import ReplanStore
from cogito_replan_cli import run as replan_cli
from cogito_common import load_json, CogitoError

class ReuseJourneyTests(GitTestCase):
    def test_real_evidence_is_adopted_without_rewriting_and_final_checks_still_run(self):
        self.journey()

    def test_cleaned_accepted_source_keeps_original_adoption_checks(self):
        self.journey(accept_source=True)

    def journey(self, accept_source=False):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        repo=Path(temporary.name).resolve();init_repo(repo)
        for name,text in {'.gitignore':'.cogito/\ndocs/cogito/\n','src/a.txt':'before\n','docs/spec.md':'same acceptance','docs/plan.md':'same plan'}.items():
            path=repo/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
        git(repo,'add','.');git(repo,'commit','-qm','baseline');base=git(repo,'rev-parse','HEAD')
        draft=package('feature');draft['baseline_commit']=base;draft['human_gate']={'predicates':[],'high_risk_hotspots':[]}
        for key in ('spec','plan'):draft['slices'][0][key]['hash']=hashlib.sha256((repo/draft['slices'][0][key]['path']).read_bytes()).hexdigest()
        source=RunStore(repo,draft['run_id']);self.prepare(source,draft);source.approve_package(draft);source.start_gate()
        wt=repo/'.cogito/worktrees/FS-1';git(repo,'worktree','add','-qb','codex/fs-1',str(wt),base)
        source.update_task('T-1','leased','implementer');source.update_task('T-1','running','implementer')
        (wt/'src/a.txt').write_text('after\n');git(wt,'add','src/a.txt');git(wt,'commit','-qm','finished independent work');head=git(wt,'rev-parse','HEAD')
        result=dict(schema_version='3.0',run_id=source.run_id,task_id='T-1',agent_id='implementer',role='implementer',status='complete',base_commit=base,head_commit=head,changed_paths=['src/a.txt'],evidence=[],risks=[],requested_transition='verifying')
        source.submit_agent_result(result);source.update_task('T-1','complete','implementer');source.transition('implementation-complete',{})
        source.run_controlled_check('C-1',wt,'source-check');evidencepath=next(iter(source.load()['evidence']));original=Path(evidencepath).read_bytes()
        source.complete_verification([load_json(Path(evidencepath))])
        source.submit_agent_result({**result,'role':'reviewer','agent_id':'reviewer','reviewed_implementer':'implementer','requested_transition':'review-approved'})
        source.transition('review-approved',{})
        if accept_source:
            git(repo, 'merge', '--no-ff', '-qm', 'integrate source', 'codex/fs-1')
            integration = git(repo, 'rev-parse', 'HEAD')
            source.complete_integration(integration, 'FS-1')
            source.run_controlled_check('C-1', repo, 'source-post')
            postpath = list(source.load()['evidence'])[-1]
            source.decide_post_verification([load_json(Path(postpath))])
            graphpath = repo / 'docs/cogito/project-graph.json'
            graph = load_json(graphpath)
            graph['active_run_id'] = None
            graph['slices']['FS-1'].update(disposition='accepted', completed_by=source.run_id)
            graphpath.write_text(json.dumps(graph))
            resultpath = repo / f'docs/cogito/results/{source.run_id}.json'
            resultpath.parent.mkdir(parents=True, exist_ok=True)
            state = source.load()
            resultpath.write_text(json.dumps(dict(schema_version='3.0', run_id=source.run_id,
                status='accepted', package_hash=state['package_hash'],
                effective_contract_hash=state['effective_contract_hash'], integration_commits=[integration],
                slice_dispositions={'FS-1': 'accepted'}, checks=[dict(id='C-1', status='passed', evidence=postpath)],
                reviews=[dict(reviewer='reviewer')], amendments=[],
                human_gate=dict(required=False, outcome='not-required'), remaining_risks=[])))
            git(repo, 'add', '-f', str(graphpath), str(resultpath))
            git(repo, 'commit', '-qm', 'finalize source')
            outcome = source.finalize(str(resultpath.relative_to(repo)), str(graphpath.relative_to(repo)),
                                     git(repo, 'rev-parse', 'HEAD'))
            self.assertEqual(outcome['cleanup']['removed'], [str(wt)], outcome['cleanup'])
            self.assertFalse(wt.exists())
        rp=ReplanStore(repo,'RP-reuse');rp.begin(source.run_id,'DEV-reused','retain unaffected work','begin');rp.stop('stop')
        newdraft=copy.deepcopy(draft);newdraft['run_id']='DEV-reused';newdraft['kind']='change'
        sl=newdraft['slices'][0];sl.update(id='FS-2',type='change',lineage=['FS-1']);sl['worker'].update(branch='codex/fs-2',worktree='.cogito/worktrees/FS-2');newdraft['execution_dag']['tasks'][0]['slice_id']='FS-2'
        new=RunStore(repo,newdraft['run_id']);self.prepare(new,newdraft)
        proposal=dict(author_id='planner',package=newdraft,differences={k:'unchanged and checked' for k in ('requirements','api','boundary','acceptance','cost','revalidation')},work=[dict(source_task_id='T-1',target_task_id='T-1',disposition='retain',validation='reuse',reason='same complete input content and contract')])
        if accept_source:
            # Existing full-tree/baseline requirements still decide whether a
            # successor may reuse evidence. Cleanup preserves its source input.
            receipt = rp._adoption(proposal, proposal['work'][0], source_tree_only=True)
            self.assertEqual(receipt['source_run_id'], source.run_id)
            self.assertEqual(Path(evidencepath).read_bytes(), original)
            (source.run_dir / 'cleanup.json').unlink()
            with self.assertRaisesRegex(CogitoError, 'no verifiable saved worktree'):
                rp._adoption(proposal, proposal['work'][0], source_tree_only=True)
            return
        rp.propose(proposal,'proposal');digest=rp.load()['proposal_hash'];rp.review(dict(proposal_hash=digest,reviewer_id='impact-reviewer',findings=[],assessment={k:'verified unchanged' for k in ('impact','reuse','revalidation','handoff')}),'review');rp.approve(digest,'approve');rp.handoff('handoff')
        self.assertEqual(new.load()['tasks']['T-1']['status'],'reviewed');self.assertEqual(new.load()['evidence'],{})
        self.assertEqual(Path(evidencepath).read_bytes(),original)
        target=repo/'.cogito/worktrees/FS-2/src/a.txt'
        target.write_text('unreviewed change\n')
        with self.assertRaises(CogitoError):new.advance_adoptions('advance')
        target.write_text('after\n')
        receipt = replan_cli(repo, ['advance-adoptions', '--run-id', new.run_id, '--action-id', 'advance'])
        self.assertEqual(set(receipt), {'run_id', 'state', 'sequence', 'last_event_hash'})
        self.assertEqual(receipt['state'], new.load()['state'])
        git(repo,'merge','--no-ff','-qm','integrate adopted work','codex/fs-2');integration=git(repo,'rev-parse','HEAD');new.complete_integration(integration,'FS-2')
        self.assertEqual(new.load()['state'],'post-integration-verification')
        new.run_controlled_check('C-1',repo,'new-post-check');postpath=next(iter(new.load()['evidence']));new.decide_post_verification([load_json(Path(postpath))])
        graphpath=repo/'docs/cogito/project-graph.json';graph=load_json(graphpath);graph['active_run_id']=None;graph['slices']['FS-2'].update(disposition='accepted',completed_by=new.run_id);graphpath.write_text(json.dumps(graph))
        resultpath=repo/f'docs/cogito/results/{new.run_id}.json';resultpath.parent.mkdir(parents=True,exist_ok=True)
        state=new.load();resultpath.write_text(json.dumps(dict(schema_version='3.0',run_id=new.run_id,status='accepted',package_hash=state['package_hash'],effective_contract_hash=state['effective_contract_hash'],integration_commits=[integration],slice_dispositions={'FS-2':'accepted'},checks=[dict(id='C-1',status='passed',evidence=postpath)],reviews=[dict(reviewer='reviewer')],amendments=[],human_gate=dict(required=False,outcome='not-required'),remaining_risks=[])))
        git(repo,'add','-f',str(graphpath),str(resultpath));git(repo,'commit','-qm','finalize successor');outcome=new.finalize(str(resultpath.relative_to(repo)),str(graphpath.relative_to(repo)),git(repo,'rev-parse','HEAD'))
        self.assertEqual(new.load()['state'],'accepted');self.assertEqual(Path(evidencepath).read_bytes(),original)
        from cogito_disposition_store import DispositionStore
        self.assertFalse(target.parent.parent.exists(), outcome['cleanup'])
        disposition = DispositionStore(repo, 'DP-after-reuse')
        disposition.begin(source.run_id, 'Inspect completed successor', 'begin', replan_id=rp.replan_id)
        self.assertEqual(set(disposition._capture()['worktrees']), {str(wt)})


    def prepare(self,store,draft):
        store.create(draft['kind']);store.transition('shared-understanding-ready',{'shared_understanding_hash':draft['shared_understanding']['hash']});store.transition('shared-understanding-confirmed',{'confirmed':True});store.transition('boundary-complete',draft['boundary']);store.prepare_package(draft)
