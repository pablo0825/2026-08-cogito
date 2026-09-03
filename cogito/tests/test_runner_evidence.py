"""Runner evidence can be derived from captured data without Git or processes."""

import copy
import sys
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import hash_json
from cogito_process_capture import ProcessCapture
from cogito_runner_evidence import build_evidence


class RunnerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.check = {"id": "C-1", "argv": ["python3", "-V"], "required": True}
        self.binding = {
            "head_commit": "a" * 40,
            "snapshot_hash": "b" * 64,
            "untracked": [{"path": "notes.txt", "sha256": "c" * 64}],
        }
        self.capture = ProcessCapture(
            exit_code=0, timed_out=False, output_limit_exceeded=False,
            termination_degraded=False, stdout=b"ok\n", stderr=b"",
            stdout_bytes=3, stderr_bytes=0,
            stdout_truncated=False, stderr_truncated=False,
        )
        self.inputs = {
            "run_id": "DEV-evidence", "check_id": "C-1", "check": self.check,
            "effective_contract_hash": "d" * 64, "capture": self.capture,
            "pre_binding": copy.deepcopy(self.binding),
            "post_binding": copy.deepcopy(self.binding),
            "started_at": "2026-09-02T14:00:00+00:00",
            "duration_seconds": 1.23456789, "cwd": "tests",
            "output_limit_bytes": 1024,
        }

    def build(self, **overrides):
        inputs = {**self.inputs, **overrides}
        before = copy.deepcopy(inputs)
        try:
            return build_evidence(**inputs)
        finally:
            self.assertEqual(inputs, before, "evidence construction must not mutate inputs")

    def test_successful_capture_preserves_identity_binding_and_execution_metadata(self):
        evidence = self.build()
        self.assertEqual(evidence, {
            "schema_version": "3.0", "run_id": "DEV-evidence", "check_id": "C-1",
            "status": "passed", "passed": True, "exit_code": 0,
            "timed_out": False, "output_limit_exceeded": False,
            "termination_degraded": False, "output_limit_bytes": 1024,
            "stdout_bytes": 3, "stderr_bytes": 0,
            "duration_seconds": 1.234568,
            "started_at": "2026-09-02T14:00:00+00:00",
            "head_commit": "a" * 40, "tree_hash": "b" * 64,
            "worktree_snapshot_hash": "b" * 64,
            "pre_worktree_snapshot_hash": "b" * 64,
            "post_worktree_snapshot_hash": "b" * 64,
            "worktree_changed_during_check": False,
            "worktree_binding": self.binding,
            "check_hash": hash_json(self.check), "effective_contract_hash": "d" * 64,
            "argv": ["python3", "-V"], "cwd": "tests",
            "stdout": "ok\n", "stderr": "", "truncated": False,
        })

    def test_every_capture_failure_prevents_a_pass_even_when_other_fields_are_successful(self):
        for changes in (
            {"exit_code": 7},
            {"exit_code": None},
            {"timed_out": True},
            {"output_limit_exceeded": True},
            {"termination_degraded": True},
        ):
            with self.subTest(changes=changes):
                evidence = self.build(capture=replace(self.capture, **changes))
                self.assertFalse(evidence["passed"])
                self.assertEqual(evidence["status"], "failed")
                for field, value in changes.items():
                    self.assertEqual(evidence[field], value)

    def test_worktree_change_fails_and_evidence_uses_the_post_check_binding(self):
        post = {**copy.deepcopy(self.binding), "head_commit": "e" * 40, "snapshot_hash": "f" * 64}
        evidence = self.build(post_binding=post)
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["status"], "failed")
        self.assertTrue(evidence["worktree_changed_during_check"])
        self.assertEqual(evidence["pre_worktree_snapshot_hash"], "b" * 64)
        for field in ("tree_hash", "worktree_snapshot_hash", "post_worktree_snapshot_hash"):
            self.assertEqual(evidence[field], "f" * 64)
        self.assertEqual(evidence["head_commit"], "e" * 40)
        self.assertEqual(evidence["worktree_binding"], post)

    def test_invalid_utf8_is_replaced_and_both_streams_are_redacted_without_recounting_bytes(self):
        check = {**self.check, "redact_patterns": [r"token=\w+", r"password=\w+"]}
        stdout = b"\xff token=secret\n"
        stderr = b"password=private \xfe"
        capture = replace(
            self.capture, stdout=stdout, stderr=stderr,
            stdout_bytes=len(stdout), stderr_bytes=len(stderr),
        )
        evidence = self.build(check=check, capture=capture)
        self.assertEqual(evidence["stdout"], "\ufffd [REDACTED]\n")
        self.assertEqual(evidence["stderr"], "[REDACTED] \ufffd")
        self.assertEqual(evidence["stdout_bytes"], len(stdout))
        self.assertEqual(evidence["stderr_bytes"], len(stderr))
        self.assertEqual(evidence["check_hash"], hash_json(check))
        self.assertFalse(evidence["truncated"])

    def test_either_capture_cap_or_the_hard_limit_marks_evidence_truncated(self):
        for flag in ("stdout_truncated", "stderr_truncated", "output_limit_exceeded"):
            with self.subTest(flag=flag):
                evidence = self.build(capture=replace(self.capture, **{flag: True}))
                self.assertTrue(evidence["truncated"])
                self.assertEqual(evidence["passed"], flag != "output_limit_exceeded")

    def test_raw_byte_counts_are_preserved_when_diagnostic_output_is_capped(self):
        capture = replace(self.capture, stdout=b"headtail", stdout_bytes=9000, stdout_truncated=True)
        evidence = self.build(capture=capture)
        self.assertEqual(evidence["stdout"], "headtail")
        self.assertEqual(evidence["stdout_bytes"], 9000)
        self.assertTrue(evidence["truncated"])

    def test_returned_nested_data_can_change_without_mutating_the_check_or_binding(self):
        before = copy.deepcopy(self.inputs)
        evidence = self.build()
        evidence["argv"].append("--changed")
        evidence["worktree_binding"]["untracked"][0]["path"] = "changed.txt"
        self.assertEqual(self.inputs, before)
        self.assertEqual(self.build()["argv"], ["python3", "-V"])

    def test_evidence_building_needs_no_files_processes_or_clock(self):
        with ExitStack() as stack:
            for target in (
                "builtins.open", "pathlib.Path.open", "pathlib.Path.resolve",
                "subprocess.run", "subprocess.Popen", "time.monotonic", "time.time",
            ):
                stack.enter_context(mock.patch(target, side_effect=AssertionError("unexpected IO or clock read")))
            evidence = self.build()
        self.assertEqual(evidence["duration_seconds"], 1.234568)
        self.assertTrue(evidence["passed"])


if __name__ == "__main__":
    unittest.main()
