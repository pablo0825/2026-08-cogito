"""Synthetic human decisions exercise real RP CLI processes and Git workers.

These decisions apply only to disposable test repositories, never live approval.
"""

import copy
import hashlib
import json
import subprocess
import sys

from cogito_test_support import GitTestCase, SCRIPTS, git
from cogito_common import CogitoError
from cogito_projection import project_events
from cogito_run_store import RunStore
import test_human_acceptance as human_support
import test_human_replan as human_replan_support
import test_replan_e2e as replan_support


class DraftReplanCli(replan_support.ReplanCli):
    """Place command inputs in the managed RP drafts, not arbitrary runtime paths."""

    def _input(self, operation, value, action_id):
        path = self.repo / ".cogito/replans" / self.replan_id / "drafts" / f"{operation}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return self.call(operation, action_id, input=path)


class ReplanRuntimeHumanEndToEndTests(GitTestCase):
    fixture = replan_support.ReplanEndToEndTests.fixture
    result = staticmethod(replan_support.ReplanEndToEndTests.result)
    check = staticmethod(replan_support.ReplanEndToEndTests.check)
    _finish = human_replan_support.HumanReplanTests._finish

    def test_unignored_runtime_handoff_requires_fresh_human_acceptance(self):
        repo, original_worker, source, ranges = self.fixture()
        self._finish(repo, original_worker, source, ranges, "FS-1", "codex/fs-1")
        source.human_feedback(
            human_support.HumanAcceptanceTests.feedback(close=True, mixed=True),
            "synthetic-mixed-feedback",
        )
        state = source.human_triage({
            "feedback_id": "HF-1",
            "assessments": [
                {"id": "I-1", "disposition": "local", "reason": "Single label typo"},
                {"id": "I-2", "disposition": "change", "reason": "Automatic query changes interaction"},
            ],
        }, "synthetic-mixed-triage")
        self.assertEqual(state["state"], "human-feedback-triage")
        self.assertEqual(state["human"]["triage"]["route"], "change")
        with self.assertRaises(CogitoError):
            source.human_correction_start({"amendment_id": "TA-bypass"}, "reject-local-bypass")

        # Reproduce the delivery/Worker mismatch before begin, stop and all RP Gates.
        (repo / ".gitignore").write_text("docs/cogito/packages/\n")
        git(repo, "add", ".gitignore")
        git(repo, "commit", "-qm", "Simulate delivery without runtime ignore")
        self.assertNotIn(".cogito/", (repo / ".gitignore").read_text())
        self.assertIn(".cogito/", (original_worker / ".gitignore").read_text())
        ignored = subprocess.run(
            ["git", "check-ignore", ".cogito/replans/probe"], cwd=repo,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(ignored.returncode, 1)
        original_events = source.events_path.read_bytes()
        original_package = source.approved_package()
        original_feedback_hash = source.load()["human"]["feedback_hash"]
        original_worker_head = git(original_worker, "rev-parse", "HEAD")
        original_index = (repo / ".git/index").read_bytes()

        replan = DraftReplanCli(repo, "RP-runtime-human")
        replan.begin(source.run_id, "DEV-successor-e2e", "Synthetic human interaction change", "begin")
        self.assertEqual(replan.stop("stop")["state"], "analyzing")
        stopped_events = (repo / ".cogito/replans/RP-runtime-human/events.jsonl").read_bytes()

        draft = copy.deepcopy(original_package)
        draft.pop("package_hash", None)
        draft.update(run_id="DEV-successor-e2e", kind="change",
                     baseline_commit=git(repo, "rev-parse", "HEAD"))
        for sl in draft["slices"]:
            old_id = sl["id"]
            sl.update(id=old_id + "-V2", type="change", lineage=[old_id])
            sl["worker"]["branch"] += "-v2"
            sl["worker"]["worktree"] += "-v2"
            for name in ("spec", "plan"):
                path = f"docs/{name}-successor.md"
                content = f"# Successor {name}\nSynthetic interaction change.\n"
                (repo / path).write_text(content)
                sl[name] = {"path": path, "hash": hashlib.sha256(content.encode()).hexdigest()}
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
            "author_id": "planner", "package": draft,
            "differences": {key: "Synthetic change reviewed: " + key for key in (
                "requirements", "api", "boundary", "acceptance", "cost", "revalidation")},
            "work": [{"source_task_id": task, "target_task_id": task,
                      "disposition": "adapt", "validation": "rerun",
                      "reason": "Changed interaction requires new checks and review"}
                     for task in source.load()["tasks"]],
        }
        state = replan.propose(proposal, "propose")
        self.assertEqual(state["state"], "reviewing")
        replan.review({
            "proposal_hash": state["proposal_hash"], "reviewer_id": "independent-planner",
            "findings": [], "assessment": {key: "Checked proposal and preserved sources"
                for key in ("impact", "reuse", "revalidation", "handoff")},
        }, "review")
        replan.approve(state["proposal_hash"], "synthetic-rp-approval")
        self.assertEqual(replan.handoff("handoff")["state"], "completed")
        self.assertEqual(successor.load()["state"], "executing")
        self.assertEqual((repo / ".git/index").read_bytes(), original_index)
        self.assertTrue((repo / ".cogito/replans/RP-runtime-human/events.jsonl")
                        .read_bytes().startswith(stopped_events))
        self.assertEqual(source.load()["state"], "superseded")
        self.assertTrue(source.events_path.read_bytes().startswith(original_events))
        self.assertEqual(source.approved_package(), original_package)
        self.assertEqual(source.load()["human"]["feedback_hash"], original_feedback_hash)
        self.assertEqual(git(original_worker, "rev-parse", "HEAD"), original_worker_head)
        self.assertEqual(git(original_worker, "status", "--porcelain"), "")

        # RP completed without runtime ignores. General post-integration runner
        # snapshots have a separate contract, so isolate runtime locally now.
        # This changes no tracked file or prior snapshot, and no global config.
        exclude = repo / ".git/info/exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text(".cogito/\n")
        worktree = repo / draft["slices"][0]["worker"]["worktree"]
        ranges = []
        for index, name in enumerate(("a", "b"), 1):
            task_id = f"T-{index}"
            base = git(worktree, "rev-parse", "HEAD")
            successor.update_task(task_id, "leased", "slice-worker")
            successor.update_task(task_id, "running", "slice-worker")
            (worktree / f"src/{name}.txt").write_text(f"{name}2\n")
            git(worktree, "add", f"src/{name}.txt")
            git(worktree, "commit", "-qm", f"Adapt {task_id} to human feedback")
            head = git(worktree, "rev-parse", "HEAD")
            ranges.append((base, head))
            result = self.result(successor, task_id, base, head)
            result.update(agent_id="slice-worker", role="implementer",
                          changed_paths=[f"src/{name}.txt"], requested_transition="verifying")
            result.pop("reviewed_implementer")
            successor.submit_agent_result(result)
            successor.update_task(task_id, "complete", "slice-worker")
        successor.transition("implementation-complete", {})
        pre = self.check(successor, worktree, "successor-pre")
        self.assertTrue(pre["passed"], pre["stderr"])
        successor.complete_verification([pre])
        self._finish(repo, worktree, successor, ranges, "FS-1-V2", "codex/fs-1-v2")
        state = RunStore(repo, successor.run_id).load()
        self.assertEqual(successor.approved_package()["human_gate"]["predicates"], [])
        self.assertEqual(state["state"], "awaiting-human")
        self.assertEqual(state["human_review_mandate"]["source_run_id"], source.run_id)
        self.assertEqual(state["human_review_mandate"]["source_feedback_hash"], original_feedback_hash)
        self.assertFalse(state.get("human"))
        events = [json.loads(line) for line in successor.events_path.read_text().splitlines()]
        self.assertFalse(any(event["type"] == "human-approved" for event in events))
        self.assertEqual(project_events(events, successor.workflow)["human_review_mandate"],
                         state["human_review_mandate"])
        saved = successor.events_path.read_bytes()
        replan.handoff("handoff")
        self.assertEqual(successor.events_path.read_bytes(), saved)

        # Only this fresh synthetic decision authorizes successor finalization.
        approved = subprocess.run([
            sys.executable, "-B", str(SCRIPTS / "cogito_gate.py"), "--repo", str(repo),
            "human-approve", "--run-id", successor.run_id,
            "--action-id", "synthetic-fresh-successor-acceptance",
        ], capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(approved.returncode, 0, approved.stderr)
        self.assertEqual(json.loads(approved.stdout)["data"]["state"], "finalizing")
        self.assertTrue(successor.events_path.read_bytes().startswith(saved))


if __name__ == "__main__":
    import unittest
    unittest.main()
