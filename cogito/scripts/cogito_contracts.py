"""Pure validation and materialization of Cogito contracts."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError, hash_json
from cogito_contract_fields import (
    CONTENT_HASH_RE, GIT_OBJECT_RE, RUN_ID_RE,
    require_array, require_boolean, require_choice, require_id, require_integer,
    require_object, require_path, require_paths, require_string, require_strings,
    safe_repo_path, validate_document,
)
from cogito_scheduler import edge_pair, ready_tasks
from cogito_workflow import load_workflow


DEFAULT_MAX_CHECK_OUTPUT_BYTES = 10 * 1024 * 1024
MIN_MAX_CHECK_OUTPUT_BYTES = 1024
MAX_MAX_CHECK_OUTPUT_BYTES = 100 * 1024 * 1024


def required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


def path_allowed(path: str, approved: Sequence[str]) -> bool:
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    normalized = candidate.as_posix().rstrip("/")
    for raw in approved:
        pattern = str(raw).rstrip("/")
        if fnmatchcase(normalized, pattern):
            return True
        prefix = pattern.removesuffix("/**").removesuffix("/*")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def package_hash(package: Mapping[str, Any]) -> str:
    return hash_json({key: value for key, value in package.items() if key != "package_hash"})


def validate_package(package: Mapping[str, Any]) -> None:
    """Validate shape and Package invariants without rewriting caller data.

    Extension fields and established optional defaults remain supported. JSON
    Schema files are not a second authority for this contract.
    """
    required_fields = {
        "schema_version", "run_id", "kind", "delivery_branch", "baseline_commit",
        "shared_understanding", "slices", "execution_dag", "checks",
        "approved_paths", "human_gate", "policy_snapshot", "limits",
        "stop_conditions", "source_registry",
    }
    require_object(package, "package", *required_fields)
    require_choice(package["schema_version"], "package.schema_version", {"3.0"})
    require_choice(package["kind"], "package.kind", {"feature", "change", "correction", "maintenance", "documentation"})
    require_string(package["run_id"], "package.run_id", RUN_ID_RE)
    require_string(package["delivery_branch"], "delivery_branch")
    require_string(package["baseline_commit"], "baseline_commit", GIT_OBJECT_RE)
    shared = require_object(package["shared_understanding"], "shared_understanding", "hash")
    require_string(shared["hash"], "shared_understanding.hash", CONTENT_HASH_RE)
    if "path" in shared:
        require_path(shared["path"], "shared_understanding.path")
    require_array(package["slices"], "slices")
    if "mini_package" in package:
        require_boolean(package["mini_package"], "mini_package")
    mini = package["kind"] in {"maintenance", "documentation"}
    if bool(package.get("mini_package")) != mini:
        raise CogitoError("mini_package must be true exactly for maintenance/documentation")
    if mini:
        if package["slices"] != []:
            raise CogitoError("Mini Package must not create Slice/Spec/Plan entries")
        guards = package.get("maintenance_guards")
        guard_names = (
            "behavior_unchanged", "public_contract_unchanged", "data_model_unchanged",
            "security_boundary_unchanged", "slice_responsibility_unchanged",
            "deterministic_evidence", "single_commit",
        )
        if not isinstance(guards, dict) or not all(guards.get(key) is True for key in guard_names):
            raise CogitoError("Mini Package requires every frozen no-semantic-change guard")
    else:
        _validate_development_slices(package)
    require_paths(package["approved_paths"], "approved_paths", nonempty=True)
    _validate_stop_conditions(package["stop_conditions"])
    _validate_execution_dag(package, mini)
    check_ids = _validate_checks(package)
    validate_human_gate(package["human_gate"], frozen=True)
    limits = package["limits"]
    global_limits = load_workflow()["limits"]
    retry_names = ("transient_retries", "verification_corrections", "review_fix_cycles", "format_repairs")
    require_object(limits, "limits", *retry_names)
    for key in retry_names:
        require_integer(limits[key], f"limits.{key}", 0, global_limits[key])
    _validate_policy_snapshot(package, check_ids)
    registry = package["source_registry"]
    dispositions = {"read-only-source", "adopted", "updated", "superseded", "not-touched"}
    for item in require_array(registry, "source_registry"):
        require_object(item, "source_registry entry", "path", "hash", "relevance", "disposition")
        validate_document(item, "source_registry entry")
        require_string(item["relevance"], "source_registry.relevance")
        require_choice(item["disposition"], "source_registry.disposition", dispositions)
    expected = package.get("package_hash")
    if expected is not None and expected != package_hash(package):
        raise CogitoError("package_hash does not match immutable package content")


def _validate_development_slices(package: Mapping[str, Any]) -> None:
    boundary = package.get("boundary")
    require_object(boundary, "boundary", "decision", "evidence")
    require_choice(boundary["decision"], "boundary.decision", {"single-slice", "split-required"})
    require_strings(boundary["evidence"], "boundary.evidence", nonempty=True)
    require_array(package["slices"], "slices", nonempty=True)
    seen: set[str] = set()
    for item in package["slices"]:
        require_object(item, "Slice", "id", "type", "spec", "plan", "worker")
        require_id(item["id"], "Slice.id")
        require_choice(item["type"], "Slice.type", {"feature", "change", "correction"})
        if item["id"] in seen:
            raise CogitoError("Slice ids must be unique")
        seen.add(item["id"])
        for document in (item["spec"], item["plan"]):
            validate_document(document, "Spec/Plan")
        if "lineage" in item:
            require_strings(item["lineage"], "Slice.lineage")
        worker = item["worker"]
        require_object(worker, "worker", "branch", "worktree", "allowed_paths")
        require_string(worker["branch"], "worker.branch")
        require_path(worker["worktree"], "worker.worktree")
        require_paths(worker["allowed_paths"], "worker.allowed_paths")


def _validate_execution_dag(package: Mapping[str, Any], mini: bool) -> None:
    dag = package["execution_dag"]
    if not isinstance(dag, dict) or not isinstance(dag.get("tasks"), list) or not isinstance(dag.get("edges"), list):
        raise CogitoError("execution_dag must contain tasks and edges")
    if not dag["tasks"]:
        raise CogitoError("execution_dag requires at least one task")
    for task in dag["tasks"]:
        _validate_task(task)
    for edge in dag["edges"]:
        # Keep the existing object and two-item sequence forms of DAG edges.
        if isinstance(edge, dict):
            require_object(edge, "DAG edge", "from", "to")
            ends = (edge["from"], edge["to"])
        elif isinstance(edge, (list, tuple)) and len(edge) == 2:
            ends = edge
        else:
            raise CogitoError("each DAG edge must contain from and to")
        for endpoint in ends:
            require_id(endpoint, "DAG endpoint")
    ready_tasks(dag["tasks"], dag["edges"])
    slice_ids = {item["id"] for item in package["slices"]}
    slice_paths = {item["id"]: item["worker"]["allowed_paths"] for item in package["slices"]}
    for task in dag["tasks"]:
        if any(not path_allowed(path, package["approved_paths"]) for path in task.get("paths", [])):
            raise CogitoError("task paths must stay within approved_paths")
        if not mini and task.get("slice_id") not in slice_ids:
            raise CogitoError("each Development Package task must reference a Package Slice")
        if not mini and any(not path_allowed(path, slice_paths[task["slice_id"]]) for path in task.get("paths", [])):
            raise CogitoError("task path exceeds its Slice worker responsibility")
    if not mini:
        task_slices = {task["id"]: task["slice_id"] for task in dag["tasks"]}
        slice_edges = sorted({
            (task_slices[source], task_slices[target])
            for source, target in map(edge_pair, dag["edges"])
            if task_slices[source] != task_slices[target]
        })
        ready_tasks(
            [{"id": slice_id, "slice_id": slice_id, "status": "pending"} for slice_id in slice_ids],
            [{"from": source, "to": target} for source, target in slice_edges],
        )
    for item in package["slices"]:
        if any(not path_allowed(path, package["approved_paths"]) for path in item["worker"]["allowed_paths"]):
            raise CogitoError("worker allowed paths must be contained by approved_paths")


def _validate_task(task: Any) -> None:
    require_object(task, "task", "id")
    require_id(task["id"], "task.id")
    if task.get("slice_id") is not None:
        require_id(task["slice_id"], "task.slice_id")
    require_paths(task.get("paths", []), "task.paths")
    if "status" in task:
        require_choice(task["status"], "task.status", {"pending", "leased", "running", "blocked", "complete", "verified", "reviewed", "integrated"})
    if "depends_on" in task:
        for dependency in require_array(task["depends_on"], "task.depends_on"):
            require_id(dependency, "task dependency")


def _validate_stop_conditions(conditions: Any) -> None:
    for condition in require_array(conditions, "stop_conditions", nonempty=True):
        if isinstance(condition, str):
            require_string(condition, "stop condition")
        else:
            require_object(condition, "stop condition", "id", "condition", "outcome")
            require_id(condition["id"], "stop condition.id")
            require_string(condition["condition"], "stop condition.condition")
            require_choice(condition["outcome"], "stop condition.outcome", {"blocked", "awaiting-human", "cancelled"})


def validate_check(check: Any) -> None:
    """Shared executable check definition for both Packages and Amendments."""
    require_object(check, "check", "id", "argv")
    require_id(check["id"], "check.id")
    require_strings(check["argv"], "check.argv", nonempty=True)
    cwd = check.get("cwd", ".")
    require_string(cwd, "check.cwd")
    if not safe_repo_path(cwd):
        raise CogitoError("check cwd escapes the worktree")
    require_integer(check.get("timeout_seconds", 300), "timeout_seconds", 1, 3600)
    require_boolean(check.get("required", True), "check.required")
    _validate_environment_names(check.get("env_allowlist", []), "check.env_allowlist")
    for pattern in require_array(check.get("redact_patterns", []), "redact_patterns"):
        # An empty regular expression is valid; non-string values are not.
        if not isinstance(pattern, str):
            raise CogitoError("redact_patterns entries must be strings")
        try:
            re.compile(pattern)
        except (re.error, OverflowError) as exc:
            raise CogitoError(f"invalid redaction pattern: {exc}") from exc


def _validate_checks(package: Mapping[str, Any]) -> list[str]:
    checks = require_array(package["checks"], "checks", nonempty=True)
    for check in checks:
        validate_check(check)
    check_ids = [check["id"] for check in checks]
    if len(check_ids) != len(set(check_ids)):
        raise CogitoError("check ids must be unique")
    return check_ids


def validate_human_gate(human: Any, *, frozen: bool = False) -> None:
    require_object(human, "human_gate", *(("predicates",) if frozen else ()))
    for item in require_array(human.get("predicates", []), "human_gate.predicates"):
        require_object(item, "human predicate", "id", "applicable")
        require_id(item["id"], "human predicate.id")
        require_boolean(item["applicable"], "human predicate.applicable")
    require_paths(human.get("high_risk_hotspots", []), "human_gate.high_risk_hotspots")
    if "required" in human:
        require_boolean(human["required"], "human_gate.required")


def _validate_environment_names(value: Any, name: str) -> None:
    require_strings(value, name)
    if any("=" in item for item in value):
        raise CogitoError(f"{name} must contain environment variable names without '='")


def validate_check_environment(
    check: Mapping[str, Any], allowed_environment: Sequence[str]
) -> None:
    """Keep a check's requested host environment within the frozen Package policy."""
    requested = check.get("env_allowlist", [])
    _validate_environment_names(requested, "check.env_allowlist")
    _validate_environment_names(allowed_environment, "allowed_environment")
    if set(requested) - set(allowed_environment):
        raise CogitoError("check environment exceeds its frozen policy snapshot")


