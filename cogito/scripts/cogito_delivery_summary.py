"""Pure, reproducible delivery history embedded in the final Result.

The event ledger remains authoritative. This is a compact index of receipts,
not a second audit log; a recorded check alone never implies that it passed.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from cogito_common import CogitoError
from cogito_contract_fields import (
    CONTENT_HASH_RE, GIT_OBJECT_RE, require_array, require_boolean,
    require_choice, require_integer, require_object, require_path, require_string, require_strings,
)


SECTIONS = ("preparation", "implementation", "integration", "corrections", "verification", "reviews", "human_acceptance")
INTEGRATION_EVENTS = {"slice-integration-complete", "wave-integration-complete", "integration-complete"}
CORRECTION_EVENTS = {"technical-correction-complete", "post-integration-correction-complete",
                     "review-fix-complete", "human-correction-complete"}
VERIFICATION_EVENTS = {
    "check-evidence-recorded", "verification-passed", "verification-correction-required",
    "post-verification-correction-required", "human-review-required", "auto-accept-ready",
    "human-correction-verified", "human-correction-reviewed", "human-correction-accepted",
    "review-approved", "review-fix-required",
}
HUMAN_EVENTS = {
    "human-review-required", "auto-accept-ready", "human-approved", "human-feedback-queued",
    "human-feedback-recorded", "human-feedback-classified", "human-correction-started",
    "human-correction-complete", "human-correction-verified", "human-correction-reviewed",
    "human-correction-accepted", "human-feedback-escalated", "human-correction-exhausted",
}
RECEIPT_FIELDS = (
    "check_id", "evidence_path", "evidence_hash", "head_commit", "effective_contract_hash",
    "evidence", "passed", "delivery_head", "human_required", "reviewer_escalation",
    "binding", "feedback_hash", "approved", "conditional", "amendment_id", "task_ids",
    "reviews", "commit_id", "completion_mode", "content_tree", "failed_evidence", "reason", "independent",
    "review_task_id", "reviewer", "review_head",
)


def _select(value: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {key: deepcopy(value[key]) for key in fields if key in value}


def build_delivery_summary(state: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Copy meaningful receipts in ledger order, without filesystem or Git IO."""
    summary: dict[str, Any] = {"schema_version": "1.0", **{key: [] for key in SECTIONS}}
    for event in events:
        kind, payload = event["type"], event.get("payload", {})
        marker = {"event_sequence": event["sequence"], "event": kind}
        if kind == "stage-committed":
            summary["preparation"].append({**marker, **_select(payload, (
                "stage_sequence", "stage", "commit_id", "base_commit", "branch", "files"))})
        if kind == "agent-result-recorded":
            result = payload["result"]
            role = result["role"]
            if role not in {"implementer", "reviewer"}:
                continue
            record = {**marker, **_select(result, (
                "task_id", "status", "base_commit", "head_commit", "evidence", "changed_paths", "requested_transition"))}
            if role == "implementer":
                record["agent_id"] = result["agent_id"]
                if state.get("kind") == "maintenance":
                    record.pop("head_commit", None)
                    record["completion_mode"] = "working-tree"
                    if "maintenance_end_tree" in payload:
                        record["content_tree"] = payload["maintenance_end_tree"]
                    if "maintenance_end_index_tree" in payload:
                        record["index_tree"] = payload["maintenance_end_index_tree"]
                else:
                    record["completion_mode"] = "commit"
                summary["implementation"].append(record)
            else:
                record.update(reviewer=result["agent_id"], implementer=result["reviewed_implementer"])
                summary["reviews"].append(record)
        if kind in INTEGRATION_EVENTS:
            summary["integration"].append({**marker, **_select(payload, (
                "commit_id", "previous_delivery_head", "slice_id", "task_ids", "source_heads"))})
        if kind in CORRECTION_EVENTS:
            record = {**marker, **_select(payload, ("amendment_id", "commit_id", "content_tree"))}
            if state.get("kind") == "maintenance":
                record["completion_mode"] = "working-tree"
                record["base_commit"] = record.pop("commit_id")
                if "binding" in payload:
                    record["content_tree"] = payload["binding"]["content_tree"]
            else:
                record["completion_mode"] = "commit"
            summary["corrections"].append(record)
        if kind in VERIFICATION_EVENTS:
            summary["verification"].append({**marker, **_select(payload, RECEIPT_FIELDS)})
        if kind in HUMAN_EVENTS:
            record = {**marker, **_select(payload, RECEIPT_FIELDS)}
            if "feedback" in payload:
                feedback = payload["feedback"]
                record["feedback"] = {**_select(feedback, ("id", "acceptance_complete", "close_after_fixes")),
                                      "item_ids": [item["id"] for item in feedback["items"]]}
            if "triage" in payload:
                triage = payload["triage"]
                record["triage"] = {**_select(triage, ("feedback_id", "route", "active_item_ids",
                                                     "deferred_item_ids", "split_authorized")),
                                    "assessments": [_select(item, ("id", "disposition"))
                                                    for item in triage["assessments"]]}
            if "resolution" in payload:
                record["resolution"] = _select(payload["resolution"], ("feedback_id", "resolved_item_ids", "summary"))
            summary["human_acceptance"].append(record)
    return summary


