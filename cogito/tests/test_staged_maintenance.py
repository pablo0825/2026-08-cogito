"""Real Git coverage for staged Maintenance paths and final delivery scope."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
import test_maintenance_corrections as corrections
import cogito_runtime as runtime


class StagedMaintenanceTests(GitTestCase):
    def fixture(self, *, cli=False, paths=None, persist_package=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        (repo / '.gitignore').write_text('.cogito/\n' + ('' if persist_package else 'docs/cogito/packages/\n'))
        for name in ('note.txt', 'delete.txt', 'old.txt', '中文.txt', 'line\nbreak.txt'):
            (repo / name).write_text('before\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        baseline = git(repo, 'rev-parse', 'HEAD')
        run_id = 'MNT-staged-scope'
        paths = paths or ['note.txt']
        draft = package('maintenance')
        draft.update({
            'run_id': run_id, 'baseline_commit': baseline, 'approved_paths': paths,
            'execution_dag': {'tasks': [{'id': 'T-1', 'paths': paths}], 'edges': []},
            'checks': [{'id': 'C-1', 'required': True, 'argv': [
                sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('note.txt').read_text() == 'after\\n'",
            ]}],
        })
        store = (corrections.MaintenanceCli if cli else runtime.RunStore)(repo, run_id)
        store.create('maintenance')
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        store.update_task('T-1', 'leased', 'worker-1')
        store.update_task('T-1', 'running', 'worker-1')
        return repo, store, baseline

    @staticmethod
    def result(store, baseline, paths):
        return {
            'schema_version': '3.0', 'run_id': store.run_id, 'task_id': 'T-1',
            'agent_id': 'worker-1', 'role': 'implementer', 'status': 'complete',
            'base_commit': baseline, 'head_commit': baseline, 'changed_paths': paths,
            'evidence': [], 'risks': [], 'requested_transition': 'verifying',
        }

    def assert_rejected_without_mutation(self, repo, store, operation):
        index = (repo / '.git/index').read_bytes()
        events = store.events_path.read_bytes()
        with self.assertRaises(runtime.CogitoError):
            operation()
        self.assertEqual((repo / '.git/index').read_bytes(), index)
        self.assertEqual(store.events_path.read_bytes(), events)

    def test_staged_only_result_is_accepted_by_public_cli(self):
        repo, store, baseline = self.fixture(cli=True)
        (repo / 'note.txt').write_text('after\n')
        git(repo, 'add', '--', 'note.txt')
        self.assertEqual(git(repo, 'diff', '--name-only'), '')
        store.submit_agent_result(self.result(store, baseline, ['note.txt']))
        self.assertEqual(store.load()['agent_results'][-1]['changed_paths'], ['note.txt'])

    def test_staged_outside_path_declared_or_omitted_cannot_be_recorded(self):
        for declared in (True, False):
            with self.subTest(declared=declared):
                repo, store, baseline = self.fixture()
                (repo / 'note.txt').write_text('after\n')
                (repo / 'outside.txt').write_text('not approved\n')
                git(repo, 'add', '--', 'note.txt', 'outside.txt')
                paths = ['note.txt', 'outside.txt'] if declared else ['note.txt']
                self.assert_rejected_without_mutation(
                    repo, store, lambda: store.submit_agent_result(self.result(store, baseline, paths)),
                )

    def test_staged_deletion_rename_and_non_ascii_or_newline_paths(self):
        paths = ['note.txt', 'delete.txt', 'old.txt', 'new.txt', '中文.txt', 'line\nbreak.txt']
        repo, store, baseline = self.fixture(paths=paths)
        (repo / 'note.txt').write_text('after\n')
        (repo / 'delete.txt').unlink()
        git(repo, 'mv', '--', 'old.txt', 'new.txt')
        (repo / '中文.txt').write_text('after\n')
        (repo / 'line\nbreak.txt').write_text('after\n')
        git(repo, 'add', '-A')
        store.submit_agent_result(self.result(store, baseline, paths))
        self.assertEqual(set(store.load()['agent_results'][-1]['changed_paths']), set(paths))

    def test_rename_cannot_hide_deleted_path_outside_approval(self):
        repo, store, baseline = self.fixture(paths=['note.txt', 'new.txt'])
        (repo / 'note.txt').write_text('after\n')
        git(repo, 'mv', '--', 'old.txt', 'new.txt')
        git(repo, 'add', '--', 'note.txt')
        self.assert_rejected_without_mutation(
            repo, store,
            lambda: store.submit_agent_result(self.result(store, baseline, ['note.txt', 'new.txt'])),
        )

    def test_staged_index_change_is_detected_even_if_worktree_reverts_it(self):
        repo, store, baseline = self.fixture()
        (repo / 'note.txt').write_text('after\n')
        git(repo, 'add', '--', 'note.txt')
        (repo / 'note.txt').write_text('before\n')
        store.submit_agent_result(self.result(store, baseline, ['note.txt']))
        self.assertEqual(store.load()['agent_results'][-1]['changed_paths'], ['note.txt'])

    def test_legal_staged_changes_reach_accepted_with_one_commit_via_cli(self):
        self.finish_staged(cli=True)

    def test_approved_package_can_be_saved_in_final_commit(self):
        self.finish_staged(persist_package=True)

    def test_finalization_rechecks_outside_scope_even_if_verified(self):
        self.finish_staged(inject_outside=True)

    def finish_staged(self, *, cli=False, persist_package=False, inject_outside=False):
        repo, store, baseline = self.fixture(cli=cli, persist_package=persist_package)
        (repo / 'note.txt').write_text('after\n')
        git(repo, 'add', '--', 'note.txt')
        store.submit_agent_result(self.result(store, baseline, ['note.txt']))
        store.update_task('T-1', 'complete', 'worker-1')
        store.transition('implementation-complete', {})
        if inject_outside:
            (repo / 'outside.txt').write_text('present before checks but never approved\n')
            git(repo, 'add', '--', 'outside.txt')
        check = corrections.MaintenanceCorrectionTests.check(store, repo, 'pre')
        self.assertTrue(check['passed'])
        store.complete_verification([check])
        store.transition('review-approved', {'review_exemption': True})
        store.complete_integration(baseline)
        post = corrections.MaintenanceCorrectionTests.check(store, repo, 'post')
        self.assertTrue(post['passed'])
        store.decide_post_verification([post])
        graph_rel = 'docs/cogito/project-graph.json'
        graph = json.loads((repo / graph_rel).read_text())
        graph['active_run_id'] = None
        (repo / graph_rel).write_text(json.dumps(graph))
        result_rel = f'docs/cogito/results/{store.run_id}.json'
        result_path = repo / result_rel
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps({
            'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': runtime.package_hash(store.approved_package()),
            'effective_contract_hash': store.load()['effective_contract_hash'],
            'integration_commits': [baseline], 'slice_dispositions': {},
            'checks': [{'id': 'C-1', 'status': 'passed', 'evidence': post['evidence_path']}],
            'reviews': [], 'amendments': [],
            'human_gate': {'required': False, 'outcome': 'not-required'}, 'remaining_risks': [],
        }))
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'staged maintenance delivery')
        final = git(repo, 'rev-parse', 'HEAD')
        self.assertEqual(git(repo, 'rev-list', '--count', f'{baseline}..{final}'), '1')
        if inject_outside:
            self.assert_rejected_without_mutation(
                repo, store, lambda: store.finalize(result_rel, graph_rel, final),
            )
            self.assertEqual(store.load()['state'], 'finalizing')
        else:
            store.finalize(result_rel, graph_rel, final)
            self.assertEqual(store.completion_report()['status'], 'accepted')
            self.assertEqual(store.completion_report()['final_commit'], final)
