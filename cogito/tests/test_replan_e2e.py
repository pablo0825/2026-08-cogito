"""Real Git acceptance journeys across a reviewed and an accepted predecessor."""

import copy
import json
import subprocess
import sys
import unittest

from cogito_test_support import GitTestCase, SCRIPTS, git
from cogito_common import CogitoError
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import test_feature_multitask as feature_support
import test_maintenance_corrections as correction_support


class ReplanCli:
    """Each Gate is a fresh process; no in-memory state bridges the handoff."""

    def __init__(self, repo, replan_id):
        self.repo, self.replan_id = repo, replan_id

    def call(self, operation, action_id=None, **options):
        argv = [sys.executable, "-B", str(SCRIPTS / "cogito_gate.py"),
                "--repo", str(self.repo), "replan", operation,
                "--replan-id", self.replan_id]
        if action_id:
            argv.extend(["--action-id", action_id])
        for key, value in options.items():
            argv.extend(["--" + key.replace("_", "-"), str(value)])
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise CogitoError(result.stderr)
        return json.loads(result.stdout)["data"]

    def load(self):
        return self.call("status")

    def begin(self, source, successor, reason, action_id):
        return self.call("begin", action_id, source_run=source, successor_run=successor, reason=reason)

    def stop(self, action_id):
        return self.call("stop", action_id)

    def _input(self, operation, value, action_id):
        path = self.repo / ".cogito" / f"e2e-{operation}.json"
        path.write_text(json.dumps(value))
        return self.call(operation, action_id, input=path)

    def propose(self, value, action_id):
        return self._input("propose", value, action_id)

    def review(self, value, action_id):
        return self._input("review", value, action_id)

    def approve(self, proposal_hash, action_id):
        return self.call("approve", action_id, proposal_hash=proposal_hash)

    def handoff(self, action_id):
        return self.call("handoff", action_id)


class ReplanEndToEndTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)
    check = staticmethod(correction_support.MaintenanceCorrectionTests.check)

    def _finish(self, repo, worktree, store, ranges, slice_id, branch):
        """Review actual task ranges, merge, run product checks and finalize."""
        for index, (base, head) in enumerate(ranges, 1):
            store.submit_agent_result(self.result(store, f"T-{index}", base, head))
        self.assertEqual(store.transition("review-approved", {})["state"], "integrating")
        git(repo, "merge", "--no-ff", "-qm", "Integrate verified Slice", branch)
        integration = git(repo, "rev-parse", "HEAD")
        self.assertEqual(store.complete_integration(integration, slice_id)["state"],
                         "post-integration-verification")
        post = self.check(store, repo, "post")
        self.assertTrue(post["passed"], post["stderr"])
        self.assertEqual(store.decide_post_verification([post])["state"], "finalizing")
        graph_relative = "docs/cogito/project-graph.json"
        graph = json.loads((repo / graph_relative).read_text())
        graph["active_run_id"] = None
        graph["slices"][slice_id].update(disposition="accepted", completed_by=store.run_id)
        (repo / graph_relative).write_text(json.dumps(graph))
        result_relative = f"docs/cogito/results/{store.run_id}.json"
        result_path = repo / result_relative
        result_path.parent.mkdir(parents=True, exist_ok=True)
        state = store.load()
        result_path.write_text(json.dumps({
            "schema_version": "3.0", "run_id": store.run_id, "status": "accepted",
            "package_hash": state["package_hash"],
            "effective_contract_hash": state["effective_contract_hash"],
            "integration_commits": [integration],
            "slice_dispositions": {slice_id: "accepted"},
            "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
            "reviews": [{"reviewer": "reviewer-T-1"}, {"reviewer": "reviewer-T-2"}],
            "amendments": [], "human_gate": {"required": False, "outcome": "not-required"},
            "remaining_risks": [],
        }))
        git(repo, "add", graph_relative, result_relative)
        git(repo, "commit", "-qm", "Finalize accepted run")
        final = git(repo, "rev-parse", "HEAD")
        self.assertEqual(store.finalize(result_relative, graph_relative, final)["state"], "accepted")
        self.assertEqual(store.completion_report()["final_commit"], final)
        return final

    def _successor(self, repo, source, *, cli=False):
        replan = (ReplanCli if cli else ReplanStore)(repo, "RP-api-e2e")
        replan.begin(source.run_id, "DEV-successor-e2e", "Approved API contract must change", "begin")
        self.assertEqual(replan.stop("stop")["state"], "analyzing")
        draft = copy.deepcopy(source.approved_package())
        draft.pop("package_hash", None)
        draft.update(run_id="DEV-successor-e2e", kind="change",
                     baseline_commit=git(repo, "rev-parse", "HEAD"))
        for sl in draft["slices"]:
            old_id = sl["id"]
            sl.update(id=old_id + "-V2", type="change", lineage=[old_id])
            sl["worker"]["branch"] += "-v2"
            sl["worker"]["worktree"] += "-v2"
        for task in draft["execution_dag"]["tasks"]:
            task["slice_id"] += "-V2"
        draft["checks"][0]["argv"] = [
            sys.executable, "-I", "-c",
            "from pathlib import Path; "
            "assert Path('src/a.txt').read_text() == 'a2\\n'; "
            "assert Path('src/b.txt').read_text() == 'b2\\n'",
        ]
        successor = RunStore(repo, draft["run_id"])
        successor.create("change")
        successor.transition("shared-understanding-ready", {
            "shared_understanding_hash": draft["shared_understanding"]["hash"]})
        successor.transition("shared-understanding-confirmed", {"confirmed": True})
        successor.transition("boundary-complete", draft["boundary"])
        successor.prepare_package(draft)
        proposal = {
            "author_id": "planner",
            "package": draft,
            "differences": {key: "Change reviewed: " + key for key in (
                "requirements", "api", "boundary", "acceptance", "cost", "revalidation")},
            "work": [{"source_task_id": task, "target_task_id": task,
                      "disposition": "adapt", "validation": "rerun",
                      "reason": "Product API changes require fresh checks and review"}
                     for task in source.load()["tasks"]],
        }
        state = replan.propose(proposal, "propose")
        replan.review({
            "proposal_hash": state["proposal_hash"], "reviewer_id": "independent-planner",
            "findings": [], "assessment": {key: "Checked explicit proposal and sources"
                for key in ("impact", "reuse", "revalidation", "handoff")},
        }, "review")
        replan.approve(state["proposal_hash"], "approve")
        self.assertEqual(replan.handoff("handoff")["state"], "completed")
        self.assertEqual(successor.load()["state"], "executing")
        self.assertFalse(successor.load()["evidence"])
        worktree = repo / draft["slices"][0]["worker"]["worktree"]
        ranges = []
        for index, name in enumerate(("a", "b"), 1):
            self.assertEqual((worktree / f"src/{name}.txt").read_text(), f"{name}1\n")
            task_id = f"T-{index}"
            base = git(worktree, "rev-parse", "HEAD")
            successor.update_task(task_id, "leased", "slice-worker")
            successor.update_task(task_id, "running", "slice-worker")
            (worktree / f"src/{name}.txt").write_text(f"{name}2\n")
            git(worktree, "add", f"src/{name}.txt")
            git(worktree, "commit", "-qm", f"Adapt {task_id} to successor contract")
            head = git(worktree, "rev-parse", "HEAD")
            ranges.append((base, head))
            result = self.result(successor, task_id, base, head)
            result.update(agent_id="slice-worker", role="implementer",
                          changed_paths=[f"src/{name}.txt"], requested_transition="verifying")
            result.pop("reviewed_implementer")
            successor.submit_agent_result(result)
            successor.update_task(task_id, "complete", "slice-worker")
        successor.transition("implementation-complete", {})
        pre = self.check(successor, worktree, "pre")
        self.assertTrue(pre["passed"], pre["stderr"])
        successor.complete_verification([pre])
        self._finish(repo, worktree, successor, ranges, "FS-1-V2", "codex/fs-1-v2")
        for name in ("a", "b"):
            self.assertEqual((repo / f"src/{name}.txt").read_text(), f"{name}2\n")
        return successor, replan

    def test_reviewing_source_is_preserved_and_successor_reaches_accepted(self):
        repo, worktree, source, _ = self.fixture()
        source_package = source.approved_package()
        source_events = source.events_path.read_bytes()
        source_head = git(worktree, "rev-parse", "HEAD")
        successor, replan = self._successor(repo, source, cli=True)
        self.assertEqual(source.load()["state"], "superseded")
        self.assertTrue(source.events_path.read_bytes().startswith(source_events))
        self.assertEqual(source.approved_package(), source_package)
        self.assertEqual(git(worktree, "rev-parse", "HEAD"), source_head)
        self.assertEqual(successor.load()["state"], "accepted")
        self.assertEqual(replan.load()["source_run_id"], source.run_id)

    def test_accepted_source_events_and_report_remain_immutable(self):
        repo, worktree, source, ranges = self.fixture()
        self._finish(repo, worktree, source, ranges, "FS-1", "codex/fs-1")
        source_events = source.events_path.read_bytes()
        report = source.completion_report()
        successor, _ = self._successor(repo, source)
        self.assertEqual(source.load()["state"], "accepted")
        self.assertEqual(source.events_path.read_bytes(), source_events)
        self.assertEqual(source.completion_report(), report)
        self.assertEqual(successor.load()["state"], "accepted")
        graph = json.loads((repo / "docs/cogito/project-graph.json").read_text())
        self.assertEqual(graph["slices"]["FS-1"]["disposition"], "accepted")
        self.assertEqual(graph["slices"]["FS-1-V2"]["lineage"], ["FS-1"])


if __name__ == "__main__":
    unittest.main()
