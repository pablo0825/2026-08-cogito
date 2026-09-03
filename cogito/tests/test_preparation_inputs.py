"""Reject malformed preparation facts before they freeze an unusable Package."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_events import append_event
from cogito_run_store import RunStore


GATE = COGITO / "scripts/cogito_gate.py"
INVALID_HASHES = (123, True, [], {}, None, "", " ", "a" * 63, "g" * 64, "a" * 63 + "\x00")
INVALID_EVIDENCE = ("not-an-array", 123, True, {}, None, [], [""], [123], [True], [[]], [{}], ["bad\x00value"])
INVALID_DECISIONS = ([], {}, 123, True, None, "", "unknown", "single-slice\x00")


class PreparationInputTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="cogito-preparation-inputs-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        init_repo(self.repo)
        (self.repo / ".gitignore").write_text(".cogito/\n", encoding="utf-8")
        (self.repo / "docs").mkdir()
        for name in ("spec", "plan"):
            (self.repo / "docs" / f"{name}.md").write_text(f"{name}\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "baseline")
        self.draft = package("feature")
        self.draft["baseline_commit"] = git(self.repo, "rev-parse", "HEAD")
        for item in self.draft["slices"]:
            for name in ("spec", "plan"):
                item[name]["hash"] = hashlib.sha256((self.repo / item[name]["path"]).read_bytes()).hexdigest()
        self.run_id = self.draft["run_id"]
        self.store = RunStore(self.repo, self.run_id)
        self.invoke("init", "--no-stage-commits", "--run-id", self.run_id, "--kind", "feature")
        self.files = (self.store.events_path, self.store.state_path, self.repo / ".git/index")

    def invoke(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, "-B", str(GATE), "--repo", str(self.repo), *args],
            text=True, capture_output=True, timeout=20,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def transition(self, event: str, payload: dict, action_id: str, *, ok: bool = True) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            "transition", "--run-id", self.run_id, "--event", event,
            "--payload-json", json.dumps(payload, ensure_ascii=False), "--action-id", action_id, ok=ok,
        )

    def snapshot(self) -> tuple[bytes, ...]:
        return tuple(path.read_bytes() for path in self.files)

    def reject(self, event: str, payload: dict, action_id: str) -> None:
        before = self.snapshot()
        result = self.transition(event, payload, action_id, ok=False)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertNotIn("Traceback", result.stderr)
        error = json.loads(result.stderr)
        self.assertIs(error["ok"], False)
        self.assertTrue(error["error"])
        self.assertEqual(self.snapshot(), before)

    def ready_and_confirm(self, *, action_id: str = "ready") -> None:
        self.transition("shared-understanding-ready", {
            "shared_understanding_hash": self.draft["shared_understanding"]["hash"],
            "extension": {"說明": "保留合法中文資料"},
        }, action_id)
        self.transition("shared-understanding-confirmed", {"confirmed": True}, "confirm")

    def finish_preparation(self) -> None:
        path = self.root / "package.json"
        path.write_text(json.dumps(self.draft, ensure_ascii=False), encoding="utf-8")
        prepared = self.invoke("prepare-package", "--run-id", self.run_id, "--package", str(path), "--action-id", "prepare")
        self.assertEqual(json.loads(prepared.stdout)["data"]["state"], "awaiting-package-approval")
        # Approval is simulated only inside this disposable test repository.
        approved = self.invoke("approve", "--run-id", self.run_id, "--package", str(path), "--action-id", "approve")
        self.assertEqual(json.loads(approved.stdout)["data"]["state"], "start-gate")
        started = self.invoke("start", "--run-id", self.run_id, "--action-id", "start")
        self.assertEqual(json.loads(started.stdout)["data"]["state"], "executing")

    def test_invalid_hashes_leave_no_write_and_action_id_can_be_corrected(self) -> None:
        for value in INVALID_HASHES:
            with self.subTest(value=value):
                self.reject("shared-understanding-ready", {"shared_understanding_hash": value}, "ready")
        self.reject("shared-understanding-ready", {}, "ready")
        self.ready_and_confirm()
        self.transition("boundary-complete", self.draft["boundary"], "boundary")
        self.finish_preparation()

    def test_invalid_boundary_evidence_leaves_no_write_and_action_id_can_be_corrected(self) -> None:
        self.ready_and_confirm()
        for value in INVALID_EVIDENCE:
            with self.subTest(value=value):
                self.reject("boundary-complete", {"decision": "single-slice", "evidence": value}, "boundary")
        self.reject("boundary-complete", {"decision": "single-slice"}, "boundary")
        self.transition("boundary-complete", self.draft["boundary"], "boundary")
        self.finish_preparation()

    def test_invalid_boundary_decisions_return_structured_errors(self) -> None:
        self.ready_and_confirm()
        for value in INVALID_DECISIONS:
            with self.subTest(value=value):
                self.reject("boundary-complete", {"decision": value, "evidence": ["bounded"]}, "boundary")
        self.reject("boundary-complete", {"evidence": ["bounded"]}, "boundary")
        self.transition("boundary-complete", self.draft["boundary"], "boundary")
        self.finish_preparation()

    def test_direct_record_cannot_bypass_hash_validation(self) -> None:
        before = self.snapshot()
        for value in INVALID_HASHES:
            with self.subTest(value=value):
                with self.assertRaises(CogitoError):
                    self.store.record("shared-understanding-ready", {"shared_understanding_hash": value}, "direct-ready")
                self.assertEqual(self.snapshot(), before)
        self.store.record("shared-understanding-ready", {"shared_understanding_hash": self.draft["shared_understanding"]["hash"]}, "direct-ready")
        self.assertEqual(self.store.load()["state"], "awaiting-shared-confirmation")

    def test_direct_record_cannot_bypass_boundary_validation(self) -> None:
        self.ready_and_confirm()
        before = self.snapshot()
        for field, values in (("evidence", INVALID_EVIDENCE), ("decision", INVALID_DECISIONS)):
            for value in values:
                with self.subTest(field=field, value=value):
                    payload = {**self.draft["boundary"], field: value}
                    with self.assertRaises(CogitoError):
                        self.store.record("boundary-complete", payload, "direct-boundary")
                    self.assertEqual(self.snapshot(), before)
        self.store.record("boundary-complete", self.draft["boundary"], "direct-boundary")
        self.finish_preparation()

    def test_valid_unicode_and_extensions_survive_preparation_and_approval(self) -> None:
        self.ready_and_confirm()
        boundary = {
            "decision": "single-slice", "evidence": ["只調整既有功能，範圍明確"],
            "extension": {"備註": ["中文證據", {"完成": True}]},
        }
        self.draft["boundary"] = copy.deepcopy(boundary)
        self.transition("boundary-complete", boundary, "boundary")
        recorded = [json.loads(line) for line in self.store.events_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(recorded[-1]["payload"], boundary)
        ready = next(event for event in recorded if event["type"] == "shared-understanding-ready")
        self.assertEqual(ready["payload"]["extension"], {"說明": "保留合法中文資料"})
        self.finish_preparation()
        self.assertEqual(self.store.approved_package()["boundary"], boundary)

    def test_legacy_invalid_hash_replays_but_must_be_revised_before_confirmation(self) -> None:
        # Bypass the new-input API only to reconstruct a legacy hash-valid log.
        append_event(self.store.events_path, {
            "type": "shared-understanding-ready",
            "payload": {"shared_understanding_hash": 123}, "action_id": "legacy-ready",
        })
        restored = json.loads(self.invoke("status", "--run-id", self.run_id).stdout)["data"]
        self.assertEqual(restored["state"], "awaiting-shared-confirmation")
        self.assertEqual(restored["shared_understanding_hash"], 123)
        self.reject("shared-understanding-confirmed", {"confirmed": True}, "confirm")
        before = self.snapshot()
        with self.assertRaises(CogitoError):
            self.store.record("shared-understanding-confirmed", {"confirmed": True}, "direct-confirm")
        self.assertEqual(self.snapshot(), before)
        digest = self.draft["shared_understanding"]["hash"]
        self.transition("shared-understanding-ready", {"shared_understanding_hash": digest}, "revised-ready")
        self.transition("shared-understanding-confirmed", {
            "confirmed": True, "shared_understanding_hash": digest,
        }, "confirm")
        self.transition("boundary-complete", self.draft["boundary"], "boundary")
        self.finish_preparation()


if __name__ == "__main__":
    unittest.main()
