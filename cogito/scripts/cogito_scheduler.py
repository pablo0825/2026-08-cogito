"""Pure Slice/task DAG validation and worker scheduling."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from cogito_common import CogitoError


def edge_pair(edge: Any) -> tuple[str, str]:
    if isinstance(edge, dict) and set(edge) >= {"from", "to"}:
        return str(edge["from"]), str(edge["to"])
    if isinstance(edge, (list, tuple)) and len(edge) == 2:
        return str(edge[0]), str(edge[1])
    raise CogitoError("each DAG edge must contain from and to")


def ready_tasks(tasks: Sequence[Mapping[str, Any]], edges: Sequence[Any], max_workers: int = 3) -> list[dict[str, Any]]:
    if not 1 <= max_workers <= 3:
        raise CogitoError("max_workers must be between 1 and 3")
    by_id = {str(task.get("id")): task for task in tasks if task.get("id")}
    if len(by_id) != len(tasks):
        raise CogitoError("task ids must be present and unique")
    pairs = [edge_pair(edge) for edge in edges]
    if any(source not in by_id or target not in by_id or source == target for source, target in pairs):
        raise CogitoError("DAG edge references an unknown task or itself")
    indegree = {key: 0 for key in by_id}
    children = {key: [] for key in by_id}
    for source, target in pairs:
        indegree[target] += 1
        children[source].append(target)
    queue = [key for key, value in indegree.items() if value == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for child in children[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
    if visited != len(by_id):
        raise CogitoError("execution graph contains a cycle")
    active_slices = {task.get("slice_id") or "mini-package" for task in tasks if task.get("status") in {"leased", "running"}}
    capacity = max(0, max_workers - len(active_slices))
    if capacity == 0:
        return []
    prerequisites: dict[str, set[str]] = {key: set() for key in by_id}
    for source, target in pairs:
        prerequisites[target].add(source)

    def dependency_ready(source: str, target: str) -> bool:
        source_task, target_task = by_id[source], by_id[target]
        if source_task.get("slice_id") == target_task.get("slice_id"):
            return source_task.get("status") in {"complete", "verified", "reviewed", "integrated"}
        return source_task.get("status") == "integrated"

    candidates = [
        dict(task) for key, task in by_id.items()
        if task.get("status", "pending") == "pending"
        and all(dependency_ready(source, key) for source in prerequisites[key])
    ]
    selected: list[dict[str, Any]] = []
    selected_slices = set(active_slices)
    for task in candidates:
        slice_id = task.get("slice_id") or "mini-package"
        if slice_id in selected_slices:
            continue
        selected.append(task)
        selected_slices.add(slice_id)
        if len(selected) >= capacity:
            break
    return selected