def _validate_policy_fields(policy: Mapping[str, Any]) -> None:
    require_integer(policy.get("max_workers", 3), "max_workers", 1, 3)
    require_boolean(policy.get("fetch_allowed", False), "fetch_allowed")
    _validate_environment_names(policy.get("allowed_environment", []), "allowed_environment")
    for check_id in require_array(policy.get("required_checks", []), "required_checks"):
        require_id(check_id, "required check id")
    require_integer(
        policy.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES),
        "max_check_output_bytes", MIN_MAX_CHECK_OUTPUT_BYTES, MAX_MAX_CHECK_OUTPUT_BYTES,
    )


def validate_project_policy(policy: Any) -> None:
    """Validate a policy before the Gate compares its restrictions to a Package."""
    require_object(policy, "Project Policy", "schema_version")
    require_choice(policy["schema_version"], "Project Policy.schema_version", {"3.0"})
    _validate_policy_fields(policy)
    validate_human_gate(policy.get("human_gate", {}))


def _validate_policy_snapshot(package: Mapping[str, Any], check_ids: Sequence[Any]) -> None:
    policy = require_object(package["policy_snapshot"], "policy_snapshot", "max_workers", "fetch_allowed")
    _validate_policy_fields(policy)
    if "hash" in policy:
        require_string(policy["hash"], "policy_snapshot.hash", CONTENT_HASH_RE)
    allowed_environment = policy.get("allowed_environment", [])
    required_checks = policy.get("required_checks", [])
    if set(required_checks) - set(check_ids):
        raise CogitoError("Package omits checks frozen by its policy snapshot")
    for check in package["checks"]:
        validate_check_environment(check, allowed_environment)


