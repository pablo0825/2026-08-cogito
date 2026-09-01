"""Validation of committed Result and Project Graph finalization artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cogito_common import CogitoError
from cogito_contracts import materialize_contract, package_hash


GitCommand = Callable[..., str]


def validate_finalization(
    *,
    run_id: str,
    package: Mapping[str, Any],
    state: Mapping[str, Any],
    load_events: Callable[[], Sequence[Mapping[str, Any]]],
    result_path: str,
    project_graph_path: str,
    final_commit: str,
    git: GitCommand,
) -> dict[str, Any]:
    """Validate final committed artifacts and return the Gate event payload."""
    result_rel, graph_rel = Path(result_path), Path(project_graph_path)
    for path in (result_rel, graph_rel):
        if path.is_absolute() or ".." in path.parts:
            raise CogitoError("finalization paths must be repository-relative")
    expected_result = Path("docs") / "cogito" / "results" / f"{run_id}.json"
    if result_rel != expected_result or graph_rel != Path("docs/cogito/project-graph.json"):
        raise CogitoError("finalization must use canonical Result and Project Graph paths")

    git("cat-file", "-e", f"{final_commit}^{{commit}}")
    if git("branch", "--show-current") != package["delivery_branch"] or git(
        "rev-parse", "HEAD"
    ) != final_commit:
        raise CogitoError("final commit must be current HEAD on the frozen delivery branch")
    result = json.loads(git("show", f"{final_commit}:{result_rel.as_posix()}"))
    graph = json.loads(git("show", f"{final_commit}:{graph_rel.as_posix()}"))

    required_result = {
        "schema_version", "run_id", "status", "package_hash", "effective_contract_hash",
        "integration_commits", "slice_dispositions", "checks", "reviews", "amendments",
        "human_gate", "remaining_risks",
    }
    if (
        not isinstance(result, dict)
        or not required_result <= result.keys()
        or result.get("schema_version") != "3.0"
    ):
        raise CogitoError("final Result is structurally incomplete")
    if result.get("run_id") != run_id or result.get("package_hash") != package_hash(package):
        raise CogitoError("final Result is not bound to this run and Package")
    if result.get("effective_contract_hash") != state.get("effective_contract_hash"):
        raise CogitoError("final Result effective contract hash does not match the run")
    if result.get("status") != "accepted" or any(
        key in result for key in ("final_commit", "result_commit", "finalization_commit")
    ):
        raise CogitoError("Result must be accepted and must not self-reference its containing commit")
    if graph.get("active_run_id") is not None:
        raise CogitoError("final Project Graph must clear active_run_id")

    events = load_events()
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

    amendments = [
        item["payload"]["amendment"]
        for item in events
        if item["type"] == "technical-amendment-added"
    ]
    if [item.get("id") for item in result["amendments"]] != [item["id"] for item in amendments] or any(
        not item.get("commit_id") for item in result["amendments"]
    ):
        raise CogitoError("Result amendment summary is incomplete or out of order")
    completion_commits = {
        item["payload"].get("amendment_id"): item["payload"].get("commit_id")
        for item in events
        if item["type"]
        in {
            "technical-correction-complete",
            "post-integration-correction-complete",
            "review-fix-complete",
        }
    }
    if any(
        completion_commits.get(item["id"]) != item["commit_id"]
        for item in result["amendments"]
    ):
        raise CogitoError("Result amendment commits do not match correction history")

    effective = materialize_contract(package, amendments)
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
    if not isinstance(result["remaining_risks"], list) or not isinstance(
        result["integration_commits"], list
    ):
        raise CogitoError("Result risks and integration commits must be arrays")
    integration_commits = [
        item["payload"]["commit_id"]
        for item in events
        if item["type"]
        in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}
    ]
    if result["integration_commits"] != integration_commits:
        raise CogitoError("Result integration commits do not exactly match Gate history")
    for commit in result["integration_commits"]:
        git("cat-file", "-e", f"{commit}^{{commit}}")
        git("merge-base", "--is-ancestor", commit, final_commit)
    for item in result["amendments"]:
        git("cat-file", "-e", f"{item['commit_id']}^{{commit}}")
        if f"Cogito-Amendment: {item['id']}" not in git(
            "show", "-s", "--format=%B", item["commit_id"]
        ):
            raise CogitoError("Result references an amendment commit without its trailer")

    post_events = [
        item for item in events if item["type"] in {"human-review-required", "auto-accept-ready"}
    ]
    expected_evidence = set(post_events[-1]["payload"]["evidence"])
    result_evidence = {item.get("evidence") for item in result["checks"]}
    if result_evidence != expected_evidence:
        raise CogitoError("Result evidence does not exactly match the final Gate verification ledger")
    if package["kind"] != "maintenance" and git(
        "rev-parse", f"{final_commit}^"
    ) != post_events[-1]["payload"].get("delivery_head"):
        raise CogitoError("final commit must directly follow the post-verification delivery HEAD")

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
    if package["kind"] != "maintenance" and reviewer_ids != {
        item.get("reviewer") for item in result["reviews"]
    }:
        raise CogitoError("Result reviewers do not exactly match recorded independent Reviewers")
    if package["kind"] == "maintenance":
        starts = [item for item in events if item["type"] == "start-gate-passed"]
        if len(starts) != 1 or git("rev-parse", f"{final_commit}^") != starts[0]["payload"][
            "delivery_head"
        ]:
            raise CogitoError("Maintenance must finalize as one commit from the Start Gate head")

    return {
        "result_path": result_rel.as_posix(),
        "project_graph_path": graph_rel.as_posix(),
        "final_commit": final_commit,
        "final_tree": git("rev-parse", f"{final_commit}^{{tree}}"),
        "project_graph_updated": True,
    }
