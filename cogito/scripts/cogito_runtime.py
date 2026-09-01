#!/usr/bin/env python3
"""Deterministic, fail-closed runtime primitives for Cogito 3.0."""

from __future__ import annotations

import hashlib
import fcntl
import json
import os
import re
import subprocess
import tempfile
from fnmatch import fnmatchcase
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = ROOT / "workflows" / "cogito-v3.json"
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class CogitoError(ValueError):
    """Raised when an input cannot safely advance the workflow."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CogitoError(f"cannot read valid JSON from {path}: {exc}") from exc


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def load_workflow(path: str | Path | None = None) -> dict[str, Any]:
    workflow = _load_json(Path(path) if path else DEFAULT_WORKFLOW)
    required = {"version", "initial_state", "terminal_states", "limits", "transitions"}
    if not isinstance(workflow, dict) or not required <= workflow.keys():
        raise CogitoError("workflow is missing required fields")
    keys: set[tuple[str, str]] = set()
    for item in workflow["transitions"]:
        if not isinstance(item, dict) or not {"from", "event", "to", "guard"} <= item.keys():
            raise CogitoError("workflow contains an invalid transition")
        key = (item["from"], item["event"])
        if key in keys:
            raise CogitoError(f"ambiguous transition: {key}")
        keys.add(key)
    if int(workflow["limits"].get("max_workers", 0)) not in range(1, 4):
        raise CogitoError("max_workers must be between 1 and 3")
    return workflow


def render_workflow_mermaid(workflow: Mapping[str, Any] | None = None) -> str:
    workflow = workflow or load_workflow()
    lines = ["stateDiagram-v2", f"    [*] --> {workflow['initial_state']}"]
    for item in workflow["transitions"]:
        lines.append(f"    {item['from']} --> {item['to']}: {item['event']}")
    states = sorted({item["from"] for item in workflow["transitions"]} | {item["to"] for item in workflow["transitions"]})
    for item in workflow.get("global_events", []):
        for state in states:
            if state not in workflow["terminal_states"] and state != item["to"]:
                lines.append(f"    {state} --> {item['to']}: {item['event']}")
    for target in workflow.get("resume_targets", []):
        lines.append(f"    blocked --> {target}: resume [{target}]")
    for terminal in workflow["terminal_states"]:
        lines.append(f"    {terminal} --> [*]")
    return "\n".join(lines) + "\n"


def render_project_graph_mermaid(graph: Mapping[str, Any]) -> str:
    if graph.get("schema_version") != "3.0" or not isinstance(graph.get("slices"), dict) or not isinstance(graph.get("dependencies"), list):
        raise CogitoError("cannot render an invalid Project Graph")
    lines = ["flowchart LR"]
    safe_ids: dict[str, str] = {}
    for slice_id, item in sorted(graph["slices"].items()):
        safe = re.sub(r"[^A-Za-z0-9_]", "_", slice_id)
        if safe in safe_ids and safe_ids[safe] != slice_id:
            raise CogitoError("Project Graph Slice ids collide in Mermaid rendering")
        safe_ids[safe] = slice_id
        label = str(slice_id).replace('"', "'")
        lines.append(f'    {safe}["{label}\\n{item.get("disposition", "unknown")}"]')
    for edge in graph["dependencies"]:
        if edge.get("from") not in graph["slices"] or edge.get("to") not in graph["slices"]:
            raise CogitoError("Project Graph dependency references an unknown Slice")
        source = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("from", "")))
        target = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("to", "")))
        if not source or not target:
            raise CogitoError("Project Graph dependency is incomplete")
        lines.append(f"    {source} --> {target}")
    return "\n".join(lines) + "\n"


def _required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


def _safe_repo_path(value: Any) -> bool:
    candidate = Path(str(value))
    return bool(str(value).strip()) and not candidate.is_absolute() and ".." not in candidate.parts


def _content_hash(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value)))


def _guard_ok(name: str, payload: Mapping[str, Any], counters: Mapping[str, int], workflow: Mapping[str, Any]) -> bool:
    checks = {
        "shared_understanding_frozen": lambda: _required(payload, "shared_understanding_hash"),
        "shared_confirmed": lambda: payload.get("confirmed") is True,
        "mini_package_valid": lambda: payload.get("package_valid") is True,
        "boundary_ready": lambda: payload.get("decision") in {"single-slice", "split-required"} and bool(payload.get("evidence")),
        "package_valid": lambda: payload.get("package_valid") is True,
        "package_approved": lambda: _required(payload, "package_path", "package_hash") and payload.get("approved") is True,
        "start_ready": lambda: all(payload.get(k) is True for k in ("baseline_valid", "contract_valid", "worktrees_valid")),
        "tasks_complete": lambda: payload.get("tasks_complete") is True,
        "verification_passed": lambda: payload.get("passed") is True and bool(payload.get("evidence")),
        "verification_retry_available": lambda: counters.get("verification_corrections", 0) < int(workflow["limits"]["verification_corrections"]) and payload.get("scope_within_contract") is True,
        "technical_correction_valid": lambda: payload.get("scope_within_contract") is True,
        "review_approved": lambda: payload.get("approved") is True and (payload.get("independent") is True or payload.get("review_exemption") is True),
        "review_retry_available": lambda: counters.get("review_fix_cycles", 0) < int(workflow["limits"]["review_fix_cycles"]) and payload.get("scope_within_contract") is True,
        "review_fix_valid": lambda: payload.get("scope_within_contract") is True,
        "integration_complete": lambda: _required(payload, "commit_id"),
        "post_checks_passed_and_human_required": lambda: payload.get("passed") is True and payload.get("human_required") is True and bool(payload.get("evidence")),
        "post_checks_passed_and_no_human": lambda: payload.get("passed") is True and payload.get("human_required") is False and bool(payload.get("evidence")),
        "human_approved": lambda: payload.get("approved") is True,
        "final_recorded": lambda: _required(payload, "result_path", "final_commit") and payload.get("project_graph_updated") is True,
        "block_reason_present": lambda: _required(payload, "reason"),
        "cancellation_authorized": lambda: payload.get("authorized") is True,
    }
    check = checks.get(name)
    return bool(check and check())


def validate_transition(
    workflow: Mapping[str, Any], state: str, event: str,
    payload: Mapping[str, Any] | None, counters: Mapping[str, int] | None = None,
    limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    counters = counters or {}
    if state in workflow["terminal_states"]:
        raise CogitoError(f"terminal state {state!r} cannot transition")
    candidates = [t for t in workflow["transitions"] if t["from"] == state and t["event"] == event]
    candidates += [t for t in workflow.get("global_events", []) if t["event"] == event]
    if len(candidates) != 1:
        raise CogitoError(f"event {event!r} is not legal from state {state!r}")
    transition = dict(candidates[0])
    effective_workflow = dict(workflow)
    effective_workflow["limits"] = dict(limits or workflow["limits"])
    if not _guard_ok(transition["guard"], payload, counters, effective_workflow):
        raise CogitoError(f"guard {transition['guard']!r} rejected event {event!r}")
    counter = transition.get("counter")
    if counter and counters.get(counter, 0) >= int(effective_workflow["limits"][counter]):
        raise CogitoError(f"retry limit exhausted: {counter}")
    return transition


def read_events(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CogitoError(f"cannot read event log: {exc}") from exc
    for expected, line in enumerate(lines, 1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CogitoError(f"invalid event JSON on line {expected}") from exc
        supplied_hash = event.get("event_hash")
        body = {k: v for k, v in event.items() if k != "event_hash"}
        if event.get("sequence") != expected or event.get("previous_event_hash") != previous:
            raise CogitoError(f"broken event chain on line {expected}")
        if supplied_hash != hash_json(body):
            raise CogitoError(f"invalid event hash on line {expected}")
        previous = supplied_hash
        events.append(event)
    return events


def append_event(path: str | Path, event: Mapping[str, Any], expected_previous_hash: str | None = None) -> dict[str, Any]:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        events = read_events(path)
        actual_previous = events[-1]["event_hash"] if events else "0" * 64
        if expected_previous_hash is not None and actual_previous != expected_previous_hash:
            raise CogitoError("event history changed during transition; retry with the same action_id")
        action_id = event.get("action_id")
        if action_id:
            matches = [item for item in events if item.get("action_id") == action_id]
            if matches:
                requested = {"type": event.get("type"), "payload": event.get("payload", {})}
                recorded = {"type": matches[0].get("type"), "payload": matches[0].get("payload", {})}
                if requested != recorded:
                    raise CogitoError(f"action_id {action_id!r} was already used for different content")
                return matches[0]
        body = {
            "sequence": len(events) + 1,
            "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "type": event.get("type"),
            "payload": event.get("payload", {}),
            "action_id": action_id,
            "previous_event_hash": actual_previous,
        }
        if not isinstance(body["type"], str) or not body["type"]:
            raise CogitoError("event type is required")
        if not isinstance(body["payload"], dict):
            raise CogitoError("event payload must be an object")
        body["event_hash"] = hash_json(body)
        line = canonical_json(body) + "\n"
        fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return body


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
                "agent_results": [],
                "evidence": {},
                "package_path": None, "package_hash": None, "effective_contract_hash": None,
                "blocked_from": None, "max_workers": int(workflow["limits"]["max_workers"]),
                "candidate_package_hash": None,
                "project_graph_hash": None,
                "shared_understanding_hash": None, "boundary": None,
                "limits": dict(workflow["limits"]),
            }
            continue
        if projection is None:
            raise CogitoError("event log must begin with run-created")
        if event_type == "task-updated":
            if not _required(payload, "task_id", "status", "agent_id"):
                raise CogitoError("task-updated requires task_id, status and agent_id")
            task_id = payload["task_id"]
            if task_id not in projection["tasks"]:
                raise CogitoError("task-updated references a task outside the effective Package")
            before = projection["tasks"][task_id].get("status", "pending")
            allowed_status = {
                "pending": {"leased", "blocked"}, "leased": {"running", "blocked"},
                "running": {"complete", "blocked"}, "blocked": {"pending"}, "complete": set(),
                "verified": set(), "reviewed": set(), "integrated": set(),
            }
            if payload["status"] not in allowed_status.get(before, set()):
                raise CogitoError(f"illegal task status transition: {before} -> {payload['status']}")
            prior_agent = projection["tasks"][task_id].get("agent_id")
            if payload["status"] != "pending" and prior_agent and prior_agent != payload["agent_id"]:
                raise CogitoError("task lease belongs to a different agent")
            if before == "pending":
                for dep in projection["tasks"][task_id].get("depends_on", []):
                    predecessor = projection["tasks"].get(dep, {})
                    same_slice = predecessor.get("slice_id") == projection["tasks"][task_id].get("slice_id")
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
                key != task_id and (item.get("slice_id") or "mini-package") == (projection["tasks"][task_id].get("slice_id") or "mini-package") and item.get("status") in {"leased", "running"}
                for key, item in projection["tasks"].items()
            ):
                raise CogitoError("a Slice may have only one active worker lease")
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
            transition = validate_transition(workflow, projection["state"], str(event_type), payload, projection["counters"], projection["limits"])
            if transition["to"] == "blocked":
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
        projection["sequence"] = item.get("sequence", projection["sequence"] + 1)
        projection["last_event_hash"] = item.get("event_hash")
    if projection is None:
        raise CogitoError("event log is empty")
    return projection


def _edge_pair(edge: Any) -> tuple[str, str]:
    if isinstance(edge, dict) and set(edge) >= {"from", "to"}:
        return str(edge["from"]), str(edge["to"])
    if isinstance(edge, (list, tuple)) and len(edge) == 2:
        return str(edge[0]), str(edge[1])
    raise CogitoError("each DAG edge must contain from and to")


def ready_tasks(tasks: Sequence[Mapping[str, Any]], edges: Sequence[Any], max_workers: int = 3) -> list[dict[str, Any]]:
    if not 1 <= max_workers <= 3:
        raise CogitoError("max_workers must be between 1 and 3")
    by_id = {str(task.get("id")): task for task in tasks if task.get("id")}
    if len(by_id) != len(tasks):
        raise CogitoError("task ids must be present and unique")
    pairs = [_edge_pair(edge) for edge in edges]
    if any(a not in by_id or b not in by_id or a == b for a, b in pairs):
        raise CogitoError("DAG edge references an unknown task or itself")
    indegree = {key: 0 for key in by_id}
    children = {key: [] for key in by_id}
    for source, target in pairs:
        indegree[target] += 1
        children[source].append(target)
    queue = [key for key, value in indegree.items() if value == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(by_id):
        raise CogitoError("execution graph contains a cycle")
    active_slices = {task.get("slice_id") or "mini-package" for task in tasks if task.get("status") in {"leased", "running"}}
    capacity = max(0, max_workers - len(active_slices))
    prerequisites: dict[str, set[str]] = {key: set() for key in by_id}
    for source, target in pairs:
        prerequisites[target].add(source)
    def dependency_ready(source: str, target: str) -> bool:
        source_task, target_task = by_id[source], by_id[target]
        if source_task.get("slice_id") == target_task.get("slice_id"):
            return source_task.get("status") in {"complete", "verified", "reviewed", "integrated"}
        return source_task.get("status") == "integrated"
    candidates = [dict(task) for key, task in by_id.items() if task.get("status", "pending") == "pending" and all(dependency_ready(source, key) for source in prerequisites[key])]
    selected: list[dict[str, Any]] = []
    selected_slices = set(active_slices)
    for task in candidates:
        slice_id = task.get("slice_id") or "mini-package"
        if slice_id in selected_slices:
            continue
        selected.append(task)
        selected_slices.add(slice_id)
        if len(selected) >= capacity:
            break
    return selected


def package_hash(package: Mapping[str, Any]) -> str:
    return hash_json({k: v for k, v in package.items() if k != "package_hash"})


def validate_package(package: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "run_id", "kind", "delivery_branch", "baseline_commit",
        "shared_understanding", "slices", "execution_dag", "checks",
        "approved_paths", "human_gate", "policy_snapshot", "limits",
        "stop_conditions", "source_registry",
    }
    if not isinstance(package, dict) or not required <= package.keys():
        raise CogitoError(f"package is missing fields: {sorted(required - set(package))}")
    if package["schema_version"] != "3.0" or package["kind"] not in {"feature", "change", "correction", "maintenance", "documentation"}:
        raise CogitoError("unsupported package schema or kind")
    if not re.fullmatch(r"(?:DEV|MNT)-[A-Za-z0-9._-]+", str(package["run_id"])) or not package["delivery_branch"] or not re.fullmatch(r"[0-9a-f]{7,64}", str(package["baseline_commit"])):
        raise CogitoError("package run_id, delivery_branch or baseline_commit is invalid")
    if not isinstance(package["shared_understanding"], dict) or not _content_hash(package["shared_understanding"].get("hash")):
        raise CogitoError("shared_understanding.hash is required")
    mini = package["kind"] in {"maintenance", "documentation"}
    if bool(package.get("mini_package")) != mini:
        raise CogitoError("mini_package must be true exactly for maintenance/documentation")
    if mini:
        if package["slices"] != []:
            raise CogitoError("Mini Package must not create Slice/Spec/Plan entries")
        guards = package.get("maintenance_guards")
        if (
            not isinstance(guards, dict)
            or not all(guards.get(key) is True for key in (
                "behavior_unchanged", "public_contract_unchanged", "data_model_unchanged",
                "security_boundary_unchanged", "slice_responsibility_unchanged",
                "deterministic_evidence", "single_commit",
            ))
        ):
            raise CogitoError("Mini Package requires every frozen no-semantic-change guard")
    else:
        boundary = package.get("boundary")
        if not isinstance(boundary, dict) or boundary.get("decision") not in {"single-slice", "split-required"} or not boundary.get("evidence"):
            raise CogitoError("a Development Package requires a non-blocked boundary decision with evidence")
        if not isinstance(package["slices"], list) or not package["slices"]:
            raise CogitoError("a Development Package requires at least one Slice")
        seen_slices: set[str] = set()
        for item in package["slices"]:
            if not isinstance(item, dict) or not {"id", "type", "spec", "plan", "worker"} <= item.keys():
                raise CogitoError("each Slice requires id, type, spec, plan and worker")
            if item["id"] in seen_slices or item["type"] not in {"feature", "change", "correction"}:
                raise CogitoError("Slice ids must be unique and types valid")
            seen_slices.add(item["id"])
            for document in (item["spec"], item["plan"]):
                if not isinstance(document, dict) or not _safe_repo_path(document.get("path")) or not _content_hash(document.get("hash")):
                    raise CogitoError("Spec and Plan require frozen path and hash")
            worker = item["worker"]
            if not isinstance(worker, dict) or not _required(worker, "branch", "worktree") or not isinstance(worker.get("allowed_paths"), list):
                raise CogitoError("each Slice requires a dedicated worker branch/worktree and allowed paths")
    if not all(isinstance(package[key], list) and package[key] for key in ("checks", "approved_paths", "stop_conditions")):
        raise CogitoError("checks, approved_paths and stop_conditions must be non-empty arrays")
    for pattern in package["approved_paths"]:
        if not _safe_repo_path(pattern):
            raise CogitoError("approved_paths must be safe repository-relative patterns")
    dag = package["execution_dag"]
    if not isinstance(dag, dict) or not isinstance(dag.get("tasks"), list) or not isinstance(dag.get("edges"), list):
        raise CogitoError("execution_dag must contain tasks and edges")
    if not dag["tasks"]:
        raise CogitoError("execution_dag requires at least one task")
    ready_tasks(dag["tasks"], dag["edges"])
    slice_ids = {item["id"] for item in package["slices"]}
    slice_paths = {item["id"]: item["worker"]["allowed_paths"] for item in package["slices"]}
    for task in dag["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("paths", []), list) or any(not _path_allowed(str(path), package["approved_paths"]) for path in task.get("paths", [])):
            raise CogitoError("task paths must stay within approved_paths")
        if not mini and task.get("slice_id") not in slice_ids:
            raise CogitoError("each Development Package task must reference a Package Slice")
        if not mini and any(not _path_allowed(str(path), slice_paths[task["slice_id"]]) for path in task.get("paths", [])):
            raise CogitoError("task path exceeds its Slice worker responsibility")
    if not mini:
        task_slices = {task["id"]: task["slice_id"] for task in dag["tasks"]}
        slice_edges = sorted({(task_slices[source], task_slices[target]) for source, target in map(_edge_pair, dag["edges"]) if task_slices[source] != task_slices[target]})
        ready_tasks(
            [{"id": slice_id, "slice_id": slice_id, "status": "pending"} for slice_id in slice_ids],
            [{"from": source, "to": target} for source, target in slice_edges],
        )
    for item in package["slices"]:
        if any(not _path_allowed(str(path), package["approved_paths"]) for path in item["worker"]["allowed_paths"]):
            raise CogitoError("worker allowed paths must be contained by approved_paths")
    check_ids = [item.get("id") for item in package["checks"] if isinstance(item, dict)]
    if (
        len(check_ids) != len(package["checks"]) or len(check_ids) != len(set(check_ids))
        or any(not ID_RE.fullmatch(str(check_id or "")) for check_id in check_ids)
        or any(not isinstance(item.get("argv"), list) or not item["argv"] or not all(isinstance(arg, str) and arg for arg in item["argv"]) for item in package["checks"])
    ):
        raise CogitoError("checks require safe unique ids and non-empty argv arrays")
    human = package["human_gate"]
    if not isinstance(human, dict) or not isinstance(human.get("predicates"), list) or not isinstance(human.get("high_risk_hotspots", []), list):
        raise CogitoError("human_gate requires frozen predicates and high_risk_hotspots")
    if any(not isinstance(item, dict) or not {"id", "applicable"} <= item.keys() or not isinstance(item["applicable"], bool) for item in human["predicates"]):
        raise CogitoError("each human predicate requires id and frozen applicable boolean")
    if any(not _safe_repo_path(path) for path in human.get("high_risk_hotspots", [])):
        raise CogitoError("human high-risk hotspots must be repository-relative paths")
    limits = package["limits"]
    global_limits = load_workflow()["limits"]
    if not isinstance(limits, dict) or any(not isinstance(limits.get(key), int) or not 0 <= limits[key] <= global_limits[key] for key in ("transient_retries", "verification_corrections", "review_fix_cycles", "format_repairs")):
        raise CogitoError("Package retry limits must be integers no looser than global limits")
    policy = package["policy_snapshot"]
    if not isinstance(policy, dict) or not isinstance(policy.get("max_workers"), int) or not 1 <= policy["max_workers"] <= 3 or not isinstance(policy.get("fetch_allowed"), bool):
        raise CogitoError("policy_snapshot requires max_workers 1..3 and frozen fetch_allowed")
    allowed_environment = policy.get("allowed_environment", [])
    required_policy_checks = policy.get("required_checks", [])
    if not isinstance(allowed_environment, list) or not all(isinstance(item, str) for item in allowed_environment) or not isinstance(required_policy_checks, list):
        raise CogitoError("policy_snapshot environment and required checks must be arrays")
    if set(required_policy_checks) - set(check_ids):
        raise CogitoError("Package omits checks frozen by its policy snapshot")
    if any(set(check.get("env_allowlist", [])) - set(allowed_environment) for check in package["checks"]):
        raise CogitoError("Package check environment exceeds its frozen policy snapshot")
    registry = package["source_registry"]
    if not isinstance(registry, list) or any(
        not isinstance(item, dict) or not {"path", "hash", "relevance", "disposition"} <= item.keys()
        or not _safe_repo_path(item.get("path")) or not _content_hash(item.get("hash"))
        or item.get("disposition") not in {"read-only-source", "adopted", "updated", "superseded", "not-touched"}
        for item in registry
    ):
        raise CogitoError("source_registry entries require path, hash, relevance and disposition")
    expected = package.get("package_hash")
    if expected is not None and expected != package_hash(package):
        raise CogitoError("package_hash does not match immutable package content")


def _path_allowed(path: str, approved: Sequence[str]) -> bool:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    normalized = candidate.as_posix().rstrip("/")
    for raw in approved:
        pattern = str(raw).rstrip("/")
        if fnmatchcase(normalized, pattern):
            return True
        prefix = pattern.removesuffix("/**").removesuffix("/*")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def validate_amendment(package: Mapping[str, Any], prior: Sequence[Mapping[str, Any]], amendment: Mapping[str, Any]) -> None:
    validate_package(package)
    allowed = {"id", "reason", "added_checks", "added_tasks", "path_fixes", "commit_id"}
    if not isinstance(amendment, dict) or not {"id", "reason"} <= amendment.keys():
        raise CogitoError("amendment id and reason are required")
    if set(amendment) - allowed:
        raise CogitoError(f"amendment attempts forbidden changes: {sorted(set(amendment) - allowed)}")
    if amendment["id"] in {item.get("id") for item in prior}:
        raise CogitoError("amendment id must be unique")
    if not any(amendment.get(key) for key in ("added_checks", "added_tasks", "path_fixes")):
        raise CogitoError("amendment must add a check/task or record an in-scope path fix")
    existing_checks = {item["id"] for item in package["checks"]}
    existing_checks |= {check["id"] for item in prior for check in item.get("added_checks", [])}
    for check in amendment.get("added_checks", []):
        if not isinstance(check, dict) or not check.get("id") or not check.get("argv") or check["id"] in existing_checks:
            raise CogitoError("added checks require new ids and non-empty argv")
        existing_checks.add(check["id"])
    existing_tasks = {item["id"] for item in package["execution_dag"]["tasks"]}
    existing_tasks |= {task["id"] for item in prior for task in item.get("added_tasks", [])}
    for task in amendment.get("added_tasks", []):
        if not isinstance(task, dict) or not task.get("id") or task["id"] in existing_tasks or not isinstance(task.get("paths"), list) or not task.get("slice_id"):
            raise CogitoError("added tasks require new ids, slice_id and paths")
        if any(not _path_allowed(str(path), package["approved_paths"]) for path in task["paths"]):
            raise CogitoError("added task paths must stay within approved paths")
        slices = {item["id"]: item for item in package["slices"]}
        if package["kind"] in {"maintenance", "documentation"}:
            if task["slice_id"] != "mini-package":
                raise CogitoError("Mini Package amendment tasks use slice_id mini-package")
        elif task["slice_id"] not in slices or any(not _path_allowed(str(path), slices[task["slice_id"]]["worker"]["allowed_paths"]) for path in task["paths"]):
            raise CogitoError("added task exceeds its Slice worker responsibility")
        existing_tasks.add(task["id"])
    if any(not _path_allowed(str(path), package["approved_paths"]) for path in amendment.get("path_fixes", [])):
        raise CogitoError("amendment path_fixes must stay within approved paths")


def effective_contract_hash(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> str:
    validate_package(package)
    validated: list[Mapping[str, Any]] = []
    for amendment in amendments:
        validate_amendment(package, validated, amendment)
        validated.append(amendment)
    return hash_json({"base_package_hash": package_hash(package), "amendments": validated}) if validated else package_hash(package)


def materialize_contract(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return the executable base Package plus ordered, monotonic overlays."""
    validate_package(package)
    effective = json.loads(json.dumps(package))
    validated: list[Mapping[str, Any]] = []
    for amendment in amendments:
        validate_amendment(package, validated, amendment)
        effective["checks"].extend(json.loads(json.dumps(amendment.get("added_checks", []))))
        effective["execution_dag"]["tasks"].extend(json.loads(json.dumps(amendment.get("added_tasks", []))))
        validated.append(amendment)
    effective["effective_contract_hash"] = effective_contract_hash(package, amendments)
    return effective


