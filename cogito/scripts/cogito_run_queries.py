"""Pure next-action guidance and completion report presentation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from cogito_common import CogitoError
from cogito_result_contract import validate_result
from cogito_scheduler import ready_tasks
from cogito_task_rules import effective_slice_id, is_active_task


def derive_next_action(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Describe the next step; the caller attaches committed data for accepted runs."""
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
        active_slices = {effective_slice_id(item) for item in tasks if is_active_task(item)}
        output["worker_capacity"] = max(0, projection["max_workers"] - len(active_slices))
    return output


def build_completion_report(run_id: str, final_commit: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Present a validated committed Result without sharing its mutable fields."""
    validate_result(result)
    return deepcopy({
        "run_id": run_id, "status": "accepted", "final_commit": final_commit,
        "checks": result["checks"], "reviews": result["reviews"], "amendments": result["amendments"],
        "human_gate": result["human_gate"], "remaining_risks": result["remaining_risks"],
    })
