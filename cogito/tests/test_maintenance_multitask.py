"""Serial Maintenance tasks retain individual scope and one final delivery commit."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError, hash_json
from cogito_run_store import RunStore
import test_maintenance_corrections as corrections


class MaintenanceMultitaskTests(GitTestCase):
    def fixture(self, *, cli=False, single_task=False):
        temporary = tempfile.TemporaryDirectory(prefix="cogito-maintenance-multitask-")
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
        for name in ("first.txt", "second.txt", "outside.txt"):
            (repo / name).write_text("before\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        baseline = git(repo, "rev-parse", "HEAD")
        draft = package("maintenance")
        draft.update({
            "run_id": "MNT-multitask", "baseline_commit": baseline,
            "approved_paths": ["first.txt", "second.txt"],
            "execution_dag": {
                "tasks": [{"id": "T-1", "paths": ["first.txt"]},
                          {"id": "T-2", "paths": ["second.txt"]}],
                "edges": [{"from": "T-1", "to": "T-2"}],
            },
            "checks": [{"id": "C-1", "required": True, "argv": [
                sys.executable, "-I", "-c",
                "from pathlib import Path; "
                "assert all(Path(p).read_text() == 'after\\n' "
                "for p in ('first.txt', 'second.txt')); "
                "assert Path('outside.txt').read_text() == 'before\\n'",
            ]}],
        })
        if single_task:
            draft["execution_dag"]["tasks"] = draft["execution_dag"]["tasks"][:1]
            draft["execution_dag"]["edges"] = []
        store = (corrections.MaintenanceCli if cli else RunStore)(repo, draft["run_id"])
        store.create("maintenance")
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        return repo, store, baseline

    @staticmethod
    def result(store, baseline, task, paths):
        return {
            "schema_version": "3.0", "run_id": store.run_id, "task_id": task,
            "agent_id": "worker", "role": "implementer", "status": "complete",
            "base_commit": baseline, "head_commit": baseline, "changed_paths": paths,
            "evidence": [], "risks": [], "requested_transition": "verifying",
        }

    def lease(self, repo, store, task):
        before = (repo / ".git/index").read_bytes()
        store.update_task(task, "leased", "worker")
        store.update_task(task, "running", "worker")
        self.assertEqual((repo / ".git/index").read_bytes(), before)

    def first_task(self, repo, store, baseline, *, staged=False):
        self.lease(repo, store, "T-1")
        (repo / "first.txt").write_text("after\n")
        if staged:
            git(repo, "add", "first.txt")
        before = (repo / ".git/index").read_bytes()
        store.submit_agent_result(self.result(store, baseline, "T-1", ["first.txt"]))
        store.update_task("T-1", "complete", "worker")
        self.assertEqual((repo / ".git/index").read_bytes(), before)
        self.assertEqual(git(repo, "rev-parse", "HEAD"), baseline)

    def assert_rejected_without_mutation(self, repo, store, operation, pattern=None):
        index = (repo / ".git/index").read_bytes()
        events = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, pattern or ".+"):
            operation()
        self.assertEqual((repo / ".git/index").read_bytes(), index)
        self.assertEqual(store.events_path.read_bytes(), events)

    def test_two_serial_tasks_accept_one_final_commit_via_cli(self):
        for staged_first in (False, True):
            with self.subTest(staged_first=staged_first):
                self.finish_two_tasks(staged_first=staged_first)

    def test_two_serial_tasks_with_independent_reviews_accept_one_final_commit_via_cli(self):
        self.finish_two_tasks(staged_first=True, independent_review=True)

    def finish_two_tasks(self, *, staged_first, independent_review=False):
        repo, store, baseline = self.fixture(cli=True)
        self.first_task(repo, store, baseline, staged=staged_first)
        self.lease(repo, store, "T-2")
        (repo / "second.txt").write_text("after\n")
        before = (repo / ".git/index").read_bytes()
        store.submit_agent_result(self.result(store, baseline, "T-2", ["second.txt"]))
        store.update_task("T-2", "complete", "worker")
        self.assertEqual((repo / ".git/index").read_bytes(), before)
        self.assertEqual(git(repo, "rev-parse", "HEAD"), baseline)
        results = store.load()["agent_results"]
        self.assertEqual([result["changed_paths"] for result in results],
                         [["first.txt"], ["second.txt"]])
        store.transition("implementation-complete", {})
        pre = corrections.MaintenanceCorrectionTests.check(store, repo, "pre")
        self.assertTrue(pre["passed"])
        store.complete_verification([pre])
        reviews = []
        if independent_review:
            for task_id in ("T-1", "T-2"):
                reviewer = f"reviewer-{task_id}"
                result = self.result(store, baseline, task_id, [])
                result.update(role="reviewer", agent_id=reviewer,
                              reviewed_implementer="worker", requested_transition="review-approved")
                store.submit_agent_result(result)
                reviews.append({"reviewer": reviewer})
            store.transition("review-approved", {})
        else:
            store.transition("review-approved", {"review_exemption": True})
        store.complete_integration(baseline)
        post = corrections.MaintenanceCorrectionTests.check(store, repo, "post")
        self.assertTrue(post["passed"])
        store.decide_post_verification([post])
        graph_relative = "docs/cogito/project-graph.json"
        graph_path = repo / graph_relative
        graph = json.loads(graph_path.read_text())
        graph["active_run_id"] = None
        graph_path.write_text(json.dumps(graph))
        result_relative = f"docs/cogito/results/{store.run_id}.json"
        result_path = repo / result_relative
        result_path.parent.mkdir(parents=True, exist_ok=True)
        state = store.load()
        result_path.write_text(json.dumps({
            "schema_version": "3.0", "run_id": store.run_id, "status": "accepted",
            "package_hash": state["package_hash"],
            "effective_contract_hash": state["effective_contract_hash"],
            "integration_commits": [baseline], "slice_dispositions": {},
            "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
            "reviews": reviews, "amendments": [],
            "human_gate": {"required": False, "outcome": "not-required"},
            "remaining_risks": [],
        }))
        git(repo, "add", "first.txt", "second.txt", graph_relative, result_relative)
        git(repo, "commit", "-qm", "complete both Maintenance tasks")
        final = git(repo, "rev-parse", "HEAD")
        self.assertEqual(git(repo, "rev-list", "--count", f"{baseline}..{final}"), "1")
        self.assertEqual(store.finalize(result_relative, graph_relative, final)["state"], "accepted")
        report = store.completion_report()
        self.assertEqual(report["status"], "accepted")
        self.assertEqual(report["final_commit"], final)
        for name in ("first.txt", "second.txt"):
            self.assertEqual(git(repo, "show", f"{final}:{name}"), "after")
        self.assertEqual(git(repo, "show", f"{final}:outside.txt"), "before")

    def test_second_task_cannot_modify_first_task_path_declared_or_omitted(self):
        for paths in (["second.txt"], ["first.txt", "second.txt"]):
            with self.subTest(paths=paths):
                repo, store, baseline = self.fixture()
                self.first_task(repo, store, baseline)
                self.lease(repo, store, "T-2")
                # Reverting T-1 to HEAD still changes T-1's completed work.
                (repo / "first.txt").write_text("before\n")
                (repo / "second.txt").write_text("after\n")
                self.assert_rejected_without_mutation(
                    repo, store,
                    lambda: store.submit_agent_result(self.result(store, baseline, "T-2", paths)),
                )

    def test_second_task_cannot_hide_staged_change_by_restoring_worktree(self):
        repo, store, baseline = self.fixture()
        self.first_task(repo, store, baseline, staged=True)
        self.lease(repo, store, "T-2")
        (repo / "first.txt").write_text("unauthorized staged change\n")
        git(repo, "add", "first.txt")
        (repo / "first.txt").write_text("after\n")
        (repo / "second.txt").write_text("after\n")
        self.assert_rejected_without_mutation(
            repo, store,
            lambda: store.submit_agent_result(self.result(store, baseline, "T-2", ["second.txt"])),
        )

    def test_interrupted_task_handoff_retains_original_scope_and_snapshots(self):
        for outside in (False, True):
            with self.subTest(outside=outside):
                repo, store, baseline = self.fixture()
                self.lease(repo, store, "T-1")
                original = store.load()["tasks"]["T-1"]["maintenance_start_tree"]
                (repo / "first.txt").write_text("after\n")
                git(repo, "add", "first.txt")
                store.update_task("T-1", "blocked", "worker")
                store.update_task("T-1", "pending", "worker")
                if outside:
                    (repo / "second.txt").write_text("unowned change\n")
                    self.assert_rejected_without_mutation(
                        repo, store, lambda: store.update_task("T-1", "leased", "replacement"),
                        "task path responsibility",
                    )
                    continue
                store.update_task("T-1", "leased", "replacement")
                store.update_task("T-1", "running", "replacement")
                self.assertEqual(store.load()["tasks"]["T-1"]["maintenance_start_tree"], original)
                result = self.result(store, baseline, "T-1", ["first.txt"])
                result["agent_id"] = "replacement"
                store.submit_agent_result(result)

    def test_first_lease_cannot_hide_unclaimed_approved_content(self):
        repo, store, baseline = self.fixture()
        (repo / "first.txt").write_text("before any lease\n")
        self.assert_rejected_without_mutation(
            repo, store, lambda: self.lease(repo, store, "T-1"), "before lease",
        )

    def test_second_task_cannot_hide_unapproved_change_already_present_at_lease(self):
        repo, store, baseline = self.fixture()
        self.first_task(repo, store, baseline)
        (repo / "outside.txt").write_text("unapproved preexisting change\n")
        # Either reject the lease itself, or the subsequent Result. The complete
        # Package scope must still be checked alongside the task's own delta.
        index = (repo / ".git/index").read_bytes()
        events = store.events_path.read_bytes()
        try:
            self.lease(repo, store, "T-2")
        except CogitoError:
            self.assertEqual((repo / ".git/index").read_bytes(), index)
            self.assertEqual(store.events_path.read_bytes(), events)
            return
        (repo / "second.txt").write_text("after\n")
        self.assert_rejected_without_mutation(
            repo, store,
            lambda: store.submit_agent_result(self.result(store, baseline, "T-2", ["second.txt"])),
        )

    def test_legacy_lease_without_start_snapshot_fails_closed(self):
        for missing in ("maintenance_start_tree", "maintenance_start_index_tree"):
            with self.subTest(missing=missing):
                repo, store, baseline = self.fixture()
                self.first_task(repo, store, baseline)
                self.lease(repo, store, "T-2")
                events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
                previous = "0" * 64
                for event in events:
                    if event["type"] == "task-updated" and event["payload"].get("task_id") == "T-2":
                        event["payload"].pop(missing, None)
                    event.pop("event_hash")
                    event["previous_event_hash"] = previous
                    previous = hash_json(event)
                    event["event_hash"] = previous
                store.events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
                store = RunStore(repo, store.run_id)
                self.assertEqual(store.load()["tasks"]["T-2"]["status"], "running")
                self.assertNotIn(missing, store.load()["tasks"]["T-2"])
                (repo / "second.txt").write_text("after\n")
                self.assert_rejected_without_mutation(
                    repo, store,
                    lambda: store.submit_agent_result(self.result(store, baseline, "T-2", ["second.txt"])),
                    "snapshot|lease",
                )

    def remove_legacy_snapshots(self, store, task):
        events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
        previous = "0" * 64
        for event in events:
            if event["type"] == "task-updated" and event["payload"].get("task_id") == task:
                event["payload"].pop("maintenance_start_tree", None)
                event["payload"].pop("maintenance_start_index_tree", None)
            event.pop("event_hash")
            event["previous_event_hash"] = previous
            previous = hash_json(event)
            event["event_hash"] = previous
        store.events_path.write_text("".join(json.dumps(event) + "\n" for event in events))
        return RunStore(store.root, store.run_id)

    def test_legacy_single_task_without_snapshots_preserves_safe_result_submission(self):
        repo, store, baseline = self.fixture(single_task=True)
        self.lease(repo, store, "T-1")
        store = self.remove_legacy_snapshots(store, "T-1")
        (repo / "first.txt").write_text("after\n")
        before = (repo / ".git/index").read_bytes()
        store.submit_agent_result(self.result(store, baseline, "T-1", ["first.txt"]))
        self.assertEqual(store.load()["agent_results"][-1]["changed_paths"], ["first.txt"])
        self.assertEqual((repo / ".git/index").read_bytes(), before)

    def test_legacy_multitask_without_snapshots_cannot_omit_prior_changes(self):
        repo, store, baseline = self.fixture()
        self.first_task(repo, store, baseline)
        self.lease(repo, store, "T-2")
        store = self.remove_legacy_snapshots(store, "T-2")
        (repo / "second.txt").write_text("after\n")
        for paths in (["second.txt"], ["first.txt", "second.txt"]):
            with self.subTest(paths=paths):
                self.assert_rejected_without_mutation(
                    repo, store,
                    lambda: store.submit_agent_result(self.result(store, baseline, "T-2", paths)),
                )

    def test_independent_review_rejects_content_changed_after_verification(self):
        for changed_path in ("first.txt", "second.txt"):
            with self.subTest(changed_path=changed_path):
                repo, store, baseline = self.fixture()
                self.first_task(repo, store, baseline)
                self.lease(repo, store, "T-2")
                (repo / "second.txt").write_text("after\n")
                store.submit_agent_result(self.result(store, baseline, "T-2", ["second.txt"]))
                store.update_task("T-2", "complete", "worker")
                store.transition("implementation-complete", {})
                pre = corrections.MaintenanceCorrectionTests.check(store, repo, "pre")
                self.assertTrue(pre["passed"])
                store.complete_verification([pre])
                (repo / changed_path).write_text("unverified edit\n")
                result = self.result(store, baseline, "T-1", [])
                result.update(role="reviewer", agent_id="reviewer-T-1",
                              reviewed_implementer="worker", requested_transition="review-approved")
                self.assert_rejected_without_mutation(
                    repo, store, lambda: store.submit_agent_result(result),
                )
