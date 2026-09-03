"""Git fixtures are independent of the developer's configuration and checkout."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, SCRIPTS, init_repo
from cogito_git import GitRepository


class GitTestSupportTests(unittest.TestCase):
    def run_fixture(self, root: Path, hostile: dict[str, str]) -> None:
        repo = root / "repo"
        repo.mkdir()

        class Fixture(GitTestCase):
            def runTest(self) -> None:
                init_repo(repo)
                product_git = GitRepository(repo)
                (repo / "tracked.txt").write_text("baseline\n")
                product_git.run("add", "tracked.txt")
                product_git.run("commit", "-qm", "baseline")
                self.assertEqual(product_git.run("rev-parse", "--show-toplevel"), str(repo.resolve()))
                self.assertEqual(product_git.run("config", "user.name"), "Cogito Test")
                self.assertEqual(product_git.run("log", "-1", "--format=%an"), "Cogito Test")
                self.assertEqual(product_git.run("config", "commit.gpgsign"), "false")
                self.assertEqual(product_git.run("config", "tag.gpgsign"), "false")
                self.assertEqual(product_git.run("config", "core.hooksPath"), os.devnull)
                self.assertNotIn("contamination", product_git.run("config", "--list"))
                # A new Python process must inherit the isolation too, as the
                # runner CLI does. Exercise the real product Git adapter there.
                child = subprocess.run(
                    [sys.executable, "-c",
                     "import sys; sys.path.insert(0, sys.argv[1]); "
                     "from cogito_git import GitRepository; "
                     "GitRepository(sys.argv[2]).run('commit', '--allow-empty', '-qm', 'child')",
                     str(SCRIPTS), str(repo)],
                    check=False, text=True, capture_output=True, timeout=15,
                )
                self.assertEqual(child.returncode, 0, child.stderr)

        with mock.patch.dict(os.environ, hostile):
            before = dict(os.environ)
            result = unittest.TestResult()
            Fixture().run(result)
            self.assertEqual(os.environ, before, "fixture must restore the caller's environment")
            self.assertTrue(result.wasSuccessful(), str(result.errors + result.failures))

    def test_global_and_system_configuration_do_not_reach_product_processes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = root / "hooks"
            hooks.mkdir()
            hook = hooks / "pre-commit"
            hook.write_text("#!/bin/sh\nexit 41\n")
            hook.chmod(0o755)
            config = (
                "[commit]\n\tgpgsign = true\n"
                "[gpg]\n\tprogram = /nonexistent-cogito-test-signer\n"
                f"[core]\n\thooksPath = {hooks}\n"
                "[cogito]\n\tcontamination = present\n"
            )
            global_config = root / "global.gitconfig"
            system_config = root / "system.gitconfig"
            global_config.write_text(config)
            system_config.write_text(config)
            self.run_fixture(root, {
                "GIT_CONFIG_GLOBAL": str(global_config),
                "GIT_CONFIG_SYSTEM": str(system_config),
                "GIT_CONFIG_NOSYSTEM": "0",
            })
            self.assertEqual(global_config.read_text(), config)
            self.assertEqual(system_config.read_text(), config)

    def test_repository_and_command_config_environment_do_not_escape_into_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            index = root / "outside-index"
            self.run_fixture(root, {
                "GIT_DIR": str(root / "outside.git"),
                "GIT_COMMON_DIR": str(root / "outside-common"),
                "GIT_WORK_TREE": str(root / "outside-worktree"),
                "GIT_INDEX_FILE": str(index),
                "GIT_OBJECT_DIRECTORY": str(root / "outside-objects"),
                "GIT_AUTHOR_NAME": "Inherited Author",
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "commit.gpgsign",
                "GIT_CONFIG_VALUE_0": "true",
                "GIT_CONFIG_KEY_1": "cogito.contamination",
                "GIT_CONFIG_VALUE_1": "present",
                "GIT_CONFIG_PARAMETERS": "'commit.gpgsign'='true'",
            })
            self.assertFalse(index.exists())
            self.assertFalse((root / "outside.git").exists())

    def test_environment_is_restored_even_when_setup_fails(self) -> None:
        class FailingFixture(GitTestCase):
            def setUp(self) -> None:
                super().setUp()
                raise RuntimeError("fixture setup failed")

            def runTest(self) -> None:
                self.fail("setup must fail first")

        with mock.patch.dict(os.environ, {"GIT_DIR": "/inherited/checkout"}):
            before = dict(os.environ)
            result = unittest.TestResult()
            FailingFixture().run(result)
            self.assertEqual(len(result.errors), 1)
            self.assertEqual(os.environ, before)


if __name__ == "__main__":
    unittest.main()
