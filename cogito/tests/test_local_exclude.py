"""Runtime defaults stay local and preserve repository user rules."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase, git, init_repo
from cogito_common import CogitoError
from cogito_local_exclude import ensure_local_excludes


class LocalExcludeTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)
        init_repo(self.repo)
        self.exclude = self.repo / '.git' / 'info' / 'exclude'

    def invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(COGITO / 'scripts' / 'cogito_gate.py'),
             '--repo', str(self.repo), *args], text=True, capture_output=True,
        )

    def test_init_installs_defaults_without_untracking_files(self) -> None:
        tracked = self.repo / '.cogito' / 'runs' / 'existing.json'
        tracked.parent.mkdir(parents=True)
        tracked.write_text('{}')
        git(self.repo, 'add', str(tracked))
        result = self.invoke('init', '--no-stage-commits', '--run-id', 'DEV-exclude', '--kind', 'feature')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('.cogito/runs/existing.json', git(self.repo, 'ls-files'))
        for relative in ('.cogito/runs/other/events.jsonl', '.cogito/worktrees/other/file'):
            self.assertEqual(git(self.repo, 'check-ignore', relative), relative)
        self.assertFalse((self.repo / '.gitignore').exists())

    def test_existing_bytes_and_exceptions_take_precedence_and_are_idempotent(self) -> None:
        self.exclude.parent.mkdir(parents=True, exist_ok=True)
        original = b'# user rules\r\n!/.cogito/runs/\r\ncustom-no-final-newline'
        self.exclude.write_bytes(original)
        ensure_local_excludes(self.repo)
        updated = self.exclude.read_bytes()
        self.assertTrue(updated.endswith(original))
        ensure_local_excludes(self.repo)
        self.assertEqual(self.exclude.read_bytes(), updated)
        result = subprocess.run(['git', '-C', str(self.repo), 'check-ignore',
                                 '.cogito/runs/run/event'], capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_status_and_report_do_not_install_defaults(self) -> None:
        result = self.invoke('init', '--no-stage-commits', '--run-id', 'DEV-read', '--kind', 'feature')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.exclude.write_bytes(b'# only user defaults\n')
        before = self.exclude.read_bytes()
        self.assertEqual(self.invoke('status', '--run-id', 'DEV-read').returncode, 0)
        self.invoke('report', '--run-id', 'DEV-read')
        self.assertEqual(self.exclude.read_bytes(), before)

    def test_linked_worktree_updates_shared_git_exclude(self) -> None:
        git(self.repo, 'commit', '--allow-empty', '-m', 'baseline')
        linked = self.repo / 'linked'
        git(self.repo, 'worktree', 'add', '-b', 'worker', str(linked))
        ensure_local_excludes(linked)
        self.assertIn(b'/.cogito/worktrees/', self.exclude.read_bytes())
        self.assertEqual(git(linked, 'check-ignore', '.cogito/worktrees/worker/file'),
                         '.cogito/worktrees/worker/file')

    def test_plain_directory_is_supported_but_broken_git_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ensure_local_excludes(root)
            self.assertFalse((root / '.git').exists())
            (root / '.git').write_text('gitdir: missing\n')
            with self.assertRaises(CogitoError):
                ensure_local_excludes(root)

    def test_symlink_exclude_is_rejected_without_touching_target(self) -> None:
        target = self.repo / 'user-settings'
        target.write_bytes(b'keep me')
        self.exclude.parent.mkdir(parents=True, exist_ok=True)
        self.exclude.unlink(missing_ok=True)
        self.exclude.symlink_to(target)
        with self.assertRaises(CogitoError):
            ensure_local_excludes(self.repo)
        self.assertEqual(target.read_bytes(), b'keep me')
