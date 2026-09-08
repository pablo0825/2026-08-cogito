"""Accepted cleanup is recoverable without changing the delivery verdict."""
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, SCRIPTS, git
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_run_store import RunStore
import cogito_gate as gate_module
import test_atomic_task_verification as verification


class CleanupFinalizationTests(GitTestCase):
    def test_normal_history_package_fallback_rejects_symlink(self):
        from cogito_cleanup import read_run_references
        repo, _, store, args = self.finalizing()
        store.finalize(*args)
        self.assertTrue(read_run_references(repo, store.run_id))
        path = repo / store.load()['package_path']
        saved = store.run_dir / 'package-copy.json'
        saved.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(saved)
        with self.assertRaisesRegex(CogitoError, 'symlink'):
            read_run_references(repo, store.run_id)

    def test_reference_reader_uses_committed_package_without_cache_writes(self):
        from cogito_cleanup import read_run_references
        repo, worker, store, args = self.finalizing(commit_package=True)
        store.finalize(*args)
        state = store.load()
        cache = store.state_path.read_bytes()
        events = store.events_path.read_bytes()
        (repo / state['package_path']).chmod(0o644)
        (repo / state['package_path']).write_text('{}')
        references = read_run_references(repo, store.run_id)
        self.assertTrue(any((repo / r.get('worktree', '.')).resolve() == worker for r in references))
        self.assertEqual(store.state_path.read_bytes(), cache)
        self.assertEqual(store.events_path.read_bytes(), events)
        store.state_path.unlink()
        read_run_references(repo, store.run_id)
        self.assertFalse(store.state_path.exists())

    @staticmethod
    def finalize_cli_arguments(store, args):
        return [
            "finalize", "--run-id", store.run_id, "--result", args[0],
            "--project-graph", args[1], "--final-commit", args[2],
            "--action-id", args[3],
        ]

    def finalizing(self, *, commit_package=False):
        fixture = verification.AtomicVerificationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        repo, worker, store, draft, _, _, integration = fixture.integrated()
        if commit_package:
            git(repo, 'add', '-f', store.load()['package_path'])
            git(repo, 'commit', '-qm', 'retain frozen Package')
        post = fixture.check(store, repo, 'C-b', 'post-cleanup')
        store.decide_post_verification([post])
        graph_path = repo / 'docs/cogito/project-graph.json'
        graph = json.loads(graph_path.read_text())
        graph['active_run_id'] = None
        graph['slices']['FS-1'].update(disposition='accepted', completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        relative = f'docs/cogito/results/{store.run_id}.json'
        result = repo / relative
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({
            'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': package_hash(store.approved_package()),
            'effective_contract_hash': store.load()['effective_contract_hash'],
            'integration_commits': [integration], 'slice_dispositions': {'FS-1': 'accepted'},
            'checks': [{'id': 'C-b', 'status': 'passed', 'evidence': post['evidence_path']}],
            'reviews': [{'reviewer': 'reviewer'}], 'amendments': [],
            'human_gate': {'required': False, 'outcome': 'not-required'}, 'remaining_risks': [],
        }))
        git(repo, 'add', relative, 'docs/cogito/project-graph.json')
        git(repo, 'commit', '-qm', 'record delivery')
        args = (relative, 'docs/cogito/project-graph.json', git(repo, 'rev-parse', 'HEAD'), 'finalize-cleanup')
        return repo, worker.resolve(), store, args

    def test_finalize_removes_worktree_preserves_report_and_replays(self):
        repo, worker, store, args = self.finalizing()
        accepted = store.finalize(*args)
        self.assertEqual(accepted['state'], 'accepted')
        self.assertEqual(accepted['cleanup']['removed'], [str(worker)])
        self.assertFalse(worker.exists())
        events = store.events_path.read_bytes()
        report = store.completion_report()
        self.assertEqual(RunStore(repo, store.run_id).completion_report(), report)
        self.assertNotIn('cleanup', store.load())
        self.assertEqual(store.finalize(*args)['cleanup']['removed'], [])
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(store.completion_report(), report)

    def test_cleanup_failure_leaves_accepted_and_same_action_can_retry(self):
        repo, worker, store, args = self.finalizing()
        output = io.StringIO()
        with mock.patch('cogito_cleanup.cleanup_accepted', side_effect=OSError('busy')), \
                redirect_stdout(output):
            code = gate_module.main([
                "--repo", str(repo), *self.finalize_cli_arguments(store, args),
            ])
        self.assertEqual(code, 0)
        accepted = json.loads(output.getvalue())["data"]
        self.assertEqual(set(accepted), {
            "run_id", "state", "sequence", "last_event_hash", "cleanup",
        })
        self.assertEqual(accepted['state'], 'accepted')
        self.assertEqual(accepted['cleanup']['error'], 'busy')
        self.assertTrue(worker.exists())
        events = store.events_path.read_bytes()
        self.assertEqual(store.finalize(*args)['cleanup']['removed'], [str(worker)])
        self.assertEqual(store.events_path.read_bytes(), events)
        with self.assertRaises(CogitoError):
            store.finalize(args[0], args[1], '0' * 40, args[3])

    def test_finalize_cli_retains_cleanup_result_without_full_state(self):
        repo, worker, store, args = self.finalizing()
        (worker / "local-secret.txt").write_text("keep\n")
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "cogito_gate.py"), "--repo", str(repo),
             *self.finalize_cli_arguments(store, args)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)["data"]
        self.assertEqual(set(receipt), {
            "run_id", "state", "sequence", "last_event_hash", "cleanup",
        })
        self.assertEqual(receipt["cleanup"]["removed"], [])
        self.assertEqual(receipt["cleanup"]["retained"][0]["worktree"], str(worker))
        self.assertNotIn("tasks", receipt)
        self.assertLess(len(result.stdout.encode()), 2 * 1024)

    def test_future_replan_captures_accepted_source_after_cleanup(self):
        from cogito_replan_store import ReplanStore
        repo, worker, store, args = self.finalizing()
        store.finalize(*args)
        self.assertFalse(worker.exists())
        replan = ReplanStore(repo, 'RP-cleanup')
        replan.begin(store.run_id, 'DEV-after-cleanup', 'New requirement', 'begin')
        saved = replan._capture()
        self.assertNotIn(str(worker), saved['worktrees'])
        self.assertEqual(saved['tasks'], store.load()['tasks'])
        (store.run_dir / 'cleanup.json').unlink()
        with self.assertRaises(CogitoError):
            replan._capture()

    def test_future_disposition_captures_cleaned_accepted_source(self):
        from cogito_disposition_store import DispositionStore
        repo, worker, store, args = self.finalizing()
        store.finalize(*args)
        self.assertFalse(worker.exists())
        disposition = DispositionStore(repo, 'DP-cleanup')
        disposition.begin(store.run_id, 'Review completed delivery', 'begin')
        saved = disposition._capture()
        self.assertNotIn(str(worker), saved['worktrees'])
        (store.run_dir / 'cleanup.json').unlink()
        with self.assertRaises(CogitoError):
            disposition._capture()
