"""Internal state shapes; JSON boundaries remain validated at runtime."""

from __future__ import annotations

from typing import Any, Literal, TypedDict


RunKind = Literal["feature", "change", "correction", "maintenance", "documentation"]
TaskStatus = Literal["pending", "leased", "running", "blocked", "complete", "verified", "reviewed", "integrated"]
AgentRole = Literal["implementer", "reviewer", "integrator"]
AgentResultStatus = Literal["complete", "needs-fix", "blocked"]


class _OptionalTaskFields(TypedDict, total=False):
    slice_id: str | None
    paths: list[str]
    depends_on: list[str]
    responsibility: str
    check_ids: list[str]
    task_id: str
    agent_id: str
    worktree: str
    branch: str
    base_commit: str
    maintenance_start_tree: str
    maintenance_start_index_tree: str
    maintenance_end_tree: str
    maintenance_end_index_tree: str
    adoption: dict[str, Any]
    released_by: str


class TaskState(_OptionalTaskFields):
    id: str
    status: TaskStatus


class _OptionalAgentResultFields(TypedDict, total=False):
    reviewed_implementer: str
    repair_attempt: int


class AgentResult(_OptionalAgentResultFields):
    schema_version: Literal["3.0"]
    run_id: str
    task_id: str
    agent_id: str
    role: AgentRole
    status: AgentResultStatus
    base_commit: str
    head_commit: str
    changed_paths: list[str]
    evidence: list[str]
    risks: list[str]
    requested_transition: str


class _OptionalEvidenceLedgerFields(TypedDict, total=False):
    head_commit: str
    effective_contract_hash: str


class EvidenceLedgerEntry(_OptionalEvidenceLedgerFields):
    check_id: str
    evidence_path: str
    evidence_hash: str
    event_sequence: int | None


class _OptionalRunFields(TypedDict, total=False):
    result_metadata_corrections: list[dict[str, Any]]
    path_amendment: dict[str, Any]
    cleanup: dict[str, Any]  # Transient finalize response; never projected or persisted.
    task_delivery: Literal["atomic"]
    stage_commits: bool
    checkpoint_head: str
    checkpoint_branch: str
    pending_checkpoint: dict[str, Any] | None
    checkpoints: list[dict[str, Any]]
    shared_document: dict[str, Any]
    human: dict[str, Any]
    human_review_mandate: dict[str, Any]
    planning: dict[str, Any]
    carryover_worktrees: dict[str, dict[str, str]]
    amendments: list[dict[str, Any]]
    shared_understanding_revised: bool


class RunState(_OptionalRunFields):
    schema_version: Literal["3.0"]
    run_id: str
    kind: RunKind
    state: str
    sequence: int
    last_event_hash: str | None
    counters: dict[str, int]
    tasks: dict[str, TaskState]
    agent_results: list[AgentResult]
    evidence: dict[str, EvidenceLedgerEntry]
    package_path: str | None
    package_hash: str | None
    effective_contract_hash: str | None
    blocked_from: str | None
    max_workers: int
    candidate_package_hash: str | None
    project_graph_hash: str | None
    shared_understanding_hash: str | None
    boundary: dict[str, Any] | None
    limits: dict[str, int]
