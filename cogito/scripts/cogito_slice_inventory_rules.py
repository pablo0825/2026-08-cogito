"""Pure assembly rules for a bounded, reference-only Slice inventory."""

from __future__ import annotations

import copy
import json
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError
from cogito_contracts import package_hash


MAX_SLICE_INVENTORY_BYTES = 1024 * 1024


def build_inventory_view(
    *,
    package: Mapping[str, Any],
    result: Mapping[str, Any],
    effective_contract: Mapping[str, Any],
    agent_results: Sequence[Mapping[str, Any]],
    amendments: Sequence[tuple[int, Mapping[str, Any]]],
    slice_id: str,
    final_commit: str,
    package_path: str,
    result_path: str,
    committed_paths: Sequence[str],
) -> dict[str, Any]:
    """Assemble deterministic source facts without changing caller-owned data."""
    slices = [item for item in package["slices"] if item["id"] == slice_id]
    if len(package["slices"]) != 1 or len(slices) != 1:
        raise CogitoError("slice-inventory currently requires an accepted single-Slice Package")
    selected = slices[0]
    frozen_tasks = [
        task for task in package["execution_dag"]["tasks"]
        if task.get("slice_id") == slice_id
    ]
    task_ids = {
        task["id"] for task in effective_contract["execution_dag"]["tasks"]
        if task.get("slice_id") == slice_id
    }
    implementer_results: list[dict[str, Any]] = []
    implementer_paths: list[str] = []
    seen_paths: set[str] = set()
    for item in agent_results:
        if item.get("role") != "implementer" or item.get("task_id") not in task_ids:
            continue
        implementer_results.append({
            key: copy.deepcopy(item[key])
            for key in (
                "task_id", "agent_id", "status", "base_commit", "head_commit", "changed_paths",
            )
        })
        for path in item["changed_paths"]:
            if path not in seen_paths:
                seen_paths.add(path)
                implementer_paths.append(path)

    amendment_records: list[dict[str, Any]] = []
    for sequence, amendment in amendments:
        amendment_records.append({
            "event_sequence": sequence,
            "id": amendment["id"],
            "reason": amendment["reason"],
            "path_additions": copy.deepcopy(amendment.get("path_additions", [])),
            "path_fixes": copy.deepcopy(amendment.get("path_fixes", [])),
            "added_tasks": copy.deepcopy(amendment.get("added_tasks", [])),
            "added_checks": copy.deepcopy(amendment.get("added_checks", [])),
        })

    inventory = {
        "schema_version": "1.0",
        "source": {
            "run_id": package["run_id"],
            "slice_id": slice_id,
            "final_commit": final_commit,
            "package_path": package_path,
            "result_path": result_path,
            "package_hash": package_hash(package),
            "effective_contract_hash": effective_contract["effective_contract_hash"],
        },
        "package_references": {
            "spec": copy.deepcopy(selected["spec"]),
            "plan": copy.deepcopy(selected["plan"]),
            "source_registry": copy.deepcopy(package["source_registry"]),
        },
        "accepted_outcome": {
            "checks": copy.deepcopy(result["checks"]),
            "reviews": copy.deepcopy(result["reviews"]),
            "human_gate": copy.deepcopy(result["human_gate"]),
            "remaining_risks": copy.deepcopy(result["remaining_risks"]),
        },
        "paths": {
            "frozen_approved": copy.deepcopy(package["approved_paths"]),
            "implementer_reported": implementer_paths,
            "start_to_final": list(committed_paths),
        },
        "implementer_results": implementer_results,
        "tasks": {"frozen": copy.deepcopy(frozen_tasks)},
        "checks": {"frozen": copy.deepcopy(package["checks"])},
        "amendments": amendment_records,
        "reference_blocks": {
            "limits": copy.deepcopy(package["limits"]),
            "policy_snapshot": copy.deepcopy(package["policy_snapshot"]),
            "stop_conditions": copy.deepcopy(package["stop_conditions"]),
        },
    }
    encoded = json.dumps(
        {"ok": True, "data": inventory}, ensure_ascii=False, sort_keys=True, indent=2,
    ).encode("utf-8")
    if len(encoded) + 1 > MAX_SLICE_INVENTORY_BYTES:  # CLI print appends one newline.
        raise CogitoError(
            f"slice inventory exceeds {MAX_SLICE_INVENTORY_BYTES} bytes; inspect the accepted artifacts directly"
        )
    return inventory
