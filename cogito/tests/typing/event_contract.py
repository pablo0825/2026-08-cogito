"""Static-only producer contracts; unused ignores detect weakened event types."""

from cogito_event_types import (
    AgentResultRecordedEvent, AgentResultRecordedPayload,
    CheckEvidenceRecordedEvent, CheckEvidenceRecordedPayload,
    IntegrationCompletedEvent, IntegrationCompletedPayload,
    TaskUpdatedEvent, TaskUpdatedPayload, TypedGateEvent,
)
from cogito_state_types import AgentResult


def valid_events(result: AgentResult) -> list[TypedGateEvent]:
    task: TaskUpdatedPayload = {"task_id": "T-1", "status": "running", "agent_id": "worker"}
    agent: AgentResultRecordedPayload = {"result": result}
    evidence: CheckEvidenceRecordedPayload = {
        "check_id": "C-1", "evidence_path": "evidence/C-1.json", "evidence_hash": "a" * 64,
    }
    integration: IntegrationCompletedPayload = {
        "commit_id": "a" * 40, "slice_id": "mini-package", "previous_delivery_head": "b" * 40,
        "task_ids": ["T-1"], "source_heads": ["c" * 40],
    }
    task_event: TaskUpdatedEvent = {"type": "task-updated", "payload": task}
    agent_event: AgentResultRecordedEvent = {"type": "agent-result-recorded", "payload": agent}
    evidence_event: CheckEvidenceRecordedEvent = {"type": "check-evidence-recorded", "payload": evidence}
    integration_event: IntegrationCompletedEvent = {"type": "integration-complete", "payload": integration}
    return [task_event, agent_event, evidence_event, integration_event]


def reject_missing_required_fields() -> None:
    task: TaskUpdatedPayload = {"task_id": "T-1", "status": "running"}  # type: ignore[typeddict-item]
    agent: AgentResultRecordedPayload = {}  # type: ignore[typeddict-item]
    evidence: CheckEvidenceRecordedPayload = {"check_id": "C-1", "evidence_path": "evidence/C-1.json"}  # type: ignore[typeddict-item]
    integration: IntegrationCompletedPayload = {"commit_id": "a" * 40, "slice_id": "mini-package", "task_ids": ["T-1"], "source_heads": []}  # type: ignore[typeddict-item]
    event: TaskUpdatedEvent = {"type": "task-updated"}  # type: ignore[typeddict-item]


def reject_bad_status_and_event_payload_pairings(payload: TaskUpdatedPayload) -> None:
    payload["status"] = "misspelled-status"  # type: ignore[typeddict-item]
    wrong_tag: TaskUpdatedEvent = {"type": "agent-result-recorded", "payload": payload}  # type: ignore[typeddict-item]
    wrong_payload: CheckEvidenceRecordedEvent = {"type": "check-evidence-recorded", "payload": payload}  # type: ignore[typeddict-item]
    wrong_union: TypedGateEvent = {"type": "agent-result-recorded", "payload": payload}  # type: ignore[misc, assignment]


def discriminated_task_status(event: TypedGateEvent) -> str:
    if event["type"] == "task-updated":
        return event["payload"]["status"]
    return "not-a-task-update"
