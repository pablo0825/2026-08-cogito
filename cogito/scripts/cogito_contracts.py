"""Contract rules with explicit limits and wrappers that load workflow settings."""

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
from cogito_path_amendment_contract import (
    apply_path_additions, validate_path_additions, validate_path_additions_shape,
)
from cogito_scheduler import ready_tasks, slice_dependencies, tasks_with_dependencies
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


def validate_shared_understanding_hash(value: Any) -> None:
    require_string(value, "shared_understanding.hash", CONTENT_HASH_RE)


def validate_boundary(value: Any) -> None:
    boundary = require_object(value, "boundary", "decision", "evidence")
    require_choice(boundary["decision"], "boundary.decision", {"single-slice", "split-required"})
    require_strings(boundary["evidence"], "boundary.evidence", nonempty=True)


def validate_preparation_event(event: str, payload: Mapping[str, Any]) -> None:
    """Validate new preparation inputs without changing historical projection."""
    if event in {"shared-understanding-ready", "shared-understanding-confirmed", "boundary-complete"}:
        require_object(payload, "preparation payload")
    if event == "shared-understanding-ready":
        validate_shared_understanding_hash(payload.get("shared_understanding_hash"))
    elif event == "shared-understanding-confirmed" and "shared_understanding_hash" in payload:
        validate_shared_understanding_hash(payload["shared_understanding_hash"])
    elif event == "boundary-complete":
        validate_boundary(payload)


def validate_package(package: Mapping[str, Any]) -> None:
    """Load default workflow limits and validate a Package without changing it."""
    validate_package_with_limits(package, load_workflow()["limits"])


