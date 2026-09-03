"""Pure Project Graph validation, formalization, and rendering."""

from __future__ import annotations

import re
from typing import Any, Mapping

from cogito_common import CogitoError
from cogito_contract_fields import (
    RUN_ID_RE, require_array, require_choice, require_id, require_object,
    require_string, require_strings, validate_document,
)
from cogito_scheduler import edge_pair


def validate_project_graph(graph: Mapping[str, Any]) -> None:
    """Validate consumed fields, retaining sparse views and extension metadata.

    Missing optional Slice metadata and active_run_id are not filled in. Existing
    render callers can still pass sparse graphs without altering their hashes.
    """
    require_object(graph, "Project Graph", "schema_version", "slices", "dependencies")
    require_choice(graph["schema_version"], "Project Graph.schema_version", {"3.0"})
    if graph.get("active_run_id") is not None:
        require_string(graph["active_run_id"], "active_run_id", RUN_ID_RE)
    slices = require_object(graph["slices"], "Project Graph.slices")
    for slice_id, item in slices.items():
        require_id(slice_id, "Slice id")
        require_object(item, f"Slice {slice_id}")
        if "kind" in item:
            require_choice(item["kind"], "Slice.kind", {"feature", "change", "correction"})
        if "disposition" in item:
            require_choice(item["disposition"], "Slice.disposition", {"planned", "active", "accepted", "cancelled", "superseded"})
        for key in ("dependencies", "lineage"):
            if key in item:
                require_strings(item[key], f"Slice.{key}")
        for key in ("spec", "plan"):
            if key in item:
                validate_document(item[key], f"Slice.{key}")
        if "introduced_by" in item:
            require_string(item["introduced_by"], "Slice.introduced_by", RUN_ID_RE)
        if item.get("completed_by") is not None:
            require_string(item["completed_by"], "Slice.completed_by", RUN_ID_RE)
    for edge in require_array(graph["dependencies"], "Project Graph.dependencies"):
        require_object(edge, "Project Graph dependency", "from", "to")
        for endpoint in (edge["from"], edge["to"]):
            require_id(endpoint, "Project Graph dependency endpoint")
            if endpoint not in slices:
                raise CogitoError("Project Graph dependency references an unknown Slice")


def render_project_graph_mermaid(graph: Mapping[str, Any]) -> str:
    try:
        validate_project_graph(graph)
    except CogitoError as exc:
        raise CogitoError("cannot render an invalid Project Graph") from exc
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
        source = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("from", "")))
        target = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("to", "")))
        if not source or not target:
            raise CogitoError("Project Graph dependency is incomplete")
        lines.append(f"    {source} --> {target}")
    return "\n".join(lines) + "\n"


def formalize_project_graph(graph: Mapping[str, Any] | None, package: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    if graph is not None:
        validate_project_graph(graph)
    result = dict(graph) if graph is not None else {"schema_version": "3.0", "active_run_id": None, "slices": {}, "dependencies": []}
    if graph is not None:
        if result.get("active_run_id") not in (None, run_id):
            raise CogitoError("another Cogito run is active in Project Graph")
    result["slices"] = {key: dict(value) for key, value in result["slices"].items()}
    for item in package["slices"]:
        if item["id"] in result["slices"] and result["slices"][item["id"]].get("disposition") not in {"planned", "active"}:
            raise CogitoError(f"Slice id is already finalized: {item['id']}")
        result["slices"][item["id"]] = {
            "kind": item["type"], "disposition": "active", "dependencies": [],
            "spec": dict(item["spec"]), "plan": dict(item["plan"]),
            "lineage": item.get("lineage", []), "introduced_by": run_id,
        }
    task_slices = {task["id"]: task.get("slice_id") for task in package["execution_dag"]["tasks"]}
    dependencies = {(item["from"], item["to"]) for item in result["dependencies"]}
    for edge in package["execution_dag"]["edges"]:
        source, target = edge_pair(edge)
        from_slice, to_slice = task_slices.get(source), task_slices.get(target)
        if from_slice and to_slice and from_slice != to_slice:
            dependencies.add((from_slice, to_slice))
    result["dependencies"] = [{"from": source, "to": target} for source, target in sorted(dependencies)]
    for slice_id, item in result["slices"].items():
        item["dependencies"] = sorted(source for source, target in dependencies if target == slice_id)
    result["active_run_id"] = run_id
    return result
