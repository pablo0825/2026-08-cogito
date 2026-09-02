"""A Slice's serial tasks can each review their own verified commit range."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
import cogito_runtime as runtime
import test_maintenance_corrections as corrections


class FeatureCli(corrections.MaintenanceCli):
    def complete_integration(self, commit, slice_id):
        return self.call("integrate", "--commit-id", commit, "--slice-id", slice_id)

    def enter_review_fix(self):
        return self.call("review-fix-start")

    def complete_review_fix(self, amendment, commit):
        return self.call("review-fix-complete", "--amendment-id", amendment, "--commit-id", commit)


class FeatureMultitaskTests(GitTestCase):
    def fixture(self, *, cli=False, formatting_defect=False, required=True):
        temporary = tempfile.TemporaryDirectory(prefix="cogito-feature-multitask-")
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        for name, content in {
            ".gitignore": ".cogito/\ndocs/cogito/packages/\n",
            "src/a.txt": "a0\n", "src/b.txt": "b0\n",
            "docs/spec.md": "spec\n", "docs/plan.md": "plan\n",
        }.items():
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        baseline = git(repo, "rev-parse", "HEAD")
        draft = package("feature")
        draft.update({
            "run_id": "DEV-feature-multitask", "baseline_commit": baseline,
            "human_gate": {"predicates": [], "high_risk_hotspots": []},
            "execution_dag": {
                "tasks": [
                    {"id": "T-1", "slice_id": "FS-1", "paths": ["src/a.txt"]},
                    {"id": "T-2", "slice_id": "FS-1", "paths": ["src/b.txt"]},
                ],
                "edges": [{"from": "T-1", "to": "T-2"}],
            },
            "checks": [{"id": "C-1", "required": required, "argv": [
                sys.executable, "-I", "-c",
                "from pathlib import Path; "
                "assert Path('src/a.txt').read_text().strip() == 'a1'; "
                "assert Path('src/b.txt').read_text() == 'b1\\n'",
            ]}],
        })
        for key in ("spec", "plan"):
            document = draft["slices"][0][key]
            document["hash"] = hashlib.sha256((repo / document["path"]).read_bytes()).hexdigest()
        store = (FeatureCli if cli else runtime.RunStore)(repo, draft["run_id"])
        store.create("feature")
        store.transition("shared-understanding-ready", {"shared_understanding_hash": "b" * 64})
        store.transition("shared-understanding-confirmed", {"confirmed": True})
        store.transition("boundary-complete", draft["boundary"])
        store.prepare_package(draft)
        # Synthetic approval belongs only to this isolated test repository.
        store.approve_package(draft)
        store.start_gate()
        worktree = repo / ".cogito/worktrees/FS-1"
        git(repo, "worktree", "add", "-q", "-b", "codex/fs-1", str(worktree), baseline)
        ranges = []
        for index, name in enumerate(("a", "b"), 1):
            task_id = f"T-{index}"
            base = git(worktree, "rev-parse", "HEAD")
            store.update_task(task_id, "leased", "slice-worker")
            store.update_task(task_id, "running", "slice-worker")
            content = f"{name}1\n" + ("\n" if formatting_defect and name == "a" else "")
            (worktree / f"src/{name}.txt").write_text(content)
            git(worktree, "add", f"src/{name}.txt")
            git(worktree, "commit", "-qm", f"implement {task_id}")
            head = git(worktree, "rev-parse", "HEAD")
            ranges.append((base, head))
            result = self.result(store, task_id, base, head)
            result.update(agent_id="slice-worker", role="implementer",
                          changed_paths=[f"src/{name}.txt"], requested_transition="verifying")
            result.pop("reviewed_implementer")
            store.submit_agent_result(result)
            store.update_task(task_id, "complete", "slice-worker")
        store.transition("implementation-complete", {})
        evidence = corrections.MaintenanceCorrectionTests.check(store, worktree, "pre")
        self.assertTrue(evidence["passed"])
        store.complete_verification([evidence])
        self.assertEqual(store.load()["state"], "reviewing")
        return repo, worktree, store, ranges

    @staticmethod
    def result(store, task_id, base, head):
        return {
            "schema_version": "3.0", "run_id": store.run_id, "task_id": task_id,
            "agent_id": f"reviewer-{task_id}", "role": "reviewer", "status": "complete",
            "base_commit": base, "head_commit": head, "changed_paths": [],
            "evidence": [], "risks": [], "requested_transition": "review-approved",
            "reviewed_implementer": "slice-worker",
        }

    def assert_rejected(self, store, result):
        events = store.events_path.read_bytes()
        state = store.load()
        with self.assertRaises(runtime.CogitoError):
            store.submit_agent_result(result)
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual(store.load(), state)

    def test_two_serial_tasks_same_slice_finish_via_real_cli(self):
        repo, worktree, store, ranges = self.fixture(cli=True)
        self.assertNotEqual(ranges[0][1], git(worktree, "rev-parse", "HEAD"))
        for index, (base, head) in enumerate(ranges, 1):
            store.submit_agent_result(self.result(store, f"T-{index}", base, head))
        state = store.transition("review-approved", {})
        self.assertEqual(state["state"], "integrating")
        git(repo, "merge", "--no-ff", "-qm", "integrate both Slice tasks", "codex/fs-1")
        integration = git(repo, "rev-parse", "HEAD")
        state = store.complete_integration(integration, "FS-1")
        self.assertEqual(state["state"], "post-integration-verification")
        for task_id in ("T-1", "T-2"):
            self.assertEqual(state["tasks"][task_id]["status"], "integrated")
        post = corrections.MaintenanceCorrectionTests.check(store, repo, "post")
        self.assertTrue(post["passed"])
        self.assertEqual(store.decide_post_verification([post])["state"], "finalizing")

        graph_relative = "docs/cogito/project-graph.json"
        graph_path = repo / graph_relative
        graph = json.loads(graph_path.read_text())
        graph["active_run_id"] = None
        graph["slices"]["FS-1"].update(disposition="accepted", completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        result_relative = f"docs/cogito/results/{store.run_id}.json"
        result_path = repo / result_relative
        result_path.parent.mkdir(parents=True, exist_ok=True)
        state = store.load()
        result_path.write_text(json.dumps({
            "schema_version": "3.0", "run_id": store.run_id, "status": "accepted",
            "package_hash": state["package_hash"],
            "effective_contract_hash": state["effective_contract_hash"],
            "integration_commits": [integration], "slice_dispositions": {"FS-1": "accepted"},
            "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
            "reviews": [{"reviewer": "reviewer-T-1"}, {"reviewer": "reviewer-T-2"}],
            "amendments": [], "human_gate": {"required": False, "outcome": "not-required"},
            "remaining_risks": [],
        }))
        git(repo, "add", graph_relative, result_relative)
        git(repo, "commit", "-qm", "finalize Feature")
        final = git(repo, "rev-parse", "HEAD")
        self.assertEqual(store.finalize(result_relative, graph_relative, final)["state"], "accepted")
        report = store.completion_report()
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["final_commit"], final)
        self.assertEqual({review["reviewer"] for review in report["reviews"]},
                         {"reviewer-T-1", "reviewer-T-2"})
        for name in ("a", "b"):
            self.assertEqual(git(repo, "show", f"{final}:src/{name}.txt"), f"{name}1")

    def test_forged_review_ranges_cannot_skip_or_absorb_other_tasks(self):
        _, _, store, ranges = self.fixture()
        for task, base, head in (
            ("T-1", ranges[0][0], ranges[1][1]),  # absorbs T-2
            ("T-1", ranges[0][1], ranges[0][1]),  # skips T-1
            ("T-2", ranges[0][0], ranges[1][1]),  # absorbs T-1
            ("T-2", ranges[1][1], ranges[1][1]),  # empty review
        ):
            with self.subTest(task=task, base=base, head=head):
                self.assert_rejected(store, self.result(store, task, base, head))

    def test_review_fix_requires_fresh_reviews_of_original_and_added_task_ranges_via_cli(self):
        _, worktree, store, ranges = self.fixture(cli=True, formatting_defect=True)
        store.submit_agent_result(self.result(store, "T-2", *ranges[1]))
        finding = self.result(store, "T-1", *ranges[0])
        finding.update(status="needs-fix", requested_transition="review-fix",
                       risks=["Remove the extra trailing blank line in src/a.txt"])
        store.submit_agent_result(finding)
        store.enter_review_fix()
        store.add_amendment({
            "id": "TA-review", "reason": "remove trailing blank line found in review",
            "added_tasks": [{"id": "T-3", "slice_id": "FS-1", "paths": ["src/a.txt"]}],
        })
        base = git(worktree, "rev-parse", "HEAD")
        store.update_task("T-3", "leased", "slice-worker")
        store.update_task("T-3", "running", "slice-worker")
        (worktree / "src/a.txt").write_text("a1\n")
        git(worktree, "add", "src/a.txt")
        git(worktree, "commit", "-qm", "Remove trailing blank line\n\nCogito-Amendment: TA-review")
        head = git(worktree, "rev-parse", "HEAD")
        result = self.result(store, "T-3", base, head)
        result.update(agent_id="slice-worker", role="implementer",
                      changed_paths=["src/a.txt"], requested_transition="verifying")
        result.pop("reviewed_implementer")
        store.submit_agent_result(result)
        store.update_task("T-3", "complete", "slice-worker")
        store.complete_review_fix("TA-review", head)
        evidence = corrections.MaintenanceCorrectionTests.check(store, worktree, "review-fix-check")
        self.assertTrue(evidence["passed"])
        store.complete_verification([evidence])

        # Original task ranges remain reviewable after the correction commit.
        store.submit_agent_result(self.result(store, "T-1", *ranges[0]))
        store.submit_agent_result(self.result(store, "T-3", base, head))
        events = store.events_path.read_bytes()
        with self.assertRaises(runtime.CogitoError):
            # T-2's approval belongs to the previous verification cycle.
            store.transition("review-approved", {})
        self.assertEqual(store.events_path.read_bytes(), events)
        store.submit_agent_result(self.result(store, "T-2", *ranges[1]))
        self.assertEqual(store.transition("review-approved", {})["state"], "integrating")

    def test_same_worker_cannot_review_either_of_its_tasks(self):
        _, _, store, ranges = self.fixture()
        for index, (base, head) in enumerate(ranges, 1):
            result = self.result(store, f"T-{index}", base, head)
            result["agent_id"] = "slice-worker"
            self.assert_rejected(store, result)

    def test_optional_only_review_still_requires_immutable_runner_evidence(self):
        for tamper in (False, True):
            with self.subTest(tamper=tamper):
                _, _, store, ranges = self.fixture(required=False)
                if tamper:
                    path = next((store.run_dir / "evidence").glob("C-1-*.json"))
                    evidence = json.loads(path.read_text())
                    evidence["stdout"] = "changed after verification"
                    # Deliberately simulate external corruption of this fixture's
                    # normally read-only evidence; the Gate must detect it.
                    path.chmod(0o600)
                    path.write_text(json.dumps(evidence))
                    self.assert_rejected(store, self.result(store, "T-1", *ranges[0]))
                else:
                    for index, (base, head) in enumerate(ranges, 1):
                        store.submit_agent_result(self.result(store, f"T-{index}", base, head))
                    self.assertEqual(store.transition("review-approved", {})["state"], "integrating")

    def test_unverified_slice_changes_reject_historical_task_review(self):
        for mutation in ("dirty", "staged", "untracked", "commit", "empty-commit", "new-check"):
            with self.subTest(mutation=mutation):
                _, worktree, store, ranges = self.fixture()
                if mutation == "untracked":
                    (worktree / "src/unreviewed.txt").write_text("new\n")
                elif mutation == "empty-commit":
                    git(worktree, "commit", "--allow-empty", "-qm", "unverified new HEAD")
                elif mutation == "new-check":
                    # A fresh check cannot bypass the closed verification phase.
                    git(worktree, "commit", "--allow-empty", "-qm", "unverified new HEAD")
                    with self.assertRaisesRegex(runtime.CogitoError, "controlled checks are not legal"):
                        store.run_controlled_check("C-1", worktree, "unaccepted")
                else:
                    (worktree / "src/b.txt").write_text("unverified replacement\n")
                    if mutation in {"staged", "commit"}:
                        git(worktree, "add", "src/b.txt")
                    if mutation == "commit":
                        git(worktree, "commit", "-qm", "unverified replacement")
                self.assert_rejected(store, self.result(store, "T-1", *ranges[0]))


if __name__ == "__main__":
    import unittest
    unittest.main()
