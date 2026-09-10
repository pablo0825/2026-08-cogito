"""Git diagnostics distinguish actual merge conflicts from failed checks."""
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, init_repo, git
from cogito_common import CogitoError
from cogito_git import GitRepository
from cogito_atomic_integration import validate_atomic_integration


class GitErrorReportingTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        init_repo(self.repo)

    def validate(self, run):
        validate_atomic_integration(
            [dict(task_id='T-1', role='implementer', status='complete', head_commit='tip')],
            ['T-1'], [], 'base', 'integration', set(), run)

    def test_permission_and_command_failures_preserve_stderr_without_conflict_advice(self):
        for code, detail in [(128, 'error: insufficient permission for adding an object'),
                             (129, 'error: unknown option write-tree'),
                             (1, 'error: unable to write object')]:
            with self.subTest(code=code, detail=detail):
                failure = subprocess.CalledProcessError(code, ['git', 'merge-tree'], output='', stderr=detail)
                with mock.patch('cogito_git.subprocess.run', side_effect=failure):
                    with self.assertRaises(CogitoError) as caught:
                        self.validate(GitRepository(self.repo).run)
                self.assertIn(detail, str(caught.exception))
                self.assertIn('did not complete', str(caught.exception))
                self.assertNotIn('resolve the conflict', str(caught.exception))

    def test_timeout_and_process_launch_failure_are_not_merge_conflicts(self):
        for failure in (PermissionError('process launch denied'), subprocess.TimeoutExpired(['git'], 20)):
            with self.subTest(error=failure), mock.patch('cogito_git.subprocess.run', side_effect=failure):
                with self.assertRaises(CogitoError) as caught:
                    self.validate(GitRepository(self.repo).run)
                self.assertIn(str(failure), str(caught.exception))
                self.assertNotIn('resolve the conflict', str(caught.exception))

    def test_real_git_conflict_keeps_reviewed_conflict_guidance(self):
        path = self.repo / 'value.txt'
        path.write_text('base\n')
        git(self.repo, 'add', 'value.txt')
        git(self.repo, 'commit', '-qm', 'base')
        git(self.repo, 'branch', 'tip')
        path.write_text('left\n')
        git(self.repo, 'commit', '-qam', 'left')
        git(self.repo, 'branch', 'base')
        git(self.repo, 'checkout', '-q', 'tip')
        path.write_text('right\n')
        git(self.repo, 'commit', '-qam', 'right')
        with self.assertRaisesRegex(CogitoError, 'found merge conflicts.*resolve the conflict'):
            self.validate(GitRepository(self.repo).run)

    def test_unrelated_git_error_retains_diagnostic(self):
        with self.assertRaises(CogitoError) as caught:
            GitRepository(self.repo).run('rev-parse', '--verify', 'missing-revision')
        self.assertIn('fatal:', str(caught.exception))