def _validate_receipt(record: Any, name: str) -> None:
    require_object(record, name, "event_sequence", "event")
    require_integer(record["event_sequence"], f"{name}.event_sequence", 1, 2**63 - 1)
    require_string(record["event"], f"{name}.event")
    for key in ("commit_id", "base_commit", "head_commit", "delivery_head", "previous_delivery_head", "content_tree", "index_tree", "review_head"):
        if key in record:
            require_string(record[key], f"{name}.{key}", GIT_OBJECT_RE)
    for key in ("feedback_hash", "evidence_hash", "effective_contract_hash"):
        if key in record:
            require_string(record[key], f"{name}.{key}", CONTENT_HASH_RE)
    for key in ("task_id", "agent_id", "reviewer", "implementer", "slice_id", "branch", "check_id", "evidence_path", "amendment_id", "reason", "requested_transition", "review_task_id"):
        if key in record:
            require_string(record[key], f"{name}.{key}")
    for key in ("evidence", "changed_paths", "task_ids", "source_heads", "failed_evidence", "reviews"):
        if key in record:
            require_strings(record[key], f"{name}.{key}")
    for key in ("passed", "approved", "conditional", "human_required", "reviewer_escalation", "independent"):
        if key in record:
            require_boolean(record[key], f"{name}.{key}")
    if "status" in record:
        require_choice(record["status"], f"{name}.status", {"complete", "needs-fix", "blocked"})
    if "binding" in record:
        binding = require_object(record["binding"], f"{name}.binding", "head", "content_tree", "effective_contract_hash")
        for key in ("head", "content_tree"):
            require_string(binding[key], f"{name}.binding.{key}", GIT_OBJECT_RE)
        require_string(binding["effective_contract_hash"], f"{name}.binding.effective_contract_hash", CONTENT_HASH_RE)


def validate_delivery_summary(summary: Any) -> None:
    """Validate shape without altering stored bytes or inferring successful work."""
    require_object(summary, "delivery_summary", "schema_version", *SECTIONS)
    require_choice(summary["schema_version"], "delivery_summary.schema_version", {"1.0"})
    for section in SECTIONS:
        previous = 0
        for record in require_array(summary[section], f"delivery_summary.{section}"):
            name = f"delivery_summary.{section} receipt"
            _validate_receipt(record, name)
            if record["event_sequence"] <= previous:
                raise CogitoError(f"{name} must follow ledger order without duplicates")
            previous = record["event_sequence"]
            if section == "preparation":
                require_object(record, name, "stage", "stage_sequence", "commit_id", "base_commit", "branch", "files")
                require_choice(record["event"], name, {"stage-committed"})
                require_choice(record["stage"], name, {"shared-understanding", "boundary", "package"})
                require_integer(record["stage_sequence"], name, 1, 2**63 - 1)
                for path, digest in require_object(record["files"], f"{name}.files").items():
                    require_path(path, f"{name}.file")
                    require_string(digest, f"{name}.file hash", CONTENT_HASH_RE)
            elif section in {"implementation", "reviews"}:
                require_object(record, name, "task_id", "status", "base_commit", "evidence", "changed_paths")
                require_choice(record["event"], name, {"agent-result-recorded"})
                if section == "implementation":
                    require_object(record, name, "agent_id", "completion_mode")
                    require_choice(record["completion_mode"], name, {"commit", "working-tree"})
                    if record["completion_mode"] == "commit":
                        require_object(record, name, "head_commit")
                    elif "head_commit" in record:
                        raise CogitoError("working-tree implementation must not claim a commit")
                else:
                    require_object(record, name, "reviewer", "implementer", "head_commit")
                    if record["reviewer"] == record["implementer"]:
                        raise CogitoError("delivery_summary reviewer must be independent")
            elif section == "integration":
                require_choice(record["event"], name, INTEGRATION_EVENTS)
                require_object(record, name, "commit_id")
            elif section == "verification":
                require_choice(record["event"], name, VERIFICATION_EVENTS)
            elif section == "corrections":
                require_choice(record["event"], name, CORRECTION_EVENTS)
                require_object(record, name, "amendment_id", "completion_mode")
                require_choice(record["completion_mode"], name, {"commit", "working-tree"})
                if record["completion_mode"] == "working-tree":
                    require_object(record, name, "base_commit", "content_tree")
                    if "commit_id" in record:
                        raise CogitoError("working-tree correction must not claim a commit")
                else:
                    require_object(record, name, "commit_id")
            else:
                require_choice(record["event"], name, HUMAN_EVENTS)
                if "feedback" in record:
                    feedback = require_object(record["feedback"], name, "id", "item_ids")
                    require_string(feedback["id"], name)
                    require_strings(feedback["item_ids"], name, nonempty=True)
                    for key in ("acceptance_complete", "close_after_fixes"):
                        if key in feedback:
                            require_boolean(feedback[key], name)
                if "triage" in record:
                    require_object(record["triage"], name, "feedback_id", "route", "assessments")
                if "resolution" in record:
                    resolution = require_object(record["resolution"], name, "feedback_id", "resolved_item_ids", "summary")
                    require_strings(resolution["resolved_item_ids"], name, nonempty=True)
                    require_string(resolution["summary"], name)


def validate_delivery_summary_records(state: Mapping[str, Any], events: Sequence[Mapping[str, Any]], result: Mapping[str, Any]) -> None:
    """New stage-commit runs require an exact summary; legacy omission is valid."""
    if "delivery_summary" not in result:
        if state.get("stage_commits") is True:
            raise CogitoError("Result requires delivery_summary for a stage-commit run")
        return
    validate_delivery_summary(result["delivery_summary"])
    if result["delivery_summary"] != build_delivery_summary(state, events):
        raise CogitoError("Result delivery_summary does not match the recorded delivery history")
