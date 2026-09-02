"""Shapes emitted by Gate operations, without changing persisted JSON validation.

Legacy readers retain their existing optional/default/extension behavior. These
types document new internal events; they do not coerce or validate old records.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from cogito_state_types import AgentResult, TaskStatus


IntegrationEvent = Literal[
    "slice-integration-complete", "wave-integration-complete", "integration-complete",
]


class _OptionalTaskUpdatedFields(TypedDict, total=False):
    worktree: str
    branch: str
    base_commit: str
    maintenance_start_tree: str
    maintenance_start_index_tree: str


class TaskUpdatedPayload(_OptionalTaskUpdatedFields):
    task_id: str
    status: TaskStatus
    agent_id: str


class _OptionalAgentResultRecordedFields(TypedDict, total=False):
    maintenance_end_tree: str
    maintenance_end_index_tree: str


class AgentResultRecordedPayload(_OptionalAgentResultRecordedFields):
    result: AgentResult


class _OptionalCheckEvidenceRecordedFields(TypedDict, total=False):
    head_commit: str
    effective_contract_hash: str


class CheckEvidenceRecordedPayload(_OptionalCheckEvidenceRecordedFields):
    check_id: str
    evidence_path: str
    evidence_hash: str


class IntegrationCompletedPayload(TypedDict):
    commit_id: str
    slice_id: str
    previous_delivery_head: str
    task_ids: list[str]
    source_heads: list[str]


class _OptionalEventMetadata(TypedDict, total=False):
    sequence: int
    event_hash: str
    previous_event_hash: str
    action_id: str | None
    request_hash: str | None
    timestamp: str | None


class TaskUpdatedEvent(_OptionalEventMetadata):
    type: Literal["task-updated"]
    payload: TaskUpdatedPayload


class AgentResultRecordedEvent(_OptionalEventMetadata):
    type: Literal["agent-result-recorded"]
    payload: AgentResultRecordedPayload


class CheckEvidenceRecordedEvent(_OptionalEventMetadata):
    type: Literal["check-evidence-recorded"]
    payload: CheckEvidenceRecordedPayload


class IntegrationCompletedEvent(_OptionalEventMetadata):
    type: IntegrationEvent
    payload: IntegrationCompletedPayload


TypedGateEvent = (
    TaskUpdatedEvent | AgentResultRecordedEvent | CheckEvidenceRecordedEvent
    | IntegrationCompletedEvent
)
