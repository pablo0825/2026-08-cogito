"""The runner must publish degraded termination as failed evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_process_capture import ProcessCapture
from cogito_runner import run_check, write_evidence_once


class RunnerTerminationTests(GitTestCase):
    def test_zero_exit_with_degraded_termination_publishes_failed_evidence(self):
        # A defensive contract test: even an otherwise successful capture must
        # fail when it cannot guarantee termination of the whole process tree.
        result = ProcessCapture(
            exit_code=0, timed_out=False, output_limit_exceeded=False,
            termination_degraded=True, stdout=b"", stderr=b"",
            stdout_bytes=0, stderr_bytes=0,
            stdout_truncated=False, stderr_truncated=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            init_repo(repo)
            (repo / "tracked.txt").write_text("baseline\n", encoding="utf-8")
            git(repo, "add", "tracked.txt")
            git(repo, "commit", "-qm", "baseline")
            contract = package("maintenance")
            contract["baseline_commit"] = git(repo, "rev-parse", "HEAD")
            with mock.patch("cogito_runner.run_bounded_process", return_value=result):
                evidence = run_check(contract, "C-1", repo)
            self.assertFalse(evidence["passed"])
            self.assertEqual(evidence["status"], "failed")
            self.assertTrue(evidence["termination_degraded"])
            path = write_evidence_once(root / "evidence", "degraded", evidence)
            self.assertEqual(json.loads(path.read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main()
