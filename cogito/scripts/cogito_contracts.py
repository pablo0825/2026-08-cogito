"""Pure validation and materialization of Cogito contracts."""

from __future__ import annotations

import json
import re
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping, Sequence

from cogito_common import ID_RE, CogitoError, hash_json
from cogito_scheduler import edge_pair, ready_tasks


DEFAULT_MAX_CHECK_OUTPUT_BYTES = 10 * 1024 * 1024
MIN_MAX_CHECK_OUTPUT_BYTES = 1024
MAX_MAX_CHECK_OUTPUT_BYTES = 100 * 1024 * 1024
from cogito_workflow import load_workflow


def required(payload: Mapping[str, Any], *keys: str) -> bool:
    return all(payload.get(key) not in (None, "", False, [], {}) for key in keys)


def safe_repo_path(value: Any) -> bool:
    candidate = Path(str(value))
    return bool(str(value).strip()) and not candidate.is_absolute() and ".." not in candidate.parts


def _content_hash(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value)))


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
    required_fields = {
        "schema_version", "run_id", "kind", "delivery_branch", "baseline_commit",
        "shared_understanding", "slices", "execution_dag", "checks",
        "approved_paths", "human_gate", "policy_snapshot", "limits",
        "stop_conditions", "source_registry",
    }
    if not isinstance(package, dict) or not required_fields <= package.keys():
        raise CogitoError(f"package is missing fields: {sorted(required_fields - set(package))}")
    if package["schema_version"] != "3.0" or package["kind"] not in {"feature", "change", "correction", "maintenance", "documentation"}:
        raise CogitoError("unsupported package schema or kind")
    if not re.fullmatch(r"(?:DEV|MNT)-[A-Za-z0-9._-]+", str(package["run_id"])) or not package["delivery_branch"] or not re.fullmatch(r"[0-9a-f]{7,64}", str(package["baseline_commit"])):
        raise CogitoError("package run_id, delivery_branch or baseline_commit is invalid")
    if not isinstance(package["shared_understanding"], dict) or not _content_hash(package["shared_understanding"].get("hash")):
        raise CogitoError("shared_understanding.hash is required")
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
    if not all(isinstance(package[key], list) and package[key] for key in ("checks", "approved_paths", "stop_conditions")):
        raise CogitoError("checks, approved_paths and stop_conditions must be non-empty arrays")
    if any(not safe_repo_path(pattern) for pattern in package["approved_paths"]):
        raise CogitoError("approved_paths must be safe repository-relative patterns")
    _validate_execution_dag(package, mini)
    check_ids = _validate_checks(package)
    _validate_human_gate(package)
    limits = package["limits"]
    global_limits = load_workflow()["limits"]
    retry_names = ("transient_retries", "verification_corrections", "review_fix_cycles", "format_repairs")
    if not isinstance(limits, dict) or any(not isinstance(limits.get(key), int) or not 0 <= limits[key] <= global_limits[key] for key in retry_names):
        raise CogitoError("Package retry limits must be integers no looser than global limits")
    _validate_policy_snapshot(package, check_ids)
    registry = package["source_registry"]
    dispositions = {"read-only-source", "adopted", "updated", "superseded", "not-touched"}
    if not isinstance(registry, list) or any(
        not isinstance(item, dict) or not {"path", "hash", "relevance", "disposition"} <= item.keys()
        or not safe_repo_path(item.get("path")) or not _content_hash(item.get("hash"))
        or item.get("disposition") not in dispositions for item in registry
    ):
        raise CogitoError("source_registry entries require path, hash, relevance and disposition")
    expected = package.get("package_hash")
    if expected is not None and expected != package_hash(package):
        raise CogitoError("package_hash does not match immutable package content")


