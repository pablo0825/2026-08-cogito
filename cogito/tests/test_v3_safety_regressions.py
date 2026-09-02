"""Negative and end-to-end safety contracts for the Cogito 3.0 runtime."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


COGITO = Path(__file__).resolve().parents[1]


def load(name: str):
    path = COGITO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def package(kind: str = "feature") -> dict:
    mini = kind in {"maintenance", "documentation"}
    value = {
        "schema_version": "3.0",
        "run_id": "DEV-safe-001",
        "kind": kind,
        "mini_package": mini,
        "delivery_branch": "main",
        "baseline_commit": "a" * 40,
        "shared_understanding": {"hash": "b" * 64},
        "slices": [],
        "execution_dag": {"tasks": [{"id": "T-1", "paths": ["src"]}], "edges": []},
        "checks": [{"id": "C-1", "argv": [sys.executable, "-c", "print('ok')"], "required": True}],
        "approved_paths": ["src/**", "tests/**"],
        "human_gate": {
            "predicates": [{"id": "public-api", "applicable": True}],
            "high_risk_hotspots": [],
        },
        "policy_snapshot": {"max_workers": 3, "fetch_allowed": False},
        "limits": {
            "transient_retries": 2,
            "verification_corrections": 3,
            "review_fix_cycles": 3,
            "format_repairs": 2,
        },
        "stop_conditions": ["contract-boundary-change"],
        "source_registry": [],
    }
    if mini:
        value["human_gate"]["predicates"] = []
        value["maintenance_guards"] = {
                key: True for key in (
                    "behavior_unchanged", "public_contract_unchanged",
                    "data_model_unchanged", "security_boundary_unchanged",
                    "slice_responsibility_unchanged", "deterministic_evidence",
                    "single_commit",
                )
        }
    else:
        value["boundary"] = {"decision": "single-slice", "evidence": ["bounded"]}
        value["execution_dag"]["tasks"][0]["slice_id"] = "FS-1"
        value["slices"] = [{
            "id": "FS-1", "type": kind, "spec": {"path": "docs/spec.md", "hash": "c" * 64},
            "plan": {"path": "docs/plan.md", "hash": "d" * 64},
            "worker": {"branch": "codex/fs-1", "worktree": ".cogito/worktrees/FS-1", "allowed_paths": ["src/**", "tests/**"]},
        }]
    return value


def git(repo: Path, *argv: str) -> str:
    return subprocess.run(["git", *argv], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


class GateSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load("cogito_runtime")

    def test_invalid_preflight_does_not_pollute_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore(directory, "DEV-safe-001")
            store.create("feature")
            before = store.events_path.read_bytes()
            with self.assertRaises(self.runtime.CogitoError):
                store.transition("package-approved", {"approved": True})
            self.assertEqual(store.events_path.read_bytes(), before)

    def test_package_cannot_loosen_project_check_output_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy_path = root / "docs" / "cogito" / "project-policy.json"
            policy_path.parent.mkdir(parents=True)
            project_policy = {
                "schema_version": "3.0",
                "max_check_output_bytes": 1024 * 1024,
            }
            policy_path.write_text(json.dumps(project_policy))
            value = package()
            value["policy_snapshot"].update({
                "hash": self.runtime.hash_json(project_policy),
                "max_check_output_bytes": 2 * 1024 * 1024,
            })
            store = self.runtime.RunStore.__new__(self.runtime.RunStore)
            store.root = root
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "output limit is looser"
            ):
                store._validate_policy(value)

    def test_blocked_run_cannot_resume_to_arbitrary_later_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore(directory, "DEV-safe-001")
            store.create("feature")
            store.transition("block", {"reason": "baseline drift"})
            with self.assertRaises(self.runtime.CogitoError):
                store.transition("resume", {"target": "finalizing", "validated": True})

    def test_generic_record_cannot_bypass_sensitive_gate_events(self) -> None:
        sensitive = ["package-approved", "start-gate-passed", "human-approved", "finalization-complete"]
        for event in sensitive:
            with self.subTest(event=event), tempfile.TemporaryDirectory() as directory:
                store = self.runtime.RunStore(directory, "DEV-safe-001")
                store.create("feature")
                before = store.events_path.read_bytes()
                with self.assertRaises(self.runtime.CogitoError):
                    store.record(event, {"approved": True, "final_commit": "f" * 40})
                self.assertEqual(store.events_path.read_bytes(), before)

    def test_generic_transition_cannot_bypass_review_fix_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore(Path(directory), "DEV-review-fix-001")
            store.create("feature")
            store.record("shared-understanding-ready", {"shared_understanding_hash": "a" * 64})
            store.record("shared-understanding-confirmed", {"confirmed": True})
            store.record("boundary-complete", {"decision": "single-slice", "evidence": ["bounded"]})
            with self.assertRaises(self.runtime.CogitoError):
                store.transition("review-fix-required", {"scope_within_contract": True})

    def test_feature_review_cannot_use_maintenance_exemption(self) -> None:
        store = self.runtime.RunStore.__new__(self.runtime.RunStore)
        store.approved_package = lambda: package()
        with self.assertRaises(self.runtime.CogitoError):
            store._validate_review({"approved": True, "review_exemption": True})

    def test_missing_evidence_fails_before_loading_ledger_or_git(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = self.runtime.RunStore.__new__(self.runtime.RunStore)
            store.run_dir = Path(directory)
            store.events_path = Path(directory) / "events.jsonl"
            store.load = lambda: self.fail("missing evidence must not load the ledger")
            store._git = lambda *_args: self.fail("missing evidence must not query Git")
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "required verification evidence is missing"
            ):
                store._validate_evidence(package(), [], require_current_head=True)

    def test_invalid_evidence_shape_fails_before_loading_ledger(self) -> None:
        validation = load("cogito_gate_validation")
        with self.assertRaisesRegex(
            self.runtime.CogitoError, "check evidence is missing fields"
        ):
            validation.validate_evidence(
                package(),
                [{"check_id": "C-1", "status": "banana"}],
                [],
                lambda: self.fail("invalid evidence must not load the ledger"),
                Path("/must-not-be-read"),
            )

    def test_legacy_evidence_without_executable_contract_fields_is_rejected(self) -> None:
        validation = load("cogito_gate_validation")
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            evidence_path = run_dir / "evidence" / "legacy.json"
            evidence_path.parent.mkdir()
            value = package()
            effective = self.runtime.materialize_contract(value, [])
            binding_body = {
                "head_tree": "a" * 40,
                "tracked_diff_sha256": "b" * 64,
                "untracked": [],
            }
            snapshot_hash = self.runtime.hash_json(binding_body)
            item = {
                "schema_version": "3.0",
                "run_id": value["run_id"],
                "check_id": "C-1",
                "passed": True,
                "check_hash": self.runtime.hash_json(value["checks"][0]),
                "effective_contract_hash": effective["effective_contract_hash"],
                "tree_hash": snapshot_hash,
                "worktree_binding": {**binding_body, "snapshot_hash": snapshot_hash},
                "evidence_path": str(evidence_path),
            }
            evidence_path.write_text(json.dumps(item))
            ledger = {
                "evidence": {
                    str(evidence_path.resolve()): {
                        "check_id": "C-1",
                        "evidence_hash": self.runtime.hash_json(item),
                        "event_sequence": 1,
                    }
                }
            }
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "check evidence is missing fields"
            ):
                validation.validate_evidence(
                    value, [item], [], lambda: ledger, run_dir
                )

    def test_gate_rejects_evidence_from_a_changed_worktree(self) -> None:
        validation = load("cogito_gate_validation")
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            evidence_path = run_dir / "evidence" / "changed.json"
            evidence_path.parent.mkdir()
            value = package()
            effective = self.runtime.materialize_contract(value, [])
            binding_body = {
                "head_commit": "a" * 40,
                "head_tree": "b" * 40,
                "tracked_diff_sha256": "c" * 64,
                "untracked": [],
            }
            post_hash = self.runtime.hash_json(binding_body)
            item = {
                "schema_version": "3.0",
                "run_id": value["run_id"],
                "check_id": "C-1",
                "status": "passed",
                "passed": True,
                "exit_code": 0,
                "timed_out": False,
                "check_hash": self.runtime.hash_json(value["checks"][0]),
                "effective_contract_hash": effective["effective_contract_hash"],
                "output_limit_exceeded": False,
                "termination_degraded": False,
                "output_limit_bytes": 10 * 1024 * 1024,
                "stdout_bytes": 0,
                "stderr_bytes": 0,
                "duration_seconds": 0.1,
                "started_at": "2026-09-02T00:00:00+00:00",
                "head_commit": "a" * 40,
                "tree_hash": post_hash,
                "worktree_snapshot_hash": post_hash,
                "pre_worktree_snapshot_hash": "d" * 64,
                "post_worktree_snapshot_hash": post_hash,
                "worktree_changed_during_check": True,
                "worktree_binding": {**binding_body, "snapshot_hash": post_hash},
                "argv": value["checks"][0]["argv"],
                "cwd": ".",
                "stdout": "",
                "stderr": "",
                "truncated": False,
                "evidence_path": str(evidence_path),
            }
            evidence_path.write_text(json.dumps(item))
            ledger = {
                "evidence": {
                    str(evidence_path.resolve()): {
                        "check_id": "C-1",
                        "evidence_hash": self.runtime.hash_json(item),
                        "event_sequence": 1,
                    }
                }
            }
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "passed check evidence contains"
            ):
                validation.validate_evidence(
                    value, [item], [], lambda: ledger, run_dir
                )

    def test_maintenance_review_exemption_advances_verified_tasks(self) -> None:
        store = self.runtime.RunStore.__new__(self.runtime.RunStore)
        store.approved_package = lambda: package("maintenance")
        store.load = lambda: {"tasks": {"T-1": {"status": "verified"}, "T-2": {"status": "integrated"}}}
        payload = {"review_exemption": True}
        store._validate_review(payload)
        self.assertEqual(payload["reviews"], ["T-1"])
        self.assertTrue(payload["approved"])
        self.assertFalse(payload["independent"])

    def test_feature_review_is_derived_from_recorded_result_identity(self) -> None:
        store = self.runtime.RunStore.__new__(self.runtime.RunStore)
        store.approved_package = lambda: package()
        store.load = lambda: {
            "tasks": {"T-1": {"id": "T-1", "slice_id": "FS-1", "status": "verified", "agent_id": "implementer-1"}},
            "agent_results": [{"task_id": "T-1", "role": "reviewer", "status": "complete", "agent_id": "reviewer-1", "reviewed_implementer": "implementer-1", "requested_transition": "review-approved"}],
        }
        payload: dict = {}
        store._validate_review(payload)
        self.assertTrue(payload["independent"])
        store.load = lambda: {
            "tasks": {"T-1": {"id": "T-1", "slice_id": "FS-1", "status": "verified", "agent_id": "implementer-1"}},
            "agent_results": [{"task_id": "T-1", "role": "reviewer", "status": "complete", "agent_id": "implementer-1", "reviewed_implementer": "implementer-1", "requested_transition": "review-approved"}],
        }
        with self.assertRaises(self.runtime.CogitoError):
            store._validate_review({})

    def test_frozen_human_predicate_cannot_be_disabled_by_event_payload(self) -> None:
        store = self.runtime.RunStore.__new__(self.runtime.RunStore)
        store.load = lambda: {"state": "post-integration-verification", "counters": {}}
        store.approved_package = lambda: package()
        store._validate_evidence = lambda _package, _evidence, **_kwargs: None
        store._git = lambda *_args: "a" * 40
        store.workflow = self.runtime.load_workflow()
        store._gate_authority = object()
        captured = {}
        store.record = lambda event, payload, action_id=None, _authority=None: captured.update(event=event, payload=payload) or captured
        store.decide_post_verification([{"evidence_path": "e.json"}], reviewer_escalation=False)
        self.assertEqual(captured["event"], "human-review-required")
        self.assertTrue(captured["payload"]["human_required"])

    def test_mini_package_has_no_slices_but_feature_requires_spec_and_plan(self) -> None:
        self.assertIsNone(self.runtime.validate_package(package("maintenance")))
        broken = package()
        del broken["slices"][0]["spec"]
        with self.assertRaises(self.runtime.CogitoError):
            self.runtime.validate_package(broken)

    def test_post_integration_correction_returns_directly_to_post_verification(self) -> None:
        workflow = self.runtime.load_workflow()
        correction = self.runtime.validate_transition(
            workflow, "post-integration-verification", "post-verification-correction-required",
            {"scope_within_contract": True}, {},
        )
        self.assertEqual(correction["to"], "post-integration-correction")
        completed = self.runtime.validate_transition(
            workflow, correction["to"], "post-integration-correction-complete",
            {"scope_within_contract": True}, {"verification_corrections": 1},
        )
        self.assertEqual(completed["to"], "post-integration-verification")

    def test_result_commit_is_not_self_referential(self) -> None:
        result = {
            "schema_version": "3.0", "run_id": "DEV-safe-001", "status": "accepted",
            "result_commit": "f" * 40, "finalization_commit": "f" * 40,
            "effective_contract_hash": "e" * 64, "checks": [], "amendments": [],
        }
        store = self.runtime.RunStore.__new__(self.runtime.RunStore)
        store.run_id = result["run_id"]
        store.workflow = self.runtime.load_workflow()
        store.load = lambda: {"state": "finalizing", "counters": {}}
        approved = package()
        store.approved_package = lambda: approved
        graph = {"active_run_id": None}
        store._git = lambda *args: json.dumps(result if args[0] == "show" and "results/" in args[1] else graph) if args[0] == "show" else ""
        with self.assertRaises(self.runtime.CogitoError):
            store.finalize("docs/cogito/results/DEV-safe-001.json", "docs/cogito/project-graph.json", "f" * 40)


class PackageApprovalAndRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = load("cogito_runtime")
        self.runner = load("cogito_runner")

    def _repo(self, root: Path) -> tuple[Path, str]:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "cogito@example.invalid")
        git(repo, "config", "user.name", "Cogito Test")
        (repo / "tracked.txt").write_text("base\n")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "base")
        return repo, git(repo, "rev-parse", "HEAD")

    def test_package_approval_copies_canonical_and_detects_later_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = package()
            store = self.runtime.RunStore(root, value["run_id"])
            store.create("feature")
            store.transition("shared-understanding-ready", {"shared_understanding_hash": value["shared_understanding"]["hash"]})
            store.transition("shared-understanding-confirmed", {"confirmed": True})
            store.transition("boundary-complete", value["boundary"])
            store.prepare_package(value)
            canonical = store.approve_package(value)
            expected = root / "docs" / "cogito" / "packages" / f"{value['run_id']}.json"
            self.assertEqual(root / canonical["package_path"], expected)
            self.assertTrue(expected.exists())
            expected.chmod(0o644)
            expected.write_text("{}")
            with self.assertRaises(self.runtime.CogitoError):
                store.load()

    def test_amendment_added_check_is_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self._repo(root)
            value = package()
            value["baseline_commit"] = commit
            amendment = {
                "id": "TA-1", "reason": "missing check",
                "added_checks": [{"id": "C-added", "argv": [sys.executable, "-c", "print('added')"], "required": True}],
            }
            evidence = self.runner.run_check(value, "C-added", repo, [amendment])
            self.assertEqual(evidence["status"], "passed")

    def test_runner_rejects_amendment_environment_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self._repo(root)
            marker = repo / "must-not-exist"
            value = package()
            value["baseline_commit"] = commit
            value["policy_snapshot"]["allowed_environment"] = ["PATH"]
            amendment = {
                "id": "TA-1", "reason": "requests an unapproved host secret",
                "added_checks": [{
                    "id": "C-added",
                    "argv": [sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).touch()"],
                    "env_allowlist": ["API_TOKEN"],
                }],
            }
            with self.assertRaisesRegex(
                self.runtime.CogitoError, "environment exceeds its frozen policy snapshot"
            ):
                self.runner.run_check(value, "C-added", repo, [amendment])
            self.assertFalse(marker.exists())

    def test_evidence_is_immutable_and_check_id_cannot_traverse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self._repo(root)
            value = package()
            value["baseline_commit"] = commit
            evidence_dir = root / "evidence"
            self.runner.write_evidence_once(evidence_dir, "C-1", self.runner.run_check(value, "C-1", repo))
            with self.assertRaises(self.runtime.CogitoError):
                self.runner.write_evidence_once(evidence_dir, "C-1", {"different": True})
            with self.assertRaises(self.runtime.CogitoError):
                self.runner.write_evidence_once(evidence_dir, "../escape", {"x": 1})

    def test_concurrent_evidence_publication_has_exactly_one_winner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self._repo(root)
            value = package()
            value["baseline_commit"] = commit
            base = self.runner.run_check(value, "C-1", repo)
            evidence_dir = root / "evidence"
            barrier = threading.Barrier(2)

            def publish(label: str):
                barrier.wait()
                candidate = dict(base, stdout=label, stdout_bytes=1)
                try:
                    path = self.runner.write_evidence_once(
                        evidence_dir, "C-race", candidate
                    )
                except self.runner.EvidenceAlreadyExists as exc:
                    return "collision", exc.path
                return "created", path

            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(publish, ("A", "B")))

            self.assertEqual([status for status, _ in results].count("created"), 1)
            self.assertEqual([status for status, _ in results].count("collision"), 1)
            paths = {path for _, path in results}
            self.assertEqual(paths, {evidence_dir.resolve() / "C-race.json"})
            published_path = next(iter(paths))
            recorded = json.loads(published_path.read_text())
            self.assertIn(recorded["stdout"], {"A", "B"})
            self.assertEqual(recorded["evidence_path"], str(published_path))
            self.assertEqual(list(evidence_dir.glob(".C-race.json.*")), [])

    def test_immutable_publication_fails_closed_without_hard_link_support(self) -> None:
        common = sys.modules["cogito_common"]
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "record.json"
            with mock.patch.object(common.os, "link", side_effect=OSError("unsupported")):
                with self.assertRaisesRegex(
                    self.runtime.CogitoError, "cannot publish immutable JSON record"
                ):
                    common.atomic_create_json(destination, {"complete": True})
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_concurrent_check_loser_reuses_the_winning_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            worktree, commit = self._repo(root)
            value = package()
            value["baseline_commit"] = commit
            winner = self.runner.run_check(value, "C-1", worktree)
            store = self.runtime.RunStore.__new__(self.runtime.RunStore)
            store.root = root
            store.run_dir = root / ".cogito" / "runs" / "DEV-race"
            store.events_path = store.run_dir / "events.jsonl"
            store._replay = lambda *_args: None
            store.approved_package = lambda: value
            store.load = lambda: {
                "state": "verifying",
                "tasks": {
                    "T-1": {"status": "complete", "worktree": str(worktree)}
                },
            }
            store.record = lambda _event, payload, *_args: payload

            def collide(target, record_id, _evidence):
                path = Path(target) / f"{record_id}.json"
                path.parent.mkdir(parents=True)
                recorded = dict(winner, evidence_path=str(path))
                path.write_text(json.dumps(recorded))
                raise self.runner.EvidenceAlreadyExists(path)

            with (
                mock.patch.object(self.runner, "run_check", return_value={"loser": True}),
                mock.patch.object(self.runner, "write_evidence_once", side_effect=collide),
            ):
                payload = store.run_controlled_check(
                    "C-1", worktree, "verify:T-1:C-1"
                )

            self.assertEqual(payload["check_id"], "C-1")
            self.assertEqual(payload["head_commit"], winner["head_commit"])
            self.assertEqual(
                payload["effective_contract_hash"], winner["effective_contract_hash"]
            )

    def test_snapshot_hash_includes_unstaged_worktree_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self._repo(root)
            value = package()
            value["baseline_commit"] = commit
            clean = self.runner.run_check(value, "C-1", repo)
            (repo / "tracked.txt").write_text("unstaged\n")
            dirty = self.runner.run_check(value, "C-1", repo)
            self.assertNotEqual(clean["worktree_snapshot_hash"], dirty["worktree_snapshot_hash"])


class MaintenanceEndToEndTests(unittest.TestCase):
    def test_single_commit_maintenance_auto_finalizes_and_reports(self) -> None:
        runtime = load("cogito_runtime")
        load("cogito_runner")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "cogito@example.invalid")
            git(repo, "config", "user.name", "Cogito Test")
            (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
            (repo / "note.txt").write_text("before\n")
            git(repo, "add", ".gitignore", "note.txt")
            git(repo, "commit", "-qm", "baseline")
            baseline = git(repo, "rev-parse", "HEAD")
            run_id = "MNT-e2e-001"
            draft = package("maintenance")
            draft.update({
                "run_id": run_id, "baseline_commit": baseline, "delivery_branch": "main",
                "approved_paths": ["note.txt"],
                "execution_dag": {"tasks": [{"id": "T-1", "paths": ["note.txt"]}], "edges": []},
            })
            store = runtime.RunStore(repo, run_id)
            store.create("maintenance")
            store.prepare_package(draft, "prepare")
            store.approve_package(draft, "approve")
            store.start_gate("start")
            (repo / "note.txt").write_text("after\n")
            store.update_task("T-1", "leased", "worker-1", "lease")
            store.update_task("T-1", "running", "worker-1", "running")
            store.submit_agent_result({
                "schema_version": "3.0", "run_id": run_id, "task_id": "T-1", "agent_id": "worker-1",
                "role": "implementer", "status": "complete", "base_commit": baseline, "head_commit": baseline,
                "changed_paths": ["note.txt"], "evidence": [], "risks": [], "requested_transition": "verifying",
            }, "result")
            store.update_task("T-1", "complete", "worker-1", "complete")
            store.transition("implementation-complete", {}, "implemented")
            store.run_controlled_check("C-1", repo, "check-pre")
            evidence_files = list((store.run_dir / "evidence").glob("C-1-*.json"))
            pre = json.loads(evidence_files[0].read_text())
            store.complete_verification([pre], "verified")
            store.transition("review-approved", {"review_exemption": True}, "reviewed")
            store.complete_integration(baseline, None, "integrated")
            store.run_controlled_check("C-1", repo, "check-post")
            post_path = next(path for path in (store.run_dir / "evidence").glob("C-1-*.json") if path not in evidence_files)
            post = json.loads(post_path.read_text())
            store.decide_post_verification([post], False, "post-verified")
            canonical = store.approved_package()
            graph_path = repo / "docs/cogito/project-graph.json"
            graph = json.loads(graph_path.read_text())
            graph["active_run_id"] = None
            graph_path.write_text(json.dumps(graph))
            result_path = repo / "docs/cogito/results" / f"{run_id}.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps({
                "schema_version": "3.0", "run_id": run_id, "status": "accepted",
                "package_hash": runtime.package_hash(canonical), "effective_contract_hash": store.load()["effective_contract_hash"],
                "integration_commits": [baseline], "slice_dispositions": {},
                "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
                "reviews": [], "amendments": [], "human_gate": {"required": False, "outcome": "not-required"}, "remaining_risks": [],
            }))
            git(repo, "add", "note.txt", "docs/cogito/project-graph.json", f"docs/cogito/results/{run_id}.json")
            git(repo, "commit", "-qm", "maintenance result")
            final_commit = git(repo, "rev-parse", "HEAD")
            store.finalize(f"docs/cogito/results/{run_id}.json", "docs/cogito/project-graph.json", final_commit, "finalize")
            self.assertEqual(store.completion_report()["final_commit"], final_commit)


if __name__ == "__main__":
    unittest.main()
