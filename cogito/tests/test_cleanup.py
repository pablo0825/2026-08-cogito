"""Cleanup deletes only proven disposable accepted worktrees, retaining audit refs."""
from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cogito_test_support import GitTestCase, git, init_repo
from cogito_cleanup import cleanup_accepted, cleaned_worktree
from cogito_execution_registry import register_external


class CleanupTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        init_repo(self.root)
        (self.root / '.gitignore').write_text('.cogito/\nnode_modules/\n.env\n')
        (self.root / 'source').write_text('baseline')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'baseline')
        self.worker = self.root / '.cogito/worktrees/FS-1'
        git(self.root, 'worktree', 'add', '-qb', 'worker', str(self.worker))
        (self.worker / 'source').write_text('implemented')
        git(self.worker, 'commit', '-qam', 'implementation')
        head = git(self.worker, 'rev-parse', 'HEAD')
        git(self.root, 'merge', '--ff-only', 'worker')
        run_dir = self.root / '.cogito/runs/RUN-1'
        run_dir.mkdir(parents=True)
        self.state = {'state': 'accepted', 'tasks': {'T-1': {
            'worktree': str(self.worker), 'branch': 'worker', 'status': 'integrated',
            'head_commit': head}}, 'evidence': {}}
        self.final = {'type': 'finalization-complete', 'event_hash': 'a' * 64,
                      'payload': {'final_commit': head}}
        self.package = {'slices': [{'worker': {'worktree': '.cogito/worktrees/FS-1', 'branch': 'worker'}}]}
        self.store = SimpleNamespace(root=self.root, run_dir=run_dir, run_id='RUN-1',
            load=lambda: self.state, approved_package=lambda: self.package,
            completion_report=lambda: {}, _events=SimpleNamespace(read=lambda: [self.final]))

    def test_remove_dependency_cache_preserves_branch_runtime_and_pinned_tree(self):
        (self.worker / 'node_modules').mkdir()
        (self.worker / 'node_modules/dependency').write_text('cache')
        (self.worker / 'source').write_text('earlier audited snapshot')
        git(self.worker, 'add', 'source')
        tree = git(self.worker, 'write-tree')
        git(self.worker, 'reset', '--hard', 'HEAD')
        self.state['content_tree'] = tree
        outcome = cleanup_accepted(self.store)
        self.assertEqual(outcome['retained'], [])
        self.assertEqual(outcome['removed'], [str(self.worker)])
        self.assertFalse(self.worker.exists())
        self.assertTrue(cleaned_worktree(self.store, self.worker))
        git(self.root, 'show-ref', '--verify', 'refs/heads/worker')
        self.assertEqual(git(self.root, 'show-ref', '--hash', '--verify',
            f'refs/cogito/cleanup/RUN-1/{tree}'), tree)
        git(self.root, 'reflog', 'expire', '--expire=now', '--all')
        git(self.root, 'gc', '--prune=now')
        self.assertEqual(git(self.root, 'show', tree + ':source'), 'earlier audited snapshot')
        self.assertTrue(self.store.run_dir.exists())
        self.assertEqual(cleanup_accepted(self.store), {'removed': [], 'retained': []})

    def test_unknown_ignored_and_untracked_data_and_changes_are_retained(self):
        for filename in ('.env', 'local.db', 'source'):
            with self.subTest(filename=filename):
                path = self.worker / filename
                original = path.read_bytes() if path.exists() else None
                path.write_text('private data')
                self.assertTrue(cleanup_accepted(self.store)['retained'])
                self.assertTrue(path.exists())
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_unintegrated_work_and_unfinished_executor_are_retained(self):
        register_external(self.root, 'RUN-1', 'worker-1', 'external-handle')
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertTrue(self.worker.exists())
        (self.store.run_dir / 'execution-registry.json').unlink()
        (self.worker / 'source').write_text('later work')
        git(self.worker, 'commit', '-qam', 'later')
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertTrue(self.worker.exists())

    def test_missing_without_receipt_and_locked_worktree_are_not_cleanup_proof(self):
        git(self.root, 'worktree', 'lock', str(self.worker))
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        git(self.root, 'worktree', 'unlock', str(self.worker))
        git(self.root, 'worktree', 'remove', str(self.worker))
        self.assertFalse(cleaned_worktree(self.store, self.worker))

    def test_accepted_and_ownership_are_required(self):
        self.state['state'] = 'executing'
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.state['state'] = 'accepted'
        self.state['tasks']['T-1']['branch'] = 'different'
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertTrue(self.worker.exists())

    def test_remove_failure_retains_accepted_and_prepared_proof_is_retryable(self):
        from cogito_git import GitRepository
        from cogito_common import CogitoError
        original = GitRepository.run
        def failing(git_repo, *args):
            if args[:2] == ('worktree', 'remove'):
                raise CogitoError('simulated removal failure')
            return original(git_repo, *args)
        with patch.object(GitRepository, 'run', failing):
            self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertEqual(self.state['state'], 'accepted')
        self.assertFalse(cleaned_worktree(self.store, self.worker))
        self.assertEqual(cleanup_accepted(self.store)['removed'], [str(self.worker)])

    def test_managed_symlink_and_package_path_mismatch_are_retained(self):
        alias = self.root / '.cogito/worktrees/alias'
        alias.symlink_to(self.worker, target_is_directory=True)
        self.package['slices'][0]['worker']['worktree'] = '.cogito/worktrees/alias'
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertTrue(self.worker.exists())

    def test_active_replan_or_disposition_blocks_removal(self):
        for source in ('replans', 'dispositions'):
            with self.subTest(source=source), patch('cogito_cleanup.' + source,
                    return_value=iter([{'state': 'stopping'}])):
                self.assertTrue(cleanup_accepted(self.store)['retained'])
                self.assertTrue(self.worker.exists())

    def test_other_run_reference_and_missing_evidence_object_block_removal(self):
        other_dir = self.root / '.cogito/runs/RUN-2'
        other_dir.mkdir()
        other = SimpleNamespace(load=lambda: {'tasks': {'T-other': {'branch': 'worker'}}})
        with patch('cogito_run_store.RunStore', return_value=other):
            self.assertTrue(cleanup_accepted(self.store)['retained'])
            self.assertTrue(self.worker.exists())
        other_dir.rmdir()
        self.state['content_tree'] = '1' * 40
        self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertTrue(self.worker.exists())

    def test_crash_after_removal_recovers_from_prepared_receipt(self):
        from cogito_git import GitRepository
        original = GitRepository.run
        def crashing(git_repo, *args):
            value = original(git_repo, *args)
            if args[:2] == ('worktree', 'remove'):
                raise OSError('simulated lost response after deletion')
            return value
        with patch.object(GitRepository, 'run', crashing):
            self.assertTrue(cleanup_accepted(self.store)['retained'])
        self.assertFalse(self.worker.exists())
        self.assertTrue(cleaned_worktree(self.store, self.worker))
        self.assertEqual(cleanup_accepted(self.store), {'removed': [], 'retained': []})
        git(self.root, 'update-ref', '-d', 'refs/cogito/cleanup/RUN-1/' + self.final['payload']['final_commit'])
        self.assertFalse(cleaned_worktree(self.store, self.worker))

    def test_index_flags_cannot_hide_changed_product_files(self):
        for flag in ('assume-unchanged', 'skip-worktree'):
            with self.subTest(flag=flag):
                git(self.worker, 'update-index', '--' + flag, 'source')
                (self.worker / 'source').write_text('hidden edits')
                self.assertTrue(cleanup_accepted(self.store)['retained'])
                self.assertTrue(self.worker.exists())
                git(self.worker, 'update-index', '--no-' + flag, 'source')
                git(self.worker, 'checkout', '--', 'source')

    def test_nested_registered_worktree_under_dependency_cache_is_retained(self):
        nested = self.worker / 'node_modules/nested-project'
        git(self.root, 'worktree', 'add', '-qb', 'nested-worker', str(nested))
        outcome = cleanup_accepted(self.store)
        self.assertTrue(outcome['retained'])
        self.assertIn('nested', outcome['retained'][0]['reason'])
        self.assertTrue(self.worker.exists())
        self.assertEqual(git(nested, 'branch', '--show-current'), 'nested-worker')

    def test_other_run_ancestor_or_descendant_path_is_retained(self):
        (self.root / '.cogito/runs/RUN-2').mkdir()
        for referenced in (self.worker.parent, self.worker / 'node_modules/nested'):
            with self.subTest(referenced=referenced):
                other = SimpleNamespace(load=lambda: {'tasks': {'T-other': {
                    'worktree': str(referenced), 'branch': 'different'}}})
                with patch('cogito_run_store.RunStore', return_value=other):
                    self.assertTrue(cleanup_accepted(self.store)['retained'])
                    self.assertTrue(self.worker.exists())

    def test_other_run_delivery_root_lease_does_not_block_cleanup(self):
        (self.root / '.cogito/runs/RUN-2').mkdir()
        other = SimpleNamespace(load=lambda: {'tasks': {'T-maintenance': {
            'worktree': str(self.root), 'branch': 'delivery'}}})
        with patch('cogito_run_store.RunStore', return_value=other):
            outcome = cleanup_accepted(self.store)
        self.assertEqual(outcome['retained'], [])
        self.assertEqual(outcome['removed'], [str(self.worker)])
        self.assertTrue(self.root.exists())
