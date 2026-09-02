"""End-to-end contract for a multi-Slice Feature run in a real Git repository."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]


def load_script(name: str, module_name: str | None = None):
    path = COGITO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(module_name or name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FeatureMultiSliceEndToEndTests(unittest.TestCase):
    def test_cross_slice_dag_is_reviewed_integrated_and_auto_accepted(self) -> None:
        self._run_feature()

    def test_final_commit_cannot_include_unverified_product_changes(self) -> None:
        self._run_feature(change_after_verification=True)

    def _run_feature(self, change_after_verification: bool = False) -> None:
        runtime = load_script("cogito_runtime")
        load_script("cogito_runner")
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "cogito@example.invalid")
            git(repo, "config", "user.name", "Cogito Test")

            (repo / "src").mkdir()
            (repo / "docs").mkdir()
            (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
            (repo / "src/a.txt").write_text("a0\n")
            (repo / "src/b.txt").write_text("b0\n")
            for name in ("a-spec", "a-plan", "b-spec", "b-plan"):
                (repo / f"docs/{name}.md").write_text(f"# {name}\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "baseline")
            baseline = git(repo, "rev-parse", "HEAD")

            run_id = "DEV-feature-e2e-001"
            draft = {
                "schema_version": "3.0",
                "run_id": run_id,
                "kind": "feature",
                "mini_package": False,
                "delivery_branch": "main",
                "baseline_commit": baseline,
                "shared_understanding": {"hash": "b" * 64},
                "boundary": {"decision": "split-required", "evidence": ["two responsibilities"]},
                "slices": [
                    {
                        "id": "FS-A", "type": "feature",
                        "spec": {"path": "docs/a-spec.md", "hash": sha256(repo / "docs/a-spec.md")},
                        "plan": {"path": "docs/a-plan.md", "hash": sha256(repo / "docs/a-plan.md")},
                        "worker": {"branch": "codex/fs-a", "worktree": ".cogito/worktrees/FS-A", "allowed_paths": ["src/a.txt"]},
                    },
                    {
                        "id": "FS-B", "type": "feature",
                        "spec": {"path": "docs/b-spec.md", "hash": sha256(repo / "docs/b-spec.md")},
                        "plan": {"path": "docs/b-plan.md", "hash": sha256(repo / "docs/b-plan.md")},
                        "worker": {"branch": "codex/fs-b", "worktree": ".cogito/worktrees/FS-B", "allowed_paths": ["src/b.txt"]},
                    },
                ],
                "execution_dag": {
                    "tasks": [
                        {"id": "T-A", "slice_id": "FS-A", "paths": ["src/a.txt"]},
                        {"id": "T-B", "slice_id": "FS-B", "paths": ["src/b.txt"]},
                    ],
                    "edges": [{"from": "T-A", "to": "T-B"}],
                },
                "checks": [{"id": "C-1", "argv": [sys.executable, "-c", "print('ok')"], "required": True}],
                "approved_paths": ["src/**"],
                "human_gate": {"predicates": [], "high_risk_hotspots": []},
                "policy_snapshot": {"max_workers": 2, "fetch_allowed": False},
                "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
                "stop_conditions": ["contract-boundary-change"],
                "source_registry": [],
            }

            store = runtime.RunStore(repo, run_id)
            store.create("feature")
            store.transition("shared-understanding-ready", {"shared_understanding_hash": "b" * 64})
            store.transition("shared-understanding-confirmed", {"confirmed": True})
            store.transition("boundary-complete", draft["boundary"])
            store.prepare_package(draft)
            store.approve_package(draft)
            store.start_gate()

            worktree_a = repo / ".cogito/worktrees/FS-A"
            git(repo, "worktree", "add", "-q", "-b", "codex/fs-a", str(worktree_a), baseline)
            store.update_task("T-A", "leased", "implementer-a")
            store.update_task("T-A", "running", "implementer-a")
            blocked_worktree_b = repo / ".cogito/worktrees/FS-B"
            git(repo, "worktree", "add", "-q", "-b", "codex/fs-b", str(blocked_worktree_b), baseline)
            with self.assertRaisesRegex(runtime.CogitoError, "cross-Slice dependencies"):
                store.update_task("T-B", "leased", "implementer-b")
            git(repo, "worktree", "remove", "--force", str(blocked_worktree_b))
            git(repo, "branch", "-D", "codex/fs-b")

            (worktree_a / "src/a.txt").write_text("a1\n")
            git(worktree_a, "add", "src/a.txt")
            git(worktree_a, "commit", "-qm", "implement FS-A")
            head_a = git(worktree_a, "rev-parse", "HEAD")
            store.submit_agent_result(self._result(run_id, "T-A", "implementer-a", "implementer", baseline, head_a, ["src/a.txt"], "verifying"))
            store.update_task("T-A", "complete", "implementer-a")
            implemented_a = store.transition("implementation-complete", {}, "implemented-a")
            self.assertEqual(store.transition("implementation-complete", {}, "implemented-a"), implemented_a)
            pre_a = self._run_check(store, worktree_a, "pre-a")
            store.complete_verification([pre_a])
            store.submit_agent_result(self._result(run_id, "T-A", "reviewer-a", "reviewer", baseline, head_a, [], "review-approved", "implementer-a"))
            reviewed_a = store.transition("review-approved", {}, "reviewed-a")
            self.assertEqual(store.transition("review-approved", {}, "reviewed-a"), reviewed_a)
            git(repo, "merge", "--no-ff", "-qm", "integrate FS-A", "codex/fs-a")
            integration_a = git(repo, "rev-parse", "HEAD")
            state = store.complete_integration(integration_a, "FS-A")
            self.assertEqual(state["state"], "executing")
            self.assertEqual(state["tasks"]["T-A"]["status"], "integrated")

            worktree_b = repo / ".cogito/worktrees/FS-B"
            git(repo, "worktree", "add", "-q", "-b", "codex/fs-b", str(worktree_b), integration_a)
            store.update_task("T-B", "leased", "implementer-b")
            store.update_task("T-B", "running", "implementer-b")
            (worktree_b / "src/b.txt").write_text("b1\n")
            git(worktree_b, "add", "src/b.txt")
            git(worktree_b, "commit", "-qm", "implement FS-B")
            head_b = git(worktree_b, "rev-parse", "HEAD")
            store.submit_agent_result(self._result(run_id, "T-B", "implementer-b", "implementer", integration_a, head_b, ["src/b.txt"], "verifying"))
            store.update_task("T-B", "complete", "implementer-b")
            implemented_b = store.transition("implementation-complete", {}, "implemented-b")
            self.assertEqual(store.transition("implementation-complete", {}, "implemented-b"), implemented_b)
            pre_b = self._run_check(store, worktree_b, "pre-b")
            store.complete_verification([pre_b])
            store.submit_agent_result(self._result(run_id, "T-B", "reviewer-b", "reviewer", integration_a, head_b, [], "review-approved", "implementer-b"))
            reviewed_b = store.transition("review-approved", {}, "reviewed-b")
            self.assertEqual(store.transition("review-approved", {}, "reviewed-b"), reviewed_b)
            git(repo, "merge", "--no-ff", "-qm", "integrate FS-B", "codex/fs-b")
            integration_b = git(repo, "rev-parse", "HEAD")
            state = store.complete_integration(integration_b, "FS-B")
            self.assertEqual(state["state"], "post-integration-verification")

            post = self._run_check(store, repo, "post")
            state = store.decide_post_verification([post], reviewer_escalation=False)
            self.assertEqual(state["state"], "finalizing")

            graph_path = repo / "docs/cogito/project-graph.json"
            graph = json.loads(graph_path.read_text())
            graph["active_run_id"] = None
            for slice_id in ("FS-A", "FS-B"):
                graph["slices"][slice_id]["disposition"] = "accepted"
                graph["slices"][slice_id]["completed_by"] = run_id
            graph_path.write_text(json.dumps(graph))
            result_path = repo / f"docs/cogito/results/{run_id}.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps({
                "schema_version": "3.0", "run_id": run_id, "status": "accepted",
                "package_hash": runtime.package_hash(store.approved_package()),
                "effective_contract_hash": store.load()["effective_contract_hash"],
                "integration_commits": [integration_a, integration_b],
                "slice_dispositions": {"FS-A": "accepted", "FS-B": "accepted"},
                "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
                "reviews": [{"reviewer": "reviewer-a"}, {"reviewer": "reviewer-b"}],
                "amendments": [], "human_gate": {"required": False, "outcome": "not-required"},
                "remaining_risks": [],
            }))
            git(repo, "add", "docs/cogito/project-graph.json", f"docs/cogito/results/{run_id}.json")
            if change_after_verification:
                (repo / "src/a.txt").write_text("unverified replacement\n")
                git(repo, "add", "src/a.txt")
            git(repo, "commit", "-qm", "finalize Cogito feature")
            final_commit = git(repo, "rev-parse", "HEAD")
            if change_after_verification:
                events_before = store.events_path.read_bytes()
                with self.assertRaisesRegex(runtime.CogitoError, "unverified content"):
                    store.finalize(f"docs/cogito/results/{run_id}.json", "docs/cogito/project-graph.json", final_commit)
                self.assertEqual(store.events_path.read_bytes(), events_before)
                self.assertEqual(store.load()["state"], "finalizing")
                return
            store.finalize(f"docs/cogito/results/{run_id}.json", "docs/cogito/project-graph.json", final_commit)
            report = store.completion_report()
            self.assertEqual(report["status"], "accepted")
            self.assertEqual(report["final_commit"], final_commit)
            self.assertEqual({item["reviewer"] for item in report["reviews"]}, {"reviewer-a", "reviewer-b"})

    @staticmethod
    def _result(run_id: str, task_id: str, agent_id: str, role: str, base: str, head: str,
                changed_paths: list[str], transition: str, reviewed_implementer: str | None = None) -> dict:
        result = {
            "schema_version": "3.0", "run_id": run_id, "task_id": task_id,
            "agent_id": agent_id, "role": role, "status": "complete",
            "base_commit": base, "head_commit": head, "changed_paths": changed_paths,
            "evidence": [], "risks": [], "requested_transition": transition,
        }
        if reviewed_implementer:
            result["reviewed_implementer"] = reviewed_implementer
        return result

    @staticmethod
    def _run_check(store, worktree: Path, action_id: str) -> dict:
        before = set((store.run_dir / "evidence").glob("C-1-*.json")) if (store.run_dir / "evidence").exists() else set()
        store.run_controlled_check("C-1", worktree, action_id)
        path = next(path for path in (store.run_dir / "evidence").glob("C-1-*.json") if path not in before)
        return json.loads(path.read_text())


if __name__ == "__main__":
    unittest.main()
