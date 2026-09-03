"""Synthetic three-worker contract conflict and a controlled check blocked mid-flight."""
import copy, hashlib, json, subprocess, sys, tempfile, time
from pathlib import Path
SOURCE=Path(__file__).resolve().parents[4]
sys.path[:0]=[str(SOURCE/'cogito/tests'), str(SOURCE/'cogito/scripts')]
from cogito_test_support import isolated_git_environment, init_repo, git, package
from cogito_run_store import RunStore
OUT=Path(__file__).resolve().parent
ROOT=Path(tempfile.mkdtemp(prefix='cogito-replanning-process-',dir='/tmp'))
logs=[]
def cli(repo,run,command,*args,expect=0):
    if command not in {'init','status','next','report'} and '--action-id' not in args:
        args=(*args,'--action-id',f'probe-{len(logs)}-{command}')
    cp=subprocess.run([sys.executable,'-B',str(SOURCE/'cogito/scripts/cogito_gate.py'),'--repo',str(repo),command,'--run-id',run,*args],capture_output=True,text=True,timeout=20)
    logs.append(dict(command=command,args=args,returncode=cp.returncode,stdout=cp.stdout,stderr=cp.stderr))
    assert cp.returncode==expect,(command,cp.stderr)
    return json.loads(cp.stdout)['data'] if cp.returncode==0 else json.loads(cp.stderr)
def jsonfile(repo,name,value):
    p=repo/'.cogito/inputs'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value));return str(p)
def transition(repo,run,event,payload,action,expect=0):
    return cli(repo,run,'transition','--event',event,'--payload-json',jsonfile(repo,action+'.json',payload),'--action-id',action,expect=expect)
def result(run,task,base,head):
    return dict(schema_version='3.0',run_id=run,task_id=task,agent_id='worker-'+task,role='implementer',status='complete',base_commit=base,head_commit=head,changed_paths=['src/'+task[-1].lower()+'.txt'],evidence=[],risks=[],requested_transition='verifying')
def setup(repo,kind='feature'):
    repo.mkdir();init_repo(repo)
    for path,text in {'.gitignore':'.cogito/\ndocs/cogito/packages/\n','src/b.txt':'before\n','src/c.txt':'before\n','src/d.txt':'before\n','docs/spec.md':'spec\n','docs/plan.md':'plan\n'}.items():
        p=repo/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
    git(repo,'add','.');git(repo,'commit','-qm','baseline')
    return git(repo,'rev-parse','HEAD')
