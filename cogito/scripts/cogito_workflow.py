"""Workflow loading, guards, transitions, and derived diagrams."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from cogito_common import CogitoError, load_json


DEFAULT_WORKFLOW = Path(__file__).resolve().parents[1] / "workflows" / "cogito-v3.json"


def load_workflow(path: str | Path | None = None) -> dict[str, Any]:
    workflow = load_json(Path(path) if path else DEFAULT_WORKFLOW)
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


def _required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


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
    candidates = [item for item in workflow["transitions"] if item["from"] == state and item["event"] == event]
    candidates += [item for item in workflow.get("global_events", []) if item["event"] == event]
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
