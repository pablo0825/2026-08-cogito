"""Security boundary tests for immutable Git object reads."""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import cogito_test_support
from cogito_common import CogitoError
from cogito_git_objects import HardenedObjectReader
from cogito_test_support import GitTestCase, git, init_repo


class HardenedObjectReaderTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name)
        init_repo(self.repo)
        (self.repo / "docs").mkdir()
        (self.repo / "docs/spec.md").write_text("spec\n", encoding="utf-8")
        (self.repo / "tool.sh").write_text("#!/bin/sh\n", encoding="utf-8")
        (self.repo / "tool.sh").chmod(0o755)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "initial")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        self.tree = git(self.repo, "rev-parse", "HEAD^{tree}")

    def test_reads_and_recomputes_commit_tree_and_blobs(self) -> None:
        reader = HardenedObjectReader(self.repo)
        self.assertEqual(reader.commit_tree(self.commit), self.tree)
        entries = reader.walk_tree(self.tree)
        self.assertEqual(
            [(item.path, item.mode, item.type) for item in entries],
            [(b"docs", "040000", "tree"), (b"docs/spec.md", "100644", "blob"),
             (b"tool.sh", "100755", "blob")],
        )
        entry, content = reader.blob_at(self.tree, "docs/spec.md")
        self.assertEqual(entry.mode, "100644")
        self.assertEqual(content, b"spec\n")

    def test_rejects_abbreviated_uppercase_missing_and_wrong_type_ids(self) -> None:
        reader = HardenedObjectReader(self.repo)
        for invalid in (self.commit[:12], self.commit.upper(), "z" * len(self.commit), None):
            with self.subTest(invalid=invalid), self.assertRaises(CogitoError):
                reader.read_object(invalid, "commit")
        with self.assertRaises(CogitoError):
            reader.read_object("f" * len(self.commit), "commit")
        with self.assertRaises(CogitoError):
            reader.read_object(self.commit, "tree")

    def test_ignores_ambient_git_authority_and_disables_mutating_features(self) -> None:
        seen: list[tuple[list[str], dict[str, str]]] = []
        original = subprocess.run

        def capture(argv, *args, **kwargs):
            seen.append((list(argv), dict(kwargs["env"])))
            return original(argv, *args, **kwargs)

        with mock.patch.dict(os.environ, {
                "GIT_OBJECT_DIRECTORY": "/untrusted", "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/bad",
                "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor",
                "GIT_CONFIG_VALUE_0": "evil"}, clear=False), mock.patch(
                    "cogito_git_objects.subprocess.run", side_effect=capture):
            reader = HardenedObjectReader(self.repo)
            reader.read_object(self.commit, "commit")
        self.assertTrue(seen)
        for argv, env in seen:
            self.assertNotIn("GIT_OBJECT_DIRECTORY", env)
            self.assertNotIn("GIT_ALTERNATE_OBJECT_DIRECTORIES", env)
            self.assertNotIn("GIT_CONFIG_COUNT", env)
            self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")
            self.assertEqual(env["GIT_NO_LAZY_FETCH"], "1")
            self.assertNotIn("checkout", argv)
            self.assertNotIn("fetch", argv)

    def test_rejects_alternates_replace_refs_and_partial_clone_configuration(self) -> None:
        git_dir = self.repo / ".git"
        alternates = git_dir / "objects/info/alternates"
        alternates.write_text("/tmp/objects\n", encoding="utf-8")
        with self.assertRaisesRegex(CogitoError, "alternates"):
            HardenedObjectReader(self.repo)
        alternates.unlink()

        replace = git_dir / "refs/replace" / self.commit
        replace.parent.mkdir(parents=True)
        replace.write_text(self.commit + "\n", encoding="ascii")
        with self.assertRaisesRegex(CogitoError, "replace"):
            HardenedObjectReader(self.repo)
        replace.unlink()

        git(self.repo, "config", "extensions.partialClone", "origin")
        with self.assertRaisesRegex(CogitoError, "partial-clone"):
            HardenedObjectReader(self.repo)

    def test_rejects_included_local_configuration(self) -> None:
        include = self.repo / "external.config"
        include.write_text("[remote \"origin\"]\n\tpromisor = true\n", encoding="utf-8")
        git(self.repo, "config", "include.path", str(include))
        with self.assertRaisesRegex(CogitoError, "includes"):
            HardenedObjectReader(self.repo)

    def test_size_limit_is_checked_before_object_body_is_requested(self) -> None:
        blob = git(self.repo, "rev-parse", "HEAD:docs/spec.md")
        reader = HardenedObjectReader(self.repo, max_blob_bytes=1)
        with mock.patch.object(reader, "_run", wraps=reader._run) as run:
            with self.assertRaisesRegex(CogitoError, "size limit"):
                reader.read_object(blob, "blob")
        self.assertEqual([call.args[1] for call in run.call_args_list], ["--batch-check"])

    def test_rejects_symlink_gitlink_and_case_collisions(self) -> None:
        blob = git(self.repo, "rev-parse", "HEAD:docs/spec.md")
        cases = (
            f"120000 blob {blob}\tlink\n",
            f"160000 commit {self.commit}\tsubmodule\n",
            f"100644 blob {blob}\tName\n100644 blob {blob}\tname\n",
        )
        for content in cases:
            with self.subTest(content=content):
                result = subprocess.run(["git", "mktree"], cwd=self.repo, input=content,
                                        text=True, capture_output=True, check=True)
                with self.assertRaises(CogitoError):
                    HardenedObjectReader(self.repo).walk_tree(result.stdout.strip())

    def test_reading_does_not_change_refs_index_or_worktree(self) -> None:
        before_refs = git(self.repo, "show-ref")
        before_index = (self.repo / ".git/index").read_bytes()
        before_status = git(self.repo, "status", "--porcelain=v1", "-uall")
        reader = HardenedObjectReader(self.repo)
        reader.walk_tree(reader.commit_tree(self.commit))
        self.assertEqual(git(self.repo, "show-ref"), before_refs)
        self.assertEqual((self.repo / ".git/index").read_bytes(), before_index)
        self.assertEqual(git(self.repo, "status", "--porcelain=v1", "-uall"), before_status)