def _validate_amendment_shape(amendment: Any) -> None:
    allowed = {"id", "reason", "added_checks", "added_tasks", "path_fixes", "commit_id"}
    require_object(amendment, "amendment", "id", "reason")
    if set(amendment) - allowed:
        raise CogitoError(f"amendment attempts forbidden changes: {sorted(set(amendment) - allowed)}")
    require_id(amendment["id"], "amendment.id")
    require_string(amendment["reason"], "amendment.reason")
    if "commit_id" in amendment:
        require_string(amendment["commit_id"], "amendment.commit_id", GIT_OBJECT_RE)
    for check in require_array(amendment.get("added_checks", []), "added_checks"):
        validate_check(check)
    for task in require_array(amendment.get("added_tasks", []), "added_tasks"):
        require_object(task, "added task", "id", "slice_id", "paths")
        _validate_task(task)
        require_id(task["slice_id"], "added task.slice_id")
    require_paths(amendment.get("path_fixes", []), "path_fixes")


def validate_amendment(package: Mapping[str, Any], prior: Sequence[Mapping[str, Any]], amendment: Mapping[str, Any]) -> None:
    validate_package(package)
    if not isinstance(prior, (list, tuple)):
        raise CogitoError("prior amendments must be a sequence")
    for item in prior:
        _validate_amendment_shape(item)
    _validate_amendment_shape(amendment)
    if amendment["id"] in {item.get("id") for item in prior}:
        raise CogitoError("amendment id must be unique")
    if not any(amendment.get(key) for key in ("added_checks", "added_tasks", "path_fixes")):
        raise CogitoError("amendment must add a check/task or record an in-scope path fix")
    existing_checks = {item["id"] for item in package["checks"]} | {check["id"] for item in prior for check in item.get("added_checks", [])}
    for check in amendment.get("added_checks", []):
        if check["id"] in existing_checks:
            raise CogitoError("added checks require new ids")
        validate_check_environment(
            check, package["policy_snapshot"].get("allowed_environment", [])
        )
        existing_checks.add(check["id"])
    existing_tasks = {item["id"] for item in package["execution_dag"]["tasks"]} | {task["id"] for item in prior for task in item.get("added_tasks", [])}
    for task in amendment.get("added_tasks", []):
        if task["id"] in existing_tasks:
            raise CogitoError("added tasks require new ids")
        if any(not path_allowed(str(path), package["approved_paths"]) for path in task["paths"]):
            raise CogitoError("added task paths must stay within approved paths")
        slices = {item["id"]: item for item in package["slices"]}
        if package["kind"] in {"maintenance", "documentation"}:
            if task["slice_id"] != "mini-package":
                raise CogitoError("Mini Package amendment tasks use slice_id mini-package")
        elif task["slice_id"] not in slices or any(not path_allowed(str(path), slices[task["slice_id"]]["worker"]["allowed_paths"]) for path in task["paths"]):
            raise CogitoError("added task exceeds its Slice worker responsibility")
        existing_tasks.add(task["id"])
    if any(not path_allowed(str(path), package["approved_paths"]) for path in amendment.get("path_fixes", [])):
        raise CogitoError("amendment path_fixes must stay within approved paths")


