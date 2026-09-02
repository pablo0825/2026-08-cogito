"""An independently requested Maintenance review fix keeps the Start HEAD."""
from pathlib import Path
import json
import sys
import tempfile

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_run_store import RunStore


class MaintenanceReviewFixTests(GitTestCase):
    def test_review_fix_records_snapshot_and_reverifies_added_task(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_repo(repo)
            (repo / '.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
            (repo / 'note.txt').write_text('before\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'baseline')
            base = git(repo, 'rev-parse', 'HEAD')
            draft = package('maintenance')
            draft.update({
                'baseline_commit': base, 'approved_paths': ['note.txt'],
                'execution_dag': {'tasks': [{'id': 'T-1', 'paths': ['note.txt']}], 'edges': []},
                'checks': [{'id': 'C-1', 'argv': [sys.executable, '-I', '-c',
                    "from pathlib import Path; assert Path('note.txt').read_text().strip() == 'after'"]}],
            })
            store = RunStore(repo, draft['run_id'])
            store.create('maintenance')
            store.prepare_package(draft)
            store.approve_package(draft)
            store.start_gate()

            def implement(task, text):
                store.update_task(task, 'leased', 'worker')
                store.update_task(task, 'running', 'worker')
                (repo / 'note.txt').write_text(text)
                store.submit_agent_result({
                    'schema_version': '3.0', 'run_id': store.run_id, 'task_id': task,
                    'agent_id': 'worker', 'role': 'implementer', 'status': 'complete',
                    'base_commit': base, 'head_commit': base, 'changed_paths': ['note.txt'],
                    'evidence': [], 'risks': [], 'requested_transition': 'verifying',
                })
                store.update_task(task, 'complete', 'worker')

            def check(action):
                before = set((store.run_dir / 'evidence').glob('*.json'))
                store.run_controlled_check('C-1', repo, action)
                path, = set((store.run_dir / 'evidence').glob('*.json')) - before
                evidence = json.loads(path.read_text())
                self.assertTrue(evidence['passed'])
                store.complete_verification([evidence])

            implement('T-1', 'after\n\n')
            store.transition('implementation-complete', {})
            check('first-check')
            store.submit_agent_result({
                'schema_version': '3.0', 'run_id': store.run_id, 'task_id': 'T-1',
                'agent_id': 'reviewer', 'role': 'reviewer', 'status': 'needs-fix',
                'reviewed_implementer': 'worker', 'base_commit': base, 'head_commit': base,
                'changed_paths': [], 'evidence': [], 'risks': ['remove extra blank line'],
                'requested_transition': 'review-fix',
            })
            store.enter_review_fix()
            store.add_amendment({
                'id': 'TA-review', 'reason': 'remove formatting defect',
                'added_tasks': [{'id': 'T-2', 'slice_id': 'mini-package', 'paths': ['note.txt']}],
            })
            implement('T-2', 'after\n')
            index_path = repo / '.git/index'
            index_before = index_path.read_bytes()
            store.complete_review_fix('TA-review', base, 'finish-review-fix')
            self.assertEqual(index_path.read_bytes(), index_before)
            self.assertEqual(git(repo, 'rev-parse', 'HEAD'), base)
            event = json.loads(store.events_path.read_text().splitlines()[-1])
            self.assertEqual(event['type'], 'review-fix-complete')
            self.assertEqual(event['payload']['completion_mode'], 'working-tree')
            self.assertEqual(git(repo, 'cat-file', '-t', event['payload']['content_tree']), 'tree')
            before = store.events_path.read_bytes()
            store.complete_review_fix('TA-review', base, 'finish-review-fix')
            self.assertEqual(store.events_path.read_bytes(), before)
            check('fixed-check')
            self.assertEqual(store.load()['tasks']['T-2']['status'], 'verified')
            self.assertEqual(store.load()['state'], 'reviewing')
