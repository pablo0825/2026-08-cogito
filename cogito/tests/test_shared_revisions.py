"""Shared Understanding revisions stay bound to the latest human confirmation."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase, git, init_repo, package


GATE = COGITO / "scripts/cogito_gate.py"
HASH_A = "a" * 64
HASH_B = "b" * 64


class SharedRevisionTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="cogito-shared-revision-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / "repo"
        self.repo.mkdir()
        init_repo(self.repo)
        (self.repo / ".gitignore").write_text(".cogito/\n")
        (self.repo / "docs").mkdir()
        for name in ("spec", "plan"):
            (self.repo / "docs" / f"{name}.md").write_text(f"{name}\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "baseline")
        self.draft = package("feature")
        self.draft["baseline_commit"] = git(self.repo, "rev-parse", "HEAD")
        for item in self.draft["slices"]:
            for name in ("spec", "plan"):
                item[name]["hash"] = hashlib.sha256((self.repo / item[name]["path"]).read_bytes()).hexdigest()
        self.run_id = self.draft["run_id"]
        self.events_path = self.repo / ".cogito/runs" / self.run_id / "events.jsonl"
        self.invoke("init", "--run-id", self.run_id, "--kind", "feature")

    def invoke(self, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, str(GATE), "--repo", str(self.repo), *args],
            text=True, capture_output=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def transition(self, event: str, payload: dict, action_id: str, *, ok: bool = True) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            "transition", "--run-id", self.run_id, "--event", event,
            "--payload-json", json.dumps(payload), "--action-id", action_id, ok=ok,
        )

    def ready(self, digest: str, action_id: str, *, ok: bool = True) -> subprocess.CompletedProcess[str]:
        return self.transition("shared-understanding-ready", {"shared_understanding_hash": digest}, action_id, ok=ok)

    def status(self) -> dict:
        return json.loads(self.invoke("status", "--run-id", self.run_id).stdout)["data"]

    def test_latest_revision_is_visible_and_binds_package_preparation(self) -> None:
        self.ready(HASH_A, "ready-a")
        revised = json.loads(self.ready(HASH_B, "ready-b").stdout)["data"]
        self.assertEqual(revised["state"], "awaiting-shared-confirmation")
        self.assertEqual(revised["shared_understanding_hash"], HASH_B)
        guidance = json.loads(self.invoke("next", "--run-id", self.run_id).stdout)["data"]
        self.assertEqual(guidance["next_action"], "request-shared-confirmation")
        self.assertEqual(guidance["shared_understanding_hash"], HASH_B)
        self.transition("shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": HASH_B}, "confirm-b")
        self.transition("boundary-complete", self.draft["boundary"], "boundary")
        events_before = self.events_path.read_bytes()
        old = copy.deepcopy(self.draft)
        old["shared_understanding"]["hash"] = HASH_A
        old_path = self.root / "package-a.json"
        old_path.write_text(json.dumps(old))
        rejected = self.invoke("prepare-package", "--run-id", self.run_id, "--package", str(old_path), "--action-id", "prepare-a", ok=False)
        self.assertIn("confirmed Shared Understanding", rejected.stderr)
        self.assertEqual(self.events_path.read_bytes(), events_before)
        latest_path = self.root / "package-b.json"
        self.draft["shared_understanding"]["hash"] = HASH_B
        latest_path.write_text(json.dumps(self.draft))
        prepared = json.loads(self.invoke("prepare-package", "--run-id", self.run_id, "--package", str(latest_path), "--action-id", "prepare-b").stdout)["data"]
        self.assertEqual(prepared["state"], "awaiting-package-approval")

    def test_replaying_old_revision_cannot_restore_hash_or_append_events(self) -> None:
        self.ready(HASH_A, "ready-a")
        revised = json.loads(self.ready(HASH_B, "ready-b").stdout)["data"]
        events_before = self.events_path.read_bytes()
        replayed = json.loads(self.ready(HASH_B, "ready-b").stdout)["data"]
        self.assertEqual(replayed, revised)
        self.ready(HASH_A, "ready-a")
        self.assertEqual(self.status()["shared_understanding_hash"], HASH_B)
        self.assertEqual(self.events_path.read_bytes(), events_before)
        self.ready(HASH_B, "ready-a", ok=False)
        self.ready(HASH_A, "ready-b", ok=False)
        self.assertEqual(self.status()["shared_understanding_hash"], HASH_B)
        self.assertEqual(self.events_path.read_bytes(), events_before)

    def test_revision_requires_explicit_confirmation_of_latest_hash(self) -> None:
        self.ready(HASH_A, "ready-a")
        self.ready(HASH_B, "ready-b")
        events_before = self.events_path.read_bytes()
        for suffix, payload in (
            ("missing", {"confirmed": True}),
            ("stale", {"confirmed": True, "shared_understanding_hash": HASH_A}),
        ):
            with self.subTest(confirmation=suffix):
                self.transition("shared-understanding-confirmed", payload, f"confirm-{suffix}", ok=False)
                self.assertEqual(self.events_path.read_bytes(), events_before)
                self.assertEqual(self.status()["state"], "awaiting-shared-confirmation")
        confirmed = json.loads(self.transition("shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": HASH_B}, "confirm-b").stdout)["data"]
        self.assertEqual(confirmed["state"], "boundary-analysis")
        self.assertEqual(confirmed["shared_understanding_hash"], HASH_B)

    def test_block_and_resume_preserve_ability_to_revise(self) -> None:
        self.ready(HASH_A, "ready-a")
        self.transition("block", {"reason": "clarify Shared Understanding"}, "block")
        resumed = json.loads(self.invoke("resume", "--run-id", self.run_id, "--action-id", "resume").stdout)["data"]
        self.assertEqual(resumed["state"], "awaiting-shared-confirmation")
        self.assertEqual(resumed["shared_understanding_hash"], HASH_A)
        self.ready(HASH_B, "ready-b")
        self.transition("shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": HASH_B}, "confirm-b")
        self.assertEqual(self.status()["state"], "boundary-analysis")

    def test_unrevised_legacy_confirmation_is_compatible_and_freezes_hash(self) -> None:
        self.ready(HASH_A, "ready-a")
        self.transition("shared-understanding-confirmed", {"confirmed": True}, "confirm-legacy")
        events_before = self.events_path.read_bytes()
        self.ready(HASH_B, "ready-after-confirmation", ok=False)
        self.assertEqual(self.events_path.read_bytes(), events_before)
        self.assertEqual(self.status()["shared_understanding_hash"], HASH_A)
        self.assertEqual(self.status()["state"], "boundary-analysis")
