"""Package candidates can be revised until approval freezes their contract."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cogito_test_support import COGITO, GitTestCase, git, init_repo, package
from cogito_common import CogitoError, atomic_write_json
from cogito_contracts import package_hash
from cogito_run_store import RunStore


GATE = COGITO / "scripts/cogito_gate.py"


class PackageRevisionTests(GitTestCase):
    def fixture(self, kind: str) -> tuple[Path, dict, Path]:
        temporary = tempfile.TemporaryDirectory(prefix="cogito-package-revision-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        repo = root / "repo"
        repo.mkdir()
        init_repo(repo)
        (repo / ".gitignore").write_text(".cogito/\n")
        (repo / "docs").mkdir()
        for name in ("spec", "plan"):
            (repo / "docs" / f"{name}.md").write_text(f"{name}\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        value = package(kind)
        value["baseline_commit"] = git(repo, "rev-parse", "HEAD")
        for item in value["slices"]:
            for name in ("spec", "plan"):
                item[name]["hash"] = hashlib.sha256((repo / item[name]["path"]).read_bytes()).hexdigest()
        draft = root / "package-v1.json"
        draft.write_text(json.dumps(value))
        self.invoke(repo, "init", "--no-stage-commits", "--run-id", value["run_id"], "--kind", kind)
        if kind == "feature":
            for event, payload in (
                ("shared-understanding-ready", {"shared_understanding_hash": value["shared_understanding"]["hash"]}),
                ("shared-understanding-confirmed", {"confirmed": True}),
                ("boundary-complete", value["boundary"]),
            ):
                self.invoke(repo, "transition", "--run-id", value["run_id"], "--event", event,
                            "--payload-json", json.dumps(payload), "--action-id", event)
        return repo, value, draft

    def invoke(self, repo: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(GATE), "--repo", str(repo), *args],
                                text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def begin_revision(self, store: RunStore, first: dict) -> None:
        store.planning_begin({
            "round": 1, "candidate_hash": package_hash(first), "author_id": "planner",
            "reason": "Record a newly identified stop condition without changing approved scope.",
            "level": "plan",
            "impact": {key: {"disposition": "reuse", "reason": "This contract component is unchanged."}
                       for key in ("requirements", "boundary", "spec", "plan", "dag", "acceptance")},
        }, "begin-revision")

    def review_revision(self, store: RunStore) -> None:
        store.planning_review({
            "round": 2, "proposal_hash": store.load()["planning"]["proposal_hash"],
            "reviewer_id": "independent-reviewer", "findings": [],
            "assessment": {key: "Compared original and revised inputs; only the stop condition changed."
                           for key in ("consistency", "impact", "reuse")},
        }, "review-revision")

    def test_candidate_revisions_require_latest_approval_and_freeze_after_approval(self) -> None:
        for kind in ("feature", "maintenance", "documentation"):
            with self.subTest(kind=kind):
                repo, first, first_path = self.fixture(kind)
                run_id = first["run_id"]
                revised = copy.deepcopy(first)
                revised["stop_conditions"].append("newly identified contract risk")
                revised["planning_round"] = 2
                revised_path = first_path.with_name("package-v2.json")
                revised_path.write_text(json.dumps(revised))
                prepare = ("prepare-package", "--run-id", run_id, "--package")
                initial = json.loads(self.invoke(repo, *prepare, str(first_path), "--action-id", "candidate-v1").stdout)["data"]
                self.assertEqual(initial["candidate_package_hash"], package_hash(first))
                store = RunStore(repo, run_id)
                self.begin_revision(store, first)
                revision_args = (*prepare, str(revised_path), "--action-id", "candidate-v2")
                updated = json.loads(self.invoke(repo, *revision_args).stdout)["data"]
                self.assertEqual(updated["state"], "awaiting-package-approval")
                self.assertEqual(updated["candidate_package_hash"], package_hash(revised))
                self.review_revision(store)
                updated = store.load()
                events_path = repo / ".cogito/runs" / run_id / "events.jsonl"
                events_before = events_path.read_bytes()
                self.assertEqual(json.loads(self.invoke(repo, *revision_args).stdout)["data"], updated)
                self.assertEqual(events_path.read_bytes(), events_before)
                # An action id must remain bound to the original request, even
                # when its event type and legal workflow state are unchanged.
                self.invoke(repo, *prepare, str(first_path), "--action-id", "candidate-v2", ok=False)
                self.assertEqual(events_path.read_bytes(), events_before)
                # Replaying an older successful prepare cannot restore its hash.
                self.invoke(repo, *prepare, str(first_path), "--action-id", "candidate-v1")
                self.assertEqual(events_path.read_bytes(), events_before)
                status = json.loads(self.invoke(repo, "status", "--run-id", run_id).stdout)["data"]
                self.assertEqual(status["candidate_package_hash"], package_hash(revised))
                approval = ("approve", "--run-id", run_id, "--package")
                rejected = self.invoke(repo, *approval, str(first_path), "--action-id", "approve-old", ok=False)
                self.assertIn("candidate", rejected.stderr)
                self.assertEqual(events_path.read_bytes(), events_before)
                canonical = repo / "docs/cogito/packages" / f"{run_id}.json"
                self.assertFalse(canonical.exists())
                approved = json.loads(self.invoke(repo, *approval, str(revised_path), "--action-id", "approve-new").stdout)["data"]
                self.assertEqual(approved["state"], "start-gate")
                self.assertEqual(approved["package_hash"], package_hash(revised))
                self.assertEqual(json.loads(canonical.read_text())["stop_conditions"], revised["stop_conditions"])
                approved_events = events_path.read_bytes()
                approved_bytes = canonical.read_bytes()
                self.invoke(repo, *prepare, str(first_path), "--action-id", "candidate-v3", ok=False)
                self.assertEqual(events_path.read_bytes(), approved_events)
                self.assertEqual(canonical.read_bytes(), approved_bytes)

    def test_revision_cannot_change_run_kind(self) -> None:
        for original_kind, replacement_kind in (("feature", "maintenance"), ("maintenance", "documentation")):
            with self.subTest(original_kind=original_kind, replacement_kind=replacement_kind):
                repo, first, first_path = self.fixture(original_kind)
                run_id = first["run_id"]
                self.invoke(repo, "prepare-package", "--run-id", run_id, "--package", str(first_path),
                            "--action-id", "candidate-v1")
                replacement = package(replacement_kind)
                replacement["baseline_commit"] = first["baseline_commit"]
                replacement_path = first_path.with_name("wrong-kind.json")
                replacement_path.write_text(json.dumps(replacement))
                events_path = repo / ".cogito/runs" / run_id / "events.jsonl"
                events_before = events_path.read_bytes()
                for command in ("prepare-package", "approve"):
                    rejected = self.invoke(repo, command, "--run-id", run_id, "--package", str(replacement_path),
                                           "--action-id", f"wrong-kind-{command}", ok=False)
                    self.assertIn("kind must match", rejected.stderr)
                    self.assertEqual(events_path.read_bytes(), events_before)

    def test_revision_during_approval_rolls_back_stale_publication(self) -> None:
        repo, first, _ = self.fixture("feature")
        store = RunStore(repo, first["run_id"])
        store.prepare_package(first, "candidate-v1")
        revised = copy.deepcopy(first)
        revised["stop_conditions"].append("newly identified contract risk")
        revised["planning_round"] = 2
        graph_path = repo / "docs/cogito/project-graph.json"
        canonical = repo / "docs/cogito/packages" / f"{first['run_id']}.json"
        old_graph = {"schema_version": "3.0", "active_run_id": None, "slices": {}, "dependencies": []}
        atomic_write_json(graph_path, old_graph)
        graph_before = graph_path.read_bytes()

        def publish_then_revise(path, value):
            atomic_write_json(path, value)
            if path == graph_path:
                revision_store = RunStore(repo, first["run_id"])
                self.begin_revision(revision_store, first)
                revision_store.prepare_package(revised, "candidate-v2")
                self.review_revision(revision_store)

        with mock.patch("cogito_approval.atomic_write_json", side_effect=publish_then_revise):
            with self.assertRaisesRegex(CogitoError, "history changed"):
                store.approve_package(first, "approve-old")
        self.assertFalse(canonical.exists())
        self.assertEqual(graph_path.read_bytes(), graph_before)
        current = store.load()
        self.assertEqual(current["state"], "awaiting-package-approval")
        self.assertEqual(current["candidate_package_hash"], package_hash(revised))
        events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
        self.assertFalse(any(event["type"] == "package-approved" for event in events))
        self.assertEqual(store.approve_package(revised, "approve-new")["state"], "start-gate")


if __name__ == "__main__":
    unittest.main()
