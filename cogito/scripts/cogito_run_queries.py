"""Pure next-action guidance and completion report presentation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from cogito_state_types import RunState
from cogito_common import CogitoError
from cogito_result_contract import validate_result
from cogito_scheduler import ready_tasks
from cogito_task_rules import effective_slice_id, is_active_task


def derive_next_action(projection: RunState) -> dict[str, Any]:
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
        "human-feedback-triage": "classify-human-feedback",
        "human-correction": "dispatch-human-correction",
        "human-correction-verifying": "verify-human-correction",
        "human-correction-reviewing": "review-human-correction",
        "finalizing": "write-result-and-finalize", "blocked": "resolve-and-run-resume-gate",
        "accepted": "report-completion", "cancelled": "report-cancellation", "superseded": "continue-successor",
    }
    if state not in actions:
        raise CogitoError(f"no action is defined for state {state!r}")
    output: dict[str, Any] = {"state": state, "next_action": actions[state]}
    if projection.get("pending_checkpoint") and state not in {"blocked", "cancelled", "superseded"}:
        output.update(next_action="commit-stage-artifacts", checkpoint=deepcopy(projection["pending_checkpoint"]))
        return output
    human = projection.get("human")
    if human:
        output.update(feedback_id=human["feedback"]["id"],
                      human_corrections=projection["counters"].get("human_corrections", 0),
                      human_correction_limit=min(3, projection["limits"].get("human_corrections", 3)))
        if human.get("escalated") and state not in {'accepted', 'cancelled', 'superseded'}:
            output["next_action"] = "prepare-human-feedback-replan"
        elif state == "human-feedback-triage" and human.get("triage"):
            output["next_action"] = {"change": "prepare-human-feedback-replan", "clarify": "clarify-human-feedback", "local": "prepare-human-correction"}[human["triage"]["route"]]
        if human.get("exhausted") and state == "blocked":
            output["next_action"] = "request-human-correction-budget-decision"
        if human.get('pending_feedback'):
            output['pending_feedback'] = human['pending_feedback']
            if state == 'awaiting-human':
                output['next_action'] = 'record-pending-human-feedback'
    planning = projection.get("planning")
    if planning and not projection.get("package_hash"):
        output["planning_round"] = planning["round"]
        output["candidate_package_hash"] = projection["candidate_package_hash"]
        output["proposal_hash"] = planning["proposal_hash"]
        if planning["revision"]:
            output["revision_reason"] = planning["revision"]["request"]["reason"]
            if state == "awaiting-package-approval" and not planning["review"]:
                output["next_action"] = "request-independent-planning-review"
    if state == "awaiting-shared-confirmation":
        output["shared_understanding_hash"] = projection["shared_understanding_hash"]
    if state == "preparing" and projection["kind"] in {"maintenance", "documentation"}:
        output["next_action"] = "assess-mini-package-eligibility"
    if state == "executing":
        tasks = list(projection["tasks"].values())
        edges = [
            {"from": dependency, "to": task["id"]}
            for task in tasks for dependency in task.get("depends_on", [])
        ]
        output["ready_tasks"] = [item["id"] for item in ready_tasks(tasks, edges, projection["max_workers"])]
        if not output['ready_tasks'] and any(t.get('adoption') and t['status']=='reviewed' for t in tasks):
            output['next_action'] = 'advance-adoptions'
        active_slices = {effective_slice_id(item) for item in tasks if is_active_task(item)}
        output["worker_capacity"] = max(0, projection["max_workers"] - len(active_slices))
    return output


def build_completion_report(run_id: str, final_commit: str, result: Mapping[str, Any]) -> dict[str, Any]:
    """Present a validated committed Result without sharing its mutable fields."""
    validate_result(result)
    report = deepcopy({
        "run_id": run_id, "status": "accepted", "final_commit": final_commit,
        "checks": result["checks"], "reviews": result["reviews"], "amendments": result["amendments"],
        "human_gate": result["human_gate"], "remaining_risks": result["remaining_risks"],
    })
    for amendment in report["amendments"]:
        if "commit_id" not in amendment:
            amendment["commit_id"] = final_commit
    return report