def _validate_development_slices(package: Mapping[str, Any]) -> None:
    boundary = package.get("boundary")
    if not isinstance(boundary, dict) or boundary.get("decision") not in {"single-slice", "split-required"} or not boundary.get("evidence"):
        raise CogitoError("a Development Package requires a non-blocked boundary decision with evidence")
    if not isinstance(package["slices"], list) or not package["slices"]:
        raise CogitoError("a Development Package requires at least one Slice")
    seen: set[str] = set()
    for item in package["slices"]:
        if not isinstance(item, dict) or not {"id", "type", "spec", "plan", "worker"} <= item.keys():
            raise CogitoError("each Slice requires id, type, spec, plan and worker")
        if item["id"] in seen or item["type"] not in {"feature", "change", "correction"}:
            raise CogitoError("Slice ids must be unique and types valid")
        seen.add(item["id"])
        for document in (item["spec"], item["plan"]):
            if not isinstance(document, dict) or not safe_repo_path(document.get("path")) or not _content_hash(document.get("hash")):
                raise CogitoError("Spec and Plan require frozen path and hash")
        worker = item["worker"]
        if not isinstance(worker, dict) or not required(worker, "branch", "worktree") or not isinstance(worker.get("allowed_paths"), list):
            raise CogitoError("each Slice requires a dedicated worker branch/worktree and allowed paths")


def _validate_execution_dag(package: Mapping[str, Any], mini: bool) -> None:
    dag = package["execution_dag"]
    if not isinstance(dag, dict) or not isinstance(dag.get("tasks"), list) or not isinstance(dag.get("edges"), list):
        raise CogitoError("execution_dag must contain tasks and edges")
    if not dag["tasks"]:
        raise CogitoError("execution_dag requires at least one task")
    ready_tasks(dag["tasks"], dag["edges"])
    slice_ids = {item["id"] for item in package["slices"]}
    slice_paths = {item["id"]: item["worker"]["allowed_paths"] for item in package["slices"]}
    for task in dag["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("paths", []), list) or any(not path_allowed(str(path), package["approved_paths"]) for path in task.get("paths", [])):
            raise CogitoError("task paths must stay within approved_paths")
        if not mini and task.get("slice_id") not in slice_ids:
            raise CogitoError("each Development Package task must reference a Package Slice")
        if not mini and any(not path_allowed(str(path), slice_paths[task["slice_id"]]) for path in task.get("paths", [])):
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
        if any(not path_allowed(str(path), package["approved_paths"]) for path in item["worker"]["allowed_paths"]):
            raise CogitoError("worker allowed paths must be contained by approved_paths")


def _validate_checks(package: Mapping[str, Any]) -> list[Any]:
    check_ids = [item.get("id") for item in package["checks"] if isinstance(item, dict)]
    if (
        len(check_ids) != len(package["checks"]) or len(check_ids) != len(set(check_ids))
        or any(not ID_RE.fullmatch(str(check_id or "")) for check_id in check_ids)
        or any(not isinstance(item.get("argv"), list) or not item["argv"] or not all(isinstance(arg, str) and arg for arg in item["argv"]) for item in package["checks"])
    ):
        raise CogitoError("checks require safe unique ids and non-empty argv arrays")
    return check_ids


def _validate_human_gate(package: Mapping[str, Any]) -> None:
    human = package["human_gate"]
    if not isinstance(human, dict) or not isinstance(human.get("predicates"), list) or not isinstance(human.get("high_risk_hotspots", []), list):
        raise CogitoError("human_gate requires frozen predicates and high_risk_hotspots")
    if any(not isinstance(item, dict) or not {"id", "applicable"} <= item.keys() or not isinstance(item["applicable"], bool) for item in human["predicates"]):
        raise CogitoError("each human predicate requires id and frozen applicable boolean")
    if any(not safe_repo_path(path) for path in human.get("high_risk_hotspots", [])):
        raise CogitoError("human high-risk hotspots must be repository-relative paths")


def _validate_policy_snapshot(package: Mapping[str, Any], check_ids: Sequence[Any]) -> None:
    policy = package["policy_snapshot"]
    if not isinstance(policy, dict) or not isinstance(policy.get("max_workers"), int) or not 1 <= policy["max_workers"] <= 3 or not isinstance(policy.get("fetch_allowed"), bool):
        raise CogitoError("policy_snapshot requires max_workers 1..3 and frozen fetch_allowed")
    allowed_environment = policy.get("allowed_environment", [])
    required_checks = policy.get("required_checks", [])
    if not isinstance(allowed_environment, list) or not all(isinstance(item, str) for item in allowed_environment) or not isinstance(required_checks, list):
        raise CogitoError("policy_snapshot environment and required checks must be arrays")
    if set(required_checks) - set(check_ids):
        raise CogitoError("Package omits checks frozen by its policy snapshot")
    if any(set(check.get("env_allowlist", [])) - set(allowed_environment) for check in package["checks"]):
        raise CogitoError("Package check environment exceeds its frozen policy snapshot")
    output_limit = policy.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES)
    if (
        type(output_limit) is not int
        or not MIN_MAX_CHECK_OUTPUT_BYTES <= output_limit <= MAX_MAX_CHECK_OUTPUT_BYTES
    ):
        raise CogitoError("policy_snapshot max_check_output_bytes must be between 1 KiB and 100 MiB")


