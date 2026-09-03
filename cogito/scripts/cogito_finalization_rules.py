"""Pure rules for committed finalization records and verification snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from cogito_state_types import RunState
from cogito_common import CogitoError, hash_json
from cogito_contract_fields import GIT_OBJECT_RE
from cogito_contracts import package_hash
from cogito_evidence_contract import validate_check_evidence


@dataclass(frozen=True)
class FinalizationContext:
    """Collected artifacts and history; Result/Graph shapes are validated on read."""

    run_id: str
    package: Mapping[str, Any]
    state: RunState
    events: Sequence[Mapping[str, Any]]
    result: Mapping[str, Any]
    graph: Mapping[str, Any]
    effective_contract: Mapping[str, Any]


def validate_final_content_changes(changed_paths: Sequence[str], metadata_paths: set[str]) -> None:
    """Only the two canonical closure records may differ from verified content."""
    unexpected = sorted(set(changed_paths) - metadata_paths)
    if unexpected:
        raise CogitoError(f"final commit changes unverified content: {unexpected}")


def validate_verification_snapshot(
    evidence: Mapping[str, Any], ledger: Mapping[str, Any], effective_contract_hash: str | None,
) -> str:
    """Validate loaded evidence against the ledger and return its content tree."""
    validate_check_evidence(evidence)
    if (hash_json(evidence) != ledger.get("evidence_hash")
            or evidence["passed"] is not True
            or evidence["effective_contract_hash"] != effective_contract_hash):
        raise CogitoError("final verification evidence no longer matches the runner ledger")
    binding = evidence["worktree_binding"]
    body = {key: value for key, value in binding.items() if key != "snapshot_hash"}
    if (hash_json(body) != binding.get("snapshot_hash")
            or binding.get("snapshot_hash") != evidence["worktree_snapshot_hash"]):
        raise CogitoError("final verification snapshot hash is invalid")
    tree = binding.get("content_tree")
    if not isinstance(tree, str) or not GIT_OBJECT_RE.fullmatch(tree):
        raise CogitoError("final verification lacks a content tree; rerun controlled checks")
    return tree


def validate_finalization_records(context: FinalizationContext) -> set[str]:
    """Check collected records without IO and return final verification paths.

    The caller validates Result/Graph shapes before loading the event history.
    This function only compares those artifacts with the approved run records.
    """
    run_id, package, state = context.run_id, context.package, context.state
    result, graph = context.result, context.graph
    if result.get("run_id") != run_id or result.get("package_hash") != package_hash(package):
        raise CogitoError("final Result is not bound to this run and Package")
    if result.get("effective_contract_hash") != state.get("effective_contract_hash"):
        raise CogitoError("final Result effective contract hash does not match the run")
    if graph.get("active_run_id") is not None:
        raise CogitoError("final Project Graph must clear active_run_id")

    _validate_graph_closure(context)
    _validate_amendment_history(context)
    evidence_paths = _validate_verification_summary(context)
    _validate_acceptance_history(context)
    return evidence_paths


def _validate_graph_closure(context: FinalizationContext) -> None:
    run_id, package, events = context.run_id, context.package, context.events
    result, graph = context.result, context.graph
    approval_events = [item for item in events if item["type"] == "package-approved"]
    approved_graph = approval_events[-1]["payload"].get("project_graph_snapshot")
    if (
        not isinstance(approved_graph, dict)
        or graph.get("schema_version") != "3.0"
        or graph.get("dependencies") != approved_graph.get("dependencies")
    ):
        raise CogitoError("final Project Graph is not a valid evolution of the approved graph")
    owned_slices = {item["id"] for item in package["slices"]}
    unrelated_final = {
        key: value for key, value in graph.get("slices", {}).items() if key not in owned_slices
    }
    unrelated_approved = {
        key: value
        for key, value in approved_graph.get("slices", {}).items()
        if key not in owned_slices
    }
    if unrelated_final != unrelated_approved:
        raise CogitoError("final Project Graph changed unrelated Slice history")

    expected_slices = {item["id"] for item in package["slices"]}
    if set(result["slice_dispositions"]) != expected_slices or any(
        value != "accepted" for value in result["slice_dispositions"].values()
    ):
        raise CogitoError("Result does not close every Package Slice")
    for slice_id in expected_slices:
        graph_slice = graph.get("slices", {}).get(slice_id, {})
        if graph_slice.get("disposition") != "accepted" or graph_slice.get("completed_by") != run_id:
            raise CogitoError("Project Graph does not accept every Package Slice")


def _validate_amendment_history(context: FinalizationContext) -> None:
    result, events = context.result, context.events
    amendments = [
        item["payload"]["amendment"]
        for item in events
        if item["type"] == "technical-amendment-added"
    ]
    if [item.get("id") for item in result["amendments"]] != [item["id"] for item in amendments]:
        raise CogitoError("Result amendment summary is incomplete or out of order")
    completions = {
        item["payload"].get("amendment_id"): item["payload"]
        for item in events
        if item["type"]
        in {
            "technical-correction-complete",
            "post-integration-correction-complete",
            "review-fix-complete",
        }
    }
    for item in result["amendments"]:
        completion = completions.get(item["id"], {})
        if completion.get("completion_mode") == "working-tree":
            starts = [event for event in events if event["type"] == "start-gate-passed"]
            if (context.package["kind"] != "maintenance" or len(starts) != 1
                    or "commit_id" in item or not item.get("content_tree")
                    or item.get("base_commit") != starts[0]["payload"]["delivery_head"]
                    or item.get("base_commit") != completion.get("commit_id")
                    or item["content_tree"] != completion.get("content_tree")):
                raise CogitoError("Result working-tree amendment does not match Maintenance correction history")
        elif not item.get("commit_id") or completion.get("commit_id") != item["commit_id"]:
            raise CogitoError("Result amendment commits do not match correction history")


def _validate_verification_summary(context: FinalizationContext) -> set[str]:
    result, events, effective = context.result, context.events, context.effective_contract
    required_checks = {
        item["id"] for item in effective["checks"] if item.get("required", True)
    }
    passed_checks = {
        item.get("id")
        for item in result["checks"]
        if item.get("status") == "passed" and item.get("evidence")
    }
    if not required_checks <= passed_checks:
        raise CogitoError("Result does not include passed evidence for every required check")
    integration_commits = [
        item["payload"]["commit_id"]
        for item in events
        if item["type"]
        in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}
    ]
    if result["integration_commits"] != integration_commits:
        raise CogitoError("Result integration commits do not exactly match Gate history")
    post_events = [
        item for item in events if item["type"] in {"human-review-required", "auto-accept-ready"}
    ]
    expected_evidence = set(post_events[-1]["payload"]["evidence"])
    result_evidence = {item.get("evidence") for item in result["checks"]}
    if result_evidence != expected_evidence:
        raise CogitoError("Result evidence does not exactly match the final Gate verification ledger")
    return expected_evidence


def _validate_acceptance_history(context: FinalizationContext) -> None:
    package, state, result, events = context.package, context.state, context.result, context.events
    human_was_required = any(item["type"] == "human-review-required" for item in events)
    if human_was_required and not any(item["type"] == "human-approved" for item in events):
        raise CogitoError(
            "Result cannot claim Human Gate approval without a recorded approval event"
        )
    expected_human = {
        "required": human_was_required,
        "outcome": "approved" if human_was_required else "not-required",
    }
    if result["human_gate"] != expected_human:
        raise CogitoError("Result human gate outcome does not match event history")
    reviewer_ids = {
        item.get("agent_id")
        for item in state.get("agent_results", [])
        if item.get("role") == "reviewer" and item.get("status") == "complete"
    }
    for task in state.get('tasks', {}).values():
        reviewer_ids.update(task.get('adoption', {}).get('source_reviewers', []))
    if package["kind"] != "maintenance" and reviewer_ids != {
        item.get("reviewer") for item in result["reviews"]
    }:
        raise CogitoError("Result reviewers do not exactly match recorded independent Reviewers")
