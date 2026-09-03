"""Validation of committed Result and Project Graph finalization artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from cogito_state_types import RunState
from cogito_common import CogitoError, load_json
from cogito_contracts import materialize_contract, materialize_contract_with_limits
from cogito_project_graph import validate_project_graph
from cogito_result_contract import validate_result
from cogito_delivery_scope import BlobReader, validate_committed_scope
from cogito_finalization_rules import (
    FinalizationContext, validate_final_content_changes,
    validate_finalization_records, validate_verification_snapshot,
)


GitCommand = Callable[..., str]


def validate_verified_content(
    *, final_commit: str, evidence_paths: set[str], state: RunState,
    metadata_paths: set[str], git: GitCommand,
) -> None:
    """Read immutable runner snapshots and compare their trees with delivery."""
    for evidence_path in sorted(evidence_paths):
        ledger = state.get("evidence", {}).get(evidence_path)
        if not ledger:
            raise CogitoError("final verification evidence is missing from the runner ledger")
        evidence = load_json(Path(evidence_path))
        tree = validate_verification_snapshot(evidence, ledger, state["effective_contract_hash"])
        try:
            git("cat-file", "-e", f"{tree}^{{tree}}")
        except CogitoError as exc:
            raise CogitoError("final verification content tree is unavailable; rerun controlled checks") from exc
        changed = git("diff", "--name-only", "--no-renames", "--no-ext-diff", "--ignore-submodules=none", "-z", tree, final_commit, "--")
        validate_final_content_changes(list(filter(None, changed.split("\0"))), metadata_paths)


def validate_finalization(
    *,
    run_id: str,
    package: Mapping[str, Any],
    state: RunState,
    load_events: Callable[[], Sequence[Mapping[str, Any]]],
    result_path: str,
    project_graph_path: str,
    final_commit: str,
    git: GitCommand,
    read_blob: BlobReader | None = None,
    workflow_limits: Mapping[str, int] | None = None,
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
    try:
        result = json.loads(git("show", f"{final_commit}:{result_rel.as_posix()}"))
        graph = json.loads(git("show", f"{final_commit}:{graph_rel.as_posix()}"))
    except json.JSONDecodeError as exc:
        raise CogitoError(f"finalization artifact is not valid JSON: {exc}") from exc
    validate_result(result)
    validate_project_graph(graph)
    events = load_events()
    amendments = [item["payload"]["amendment"] for item in events if item["type"] == "technical-amendment-added"]
    effective = (
        materialize_contract(package, amendments) if workflow_limits is None
        else materialize_contract_with_limits(package, amendments, workflow_limits)
    )
    context = FinalizationContext(
        run_id=run_id, package=package, state=state, events=events,
        result=result, graph=graph, effective_contract=effective,
    )
    expected_evidence = validate_finalization_records(context)
    _validate_commit_history(context, final_commit, git)

    metadata_paths = {result_rel.as_posix(), graph_rel.as_posix()}
    _validate_delivery_scope(context, final_commit, metadata_paths, git, read_blob)
    if package["kind"] not in {"maintenance", "documentation"}:
        changed = git("diff", "--name-only", "--no-renames", "--no-ext-diff", "--ignore-submodules=none", "-z", f"{final_commit}^", final_commit, "--")
        validate_final_content_changes(list(filter(None, changed.split("\0"))), metadata_paths)
    validate_verified_content(
        final_commit=final_commit, evidence_paths=expected_evidence, state=state,
        metadata_paths=metadata_paths, git=git,
    )
    return {
        "result_path": result_rel.as_posix(),
        "project_graph_path": graph_rel.as_posix(),
        "final_commit": final_commit,
        "final_tree": git("rev-parse", f"{final_commit}^{{tree}}"),
        "project_graph_updated": True,
    }


def _validate_delivery_scope(
    context: FinalizationContext, final_commit: str, metadata_paths: set[str], git: GitCommand,
    read_blob: BlobReader | None = None,
) -> None:
    starts = [item for item in context.events if item["type"] == "start-gate-passed"]
    if len(starts) != 1:
        raise CogitoError("delivery scope requires exactly one Start Gate head")
    base = starts[0]["payload"]["delivery_head"]
    validate_committed_scope(context.package, base, final_commit, git, metadata_paths, read_blob)


def _validate_commit_history(context: FinalizationContext, final_commit: str, git: GitCommand) -> None:
    """Check repository facts that cannot be established from records alone."""
    package, result, events = context.package, context.result, context.events
    for commit in result["integration_commits"]:
        git("cat-file", "-e", f"{commit}^{{commit}}")
        git("merge-base", "--is-ancestor", commit, final_commit)
    for item in result["amendments"]:
        commit = item.get("commit_id", final_commit)
        git("cat-file", "-e", f"{commit}^{{commit}}")
        if "commit_id" not in item:
            git("cat-file", "-e", f"{item['content_tree']}^{{tree}}")
        if f"Cogito-Amendment: {item['id']}" not in git(
            "show", "-s", "--format=%B", commit
        ).splitlines():
            raise CogitoError("Result references an amendment commit without its trailer")

    post_events = [
        item for item in events if item["type"] in {"human-review-required", "auto-accept-ready", "human-correction-reviewed", "human-correction-accepted"}
    ]
    if package["kind"] != "maintenance" and git(
        "rev-parse", f"{final_commit}^"
    ) != post_events[-1]["payload"].get("delivery_head"):
        raise CogitoError("final commit must directly follow the post-verification delivery HEAD")

    if package["kind"] == "maintenance":
        starts = [item for item in events if item["type"] == "start-gate-passed"]
        parents = git("rev-list", "--parents", "-n", "1", final_commit).split()[1:]
        if len(starts) != 1 or parents != [starts[0]["payload"]["delivery_head"]]:
            raise CogitoError("Maintenance must finalize as one commit from the Start Gate head")