def validate_amendment(package: Mapping[str, Any], prior: Sequence[Mapping[str, Any]], amendment: Mapping[str, Any]) -> None:
    validate_package(package)
    allowed = {"id", "reason", "added_checks", "added_tasks", "path_fixes", "commit_id"}
    if not isinstance(amendment, dict) or not {"id", "reason"} <= amendment.keys():
        raise CogitoError("amendment id and reason are required")
    if set(amendment) - allowed:
        raise CogitoError(f"amendment attempts forbidden changes: {sorted(set(amendment) - allowed)}")
    if amendment["id"] in {item.get("id") for item in prior}:
        raise CogitoError("amendment id must be unique")
    if not any(amendment.get(key) for key in ("added_checks", "added_tasks", "path_fixes")):
        raise CogitoError("amendment must add a check/task or record an in-scope path fix")
    existing_checks = {item["id"] for item in package["checks"]} | {check["id"] for item in prior for check in item.get("added_checks", [])}
    for check in amendment.get("added_checks", []):
        if not isinstance(check, dict) or not check.get("id") or not check.get("argv") or check["id"] in existing_checks:
            raise CogitoError("added checks require new ids and non-empty argv")
        existing_checks.add(check["id"])
    existing_tasks = {item["id"] for item in package["execution_dag"]["tasks"]} | {task["id"] for item in prior for task in item.get("added_tasks", [])}
    for task in amendment.get("added_tasks", []):
        if not isinstance(task, dict) or not task.get("id") or task["id"] in existing_tasks or not isinstance(task.get("paths"), list) or not task.get("slice_id"):
            raise CogitoError("added tasks require new ids, slice_id and paths")
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
    if not isinstance(result, dict) or not required_fields <= result.keys():
        raise CogitoError(f"agent result is missing fields: {sorted(required_fields - set(result))}")
    if result["schema_version"] != "3.0" or result["role"] not in {"implementer", "reviewer", "integrator"} or result["status"] not in {"complete", "needs-fix", "blocked"}:
        raise CogitoError("unsupported agent result value")
    if not re.fullmatch(r"[0-9a-f]{7,64}", str(result["base_commit"])) or not re.fullmatch(r"[0-9a-f]{7,64}", str(result["head_commit"])):
        raise CogitoError("Agent Result base/head commit ids are invalid")
    transitions = {"executing", "verifying", "technical-correction", "reviewing", "review-approved", "review-fix", "integrating", "post-integration-verification", "awaiting-human", "finalizing", "blocked"}
    if result["requested_transition"] not in transitions:
        raise CogitoError("Agent Result requested_transition is invalid")
    repair_attempt = result.get("repair_attempt", 0)
    if isinstance(repair_attempt, bool) or not isinstance(repair_attempt, int) or not 0 <= repair_attempt <= 2:
        raise CogitoError("agent result repair_attempt must be an integer from 0 through 2")
    for key in ("changed_paths", "evidence", "risks"):
        if not isinstance(result[key], list):
            raise CogitoError(f"agent result {key} must be an array")
    if result["status"] == "complete" and result["role"] != "reviewer" and not result["head_commit"]:
        raise CogitoError("completed implementation/integration requires head_commit")
    if result["role"] == "reviewer" and (not result.get("reviewed_implementer") or result.get("reviewed_implementer") == result.get("agent_id")):
        raise CogitoError("an independent reviewer must identify a different implementer")
    if package:
        validate_package(package)
        if result["run_id"] != package["run_id"]:
            raise CogitoError("agent result run_id does not match package")
        if any(not path_allowed(str(path), package["approved_paths"]) for path in result["changed_paths"]):
            raise CogitoError("agent changed a path outside the approved package")
