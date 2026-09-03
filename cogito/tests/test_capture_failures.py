"""Capture propagates termination failures without launching real processes."""

import io
import subprocess
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cogito_process_capture as capture
from cogito_common import CogitoError


class ProcessDouble:
    pid = 123456789  # Never passed to the real OS: capture.os is replaced below.

    def __init__(self, output=b"", *, kill_error=None):
        self.stdout = io.BytesIO(output)
        self.stderr = io.BytesIO()
        self.returncode = None
        self.kill_error = kill_error

    def poll(self):
        return self.returncode

    def kill(self):
        if self.kill_error:
            raise self.kill_error
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("simulated process", timeout)
        return self.returncode


class CaptureFailureTests(unittest.TestCase):
    def run_capture(self, process, *, timeout=0, stop=None):
        # Real reader threads consume only BytesIO. The entire OS adapter is
        # replaced, so no branch can accidentally signal a real process.
        fake_os = SimpleNamespace(name="posix", killpg=mock.Mock(side_effect=PermissionError("group denied")))
        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(capture, "os", fake_os))
            stack.enter_context(mock.patch.object(capture.subprocess, "Popen", return_value=process))
            stack.enter_context(mock.patch.object(capture, "TERMINATION_DRAIN_SECONDS", 0))
            if stop is not None:
                stack.enter_context(mock.patch.object(capture, "_stop_process_group", side_effect=stop))
            return capture.run_bounded_process(
                ["never-executed"], cwd=Path("."), env={}, timeout_seconds=timeout,
                evidence_cap=128, output_limit=1024,
            )

    def test_timeout_records_degraded_group_termination(self):
        result = self.run_capture(ProcessDouble())
        self.assertTrue(result.timed_out)
        self.assertTrue(result.termination_degraded)
        self.assertFalse(result.output_limit_exceeded)
        self.assertIsNone(result.exit_code)

    def test_output_limit_records_degraded_group_termination(self):
        result = self.run_capture(ProcessDouble(b"x" * 2048), timeout=60)
        self.assertTrue(result.output_limit_exceeded)
        self.assertTrue(result.termination_degraded)
        self.assertFalse(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertEqual(result.stdout_bytes, 2048)
        self.assertLessEqual(len(result.stdout), 128)

    def test_first_stop_error_survives_a_later_successful_stop(self):
        process = ProcessDouble()
        outcomes = iter(((True, "first termination failed"), (False, None)))

        def stop(_process):
            outcome = next(outcomes)
            if outcome[1] is None:
                process.kill()
            return outcome

        with self.assertRaisesRegex(CogitoError, "first termination failed"):
            self.run_capture(process, stop=stop)
        self.assertEqual(process.returncode, -9)

    def test_degraded_flag_survives_a_later_successful_stop(self):
        process = ProcessDouble()
        first = True

        def stop(_process):
            nonlocal first
            if first:
                first = False
                return True, None
            process.kill()
            return False, None

        result = self.run_capture(process, stop=stop)
        self.assertTrue(result.termination_degraded)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)

    def test_an_unterminated_process_raises_instead_of_returning_capture(self):
        process = ProcessDouble(kill_error=PermissionError("direct kill denied"))
        with self.assertRaisesRegex(CogitoError, "process did not terminate"):
            self.run_capture(process)
        self.assertIsNone(process.returncode)
        self.assertTrue(process.stdout.closed)
        self.assertTrue(process.stderr.closed)


if __name__ == "__main__":
    unittest.main()