def validate_agent_result(result: Mapping[str, Any], package: Mapping[str, Any] | None = None) -> None:
    required = {"schema_version", "run_id", "task_id", "agent_id", "role", "status", "base_commit", "head_commit", "changed_paths", "evidence", "risks", "requested_transition"}
    if not isinstance(result, dict) or not required <= result.keys():
        raise CogitoError(f"agent result is missing fields: {sorted(required - set(result))}")
    if result["schema_version"] != "3.0" or result["role"] not in {"implementer", "reviewer", "integrator"} or result["status"] not in {"complete", "needs-fix", "blocked"}:
        raise CogitoError("unsupported agent result value")
    if not re.fullmatch(r"[0-9a-f]{7,64}", str(result["base_commit"])) or not re.fullmatch(r"[0-9a-f]{7,64}", str(result["head_commit"])):
        raise CogitoError("Agent Result base/head commit ids are invalid")
    if result["requested_transition"] not in {"executing", "verifying", "technical-correction", "reviewing", "review-approved", "review-fix", "integrating", "post-integration-verification", "awaiting-human", "finalizing", "blocked"}:
        raise CogitoError("Agent Result requested_transition is invalid")
    repair_attempt = result.get("repair_attempt", 0)
    if isinstance(repair_attempt, bool) or not isinstance(repair_attempt, int) or not 0 <= repair_attempt <= 2:
        raise CogitoError("agent result repair_attempt must be an integer from 0 through 2")
    for key in ("changed_paths", "evidence", "risks"):
        if not isinstance(result[key], list):
            raise CogitoError(f"agent result {key} must be an array")
    if result["status"] == "complete" and result["role"] != "reviewer" and not result["head_commit"]:
        raise CogitoError("completed implementation/integration requires head_commit")
    if result["role"] == "reviewer" and (not result.get("reviewed_implementer") or result.get("reviewed_implementer") == result.get("agent_id")):
        raise CogitoError("an independent reviewer must identify a different implementer")
    if package:
        validate_package(package)
        if result["run_id"] != package["run_id"]:
            raise CogitoError("agent result run_id does not match package")
        if any(not _path_allowed(str(path), package["approved_paths"]) for path in result["changed_paths"]):
            raise CogitoError("agent changed a path outside the approved package")


