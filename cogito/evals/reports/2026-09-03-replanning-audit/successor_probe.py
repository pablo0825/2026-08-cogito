"""Temporary real-Git RunStore probes; no product source changes or forged events."""
from pathlib import Path
import sys,json,copy,hashlib
from unittest import mock
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'scripts')]
from test_feature_e2e import FeatureMultiSliceEndToEndTests
import cogito_runtime as rt
from cogito_test_support import git
Original=rt.RunStore
class Done(Exception):pass
records=[]
def log(label,**data):
    row={'case':CASE,'probe':label,**data}; records.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
def attempt(label, fn):
    try:
        value=fn();log(label,ok=True,state=value.get('state') if isinstance(value,dict) else str(value));return value
    except rt.CogitoError as e:log(label,ok=False,error=str(e));return None

def successor(old, accepted=False):
    repo=old.root; history=old.events_path.read_bytes();package=copy.deepcopy(old.approved_package());package.pop('package_hash',None)
    graphpath=repo/'docs/cogito/project-graph.json';beforegraph=graphpath.read_bytes(); old_graph_snapshot=json.loads(beforegraph)
    if not accepted:
        # A has integrated; B is running with uncommitted work when the API finding appears.
        wt=repo/'.cogito/worktrees/FS-B'
        git(repo,'worktree','add','-q','-b','codex/fs-b',str(wt),git(repo,'rev-parse','HEAD'))
        old.update_task('T-B','leased','implementer-b');old.update_task('T-B','running','implementer-b')
        (wt/'src/b.txt').write_text('valuable incomplete export\n')
        old.transition('block',{'reason':'shared API requires explicit new contract'})
        blocked=old.load();old.transition('cancel',{'authorized':True})
        st=old.load();log('cancel_preserves_graph_leases_work',state=st['state'],graph_unchanged=graphpath.read_bytes()==beforegraph,active_run_id=json.loads(graphpath.read_text())['active_run_id'],task_statuses={k:v['status'] for k,v in st['tasks'].items()},lease_unchanged=st['tasks']['T-B']==blocked['tasks']['T-B'],uncommitted_content=(wt/'src/b.txt').read_text())
        history=old.events_path.read_bytes()
    else:
        attempt('accepted_resume',old.resume_gate)
        attempt('accepted_block',lambda:old.transition('block',{'reason':'API v2'}))
    new_id='DEV-successor-'+CASE
    package['run_id']=new_id;package['kind']='change';package['baseline_commit']=git(repo,'rev-parse','HEAD')
    for s in package['slices']:s['type']='change'
    new=Original(repo,new_id);new.create('change');new.transition('shared-understanding-ready',{'shared_understanding_hash':package['shared_understanding']['hash']});new.transition('shared-understanding-confirmed',{'confirmed':True});new.transition('boundary-complete',package['boundary']);new.prepare_package(package)
    same=attempt('new_run_same_slice_approve_before_manual_cleanup',lambda:new.approve_package(package))
    if not accepted:
        graph=json.loads(graphpath.read_text());graph['active_run_id']=None;graphpath.write_text(json.dumps(graph))
        log('manual_graph_clear',note='explicit audit manual file edit; no dedicated successor gate')
    if CASE=='same':
        same=attempt('same_active_slice_approve_after_graph_clear',lambda:new.approve_package(package))
        assert same
        log('same_slice_metadata_overwrite',before_slice=old_graph_snapshot['slices']['FS-A'],after_slice=json.loads(graphpath.read_text())['slices']['FS-A'],introduced_by=json.loads(graphpath.read_text())['slices']['FS-A']['introduced_by'],old_history_unchanged=old.events_path.read_bytes()==history,new_tasks={k:v['status'] for k,v in new.load()['tasks'].items()})
        attempt('same_worker_paths_start',new.start_gate)
        return
    # Accepted Slice IDs are immutable. New IDs + lineage + distinct layouts retain the old graph nodes.
    for s in package['slices']:
        oldid=s['id'];s['id']=oldid+'-V2';s['lineage']=[oldid]
        s['worker']['branch']+='-v2';s['worker']['worktree']+='-v2'
    for t in package['execution_dag']['tasks']:t['slice_id']+='-V2'
    new.prepare_package(package);new.approve_package(package)
    if accepted:
        attempt('accepted_successor_unstaged_graph_start',new.start_gate)
        git(repo,'add','docs/cogito/project-graph.json')
        log('stage_control_graph',note='stage only formalized graph, no commit')
    new.start_gate()
    log('new_ids_lineage_approve_start',state=new.load()['state'],old_history_unchanged=old.events_path.read_bytes()==history,old_worktrees_preserved=all((repo/p).exists() for p in ['.cogito/worktrees/FS-A','.cogito/worktrees/FS-B']),new_tasks={k:v['status'] for k,v in new.load()['tasks'].items()},new_evidence_count=len(new.load()['evidence']),graph_nodes=list(json.loads(graphpath.read_text())['slices']))
    # Existing integrated implementation is now part of the new baseline, but new approval does not import status/evidence.
    wt=repo/'.cogito/worktrees/FS-A-v2';git(repo,'worktree','add','-q','-b','codex/fs-a-v2',str(wt),package['baseline_commit']);new.update_task('T-A','leased','new-implementer');new.update_task('T-A','running','new-implementer')
    log('new_worker_preserves_integrated_product',product=(wt/'src/a.txt').read_text())
    oldresult=old.load()['agent_results'][0]
    attempt('old_agent_result_submission',lambda:new.submit_agent_result(oldresult))
    # Produce a genuine new result to reach verification, then try the former run's actual check artifact.
    (wt/'src/a.txt').write_text('a2\n');git(wt,'add','src/a.txt');git(wt,'commit','-qm','new approved API implementation')
    result=FeatureMultiSliceEndToEndTests._result(new_id,'T-A','new-implementer','implementer',package['baseline_commit'],git(wt,'rev-parse','HEAD'),['src/a.txt'],'verifying')
    new.submit_agent_result(result);new.update_task('T-A','complete','new-implementer');new.transition('implementation-complete',{})
    evidence=json.loads(Path(next(iter(old.load()['evidence']))).read_text())
    attempt('old_check_evidence_reuse',lambda:new.complete_verification([evidence]))

class AuditStore(Original):
    def complete_integration(self,*args,**kwargs):
        result=super().complete_integration(*args,**kwargs)
        if CASE!='accepted' and len(args)>1 and args[1]=='FS-A':
            successor(self);raise Done()
        return result
    def finalize(self,*args,**kwargs):
        result=super().finalize(*args,**kwargs)
        if CASE=='accepted':
            successor(self,True);raise Done()
        return result

for CASE in ['same','new','accepted']:
    t=FeatureMultiSliceEndToEndTests();t.setUp()
    try:
        with mock.patch.object(rt,'RunStore',AuditStore):t._run_feature()
    except Done:pass
    finally:t.doCleanups()
Path(__file__).with_name('successor-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n')
