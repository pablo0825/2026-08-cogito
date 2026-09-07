"""Pure event projection, with a convenience wrapper that loads the workflow."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, cast

from cogito_checkpoints import guard_checkpoint, project_checkpoint
from cogito_human_projection import HUMAN_EVENTS, project_human_metadata
from cogito_state_types import AgentResult, EvidenceLedgerEntry, RunState, TaskState
from cogito_event_types import (
    AgentResultRecordedPayload, CheckEvidenceRecordedPayload,
    IntegrationCompletedPayload, TaskUpdatedPayload,
)
from cogito_path_amendment_state import project_path_amendment, apply_path_projection, guard_pending
from cogito_common import CogitoError
from cogito_task_rules import dependency_satisfied, effective_slice_id, is_active_task
from cogito_workflow import load_workflow, validate_transition
from cogito_planning import project_planning, project_candidate, guard_preparation


def _required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


def reduce_events(events: Iterable[Mapping[str, Any]], workflow: Mapping[str, Any] | None = None) -> RunState:
    """Compatibility entry point; omitted/empty workflow loads the bundled file."""
    return project_events(events, workflow or load_workflow())


def project_events(events: Iterable[Mapping[str, Any]], workflow: Mapping[str, Any]) -> RunState:
    """Project recorded events using supplied workflow data, without file IO."""
    result_origins: dict[tuple[Any, Any], tuple[int, Mapping[str, Any]]] = {}
    projection: RunState | None = None
    history: list[Mapping[str, Any]] = []
    for item in events:
        history.append(item)
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
            if "task_delivery" in payload:
                if payload["task_delivery"] != "atomic" or payload["kind"] not in {"feature", "change", "correction"}:
                    raise CogitoError("invalid task delivery mode")
                projection["task_delivery"] = "atomic"
            if payload.get("stage_commits") is True:
                if not payload.get("checkpoint_head") or not payload.get("checkpoint_branch"):
                    raise CogitoError("stage commits require a Git baseline and branch")
                projection.update({"stage_commits": True, "checkpoint_head": payload["checkpoint_head"],
                                   "checkpoint_branch": payload["checkpoint_branch"],
                                   "checkpoints": [], "pending_checkpoint": None})
            continue
        if projection is None:
            raise CogitoError("event log must begin with run-created")
        if event_type == 'review-approved' and 'retention' in payload:
            from cogito_review_retention_rules import validate_recorded_retention
            validate_recorded_retention(history[:-1], projection, payload)
        guard_pending(projection, event_type, payload)
        guard_checkpoint(projection, event_type)
        guard_preparation(projection, event_type, payload)
        if project_path_amendment(projection, event_type, payload):
            pass
        elif event_type == "stage-committed":
            project_checkpoint(projection, item)
        elif project_planning(projection, event_type, payload):
            pass
        elif event_type in HUMAN_EVENTS:
            _apply_transition(projection, workflow, event_type, payload)
            project_human_metadata(projection, event_type, payload)
        elif event_type == "human-review-mandated":
            if not payload.get("replan_id") or not payload.get("source_run_id"):
                raise CogitoError("human review mandate requires RP lineage")
            projection["human_review_mandate"] = dict(payload)
        elif event_type == "disposition-resumed":
            if projection['state'] != 'blocked' or payload.get('validated') is not True or not payload.get('disposition_id'):
                raise CogitoError('disposition resumption requires a validated paused original run')
            if payload.get('target') not in workflow['resume_targets']:
                raise CogitoError('invalid disposition resumption target')
            projection['state'] = payload['target']
            projection['blocked_from'] = None
            projection['project_graph_hash'] = payload['project_graph_hash']
            projection['carryover_worktrees'] = payload['carryover_worktrees']
            if projection.get('human'):
                projection.setdefault('withdrawn_human_feedback', []).append(projection.pop('human'))
                projection['human_review_mandate'] = {'disposition_id': payload['disposition_id'], 'source_run_id': projection['run_id']}
            for task in projection['tasks'].values():
                if is_active_task(task):
                    task['status'] = 'pending'
                    task['released_by'] = payload['disposition_id']
        elif event_type == "run-superseded":
            if projection['state'] != 'blocked' or not _required(payload, 'replan_id', 'successor_run_id'):
                raise CogitoError('supersession requires a blocked source and explicit successor')
            projection['state'] = 'superseded'
            for task in projection['tasks'].values():
                if is_active_task(task): task['released_by'] = payload['replan_id']
        elif event_type == "work-carried":
            if projection['state'] != 'executing' or not payload.get('worktree') or not payload.get('binding'):
                raise CogitoError('invalid work carryover receipt')
            projection.setdefault('carryover_worktrees', {})[payload['worktree']] = payload['binding']
        elif event_type == "work-adopted":
            receipt = payload.get('receipt', {})
            target = receipt.get('target_task_id')
            if (projection['state'] != 'executing' or target not in projection['tasks']
                    or projection['tasks'][target]['status'] != 'pending'
                    or receipt.get('successor_run_id') != projection['run_id']
                    or not receipt.get('evidence') or not receipt.get('source_reviewers')):
                raise CogitoError('invalid work adoption receipt')
            adopted_task = projection['tasks'][target]
            adopted_task['status'] = 'reviewed'
            adopted_task['adoption'] = receipt
            adopted_task['worktree'] = payload['worktree']
        elif event_type == "adoption-ready":
            ids = payload.get('task_ids', [])
            missing_task: Mapping[str, Any] = {}
            if (projection['state'] != 'executing' or not ids
                    or any(projection['tasks'].get(t, missing_task).get('status')!='reviewed' for t in ids)):
                raise CogitoError('invalid adoption progression')
            projection['state'] = 'integrating'
        elif event_type == "task-updated":
            _apply_task_update(projection, payload)
        elif event_type == "agent-result-recorded":
            result = payload.get("result")
            if not isinstance(result, dict):
                raise CogitoError("agent-result-recorded requires a structured result")
            result_payload = cast(AgentResultRecordedPayload, payload)
            result_origins[(item.get("sequence"), item.get("event_hash"))] = (
                len(projection["agent_results"]), result_payload["result"],
            )
            projection["agent_results"].append(result_payload["result"])
            if result.get("role") == "implementer":
                result_task = projection["tasks"].get(result.get("task_id", ""))
                if result_task is not None:
                    if "maintenance_end_tree" in result_payload:
                        result_task["maintenance_end_tree"] = result_payload["maintenance_end_tree"]
                    if "maintenance_end_index_tree" in result_payload:
                        result_task["maintenance_end_index_tree"] = result_payload["maintenance_end_index_tree"]
        elif event_type == "agent-result-metadata-corrected":
            from cogito_result_metadata import require_recovery_state, validate_correction
            require_recovery_state(projection)
            if (set(payload) != {"original_event_sequence", "original_event_hash", "result"}
                    or type(payload['original_event_sequence']) is not int
                    or not isinstance(payload['original_event_hash'], str)
                    or not isinstance(payload['result'], dict)):
                raise CogitoError("invalid Result metadata correction payload")
            reference = (payload["original_event_sequence"], payload["original_event_hash"])
            if reference not in result_origins:
                raise CogitoError("Result metadata correction references an unknown original event")
            position, original = result_origins[reference]
            latest_position = max((i for i, result in enumerate(projection["agent_results"])
                                   if result.get("task_id") == original.get("task_id")
                                   and result.get("role") == "implementer"), default=-1)
            if position != latest_position:
                raise CogitoError("Result metadata correction cannot revive a superseded Task Result")
            validate_correction(original, payload["result"])
            corrected_task: Mapping[str, Any] = projection["tasks"].get(original["task_id"], {})
            if (projection.get("task_delivery") != "atomic" or corrected_task.get("status") != "complete"
                    or corrected_task.get("agent_id") != original["agent_id"]
                    or corrected_task.get("base_commit") != original["base_commit"]
                    or projection["agent_results"][position] != original):
                raise CogitoError("Result metadata correction requires an uncorrected completed atomic Result")
            projection["agent_results"][position] = cast(AgentResult, dict(payload["result"]))
            projection.setdefault("result_metadata_corrections", []).append(dict(payload))
        elif event_type == "check-evidence-recorded":
            if not _required(payload, "check_id", "evidence_path", "evidence_hash"):
                raise CogitoError("check-evidence-recorded is incomplete")
            evidence_payload = cast(CheckEvidenceRecordedPayload, payload)
            entry: EvidenceLedgerEntry = {
                **evidence_payload, "event_sequence": item.get("sequence"),
            }
            projection["evidence"][evidence_payload["evidence_path"]] = entry
        elif event_type == "technical-amendment-added":
            if projection.get("package_hash") is None or projection["state"] in workflow["terminal_states"]:
                raise CogitoError("amendments require an approved package on an active run")
            apply_path_projection(projection, payload)
            projection.setdefault("amendments", []).append(dict(payload))
            projection["effective_contract_hash"] = payload.get("effective_contract_hash")
            for task in payload.get("amendment", {}).get("added_tasks", []):
                if task["id"] in projection["tasks"]:
                    raise CogitoError("amendment task id already exists in run state")
                projection["tasks"][task["id"]] = cast(TaskState, {**dict(task), "status": "pending"})
        elif event_type == 'check-preparation-failed':
            from cogito_check_retry_rules import validate_failure
            validate_failure(projection, history[:-1], payload)
        elif event_type in {"transient-retry", "format-repair-recorded"}:
            if 'check_retry' in payload:
                from cogito_check_retry_rules import validate_link
                if event_type != 'transient-retry':
                    raise CogitoError('only transient retry may bind check attempts')
                validate_link(projection, history[:-1], payload['check_retry'])
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
        if event_type != "stage-committed":
            project_checkpoint(projection, item)
        projection["sequence"] = item.get("sequence", projection["sequence"] + 1)
        projection["last_event_hash"] = item.get("event_hash")
    if projection is None:
        raise CogitoError("event log is empty")
    return projection


def _apply_task_update(projection: RunState, payload: Mapping[str, Any]) -> None:
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
    task_payload = cast(TaskUpdatedPayload, payload)
    prior_agent = projection["tasks"][task_id].get("agent_id")
    if task_payload["status"] != "pending" and prior_agent and prior_agent != task_payload["agent_id"]:
        raise CogitoError("task lease belongs to a different agent")
    if before == "pending":
        for dependency in projection["tasks"][task_id].get("depends_on", []):
            predecessor: Mapping[str, Any] = projection["tasks"].get(dependency, {})
            if not dependency_satisfied(predecessor, projection["tasks"][task_id]):
                raise CogitoError("cross-Slice dependencies must be integrated before dispatch")
    updated = projection["tasks"][task_id].copy()
    updated.update(task_payload)
    if task_payload["status"] == "pending":
        updated["released_by"] = task_payload["agent_id"]
        updated.pop("agent_id", None)
        updated.pop("maintenance_end_tree", None)
        updated.pop("maintenance_end_index_tree", None)
    projection["tasks"][task_id] = updated
    active_slices = {
        effective_slice_id(item) for item in projection["tasks"].values()
        if is_active_task(item)
    }
    if len(active_slices) > int(projection["max_workers"]):
        raise CogitoError("worker lease limit exceeded")
    if task_payload["status"] == "leased" and any(
        key != task_id
        and effective_slice_id(item) == effective_slice_id(projection["tasks"][task_id])
        and is_active_task(item)
        for key, item in projection["tasks"].items()
    ):
        raise CogitoError("a Slice may have only one active worker lease")


def _apply_transition(projection: RunState, workflow: Mapping[str, Any], event_type: str, payload: Mapping[str, Any]) -> None:
    missing_task: Mapping[str, Any] = {}
    if (event_type == "shared-understanding-confirmed"
            and ("shared_understanding_hash" in payload or projection.get("shared_understanding_revised", False))
            and payload.get("shared_understanding_hash") != projection.get("shared_understanding_hash")):
        raise CogitoError("Shared Understanding confirmation must name the latest summary hash")
    transition = validate_transition(workflow, projection["state"], event_type, payload, projection["counters"], projection["limits"])
    # Further findings belong to the same blocked interval. Its resume target
    # remains the state that preceded the first block, including during replay.
    if transition["to"] == "blocked" and projection["state"] != "blocked":
        projection["blocked_from"] = projection["state"]
    projection["state"] = transition["to"]
    if transition.get("counter"):
        key = transition["counter"]
        projection["counters"][key] = projection["counters"].get(key, 0) + 1
    if event_type == "cancel" and payload.get('disposition_id'):
        for task in projection['tasks'].values():
            if is_active_task(task):
                task['status'] = 'blocked'
                task['released_by'] = payload['disposition_id']
    if event_type == "package-approved":
        # RP successors and older initializers can omit the optional delivery hint.
        # Reconstruct it only from a candidate snapshot authenticated by approval.
        candidate = projection.get("planning", {}).get("candidate")
        if candidate is not None:
            from cogito_contracts import package_hash, validate_package_with_limits
            approved_candidate = candidate["package"]
            if (package_hash(approved_candidate) != payload["package_hash"]
                    or projection.get("candidate_package_hash") != payload["package_hash"]):
                raise CogitoError("approved Package does not match the recorded candidate snapshot")
            validate_package_with_limits(approved_candidate, workflow["limits"])
            if approved_candidate.get("task_delivery") == "atomic":
                projection["task_delivery"] = "atomic"
            else:
                projection.pop("task_delivery", None)
        projection["package_path"] = payload["package_path"]
        projection["package_hash"] = payload["package_hash"]
        projection["effective_contract_hash"] = payload["package_hash"]
        projection["max_workers"] = int(payload["max_workers"])
        projection["project_graph_hash"] = payload["project_graph_hash"]
        projection["limits"].update(payload["limits"])
        if payload.get("human_review_mandate"):
            projection["human_review_mandate"] = dict(payload["human_review_mandate"])
        projection["tasks"] = {item["id"]: cast(TaskState, {**dict(item), "status": "pending"}) for item in payload.get("tasks", [])}
    elif event_type in {"package-ready", "mini-package-ready"}:
        projection["candidate_package_hash"] = payload.get("candidate_package_hash")
        project_candidate(projection, payload)
    elif event_type == "shared-understanding-ready":
        if (projection.get("shared_understanding_hash") is not None
                and projection["shared_understanding_hash"] != payload.get("shared_understanding_hash")):
            projection["shared_understanding_revised"] = True
        projection["shared_understanding_hash"] = payload.get("shared_understanding_hash")
        if projection.get("stage_commits"):
            projection["shared_document"] = dict(payload["document"])
        if projection.get("planning", {}).get("revision"):
            projection["planning"]["shared_document"] = dict(payload["document"])
    elif event_type == "boundary-complete":
        projection["boundary"] = {k: v for k, v in payload.items() if k != "planning_round"}
    elif event_type == "verification-passed":
        for task in projection["tasks"].values():
            if task.get("status") == "complete":
                task["status"] = "verified"
    elif event_type == "review-approved":
        for task_id in payload.get("reviews", []):
            if projection["tasks"].get(task_id, missing_task).get("status") == "verified":
                projection["tasks"][task_id]["status"] = "reviewed"
    elif event_type in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}:
        integration_payload = cast(IntegrationCompletedPayload, payload)
        for task_id in integration_payload.get("task_ids", []):
            if projection["tasks"].get(task_id, missing_task).get("status") == "reviewed":
                projection["tasks"][task_id]["status"] = "integrated"