summary={'root':str(ROOT),'synthetic_approvals_and_product_workers':True}
with isolated_git_environment():
    repo=ROOT/'parallel';base=setup(repo);draft=package('feature');run='DEV-parallel-replan'
    draft.update(run_id=run,baseline_commit=base,approved_paths=['src/b.txt','src/c.txt','src/d.txt'])
    slices=[]
    for name in 'BCD':
        sl=copy.deepcopy(draft['slices'][0]);sl['id']='FS-'+name
        sl['worker']={'branch':'codex/worker-'+name,'worktree':'.cogito/worktrees/'+name,'allowed_paths':['src/'+name.lower()+'.txt']}
        for key in ('spec','plan'):sl[key]['hash']=hashlib.sha256((repo/sl[key]['path']).read_bytes()).hexdigest()
        slices.append(sl)
    draft.update(slices=slices,execution_dag={'tasks':[{'id':'T-'+n,'slice_id':'FS-'+n,'paths':['src/'+n.lower()+'.txt']} for n in 'BCD'],'edges':[]})
    cli(repo,run,'init','--kind','feature')
    transition(repo,run,'shared-understanding-ready',{'shared_understanding_hash':'b'*64},'shared')
    transition(repo,run,'shared-understanding-confirmed',{'confirmed':True},'confirmed')
    transition(repo,run,'boundary-complete',draft['boundary'],'boundary')
    draftfile=jsonfile(repo,'package.json',draft)
    cli(repo,run,'prepare-package','--package',draftfile,'--action-id','prepare');cli(repo,run,'approve','--package',draftfile,'--action-id','approve');cli(repo,run,'start','--action-id','start')
    for name in 'BCD':
        wt=repo/'.cogito/worktrees'/name;git(repo,'worktree','add','-qb','codex/worker-'+name,str(wt),base)
        for state in ('leased','running'):cli(repo,run,'task','--task-id','T-'+name,'--status',state,'--agent-id','worker-T-'+name,'--action-id',state+name)
    processes=[]
    worker_code="from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_text('in progress\\n'); print('ready',flush=True); sys.stdin.readline(); p.write_text('finished after block\\n'); print('done',flush=True)"
    try:
        for name in 'BD':
            p=subprocess.Popen([sys.executable,'-I','-c',worker_code,str(repo/'.cogito/worktrees'/name/'src'/f'{name.lower()}.txt')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            processes.append(p);assert p.stdout.readline().strip()=='ready'
        wt=repo/'.cogito/worktrees/C';(wt/'src/c.txt').write_text('current contract implementation\n');git(wt,'add','src/c.txt');git(wt,'commit','-qm','C implementation before contract finding');head=git(wt,'rev-parse','HEAD')
        cli(repo,run,'agent-result','--input',jsonfile(repo,'C-result.json',result(run,'T-C',base,head)),'--action-id','C-result')
        cli(repo,run,'task','--task-id','T-C','--status','complete','--agent-id','worker-T-C','--action-id','C-complete')
        formal=transition(repo,run,'implementation-complete',{},'formal-verification',expect=2)
        before=cli(repo,run,'status');package_bytes=(repo/f'docs/cogito/packages/{run}.json').read_bytes()
        blocked=transition(repo,run,'block',{'reason':'Synthetic finding: completion statistics requires a shared API/data format outside approved contract','slice_id':'FS-C'},'block-C')
        alive=[p.poll() is None for p in processes]
        rejected=cli(repo,run,'task','--task-id','T-B','--status','complete','--agent-id','worker-T-B','--action-id','B-after-block',expect=2)
        for p in processes:stdout,stderr=p.communicate('continue\n',timeout=5);assert p.returncode==0
        after=cli(repo,run,'status')
        assert all(alive) and after['state']=='blocked' and after['tasks']==before['tasks']
        resumed=cli(repo,run,'resume','--action-id','resume-original')
        summary['parallel']={'formal_verification_while_others_running':formal,'blocked_state':blocked['state'],'processes_alive_after_block':alive,'blocked_tasks':{k:v['status'] for k,v in after['tasks'].items()},'B_update_rejected':rejected,'worker_B_file':(repo/'.cogito/worktrees/B/src/b.txt').read_text(),'worker_D_file':(repo/'.cogito/worktrees/D/src/d.txt').read_text(),'package_unchanged':package_bytes==(repo/f'docs/cogito/packages/{run}.json').read_bytes(),'resumed_state':resumed['state']}
    finally:
        for p in processes:
            if p.poll() is None:p.kill();p.communicate(timeout=5)
    repo=ROOT/'runner';base=setup(repo);run='MNT-running-check';draft=package('maintenance')
    signal=ROOT/'release-check';started=ROOT/'check-started';finished=ROOT/'check-finished'
    check_code="from pathlib import Path; import time; " + f"s=Path({str(signal)!r}); Path({str(started)!r}).write_text('started'); " + "\nfor _ in range(500):\n if s.exists(): break\n time.sleep(.01)\nelse: raise RuntimeError('barrier timeout')\n"+f"Path({str(finished)!r}).write_text('finished after block')\n"
    draft.update(run_id=run,baseline_commit=base,approved_paths=['src/c.txt'],execution_dag={'tasks':[{'id':'T-C','paths':['src/c.txt']}],'edges':[]},checks=[{'id':'C-wait','required':True,'timeout_seconds':10,'argv':[sys.executable,'-I','-c',check_code]}])
    cli(repo,run,'init','--kind','maintenance');path=jsonfile(repo,'package.json',draft)
    cli(repo,run,'prepare-package','--package',path);cli(repo,run,'approve','--package',path);cli(repo,run,'start')
    for state in ('leased','running'):cli(repo,run,'task','--task-id','T-C','--status',state,'--agent-id','worker-T-C')
    (repo/'src/c.txt').write_text('after\n');cli(repo,run,'agent-result','--input',jsonfile(repo,'result.json',result(run,'T-C',base,base)));cli(repo,run,'task','--task-id','T-C','--status','complete','--agent-id','worker-T-C');transition(repo,run,'implementation-complete',{},'implemented')
    argv=[sys.executable,'-B',str(SOURCE/'cogito/scripts/cogito_gate.py'),'--repo',str(repo),'run-check','--run-id',run,'--check-id','C-wait','--worktree',str(repo),'--action-id','long-check']
    p=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+5
        while not started.exists() and time.monotonic()<deadline and p.poll() is None:time.sleep(.01)
        assert started.exists()
        transition(repo,run,'block',{'reason':'contract change discovered while check is executing'},'block-check')
        alive=p.poll() is None;signal.write_text('release');stdout,stderr=p.communicate(timeout=12)
        logs.append({'command':'asynchronous run-check','argv':argv,'returncode':p.returncode,'stdout':stdout,'stderr':stderr})
        state=cli(repo,run,'status');evidence=list((repo/'.cogito/runs'/run/'evidence').glob('C-wait-*.json'))
        ev=json.loads(evidence[0].read_text()) if evidence else None
        summary['controlled_check']={'alive_after_block':alive,'completed_after_block':finished.exists(),'run_check_exit':p.returncode,'state_after_check':state['state'],'evidence_passed':ev and ev['passed'],'event_types':[json.loads(x)['type'] for x in (repo/'.cogito/runs'/run/'events.jsonl').read_text().splitlines()]}
        assert alive and finished.exists() and state['state']=='blocked'
    finally:
        if p.poll() is None:p.kill();p.communicate(timeout=5)
(OUT/'process-transcript.json').write_text(json.dumps(logs,indent=2,ensure_ascii=False)+'\n')
(OUT/'process-summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
print(json.dumps(summary,indent=2,ensure_ascii=False))
