import sys, json, hashlib, tempfile
from pathlib import Path
sys.path.insert(0, '/Users/pablo/Documents/project/2026-08-cogito/cogito/tests')
from cogito_test_support import isolated_git_environment, init_repo, git, package
import cogito_runtime as r
from test_feature_e2e import FeatureMultiSliceEndToEndTests as H

def implementer_id(i):
    return 'slice-worker' if '--same-implementer' in sys.argv else f'implementer-{i}'

def main():
    repo=Path(tempfile.mkdtemp(prefix='cogito-feature-multitask-', dir='/tmp'))
    print('repo:', repo, flush=True)
    init_repo(repo)
    for name, content in {'.gitignore':'.cogito/\ndocs/cogito/packages/\n','src/a.txt':'a0\n','src/b.txt':'b0\n','docs/spec.md':'spec\n','docs/plan.md':'plan\n'}.items():
        p=repo/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)
    git(repo,'add','.');git(repo,'commit','-qm','baseline');base=git(repo,'rev-parse','HEAD')
    d=package('feature');d['run_id']='DEV-feature-multitask-probe';d['baseline_commit']=base
    d['human_gate']={'predicates':[],'high_risk_hotspots':[]}
    d['slices'][0]['worker']['allowed_paths']=['src/**']
    for key in ('spec','plan'):d['slices'][0][key]['hash']=hashlib.sha256((repo/d['slices'][0][key]['path']).read_bytes()).hexdigest()
    d['execution_dag']={'tasks':[{'id':'T-1','slice_id':'FS-1','paths':['src/a.txt']},{'id':'T-2','slice_id':'FS-1','paths':['src/b.txt']}],'edges':[{'from':'T-1','to':'T-2'}]}
    d['checks']=[{'id':'C-1','required':True,'argv':[sys.executable,'-I','-c',"from pathlib import Path; assert Path('src/a.txt').read_text() == 'a1\\n'; assert Path('src/b.txt').read_text() == 'b1\\n'"]}]
    s=r.RunStore(repo,d['run_id']);s.create('feature');s.transition('shared-understanding-ready',{'shared_understanding_hash':'b'*64});s.transition('shared-understanding-confirmed',{'confirmed':True});s.transition('boundary-complete',d['boundary']);s.prepare_package(d);s.approve_package(d);s.start_gate()
    print('Synthetic test approval only; no real human approval asserted.')
    wt=repo/'.cogito/worktrees/FS-1';git(repo,'worktree','add','-q','-b','codex/fs-1',str(wt),base)
    heads=[];bases=[]
    for i,name in enumerate(('a','b'),1):
        task=f'T-{i}';agent=implementer_id(i);bases.append(git(wt,'rev-parse','HEAD'))
        s.update_task(task,'leased',agent);s.update_task(task,'running',agent)
        (wt/f'src/{name}.txt').write_text(f'{name}1\n');git(wt,'add',f'src/{name}.txt');git(wt,'commit','-qm',f'implement {task}');heads.append(git(wt,'rev-parse','HEAD'))
        s.submit_agent_result(H._result(s.run_id,task,agent,'implementer',bases[-1],heads[-1],[f'src/{name}.txt'],'verifying'));s.update_task(task,'complete',agent)
    s.transition('implementation-complete',{})
    e=H._run_check(s,wt,'pre-check');print('check passed:',e['passed']);s.complete_verification([e]);print('state after verification:',s.load()['state'])
    for label,head in [('original task head',heads[0]),('latest Slice head',heads[1])]:
        before=s.events_path.read_bytes()
        try:s.submit_agent_result(H._result(s.run_id,'T-1','reviewer-1','reviewer',bases[0],head,[],'review-approved',implementer_id(1)))
        except r.CogitoError as exc:print('T-1 review using',label,'REJECTED:',str(exc),'events unchanged:',before==s.events_path.read_bytes())
        else:print('T-1 review using',label,'ACCEPTED')
    s.submit_agent_result(H._result(s.run_id,'T-2','reviewer-2','reviewer',bases[1],heads[1],[],'review-approved',implementer_id(2)))
    try:s.transition('review-approved',{})
    except r.CogitoError as exc:print('review closure REJECTED:',str(exc))
    print('final state:',s.load()['state'])
with isolated_git_environment():main()