def effective_contract_hash(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> str:
    validate_package(package)
    validated: list[Mapping[str, Any]] = []
    for amendment in amendments:
        validate_amendment(package, validated, amendment)
        validated.append(amendment)
    return hash_json({"base_package_hash": package_hash(package), "amendments": validated}) if validated else package_hash(package)


def materialize_contract(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    validate_package(package)
    effective = json.loads(json.dumps(package))
    validated: list[Mapping[str, Any]] = []
    for amendment in amendments:
        validate_amendment(package, validated, amendment)
        effective["checks"].extend(json.loads(json.dumps(amendment.get("added_checks", []))))
        effective["execution_dag"]["tasks"].extend(json.loads(json.dumps(amendment.get("added_tasks", []))))
        validated.append(amendment)
    effective["effective_contract_hash"] = effective_contract_hash(package, amendments)
    return effective


def validate_agent_result(result: Mapping[str, Any], package: Mapping[str, Any] | None = None) -> None:
    required_fields = {"schema_version", "run_id", "task_id", "agent_id", "role", "status", "base_commit", "head_commit", "changed_paths", "evidence", "risks", "requested_transition"}
    require_object(result, "agent result", *required_fields)
    require_choice(result["schema_version"], "agent result.schema_version", {"3.0"})
    require_string(result["run_id"], "agent result.run_id", RUN_ID_RE)
    require_id(result["task_id"], "agent result.task_id")
    require_string(result["agent_id"], "agent result.agent_id")
    require_choice(result["role"], "agent result.role", {"implementer", "reviewer", "integrator"})
    require_choice(result["status"], "agent result.status", {"complete", "needs-fix", "blocked"})
    for key in ("base_commit", "head_commit"):
        require_string(result[key], f"agent result.{key}", GIT_OBJECT_RE)
    transitions = {"executing", "verifying", "technical-correction", "reviewing", "review-approved", "review-fix", "integrating", "post-integration-verification", "awaiting-human", "finalizing", "blocked"}
    require_choice(result["requested_transition"], "agent result.requested_transition", transitions)
    require_integer(result.get("repair_attempt", 0), "repair_attempt", 0, 2)
    require_paths(result["changed_paths"], "agent result.changed_paths")
    for key in ("evidence", "risks"):
        require_strings(result[key], f"agent result.{key}")
    if "reviewed_implementer" in result:
        require_string(result["reviewed_implementer"], "reviewed_implementer")
    if result["role"] == "reviewer" and (not result.get("reviewed_implementer") or result.get("reviewed_implementer") == result.get("agent_id")):
        raise CogitoError("an independent reviewer must identify a different implementer")
    if package is not None:
        validate_package(package)
        if result["run_id"] != package["run_id"]:
            raise CogitoError("agent result run_id does not match package")
        if any(not path_allowed(str(path), package["approved_paths"]) for path in result["changed_paths"]):
            raise CogitoError("agent changed a path outside the approved package")