def validate_package_with_limits(
    package: Mapping[str, Any], workflow_limits: Mapping[str, int],
) -> None:
    """Validate shape and Package invariants without rewriting caller data.

    Workflow limits are supplied by the caller; this function performs no I/O.
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
    validate_shared_understanding_hash(shared["hash"])
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
    _validate_checks(package)
    _validate_task_delivery(package)
    validate_human_gate(package["human_gate"], frozen=True)
    limits = package["limits"]
    retry_names = ("transient_retries", "verification_corrections", "review_fix_cycles", "format_repairs")
    require_object(limits, "limits", *retry_names)
    for key in retry_names:
        require_integer(limits[key], f"limits.{key}", 0, workflow_limits[key])
    if 'human_corrections' in limits:
        require_integer(limits['human_corrections'], 'limits.human_corrections', 1,
                        min(3, workflow_limits.get('human_corrections', 3)))
    _validate_policy_snapshot(package)
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
    validate_boundary(package.get("boundary"))
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
        ends: Sequence[Any]
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
    for task, derived in zip(dag["tasks"], tasks_with_dependencies(dag)):
        if "depends_on" in task and set(task["depends_on"]) != set(derived["depends_on"]):
            raise CogitoError("task.depends_on must match execution_dag.edges")
    slice_ids = {item["id"] for item in package["slices"]}
    slice_paths = {item["id"]: item["worker"]["allowed_paths"] for item in package["slices"]}
    for task in dag["tasks"]:
        if mini and task.get("slice_id") not in (None, "mini-package"):
            raise CogitoError("Mini Package tasks use slice_id mini-package or omit it")
        if any(not path_allowed(path, package["approved_paths"]) for path in task.get("paths", [])):
            raise CogitoError("task paths must stay within approved_paths")
        if not mini and task.get("slice_id") not in slice_ids:
            raise CogitoError("each Development Package task must reference a Package Slice")
        if not mini and any(not path_allowed(path, slice_paths[task["slice_id"]]) for path in task.get("paths", [])):
            raise CogitoError("task path exceeds its Slice worker responsibility")
    if not mini:
        slice_edges = sorted(slice_dependencies(dag))
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
    """Validate frozen policy declarations, not whether their conditions are true.

    The Coordinator evaluates the described evidence and requests a legal Gate
    transition. An outcome is policy intent, not an executable transition.
    """
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
    if "phase" in check:
        require_choice(check["phase"], "check.phase", {"task", "integration"})
    _validate_environment_names(check.get("env_allowlist", []), "check.env_allowlist")
    for pattern in require_array(check.get("redact_patterns", []), "redact_patterns"):
        # An empty regular expression is valid; non-string values are not.
        if not isinstance(pattern, str):
            raise CogitoError("redact_patterns entries must be strings")
        try:
            re.compile(pattern)
        except (re.error, OverflowError) as exc:
            raise CogitoError(f"invalid redaction pattern: {exc}") from exc


def _validate_checks(package: Mapping[str, Any]) -> None:
    checks = require_array(package["checks"], "checks", nonempty=True)
    for check in checks:
        validate_check(check)
    check_ids = [check["id"] for check in checks]
    if len(check_ids) != len(set(check_ids)):
        raise CogitoError("check ids must be unique")


def _validate_task_delivery(package: Mapping[str, Any]) -> None:
    """Opt-in atomic delivery preserves the meaning and hashes of frozen Packages."""
    if "task_delivery" not in package:
        if any("phase" in check for check in package["checks"]):
            raise CogitoError("check.phase requires atomic task delivery")
        return
    require_choice(package["task_delivery"], "task_delivery", {"atomic"})
    if package["kind"] not in {"feature", "change", "correction"}:
        raise CogitoError("atomic task delivery requires feature, change, or correction")
    checks = {check["id"]: check for check in package["checks"]}
    if not any(check.get("required", True) and check.get("phase", "integration") == "integration"
               for check in checks.values()):
        raise CogitoError("atomic task delivery requires a required integration check")
    targeted: set[str] = set()
    for task in package["execution_dag"]["tasks"]:
        require_string(task.get("responsibility"), "task.responsibility")
        require_paths(task.get("paths"), "task.paths", nonempty=True)
        require_strings(task.get("check_ids"), "task.check_ids", nonempty=True)
        check_ids = task["check_ids"]
        if len(check_ids) != len(set(check_ids)):
            raise CogitoError("task.check_ids must be unique")
        for check_id in check_ids:
            require_id(check_id, "task check id")
            if check_id not in checks or checks[check_id].get("required", True) is not True:
                raise CogitoError("task.check_ids must reference required checks")
            targeted.add(check_id)
    orphaned = sorted(check_id for check_id, check in checks.items()
                      if check.get("required", True) and check.get("phase") == "task"
                      and check_id not in targeted)
    if orphaned:
        raise CogitoError(f"required task checks must be referenced by a task: {orphaned}")


def validate_required_checks(
    checks: Sequence[Mapping[str, Any]], required_ids: Sequence[str], source: str,
) -> None:
    """Enforce policy requirements on validated checks without rewriting them.

    Omitting `required` keeps the established default of True. Both Project
    Policy and the frozen snapshot use this rule, including optional downgrades.
    """
    by_id = {check["id"]: check for check in checks}
    missing = set(required_ids) - by_id.keys()
    if missing:
        raise CogitoError(f"Package omits checks required by {source}: {sorted(missing)}")
    optional = sorted({
        check_id for check_id in required_ids
        if by_id[check_id].get("required", True) is not True
    })
    if optional:
        raise CogitoError(f"Package marks checks required by {source} as optional: {optional}")
    task_only = sorted(check_id for check_id in required_ids
                       if by_id[check_id].get("phase", "integration") != "integration")
    if task_only:
        raise CogitoError(f"checks required by {source} must remain integration-scoped: {task_only}")


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


def _validate_policy_snapshot(package: Mapping[str, Any]) -> None:
    policy = require_object(package["policy_snapshot"], "policy_snapshot", "max_workers", "fetch_allowed")
    _validate_policy_fields(policy)
    if "hash" in policy:
        require_string(policy["hash"], "policy_snapshot.hash", CONTENT_HASH_RE)
    allowed_environment = policy.get("allowed_environment", [])
    validate_required_checks(package["checks"], policy.get("required_checks", []), "policy snapshot")
    for check in package["checks"]:
        validate_check_environment(check, allowed_environment)


def _validate_amendment_shape(amendment: Any) -> None:
    allowed = {"id", "reason", "added_checks", "added_tasks", "path_fixes", "commit_id", "path_additions"}
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
    validate_path_additions_shape(amendment)


def validate_amendment(package: Mapping[str, Any], prior: Sequence[Mapping[str, Any]], amendment: Mapping[str, Any]) -> None:
    """Validate the complete ordered history, including the proposed addition."""
    if not isinstance(prior, (list, tuple)):
        raise CogitoError("prior amendments must be a sequence")
    materialize_contract(package, [*prior, amendment])


def _validate_amendment_changes(effective: Mapping[str, Any], amendment: Mapping[str, Any]) -> None:
    """Check a shaped amendment against the already validated effective prefix."""
    if not any(amendment.get(key) for key in ("added_checks", "added_tasks", "path_fixes", "path_additions")):
        raise CogitoError("amendment must add a check/task or record an in-scope path fix")
    validate_path_additions(effective, amendment)
    existing_checks = {item["id"] for item in effective["checks"]}
    for check in amendment.get("added_checks", []):
        if check["id"] in existing_checks:
            raise CogitoError("added checks require new ids")
        validate_check_environment(
            check, effective["policy_snapshot"].get("allowed_environment", [])
        )
        existing_checks.add(check["id"])
    existing_tasks = {item["id"] for item in effective["execution_dag"]["tasks"]}
    slices = {item["id"]: item for item in effective["slices"]}
    for task in amendment.get("added_tasks", []):
        if task["id"] in existing_tasks:
            raise CogitoError("added tasks require new ids")
        if any(not path_allowed(str(path), effective["approved_paths"]) for path in task["paths"]):
            raise CogitoError("added task paths must stay within approved paths")
        if effective["kind"] in {"maintenance", "documentation"}:
            if task["slice_id"] != "mini-package":
                raise CogitoError("Mini Package amendment tasks use slice_id mini-package")
        elif task["slice_id"] not in slices or any(not path_allowed(str(path), slices[task["slice_id"]]["worker"]["allowed_paths"]) for path in task["paths"]):
            raise CogitoError("added task exceeds its Slice worker responsibility")
        existing_tasks.add(task["id"])
    if any(not path_allowed(str(path), effective["approved_paths"]) for path in amendment.get("path_fixes", [])):
        raise CogitoError("amendment path_fixes must stay within approved paths")


def effective_contract_hash(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> str:
    """Return the digest from the same validation path used by execution."""
    return materialize_contract(package, amendments)["effective_contract_hash"]


def materialize_contract(package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Load default workflow limits and materialize the effective contract."""
    return materialize_contract_with_limits(package, amendments, load_workflow()["limits"])


