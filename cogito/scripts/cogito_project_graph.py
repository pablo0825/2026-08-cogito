"""Pure Project Graph validation, formalization, and rendering."""

from __future__ import annotations

import re
from typing import Any, Mapping

from cogito_common import CogitoError
from cogito_scheduler import edge_pair


def validate_project_graph(graph: Mapping[str, Any]) -> None:
    if graph.get("schema_version") != "3.0" or not isinstance(graph.get("slices"), dict) or not isinstance(graph.get("dependencies"), list):
        raise CogitoError("existing Project Graph is invalid")


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
        if edge.get("from") not in graph["slices"] or edge.get("to") not in graph["slices"]:
            raise CogitoError("Project Graph dependency references an unknown Slice")
        source = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("from", "")))
        target = re.sub(r"[^A-Za-z0-9_]", "_", str(edge.get("to", "")))
        if not source or not target:
            raise CogitoError("Project Graph dependency is incomplete")
        lines.append(f"    {source} --> {target}")
    return "\n".join(lines) + "\n"


def formalize_project_graph(graph: Mapping[str, Any] | None, package: Mapping[str, Any], run_id: str) -> dict[str, Any]:
    result = dict(graph) if graph is not None else {"schema_version": "3.0", "active_run_id": None, "slices": {}, "dependencies": []}
    if graph is not None:
        validate_project_graph(result)
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
