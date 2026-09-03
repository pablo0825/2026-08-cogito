"""Termination fallback contracts without signalling or launching real processes."""

from __future__ import annotations

import itertools
import signal
import subprocess
import unittest
from unittest import mock

from cogito_test_support import SCRIPTS  # Adds the scripts directory to sys.path.
import cogito_process_capture as capture


class ProcessTerminationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process = mock.Mock(spec=["pid", "poll", "kill", "wait"])
        self.process.pid = 123456
        self.process.poll.return_value = None
        self.process.kill.side_effect = self.mark_exited
        self.process.wait.return_value = -9
        # Patch every OS operation even in tests for the other platform: no test
        # can accidentally send a signal, run taskkill, or sleep in real time.
        self.killpg = self.patch("os.killpg", create=True)
        self.patch("signal.SIGKILL", new=getattr(signal, "SIGKILL", 9), create=True)
        self.run = self.patch("subprocess.run")
        self.run.return_value = subprocess.CompletedProcess([], 0)
        self.patch("time.monotonic", side_effect=itertools.count(0, 2))
        self.patch("time.sleep")

    def patch(self, target: str, **kwargs):
        patcher = mock.patch(f"cogito_process_capture.{target}", **kwargs)
        value = patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def mark_exited(self) -> None:
        self.process.poll.return_value = -9

    def stop(self, platform: str) -> tuple[bool, str | None]:
        # Limit the platform override to the function under test so pathlib and
        # the test runner keep their real host platform outside this call.
        with mock.patch.object(capture.os, "name", platform):
            return capture._stop_process_group(self.process)

    def test_posix_missing_group_is_already_terminated_without_degradation(self) -> None:
        self.killpg.side_effect = ProcessLookupError("group has exited")
        self.assertEqual(self.stop("posix"), (False, None))
        self.process.kill.assert_not_called()

    def test_posix_denied_group_signal_with_exited_child_still_marks_degradation(self) -> None:
        self.killpg.side_effect = PermissionError("group signal denied")
        self.process.poll.return_value = 0
        self.assertEqual(self.stop("posix"), (True, None))
        self.process.kill.assert_not_called()

    def test_posix_denied_group_signal_falls_back_to_direct_child(self) -> None:
        self.killpg.side_effect = PermissionError("group signal denied")
        self.assertEqual(self.stop("posix"), (True, None))
        self.assertIsNotNone(self.process.poll())

    def test_posix_group_and_direct_termination_failure_preserves_both_reasons(self) -> None:
        self.killpg.side_effect = PermissionError("group signal denied")
        self.process.kill.side_effect = OSError("direct kill denied")
        degraded, reason = self.stop("posix")
        self.assertTrue(degraded)
        self.assertEqual(reason, (
            "cannot terminate controlled check process: "
            "group error=group signal denied; direct error=direct kill denied"
        ))
        self.assertIsNone(self.process.poll())

    def test_posix_exited_child_still_requires_descendant_group_cleanup(self) -> None:
        self.process.poll.return_value = 0
        self.assertEqual(self.stop("posix"), (False, None))
        self.killpg.assert_has_calls([
            mock.call(self.process.pid, signal.SIGTERM),
            mock.call(self.process.pid, signal.SIGKILL),
        ])
        self.process.kill.assert_not_called()

    def test_posix_group_disappearing_after_term_is_successful_cleanup(self) -> None:
        self.killpg.side_effect = [None, ProcessLookupError("group exited after TERM")]
        self.assertEqual(self.stop("posix"), (False, None))
        self.process.kill.assert_not_called()

    def test_posix_failed_kill_after_term_uses_degraded_direct_cleanup(self) -> None:
        self.killpg.side_effect = [None, PermissionError("group KILL denied")]
        self.assertEqual(self.stop("posix"), (True, None))
        self.assertIsNotNone(self.process.poll())

    def test_posix_failed_group_kill_with_exited_child_remains_degraded(self) -> None:
        self.process.poll.return_value = 0
        self.killpg.side_effect = [None, PermissionError("group KILL denied")]
        self.assertEqual(self.stop("posix"), (True, None))
        self.process.kill.assert_not_called()

    def test_posix_failed_group_kill_and_direct_kill_preserve_escalation_reason(self) -> None:
        self.killpg.side_effect = [None, PermissionError("group KILL denied")]
        self.process.kill.side_effect = OSError("direct kill denied")
        degraded, reason = self.stop("posix")
        self.assertTrue(degraded)
        self.assertEqual(reason, (
            "cannot kill controlled check process: "
            "group error=group KILL denied; direct error=direct kill denied"
        ))
        self.assertIsNone(self.process.poll())

    def test_windows_successful_taskkill_preserves_tree_termination_guarantee(self) -> None:
        self.assertEqual(self.stop("nt"), (False, None))
        self.assertEqual(self.run.call_args.args[0], [
            "taskkill", "/PID", str(self.process.pid), "/T", "/F",
        ])
        self.assertFalse(self.run.call_args.kwargs["shell"])
        self.process.kill.assert_not_called()

    def test_windows_taskkill_timeout_can_recover_with_degraded_direct_kill(self) -> None:
        self.run.side_effect = subprocess.TimeoutExpired("taskkill", 2)
        self.assertEqual(self.stop("nt"), (True, None))
        self.assertIsNotNone(self.process.poll())

    def test_windows_missing_taskkill_can_recover_with_degraded_direct_kill(self) -> None:
        self.run.side_effect = FileNotFoundError("taskkill not installed")
        self.assertEqual(self.stop("nt"), (True, None))
        self.assertIsNotNone(self.process.poll())

    def test_windows_nonzero_taskkill_for_exited_child_remains_degraded(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 128)
        self.process.poll.return_value = 0
        self.assertEqual(self.stop("nt"), (True, None))
        self.process.kill.assert_not_called()

    def test_windows_taskkill_and_direct_kill_failures_preserve_both_reasons(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 5)
        self.process.kill.side_effect = PermissionError("direct kill denied")
        degraded, reason = self.stop("nt")
        self.assertTrue(degraded)
        self.assertEqual(reason, (
            "cannot terminate controlled check process tree: "
            "taskkill exited with status 5; direct process kill failed: direct kill denied"
        ))
        self.assertIsNone(self.process.poll())

    def test_windows_taskkill_timeout_and_unresponsive_child_are_unrecoverable(self) -> None:
        taskkill_timeout = subprocess.TimeoutExpired("taskkill", 2)
        child_timeout = subprocess.TimeoutExpired("controlled check", 1)
        self.run.side_effect = taskkill_timeout
        self.process.kill.side_effect = None  # The child remains alive after kill.
        self.process.wait.side_effect = child_timeout
        degraded, reason = self.stop("nt")
        self.assertTrue(degraded)
        self.assertEqual(reason, (
            "cannot terminate controlled check process tree: "
            f"{taskkill_timeout}; direct process kill failed: {child_timeout}"
        ))
        self.assertIsNone(self.process.poll())

    def test_windows_child_exiting_during_failed_direct_kill_is_degraded_recovery(self) -> None:
        self.run.return_value = subprocess.CompletedProcess([], 5)

        def exited_during_kill() -> None:
            self.mark_exited()
            raise ProcessLookupError("child already exited")

        self.process.kill.side_effect = exited_during_kill
        self.assertEqual(self.stop("nt"), (True, None))
        self.assertIsNotNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()
