"""Gate policy, review, and immutable-evidence validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from cogito_common import CogitoError, hash_json, load_json
from cogito_contracts import (
    DEFAULT_MAX_CHECK_OUTPUT_BYTES,
    MAX_MAX_CHECK_OUTPUT_BYTES,
    MIN_MAX_CHECK_OUTPUT_BYTES,
    materialize_contract,
)


def validate_policy(root: Path, package: Mapping[str, Any]) -> None:
    """Ensure a Package is no less restrictive than Project Policy."""
    policy_path = root / "docs" / "cogito" / "project-policy.json"
    snapshot = package["policy_snapshot"]
    if not policy_path.exists():
        if snapshot.get("fetch_allowed") is not False:
            raise CogitoError("fetch is not authorized without Project Policy")
        if snapshot.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES) > DEFAULT_MAX_CHECK_OUTPUT_BYTES:
            raise CogitoError("Package check output limit is looser than the default Project Policy")
        return

    project = load_json(policy_path)
    if project.get("schema_version") != "3.0":
        raise CogitoError("Project Policy schema_version must be 3.0")
    if snapshot.get("hash") != hash_json(project):
        raise CogitoError("Package policy snapshot does not match current Project Policy")
    if snapshot["max_workers"] > int(project.get("max_workers", 3)):
        raise CogitoError("Package max_workers is looser than Project Policy")
    if snapshot.get("fetch_allowed") is True and project.get("fetch_allowed") is not True:
        raise CogitoError("Package cannot authorize fetch beyond Project Policy")
    project_output_limit = project.get(
        "max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES
    )
    if (
        type(project_output_limit) is not int
        or not MIN_MAX_CHECK_OUTPUT_BYTES
        <= project_output_limit
        <= MAX_MAX_CHECK_OUTPUT_BYTES
    ):
        raise CogitoError("Project Policy max_check_output_bytes must be between 1 KiB and 100 MiB")
    if snapshot.get("max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES) > project_output_limit:
        raise CogitoError("Package check output limit is looser than Project Policy")

    required_checks = set(project.get("required_checks", []))
    if not required_checks <= {item["id"] for item in package["checks"]}:
        raise CogitoError("Package omits checks required by Project Policy")
    allowed_env = set(project.get("allowed_environment", []))
    for check in package["checks"]:
        if set(check.get("env_allowlist", [])) - allowed_env:
            raise CogitoError("Package check environment exceeds Project Policy")

    project_human = project.get("human_gate", {})
    package_predicates = {
        item["id"]: item["applicable"] for item in package["human_gate"]["predicates"]
    }
    for predicate in project_human.get("predicates", []):
        if predicate.get("applicable") is True and package_predicates.get(predicate.get("id")) is not True:
            raise CogitoError("Package removes a Human Gate required by Project Policy")
    if not set(project_human.get("high_risk_hotspots", [])) <= set(
        package["human_gate"]["high_risk_hotspots"]
    ):
        raise CogitoError("Package removes high-risk hotspots required by Project Policy")
    if project_human.get("required") is True and not (
        package["human_gate"]["high_risk_hotspots"] or any(package_predicates.values())
    ):
        raise CogitoError("Project Policy requires a Human Gate")


def validate_review(
    package: Mapping[str, Any],
    load_state: Callable[[], Mapping[str, Any]],
    payload: MutableMapping[str, Any],
) -> None:
    """Derive the Gate-owned review verdict for the current verification wave."""
    if payload.get("review_exemption") is True:
        if package["kind"] != "maintenance" or not all(package["maintenance_guards"].values()):
            raise CogitoError(
                "independent-review exemption is only valid for objectively low-risk Maintenance"
            )
        state = load_state()
        payload["reviews"] = sorted(
            task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified"
        )
        if not payload["reviews"]:
            raise CogitoError("review exemption requires verified Maintenance tasks")
        payload["approved"] = True
        payload["independent"] = False
        return

    state = load_state()
    expected = {
        task_id for task_id, task in state["tasks"].items() if task.get("status") == "verified"
    }
    if not expected:
        raise CogitoError("review approval requires completed implementation tasks")
    latest: dict[str, Mapping[str, Any]] = {}
    for result in state["agent_results"]:
        if result.get("role") == "reviewer":
            latest[str(result.get("task_id"))] = result
    closed = {
        result["task_id"]
        for result in latest.values()
        if result.get("task_id") in expected
        and result.get("status") == "complete"
        and result.get("requested_transition") == "review-approved"
        and result.get("reviewed_implementer")
        == state["tasks"].get(result.get("task_id"), {}).get("agent_id")
        and result.get("agent_id")
        != state["tasks"].get(result.get("task_id"), {}).get("agent_id")
    }
    if closed != expected:
        raise CogitoError(
            "every completed implementation task requires a Gate-recorded independent Reviewer Result"
        )
    payload["reviews"] = sorted(closed)
    payload["approved"] = True
    payload["independent"] = True


def validate_evidence(
    package: Mapping[str, Any],
    evidence: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    load_ledger: Callable[[], Mapping[str, Any]],
    run_dir: Path,
    load_current_head: Callable[[], str] | None = None,
) -> None:
    """Validate controlled-runner evidence against its contract and event cycle."""
    prior = [
        item["payload"]["amendment"]
        for item in events
        if item["type"] == "technical-amendment-added"
    ]
    effective = materialize_contract(package, prior)
    required = {item["id"]: item for item in effective["checks"] if item.get("required", True)}
    supplied = {item.get("check_id"): item for item in evidence}
    anchors = (
        {"integration-complete", "post-integration-correction-complete"}
        if load_current_head is not None
        else {"implementation-complete", "technical-correction-complete", "review-fix-complete"}
    )
    anchor_sequence = max(
        (item["sequence"] for item in events if item["type"] in anchors), default=0
    )
    if set(required) - set(supplied):
        raise CogitoError("required verification evidence is missing")

    evidence_root = (run_dir / "evidence").resolve()
    for check_id, check in required.items():
        item = supplied[check_id]
        evidence_path = Path(str(item.get("evidence_path", ""))).resolve()
        try:
            evidence_path.relative_to(evidence_root)
        except ValueError as exc:
            raise CogitoError(f"evidence path is outside this run for {check_id}") from exc
        if not evidence_path.is_file():
            raise CogitoError(f"immutable evidence file is missing for {check_id}")
        recorded = load_json(evidence_path)
        if recorded != item:
            raise CogitoError(
                f"evidence payload does not match its immutable file for {check_id}"
            )
        entry = load_ledger().get("evidence", {}).get(str(evidence_path))
        if (
            not entry
            or entry.get("evidence_hash") != hash_json(recorded)
            or entry.get("check_id") != check_id
        ):
            raise CogitoError(
                f"evidence was not produced and recorded by the controlled runner for {check_id}"
            )
        if int(entry.get("event_sequence") or 0) <= anchor_sequence:
            raise CogitoError(f"evidence predates the current verification cycle for {check_id}")
        if (
            item.get("passed") is not True
            or item.get("check_hash") != hash_json(check)
            or item.get("effective_contract_hash") != effective["effective_contract_hash"]
        ):
            raise CogitoError(f"evidence binding failed for {check_id}")
        expected_output_limit = package["policy_snapshot"].get(
            "max_check_output_bytes", DEFAULT_MAX_CHECK_OUTPUT_BYTES
        )
        recorded_output_limit = item.get("output_limit_bytes")
        if (
            item.get("output_limit_exceeded") is not False
            or item.get("termination_degraded") is not False
            or recorded_output_limit != expected_output_limit
        ):
            raise CogitoError(f"evidence output policy binding failed for {check_id}")
        binding = item.get("worktree_binding")
        if not isinstance(binding, dict) or binding.get("snapshot_hash") != item.get("tree_hash"):
            raise CogitoError(f"working-tree binding is missing for {check_id}")
        binding_body = {key: value for key, value in binding.items() if key != "snapshot_hash"}
        if hash_json(binding_body) != binding["snapshot_hash"]:
            raise CogitoError(f"working-tree binding hash is invalid for {check_id}")
        if load_current_head is not None and item.get("head_commit") != load_current_head():
            raise CogitoError(
                f"post-integration evidence is not bound to current HEAD for {check_id}"
            )
