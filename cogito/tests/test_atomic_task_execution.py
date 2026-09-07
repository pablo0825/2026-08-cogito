"""Atomic Tasks bind one commit and targeted checks before sequential dispatch."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, atomic_package, git, init_repo, package
from cogito_common import CogitoError
from cogito_run_store import RunStore


class AtomicTaskTests(GitTestCase):
    def executing(self, configure=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        for name, content in {
            '.gitignore': '.cogito/\ndocs/cogito/packages/\n',
            'src/a.txt': 'before\n', 'src/b.txt': 'before\n',
            'docs/spec.md': 'spec\n', 'docs/plan.md': 'plan\n',
        }.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        base = git(repo, 'rev-parse', 'HEAD')
        draft = package()
        draft.update(baseline_commit=base,
                     human_gate={'predicates': [], 'high_risk_hotspots': []})
        draft['checks'] = [
            {'id': f'C-{name}', 'phase': 'task' if name == 'a' else 'integration',
             'argv': [sys.executable, '-I', '-c',
                      f"from pathlib import Path; assert Path('src/{name}.txt').read_text() == 'after\\n'"]}
            for name in ('a', 'b')
        ]
        draft['execution_dag'] = {
            'tasks': [{'id': f'T-{name}', 'slice_id': 'FS-1', 'paths': [f'src/{name}.txt']}
                      for name in ('a', 'b')],
            'edges': [{'from': 'T-a', 'to': 'T-b'}],
        }
        atomic_package(draft)
        for task, name in zip(draft['execution_dag']['tasks'], ('a', 'b')):
            task['check_ids'] = [f'C-{name}']
        for field in ('spec', 'plan'):
            document = draft['slices'][0][field]
            document['hash'] = hashlib.sha256((repo / document['path']).read_bytes()).hexdigest()
        if configure is not None:
            configure(draft)
        store = RunStore(repo, draft['run_id'])
        store.create('feature', task_delivery='atomic')
        store.transition('shared-understanding-ready', {'shared_understanding_hash': 'b' * 64})
        store.transition('shared-understanding-confirmed', {'confirmed': True})
        store.transition('boundary-complete', draft['boundary'])
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        worker = repo / draft['slices'][0]['worker']['worktree']
        git(repo, 'worktree', 'add', '-q', '-b', draft['slices'][0]['worker']['branch'], str(worker), base)
        return repo, worker, store, draft

    @staticmethod
    def lease(store, task='T-a'):
        store.update_task(task, 'leased', 'worker')
        store.update_task(task, 'running', 'worker')

    @staticmethod
    def commit(worker, message='implement task'):
        git(worker, 'add', 'src')
        git(worker, 'commit', '-qm', message)
        return git(worker, 'rev-parse', 'HEAD')

    @staticmethod
    def check(store, worker, check='C-a', action='check-a'):
        before = set((store.run_dir / 'evidence').glob('*.json'))
        store.run_controlled_check(check, worker, action)
        path, = set((store.run_dir / 'evidence').glob('*.json')) - before
        return json.loads(path.read_text())

    @staticmethod
    def result(store, worker, evidence=(), task='T-a'):
        base = store.load()['tasks'][task]['base_commit']
        head = git(worker, 'rev-parse', 'HEAD')
        return {
            'schema_version': '3.0', 'run_id': store.run_id, 'task_id': task,
            'agent_id': 'worker', 'role': 'implementer', 'status': 'complete',
            'base_commit': base, 'head_commit': head,
            'changed_paths': list(filter(None, git(worker, 'diff', '--name-only', base, head).splitlines())),
            'evidence': [item['evidence_path'] for item in evidence],
            'risks': [], 'requested_transition': 'verifying',
        }

    def implement(self, store, worker, name='a', *, precommit=False):
        task = f'T-{name}'
        self.lease(store, task)
        (worker / f'src/{name}.txt').write_text('after\n')
        if precommit:
            evidence = self.check(store, worker, f'C-{name}', f'check-{name}')
        self.commit(worker)
        if not precommit:
            evidence = self.check(store, worker, f'C-{name}', f'check-{name}')
        result = self.result(store, worker, [evidence], task)
        store.submit_agent_result(result)
        store.update_task(task, 'complete', 'worker')
        return result, evidence

    def test_completion_and_next_task_require_recorded_result(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        with self.assertRaises(CogitoError):
            store.update_task('T-a', 'complete', 'worker')
        with self.assertRaises(CogitoError):
            store.update_task('T-b', 'leased', 'worker')

    def test_invalid_completed_result_transition_is_rejected_before_recording(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        result = self.result(store, worker)
        result['requested_transition'] = 'executing'
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'must request verifying'):
            store.submit_agent_result(result, 'wrong-transition')
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual(store.load()['tasks']['T-a']['status'], 'running')

    def test_interrupted_task_retains_original_base_and_requires_fresh_evidence(self):
        for committed in (False, True):
            with self.subTest(committed=committed):
                _, worker, store, _ = self.executing()
                self.lease(store)
                base = git(worker, 'rev-parse', 'HEAD')
                (worker / 'src/a.txt').write_text('after\n')
                if committed:
                    self.commit(worker)
                old = self.check(store, worker)
                store.update_task('T-a', 'blocked', 'worker')
                store.update_task('T-a', 'pending', 'worker')
                self.lease(store)
                self.assertEqual(store.load()['tasks']['T-a']['base_commit'], base)
                if not committed:
                    self.commit(worker)
                with self.assertRaisesRegex(CogitoError, 'predates'):
                    store.submit_agent_result(self.result(store, worker, [old]))
                fresh = self.check(store, worker, action='resumed-check')
                store.submit_agent_result(self.result(store, worker, [fresh]))
                store.update_task('T-a', 'complete', 'worker')
                self.lease(store, 'T-b')

    def test_interrupted_task_cannot_absorb_another_task_or_rewrite_recorded_commit(self):
        for mode in ('outside-path', 'rewrite-recorded'):
            with self.subTest(mode=mode):
                _, worker, store, _ = self.executing()
                self.lease(store)
                (worker / 'src/a.txt').write_text('after\n')
                if mode == 'rewrite-recorded':
                    self.commit(worker)
                    evidence = self.check(store, worker)
                    store.submit_agent_result(self.result(store, worker, [evidence]))
                    git(worker, 'commit', '--amend', '-qm', 'different recorded commit')
                else:
                    (worker / 'src/b.txt').write_text('unowned change\n')
                store.update_task('T-a', 'blocked', 'worker')
                store.update_task('T-a', 'pending', 'worker')
                with self.assertRaises(CogitoError):
                    store.update_task('T-a', 'leased', 'worker')

    def test_one_commit_per_task_and_precommit_content_evidence(self):
        _, worker, store, _ = self.executing()
        first, evidence = self.implement(store, worker, precommit=True)
        self.assertEqual(evidence['head_commit'], first['base_commit'])
        second, _ = self.implement(store, worker, 'b')
        self.assertEqual(second['base_commit'], first['head_commit'])
        self.assertEqual(git(worker, 'rev-list', '--count', first['base_commit'] + '..HEAD'), '2')
        self.assertEqual(store.load()['tasks']['T-b']['status'], 'complete')

    def test_check_only_amendment_cannot_open_untracked_product_correction(self):
        _, worker, store, _ = self.executing()
        self.implement(store, worker)
        self.implement(store, worker, 'b')
        store.transition('implementation-complete', {})
        store.add_amendment({'id': 'TA-check', 'reason': 'additional integration check',
                             'added_checks': [{'id': 'C-extra', 'argv': [sys.executable, '-V']}]})
        with self.assertRaisesRegex(CogitoError, 'atomic corrections require amendment tasks'):
            store.enter_correction()

    def test_failed_unrecorded_commit_can_be_corrected_without_losing_evidence(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        base = git(worker, 'rev-parse', 'HEAD')
        (worker / 'src/a.txt').write_text('wrong\n')
        self.commit(worker)
        failed = self.check(store, worker)
        self.assertFalse(failed['passed'])
        original_bytes = Path(failed['evidence_path']).read_bytes()
        (worker / 'src/a.txt').write_text('after\n')
        git(worker, 'add', 'src/a.txt')
        git(worker, 'commit', '--amend', '-qm', 'fix unrecorded task')
        passed = self.check(store, worker, action='fixed-check')
        store.submit_agent_result(self.result(store, worker, [passed]))
        store.update_task('T-a', 'complete', 'worker')
        self.assertEqual(git(worker, 'rev-parse', 'HEAD^'), base)
        self.assertEqual(Path(failed['evidence_path']).read_bytes(), original_bytes)

    def test_complete_result_cannot_be_replaced_before_task_status_completion(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        evidence = self.check(store, worker)
        store.submit_agent_result(self.result(store, worker, [evidence]))
        git(worker, 'commit', '--amend', '-qm', 'rewrite after complete Result')
        replacement = self.check(store, worker, action='replacement-check')
        with self.assertRaisesRegex(CogitoError, 'cannot rewrite'):
            store.submit_agent_result(self.result(store, worker, [replacement]))

    def test_zero_empty_multiple_and_merge_commits_are_rejected(self):
        for mode in ('zero', 'empty', 'multiple', 'merge'):
            with self.subTest(mode=mode):
                _, worker, store, _ = self.executing()
                self.lease(store)
                if mode == 'empty':
                    git(worker, 'commit', '--allow-empty', '-qm', 'empty')
                elif mode in {'multiple', 'merge'}:
                    base = git(worker, 'rev-parse', 'HEAD')
                    (worker / 'src/a.txt').write_text('intermediate\n')
                    self.commit(worker)
                    (worker / 'src/a.txt').write_text('after\n')
                    head = self.commit(worker)
                    if mode == 'merge':
                        tree = git(worker, 'rev-parse', 'HEAD^{tree}')
                        merged = git(worker, 'commit-tree', tree, '-p', base, '-p', head, '-m', 'merge')
                        git(worker, 'reset', '--hard', merged)
                with self.assertRaisesRegex(CogitoError, 'exactly one nonempty commit'):
                    store.submit_agent_result(self.result(store, worker))

    def test_missing_failed_stale_and_tampered_evidence_are_rejected(self):
        for mode in ('missing', 'failed', 'stale', 'tampered'):
            with self.subTest(mode=mode):
                _, worker, store, _ = self.executing()
                self.lease(store)
                evidence = []
                if mode == 'failed':
                    evidence = [self.check(store, worker)]
                    self.assertFalse(evidence[0]['passed'])
                (worker / 'src/a.txt').write_text('after\n')
                if mode == 'stale':
                    evidence = [self.check(store, worker)]
                    (worker / 'src/a.txt').write_text('different\n')
                self.commit(worker)
                if mode == 'tampered':
                    evidence = [self.check(store, worker)]
                    evidence[0]['stdout'] = 'forged'
                    path = Path(evidence[0]['evidence_path'])
                    path.chmod(0o600)
                    path.write_text(json.dumps(evidence[0]))
                with self.assertRaises(CogitoError):
                    store.submit_agent_result(self.result(store, worker, evidence))

    def test_uncommitted_product_and_unauthorized_checks_are_rejected(self):
        repo, worker, store, _ = self.executing()
        self.lease(store)
        for check, location in (('C-b', worker), ('C-a', repo)):
            with self.subTest(check=check, location=location), self.assertRaises(CogitoError):
                store.run_controlled_check(check, location, 'unauthorized-' + check)
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        evidence = self.check(store, worker)
        (worker / 'src/a.txt').write_text('uncommitted\n')
        with self.assertRaises(CogitoError):
            store.submit_agent_result(self.result(store, worker, [evidence]))

    def test_content_changed_after_result_blocks_task_completion(self):
        _, worker, store, _ = self.executing()
        self.lease(store)
        (worker / 'src/a.txt').write_text('after\n')
        self.commit(worker)
        evidence = self.check(store, worker)
        store.submit_agent_result(self.result(store, worker, [evidence]))
        (worker / 'src/a.txt').write_text('changed after result\n')
        with self.assertRaises(CogitoError):
            store.update_task('T-a', 'complete', 'worker')

    def test_block_resume_preserves_completed_task_and_next_base(self):
        _, worker, store, _ = self.executing()
        result, _ = self.implement(store, worker)
        store.transition('block', {'reason': 'interrupt'}, 'block')
        store.resume_gate('resume')
        self.assertEqual(store.load()['tasks']['T-a']['status'], 'complete')
        self.lease(store, 'T-b')
        self.assertEqual(store.load()['tasks']['T-b']['base_commit'], result['head_commit'])
