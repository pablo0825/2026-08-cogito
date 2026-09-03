"""Real integration commits cannot introduce paths outside the approved Package."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, SCRIPTS, git, init_repo, package
import test_feature_e2e as feature_helpers
import cogito_runtime as runtime


class IntegrationScopeTests(GitTestCase):
    def ready_to_integrate(self, kind='feature', *, unusual_worker_paths=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        files = {
            '.gitignore': '.cogito/\ndocs/cogito/packages/\n',
            'src/a/value.txt': 'before\n', 'src/a/old.txt': 'rename me\n',
            'src/b/value.txt': 'other slice\n', 'outside-old.txt': 'outside\n',
            'docs/spec.md': 'spec\n', 'docs/plan.md': 'plan\n',
        }
        for name, content in files.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        base = git(repo, 'rev-parse', 'HEAD')
        draft = package(kind)
        draft.update({
            'run_id': 'DEV-integration-scope', 'baseline_commit': base,
            'approved_paths': ['src/a/**', 'src/b/**'],
            'boundary': {'decision': 'split-required', 'evidence': ['separate responsibilities']},
            'human_gate': {'predicates': [], 'high_risk_hotspots': []},
            'checks': [{'id': 'C-1', 'required': True, 'argv': [sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('src/a/value.txt').read_text() == 'after implementation\\n'"]}],
            'execution_dag': {
                'tasks': [{'id': f'T-{name}', 'slice_id': f'FS-{name}', 'paths': [f'src/{name.lower()}/**']}
                          for name in ('A', 'B')],
                'edges': [{'from': 'T-A', 'to': 'T-B'}],
            },
        })
        draft['slices'] = [{
            'id': f'FS-{name}', 'type': kind,
            'spec': {'path': 'docs/spec.md', 'hash': hashlib.sha256((repo / 'docs/spec.md').read_bytes()).hexdigest()},
            'plan': {'path': 'docs/plan.md', 'hash': hashlib.sha256((repo / 'docs/plan.md').read_bytes()).hexdigest()},
            'worker': {'branch': f'codex/fs-{name.lower()}', 'worktree': f'.cogito/worktrees/FS-{name}',
                       'allowed_paths': [f'src/{name.lower()}/**']},
        } for name in ('A', 'B')]
        store = runtime.RunStore(repo, draft['run_id'])
        store.create(kind)
        store.transition('shared-understanding-ready', {'shared_understanding_hash': 'b' * 64})
        store.transition('shared-understanding-confirmed', {'confirmed': True})
        store.transition('boundary-complete', draft['boundary'])
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        worker = repo / '.cogito/worktrees/FS-A'
        git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-a', str(worker), base)
        store.update_task('T-A', 'leased', 'worker-a')
        store.update_task('T-A', 'running', 'worker-a')
        (worker / 'src/a/value.txt').write_text('after implementation\n')
        changed = ['src/a/value.txt']
        if unusual_worker_paths:
            name = 'src/a/中文\n新檔.txt'
            git(worker, 'mv', '--', 'src/a/old.txt', name)
            changed.extend(['src/a/old.txt', name])
        git(worker, 'add', '-A')
        git(worker, 'commit', '-qm', 'implement slice A')
        head = git(worker, 'rev-parse', 'HEAD')
        helper = feature_helpers.FeatureMultiSliceEndToEndTests
        store.submit_agent_result(helper._result(store.run_id, 'T-A', 'worker-a', 'implementer',
                                                base, head, changed, 'verifying'))
        store.update_task('T-A', 'complete', 'worker-a')
        store.transition('implementation-complete', {})
        evidence = helper._run_check(store, worker, 'verify-a')
        self.assertTrue(evidence['passed'], evidence)
        store.complete_verification([evidence])
        store.submit_agent_result(helper._result(store.run_id, 'T-A', 'reviewer-a', 'reviewer',
                                                base, head, [], 'review-approved', 'worker-a'))
        store.transition('review-approved', {})
        git(repo, 'merge', '--no-ff', '--no-commit', 'codex/fs-a')
        return repo, store, base

    def invoke_integrate(self, repo, store):
        return subprocess.run([
            sys.executable, '-B', str(SCRIPTS / 'cogito_gate.py'), '--repo', str(repo),
            'integrate', '--run-id', store.run_id, '--slice-id', 'FS-A',
            '--commit-id', git(repo, 'rev-parse', 'HEAD'), '--action-id', 'integrate-a',
        ], capture_output=True, text=True, timeout=20)

    def assert_integration_rejected(self, repo, store):
        git(repo, 'commit', '-qm', 'merge with undeclared integration content')
        before_events = store.events_path.read_bytes()
        before_index = (repo / '.git/index').read_bytes()
        before_head = git(repo, 'rev-parse', 'HEAD')
        response = self.invoke_integrate(repo, store)
        self.assertEqual(response.returncode, 2, response.stdout + response.stderr)
        self.assertEqual(response.stdout, '')
        error = json.loads(response.stderr)
        self.assertIs(error['ok'], False)
        self.assertIn('approved paths', error['error'])
        self.assertNotIn('Traceback', response.stderr)
        self.assertEqual(store.events_path.read_bytes(), before_events)
        self.assertEqual((repo / '.git/index').read_bytes(), before_index)
        self.assertEqual(git(repo, 'rev-parse', 'HEAD'), before_head)
        self.assertEqual(store.load()['state'], 'integrating')

    def test_feature_change_correction_reject_unapproved_merge_content_via_cli(self):
        for kind in ('feature', 'change', 'correction'):
            with self.subTest(kind=kind):
                repo, store, _ = self.ready_to_integrate(kind)
                (repo / 'unrelated.txt').write_text('never approved\n')
                git(repo, 'add', '--', 'unrelated.txt')
                self.assert_integration_rejected(repo, store)

    def test_integration_preserves_existing_package_wide_path_policy(self):
        repo, store, _ = self.ready_to_integrate()
        (repo / 'src/b/value.txt').write_text('package approved integration correction\n')
        git(repo, 'add', '--', 'src/b/value.txt')
        git(repo, 'commit', '-qm', 'integration correction within package scope')
        response = self.invoke_integrate(repo, store)
        self.assertEqual(response.returncode, 0, response.stderr)
        self.assertEqual(json.loads(response.stdout)['data']['tasks']['T-A']['status'], 'integrated')

    def test_rename_cannot_hide_unapproved_source_or_destination(self):
        for source, destination in (
            ('outside-old.txt', 'src/a/imported.txt'),
            ('src/a/old.txt', '外部\n重新命名.txt'),
        ):
            with self.subTest(source=source, destination=destination):
                repo, store, _ = self.ready_to_integrate()
                git(repo, 'mv', '--', source, destination)
                self.assert_integration_rejected(repo, store)

    def test_unapproved_unicode_newline_path_cannot_evade_scope(self):
        repo, store, _ = self.ready_to_integrate()
        name = '未核准\n檔案.txt'
        (repo / name).write_text('unapproved\n')
        git(repo, 'add', '--', name)
        self.assert_integration_rejected(repo, store)

    def test_approved_worker_rename_with_unicode_newline_path_integrates(self):
        repo, store, _ = self.ready_to_integrate(unusual_worker_paths=True)
        git(repo, 'commit', '-qm', 'integrate reviewed unicode rename')
        response = self.invoke_integrate(repo, store)
        self.assertEqual(response.returncode, 0, response.stderr)
        state = json.loads(response.stdout)['data']
        self.assertEqual(state['state'], 'executing')
        self.assertEqual(state['tasks']['T-A']['status'], 'integrated')
        self.assertEqual((repo / 'src/a/中文\n新檔.txt').read_text(), 'rename me\n')

    def test_finalization_scope_rechecks_historical_delivery_for_every_kind(self):
        # Exercise the finalization IO boundary directly with historical inputs.
        # No live Gate is made to approve the unsafe commit, and no gate is mocked.
        from cogito_finalization import _validate_delivery_scope
        from cogito_finalization_rules import FinalizationContext

        for kind in ('feature', 'change', 'correction', 'maintenance', 'documentation'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory)
                init_repo(repo)
                (repo / 'product.txt').write_text('baseline\n')
                git(repo, 'add', '.')
                git(repo, 'commit', '-qm', 'historical start')
                baseline = git(repo, 'rev-parse', 'HEAD')
                # This content could already appear in old verification evidence;
                # the delivery-scope check must independently reject it.
                (repo / 'unrelated.txt').write_text('historically integrated outside approval\n')
                git(repo, 'add', '--', 'unrelated.txt')
                git(repo, 'commit', '-qm', 'historical out-of-scope integration')
                final = git(repo, 'rev-parse', 'HEAD')
                draft = package(kind)
                draft['baseline_commit'] = baseline
                draft['approved_paths'] = ['product.txt']
                context = FinalizationContext(
                    run_id=draft['run_id'], package=draft, state={},
                    events=[{'type': 'start-gate-passed', 'payload': {'delivery_head': baseline}}],
                    result={}, graph={}, effective_contract={},
                )
                index_before = (repo / '.git/index').read_bytes()
                with self.assertRaisesRegex(runtime.CogitoError, 'approved paths'):
                    _validate_delivery_scope(
                        context, final,
                        {f'docs/cogito/results/{draft["run_id"]}.json', 'docs/cogito/project-graph.json'},
                        lambda *args: git(repo, *args),
                    )
                self.assertEqual((repo / '.git/index').read_bytes(), index_before)
                self.assertEqual(git(repo, 'rev-parse', 'HEAD'), final)
