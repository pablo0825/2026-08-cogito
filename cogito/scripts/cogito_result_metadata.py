"""Narrow, append-only recovery for accepted atomic Result transition hints."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, cast

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, load_json
from cogito_contracts import materialize_contract_with_limits, path_allowed, validate_agent_result
from cogito_event_repository import EventSnapshot
from cogito_evidence_binding import capture_index_and_worktree_trees, working_tree_changed_paths
from cogito_execution_registry import quiescent_guard
from cogito_replan_lock import run_mutation
from cogito_task_rules import is_active_task

if TYPE_CHECKING:
    from cogito_run_store import RunStore

EVENT = "agent-result-metadata-corrected"


def validate_correction(original: Mapping[str, Any], corrected: Mapping[str, Any]) -> None:
    if (original.get("role") != "implementer" or original.get("status") != "complete"
            or original.get("requested_transition") != "executing"):
        raise CogitoError("only completed Implementer executing hints can be corrected")
    if dict(corrected) != {**original, "requested_transition": "verifying"}:
        raise CogitoError("Result correction may change only requested_transition to verifying")


def require_recovery_state(state: Mapping[str, Any]) -> None:
    if state.get("state") != "blocked" or state.get("blocked_from") != "executing":
        raise CogitoError("Result metadata recovery requires a run blocked from executing")
    if state.get("human", {}).get("escalated"):
        raise CogitoError("Result metadata recovery cannot clear a human escalation")
    if any(is_active_task(task) for task in state["tasks"].values()):
        raise CogitoError("Result metadata recovery requires no active tasks")


class ResultMetadataMixin:
    @run_mutation
    def correct_result_metadata(self, request: Mapping[str, Any], action_id: str):
        store = cast("RunStore", self)
        if (set(request) != {"original_event_sequence", "original_event_hash", "result"}
                or type(request["original_event_sequence"]) is not int
                or not isinstance(request["original_event_hash"], str)
                or not isinstance(request["result"], dict) or not action_id):
            raise CogitoError("Result metadata correction requires an exact event reference and Result")
        fingerprint = request_fingerprint("correct-result-metadata", request=request)
        replay = store._replay(action_id, EVENT, fingerprint)
        if replay is not None:
            return replay
        snapshot = store._events.snapshot()
        require_recovery_state(snapshot.state)
        from cogito_projection import project_events
        matches = [(index, event) for index, event in enumerate(snapshot.events)
                   if event.get("sequence") == request["original_event_sequence"]
                   and event.get("event_hash") == request["original_event_hash"]]
        if len(matches) != 1 or matches[0][1]["type"] != "agent-result-recorded":
            raise CogitoError("Result metadata correction does not reference an accepted Result event")
        index, event = matches[0]
        original = event["payload"]["result"]
        task_results = [item for item in snapshot.events if item["type"] == "agent-result-recorded"
                        and item["payload"]["result"].get("task_id") == original.get("task_id")
                        and item["payload"]["result"].get("role") == "implementer"]
        if not task_results or task_results[-1]["event_hash"] != event["event_hash"]:
            raise CogitoError("Result metadata correction cannot revive a superseded Task Result")
        validate_correction(original, request["result"])
        if any(item["original_event_sequence"] == event["sequence"]
               for item in snapshot.state.get("result_metadata_corrections", [])):
            raise CogitoError("Result metadata was already corrected; replay its original action id")
        history = snapshot.events[:index]
        historical = EventSnapshot(history, project_events(history, store.workflow))
        package = store._approved_package_from_state(historical.state)
        effective = materialize_contract_with_limits(package,
            [item["payload"]["amendment"] for item in history if item["type"] == "technical-amendment-added"],
            store.workflow["limits"])
        if package.get("task_delivery") != "atomic" or historical.state["state"] != "executing":
            raise CogitoError("Result metadata recovery supports only accepted atomic execution Results")
        validate_agent_result(request["result"], package, workflow_limits=store.workflow["limits"],
                              approved_paths=effective['approved_paths'])
        task = historical.state["tasks"].get(original["task_id"])
        definition = next((item for item in effective["execution_dag"]["tasks"]
                           if item["id"] == original["task_id"]), None)
        if not task or not definition or any(task.get(key) != definition.get(key) for key in ("paths", "check_ids")):
            raise CogitoError("historical Task does not match its effective contract")
        current_task = snapshot.state["tasks"].get(original["task_id"])
        if (not task or task.get("status") != "running" or not current_task
                or current_task.get("status") != "complete"
                or original["run_id"] != store.run_id or original["agent_id"] != task.get("agent_id")
                or original["base_commit"] != task.get("base_commit")
                or any(current_task.get(key) != task.get(key) for key in
                       ("agent_id", "base_commit", "branch", "worktree", "paths", "check_ids"))):
            raise CogitoError("Result metadata correction does not match its completed historical lease")
        if not any(item["type"] == "task-updated" and item["payload"].get("task_id") == original["task_id"]
                   and item["payload"].get("status") == "complete" for item in snapshot.events[index + 1:]):
            raise CogitoError("Result metadata correction requires recorded Task completion")
        with quiescent_guard(store.root, store.run_id, allow_external_receipts=True) as idle:
            if not idle:
                raise CogitoError("Result metadata recovery requires all executors to be quiescent")
            store._require_finished_check_attempts(snapshot)
            worktree = Path(task["worktree"])
            store._validate_historical_result(original, task, historical, package)
            completed = [item for item in snapshot.state["agent_results"]
                         if item["role"] == "implementer" and item["status"] == "complete"
                         and item['task_id'] in snapshot.state['tasks']
                         and snapshot.state["tasks"][item["task_id"]].get("worktree") == str(worktree)]
            if not completed:
                raise CogitoError("Result recovery has no completed checkout tip")
            latest = completed[-1]
            latest_task = snapshot.state["tasks"][latest["task_id"]]
            if (latest_task["status"] != "complete" or latest_task["branch"] != task["branch"]
                    or store._git_at(worktree, "branch", "--show-current") != task["branch"]
                    or store._git_at(worktree, "rev-parse", "HEAD") != latest["head_commit"]):
                raise CogitoError("Result recovery checkout must be on its last completed Task tip")
            store._git_at(worktree, "merge-base", "--is-ancestor", original["head_commit"], latest["head_commit"])
            tip_tree = store._git_at(worktree, "rev-parse", f"{latest['head_commit']}^{{tree}}")
            if (capture_index_and_worktree_trees(worktree) != (tip_tree, tip_tree)
                    or working_tree_changed_paths(worktree, latest["head_commit"])):
                raise CogitoError("Result recovery requires an unchanged checkout and index")
            # The final receipt binds the current checkout even when repairing an earlier Task.
            final_events = [(i, value) for i, value in enumerate(snapshot.events)
                            if value["type"] == "agent-result-recorded"
                            and value["payload"]["result"]["task_id"] == latest["task_id"]
                            and value["payload"]["result"]["role"] == "implementer"
                            and value["payload"]["result"]["status"] == "complete"]
            final_index, final_event = final_events[-1]
            final_history = snapshot.events[:final_index]
            final_snapshot = EventSnapshot(final_history, project_events(final_history, store.workflow))
            store._validate_historical_result(final_event["payload"]["result"], latest_task,
                final_snapshot, store._approved_package_from_state(final_snapshot.state))
            return store.record(EVENT, dict(request), action_id, store._GATE_AUTHORITY,
                               request_hash=fingerprint, expected_previous_hash=snapshot.state["last_event_hash"])

    def _validate_historical_result(self, result, task, snapshot, package):
        store = cast("RunStore", self)
        worktree = Path(task["worktree"])
        base, head = result["base_commit"], result["head_commit"]
        if (base != task["base_commit"] or result["agent_id"] != task["agent_id"]
                or store._git_at(worktree, "rev-list", "--parents", "-n", "1", head).split()[1:] != [base]):
            raise CogitoError("historical atomic Result must retain its identity and single parent")
        actual = set(filter(None, store._git_at(worktree, "diff", "--name-only", "--no-renames",
                         "--no-ext-diff", "-z", base, head, "--").split("\0")))
        if (not actual or actual != set(result["changed_paths"])
                or any(not path_allowed(path, task["paths"]) for path in actual)):
            raise CogitoError("historical Result paths do not match its atomic commit")
        evidence = [load_json(Path(path)) for path in result["evidence"]]
        store._validate_evidence(package, evidence, snapshot=snapshot, phase="task", task_id=result["task_id"])
        tree = store._git_at(worktree, "rev-parse", f"{head}^{{tree}}")
        if any(item["head_commit"] not in {base, head}
               or item["worktree_binding"].get("content_tree") != tree for item in evidence):
            raise CogitoError("historical evidence does not match the atomic commit tree")

    def _require_finished_check_attempts(self, snapshot):
        store = cast("RunStore", self)
        completed = {event.get("request_hash") for event in snapshot.events
                     if event["type"] == "check-evidence-recorded"}
        for path in (store.run_dir / "check-actions").glob("*/started.json"):
            if load_json(path).get("request_hash") not in completed:
                raise CogitoError("Result recovery cannot proceed with an unknown check outcome")
