"""Black-box contract for canonical approval and guarded resume CLI operations."""

from __future__ import annotations

import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cogito_test_support import GitTestCase, COGITO, git, init_repo, minimal_package, atomic_package
from cogito_common import hash_json
from cogito_contracts import package_hash


GATE = COGITO / "scripts" / "cogito_gate.py"


class GateCliContractTests(GitTestCase):
    def test_amendment_validation_returns_hash_only_for_a_valid_history(self) -> None:
        package = minimal_package()
        prior = {"id": "TA-1", "reason": "add check", "added_checks": [{"id": "C-2", "argv": ["python3", "-V"]}]}
        amendment = {"id": "TA-2", "reason": "repair path", "path_fixes": ["src"]}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("package", package), ("prior", prior), ("amendment", amendment)):
                (root / f"{name}.json").write_text(json.dumps(value))
            args = ("validate", "--type", "amendment", "--package", str(root / "package.json"),
                    "--prior", str(root / "prior.json"), "--input", str(root / "amendment.json"))
            result = self.invoke(root, *args)
            self.assertEqual(json.loads(result.stdout)["data"], {
                "valid": True, "effective_contract_hash": hash_json({
                    "base_package_hash": package_hash(package), "amendments": [prior, amendment],
                }),
            })
            prior["added_checks"][0]["id"] = "C-1"
            (root / "prior.json").write_text(json.dumps(prior))
            result = self.invoke(root, *args, ok=False)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stderr)["ok"])
            self.assertEqual(result.stdout, "")

    def invoke(self, repo: Path, *args: str, ok: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run([sys.executable, str(GATE), "--repo", str(repo), *args], text=True, capture_output=True)
        if ok and result.returncode != 0:
            self.fail(result.stderr)
        return result

    def test_canonical_approval_start_and_resume_cannot_skip_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            init_repo(repo)
            (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
            git(repo, "add", ".gitignore")
            git(repo, "commit", "-qm", "baseline")
            baseline = git(repo, "rev-parse", "HEAD")
            run_id = "DEV-cli-001"
            (repo / "docs").mkdir()
            (repo / "docs/spec.md").write_text("spec\n")
            (repo / "docs/plan.md").write_text("plan\n")
            spec_hash = hashlib.sha256((repo / "docs/spec.md").read_bytes()).hexdigest()
            plan_hash = hashlib.sha256((repo / "docs/plan.md").read_bytes()).hexdigest()
            package = {
                "schema_version": "3.0", "run_id": run_id, "kind": "feature", "mini_package": False,
                "delivery_branch": git(repo, "branch", "--show-current"), "baseline_commit": baseline,
                "shared_understanding": {"hash": "a" * 64},
                "boundary": {"decision": "single-slice", "evidence": ["bounded"]},
                "slices": [
                    {"id": f"FS-00{index}", "type": "feature", "spec": {"path": "docs/spec.md", "hash": spec_hash}, "plan": {"path": "docs/plan.md", "hash": plan_hash}, "worker": {"branch": f"codex/fs-00{index}", "worktree": f".cogito/worktrees/FS-00{index}", "allowed_paths": ["src/**"]}}
                    for index in range(1, 5)
                ],
                "execution_dag": {"tasks": [{"id": f"T-00{index}", "slice_id": f"FS-00{index}", "paths": ["src/**"]} for index in range(1, 5)], "edges": []},
                "checks": [{"id": "V-001", "argv": [sys.executable, "-c", "print('ok')"], "required": True}],
                "approved_paths": ["src/**"], "human_gate": {"predicates": [], "high_risk_hotspots": []},
                "policy_snapshot": {"max_workers": 3, "fetch_allowed": False},
                "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
                "stop_conditions": ["contract-drift"], "source_registry": [],
            }
            atomic_package(package)
            draft = root / "package.json"
            draft.write_text(json.dumps(package))
            self.invoke(repo, "init", "--no-stage-commits", "--run-id", run_id, "--kind", "feature")
            self.invoke(repo, "transition", "--run-id", run_id, "--event", "shared-understanding-ready", "--payload-json", json.dumps({"shared_understanding_hash": "a" * 64}), "--action-id", "shared-ready-1")
            self.invoke(repo, "transition", "--run-id", run_id, "--event", "shared-understanding-confirmed", "--payload-json", '{"confirmed":true}', "--action-id", "shared-confirm-1")
            self.invoke(repo, "transition", "--run-id", run_id, "--event", "boundary-complete", "--payload-json", json.dumps(package["boundary"]), "--action-id", "boundary-1")
            mismatched = dict(package)
            mismatched["shared_understanding"] = {"hash": "b" * 64}
            mismatch_draft = root / "mismatched-package.json"
            mismatch_draft.write_text(json.dumps(mismatched))
            rejected = self.invoke(repo, "prepare-package", "--run-id", run_id, "--package", str(mismatch_draft), "--action-id", "mismatch-1", ok=False)
            self.assertIn("confirmed Shared Understanding", rejected.stderr)
            self.invoke(repo, "prepare-package", "--run-id", run_id, "--package", str(draft), "--action-id", "prepare-1")
            approved = self.invoke(repo, "approve", "--run-id", run_id, "--package", str(draft), "--action-id", "approve-1")
            self.assertIn('"state": "start-gate"', approved.stdout)
            self.assertTrue((repo / "docs/cogito/packages" / f"{run_id}.json").exists())
            graph = json.loads((repo / "docs/cogito/project-graph.json").read_text())
            self.assertEqual(graph["active_run_id"], run_id)
            self.assertEqual(graph["slices"]["FS-001"]["disposition"], "active")
            replayed = self.invoke(repo, "approve", "--run-id", run_id, "--package", str(draft), "--action-id", "approve-1")
            self.assertIn('"state": "start-gate"', replayed.stdout)
            started = self.invoke(repo, "start", "--run-id", run_id, "--action-id", "start-1")
            self.assertIn('"state": "executing"', started.stdout)
            for index in range(1, 5):
                git(
                    repo,
                    "worktree",
                    "add",
                    "-b",
                    f"codex/fs-00{index}",
                    str(repo / ".cogito/worktrees" / f"FS-00{index}"),
                    baseline,
                )
            for index in range(1, 4):
                next_action = json.loads(self.invoke(repo, "next", "--run-id", run_id).stdout)["data"]
                self.assertEqual(next_action["worker_capacity"], 4 - index)
                self.assertEqual(next_action["ready_tasks"], [f"T-00{task}" for task in range(index, 4)])
                self.invoke(repo, "task", "--run-id", run_id, "--task-id", f"T-00{index}", "--status", "leased", "--agent-id", f"worker-{index}", "--action-id", f"lease-{index}")
            full = json.loads(self.invoke(repo, "next", "--run-id", run_id).stdout)["data"]
            self.assertEqual(full["worker_capacity"], 0)
            self.assertEqual(full["ready_tasks"], [])
            overflow = self.invoke(repo, "task", "--run-id", run_id, "--task-id", "T-004", "--status", "leased", "--agent-id", "worker-4", "--action-id", "lease-4", ok=False)
            self.assertIn("worker lease limit exceeded", overflow.stderr)
            self.invoke(repo, "task", "--run-id", run_id, "--task-id", "T-001", "--status", "blocked", "--agent-id", "worker-1", "--action-id", "release-1")
            available = json.loads(self.invoke(repo, "next", "--run-id", run_id).stdout)["data"]
            self.assertEqual(available["worker_capacity"], 1)
            self.assertEqual(available["ready_tasks"], ["T-004"])
            self.invoke(repo, "task", "--run-id", run_id, "--task-id", "T-004", "--status", "leased", "--agent-id", "worker-4", "--action-id", "lease-4")
            self.invoke(repo, "transition", "--run-id", run_id, "--event", "block", "--payload-json", '{"reason":"transient"}', "--action-id", "block-1")
            additional_block = ("transition", "--run-id", run_id, "--event", "block",
                                "--payload-json", '{"reason":"another finding"}', "--action-id", "block-2")
            blocked = json.loads(self.invoke(repo, *additional_block).stdout)["data"]
            self.assertEqual(blocked["blocked_from"], "executing")
            events_path = repo / ".cogito/runs" / run_id / "events.jsonl"
            events_before = events_path.read_bytes()
            self.assertEqual(json.loads(self.invoke(repo, *additional_block).stdout)["data"], blocked)
            self.assertEqual(events_path.read_bytes(), events_before)
            # Older versions cached the second block as the origin. Only repair
            # this disposable cache; both historical reasons must stay intact.
            state_path = events_path.with_name("state.json")
            state_path.write_text(json.dumps({**blocked, "blocked_from": "blocked"}))
            restored = json.loads(self.invoke(repo, "status", "--run-id", run_id).stdout)["data"]
            self.assertEqual(restored["blocked_from"], "executing")
            self.assertEqual(json.loads(state_path.read_text()), restored)
            self.assertEqual(events_path.read_bytes(), events_before)
            block_reasons = [event["payload"]["reason"] for event in map(json.loads, events_before.splitlines()) if event["type"] == "block"]
            self.assertEqual(block_reasons, ["transient", "another finding"])
            skipped = self.invoke(repo, "resume", "--run-id", run_id, "--target", "finalizing", "--action-id", "skip-1", ok=False)
            self.assertNotEqual(skipped.returncode, 0)
            resumed = self.invoke(repo, "resume", "--run-id", run_id, "--action-id", "resume-1")
            self.assertIn('"state": "executing"', resumed.stdout)


if __name__ == "__main__":
    unittest.main()
