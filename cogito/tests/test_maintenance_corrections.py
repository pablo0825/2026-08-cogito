"""Maintenance corrections keep one delivery commit and auditable snapshots."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, SCRIPTS, git, init_repo, package
import cogito_runtime as runtime


class MaintenanceCli:
    """Exercise the public CLI while sharing the runtime fixture vocabulary."""

    def __init__(self, repo, run_id):
        self.repo, self.run_id = repo, run_id
        self.run_dir = repo / ".cogito/runs" / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.sequence = 0

    def call(self, command, *options):
        self.sequence += 1
        if command not in {"init", "status", "report"}:
            options = (*options, "--action-id", f"cli-{self.sequence}")
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "cogito_gate.py"), "--repo", str(self.repo),
             command, "--run-id", self.run_id, *map(str, options)],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode:
            raise runtime.CogitoError(result.stderr)
        return json.loads(result.stdout)["data"]

    def payload(self, value):
        path = self.run_dir / "drafts" / f"input-{self.sequence + 1}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
        return path

    def create(self, kind):
        return self.call("init", "--no-stage-commits", "--kind", kind)

    def load(self):
        return self.call("status")

    def prepare_package(self, value):
        return self.call("prepare-package", "--package", self.payload(value))

    def approve_package(self, value):
        return self.call("approve", "--package", self.payload(value))

    def approved_package(self):
        return json.loads((self.repo / f"docs/cogito/packages/{self.run_id}.json").read_text())

    def start_gate(self):
        return self.call("start")

    def update_task(self, task, status, agent):
        return self.call("task", "--task-id", task, "--status", status, "--agent-id", agent)

    def submit_agent_result(self, value):
        return self.call("agent-result", "--input", self.payload(value))

    def transition(self, event, value):
        return self.call("transition", "--event", event, "--payload-json", self.payload(value))

    def run_controlled_check(self, check, worktree, action_id):
        return self.call("run-check", "--check-id", check, "--worktree", worktree)

    def complete_verification(self, evidence):
        return self.call("verify", "--evidence", evidence[0]["evidence_path"])

    def complete_integration(self, commit):
        return self.call("integrate", "--commit-id", commit)

    def decide_post_verification(self, evidence):
        return self.call("post-verify", "--evidence", evidence[0]["evidence_path"])

    def add_amendment(self, value):
        return self.call("amend", "--amendment", self.payload(value))

    def enter_correction(self):
        return self.call("correction-start")

    def complete_correction(self, amendment, commit):
        return self.call("correction-complete", "--amendment-id", amendment, "--commit-id", commit)

    def finalize(self, result, graph, commit):
        return self.call("finalize", "--result", result, "--project-graph", graph, "--final-commit", commit)

    def completion_report(self):
        return self.call("report")


class MaintenanceCorrectionTests(GitTestCase):
    def test_cli_pre_and_post_integration_corrections_accept_one_final_commit(self):
        self.run_corrections(cli=True, post_correction=True)

    def test_missing_final_amendment_trailer_is_rejected(self):
        self.run_corrections(reject="missing-trailer")

    def test_every_correction_needs_its_final_trailer(self):
        self.run_corrections(post_correction=True, reject="missing-first-trailer")

    def test_result_cannot_replace_recorded_correction_snapshot(self):
        self.run_corrections(reject="changed-snapshot")

    def test_correction_commit_before_finalization_is_rejected(self):
        self.run_corrections(reject="early-commit")

    def test_correction_on_wrong_branch_with_same_head_is_rejected(self):
        self.run_corrections(reject="wrong-branch")

    def test_staged_unapproved_path_is_rejected_without_changing_index(self):
        self.run_corrections(reject="staged-scope")

    def test_untracked_unapproved_path_is_rejected_without_changing_index(self):
        self.run_corrections(reject="untracked-scope")

    def test_final_merge_commit_is_rejected_even_with_verified_content(self):
        self.run_corrections(reject="merge-final")

    def run_corrections(self, *, cli=False, post_correction=False, reject=None):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_repo(repo)
            (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
            (repo / "note.txt").write_text("before\n")
            git(repo, "add", ".")
            git(repo, "commit", "-qm", "baseline")
            baseline = git(repo, "rev-parse", "HEAD")
            run_id = "MNT-correction-e2e"
            draft = package("maintenance")
            draft.update({
                "run_id": run_id, "baseline_commit": baseline,
                "approved_paths": ["note.txt"],
                "execution_dag": {"tasks": [{"id": "T-1", "paths": ["note.txt"]}], "edges": []},
                "checks": [{"id": "C-1", "required": True, "argv": [
                    sys.executable, "-I", "-c",
                    "from pathlib import Path; assert Path('note.txt').read_text() == 'after\\n'",
                ]}],
            })
            store = (MaintenanceCli if cli else runtime.RunStore)(repo, run_id)
            store.create("maintenance")
            store.prepare_package(draft)
            store.approve_package(draft)
            store.start_gate()
            store.update_task("T-1", "leased", "worker-1")
            store.update_task("T-1", "running", "worker-1")
            (repo / "note.txt").write_text("wrong\n")
            store.submit_agent_result({
                "schema_version": "3.0", "run_id": run_id, "task_id": "T-1", "agent_id": "worker-1",
                "role": "implementer", "status": "complete", "base_commit": baseline, "head_commit": baseline,
                "changed_paths": ["note.txt"], "evidence": [], "risks": [], "requested_transition": "verifying",
            })
            store.update_task("T-1", "complete", "worker-1")
            store.transition("implementation-complete", {})
            self.assertFalse(self.check(store, repo, "pre-failed")["passed"])
            store.add_amendment({"id": "TA-1", "reason": "fix internal typo", "path_fixes": ["note.txt"]})
            store.enter_correction()
            (repo / "note.txt").write_text("after\n")
            if reject in {"wrong-branch", "staged-scope", "untracked-scope"}:
                if reject == "wrong-branch":
                    git(repo, "switch", "-qc", "other-branch")
                    expected_error = "unchanged Start Gate HEAD"
                else:
                    (repo / "outside.txt").write_text("not approved\n")
                    if reject == "staged-scope":
                        git(repo, "add", "outside.txt")
                    expected_error = "snapshot exceeds approved paths"
                index_before = (repo / ".git/index").read_bytes()
                before = store.events_path.read_bytes()
                with self.assertRaisesRegex(runtime.CogitoError, expected_error):
                    store.complete_correction("TA-1", baseline)
                self.assertEqual((repo / ".git/index").read_bytes(), index_before)
                self.assertEqual(store.events_path.read_bytes(), before)
                self.assertEqual(git(repo, "rev-parse", "HEAD"), baseline)
                self.assertEqual(store.load()["state"], "technical-correction")
                return
            if reject == "early-commit":
                git(repo, "add", "note.txt")
                git(repo, "commit", "-qm", "early fix\n\nCogito-Amendment: TA-1")
                before = store.events_path.read_bytes()
                for checkpoint in (git(repo, "rev-parse", "HEAD"), baseline):
                    with self.subTest(checkpoint=checkpoint):
                        with self.assertRaisesRegex(runtime.CogitoError, "unchanged Start Gate HEAD"):
                            store.complete_correction("TA-1", checkpoint)
                        self.assertEqual(store.events_path.read_bytes(), before)
                self.assertEqual(store.load()["state"], "technical-correction")
                return
            index_before = (repo / ".git/index").read_bytes()
            store.complete_correction("TA-1", baseline)
            self.assertEqual((repo / ".git/index").read_bytes(), index_before)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), baseline)
            fixed = self.check(store, repo, "pre-fixed")
            self.assertTrue(fixed["passed"])
            store.complete_verification([fixed])
            store.transition("review-approved", {"review_exemption": True})
            store.complete_integration(baseline)
            if post_correction:
                (repo / "note.txt").write_text("post typo\n")
                self.assertFalse(self.check(store, repo, "post-failed")["passed"])
                store.add_amendment({"id": "TA-2", "reason": "fix integration typo", "path_fixes": ["note.txt"]})
                store.enter_correction()
                (repo / "note.txt").write_text("after\n")
                state = store.complete_correction("TA-2", baseline)
                self.assertEqual(state["state"], "post-integration-verification")
                self.assertEqual(git(repo, "rev-parse", "HEAD"), baseline)
            post = self.check(store, repo, "post-fixed")
            self.assertTrue(post["passed"])
            store.decide_post_verification([post])
            events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
            integrations = [event for event in events if event["type"] == "integration-complete"]
            self.assertEqual(len(integrations), 1)
            completions = [event["payload"] for event in events if event["type"] in {
                "technical-correction-complete", "post-integration-correction-complete",
            }]
            self.assertEqual(len(completions), 2 if post_correction else 1)
            for item in completions:
                self.assertEqual(item["completion_mode"], "working-tree")
                self.assertEqual(item["commit_id"], baseline)
                self.assertEqual(git(repo, "cat-file", "-t", item["content_tree"]), "tree")
            amendments = [{"id": item["amendment_id"], "base_commit": baseline,
                           "content_tree": item["content_tree"]} for item in completions]
            if reject == "changed-snapshot":
                amendments[0]["content_tree"] = git(repo, "rev-parse", f"{baseline}^{{tree}}")
            graph_path = repo / "docs/cogito/project-graph.json"
            graph = json.loads(graph_path.read_text())
            graph["active_run_id"] = None
            graph_path.write_text(json.dumps(graph))
            result_relative = f"docs/cogito/results/{run_id}.json"
            result_path = repo / result_relative
            result_path.parent.mkdir(parents=True)
            result_path.write_text(json.dumps({
                "schema_version": "3.0", "run_id": run_id, "status": "accepted",
                "package_hash": runtime.package_hash(store.approved_package()),
                "effective_contract_hash": store.load()["effective_contract_hash"],
                "integration_commits": [baseline], "slice_dispositions": {},
                "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
                "reviews": [], "amendments": amendments,
                "human_gate": {"required": False, "outcome": "not-required"}, "remaining_risks": [],
            }))
            trailers = [f"Cogito-Amendment: {item['id']}" for item in amendments]
            if reject == "missing-trailer":
                trailers = []
            elif reject == "missing-first-trailer":
                trailers = trailers[1:]
            git(repo, "add", "note.txt", "docs/cogito/project-graph.json", result_relative)
            git(repo, "commit", "-qm", "maintenance result\n\n" + "\n".join(trailers))
            final = git(repo, "rev-parse", "HEAD")
            self.assertEqual(git(repo, "rev-list", "--count", f"{baseline}..{final}"), "1")
            if reject == "merge-final":
                verified_tree = git(repo, "rev-parse", f"{final}^{{tree}}")
                extra = git(repo, "commit-tree", f"{baseline}^{{tree}}", "-p", baseline, "-m", "extra parent")
                final = git(repo, "commit-tree", verified_tree, "-p", baseline, "-p", extra,
                            "-m", "maintenance merge\n\n" + "\n".join(trailers))
                git(repo, "reset", "--hard", final)
                self.assertEqual(git(repo, "rev-parse", f"{final}^{{tree}}"), verified_tree)
            if reject:
                before = store.events_path.read_bytes()
                expected_error = (
                    "does not match Maintenance correction history"
                    if reject == "changed-snapshot" else
                    "Maintenance must finalize as one commit from the Start Gate head"
                    if reject == "merge-final" else "without its trailer"
                )
                with self.assertRaisesRegex(runtime.CogitoError, expected_error):
                    store.finalize(result_relative, "docs/cogito/project-graph.json", final)
                self.assertEqual(store.events_path.read_bytes(), before)
                self.assertEqual(store.load()["state"], "finalizing")
                return
            store.finalize(result_relative, "docs/cogito/project-graph.json", final)
            report = store.completion_report()
            self.assertEqual(report["status"], "accepted")
            self.assertEqual(report["final_commit"], final)
            self.assertEqual(report["amendments"], [{**item, "commit_id": final} for item in amendments])
            self.assertEqual(git(repo, "show", f"{final}:note.txt"), "after")

    @staticmethod
    def check(store, repo, action_id):
        before = set((store.run_dir / "evidence").glob("C-1-*.json"))
        store.run_controlled_check("C-1", repo, action_id)
        path, = set((store.run_dir / "evidence").glob("C-1-*.json")) - before
        return json.loads(path.read_text())