class RunStore:
    _GATE_AUTHORITY = object()

    def __init__(self, root: str | Path, run_id: str, workflow: Mapping[str, Any] | None = None):
        if not re.fullmatch(r"(?:DEV|MNT)-[A-Za-z0-9._-]+", run_id):
            raise CogitoError("run_id must use a safe DEV-* or MNT-* identifier")
        self.root = Path(root).resolve()
        self.run_id = run_id
        self.run_dir = self.root / ".cogito" / "runs" / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.state_path = self.run_dir / "state.json"
        self.workflow = dict(workflow or load_workflow())

    def create(self, kind: str) -> dict[str, Any]:
        if self.events_path.exists():
            raise CogitoError(f"run already exists: {self.run_id}")
        self.run_dir.mkdir(parents=True, exist_ok=False)
        append_event(self.events_path, {"type": "run-created", "payload": {"run_id": self.run_id, "kind": kind}, "action_id": f"create:{self.run_id}"})
        return self._project()

    def load(self) -> dict[str, Any]:
        projection = reduce_events(read_events(self.events_path), self.workflow)
        if projection.get("package_path"):
            package_path = self.root / projection["package_path"]
            package = _load_json(package_path)
            validate_package(package)
            if package_hash(package) != projection["package_hash"]:
                raise CogitoError("approved Package content no longer matches its frozen hash")
        cached = _load_json(self.state_path) if self.state_path.exists() else None
        if cached is not None and (cached.get("sequence"), cached.get("last_event_hash")) != (projection.get("sequence"), projection.get("last_event_hash")):
            atomic_write_json(self.state_path, projection)
        return projection

    def _project(self) -> dict[str, Any]:
        projection = reduce_events(read_events(self.events_path), self.workflow)
        atomic_write_json(self.state_path, projection)
        return projection

    def record(self, event_type: str, payload: Mapping[str, Any], action_id: str | None = None, _authority: object | None = None) -> dict[str, Any]:
        protected = {"package-ready", "mini-package-ready", "package-approved", "technical-amendment-added", "task-updated", "agent-result-recorded", "check-evidence-recorded", "start-gate-passed", "verification-passed", "verification-correction-required", "post-verification-correction-required", "technical-correction-complete", "post-integration-correction-complete", "review-fix-required", "review-fix-complete", "slice-integration-complete", "wave-integration-complete", "integration-complete", "human-review-required", "auto-accept-ready", "human-approved", "finalization-complete", "resume", "transient-retry", "format-repair-recorded"}
        if event_type in protected and _authority is not self._GATE_AUTHORITY:
            raise CogitoError(f"{event_type} requires its dedicated Gate operation")
        existing = read_events(self.events_path)
        if action_id:
            matches = [item for item in existing if item.get("action_id") == action_id]
            if matches:
                requested = {"type": event_type, "payload": dict(payload)}
                recorded = {"type": matches[0]["type"], "payload": matches[0]["payload"]}
                if requested != recorded:
                    raise CogitoError(f"action_id {action_id!r} was already used for different content")
                return self.load()
        # Validate the candidate against authoritative history before mutating it.
        reduce_events([*existing, {"type": event_type, "payload": dict(payload)}], self.workflow)
        expected = existing[-1]["event_hash"] if existing else "0" * 64
        append_event(self.events_path, {"type": event_type, "payload": dict(payload), "action_id": action_id}, expected)
        return self._project()

    def transition(self, event: str, payload: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, event, payload)
        if replay is not None:
            return replay
        current = self.load()
        protected = {"package-ready", "mini-package-ready", "package-approved", "start-gate-passed", "verification-passed", "verification-correction-required", "post-verification-correction-required", "technical-correction-complete", "post-integration-correction-complete", "review-fix-required", "review-fix-complete", "slice-integration-complete", "wave-integration-complete", "integration-complete", "human-review-required", "auto-accept-ready", "human-approved", "finalization-complete", "resume", "transient-retry", "format-repair-recorded"}
        if event in protected:
            raise CogitoError(f"{event} requires its dedicated Gate operation")
        payload = dict(payload)
        if event == "implementation-complete":
            completed = {task_id for task_id, item in current["tasks"].items() if item.get("status") == "complete"}
            implemented = {item.get("task_id") for item in current["agent_results"] if item.get("role") == "implementer" and item.get("status") == "complete" and item.get("requested_transition") == "verifying"}
            active = any(item.get("status") in {"leased", "running"} for item in current["tasks"].values())
            edges = [{"from": dependency, "to": task["id"]} for task in current["tasks"].values() for dependency in task.get("depends_on", [])]
            dispatchable = ready_tasks(list(current["tasks"].values()), edges, current["max_workers"])
            payload["tasks_complete"] = bool(completed) and not active and not dispatchable and completed <= implemented
            payload["task_ids"] = sorted(completed)
        if event == "review-approved":
            self._validate_review(payload)
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id)

    def approved_package(self) -> dict[str, Any]:
        state = self.load()
        if not state.get("package_path"):
            raise CogitoError("run has no approved Package")
        package = _load_json(self.root / state["package_path"])
        validate_package(package)
        if package_hash(package) != state["package_hash"]:
            raise CogitoError("approved Package hash mismatch")
        return package

    def prepare_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package(package)
        self._validate_policy(package)
        current = self.load()
        mini = package["kind"] in {"maintenance", "documentation"}
        if not mini and package["shared_understanding"]["hash"] != current.get("shared_understanding_hash"):
            raise CogitoError("Package is not bound to the confirmed Shared Understanding")
        if not mini and package["boundary"] != current.get("boundary"):
            raise CogitoError("Package is not bound to the recorded Boundary Gate result")
        event = "mini-package-ready" if mini else "package-ready"
        expected_state = "preparing" if mini else "package-preparing"
        payload = {"package_valid": True, "candidate_package_hash": package_hash(package)}
        replay = self._replay(action_id, event, payload)
        if replay is not None:
            return replay
        if current["state"] != expected_state:
            raise CogitoError("Package preparation is not legal in the current state")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def update_task(self, task_id: str, status: str, agent_id: str, action_id: str | None = None) -> dict[str, Any]:
        payload = {"task_id": task_id, "status": status, "agent_id": agent_id}
        if action_id:
            matches = [item for item in read_events(self.events_path) if item.get("action_id") == action_id]
            if matches:
                if len(matches) != 1 or matches[0]["type"] != "task-updated" or any(matches[0]["payload"].get(key) != value for key, value in payload.items()):
                    raise CogitoError(f"action_id {action_id!r} was already used for different content")
                return self.load()
        current = self.load()
        if current["state"] not in {"executing", "technical-correction", "review-fix", "post-integration-correction"}:
            raise CogitoError("task updates are not legal in the current state")
        task = current["tasks"].get(task_id)
        if not task:
            raise CogitoError("task is outside the effective Package")
        if status == "leased":
            package = self.approved_package()
            if current["state"] == "post-integration-correction":
                worktree, branch = self.root, package["delivery_branch"]
            else:
                worktree, branch = self._task_worktree(task, package)
            base_commit = self._git_at(worktree, "rev-parse", "HEAD")
            prior_heads = [item["head_commit"] for item in current["agent_results"] if item.get("role") == "implementer" and current["tasks"].get(item.get("task_id"), {}).get("slice_id") == task.get("slice_id")]
            expected_base = prior_heads[-1] if prior_heads and current["state"] != "post-integration-correction" else self._git("rev-parse", "HEAD")
            if base_commit != expected_base:
                raise CogitoError("a Slice worktree must start from the latest delivery HEAD")
            payload.update({"worktree": str(worktree), "branch": branch, "base_commit": base_commit})
        return self.record("task-updated", payload, action_id, self._GATE_AUTHORITY)

    def submit_agent_result(self, result: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        payload = {"result": dict(result)}
        replay = self._replay(action_id, "agent-result-recorded", payload)
        if replay is not None:
            return replay
        package = self.approved_package()
        validate_agent_result(result, package)
        state = self.load()
        allowed_states = {
            "implementer": {"executing", "technical-correction", "review-fix", "post-integration-correction"},
            "reviewer": {"reviewing"}, "integrator": {"integrating"},
        }
        if state["state"] not in allowed_states[result["role"]]:
            raise CogitoError(f"{result['role']} Result is not legal in state {state['state']}")
        task = state["tasks"].get(result["task_id"])
        if not task:
            raise CogitoError("Agent Result references a task outside the effective Package")
        if result["role"] != "reviewer" and task.get("agent_id") != result["agent_id"]:
            raise CogitoError("Agent Result identity does not own the task lease")
        if result["role"] == "reviewer" and result.get("reviewed_implementer") != task.get("agent_id"):
            raise CogitoError("Reviewer Result is not bound to the task implementer")
        worktree = Path(str(task.get("worktree", "")))
        if not worktree.is_dir() or result["base_commit"] != task.get("base_commit") or result["head_commit"] != self._git_at(worktree, "rev-parse", "HEAD"):
            raise CogitoError("Agent Result commits are not bound to the leased worktree")
        if self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
            raise CogitoError("Agent Result worktree is not on its leased branch")
        self._git("cat-file", "-e", f"{result['base_commit']}^{{commit}}")
        self._git("cat-file", "-e", f"{result['head_commit']}^{{commit}}")
        self._git("merge-base", "--is-ancestor", result["base_commit"], result["head_commit"])
        actual_paths = set(filter(None, self._git_at(worktree, "diff", "--name-only", result["base_commit"], result["head_commit"], "--").splitlines()))
        if package["kind"] == "maintenance":
            actual_paths.update(filter(None, self._git_at(worktree, "diff", "--name-only", "--").splitlines()))
            actual_paths.update(filter(None, self._git_at(worktree, "ls-files", "--others", "--exclude-standard").splitlines()))
            control_paths = {self.load().get("package_path"), "docs/cogito/project-graph.json"}
            actual_paths = {path for path in actual_paths if path not in control_paths and not path.startswith(".cogito/")}
        if result["role"] != "reviewer" and set(result["changed_paths"]) != actual_paths:
            raise CogitoError("Agent Result changed_paths do not match its commit range")
        if any(not _path_allowed(path, task.get("paths", [])) for path in actual_paths):
            raise CogitoError("Agent Result exceeds its task path responsibility")
        return self.record("agent-result-recorded", payload, action_id, self._GATE_AUTHORITY)

    def complete_verification(self, evidence: Sequence[Mapping[str, Any]], action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "verification-passed")
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "verifying":
            raise CogitoError("verification closure is not legal in the current state")
        package = self.approved_package()
        self._validate_evidence(package, evidence)
        payload = {"passed": True, "evidence": [item["evidence_path"] for item in evidence]}
        validate_transition(self.workflow, current["state"], "verification-passed", payload, current["counters"])
        return self.record("verification-passed", payload, action_id, self._GATE_AUTHORITY)

    def run_controlled_check(self, check_id: str, worktree: str | Path, action_id: str) -> dict[str, Any]:
        replay = self._replay(action_id, "check-evidence-recorded")
        if replay is not None:
            return replay
        if not action_id:
            raise CogitoError("controlled check requires a stable action_id")
        package = self.approved_package()
        state = self.load()
        supplied_worktree = Path(worktree).resolve()
        if state["state"] == "post-integration-verification":
            if supplied_worktree != self.root:
                raise CogitoError("post-integration checks must run in the delivery checkout")
        elif state["state"] == "verifying":
            eligible = {Path(str(task.get("worktree", ""))).resolve() for task in state["tasks"].values() if task.get("status") == "complete"}
            if supplied_worktree not in eligible:
                raise CogitoError("verification checks must run in a completed Package Slice worktree")
        else:
            raise CogitoError("controlled checks are not legal in the current state")
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        try:
            from cogito_runner import run_check, write_evidence_once
        except ImportError as exc:  # pragma: no cover - installation failure
            raise CogitoError(f"controlled runner is unavailable: {exc}") from exc
        record_id = f"{check_id}-{hash_json({'action_id': action_id})[:16]}"
        path = self.run_dir / "evidence" / f"{record_id}.json"
        if not path.exists():
            evidence = run_check(package, check_id, supplied_worktree, prior)
            path = write_evidence_once(self.run_dir / "evidence", record_id, evidence)
        recorded = _load_json(path)
        payload = {"check_id": check_id, "evidence_path": str(path), "evidence_hash": hash_json(recorded), "head_commit": recorded["head_commit"], "effective_contract_hash": recorded["effective_contract_hash"]}
        return self.record("check-evidence-recorded", payload, action_id, self._GATE_AUTHORITY)

    def enter_correction(self, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, {"verification-correction-required", "post-verification-correction-required"})
        if replay is not None:
            return replay
        current = self.load()
        events = read_events(self.events_path)
        amendments = [item for item in events if item["type"] == "technical-amendment-added"]
        if not amendments:
            raise CogitoError("correction requires a validated Technical Amendment")
        completions = [item for item in events if item["type"] in {"technical-correction-complete", "post-integration-correction-complete", "review-fix-complete"}]
        consumed = {item["payload"].get("amendment_id") for item in completions}
        if amendments[-1]["payload"]["amendment"]["id"] in consumed:
            raise CogitoError("correction requires a new, unconsumed Technical Amendment")
        if current["state"] == "verifying":
            event = "verification-correction-required"
        elif current["state"] == "post-integration-verification":
            event = "post-verification-correction-required"
        else:
            raise CogitoError("correction is not legal in the current state")
        amendment = amendments[-1]["payload"]["amendment"]
        payload = {"scope_within_contract": True, "amendment_id": amendment["id"], "effective_contract_hash": amendments[-1]["payload"]["effective_contract_hash"]}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def complete_correction(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> dict[str, Any]:
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, {"technical-correction-complete", "post-integration-correction-complete"}, payload)
        if replay is not None:
            return replay
        current = self.load()
        event = "technical-correction-complete" if current["state"] == "technical-correction" else "post-integration-correction-complete" if current["state"] == "post-integration-correction" else None
        if event is None:
            raise CogitoError("correction completion is not legal in the current state")
        started = [item for item in read_events(self.events_path) if item["type"] in {"verification-correction-required", "post-verification-correction-required"}]
        if not started or started[-1]["payload"].get("amendment_id") != amendment_id:
            raise CogitoError("correction completion does not match the amendment that opened this correction cycle")
        amendments = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        matching = [item for item in amendments if item["id"] == amendment_id]
        if len(matching) != 1:
            raise CogitoError("correction commit references an unknown Technical Amendment")
        if any(current["tasks"].get(task["id"], {}).get("status") != "complete" for task in matching[0].get("added_tasks", [])):
            raise CogitoError("correction cannot finish before amendment tasks complete")
        added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
        implementation_results = [item for item in current["agent_results"] if item.get("task_id") in added_ids and item.get("role") == "implementer" and item.get("status") == "complete"]
        if added_ids and (added_ids != {item.get("task_id") for item in implementation_results} or commit_id not in {item.get("head_commit") for item in implementation_results}):
            raise CogitoError("correction tasks require Gate-recorded Implementer Results")
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        message = self._git("show", "-s", "--format=%B", commit_id)
        if f"Cogito-Amendment: {amendment_id}" not in message:
            raise CogitoError("correction commit is missing the Cogito-Amendment trailer")
        package = self.approved_package()
        if current["state"] == "post-integration-correction" and (self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != commit_id):
            raise CogitoError("post-integration correction commit must be current delivery HEAD")
        if not added_ids and commit_id != self._git("rev-parse", "HEAD"):
            raise CogitoError("a correction without added tasks must use current delivery HEAD")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def enter_review_fix(self, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "review-fix-required")
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "reviewing":
            raise CogitoError("review fix is not legal in the current state")
        findings = [item for item in current["agent_results"] if item.get("role") == "reviewer" and item.get("status") == "needs-fix" and item.get("requested_transition") == "review-fix"]
        if not findings:
            raise CogitoError("review fix requires a Gate-recorded Reviewer Result with needs-fix")
        finding = findings[-1]
        payload = {"scope_within_contract": True, "review_task_id": finding["task_id"], "reviewer": finding["agent_id"], "review_head": finding["head_commit"]}
        validate_transition(self.workflow, current["state"], "review-fix-required", payload, current["counters"], current["limits"])
        return self.record("review-fix-required", payload, action_id, self._GATE_AUTHORITY)

    def complete_review_fix(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> dict[str, Any]:
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, "review-fix-complete", payload)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "review-fix":
            raise CogitoError("review fix completion is not legal in the current state")
        started = [item for item in read_events(self.events_path) if item["type"] == "review-fix-required"]
        if not started:
            raise CogitoError("review fix has no recorded Reviewer finding")
        amendment_events = [item for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        matching_events = [item for item in amendment_events if item["payload"]["amendment"].get("id") == amendment_id and item["sequence"] > started[-1]["sequence"]]
        matching = [item["payload"]["amendment"] for item in matching_events]
        if len(matching) != 1:
            raise CogitoError("review fix requires a new Technical Amendment bound to the current finding")
        added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
        if not added_ids or any(current["tasks"].get(task_id, {}).get("status") != "complete" for task_id in added_ids):
            raise CogitoError("review fix requires completed amendment tasks")
        implementer_results = [item for item in current["agent_results"] if item.get("task_id") in added_ids and item.get("role") == "implementer" and item.get("status") == "complete"]
        if {item.get("task_id") for item in implementer_results} != added_ids or commit_id not in {item.get("head_commit") for item in implementer_results}:
            raise CogitoError("review fix commit is not bound to its Implementer Results")
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        if f"Cogito-Amendment: {amendment_id}" not in self._git("show", "-s", "--format=%B", commit_id):
            raise CogitoError("review fix commit is missing the Cogito-Amendment trailer")
        validate_transition(self.workflow, current["state"], "review-fix-complete", payload, current["counters"], current["limits"])
        return self.record("review-fix-complete", payload, action_id, self._GATE_AUTHORITY)

    def record_retry(self, kind: str, reason: str, action_id: str | None = None) -> dict[str, Any]:
        event = {"transient": "transient-retry", "format": "format-repair-recorded"}.get(kind)
        if event is None or not reason.strip():
            raise CogitoError("retry kind must be transient or format and include a reason")
        payload = {"reason": reason}
        replay = self._replay(action_id, event, payload)
        if replay is not None:
            return replay
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def complete_integration(self, commit_id: str, slice_id: str | None = None, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, {"slice-integration-complete", "wave-integration-complete", "integration-complete"})
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "integrating":
            raise CogitoError("integration closure is not legal in the current state")
        package = self.approved_package()
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        if self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != commit_id:
            raise CogitoError("integration commit must be current HEAD on the delivery branch")
        target_slice = slice_id or "mini-package"
        task_ids = [task_id for task_id, task in current["tasks"].items() if (task.get("slice_id") or "mini-package") == target_slice]
        if not task_ids or any(current["tasks"][task_id].get("status") != "reviewed" for task_id in task_ids):
            raise CogitoError("integration requires every task in the target Slice to be independently reviewed")
        latest_implementation = {item.get("task_id"): item for item in current["agent_results"] if item.get("role") == "implementer" and item.get("status") == "complete"}
        source_heads = []
        for task_id in task_ids:
            result = latest_implementation.get(task_id)
            if not result:
                raise CogitoError("integration is missing a Gate-recorded implementation Result")
            self._git("merge-base", "--is-ancestor", result["head_commit"], commit_id)
            source_heads.append(result["head_commit"])
        history = read_events(self.events_path)
        prior_integrations = [item for item in history if item["type"] in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}]
        starts = [item for item in history if item["type"] == "start-gate-passed"]
        previous_head = prior_integrations[-1]["payload"]["commit_id"] if prior_integrations else starts[-1]["payload"]["delivery_head"]
        self._git("merge-base", "--is-ancestor", previous_head, commit_id)
        remaining_reviewed = any(task_id not in task_ids and task.get("status") == "reviewed" for task_id, task in current["tasks"].items())
        remaining_unintegrated = any(task_id not in task_ids and task.get("status") != "integrated" for task_id, task in current["tasks"].items())
        event = "slice-integration-complete" if remaining_reviewed else "wave-integration-complete" if remaining_unintegrated else "integration-complete"
        payload = {"commit_id": commit_id, "slice_id": target_slice, "task_ids": sorted(task_ids), "source_heads": sorted(source_heads), "previous_delivery_head": previous_head}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"], current["limits"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def add_amendment(self, amendment: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "technical-amendment-added")
        if replay is not None:
            recorded = [item for item in read_events(self.events_path) if item.get("action_id") == action_id][0]
            if recorded["payload"].get("amendment") != dict(amendment):
                raise CogitoError(f"action_id {action_id!r} was already used for different content")
            return replay
        package = self.approved_package()
        state = self.load()
        if state["state"] not in {"verifying", "reviewing", "review-fix", "post-integration-verification"}:
            raise CogitoError("Technical Amendments are only legal while handling a verification or review finding")
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        validate_amendment(package, prior, amendment)
        digest = effective_contract_hash(package, [*prior, amendment])
        payload = {"amendment": dict(amendment), "effective_contract_hash": digest}
        return self.record(
            "technical-amendment-added",
            payload,
            action_id, self._GATE_AUTHORITY,
        )

    def approve_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package(package)
        self._validate_policy(package)
        digest = package_hash(package)
        package["package_hash"] = digest
        relative = Path("docs") / "cogito" / "packages" / f"{self.run_id}.json"
        dependencies: dict[str, list[str]] = {item["id"]: [] for item in package["execution_dag"]["tasks"]}
        for edge in package["execution_dag"]["edges"]:
            source, target = _edge_pair(edge)
            dependencies[target].append(source)
        tasks = [{**dict(item), "depends_on": dependencies[item["id"]]} for item in package["execution_dag"]["tasks"]]
        replay = self._replay(action_id, "package-approved")
        if replay is not None:
            recorded = [item for item in read_events(self.events_path) if item.get("action_id") == action_id][0]
            if recorded["payload"].get("package_hash") != digest:
                raise CogitoError(f"action_id {action_id!r} was already used for a different Package")
            return replay
        current = self.load()
        if current["state"] != "awaiting-package-approval":
            raise CogitoError("Package approval is not legal in the current state")
        if current.get("candidate_package_hash") != digest:
            raise CogitoError("approved Package differs from the Gate-validated candidate")
        target = self.root / relative
        graph_path = self.root / "docs" / "cogito" / "project-graph.json"
        graph_before = graph_path.read_bytes() if graph_path.exists() else None
        if target.exists():
            existing_package = _load_json(target)
            if package_hash(existing_package) != digest:
                raise CogitoError("canonical immutable Package already exists with different content")
        else:
            atomic_write_json(target, package)
        graph = self._formalize_project_graph(package, graph_path)
        event_payload = {"approved": True, "package_path": relative.as_posix(), "package_hash": digest, "tasks": tasks, "max_workers": package["policy_snapshot"]["max_workers"], "project_graph_hash": hash_json(graph), "project_graph_snapshot": graph, "limits": package["limits"]}
        atomic_write_json(graph_path, graph)
        try:
            state = self.record(
                "package-approved",
                event_payload,
                action_id, self._GATE_AUTHORITY,
            )
        except Exception:
            try:
                if not any(item["type"] == "package-approved" for item in read_events(self.events_path)):
                    target.unlink()
            except OSError:
                pass
            if graph_before is None:
                try:
                    graph_path.unlink()
                except OSError:
                    pass
            else:
                graph_path.write_bytes(graph_before)
            raise
        target.chmod(0o444)
        return state

    def start_gate(self, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "start-gate-passed")
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "start-gate":
            raise CogitoError("Start Gate is not legal in the current state")
        package = self.approved_package()
        self._validate_policy(package)
        head = self._git("rev-parse", "HEAD")
        self._git("cat-file", "-e", f"{package['baseline_commit']}^{{commit}}")
        if self._git("branch", "--show-current") != package["delivery_branch"]:
            raise CogitoError("Start Gate is not on the Package delivery branch")
        self._git("merge-base", "--is-ancestor", package["baseline_commit"], head)
        allowed_control = {self.load()["package_path"], "docs/cogito/project-graph.json"}
        for item in package["slices"]:
            for document in (item["spec"], item["plan"]):
                self._validate_content_hash(document["path"], document["hash"])
                allowed_control.add(document["path"])
        for source in package["source_registry"]:
            self._validate_content_hash(source["path"], source["hash"])
            if source["disposition"] in {"adopted", "updated"}:
                allowed_control.add(source["path"])
        graph = _load_json(self.root / "docs" / "cogito" / "project-graph.json")
        if hash_json(graph) != current.get("project_graph_hash") or graph.get("active_run_id") != self.run_id or any(item["id"] not in graph.get("slices", {}) for item in package["slices"]):
            raise CogitoError("Project Graph is not formalized for this Package")
        dirty = []
        for line in self._git("status", "--porcelain", "--untracked-files=all").splitlines():
            path = line[3:].split(" -> ")[-1] if len(line) > 3 else ""
            if not path.startswith(".cogito/") and path not in allowed_control:
                dirty.append(line)
        if dirty:
            raise CogitoError("Start Gate requires a clean delivery checkout")
        payload = {
            "baseline_valid": True, "contract_valid": True, "worktrees_valid": self._worker_layout_valid(package),
            "delivery_head": head, "package_hash": package_hash(package),
        }
        validate_transition(self.workflow, current["state"], "start-gate-passed", payload, current["counters"])
        return self.record("start-gate-passed", payload, action_id, self._GATE_AUTHORITY)

    def decide_post_verification(self, passed_evidence: Sequence[Mapping[str, Any]], reviewer_escalation: bool = False, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, {"human-review-required", "auto-accept-ready"})
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "post-integration-verification":
            raise CogitoError("post-verification decision is not legal in the current state")
        package = self.approved_package()
        self._validate_evidence(package, passed_evidence, require_current_head=True)
        human = package["human_gate"]
        human_required = bool(reviewer_escalation or human.get("high_risk_hotspots") or any(item["applicable"] for item in human["predicates"]))
        event = "human-review-required" if human_required else "auto-accept-ready"
        payload = {"passed": True, "human_required": human_required, "evidence": [item["evidence_path"] for item in passed_evidence], "reviewer_escalation": bool(reviewer_escalation), "delivery_head": self._git("rev-parse", "HEAD")}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY)

    def resume_gate(self, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "resume")
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "blocked" or not current.get("blocked_from"):
            raise CogitoError("only a blocked run with a recorded origin may resume")
        target = current["blocked_from"]
        if target not in self.workflow["resume_targets"]:
            raise CogitoError("blocked origin is not a legal resume target")
        if current.get("package_path"):
            package = self.approved_package()
            self._validate_policy(package)
            head = self._git("rev-parse", "HEAD")
            if self._git("branch", "--show-current") != package["delivery_branch"]:
                raise CogitoError("Resume Gate delivery branch drifted")
            self._git("merge-base", "--is-ancestor", package["baseline_commit"], head)
            if target != "finalizing":
                graph = _load_json(self.root / "docs/cogito/project-graph.json")
                if hash_json(graph) != current.get("project_graph_hash") or graph.get("active_run_id") != self.run_id:
                    raise CogitoError("Resume Gate Project Graph drifted")
            for task in current["tasks"].values():
                if task.get("status") in {"leased", "running"}:
                    worktree = Path(str(task.get("worktree", "")))
                    if not worktree.is_dir() or self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
                        raise CogitoError("Resume Gate found a drifted active worker lease")
                    worker_head = self._git_at(worktree, "rev-parse", "HEAD")
                    self._git("merge-base", "--is-ancestor", task.get("base_commit"), worker_head)
                    recorded = [item for item in current["agent_results"] if item.get("task_id") == task.get("id")]
                    if recorded and worker_head != recorded[-1].get("head_commit"):
                        raise CogitoError("Resume Gate worker HEAD differs from its recorded Result")
            for evidence_path, ledger in current.get("evidence", {}).items():
                evidence = _load_json(Path(evidence_path))
                if hash_json(evidence) != ledger.get("evidence_hash"):
                    raise CogitoError("Resume Gate found tampered evidence")
        reconciliation = hash_json({"target": target, "head": self._git("rev-parse", "HEAD"), "event_hash": current["last_event_hash"]})
        return self.record("resume", {"target": target, "validated": True, "reconciliation_hash": reconciliation}, action_id, self._GATE_AUTHORITY)

    def approve_human_gate(self, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "human-approved")
        if replay is not None:
            return replay
        current = self.load()
        payload = {"approved": True}
        validate_transition(self.workflow, current["state"], "human-approved", payload, current["counters"])
        return self.record("human-approved", payload, action_id, self._GATE_AUTHORITY)

    def finalize(self, result_path: str, project_graph_path: str, final_commit: str, action_id: str | None = None) -> dict[str, Any]:
        replay = self._replay(action_id, "finalization-complete")
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "finalizing":
            raise CogitoError("finalization is not legal in the current state")
        package = self.approved_package()
        result_rel, graph_rel = Path(result_path), Path(project_graph_path)
        for path in (result_rel, graph_rel):
            if path.is_absolute() or ".." in path.parts:
                raise CogitoError("finalization paths must be repository-relative")
        expected_result = Path("docs") / "cogito" / "results" / f"{self.run_id}.json"
        if result_rel != expected_result or graph_rel != Path("docs/cogito/project-graph.json"):
            raise CogitoError("finalization must use canonical Result and Project Graph paths")
        self._git("cat-file", "-e", f"{final_commit}^{{commit}}")
        if self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != final_commit:
            raise CogitoError("final commit must be current HEAD on the frozen delivery branch")
        result = json.loads(self._git("show", f"{final_commit}:{result_rel.as_posix()}"))
        graph = json.loads(self._git("show", f"{final_commit}:{graph_rel.as_posix()}"))
        required_result = {"schema_version", "run_id", "status", "package_hash", "effective_contract_hash", "integration_commits", "slice_dispositions", "checks", "reviews", "amendments", "human_gate", "remaining_risks"}
        if not isinstance(result, dict) or not required_result <= result.keys() or result.get("schema_version") != "3.0":
            raise CogitoError("final Result is structurally incomplete")
        if result.get("run_id") != self.run_id or result.get("package_hash") != package_hash(package):
            raise CogitoError("final Result is not bound to this run and Package")
        if result.get("effective_contract_hash") != current.get("effective_contract_hash"):
            raise CogitoError("final Result effective contract hash does not match the run")
        if result.get("status") != "accepted" or any(key in result for key in ("final_commit", "result_commit", "finalization_commit")):
            raise CogitoError("Result must be accepted and must not self-reference its containing commit")
        if graph.get("active_run_id") is not None:
            raise CogitoError("final Project Graph must clear active_run_id")
        approval_events = [item for item in read_events(self.events_path) if item["type"] == "package-approved"]
        approved_graph = approval_events[-1]["payload"].get("project_graph_snapshot")
        if not isinstance(approved_graph, dict) or graph.get("schema_version") != "3.0" or graph.get("dependencies") != approved_graph.get("dependencies"):
            raise CogitoError("final Project Graph is not a valid evolution of the approved graph")
        owned_slices = {item["id"] for item in package["slices"]}
        if {key: value for key, value in graph.get("slices", {}).items() if key not in owned_slices} != {key: value for key, value in approved_graph.get("slices", {}).items() if key not in owned_slices}:
            raise CogitoError("final Project Graph changed unrelated Slice history")
        expected_slices = {item["id"] for item in package["slices"]}
        if set(result["slice_dispositions"]) != expected_slices or any(value != "accepted" for value in result["slice_dispositions"].values()):
            raise CogitoError("Result does not close every Package Slice")
        for slice_id in expected_slices:
            graph_slice = graph.get("slices", {}).get(slice_id, {})
            if graph_slice.get("disposition") != "accepted" or graph_slice.get("completed_by") != self.run_id:
                raise CogitoError("Project Graph does not accept every Package Slice")
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        if [item.get("id") for item in result["amendments"]] != [item["id"] for item in prior] or any(not item.get("commit_id") for item in result["amendments"]):
            raise CogitoError("Result amendment summary is incomplete or out of order")
        completion_commits = {
            item["payload"].get("amendment_id"): item["payload"].get("commit_id")
            for item in read_events(self.events_path)
            if item["type"] in {"technical-correction-complete", "post-integration-correction-complete", "review-fix-complete"}
        }
        if any(completion_commits.get(item["id"]) != item["commit_id"] for item in result["amendments"]):
            raise CogitoError("Result amendment commits do not match correction history")
        effective = materialize_contract(package, prior)
        required_checks = {item["id"] for item in effective["checks"] if item.get("required", True)}
        passed_checks = {item.get("id") for item in result["checks"] if item.get("status") == "passed" and item.get("evidence")}
        if not required_checks <= passed_checks:
            raise CogitoError("Result does not include passed evidence for every required check")
        if not isinstance(result["remaining_risks"], list) or not isinstance(result["integration_commits"], list):
            raise CogitoError("Result risks and integration commits must be arrays")
        integration_events = [item["payload"]["commit_id"] for item in read_events(self.events_path) if item["type"] in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}]
        if result["integration_commits"] != integration_events:
            raise CogitoError("Result integration commits do not exactly match Gate history")
        for commit in result["integration_commits"]:
            self._git("cat-file", "-e", f"{commit}^{{commit}}")
            self._git("merge-base", "--is-ancestor", commit, final_commit)
        for item in result["amendments"]:
            self._git("cat-file", "-e", f"{item['commit_id']}^{{commit}}")
            if f"Cogito-Amendment: {item['id']}" not in self._git("show", "-s", "--format=%B", item["commit_id"]):
                raise CogitoError("Result references an amendment commit without its trailer")
        events = read_events(self.events_path)
        post_events = [item for item in events if item["type"] in {"human-review-required", "auto-accept-ready"}]
        expected_evidence = set(post_events[-1]["payload"]["evidence"])
        result_evidence = {item.get("evidence") for item in result["checks"]}
        if result_evidence != expected_evidence:
            raise CogitoError("Result evidence does not exactly match the final Gate verification ledger")
        if package["kind"] != "maintenance" and self._git("rev-parse", f"{final_commit}^") != post_events[-1]["payload"].get("delivery_head"):
            raise CogitoError("final commit must directly follow the post-verification delivery HEAD")
        human_was_required = any(item["type"] == "human-review-required" for item in events)
        if human_was_required and not any(item["type"] == "human-approved" for item in events):
            raise CogitoError("Result cannot claim Human Gate approval without a recorded approval event")
        expected_human = {"required": human_was_required, "outcome": "approved" if human_was_required else "not-required"}
        if result["human_gate"] != expected_human:
            raise CogitoError("Result human gate outcome does not match event history")
        reviewer_ids = {item.get("agent_id") for item in current.get("agent_results", []) if item.get("role") == "reviewer" and item.get("status") == "complete"}
        if package["kind"] != "maintenance" and reviewer_ids != {item.get("reviewer") for item in result["reviews"]}:
            raise CogitoError("Result reviewers do not exactly match recorded independent Reviewers")
        if package["kind"] == "maintenance":
            starts = [item for item in read_events(self.events_path) if item["type"] == "start-gate-passed"]
            if len(starts) != 1 or self._git("rev-parse", f"{final_commit}^") != starts[0]["payload"]["delivery_head"]:
                raise CogitoError("Maintenance must finalize as one commit from the Start Gate head")
        payload = {"result_path": result_rel.as_posix(), "project_graph_path": graph_rel.as_posix(), "final_commit": final_commit, "final_tree": self._git("rev-parse", f"{final_commit}^{{tree}}"), "project_graph_updated": True}
        validate_transition(self.workflow, current["state"], "finalization-complete", payload, current["counters"])
        return self.record("finalization-complete", payload, action_id, self._GATE_AUTHORITY)

    def completion_report(self) -> dict[str, Any]:
        current = self.load()
        if current["state"] != "accepted":
            raise CogitoError("completion report is only available for an accepted run")
        final_events = [item for item in read_events(self.events_path) if item["type"] == "finalization-complete"]
        final = final_events[-1]["payload"]
        result = json.loads(self._git("show", f"{final['final_commit']}:{final['result_path']}"))
        return {
            "run_id": self.run_id, "status": "accepted", "final_commit": final["final_commit"],
            "checks": result["checks"], "reviews": result["reviews"], "amendments": result["amendments"],
            "human_gate": result["human_gate"], "remaining_risks": result["remaining_risks"],
        }

    def _git(self, *args: str) -> str:
        try:
            result = subprocess.run(["git", "-C", str(self.root), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CogitoError(f"Git validation failed: {exc}") from exc
        return result.stdout.strip()

    def _git_at(self, directory: Path, *args: str) -> str:
        try:
            result = subprocess.run(["git", "-C", str(directory), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        except (OSError, subprocess.SubprocessError) as exc:
            raise CogitoError(f"worktree Git validation failed: {exc}") from exc
        return result.stdout.strip()

    def _task_worktree(self, task: Mapping[str, Any], package: Mapping[str, Any]) -> tuple[Path, str]:
        if package["kind"] in {"maintenance", "documentation"}:
            return self.root, package["delivery_branch"]
        slices = {item["id"]: item for item in package["slices"]}
        slice_item = slices.get(task.get("slice_id"))
        if not slice_item:
            raise CogitoError("task has no owning Slice")
        worktree = (self.root / slice_item["worker"]["worktree"]).resolve()
        try:
            worktree.relative_to(self.root)
        except ValueError as exc:
            raise CogitoError("worker worktree escapes repository root") from exc
        if not worktree.is_dir() or self._git_at(worktree, "branch", "--show-current") != slice_item["worker"]["branch"]:
            raise CogitoError("dedicated worker branch/worktree is not ready")
        return worktree, slice_item["worker"]["branch"]

    def _validate_content_hash(self, relative: str, expected: str) -> None:
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (ValueError, OSError) as exc:
            raise CogitoError(f"cannot validate Package content {relative}: {exc}") from exc
        if actual != expected:
            raise CogitoError(f"Package content hash drifted: {relative}")

    def _replay(self, action_id: str | None, event_type: str | set[str], payload: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
        if not action_id or not self.events_path.exists():
            return None
        expected = {event_type} if isinstance(event_type, str) else event_type
        matches = [item for item in read_events(self.events_path) if item.get("action_id") == action_id]
        if not matches:
            return None
        if len(matches) != 1 or matches[0]["type"] not in expected or (payload is not None and matches[0]["payload"] != dict(payload)):
            raise CogitoError(f"action_id {action_id!r} was already used for different content")
        return self.load()

    def _worker_layout_valid(self, package: Mapping[str, Any]) -> bool:
        if package["kind"] in {"maintenance", "documentation"}:
            return True
        branches = [item["worker"]["branch"] for item in package["slices"]]
        worktrees = [item["worker"]["worktree"] for item in package["slices"]]
        return (
            len(branches) == len(set(branches)) and len(worktrees) == len(set(worktrees))
            and package["delivery_branch"] not in branches
            and all(_safe_repo_path(path) and not (self.root / path).exists() for path in worktrees)
        )

    def _formalize_project_graph(self, package: Mapping[str, Any], path: Path) -> dict[str, Any]:
        if path.exists():
            graph = _load_json(path)
            if graph.get("schema_version") != "3.0" or not isinstance(graph.get("slices"), dict) or not isinstance(graph.get("dependencies"), list):
                raise CogitoError("existing Project Graph is invalid")
            if graph.get("active_run_id") not in (None, self.run_id):
                raise CogitoError("another Cogito run is active in Project Graph")
        else:
            graph = {"schema_version": "3.0", "active_run_id": None, "slices": {}, "dependencies": []}
        for item in package["slices"]:
            if item["id"] in graph["slices"] and graph["slices"][item["id"]].get("disposition") not in {"planned", "active"}:
                raise CogitoError(f"Slice id is already finalized: {item['id']}")
            graph["slices"][item["id"]] = {
                "kind": item["type"], "disposition": "active", "dependencies": [],
                "spec": dict(item["spec"]), "plan": dict(item["plan"]),
                "lineage": item.get("lineage", []), "introduced_by": self.run_id,
            }
        task_slices = {task["id"]: task.get("slice_id") for task in package["execution_dag"]["tasks"]}
        dependencies = {(item["from"], item["to"]) for item in graph["dependencies"]}
        for edge in package["execution_dag"]["edges"]:
            source, target = _edge_pair(edge)
            from_slice, to_slice = task_slices.get(source), task_slices.get(target)
            if from_slice and to_slice and from_slice != to_slice:
                dependencies.add((from_slice, to_slice))
        graph["dependencies"] = [{"from": source, "to": target} for source, target in sorted(dependencies)]
        for slice_id, item in graph["slices"].items():
            item["dependencies"] = sorted(source for source, target in dependencies if target == slice_id)
        graph["active_run_id"] = self.run_id
        return graph

    def _validate_policy(self, package: Mapping[str, Any]) -> None:
        policy_path = self.root / "docs" / "cogito" / "project-policy.json"
        snapshot = package["policy_snapshot"]
        if not policy_path.exists():
            if snapshot.get("fetch_allowed") is not False:
                raise CogitoError("fetch is not authorized without Project Policy")
            return
        project = _load_json(policy_path)
        if project.get("schema_version") != "3.0":
            raise CogitoError("Project Policy schema_version must be 3.0")
        if snapshot.get("hash") != hash_json(project):
            raise CogitoError("Package policy snapshot does not match current Project Policy")
        project_workers = int(project.get("max_workers", 3))
        if snapshot["max_workers"] > project_workers:
            raise CogitoError("Package max_workers is looser than Project Policy")
        if snapshot.get("fetch_allowed") is True and project.get("fetch_allowed") is not True:
            raise CogitoError("Package cannot authorize fetch beyond Project Policy")
        required_checks = set(project.get("required_checks", []))
        if not required_checks <= {item["id"] for item in package["checks"]}:
            raise CogitoError("Package omits checks required by Project Policy")
        allowed_env = set(project.get("allowed_environment", []))
        for check in package["checks"]:
            if set(check.get("env_allowlist", [])) - allowed_env:
                raise CogitoError("Package check environment exceeds Project Policy")
        project_human = project.get("human_gate", {})
        package_predicates = {item["id"]: item["applicable"] for item in package["human_gate"]["predicates"]}
        for predicate in project_human.get("predicates", []):
            if predicate.get("applicable") is True and package_predicates.get(predicate.get("id")) is not True:
                raise CogitoError("Package removes a Human Gate required by Project Policy")
        if not set(project_human.get("high_risk_hotspots", [])) <= set(package["human_gate"]["high_risk_hotspots"]):
            raise CogitoError("Package removes high-risk hotspots required by Project Policy")
        if project_human.get("required") is True and not (
            package["human_gate"]["high_risk_hotspots"] or any(package_predicates.values())
        ):
            raise CogitoError("Project Policy requires a Human Gate")

    def _validate_review(self, payload: Mapping[str, Any]) -> None:
        package = self.approved_package()
        if payload.get("review_exemption") is True:
            if package["kind"] != "maintenance" or not all(package["maintenance_guards"].values()):
                raise CogitoError("independent-review exemption is only valid for objectively low-risk Maintenance")
            state = self.load()
            payload["reviews"] = sorted(task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified")
            if not payload["reviews"]:
                raise CogitoError("review exemption requires verified Maintenance tasks")
            payload["approved"] = True
            payload["independent"] = False
            return
        state = self.load()
        expected = {task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified"}
        if not expected:
            raise CogitoError("review approval requires completed implementation tasks")
        closed: set[str] = set()
        latest: dict[str, Mapping[str, Any]] = {}
        for result in state["agent_results"]:
            if result.get("role") == "reviewer":
                latest[str(result.get("task_id"))] = result
        for result in latest.values():
            task = state["tasks"].get(result.get("task_id"), {})
            if (
                result.get("role") == "reviewer" and result.get("status") == "complete"
                and result.get("requested_transition") == "review-approved"
                and result.get("reviewed_implementer") == task.get("agent_id")
                and result.get("agent_id") != task.get("agent_id")
            ):
                closed.add(result["task_id"])
        if closed != expected:
            raise CogitoError("every completed implementation task requires a Gate-recorded independent Reviewer Result")
        payload["reviews"] = sorted(closed)
        payload["approved"] = True
        payload["independent"] = True

    def _validate_evidence(self, package: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]], require_current_head: bool = False) -> None:
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        effective = materialize_contract(package, prior)
        required = {item["id"]: item for item in effective["checks"] if item.get("required", True)}
        supplied = {item.get("check_id"): item for item in evidence}
        events = read_events(self.events_path)
        anchors = {"implementation-complete", "technical-correction-complete", "review-fix-complete"}
        if require_current_head:
            anchors = {"integration-complete", "post-integration-correction-complete"}
        anchor_sequence = max((item["sequence"] for item in events if item["type"] in anchors), default=0)
        if set(required) - set(supplied):
            raise CogitoError("required verification evidence is missing")
        for check_id, check in required.items():
            item = supplied[check_id]
            evidence_path = Path(str(item.get("evidence_path", ""))).resolve()
            try:
                evidence_path.relative_to((self.run_dir / "evidence").resolve())
            except ValueError as exc:
                raise CogitoError(f"evidence path is outside this run for {check_id}") from exc
            if not evidence_path.is_file():
                raise CogitoError(f"immutable evidence file is missing for {check_id}")
            recorded = _load_json(evidence_path)
            if recorded != item:
                raise CogitoError(f"evidence payload does not match its immutable file for {check_id}")
            ledger = self.load().get("evidence", {}).get(str(evidence_path))
            if not ledger or ledger.get("evidence_hash") != hash_json(recorded) or ledger.get("check_id") != check_id:
                raise CogitoError(f"evidence was not produced and recorded by the controlled runner for {check_id}")
            if int(ledger.get("event_sequence") or 0) <= anchor_sequence:
                raise CogitoError(f"evidence predates the current verification cycle for {check_id}")
            if item.get("passed") is not True or item.get("check_hash") != hash_json(check) or item.get("effective_contract_hash") != effective["effective_contract_hash"]:
                raise CogitoError(f"evidence binding failed for {check_id}")
            binding = item.get("worktree_binding")
            if not isinstance(binding, dict) or binding.get("snapshot_hash") != item.get("tree_hash"):
                raise CogitoError(f"working-tree binding is missing for {check_id}")
            binding_body = {key: value for key, value in binding.items() if key != "snapshot_hash"}
            if hash_json(binding_body) != binding["snapshot_hash"]:
                raise CogitoError(f"working-tree binding hash is invalid for {check_id}")
            if require_current_head and item.get("head_commit") != self._git("rev-parse", "HEAD"):
                raise CogitoError(f"post-integration evidence is not bound to current HEAD for {check_id}")

    def next_action(self) -> dict[str, Any]:
        projection = self.load()
        state = projection["state"]
        actions = {
            "preparing": "draft-shared-understanding", "awaiting-shared-confirmation": "request-shared-confirmation",
            "boundary-analysis": "run-boundary-gate", "package-preparing": "author-development-package",
            "awaiting-package-approval": "request-package-approval", "start-gate": "validate-latest-baseline",
            "executing": "dispatch-ready-workers", "verifying": "run-controlled-checks",
            "technical-correction": "dispatch-in-scope-correction", "reviewing": "dispatch-independent-reviewer",
            "review-fix": "dispatch-review-fix", "integrating": "integrate-serially",
            "post-integration-verification": "run-post-integration-checks", "awaiting-human": "request-human-review",
            "post-integration-correction": "dispatch-post-integration-correction",
            "finalizing": "write-result-and-finalize", "blocked": "resolve-and-run-resume-gate",
            "accepted": "report-completion", "cancelled": "report-cancellation",
        }
        if state not in actions:
            raise CogitoError(f"no action is defined for state {state!r}")
        output: dict[str, Any] = {"state": state, "next_action": actions[state]}
        if state == "preparing" and projection["kind"] in {"maintenance", "documentation"}:
            output["next_action"] = "assess-mini-package-eligibility"
        if state == "executing":
            tasks = list(projection["tasks"].values())
            edges = [
                {"from": dependency, "to": task["id"]}
                for task in tasks for dependency in task.get("depends_on", [])
            ]
            output["ready_tasks"] = [item["id"] for item in ready_tasks(tasks, edges, projection["max_workers"])]
            active_slices = {item.get("slice_id") or "mini-package" for item in tasks if item.get("status") in {"leased", "running"}}
            output["worker_capacity"] = max(0, projection["max_workers"] - len(active_slices))
        if state == "accepted":
            output["report"] = self.completion_report()
        return output
