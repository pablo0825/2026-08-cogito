"""End-to-end contract for a multi-Slice Feature run in a real Git repository."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


from cogito_test_support import GitTestCase, git, init_repo
import cogito_runtime as runtime
from cogito_run_queries import completion_report_hint


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class FeatureMultiSliceEndToEndTests(GitTestCase):
    def test_cross_slice_dag_is_reviewed_integrated_and_auto_accepted(self) -> None:
        self._run_feature()

    def test_explicit_workflow_limits_reach_runner_verification_and_finalization(self) -> None:
        workflow = runtime.load_workflow()
        workflow["limits"]["transient_retries"] = 4
        with ExitStack() as stack:
            for module in ("cogito_contracts", "cogito_projection", "cogito_runner", "cogito_run_store"):
                stack.enter_context(mock.patch(
                    f"{module}.load_workflow", side_effect=AssertionError("unexpected default workflow read"),
                ))
            self._run_feature(workflow=workflow)

    def test_incorrect_slice_content_fails_checks_and_cannot_pass_verification(self) -> None:
        for slice_name in ("a", "b"):
            with self.subTest(slice=slice_name):
                self._run_feature(invalid_product=slice_name)

    def test_final_commit_cannot_include_unverified_product_changes(self) -> None:
        self._run_feature(change_after_verification=True)

    def _run_feature(
        self, change_after_verification: bool = False, *, invalid_product: str | None = None,
        workflow: dict | None = None,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_repo(repo, branch="main")

            (repo / "src").mkdir()
            (repo / "docs").mkdir()
            (repo / "tests").mkdir()
            (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
            (repo / "src/a.txt").write_text("a0\n")
            (repo / "src/b.txt").write_text("b0\n")
            self._write_product_test(repo, "a", "a0\n")
            self._write_product_test(repo, "b", "b0\n")
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
                        "worker": {"branch": "codex/fs-a", "worktree": ".cogito/worktrees/FS-A", "allowed_paths": ["src/a.txt", "tests/test_a.py"]},
                    },
                    {
                        "id": "FS-B", "type": "feature",
                        "spec": {"path": "docs/b-spec.md", "hash": sha256(repo / "docs/b-spec.md")},
                        "plan": {"path": "docs/b-plan.md", "hash": sha256(repo / "docs/b-plan.md")},
                        "worker": {"branch": "codex/fs-b", "worktree": ".cogito/worktrees/FS-B", "allowed_paths": ["src/b.txt", "tests/test_b.py"]},
                    },
                ],
                "execution_dag": {
                    "tasks": [
                        {"id": "T-A", "slice_id": "FS-A", "paths": ["src/a.txt", "tests/test_a.py"]},
                        {"id": "T-B", "slice_id": "FS-B", "paths": ["src/b.txt", "tests/test_b.py"]},
                    ],
                    "edges": [{"from": "T-A", "to": "T-B"}],
                },
                "checks": [{"id": "C-1", "argv": [sys.executable, "-B", "-m", "unittest", "discover", "-s", "tests", "-v"], "required": True}],
                "approved_paths": ["src/**", "tests/**"],
                "human_gate": {"predicates": [], "high_risk_hotspots": []},
                "policy_snapshot": {"max_workers": 2, "fetch_allowed": False},
                "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
                "stop_conditions": ["contract-boundary-change"],
                "source_registry": [],
            }

            if workflow is not None:
                draft["limits"]["transient_retries"] = workflow["limits"]["transient_retries"]
            store = runtime.RunStore(repo, run_id, workflow)
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

            (worktree_a / "src/a.txt").write_text("incorrect\n" if invalid_product == "a" else "a1\n")
            self._write_product_test(worktree_a, "a", "a1\n")
            git(worktree_a, "add", "src/a.txt", "tests/test_a.py")
            git(worktree_a, "commit", "-qm", "implement FS-A")
            head_a = git(worktree_a, "rev-parse", "HEAD")
            store.submit_agent_result(self._result(run_id, "T-A", "implementer-a", "implementer", baseline, head_a, ["src/a.txt", "tests/test_a.py"], "verifying"))
            store.update_task("T-A", "complete", "implementer-a")
            implemented_a = store.transition("implementation-complete", {}, "implemented-a")
            self.assertEqual(store.transition("implementation-complete", {}, "implemented-a"), implemented_a)
            pre_a = self._run_check(store, worktree_a, "pre-a")
            if invalid_product == "a":
                self._assert_product_rejected(store, pre_a, "T-A")
                return
            self.assertTrue(pre_a["passed"], pre_a["stderr"])
            self.assertIn("Ran 2 tests", pre_a["stderr"])
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
            (worktree_b / "src/b.txt").write_text("incorrect\n" if invalid_product == "b" else "b1\n")
            self._write_product_test(worktree_b, "b", "b1\n")
            git(worktree_b, "add", "src/b.txt", "tests/test_b.py")
            git(worktree_b, "commit", "-qm", "implement FS-B")
            head_b = git(worktree_b, "rev-parse", "HEAD")
            store.submit_agent_result(self._result(run_id, "T-B", "implementer-b", "implementer", integration_a, head_b, ["src/b.txt", "tests/test_b.py"], "verifying"))
            store.update_task("T-B", "complete", "implementer-b")
            implemented_b = store.transition("implementation-complete", {}, "implemented-b")
            self.assertEqual(store.transition("implementation-complete", {}, "implemented-b"), implemented_b)
            pre_b = self._run_check(store, worktree_b, "pre-b")
            if invalid_product == "b":
                self._assert_product_rejected(store, pre_b, "T-B")
                return
            self.assertTrue(pre_b["passed"], pre_b["stderr"])
            self.assertIn("Ran 2 tests", pre_b["stderr"])
            store.complete_verification([pre_b])
            store.submit_agent_result(self._result(run_id, "T-B", "reviewer-b", "reviewer", integration_a, head_b, [], "review-approved", "implementer-b"))
            reviewed_b = store.transition("review-approved", {}, "reviewed-b")
            self.assertEqual(store.transition("review-approved", {}, "reviewed-b"), reviewed_b)
            git(repo, "merge", "--no-ff", "-qm", "integrate FS-B", "codex/fs-b")
            integration_b = git(repo, "rev-parse", "HEAD")
            state = store.complete_integration(integration_b, "FS-B")
            self.assertEqual(state["state"], "post-integration-verification")

            post = self._run_check(store, repo, "post")
            self.assertTrue(post["passed"], post["stderr"])
            self.assertIn("Ran 2 tests", post["stderr"])
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
            self.assertEqual(git(repo, "show", f"{final_commit}:src/a.txt"), "a1")
            self.assertEqual(git(repo, "show", f"{final_commit}:src/b.txt"), "b1")
            self.assertEqual({item["reviewer"] for item in report["reviews"]}, {"reviewer-a", "reviewer-b"})
            # Later edits and commits must not replace the recorded delivery report.
            (repo / f"docs/cogito/results/{run_id}.json").write_text("{invalid later result")
            git(repo, "add", f"docs/cogito/results/{run_id}.json")
            git(repo, "commit", "-qm", "later unrelated edit")
            before = store.events_path.read_bytes()
            with mock.patch.object(store, "load", wraps=store.load) as load_state:
                guidance = store.next_action()
                self.assertEqual(guidance['state'], 'accepted')
                self.assertEqual(guidance['next_action'], 'report-completion')
                self.assertNotIn('report', guidance)
                self.assertEqual(guidance['report_query'], completion_report_hint(store.root, run_id))
                self.assertTrue(guidance['cleanup']['observation_only'])
                load_state.assert_called_once_with()
            self.assertEqual(store.completion_report(), report)
            self.assertEqual(store.events_path.read_bytes(), before)

    @staticmethod
    def _write_product_test(repo: Path, name: str, expected: str) -> None:
        # Each Slice owns its product assertion, which is merged with its change.
        (repo / f"tests/test_{name}.py").write_text(
            "from pathlib import Path\n"
            "import unittest\n\n"
            "class ProductContentTests(unittest.TestCase):\n"
            "    def test_content(self):\n"
            f"        self.assertEqual(Path('src/{name}.txt').read_text(), {expected!r})\n"
        )

    def _assert_product_rejected(self, store, evidence: dict, task_id: str) -> None:
        self.assertEqual(evidence["status"], "failed")
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["exit_code"], 1)
        self.assertIn("AssertionError", evidence["stderr"])
        self.assertFalse(evidence["worktree_changed_during_check"])
        before = store.events_path.read_bytes()
        state_before = store.load()
        with self.assertRaisesRegex(runtime.CogitoError, "evidence binding failed"):
            store.complete_verification([evidence])
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual(store.load(), state_before)
        self.assertEqual(state_before["state"], "verifying")
        self.assertEqual(state_before["tasks"][task_id]["status"], "complete")

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
