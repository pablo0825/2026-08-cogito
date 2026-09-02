"""Original command identity, completed replay, and interrupted check execution."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from cogito_common import CogitoError
from cogito_events import append_event, read_events
from cogito_git import GitRepository
from cogito_run_store import RunStore
from cogito_test_support import GitTestCase, init_repo, package


class ActionReplayTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git = GitRepository(self.repo).run
        init_repo(self.repo)
        (self.repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
        (self.repo / "note.txt").write_text("before\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.head = self.git("rev-parse", "HEAD")
        self.counter = self.root / "executions.txt"
        self.draft = package("maintenance")
        self.draft.update({
            "baseline_commit": self.head, "approved_paths": ["note.txt"],
            "execution_dag": {"tasks": [{"id": "T-1", "paths": ["note.txt"]}], "edges": []},
            "checks": [{"id": "C-1", "argv": [sys.executable, "-c",
                "import pathlib,sys,time; pathlib.Path(sys.argv[1]).open('a').write('executed\\n'); time.sleep(.05)",
                str(self.counter)], "required": True}],
        })
        self.store = RunStore(self.repo, self.draft["run_id"])
        self.store.create("maintenance")
        self.store.prepare_package(self.draft, "prepare")
        self.store.approve_package(self.draft, "approve")
        self.store.start_gate("start")
        self.store.update_task("T-1", "leased", "worker", "lease")
        self.store.update_task("T-1", "running", "worker", "running")
        (self.repo / "note.txt").write_text("after\n")
        self.result = {
            "schema_version": "3.0", "run_id": self.store.run_id,
            "task_id": "T-1", "agent_id": "worker", "role": "implementer",
            "status": "complete", "base_commit": self.head, "head_commit": self.head,
            "changed_paths": ["note.txt"], "evidence": [], "risks": [], "requested_transition": "verifying",
        }
        self.store.submit_agent_result(self.result, "result")
        self.store.update_task("T-1", "complete", "worker", "complete")
        self.store.transition("implementation-complete", {}, "implemented")

    def evidence(self, action_id: str) -> dict:
        self.store.run_controlled_check("C-1", self.repo, action_id)
        event = next(item for item in read_events(self.store.events_path) if item["action_id"] == action_id)
        return json.loads(Path(event["payload"]["evidence_path"]).read_text())

    def assert_replay(self, operation, *args, **kwargs) -> None:
        before = self.store.events_path.read_bytes()
        expected = self.store.load()
        self.assertEqual(operation(*args, **kwargs), expected)
        self.assertEqual(self.store.events_path.read_bytes(), before)

    def assert_conflict(self, operation, *args, **kwargs) -> None:
        before = self.store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "different content"):
            operation(*args, **kwargs)
        self.assertEqual(self.store.events_path.read_bytes(), before)

    def test_completed_commands_replay_after_state_has_advanced(self) -> None:
        for method, args in (
            (self.store.prepare_package, (self.draft, "prepare")),
            (self.store.approve_package, (self.draft, "approve")),
            (self.store.start_gate, ("start",)),
            (self.store.update_task, ("T-1", "leased", "worker", "lease")),
            (self.store.submit_agent_result, (self.result, "result")),
            (self.store.transition, ("implementation-complete", {}, "implemented")),
        ):
            with self.subTest(command=method.__name__):
                self.assert_replay(method, *args)
        changed = {**self.draft, "description": "different request"}
        self.assert_conflict(self.store.prepare_package, changed, "prepare")
        self.assert_conflict(self.store.approve_package, changed, "approve")
        self.assert_conflict(self.store.update_task, "T-1", "leased", "another-worker", "lease")
        self.assert_conflict(self.store.submit_agent_result, {**self.result, "risks": ["new"]}, "result")
        self.assert_conflict(self.store.transition, "implementation-complete", {"tasks_complete": True}, "implemented")

    def test_check_and_remaining_delivery_commands_bind_every_input(self) -> None:
        pre = self.evidence("check-pre")
        self.assert_replay(self.store.run_controlled_check, "C-1", str(self.repo), "check-pre")
        self.assert_conflict(self.store.run_controlled_check, "DOES-NOT-EXIST", self.repo, "check-pre")
        self.assert_conflict(self.store.run_controlled_check, "C-1", self.root / "missing", "check-pre")
        self.assertEqual(self.counter.read_text().splitlines(), ["executed"])
        self.store.complete_verification([pre], "verify")
        self.assert_replay(self.store.complete_verification, [pre], "verify")
        changed = {**pre, "stdout": "different evidence with the same path"}
        self.assert_conflict(self.store.complete_verification, [changed], "verify")
        self.store.transition("review-approved", {"review_exemption": True}, "review")
        self.assert_replay(self.store.transition, "review-approved", {"review_exemption": True}, "review")
        self.store.complete_integration(self.head, None, "integrate")
        self.assert_replay(self.store.complete_integration, self.head, None, "integrate")
        self.assert_conflict(self.store.complete_integration, "f" * 40, None, "integrate")
        self.assert_conflict(self.store.complete_integration, self.head, "other-slice", "integrate")
        post = self.evidence("check-post")
        self.store.decide_post_verification([post], False, "post")
        self.assert_replay(self.store.decide_post_verification, [post], False, "post")
        self.assert_conflict(self.store.decide_post_verification, [post], True, "post")
        self.assert_conflict(self.store.decide_post_verification, [{**post, "stdout": "changed"}], False, "post")

        graph_path = self.repo / "docs/cogito/project-graph.json"
        graph = json.loads(graph_path.read_text())
        graph["active_run_id"] = None
        graph_path.write_text(json.dumps(graph))
        result_rel = f"docs/cogito/results/{self.store.run_id}.json"
        result_path = self.repo / result_rel
        result_path.parent.mkdir(parents=True)
        result_path.write_text(json.dumps({
            "schema_version": "3.0", "run_id": self.store.run_id, "status": "accepted",
            "package_hash": self.store.load()["package_hash"],
            "effective_contract_hash": self.store.load()["effective_contract_hash"],
            "integration_commits": [self.head], "slice_dispositions": {},
            "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
            "reviews": [], "amendments": [], "remaining_risks": [],
            "human_gate": {"required": False, "outcome": "not-required"},
        }))
        self.git("add", "--all")
        self.git("commit", "-qm", "finalize")
        final = self.git("rev-parse", "HEAD")
        graph_rel = "docs/cogito/project-graph.json"
        self.store.finalize(result_rel, graph_rel, final, "finalize")
        self.assert_replay(self.store.finalize, result_rel, graph_rel, final, "finalize")
        for args in (("other.json", graph_rel, final), (result_rel, "other.json", final), (result_rel, graph_rel, self.head)):
            self.assert_conflict(self.store.finalize, *args, "finalize")

    def test_other_commands_cannot_reuse_a_completed_action_id(self) -> None:
        for operation, args in (
            (self.store.enter_correction, ()),
            (self.store.complete_correction, ("TA-1", self.head)),
            (self.store.enter_review_fix, ()),
            (self.store.complete_review_fix, ("TA-1", self.head)),
            (self.store.add_amendment, ({"id": "TA-1", "reason": "new"},)),
            (self.store.record_retry, ("transient", "retry")),
            (self.store.resume_gate, ()),
            (self.store.approve_human_gate, ()),
        ):
            with self.subTest(command=operation.__name__):
                self.assert_conflict(operation, *args, action_id="implemented")

    def test_review_event_uses_gate_decision_and_preserves_the_original_request(self) -> None:
        pre = self.evidence("check")
        self.store.complete_verification([pre], "verify")
        forged = {"approved": True, "independent": True, "reviews": ["T-1"]}
        before = self.store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "independent Reviewer Result"):
            self.store.transition("review-approved", forged, "review")
        self.assertEqual(self.store.events_path.read_bytes(), before)
        self.assertEqual(forged, {"approved": True, "independent": True, "reviews": ["T-1"]})

        request = {"review_exemption": True, "approved": False, "independent": True,
                   "reviews": ["unrecorded-task"], "note": {"reason": "low risk"}}
        original = copy.deepcopy(request)
        state = self.store.transition("review-approved", request, "review")
        self.assertEqual(state["tasks"]["T-1"]["status"], "reviewed")
        event = read_events(self.store.events_path)[-1]
        self.assertEqual(event["payload"], {
            **original, "reviews": ["T-1"], "approved": True, "independent": False,
        })
        self.assertEqual(request, original)
        self.assert_replay(self.store.transition, "review-approved", request, "review")
        self.assert_conflict(self.store.transition, "review-approved", event["payload"], "review")

    def test_amendment_and_correction_replay_bind_their_original_arguments(self) -> None:
        amendment = {"id": "TA-1", "reason": "fix", "path_fixes": ["note.txt"]}
        self.store.add_amendment(amendment, "amend")
        self.assert_replay(self.store.add_amendment, amendment, "amend")
        self.assert_conflict(self.store.add_amendment, {**amendment, "reason": "changed"}, "amend")
        self.store.enter_correction("correct")
        self.assert_replay(self.store.enter_correction, "correct")
        commit = self.head
        self.store.complete_correction("TA-1", commit, "corrected")
        self.assert_replay(self.store.complete_correction, "TA-1", commit, "corrected")
        self.assert_conflict(self.store.complete_correction, "TA-other", commit, "corrected")
        self.assert_conflict(self.store.complete_correction, "TA-1", "f" * 40, "corrected")

    def test_correction_without_tasks_still_requires_trailer_and_current_head(self) -> None:
        # Documentation retains committed corrections; Maintenance now uses
        # uncommitted snapshots and puts its trailers on the final commit.
        repo = self.root / "documentation"
        repo.mkdir()
        init_repo(repo)
        git = GitRepository(repo).run
        (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
        (repo / "note.txt").write_text("before\n")
        git("add", ".")
        git("commit", "-qm", "baseline")
        base = git("rev-parse", "HEAD")
        draft = package("documentation")
        draft.update({"baseline_commit": base, "approved_paths": ["note.txt"],
                      "execution_dag": {"tasks": [{"id": "T-1", "paths": ["note.txt"]}], "edges": []}})
        store = RunStore(repo, draft["run_id"])
        store.create("documentation")
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        store.update_task("T-1", "leased", "worker")
        store.update_task("T-1", "running", "worker")
        (repo / "note.txt").write_text("after\n")
        git("add", "note.txt")
        git("commit", "-qm", "implementation")
        store.submit_agent_result({**self.result, "run_id": store.run_id,
                                   "base_commit": base, "head_commit": git("rev-parse", "HEAD")})
        store.update_task("T-1", "complete", "worker")
        store.transition("implementation-complete", {})
        store.add_amendment({"id": "TA-1", "reason": "fix", "path_fixes": ["note.txt"]})
        store.enter_correction()
        before = store.events_path.read_bytes()
        git("commit", "--allow-empty", "-qm", "missing trailer")
        commit = git("rev-parse", "HEAD")
        with self.assertRaisesRegex(CogitoError, "missing the Cogito-Amendment trailer"):
            store.complete_correction("TA-1", commit, "corrected")
        git("commit", "--allow-empty", "-qm", "fix\n\nCogito-Amendment: TA-1")
        old_head = git("rev-parse", "HEAD")
        git("commit", "--allow-empty", "-qm", "new delivery head")
        with self.assertRaisesRegex(CogitoError, "must use current delivery HEAD"):
            store.complete_correction("TA-1", old_head, "corrected")
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_invalid_amendment_dependencies_do_not_append_events(self) -> None:
        def added(task_id, dependencies):
            return {"id": task_id, "slice_id": "mini-package", "paths": ["note.txt"], "depends_on": dependencies}

        before = self.store.events_path.read_bytes()
        for tasks in ([added("T-2", ["missing"])], [added("T-2", ["T-2"])],
                      [added("T-2", ["T-3"]), added("T-3", ["T-2"])]):
            with self.subTest(tasks=tasks), self.assertRaises(CogitoError):
                self.store.add_amendment({"id": "TA-1", "reason": "fix", "added_tasks": tasks}, "amend")
            self.assertEqual(self.store.events_path.read_bytes(), before)
        # A rejected request did not consume this ID; a valid dependency can run.
        self.store.add_amendment({"id": "TA-1", "reason": "fix", "added_tasks": [added("T-2", ["T-1"])]}, "amend")
        self.store.enter_correction("correct")
        state = self.store.update_task("T-2", "leased", "worker", "lease-fix")
        self.assertEqual(state["tasks"]["T-2"]["status"], "leased")

    def test_review_fix_replay_binds_amendment_and_commit(self) -> None:
        pre = self.evidence("check")
        self.store.complete_verification([pre], "verify")
        finding = {**self.result, "role": "reviewer", "agent_id": "reviewer",
                   "reviewed_implementer": "worker", "status": "needs-fix",
                   "changed_paths": [], "requested_transition": "review-fix"}
        self.store.submit_agent_result(finding, "finding")
        self.store.enter_review_fix("fix-start")
        self.assert_replay(self.store.enter_review_fix, "fix-start")
        self.store.add_amendment({"id": "TA-1", "reason": "review finding", "added_tasks": [
            {"id": "T-2", "slice_id": "mini-package", "paths": ["note.txt"], "depends_on": ["T-1"]},
        ]}, "amend")
        self.store.update_task("T-2", "leased", "worker", "lease-fix")
        self.store.update_task("T-2", "running", "worker", "run-fix")
        (self.repo / "note.txt").write_text("review fix\n")
        commit = self.head
        self.store.submit_agent_result({**self.result, "task_id": "T-2", "head_commit": commit}, "fix-result")
        self.store.update_task("T-2", "complete", "worker", "fix-complete")
        self.store.complete_review_fix("TA-1", commit, "fixed")
        self.assert_replay(self.store.complete_review_fix, "TA-1", commit, "fixed")
        self.assert_conflict(self.store.complete_review_fix, "TA-other", commit, "fixed")
        self.assert_conflict(self.store.complete_review_fix, "TA-1", "f" * 40, "fixed")

    def test_retry_and_resume_do_not_repeat_their_events(self) -> None:
        self.store.record_retry("transient", "interruption", "retry")
        self.assert_replay(self.store.record_retry, "transient", "interruption", "retry")
        self.assert_conflict(self.store.record_retry, "format", "interruption", "retry")
        self.assert_conflict(self.store.record_retry, "transient", "different", "retry")
        self.assertEqual(self.store.load()["counters"]["transient_retries"], 1)
        self.store.transition("block", {"reason": "interruption"}, "block")
        self.store.resume_gate("resume")
        self.assert_replay(self.store.resume_gate, "resume")

    def test_event_append_failure_recovers_published_evidence_without_running_again(self) -> None:
        with mock.patch("cogito_event_repository.append_event", side_effect=OSError("injected append failure")):
            with self.assertRaises(OSError):
                self.evidence("interrupted")
        self.assert_conflict(self.store.run_controlled_check, "OTHER", self.repo, "interrupted")
        self.assert_conflict(self.store.run_controlled_check, "C-1", self.root / "other", "interrupted")
        self.evidence("interrupted")
        self.assertEqual(self.counter.read_text().splitlines(), ["executed"])
        self.assertEqual(sum(e["action_id"] == "interrupted" for e in read_events(self.store.events_path)), 1)

    def test_failure_after_event_append_replays_without_executing_again(self) -> None:
        def append_then_fail(*args, **kwargs):
            append_event(*args, **kwargs)
            raise OSError("injected failure after append")
        with mock.patch("cogito_event_repository.append_event", side_effect=append_then_fail):
            with self.assertRaises(OSError):
                self.evidence("recorded")
        self.evidence("recorded")
        self.assertEqual(self.counter.read_text().splitlines(), ["executed"])

    def test_unknown_process_outcome_is_not_automatically_reexecuted(self) -> None:
        import cogito_runner
        run_check = cogito_runner.run_check
        def run_then_fail(*args, **kwargs):
            run_check(*args, **kwargs)
            raise OSError("process completed but evidence was not published")
        with mock.patch("cogito_runner.run_check", side_effect=run_then_fail):
            with self.assertRaises(OSError):
                self.evidence("unknown")
        with self.assertRaisesRegex(CogitoError, "outcome is unknown"):
            self.evidence("unknown")
        self.assert_conflict(self.store.record_retry, "transient", "different command", "unknown")
        self.assertEqual(self.counter.read_text().splitlines(), ["executed"])

    def test_simultaneous_retries_execute_a_check_only_once(self) -> None:
        barrier = threading.Barrier(2)
        def invoke():
            store = RunStore(self.repo, self.store.run_id)
            barrier.wait(timeout=5)
            return store.run_controlled_check("C-1", self.repo, "concurrent")
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(invoke) for _ in range(2)]
            results = [future.result(timeout=15) for future in futures]
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.counter.read_text().splitlines(), ["executed"])
        self.assertEqual(sum(e["action_id"] == "concurrent" for e in read_events(self.store.events_path)), 1)

    def test_legacy_history_remains_readable_but_is_not_guessed_on_replay(self) -> None:
        append_event(self.store.events_path, {"type": "block", "payload": {"reason": "legacy"}, "action_id": "legacy"})
        before = self.store.events_path.read_bytes()
        self.assertEqual(self.store.load()["state"], "blocked")
        with self.assertRaisesRegex(CogitoError, "no request fingerprint"):
            self.store.transition("block", {"reason": "legacy"}, "legacy")
        self.assertEqual(self.store.events_path.read_bytes(), before)

    def test_json_boolean_and_number_are_different_requests(self) -> None:
        self.store.transition("block", {"reason": "test", "detail": True}, "typed")
        self.assert_conflict(self.store.transition, "block", {"reason": "test", "detail": 1}, "typed")

    def test_uninitialized_check_does_not_prevent_initializing_the_run(self) -> None:
        store = RunStore(self.repo, "DEV-not-initialized")
        with self.assertRaisesRegex(CogitoError, "must be initialized"):
            store.run_controlled_check("C-1", self.repo, "too-early")
        self.assertFalse(store.run_dir.exists())
        self.assertEqual(store.create("maintenance")["state"], "preparing")


class EventReplayTests(unittest.TestCase):
    def test_append_deduplicates_exact_request_even_with_stale_cas(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            event = {"type": "test", "payload": {"derived": True}, "action_id": "same", "request_hash": "a" * 64}
            first = append_event(path, event, "0" * 64)
            before = path.read_bytes()
            self.assertEqual(append_event(path, event, "0" * 64), first)
            for changed in ({**event, "request_hash": "b" * 64}, {**event, "payload": {"derived": 1}}):
                with self.assertRaisesRegex(CogitoError, "different content"):
                    append_event(path, changed)
            legacy_caller = copy.deepcopy(event)
            del legacy_caller["request_hash"]
            with self.assertRaisesRegex(CogitoError, "without its request fingerprint"):
                append_event(path, legacy_caller)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
