"""Gate policy, review, and immutable-evidence validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from cogito_state_types import AgentResult, RunState
from cogito_common import CogitoError, hash_json, load_json
from cogito_contract_fields import GIT_OBJECT_RE
from cogito_contracts import (
    DEFAULT_MAX_CHECK_OUTPUT_BYTES,
    validate_project_policy,
    validate_required_checks,
)
from cogito_evidence_contract import validate_check_evidence


def validate_policy(root: Path, package: Mapping[str, Any]) -> None:
    """Ensure a Package is no less restrictive than Project Policy."""
    policy_path = root / "docs" / "cogito" / "project-policy.json"
    snapshot = package["policy_snapshot"]
    if not policy_path.exists():
        if snapshot.get("fetch_allowed") is not False:
            raise CogitoError("fetch is not authorized without Project Policy")
        if snapshot.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES) > DEFAULT_MAX_CHECK_OUTPUT_BYTES:
            raise CogitoError("Package check output limit is looser than the default Project Policy")
        _validate_environment_policy(package, {})
        return

    project = load_json(policy_path)
    validate_project_policy(project)
    if snapshot.get("hash") != hash_json(project):
        raise CogitoError("Package policy snapshot does not match current Project Policy")
    if snapshot["max_workers"] > int(project.get("max_workers", 3)):
        raise CogitoError("Package max_workers is looser than Project Policy")
    if snapshot.get("fetch_allowed") is True and project.get("fetch_allowed") is not True:
        raise CogitoError("Package cannot authorize fetch beyond Project Policy")
    project_output_limit = project.get(
        "max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES
    )
    if snapshot.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES) > project_output_limit:
        raise CogitoError("Package check output limit is looser than Project Policy")

    validate_required_checks(package["checks"], project.get("required_checks", []), "Project Policy")
    _validate_environment_policy(package, project)

    project_human = project.get("human_gate", {})
    package_predicates = {
        item["id"]: item["applicable"] for item in package["human_gate"]["predicates"]
    }
    for predicate in project_human.get("predicates", []):
        if predicate.get("applicable") is True and package_predicates.get(predicate.get("id")) is not True:
            raise CogitoError("Package removes a Human Gate required by Project Policy")
    if not set(project_human.get("high_risk_hotspots", [])) <= set(
        package["human_gate"]["high_risk_hotspots"]
    ):
        raise CogitoError("Package removes high-risk hotspots required by Project Policy")
    if project_human.get("required") is True and not (
        package["human_gate"]["high_risk_hotspots"] or any(package_predicates.values())
    ):
        raise CogitoError("Project Policy requires a Human Gate")


def _validate_environment_policy(
    package: Mapping[str, Any], project: Mapping[str, Any],
) -> None:
    """Bound future Amendment permissions, not just checks already in the Package.

    Missing Project Policy grants no additional environment access. The runner's
    fixed base environment is separate and is not changed by these allowlists.
    """
    allowed_env = set(project.get("allowed_environment", []))
    if set(package["policy_snapshot"].get("allowed_environment", [])) - allowed_env:
        raise CogitoError("Package policy snapshot environment exceeds Project Policy")
    for check in package["checks"]:
        if set(check.get("env_allowlist", [])) - allowed_env:
            raise CogitoError("Package check environment exceeds Project Policy")


def derive_review_decision(
    package: Mapping[str, Any],
    state: RunState,
    *, review_exemption: bool = False,
) -> dict[str, Any]:
    """Return the current wave's Gate verdict without IO or input mutation.

    Inputs are the validated Package and recorded run state. Approval and
    reviewer independence are derived here, never accepted from a request.
    """
    if review_exemption is True:
        if package["kind"] != "maintenance" or not all(package["maintenance_guards"].values()):
            raise CogitoError(
                "independent-review exemption is only valid for objectively low-risk Maintenance"
            )
        reviews = sorted(
            task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified"
        )
        if not reviews:
            raise CogitoError("review exemption requires verified Maintenance tasks")
        return {"reviews": reviews, "approved": True, "independent": False}

    expected = {
        task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified"
    }
    if not expected:
        raise CogitoError("review approval requires completed implementation tasks")
    latest: dict[str, AgentResult] = {}
    for result in state["agent_results"]:
        if result.get("role") == "reviewer":
            latest[str(result.get("task_id"))] = result
    missing_task: Mapping[str, Any] = {}
    closed = {
        result["task_id"]
        for result in latest.values()
        if result.get("task_id") in expected
        and result.get("status") == "complete"
        and result.get("requested_transition") == "review-approved"
        and result.get("reviewed_implementer")
        == state["tasks"].get(result.get("task_id"), missing_task).get("agent_id")
        and result.get("agent_id")
        != state["tasks"].get(result.get("task_id"), missing_task).get("agent_id")
    }
    if closed != expected:
        raise CogitoError(
            "every completed implementation task requires a Gate-recorded independent Reviewer Result"
        )
    return {"reviews": sorted(closed), "approved": True, "independent": True}


def validate_evidence(
    package: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    ledger: Mapping[str, Mapping[str, Any]],
    recorded_evidence: Mapping[str, Mapping[str, Any]],
    *,
    effective_contract: Mapping[str, Any],
    phase: Literal["implementation", "post-integration"],
    current_head: str | None = None,
    validate_supplied: bool = False,
) -> None:
    """Validate loaded evidence against one contract, ledger, and event snapshot.

    The caller materializes the contract and checks file existence/containment.
    Both loaded mappings use each supplied evidence_path's original string as
    their key; canonical path lookup belongs to the caller. No inputs are mutated.
    """
    if phase not in {"implementation", "post-integration"}:
        raise CogitoError("evidence phase must be implementation or post-integration")
    post_integration = phase == "post-integration"
    if post_integration and (
        not isinstance(current_head, str) or not GIT_OBJECT_RE.fullmatch(current_head)
    ):
        raise CogitoError("post-integration evidence requires a valid current HEAD")
    for item in evidence:
        validate_check_evidence(item)
        if post_integration:
            tree = item["worktree_binding"].get("content_tree")
            if not isinstance(tree, str) or not GIT_OBJECT_RE.fullmatch(tree):
                raise CogitoError("post-integration evidence lacks a content tree; rerun controlled checks")
    required = {
        item["id"]: item for item in effective_contract["checks"]
        if item.get("required", True)
    }
    supplied = {item.get("check_id"): item for item in evidence}
    if validate_supplied:
        known = {item['id']: item for item in effective_contract['checks']}
        if not supplied or len(supplied) != len(evidence) or supplied.keys() - known.keys():
            raise CogitoError('human evidence must name distinct known checks and cannot be empty')
        required.update({key: known[key] for key in supplied})
    anchors = (
        {"integration-complete", "post-integration-correction-complete", "human-correction-complete"}
        if post_integration
        else {"implementation-complete", "technical-correction-complete", "review-fix-complete"}
    )
    anchor_sequence = max(
        (item["sequence"] for item in events if item["type"] in anchors), default=0
    )
    if set(required) - set(supplied):
        raise CogitoError("required verification evidence is missing")

    for check_id, check in required.items():
        item = supplied[check_id]
        evidence_path = item["evidence_path"]
        if evidence_path not in recorded_evidence:
            raise CogitoError(f"immutable evidence file is missing for {check_id}")
        recorded = recorded_evidence[evidence_path]
        validate_check_evidence(recorded)
        if recorded != item:
            raise CogitoError(
                f"evidence payload does not match its immutable file for {check_id}"
            )
        entry = ledger.get(evidence_path)
        if (
            not entry
            or entry.get("evidence_hash") != hash_json(recorded)
            or entry.get("check_id") != check_id
        ):
            raise CogitoError(
                f"evidence was not produced and recorded by the controlled runner for {check_id}"
            )
        if int(entry.get("event_sequence") or 0) <= anchor_sequence:
            raise CogitoError(f"evidence predates the current verification cycle for {check_id}")
        if (
            item.get("passed") is not True
            or item.get("check_hash") != hash_json(check)
            or item.get("effective_contract_hash") != effective_contract["effective_contract_hash"]
        ):
            raise CogitoError(f"evidence binding failed for {check_id}")
        expected_output_limit = package["policy_snapshot"].get(
            "max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES
        )
        recorded_output_limit = item.get("output_limit_bytes")
        if (
            item.get("output_limit_exceeded") is not False
            or item.get("termination_degraded") is not False
            or recorded_output_limit != expected_output_limit
        ):
            raise CogitoError(f"evidence output policy binding failed for {check_id}")
        binding = item.get("worktree_binding")
        if not isinstance(binding, dict) or binding.get("snapshot_hash") != item.get("tree_hash"):
            raise CogitoError(f"working-tree binding is missing for {check_id}")
        binding_body = {key: value for key, value in binding.items() if key != "snapshot_hash"}
        if hash_json(binding_body) != binding["snapshot_hash"]:
            raise CogitoError(f"working-tree binding hash is invalid for {check_id}")
        if (
            item.get("worktree_changed_during_check") is not False
            or item.get("pre_worktree_snapshot_hash") != item.get("post_worktree_snapshot_hash")
            or item.get("post_worktree_snapshot_hash") != item.get("worktree_snapshot_hash")
            or item.get("worktree_snapshot_hash") != item.get("tree_hash")
            or binding.get("head_commit") != item.get("head_commit")
        ):
            raise CogitoError(f"evidence worktree stability binding failed for {check_id}")
        if post_integration and item.get("head_commit") != current_head:
            raise CogitoError(
                f"post-integration evidence is not bound to current HEAD for {check_id}"
            )
