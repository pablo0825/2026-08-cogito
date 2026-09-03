"""Replay the existing two-Slice fixture through real CLI processes, preserving evidence.
All confirmation, approval and worker/reviewer identities are synthetic test data.
This verifies runtime behavior, not live human authorization or agent independence.
"""
from pathlib import Path
from contextlib import contextmanager
import argparse, datetime, json, subprocess, sys, traceback

parser = argparse.ArgumentParser()
parser.add_argument('--source', default='/Users/pablo/Documents/project/2026-08-cogito')
parser.add_argument('--scenario', choices=['happy-path','human-gate','failed-product','unverified-final','integration-outside'], default='happy-path')
parser.add_argument('--kind', choices=['feature','change','correction'], default='feature')
args = parser.parse_args()
SOURCE = Path(args.source)
ROOT = Path(__file__).resolve().parent
SCENARIO = args.scenario
OUT = ROOT / (SCENARIO if args.kind == 'feature' else f'{args.kind}-{SCENARIO}')
OUT.mkdir(parents=True, exist_ok=True)
REPO = OUT / 'repo'
if REPO.exists():
    raise SystemExit(f'Refusing to overwrite existing run: {REPO}')
REPO.mkdir()
sys.path[:0] = [str(SOURCE/'cogito/tests'), str(SOURCE/'cogito/scripts'), str(ROOT)]
import fixture_cli as fixture
import cogito_runtime as runtime

@contextmanager
def persistent_repo():
    yield str(REPO)

class CliStore:
    def __init__(self, repo, run_id, workflow=None):
        assert workflow is None
        self.repo, self.run_id = Path(repo), run_id
        self.run_dir = self.repo / '.cogito/runs' / run_id
        self.events_path = self.run_dir / 'events.jsonl'
        self.sequence = 0
    def invoke(self, command, options):
        argv = [sys.executable, '-B', str(SOURCE/'cogito/scripts/cogito_gate.py'), '--repo', str(self.repo), command, '--run-id', self.run_id, *map(str, options)]
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=45)
        with (OUT/'cli-transcript.jsonl').open('a') as log:
            log.write(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(), 'argv':argv, 'exit_code':cp.returncode, 'stdout':cp.stdout, 'stderr':cp.stderr})+'\n')
        if cp.returncode:
            try:
                message=json.loads(cp.stderr)['error']
            except Exception:
                message=cp.stderr
            raise runtime.CogitoError(message)
        return json.loads(cp.stdout)['data']
    def call(self, command, *options, action_id=None):
        if command != 'init':
            self.invoke('next', [])
        self.sequence += 1
        if command not in {'init','status','next','report'}:
            options=(*options, '--action-id', action_id or f'simulation-{self.sequence:03d}-{command}')
        result=self.invoke(command, options)
        if command not in {'status','next','report'}:
            self.invoke('next', [])
        return result
    def payload(self, value):
        directory=self.run_dir/'drafts'
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/f'cli-payload-{self.sequence+1:03d}.json'
        path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
        return path
    def create(self, kind): return self.call('init','--kind',kind)
    def load(self): return self.call('status')
    def next_action(self): return self.call('next')
    def transition(self, event, payload, action_id=None):
        return self.call('transition','--event',event,'--payload-json',self.payload(payload),action_id=action_id)
    def prepare_package(self, draft): return self.call('prepare-package','--package',self.payload(draft))
    def approve_package(self, draft): return self.call('approve','--package',self.payload(draft))
    def approved_package(self): return json.loads((self.repo/f'docs/cogito/packages/{self.run_id}.json').read_text())
    def start_gate(self): return self.call('start')
    def update_task(self, task, status, agent):
        return self.call('task','--task-id',task,'--status',status,'--agent-id',agent)
    def submit_agent_result(self, result): return self.call('agent-result','--input',self.payload(result))
    def run_controlled_check(self, check, worktree, action_id):
        return self.call('run-check','--check-id',check,'--worktree',worktree,action_id=action_id)
    def complete_verification(self, evidence):
        options=[]
        for item in evidence: options.extend(['--evidence', item['evidence_path']])
        return self.call('verify',*options)
    def complete_integration(self, commit, slice_id):
        return self.call('integrate','--commit-id',commit,'--slice-id',slice_id)
    def decide_post_verification(self,evidence,reviewer_escalation=False):
        options=[]
        for item in evidence: options.extend(['--evidence',item['evidence_path']])
        if reviewer_escalation: options.append('--reviewer-escalation')
        return self.call('post-verify',*options)
    def finalize(self, result, graph, commit):
        return self.call('finalize','--result',result,'--project-graph',graph,'--final-commit',commit)
    def completion_report(self): return self.call('report')

fixture.CliStore=CliStore
fixture.persistent_repo=persistent_repo
fixture.SCENARIO=SCENARIO
fixture.KIND=args.kind
case=fixture.FeatureMultiSliceEndToEndTests()
started=datetime.datetime.now(datetime.timezone.utc)
result={'kind':args.kind,'scenario':SCENARIO,'started_at':started.isoformat(),'repo':str(REPO),'fixture_source':'cogito/tests/test_feature_e2e.py','synthetic_approvals_and_agent_identities':True}
try:
    case.setUp()
    case._run_feature(invalid_product='a' if SCENARIO=='failed-product' else None,change_after_verification=SCENARIO=='unverified-final')
    result['assertions_passed']=True
except Exception:
    result['assertions_passed']=False
    result['error']=traceback.format_exc()
finally:
    case.doCleanups()
    result['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat()
    state=REPO/'.cogito/runs/DEV-feature-e2e-001/state.json'
    if state.exists(): result['final_state']=json.loads(state.read_text()).get('state')
    (OUT/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(0 if result['assertions_passed'] else 1)
