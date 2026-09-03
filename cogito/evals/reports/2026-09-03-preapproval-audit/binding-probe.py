"""Read-only product audit; all state mutations occur in temporary repositories."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

COGITO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COGITO / 'tests'))
from test_package_revisions import PackageRevisionTests
from cogito_test_support import git, init_repo, package

class BindingProbes(PackageRevisionTests):
    # Override inherited suite selection in __main__: only these probes run.
    def traced(self, repo, *args, ok=True):
        result = self.invoke(repo, *args, ok=ok)
        print(json.dumps({'argv': args, 'rc': result.returncode, 'stdout': result.stdout.strip(), 'stderr': result.stderr.strip()}, ensure_ascii=False), flush=True)
        return result

    def put(self, root, name, value):
        path = root / name
        path.write_text(json.dumps(value, ensure_ascii=False))
        return str(path)

    def test_scope_shrink_with_old_bindings(self):
        temporary = tempfile.TemporaryDirectory(prefix='cogito-binding-scope-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        repo = root / 'repo'
        repo.mkdir()
        init_repo(repo)
        (repo/'.gitignore').write_text('.cogito/\n')
        (repo/'docs').mkdir()
        shared = repo/'docs/shared.md'
        shared.write_text('Confirmed scope: filtering, completion statistics, and JSON export. All three are required this run.\n')
        initial = package('feature')
        initial['shared_understanding'] = {'path':'docs/shared.md','hash':hashlib.sha256(shared.read_bytes()).hexdigest()}
        initial['boundary'] = {'decision':'split-required','evidence':['B: filtering; C: completion statistics; D: JSON export. Three independent responsibilities.']}
        template = copy.deepcopy(initial['slices'][0])
        initial['slices'] = []
        initial['execution_dag']['tasks'] = []
        for ident, name in [('B','filter'),('C','statistics'),('D','export')]:
            item = copy.deepcopy(template)
            item['id'] = f'FS-{ident}'
            item['worker']['branch'] = f'codex/fs-{ident.lower()}'
            item['worker']['worktree'] = f'.cogito/worktrees/FS-{ident}'
            item['worker']['allowed_paths'] = [f'src/{name}.py']
            for key in ('spec','plan'):
                path = repo/f'docs/{name}-{key}.md'
                path.write_text(f'{key}: implement and validate {name} in this run.\n')
                item[key] = {'path':path.relative_to(repo).as_posix(),'hash':hashlib.sha256(path.read_bytes()).hexdigest()}
            initial['slices'].append(item)
            initial['execution_dag']['tasks'].append({'id':f'{ident}-{name}','slice_id':f'FS-{ident}','paths':[f'src/{name}.py']})
        git(repo,'add','.')
        git(repo,'commit','-qm','three-feature planning baseline')
        initial['baseline_commit'] = git(repo,'rev-parse','HEAD')
        run=initial['run_id']
        draft=root/'draft.json'
        self.invoke(repo,'init','--run-id',run,'--kind','feature')
        for event,payload in [('shared-understanding-ready',{'shared_understanding_hash':initial['shared_understanding']['hash']}),('shared-understanding-confirmed',{'confirmed':True}),('boundary-complete',initial['boundary'])]:
            self.invoke(repo,'transition','--run-id',run,'--event',event,'--payload-json',json.dumps(payload),'--action-id',event)
        initial_path = self.put(draft.parent, 'three-features.json', initial)
        self.traced(repo, 'prepare-package', '--run-id', run, '--package', initial_path, '--action-id', 'three-features')
        # Honest changed consensus and Boundary are separately rejected.
        changed = copy.deepcopy(initial)
        changed['shared_understanding']['hash'] = 'e'*64
        self.traced(repo, 'prepare-package', '--run-id', run, '--package', self.put(draft.parent,'new-consensus.json',changed), '--action-id','new-consensus',ok=False)
        changed = copy.deepcopy(initial)
        changed['boundary']['evidence'] = ['Only filtering remains; statistics and export deferred.']
        self.traced(repo, 'prepare-package', '--run-id', run, '--package', self.put(draft.parent,'new-boundary.json',changed), '--action-id','new-boundary',ok=False)
        # Revise real Spec/Plan and hashes while retaining old confirmed identity.
        revised = copy.deepcopy(initial)
        revised['execution_dag']['tasks'] = revised['execution_dag']['tasks'][:1]
        revised['slices'] = revised['slices'][:1]
        (repo/'docs/filter-spec.md').write_text('Scope: filtering only.\nStatistics and JSON export deferred.\nAcceptance: filtering works.\n')
        (repo/'docs/filter-plan.md').write_text('Only B implements filtering this run.\n')
        for key in ('spec', 'plan'):
            revised['slices'][0][key]['hash'] = hashlib.sha256((repo / revised['slices'][0][key]['path']).read_bytes()).hexdigest()
        revised_path = self.put(draft.parent,'filter-only.json',revised)
        self.traced(repo,'prepare-package','--run-id',run,'--package',revised_path,'--action-id','filter-only')
        self.traced(repo,'approve','--run-id',run,'--package',initial_path,'--action-id','approve-old',ok=False)
        self.traced(repo,'approve','--run-id',run,'--package',revised_path,'--action-id','approve-filter')
        self.traced(repo,'start','--run-id',run,'--action-id','start-filter')
        events = [json.loads(x) for x in (repo/'.cogito/runs'/run/'events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(x['type']=='shared-understanding-confirmed' for x in events),1)
        self.assertEqual(sum(x['type']=='boundary-complete' for x in events),1)
        print('RESULT scope shrink: prepare/approve/start succeeded with original consensus identity and original Boundary record; no new confirmations.',flush=True)

    def test_file_hash_checked_at_start(self):
        repo,value,draft = self.fixture('feature')
        run=value['run_id']
        self.traced(repo,'prepare-package','--run-id',run,'--package',str(draft),'--action-id','prepare')
        (repo/'docs/spec.md').write_text('Changed scope after candidate preparation.\n')
        self.traced(repo,'approve','--run-id',run,'--package',str(draft),'--action-id','approve')
        rejected=self.traced(repo,'start','--run-id',run,'--action-id','start',ok=False)
        self.assertIn('hash',rejected.stderr)
        print('RESULT stale Spec bytes: approval succeeds but Start Gate rejects hash mismatch; this is NOT an execution bypass.',flush=True)

if __name__=='__main__':
    suite=unittest.TestSuite(BindingProbes(name) for name in ('test_scope_shrink_with_old_bindings','test_file_hash_checked_at_start'))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
