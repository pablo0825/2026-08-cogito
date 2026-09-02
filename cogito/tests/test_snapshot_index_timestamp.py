"""Temporary-index snapshots must retain Git's racy-clean content checks."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo
from cogito_evidence_binding import working_tree_content_tree


class SnapshotIndexTimestampTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        init_repo(self.repo)
        # Model a filesystem whose useful stat precision is whole seconds.
        # Ignoring ctime is a supported Git configuration, not a snapshot mock.
        git(self.repo, "config", "core.checkStat", "minimal")
        git(self.repo, "config", "core.trustctime", "false")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        (self.repo / "tracked.txt").write_bytes(b"before\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "baseline")

    def index_path(self, worktree: Path) -> Path:
        path = Path(git(worktree, "rev-parse", "--git-path", "index"))
        return path if path.is_absolute() else worktree / path

    def snapshot_preserving_index(self, worktree: Path) -> str:
        index = self.index_path(worktree)
        before_bytes = index.read_bytes()
        before_mtime = index.stat().st_mtime_ns
        tree = working_tree_content_tree(worktree)
        self.assertEqual(index.read_bytes(), before_bytes)
        self.assertEqual(index.stat().st_mtime_ns, before_mtime)
        return tree

    def assert_blob(self, worktree: Path, tree: str, relative: str) -> None:
        captured = subprocess.run(
            ["git", "-C", str(worktree), "show", f"{tree}:{relative}"],
            check=True, capture_output=True,
        ).stdout
        self.assertEqual(captured, (worktree / relative).read_bytes())

    def assert_racy_snapshot(self, worktree: Path) -> None:
        tracked = worktree / "tracked.txt"
        # Use a fixed past timestamp so a newly copied index is always newer,
        # without depending on process speed or sleeping across a clock tick.
        timestamp_ns = 1_700_000_000_000_000_000
        os.utime(tracked, ns=(timestamp_ns, timestamp_ns))
        git(worktree, "add", "tracked.txt")
        index = self.index_path(worktree)
        os.utime(index, ns=(timestamp_ns, timestamp_ns))
        indexed_mtime = tracked.stat().st_mtime_ns
        tracked.write_bytes(b"after\n\n")
        os.utime(tracked, ns=(timestamp_ns, timestamp_ns))
        self.assertEqual(tracked.stat().st_mtime_ns, indexed_mtime)
        self.assertEqual(tracked.stat().st_size, len(b"before\n"))
        self.assertEqual(index.stat().st_mtime_ns, tracked.stat().st_mtime_ns)

        tree = self.snapshot_preserving_index(worktree)
        self.assert_blob(worktree, tree, "tracked.txt")
        self.assertNotEqual(tree, git(worktree, "rev-parse", "HEAD^{tree}"))

    def test_equal_size_timestamp_collision_captures_current_working_content(self) -> None:
        self.assert_racy_snapshot(self.repo)

    def test_linked_worktree_timestamp_collision_preserves_its_own_index(self) -> None:
        linked = self.root / "linked"
        git(self.repo, "worktree", "add", "-qb", "codex/snapshot-worker", str(linked))
        main_index = self.index_path(self.repo)
        main_before = (main_index.read_bytes(), main_index.stat().st_mtime_ns)
        self.assert_racy_snapshot(linked)
        self.assertEqual((main_index.read_bytes(), main_index.stat().st_mtime_ns), main_before)

    def test_staged_and_forced_ignored_entries_keep_original_index_metadata(self) -> None:
        (self.repo / "tracked.txt").write_bytes(b"staged\n")
        (self.repo / "ignored.txt").write_bytes(b"explicitly staged ignored file\n")
        git(self.repo, "add", "tracked.txt")
        git(self.repo, "add", "--force", "ignored.txt")
        (self.repo / "tracked.txt").write_bytes(b"current unstaged working content\n")
        (self.repo / "untracked.txt").write_bytes(b"new working file\n")
        tree = self.snapshot_preserving_index(self.repo)
        for relative in ("tracked.txt", "ignored.txt", "untracked.txt"):
            with self.subTest(path=relative):
                self.assert_blob(self.repo, tree, relative)


if __name__ == "__main__":
    unittest.main()
