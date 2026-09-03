import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
SRC=Path('/Users/pablo/Documents/project/2026-08-cogito')
OUT=SRC/'cogito/evals/reports/2026-09-02-flow-simulation-current'
ROOT=Path(tempfile.mkdtemp(prefix='cogito-cli-behavior-',dir='/tmp')).resolve()
ENV={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
ENV.update(GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_CONFIG_NOSYSTEM='1',GIT_TERMINAL_PROMPT='0')
log=[]; results={"root":str(ROOT),"approval_notice":"all approval inputs are synthetic fixtures, not human authorization"}
def run(argv,cwd=None,expected=0):
 p=subprocess.run(list(map(str,argv)),cwd=cwd,env=ENV,text=True,capture_output=True,timeout=30)
 log.append(dict(argv=list(map(str,argv)),cwd=str(cwd) if cwd else None,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
 (OUT/'cli-behavior-commands.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in log))
 assert p.returncode==expected,(argv,p.returncode,p.stderr)
 return json.loads(p.stdout)['data'] if p.stdout.startswith('{') else p.stdout.strip()
def git(repo,*a): return run(['git',*a],repo)
def repo(name):
 p=ROOT/name;p.mkdir();git(p,'init','-q','--template=','-b','main')
 for key,value in [('user.email','cogito@example.invalid'),('user.name','Cogito Simulation'),('commit.gpgsign','false'),('core.hooksPath','/dev/null')]:git(p,'config',key,value)
 (p/'.gitignore').write_text('.cogito/\n');(p/'note.py').write_text('value = 3\nprint(value)\n')
 git(p,'add','.');git(p,'commit','-qm','baseline');return p
def gate(p,id,cmd,*args,expected=0):return run([sys.executable,'-B',SRC/'cogito/scripts/cogito_gate.py','--repo',p,cmd,'--run-id',id,*args],expected=expected)
def trans(p,id,event,data,action,expected=0):return gate(p,id,'transition','--event',event,'--payload-json',json.dumps(data),'--action-id',action,expected=expected)
# Fresh public CLI complete maintenance flow, actual semantic-preserving local identifier rename.
p=repo('mini-complete');id='MNT-cli-behavior';base=git(p,'rev-parse','HEAD')
gate(p,id,'init','--kind','maintenance');results['mini_first_action']=gate(p,id,'next')
pkg={'schema_version':'3.0','run_id':id,'kind':'maintenance','mini_package':True,'delivery_branch':'main','baseline_commit':base,'shared_understanding':{'hash':'a'*64},'slices':[],'approved_paths':['note.py'],'checks':[{'id':'C-1','argv':[sys.executable,'-I','-c',"import subprocess,sys; r=subprocess.run([sys.executable,'-I','note.py'],capture_output=True,text=True); assert r.returncode==0 and r.stdout=='3\\n'"],'required':True}],'execution_dag':{'tasks':[{'id':'T-1','paths':['note.py']}],'edges':[]},'human_gate':{'predicates':[],'high_risk_hotspots':[]},'policy_snapshot':{'max_workers':3,'fetch_allowed':False},'limits':{'transient_retries':2,'verification_corrections':3,'review_fix_cycles':3,'format_repairs':2},'stop_conditions':['behavior changes or unexpected output'],'source_registry':[],'maintenance_guards':{k:True for k in ['behavior_unchanged','public_contract_unchanged','data_model_unchanged','security_boundary_unchanged','slice_responsibility_unchanged','deterministic_evidence','single_commit']}}
draft=p/'.cogito/runs'/id/'drafts/package.json';draft.parent.mkdir();draft.write_text(json.dumps(pkg))
gate(p,id,'prepare-package','--package',draft,'--action-id','prepare-1')
results['mini_preapproval_start']=gate(p,id,'start','--action-id','start-too-soon',expected=2)
approved=gate(p,id,'approve','--package',draft,'--action-id','simulated-approval-1')
gate(p,id,'start','--action-id','start-1')
for st in ['leased','running']:gate(p,id,'task','--task-id','T-1','--status',st,'--agent-id','synthetic-implementer','--action-id','task-'+st)
(p/'note.py').write_text('renamed_value = 3\nprint(renamed_value)\n')
agent={'schema_version':'3.0','run_id':id,'task_id':'T-1','agent_id':'synthetic-implementer','role':'implementer','status':'complete','base_commit':base,'head_commit':base,'changed_paths':['note.py'],'evidence':[],'risks':[],'requested_transition':'verifying'}
f=draft.with_name('agent-result.json');f.write_text(json.dumps(agent));gate(p,id,'agent-result','--input',f,'--action-id','impl-1')
gate(p,id,'task','--task-id','T-1','--status','complete','--agent-id','synthetic-implementer','--action-id','task-complete')
trans(p,id,'implementation-complete',{},'implementation-complete')
pre=gate(p,id,'run-check','--check-id','C-1','--worktree',p,'--action-id','pre-check')
ep=list(pre['evidence'])[-1]
gate(p,id,'verify','--evidence',ep,'--action-id','verify-1')
trans(p,id,'review-approved',{'review_exemption':True},'review-1')
gate(p,id,'integrate','--commit-id',base,'--action-id','integrate-1')
post=gate(p,id,'run-check','--check-id','C-1','--worktree',p,'--action-id','post-check');ep=next(iter(set(post['evidence'])-set(pre['evidence'])))
state=gate(p,id,'post-verify','--evidence',ep,'--action-id','post-verify-1');assert state['state']=='finalizing'
graph=p/'docs/cogito/project-graph.json';g=json.loads(graph.read_text());g['active_run_id']=None;graph.write_text(json.dumps(g))
res={'schema_version':'3.0','run_id':id,'status':'accepted','package_hash':state['package_hash'],'effective_contract_hash':state['effective_contract_hash'],'integration_commits':[base],'slice_dispositions':{},'checks':[{'id':'C-1','status':'passed','evidence':ep}],'reviews':[],'amendments':[],'human_gate':{'required':False,'outcome':'not-required'},'remaining_risks':[]}
r=p/'docs/cogito/results'/f'{id}.json';r.parent.mkdir();r.write_text(json.dumps(res));git(p,'add','-A');git(p,'commit','-qm','Rename internal identifier and finalize simulation');final=git(p,'rev-parse','HEAD')
state=gate(p,id,'finalize','--result',str(r.relative_to(p)),'--final-commit',final,'--action-id','finalize-1');assert state['state']=='accepted'
results['mini_report']=gate(p,id,'report');results['mini_delivery_commit_count']=git(p,'rev-list','--count',f'{base}..{final}')
# Newly fixed non-object event handling, status and next, plus cache/index immutability.
p=repo('event-shape');id='DEV-event-shape';gate(p,id,'init','--kind','feature');events=p/'.cogito/runs'/id/'events.jsonl';cache=events.with_name('state.json');valid=events.read_bytes();cache0=cache.read_bytes();index0=(p/'.git/index').read_bytes();count=0
for value in [[],None,'event',42,True]:
 for prefix in [b'',valid]:
  damaged=prefix+json.dumps(value).encode()+b'\n';events.write_bytes(damaged)
  for cmd in ['status','next']:
   gate(p,id,cmd,expected=2);latest=log[-1];error=json.loads(latest['stderr']);assert error['ok'] is False and 'object' in error['error'] and 'Traceback' not in latest['stderr'];assert events.read_bytes()==damaged and cache.read_bytes()==cache0 and (p/'.git/index').read_bytes()==index0;count+=1
results['nonobject_event_cases']=count
# Separate fresh cases show malformed preapproval inputs are persisted and cannot be revised later.
results['malformed_preapproval']=[]
for label,sh,bound in [('bad-shared-hash',123,{'decision':'single-slice','evidence':['bounded']}),('bad-boundary-evidence','a'*64,{'decision':'single-slice','evidence':'not-an-array'})]:
 p=repo(label);id='DEV-'+label;gate(p,id,'init','--kind','feature')
 state=trans(p,id,'shared-understanding-ready',{'shared_understanding_hash':sh},'shared-1');trans(p,id,'shared-understanding-confirmed',{'confirmed':True},'simulated-confirmation-1');state=trans(p,id,'boundary-complete',bound,'boundary-1')
 assert state['state']=='package-preparing';trans(p,id,'shared-understanding-ready',{'shared_understanding_hash':'a'*64},'repair-shared',expected=2);trans(p,id,'boundary-complete',{'decision':'single-slice','evidence':['bounded']},'repair-boundary',expected=2)
 feature=json.loads(json.dumps(pkg));feature.update(run_id=id,kind='feature',mini_package=False,baseline_commit=git(p,'rev-parse','HEAD'),boundary=bound,shared_understanding={'hash':sh})
 feature.pop('maintenance_guards');(p/'docs').mkdir();(p/'docs/spec.md').write_text('測試用 Spec\n');(p/'docs/plan.md').write_text('測試用 Plan\n')
 feature['slices']=[{'id':'FS-001','type':'feature','spec':{'path':'docs/spec.md','hash':hashlib.sha256((p/'docs/spec.md').read_bytes()).hexdigest()},'plan':{'path':'docs/plan.md','hash':hashlib.sha256((p/'docs/plan.md').read_bytes()).hexdigest()},'worker':{'branch':'codex/fs-001','worktree':'.cogito/worktrees/FS-001','allowed_paths':['note.py']}}]
 feature['execution_dag']['tasks'][0]['slice_id']='FS-001';d=p/'.cogito/runs'/id/'drafts/p.json';d.parent.mkdir();d.write_text(json.dumps(feature))
 gate(p,id,'prepare-package','--package',d,'--action-id','prepare-invalid',expected=2);invalid_error=json.loads(log[-1]['stderr'])['error']
 feature['shared_understanding']['hash']='a'*64;feature['boundary']={'decision':'single-slice','evidence':['bounded']};d.write_text(json.dumps(feature))
 gate(p,id,'prepare-package','--package',d,'--action-id','prepare-corrected',expected=2);corrected_error=json.loads(log[-1]['stderr'])['error']
 trans(p,id,'block',{'reason':'invalid frozen preapproval input; simulation recovery probe'},'block-invalid')
 resumed=gate(p,id,'resume','--action-id','resume-invalid');assert resumed['state']=='package-preparing'
 gate(p,id,'resume','--target','preparing','--action-id','resume-target-probe',expected=2)
 gate(p,id,'prepare-package','--package',d,'--action-id','prepare-after-resume',expected=2);after_resume=json.loads(log[-1]['stderr'])['error']
 results['malformed_preapproval'].append({'case':label,'state':state['state'],'shared_understanding_hash':state['shared_understanding_hash'],'boundary':state['boundary'],'repo':str(p),'repair_events_rejected':True,'matching_package_rejected':invalid_error,'corrected_package_rejected':corrected_error,'block_resume_state':resumed['state'],'after_resume_package_rejected':after_resume})
p=repo('shared-repair-before-confirmation');id='DEV-shared-repair';gate(p,id,'init','--kind','feature')
trans(p,id,'shared-understanding-ready',{'shared_understanding_hash':123},'initial-invalid')
trans(p,id,'shared-understanding-ready',{'shared_understanding_hash':'a'*64},'repair-before-confirm')
repaired=trans(p,id,'shared-understanding-confirmed',{'confirmed':True,'shared_understanding_hash':'a'*64},'simulated-confirm')
assert repaired['state']=='boundary-analysis' and repaired['shared_understanding_hash']=='a'*64
results['shared_repair_before_confirmation']='passed'
(OUT/'cli-behavior-summary.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n');print(json.dumps(results,ensure_ascii=False,indent=2))
