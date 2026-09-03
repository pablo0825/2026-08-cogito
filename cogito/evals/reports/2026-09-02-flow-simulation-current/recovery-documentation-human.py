import json, sys, tempfile
from pathlib import Path
sys.path[:0]=[str(Path.cwd()/'cogito/tests'),str(Path.cwd()/'cogito/scripts')]
from cogito_test_support import isolated_git_environment, init_repo, git, package
from test_maintenance_corrections import MaintenanceCli
from cogito_common import CogitoError
class LoggedCli(MaintenanceCli):
    def call(self, command, *opts):
        try:
            data=super().call(command,*opts)
            print(json.dumps({'command':command,'state':data.get('state'),'ok':True},ensure_ascii=False))
            return data
        except CogitoError as e:
            print(json.dumps({'command':command,'ok':False,'error':str(e)},ensure_ascii=False))
            raise
with isolated_git_environment(), tempfile.TemporaryDirectory(prefix='cogito-doc-human-') as tmp:
    repo=Path(tmp);init_repo(repo)
    (repo/'.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
    (repo/'README.md').write_text('Readme.\n')
    git(repo,'add','.');git(repo,'commit','-qm','baseline');base=git(repo,'rev-parse','HEAD')
    draft=package('documentation');draft.update(run_id='MNT-doc-human',baseline_commit=base,approved_paths=['README.md'],execution_dag={'tasks':[{'id':'T-1','paths':['README.md']}],'edges':[]},checks=[{'id':'C-doc','required':True,'argv':[sys.executable,'-I','-c',"from pathlib import Path; assert Path('README.md').read_text() == '# Readme\\n'"]}],human_gate={'predicates':[{'id':'HA-doc','applicable':True}],'high_risk_hotspots':[]})
    cli=LoggedCli(repo,draft['run_id']);cli.create('documentation');cli.prepare_package(draft);cli.approve_package(draft);cli.start_gate()
    cli.call('retry','--kind','transient','--reason','simulated intermittent interruption')
    cli.transition('block',{'reason':'simulated pause'});cli.transition('block',{'reason':'additional issue'})
    blocked=cli.load();assert blocked['blocked_from']=='executing'
    resumed=cli.call('resume');assert resumed['state']=='executing' and resumed['counters']['transient_retries']==1
    cli.update_task('T-1','leased','writer');cli.update_task('T-1','running','writer')
    (repo/'README.md').write_text('# Readme\n');git(repo,'add','README.md');git(repo,'commit','-qm','format title');head=git(repo,'rev-parse','HEAD')
    result=dict(schema_version='3.0',run_id=cli.run_id,task_id='T-1',agent_id='writer',role='implementer',status='complete',base_commit=base,head_commit=head,changed_paths=['README.md'],evidence=[],risks=[],requested_transition='verifying')
    cli.submit_agent_result(result);cli.update_task('T-1','complete','writer');cli.transition('implementation-complete',{})
    def check():
        cli.run_controlled_check('C-doc',repo,'unused');event=json.loads(cli.events_path.read_text().splitlines()[-1]);return json.loads(Path(event['payload']['evidence_path']).read_text())
    pre=check();assert pre['passed'];cli.complete_verification([pre])
    try: cli.transition('review-approved',{'review_exemption':True})
    except CogitoError: pass
    else: raise AssertionError('documentation wrongly exempted')
    cli.submit_agent_result({**result,'role':'reviewer','agent_id':'reviewer','reviewed_implementer':'writer','changed_paths':[],'requested_transition':'review-approved'})
    cli.transition('review-approved',{});cli.complete_integration(head)
    post=check();assert post['passed'];state=cli.decide_post_verification([post]);assert state['state']=='awaiting-human'
    before=cli.events_path.read_bytes()
    try: cli.finalize('docs/cogito/results/MNT-doc-human.json','docs/cogito/project-graph.json',head)
    except CogitoError: pass
    else: raise AssertionError('human gate bypassed')
    assert cli.events_path.read_bytes()==before
    cli.call('human-approve')
    state=cli.load();graph_path=repo/'docs/cogito/project-graph.json';graph=json.loads(graph_path.read_text());graph['active_run_id']=None;graph_path.write_text(json.dumps(graph))
    result_rel='docs/cogito/results/MNT-doc-human.json';result_path=repo/result_rel;result_path.parent.mkdir(parents=True)
    result_path.write_text(json.dumps(dict(schema_version='3.0',run_id=cli.run_id,status='accepted',package_hash=state['package_hash'],effective_contract_hash=state['effective_contract_hash'],integration_commits=[head],slice_dispositions={},checks=[{'id':'C-doc','status':'passed','evidence':post['evidence_path']}],reviews=[{'reviewer':'reviewer','outcome':'approved'}],amendments=[],human_gate={'required':True,'outcome':'approved'},remaining_risks=[])))
    git(repo,'add','README.md','docs/cogito/project-graph.json',result_rel);git(repo,'commit','-qm','finalize documentation');final=git(repo,'rev-parse','HEAD')
    assert cli.finalize(result_rel,'docs/cogito/project-graph.json',final)['state']=='accepted'
    report=cli.completion_report();print(json.dumps({'completion_report':report},ensure_ascii=False))
    events=[json.loads(line) for line in cli.events_path.read_text().splitlines()]
    print(json.dumps({'events':len(events),'human_required_events':sum(e['type']=='human-review-required' for e in events),'human_approved_events':sum(e['type']=='human-approved' for e in events),'final_state':'accepted'},ensure_ascii=False))
