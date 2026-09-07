"""Read-only assembly of trustworthy facts from one accepted Slice."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, cast

from cogito_common import CogitoError
from cogito_contract_fields import GIT_OBJECT_RE, RUN_ID_RE, require_id, require_path, require_string
from cogito_contracts import materialize_contract_with_limits, package_hash
from cogito_delivery_summary import validate_delivery_summary_records
from cogito_event_repository import EventRepository
from cogito_git import GitRepository
from cogito_ports import EventRepositoryPort, GitRepositoryPort
from cogito_result_contract import validate_result
from cogito_slice_inventory_compat import EVENT as HISTORICAL_RESOLUTION_EVENT
from cogito_slice_inventory_compat import (
    compatible_result, compatible_snapshot, validate_resolution_checks,
)
from cogito_slice_inventory_rules import build_inventory_view
from cogito_workflow import load_workflow


def _read_json_blob(
    git_repository: GitRepositoryPort, commit_id: str, path: str, name: str,
) -> dict[str, Any]:
    try:
        value = json.loads(git_repository.read_blob(commit_id, path).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CogitoError(f"committed {name} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise CogitoError(f"committed {name} must be a JSON object")
    return value


def build_slice_inventory(
    root: str | Path,
    source_run: str,
    source_slice: str,
    *,
    workflow: Mapping[str, Any] | None = None,
    event_repository: EventRepositoryPort | None = None,
    git_repository: GitRepositoryPort | None = None,
) -> dict[str, Any]:
    """Read accepted ledger and committed artifacts without repairing any cache."""
    require_string(source_run, "source_run", RUN_ID_RE)
    if not source_run.startswith("DEV-"):
        raise CogitoError("slice-inventory source must be a Development run")
    require_id(source_slice, "source_slice")
    repo_root = Path(root).resolve()
    workflow_value = dict(workflow or load_workflow())
    events_path = repo_root / ".cogito" / "runs" / source_run / "events.jsonl"
    state_path = repo_root / ".cogito" / "runs" / source_run / "state.json"
    ledger = event_repository or EventRepository(events_path, state_path, workflow_value)
    git = git_repository or GitRepository(repo_root)
    if not ledger.exists():
        raise CogitoError(f"source run does not exist: {source_run}")

    historical_resolution = False
    try:
        snapshot = ledger.snapshot()
    except CogitoError:
        events = ledger.read()
        historical_resolution = any(
            item.get("type") == HISTORICAL_RESOLUTION_EVENT for item in events
        )
        if not historical_resolution:
            raise
        snapshot = compatible_snapshot(events, workflow_value)
    state, events = snapshot.state, snapshot.events
    if state.get("run_id") != source_run or state.get("state") != "accepted":
        raise CogitoError("slice-inventory source must be an accepted run")

    final_events = [item for item in events if item["type"] == "finalization-complete"]
    start_events = [item for item in events if item["type"] == "start-gate-passed"]
    if len(final_events) != 1 or len(start_events) != 1:
        raise CogitoError("accepted source requires exactly one Start Gate and finalization event")
    final_payload = final_events[0]["payload"]
    start_payload = start_events[0]["payload"]
    package_path = state.get("package_path")
    result_path = final_payload.get("result_path")
    project_graph_path = final_payload.get("project_graph_path")
    final_commit = final_payload.get("final_commit")
    delivery_head = start_payload.get("delivery_head")
    require_path(package_path, "accepted package_path")
    require_path(result_path, "accepted result_path")
    require_path(project_graph_path, "accepted project_graph_path")
    require_string(final_commit, "accepted final_commit", GIT_OBJECT_RE)
    require_string(delivery_head, "accepted delivery_head", GIT_OBJECT_RE)
    package_path = cast(str, package_path)
    result_path = cast(str, result_path)
    final_commit = cast(str, final_commit)
    delivery_head = cast(str, delivery_head)

    package = _read_json_blob(git, final_commit, package_path, "Package")
    result = _read_json_blob(git, final_commit, result_path, "Result")
    validated_result = compatible_result(result, events) if historical_resolution else result
    validate_result(validated_result)
    amendments = [
        (int(item["sequence"]), item["payload"]["amendment"])
        for item in events if item["type"] == "technical-amendment-added"
    ]
    effective = materialize_contract_with_limits(
        package, [item for _, item in amendments], workflow_value["limits"],
    )
    if historical_resolution:
        validate_resolution_checks(events, effective)
    if package.get("kind") not in {"feature", "change", "correction"}:
        raise CogitoError("slice-inventory source must use a Development Package")
    accepted_slices = [item["id"] for item in package["slices"]]
    if len(accepted_slices) != 1:
        raise CogitoError("slice-inventory currently requires an accepted single-Slice Package")
    if source_slice != accepted_slices[0]:
        raise CogitoError(
            f"source Slice {source_slice} does not match accepted Slice {accepted_slices[0]}"
        )
    frozen_hash = package_hash(package)
    if package.get("run_id") != source_run or frozen_hash != state.get("package_hash"):
        raise CogitoError("committed Package does not match the accepted run")
    if result.get("run_id") != source_run or result.get("package_hash") != frozen_hash:
        raise CogitoError("committed Result does not match the accepted run and Package")
    effective_hash = effective["effective_contract_hash"]
    if (state.get("effective_contract_hash") != effective_hash
            or result.get("effective_contract_hash") != effective_hash):
        raise CogitoError("accepted effective contract hashes do not match")
    if [item.get("id") for item in result["amendments"]] != [item["id"] for _, item in amendments]:
        raise CogitoError("Result amendment summary is incomplete or out of order")
    if result.get("slice_dispositions") != {source_slice: "accepted"}:
        raise CogitoError("source Slice is not the sole accepted Package Slice")
    validation_events = [
        item for item in events if item.get("type") != HISTORICAL_RESOLUTION_EVENT
    ] if historical_resolution else events
    validate_delivery_summary_records(state, validation_events, validated_result)

    git.run("merge-base", "--is-ancestor", delivery_head, final_commit)
    final_tree = git.run("rev-parse", f"{final_commit}^{{tree}}")
    if final_payload.get("final_tree") != final_tree:
        raise CogitoError("accepted final commit tree does not match the event ledger")
    changed = git.run(
        "diff", "--name-only", "--no-renames", "--no-ext-diff",
        "--ignore-submodules=none", "-z", delivery_head, final_commit, "--",
    )
    committed_paths = [path for path in changed.split("\0") if path]
    return build_inventory_view(
        package=package,
        result=result,
        effective_contract=effective,
        agent_results=state.get("agent_results", []),
        amendments=amendments,
        slice_id=source_slice,
        final_commit=final_commit,
        package_path=package_path,
        result_path=result_path,
        committed_paths=committed_paths,
    )
