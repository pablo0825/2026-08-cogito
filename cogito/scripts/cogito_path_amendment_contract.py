"""Pure, append-only scope additions for atomic execution and correction Tasks."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Mapping

from cogito_common import CogitoError
from cogito_contract_fields import require_array, require_id, require_object, require_paths, require_string


def validate_path_additions_shape(amendment: Mapping[str, Any]) -> None:
    if "path_additions" not in amendment:
        return
    additions = require_array(amendment["path_additions"], "path_additions", nonempty=True)
    if "commit_id" in amendment or amendment.get("path_fixes"):
        raise CogitoError("path additions cannot mix with other amendment changes")
    task_ids: set[str] = set()
    paths: set[str] = set()
    for addition in additions:
        require_object(addition, "path addition", "task_id", "paths", "reason", "check_ids")
        if set(addition) != {"task_id", "paths", "reason", "check_ids"}:
            raise CogitoError("path addition contains unknown fields")
        require_id(addition["task_id"], "path addition.task_id")
        if addition["task_id"] in task_ids:
            raise CogitoError("path additions require distinct task ids")
        task_ids.add(addition["task_id"])
        require_string(addition["reason"], "path addition.reason")
        require_paths(addition["paths"], "path addition.paths", nonempty=True)
        for path in addition["paths"]:
            if (str(PurePosixPath(path)) != path or path == "."
                    or any(char in path for char in "*?[]\\\r\n")
                    or any(part in {".git", ".cogito"} for part in PurePosixPath(path).parts)):
                raise CogitoError("path additions require exact normalized product file paths")
            if path in paths:
                raise CogitoError("path additions require distinct paths")
            paths.add(path)
        checks = require_array(addition["check_ids"], "path addition.check_ids", nonempty=True)
        for check in checks:
            require_id(check, "path addition check id")
        if len(checks) != len(set(checks)):
            raise CogitoError("path addition.check_ids must be unique")
    if amendment.get("added_tasks"):
        added = {task["id"]: task for task in amendment["added_tasks"]}
        if set(added) != task_ids:
            raise CogitoError("review path additions must target exactly the new correction tasks")
        for row in additions:
            task = added[row["task_id"]]
            if not set(row["paths"]) <= set(task["paths"]) or not set(row["check_ids"]) <= set(task.get("check_ids", [])):
                raise CogitoError("new correction tasks must include their added paths and checks")


def validate_path_additions(effective: Mapping[str, Any], amendment: Mapping[str, Any]) -> None:
    # Local import avoids a module cycle while sharing the authoritative matcher.
    from cogito_contracts import path_allowed

    additions = amendment.get("path_additions", [])
    if not additions:
        return
    if effective.get("task_delivery") != "atomic" or effective["kind"] not in {"feature", "change", "correction"}:
        raise CogitoError("path additions require an atomic Development Package")
    tasks = {task["id"]: task for task in effective["execution_dag"]["tasks"]}
    added = {task["id"]: task for task in amendment.get("added_tasks", [])}
    if set(added) & set(tasks):
        raise CogitoError("added tasks require new ids")
    tasks.update(added)
    slices = {item["id"]: item for item in effective["slices"]}
    checks = {check["id"] for check in [*effective["checks"], *amendment.get("added_checks", [])]
              if check.get("required", True)}
    protected = ["docs/cogito", *effective["human_gate"].get("high_risk_hotspots", [])]
    protected.extend(item["path"] for item in effective["source_registry"])
    protected.extend(item[key]["path"] for item in slices.values() for key in ("spec", "plan"))
    if effective.get("shared_understanding", {}).get("path"):
        protected.append(effective["shared_understanding"]["path"])
    slice_ids: set[str] = set()
    claimed: list[str] = []
    for addition in additions:
        task = tasks.get(addition["task_id"])
        if task is None:
            raise CogitoError("path additions require existing tasks")
        slice_ids.add(task["slice_id"])
        if not set(addition["check_ids"]) <= checks:
            raise CogitoError("path additions must reference required checks")
        for path in addition["paths"]:
            if path_allowed(path, protected) or any(path_allowed(value, [path]) for value in protected):
                raise CogitoError("path addition overlaps frozen control or safety scope")
            if task["id"] not in added and path_allowed(path, task["paths"]):
                raise CogitoError("path addition is already within its Task scope")
            if any(path_allowed(path, other["paths"]) or any(path_allowed(value, [path]) for value in other["paths"])
                   for other in tasks.values() if other["id"] != task["id"]):
                raise CogitoError("path addition overlaps another Task responsibility")
            if any(path_allowed(path, other["worker"]["allowed_paths"])
                   or any(path_allowed(value, [path]) for value in other["worker"]["allowed_paths"])
                   for other in slices.values() if other["id"] != task["slice_id"]):
                raise CogitoError("path addition overlaps another Slice responsibility")
            if path_allowed(path, claimed) or any(path_allowed(value, [path]) for value in claimed):
                raise CogitoError("path additions overlap each other")
            claimed.append(path)
    if len(slice_ids) != 1:
        raise CogitoError("path additions must target one Slice")


def apply_path_additions(effective: dict[str, Any], amendment: Mapping[str, Any]) -> None:
    """Append validated additions to an owned copy; leave raw inputs unchanged."""
    tasks = {task["id"]: task for task in effective["execution_dag"]["tasks"]}
    slices = {item["id"]: item for item in effective["slices"]}
    for addition in amendment.get("path_additions", []):
        task = tasks[addition["task_id"]]
        for path in addition["paths"]:
            for paths in (effective["approved_paths"], slices[task["slice_id"]]["worker"]["allowed_paths"], task["paths"]):
                if path not in paths:
                    paths.append(path)
        for check in addition["check_ids"]:
            if check not in task["check_ids"]:
                task["check_ids"].append(check)
