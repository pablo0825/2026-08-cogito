"""Live executor checks for the stop fence; no mocked process termination."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError, load_json
from cogito_execution_registry import register_process, snapshot
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore


class ReplanLiveTests(GitTestCase):
    def fixture(self, check_argv, *, complete=True):
        temporary = tempfile.TemporaryDirectory(prefix='cogito-replan-live-')
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        for name, content in {
            '.gitignore': '.cogito/\ndocs/cogito/packages/\n',
            'src/a.txt': 'before\n', 'docs/spec.md': 'spec\n',
            'docs/plan.md': 'plan\n',
        }.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        baseline = git(repo, 'rev-parse', 'HEAD')
        draft = package('feature')
        draft.update(run_id='DEV-live', baseline_commit=baseline,
                     human_gate={'predicates': [], 'high_risk_hotspots': []},
                     checks=[{'id': 'C-live', 'required': True, 'argv': check_argv}])
        for key in ('spec', 'plan'):
            document = draft['slices'][0][key]
            document['hash'] = hashlib.sha256((repo / document['path']).read_bytes()).hexdigest()
        store = RunStore(repo, draft['run_id'])
        store.create('feature')
        store.transition('shared-understanding-ready', {'shared_understanding_hash': 'b' * 64})
        store.transition('shared-understanding-confirmed', {'confirmed': True})
        store.transition('boundary-complete', draft['boundary'])
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        worktree = repo / '.cogito/worktrees/FS-1'
        git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-1', str(worktree), baseline)
        store.update_task('T-1', 'leased', 'worker-C')
        store.update_task('T-1', 'running', 'worker-C')
        (worktree / 'src/a.txt').write_text('after\n')
        if complete:
            git(worktree, 'add', 'src/a.txt')
            git(worktree, 'commit', '-qm', 'implement')
            store.submit_agent_result(dict(
                schema_version='3.0', run_id=store.run_id, task_id='T-1',
                agent_id='worker-C', role='implementer', status='complete',
                base_commit=baseline, head_commit=git(worktree, 'rev-parse', 'HEAD'),
                changed_paths=['src/a.txt'], evidence=[], risks=[], requested_transition='verifying'))
            store.update_task('T-1', 'complete', 'worker-C')
            store.transition('implementation-complete', {})
        return repo, worktree, store

    def wait_for_file(self, path, future):
        deadline = time.monotonic() + 15
        while not path.exists():
            if future.done():
                future.result()
                self.fail('controlled check exited before readiness signal')
            if time.monotonic() >= deadline:
                self.fail('controlled check did not reach readiness barrier')
            time.sleep(.02)

    def test_midflight_check_keeps_artifact_but_cannot_write_old_ledger(self):
        barrier = tempfile.TemporaryDirectory(prefix='cogito-replan-barrier-')
        self.addCleanup(barrier.cleanup)
        ready, release = (Path(barrier.name) / name for name in ('ready', 'release'))
        script = (
            'from pathlib import Path; import time\n'
            f'Path({str(ready)!r}).write_text("ready")\n'
            f'while not Path({str(release)!r}).exists(): time.sleep(.02)\n'
            'print("finished original check", flush=True)\n'
        )
        repo, worktree, store = self.fixture([sys.executable, '-I', '-c', script])
        rp = ReplanStore(repo, 'RP-live')
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(store.run_controlled_check, 'C-live', worktree, 'check-live')
        try:
            self.wait_for_file(ready, future)
            registry = snapshot(repo, store.run_id)
            self.assertFalse(registry['quiescent'])
            self.assertEqual(len(registry['entries']), 1)
            rp.begin(store.run_id, 'DEV-next', 'API requires a new contract', 'begin')
            blocked_events = store.events_path.read_bytes()
            self.assertEqual(store.load()['state'], 'blocked')
            with self.assertRaisesRegex(CogitoError, 'not confirmed stopped'):
                rp.stop('stop')
            self.assertEqual(rp.load()['state'], 'stopping')
            self.assertFalse(future.done())
            release.write_text('continue')
            with self.assertRaises(CogitoError):
                future.result(timeout=15)
            self.assertEqual(store.events_path.read_bytes(), blocked_events)
            artifacts = list((store.run_dir / 'evidence').glob('*.json'))
            self.assertEqual(len(artifacts), 1)
            evidence = load_json(artifacts[0])
            self.assertTrue(evidence['passed'])
            self.assertEqual(evidence['run_id'], store.run_id)
            self.assertFalse(any(e['type'] == 'check-evidence-recorded' for e in store._events.read()))
            self.assertTrue(snapshot(repo, store.run_id)['quiescent'])
            rp.stop('stop')
            self.assertEqual(rp.load()['state'], 'analyzing')
            self.assertEqual(store.events_path.read_bytes(), blocked_events)
            with self.assertRaises(CogitoError):
                store.run_controlled_check('C-live', worktree, 'check-live')
        finally:
            release.write_text('cleanup')
            pool.shutdown(wait=True)

    def test_running_worker_requires_actual_exit_before_snapshot(self):
        repo, worktree, store = self.fixture([sys.executable, '-c', 'print("ok")'], complete=False)
        child = subprocess.Popen(
            [sys.executable, '-u', '-c',
             'import sys; from pathlib import Path; print("ready", flush=True); '
             'sys.stdin.readline(); Path("src/a.txt").write_text("saved before exit\\n")'],
            cwd=worktree, start_new_session=True, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )
        try:
            self.assertEqual(child.stdout.readline(), b'ready\n')
            register_process(repo, store.run_id, 'worker-C', child.pid)
            rp = ReplanStore(repo, 'RP-worker')
            rp.begin(store.run_id, 'DEV-next', 'API changed', 'begin')
            with self.assertRaisesRegex(CogitoError, 'not confirmed stopped'):
                rp.stop('stop')
            self.assertEqual(rp.load()['state'], 'stopping')
            self.assertIsNone(child.poll())
            child.stdin.write(b'save\n')
            child.stdin.flush()
            self.assertEqual(child.wait(timeout=5), 0)
            rp.stop('stop')
            self.assertEqual(rp.load()['state'], 'analyzing')
            self.assertEqual((worktree / 'src/a.txt').read_text(), 'saved before exit\n')
            self.assertEqual(store.load()['tasks']['T-1']['status'], 'running')
            self.assertIn(str(worktree.resolve()), rp.load()['snapshot']['worktrees'])
        finally:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdin.close()
            child.stdout.close()


if __name__ == '__main__':
    import unittest
    unittest.main()
