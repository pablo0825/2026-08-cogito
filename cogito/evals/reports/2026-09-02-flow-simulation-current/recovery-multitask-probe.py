import json, sys, tempfile
from pathlib import Path
sys.path[:0] = [str(Path.cwd()/'cogito/tests'), str(Path.cwd()/'cogito/scripts')]
from cogito_test_support import isolated_git_environment, init_repo, git, package
from cogito_run_store import RunStore
from cogito_common import CogitoError
with isolated_git_environment(), tempfile.TemporaryDirectory(prefix='cogito-maint-two-tasks-') as tmp:
    repo=Path(tmp); init_repo(repo)
    (repo/'.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
    for name in ('first.txt','second.txt'): (repo/name).write_text('before\n')
    git(repo,'add','.'); git(repo,'commit','-qm','baseline'); base=git(repo,'rev-parse','HEAD')
    draft=package('maintenance'); draft.update(baseline_commit=base,approved_paths=['first.txt','second.txt'],execution_dag={'tasks':[{'id':'T-1','paths':['first.txt']},{'id':'T-2','paths':['second.txt']}],'edges':[{'from':'T-1','to':'T-2'}]})
    store=RunStore(repo,draft['run_id']); store.create('maintenance'); store.prepare_package(draft); store.approve_package(draft); store.start_gate()
    def result(task,paths):
        return dict(schema_version='3.0',run_id=store.run_id,task_id=task,agent_id='worker',role='implementer',status='complete',base_commit=base,head_commit=base,changed_paths=paths,evidence=[],risks=[],requested_transition='verifying')
    store.update_task('T-1','leased','worker');store.update_task('T-1','running','worker');(repo/'first.txt').write_text('after\n');store.submit_agent_result(result('T-1',['first.txt']));store.update_task('T-1','complete','worker')
    store.update_task('T-2','leased','worker');store.update_task('T-2','running','worker');(repo/'second.txt').write_text('after\n')
    for paths in (['second.txt'],['first.txt','second.txt']):
        try: store.submit_agent_result(result('T-2',paths))
        except CogitoError as e: print(json.dumps({'task':'T-2','changed_paths':paths,'error':str(e),'state':store.load()['state']},ensure_ascii=False))
        else: raise AssertionError('unexpected acceptance')
    print(json.dumps({'start_head_unchanged':git(repo,'rev-parse','HEAD')==base,'task_states':{k:v['status'] for k,v in store.load()['tasks'].items()}},ensure_ascii=False))
