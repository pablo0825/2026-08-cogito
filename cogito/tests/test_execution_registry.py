"""Executor quiescence must be established rather than declared."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
import cogito_execution_registry as registry


class ExecutionRegistryTests(GitTestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = "DEV-registry"

    def child(self, *, separate=True):
        child = subprocess.Popen([sys.executable, "-c", "import time; print(\"ready\", flush=True); time.sleep(120)"], start_new_session=separate, stdout=subprocess.PIPE)
        self.assertEqual(child.stdout.readline(), b"ready\n")
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.wait(timeout=5)
            child.stdout.close()
        self.addCleanup(cleanup)
        return child

    def test_stop_marker_then_deadline_terminates_real_dedicated_process(self):
        child = self.child()
        with registry.managed_process(self.root, self.run, "worker", child.pid):
            pass
        self.assertFalse(registry.quiescent(self.root, self.run))
        status = registry.request_stop(self.root, self.run, now=100)
        self.assertEqual(status["stop_request"]["deadline"], 160)
        self.assertEqual(registry.terminate_overdue(self.root, self.run, now=159)["signaled"], [])
        self.assertIsNone(child.poll())
        self.assertEqual(registry.terminate_overdue(self.root, self.run, now=160)["signaled"], ["worker"])
        child.wait(timeout=5)
        self.assertTrue(registry.quiescent(self.root, self.run))

    def test_request_replay_cannot_extend_deadline_and_blocks_new_work(self):
        registry.request_stop(self.root, self.run, now=100)
        status = registry.request_stop(self.root, self.run, now=200)
        self.assertEqual(status["stop_request"]["deadline"], 160)
        with self.assertRaises(CogitoError):
            registry.register_external(self.root, self.run, "new", "agent-new")
        child = self.child()
        with self.assertRaises(CogitoError):
            registry.register_process(self.root, self.run, "new", child.pid)

    def test_pid_identity_mismatch_never_signals_or_claims_quiescent(self):
        child = self.child()
        entry = registry.register_process(self.root, self.run, "worker", child.pid)
        registry.request_stop(self.root, self.run, deadline_seconds=0, now=0)
        changed = {**entry["identity"], "started": "different-start"}
        with mock.patch.object(registry, "process_identity", return_value=changed), mock.patch.object(registry.os, "killpg") as kill:
            self.assertFalse(registry.quiescent(self.root, self.run))
            result = registry.terminate_overdue(self.root, self.run, now=1)
            self.assertEqual(result["unresolved"], ["worker"])
            kill.assert_not_called()

    def test_shared_group_is_never_signaled(self):
        child = self.child(separate=False)
        registry.register_process(self.root, self.run, "worker", child.pid)
        registry.request_stop(self.root, self.run, deadline_seconds=0, now=0)
        with mock.patch.object(registry.os, "killpg") as kill:
            self.assertEqual(registry.terminate_overdue(self.root, self.run, now=1)["unresolved"], ["worker"])
            kill.assert_not_called()
        self.assertIsNone(child.poll())

    def test_exited_leader_with_remaining_group_is_not_quiescent(self):
        child = self.child()
        registry.register_process(self.root, self.run, "worker", child.pid)
        child.kill()
        child.wait(timeout=5)
        with mock.patch.object(registry, "_group_alive", return_value=True):
            status = registry.snapshot(self.root, self.run)
            self.assertFalse(status["quiescent"])
            self.assertEqual(status["entries"]["worker"]["observation"], "descendants-running")

    def test_external_receipt_is_explicit_attestation_only(self):
        registry.register_external(self.root, self.run, "worker", "agent-123")
        self.assertFalse(registry.quiescent(self.root, self.run))
        with self.assertRaises(CogitoError):
            registry.record_external_receipt(self.root, self.run, "worker", "agent-123", {"stopped": True})
        receipt = {"provider": "host", "control_tool": "interrupt_agent", "event_id": "event-1", "handle": "agent-123", "status": "interrupted", "raw_response": {"handle": "agent-123", "status": "interrupted"}}
        registry.record_external_receipt(self.root, self.run, "worker", "agent-123", receipt)
        self.assertFalse(registry.quiescent(self.root, self.run))
        self.assertTrue(registry.quiescent(self.root, self.run, allow_external_receipts=True))
        invalid = {**receipt, "raw_response": {"handle": "other", "status": "interrupted"}}
        with self.assertRaises(CogitoError):
            registry.record_external_receipt(self.root, self.run, "worker", "agent-123", invalid)

    def test_malformed_registry_fails_closed(self):
        registry.request_stop(self.root, self.run, now=0)
        path = self.root / ".cogito/runs" / self.run / "execution-registry.json"
        for value in ([], {"schema_version": 1, "run_id": self.run, "entries": {"bad": {"kind": "process"}}}, {"schema_version": 1, "run_id": self.run, "entries": {}, "stop_request": {"requested_at": 2, "deadline": 1}}):
            path.write_text(json.dumps(value))
            with self.assertRaises(CogitoError):
                registry.quiescent(self.root, self.run)

    def test_inspection_failure_is_not_termination(self):
        child = self.child()
        registry.register_process(self.root, self.run, "worker", child.pid)
        with mock.patch.object(registry, "_ps", side_effect=CogitoError("unavailable")):
            with self.assertRaises(CogitoError):
                registry.quiescent(self.root, self.run)


if __name__ == "__main__":
    unittest.main()
