"""Pure projection of append-only run events into current state."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from cogito_common import CogitoError
from cogito_workflow import load_workflow, validate_transition


def _required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


def reduce_events(events: Iterable[Mapping[str, Any]], workflow: Mapping[str, Any] | None = None) -> dict[str, Any]:
    workflow = workflow or load_workflow()
    projection: dict[str, Any] | None = None
    for item in events:
        event_type = item.get("type")
        payload = item.get("payload", {})
        if event_type == "run-created":
            if projection is not None or not _required(payload, "run_id", "kind"):
                raise CogitoError("run-created must be the first, complete event")
            if payload["kind"] not in {"feature", "change", "correction", "maintenance", "documentation"}:
                raise CogitoError("invalid run kind")
            projection = {
                "schema_version": "3.0", "run_id": payload["run_id"], "kind": payload["kind"],
                "state": workflow["initial_state"], "sequence": item.get("sequence", 1),
                "last_event_hash": item.get("event_hash"), "counters": {}, "tasks": {},
                "agent_results": [], "evidence": {},
                "package_path": None, "package_hash": None, "effective_contract_hash": None,
                "blocked_from": None, "max_workers": int(workflow["limits"]["max_workers"]),
                "candidate_package_hash": None, "project_graph_hash": None,
                "shared_understanding_hash": None, "boundary": None,
                "limits": dict(workflow["limits"]),
            }
            continue
        if projection is None:
            raise CogitoError("event log must begin with run-created")
        if event_type == "task-updated":
            _apply_task_update(projection, payload)
        elif event_type == "agent-result-recorded":
            result = payload.get("result")
            if not isinstance(result, dict):
                raise CogitoError("agent-result-recorded requires a structured result")
            projection["agent_results"].append(result)
        elif event_type == "check-evidence-recorded":
            if not _required(payload, "check_id", "evidence_path", "evidence_hash"):
                raise CogitoError("check-evidence-recorded is incomplete")
            projection["evidence"][payload["evidence_path"]] = {**dict(payload), "event_sequence": item.get("sequence")}
        elif event_type == "technical-amendment-added":
            if projection.get("package_hash") is None or projection["state"] in workflow["terminal_states"]:
                raise CogitoError("amendments require an approved package on an active run")
            projection.setdefault("amendments", []).append(dict(payload))
            projection["effective_contract_hash"] = payload.get("effective_contract_hash")
            for task in payload.get("amendment", {}).get("added_tasks", []):
                if task["id"] in projection["tasks"]:
                    raise CogitoError("amendment task id already exists in run state")
                projection["tasks"][task["id"]] = {**dict(task), "status": "pending"}
        elif event_type in {"transient-retry", "format-repair-recorded"}:
            counter = "transient_retries" if event_type == "transient-retry" else "format_repairs"
            limit = int(projection["limits"][counter])
            if projection["state"] in workflow["terminal_states"] or projection["counters"].get(counter, 0) >= limit:
                raise CogitoError(f"retry limit exhausted: {counter}")
            if not _required(payload, "reason"):
                raise CogitoError(f"{event_type} requires a reason")
            projection["counters"][counter] = projection["counters"].get(counter, 0) + 1
        elif event_type == "resume":
            if projection["state"] != "blocked":
                raise CogitoError("only blocked runs may resume")
            target = payload.get("target")
            if target not in workflow.get("resume_targets", []):
                raise CogitoError("illegal resume target")
            if payload.get("validated") is not True:
                raise CogitoError("resume-gate validation is required")
            projection["state"] = target
            projection["blocked_from"] = None
        else:
            _apply_transition(projection, workflow, str(event_type), payload)
        projection["sequence"] = item.get("sequence", projection["sequence"] + 1)
        projection["last_event_hash"] = item.get("event_hash")
    if projection is None:
        raise CogitoError("event log is empty")
    return projection


def _apply_task_update(projection: dict[str, Any], payload: Mapping[str, Any]) -> None:
    if not _required(payload, "task_id", "status", "agent_id"):
        raise CogitoError("task-updated requires task_id, status and agent_id")
    task_id = payload["task_id"]
    if task_id not in projection["tasks"]:
        raise CogitoError("task-updated references a task outside the effective Package")
    before = projection["tasks"][task_id].get("status", "pending")
    allowed_status = {
        "pending": {"leased", "blocked"}, "leased": {"running", "blocked"},
        "running": {"complete", "blocked"}, "blocked": {"pending"},
        "complete": set(), "verified": set(), "reviewed": set(), "integrated": set(),
    }
    if payload["status"] not in allowed_status.get(before, set()):
        raise CogitoError(f"illegal task status transition: {before} -> {payload['status']}")
    prior_agent = projection["tasks"][task_id].get("agent_id")
    if payload["status"] != "pending" and prior_agent and prior_agent != payload["agent_id"]:
        raise CogitoError("task lease belongs to a different agent")
    if before == "pending":
        for dependency in projection["tasks"][task_id].get("depends_on", []):
            predecessor = projection["tasks"].get(dependency, {})
            same_slice = (predecessor.get("slice_id") or "mini-package") == (projection["tasks"][task_id].get("slice_id") or "mini-package")
            allowed = {"complete", "verified", "reviewed", "integrated"} if same_slice else {"integrated"}
            if predecessor.get("status") not in allowed:
                raise CogitoError("cross-Slice dependencies must be integrated before dispatch")
    updated = dict(projection["tasks"][task_id])
    updated.update(payload)
    if payload["status"] == "pending":
        updated["released_by"] = payload["agent_id"]
        updated.pop("agent_id", None)
    projection["tasks"][task_id] = updated
    active_slices = {item.get("slice_id") or "mini-package" for item in projection["tasks"].values() if item.get("status") in {"leased", "running"}}
    if len(active_slices) > int(projection["max_workers"]):
        raise CogitoError("worker lease limit exceeded")
    if payload["status"] == "leased" and any(
        key != task_id
        and (item.get("slice_id") or "mini-package") == (projection["tasks"][task_id].get("slice_id") or "mini-package")
        and item.get("status") in {"leased", "running"}
        for key, item in projection["tasks"].items()
    ):
        raise CogitoError("a Slice may have only one active worker lease")


def _apply_transition(projection: dict[str, Any], workflow: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]) -> None:
    transition = validate_transition(workflow, projection["state"], event_type, payload, projection["counters"], projection["limits"])
    # Further findings belong to the same blocked interval. Its resume target
    # remains the state that preceded the first block, including during replay.
    if transition["to"] == "blocked" and projection["state"] != "blocked":
        projection["blocked_from"] = projection["state"]
    projection["state"] = transition["to"]
    if transition.get("counter"):
        key = transition["counter"]
        projection["counters"][key] = projection["counters"].get(key, 0) + 1
    if event_type == "package-approved":
        projection["package_path"] = payload["package_path"]
        projection["package_hash"] = payload["package_hash"]
        projection["effective_contract_hash"] = payload["package_hash"]
        projection["max_workers"] = int(payload["max_workers"])
        projection["project_graph_hash"] = payload["project_graph_hash"]
        projection["limits"].update(payload["limits"])
        projection["tasks"] = {item["id"]: {**dict(item), "status": "pending"} for item in payload.get("tasks", [])}
    elif event_type in {"package-ready", "mini-package-ready"}:
        projection["candidate_package_hash"] = payload.get("candidate_package_hash")
    elif event_type == "shared-understanding-ready":
        projection["shared_understanding_hash"] = payload.get("shared_understanding_hash")
    elif event_type == "boundary-complete":
        projection["boundary"] = dict(payload)
    elif event_type == "verification-passed":
        for task in projection["tasks"].values():
            if task.get("status") == "complete":
                task["status"] = "verified"
    elif event_type == "review-approved":
        for task_id in payload.get("reviews", []):
            if projection["tasks"].get(task_id, {}).get("status") == "verified":
                projection["tasks"][task_id]["status"] = "reviewed"
    elif event_type in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}:
        for task_id in payload.get("task_ids", []):
            if projection["tasks"].get(task_id, {}).get("status") == "reviewed":
                projection["tasks"][task_id]["status"] = "integrated"