def materialize_contract_with_limits(
    package: Mapping[str, Any], amendments: Sequence[Mapping[str, Any]],
    workflow_limits: Mapping[str, int],
) -> dict[str, Any]:
    """Validate the base once, apply amendments in order, and return data plus hash.

    The caller supplies workflow limits, so materialization performs no I/O.
    Each prefix must be executable on its own: a later amendment cannot repair
    an earlier invalid dependency. Only raw inputs contribute to the digest.
    """
    validate_package_with_limits(package, workflow_limits)
    base_hash = package_hash(package)
    effective = json.loads(json.dumps(package))
    frozen_dependencies = slice_dependencies(package["execution_dag"])
    mini = package["kind"] in {"maintenance", "documentation"}
    amendment_ids: set[str] = set()
    validated: list[Mapping[str, Any]] = []
    for amendment in amendments:
        _validate_amendment_shape(amendment)
        if amendment["id"] in amendment_ids:
            raise CogitoError("amendment id must be unique")
        _validate_amendment_changes(effective, amendment)
        addition = json.loads(json.dumps(amendment))
        effective["checks"].extend(addition.get("added_checks", []))
        apply_path_additions(effective, addition)
        dag = effective["execution_dag"]
        dag["tasks"].extend(addition.get("added_tasks", []))
        dag["edges"].extend(
            {"from": dependency, "to": task["id"]}
            for task in addition.get("added_tasks", []) for dependency in task.get("depends_on", [])
        )
        _validate_execution_dag(effective, mini)
        _validate_task_delivery(effective)
        if slice_dependencies(dag) != frozen_dependencies:
            raise CogitoError("amendment cannot change approved Slice dependencies")
        amendment_ids.add(amendment["id"])
        validated.append(amendment)
    effective["effective_contract_hash"] = (
        hash_json({"base_package_hash": base_hash, "amendments": validated}) if validated else base_hash
    )
    return effective


def validate_agent_result(
    result: Mapping[str, Any], package: Mapping[str, Any] | None = None, *,
    workflow_limits: Mapping[str, int] | None = None,
    approved_paths: Sequence[str] | None = None,
) -> None:
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
        if workflow_limits is None:
            validate_package(package)
        else:
            validate_package_with_limits(package, workflow_limits)
        if result["run_id"] != package["run_id"]:
            raise CogitoError("agent result run_id does not match package")
        result_paths = package["approved_paths"] if approved_paths is None else approved_paths
        if any(not path_allowed(str(path), result_paths) for path in result["changed_paths"]):
            raise CogitoError("agent changed a path outside the approved package")
