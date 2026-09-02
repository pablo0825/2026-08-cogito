"""Process lifetime and output lifetime are independent capture contracts."""

from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cogito_process_capture import ProcessCapture, run_bounded_process


class ProcessCaptureLifetimeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def capture(self, source: str, *, timeout: int = 5) -> ProcessCapture:
        return run_bounded_process(
            [sys.executable, "-c", textwrap.dedent(source)],
            cwd=self.root,
            env=os.environ,
            timeout_seconds=timeout,
            evidence_cap=1024,
            output_limit=1024 * 1024,
        )

    def test_closed_output_does_not_interrupt_remaining_work(self) -> None:
        result = self.capture("""
            import os, pathlib, time
            os.close(1)
            os.close(2)
            time.sleep(0.2)
            pathlib.Path('completed').write_text('finished after EOF')
        """)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.output_limit_exceeded)
        self.assertEqual((self.root / "completed").read_text(), "finished after EOF")
        self.assertEqual((result.stdout, result.stderr), (b"", b""))

    def test_closed_output_preserves_the_eventual_failure_exit_code(self) -> None:
        result = self.capture("""
            import os, time
            os.close(1)
            os.close(2)
            time.sleep(0.2)
            raise SystemExit(7)
        """)
        self.assertEqual(result.exit_code, 7)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.output_limit_exceeded)

    def test_closed_output_does_not_disable_the_process_timeout(self) -> None:
        # A finite sleep also bounds the child lifetime if timeout handling fails.
        result = self.capture("""
            import os, pathlib, time
            os.close(1)
            os.close(2)
            time.sleep(3)
            pathlib.Path('completed').write_text('timeout was missed')
        """, timeout=1)
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.exit_code)
        self.assertFalse(result.output_limit_exceeded)
        self.assertFalse((self.root / "completed").exists())

    def test_closing_one_stream_preserves_output_from_the_other(self) -> None:
        for closed_fd, open_fd in ((1, 2), (2, 1)):
            with self.subTest(closed_fd=closed_fd):
                result = self.capture(f"""
                    import os, time
                    os.close({closed_fd})
                    time.sleep(0.1)
                    os.write({open_fd}, b'output after the other stream closed')
                """)
                self.assertEqual(result.exit_code, 0)
                self.assertFalse(result.timed_out)
                remaining = result.stdout if open_fd == 1 else result.stderr
                closed = result.stdout if closed_fd == 1 else result.stderr
                self.assertEqual(remaining, b"output after the other stream closed")
                self.assertEqual(closed, b"")

    def test_parent_exit_still_drains_output_inherited_by_a_child(self) -> None:
        result = self.capture("""
            import os, subprocess, sys
            subprocess.Popen([
                sys.executable, '-c',
                "import os,time; time.sleep(0.2); os.write(1, b'child stdout'); os.write(2, b'child stderr')",
            ])
            os._exit(0)
        """)
        self.assertEqual(result.exit_code, 0)
        self.assertFalse(result.timed_out)
        self.assertEqual(result.stdout, b"child stdout")
        self.assertEqual(result.stderr, b"child stderr")


if __name__ == "__main__":
    unittest.main()
