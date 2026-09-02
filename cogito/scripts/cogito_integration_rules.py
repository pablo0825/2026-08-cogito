"""Pure Slice integration decisions from recorded tasks, results, and history."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

from cogito_common import CogitoError
from cogito_state_types import RunState
from cogito_task_rules import effective_slice_id


IntegrationEvent = Literal[
    "slice-integration-complete", "wave-integration-complete", "integration-complete",
]


@dataclass(frozen=True)
class IntegrationDecision:
    """Detached event fields and commit ancestry requirements for the caller."""

    event: IntegrationEvent
    task_ids: tuple[str, ...]
    source_heads: tuple[str, ...]
    previous_delivery_head: str


def derive_integration_decision(
    state: RunState, events: Sequence[Mapping[str, Any]], slice_id: str | None,
) -> IntegrationDecision:
    """Select an integration event without reading Git or changing input data.

    The caller validates the integrating phase and supplies chronological,
    validated history. Returned commit IDs still require Git ancestry checks.
    """
    target_slice = slice_id or "mini-package"
    task_ids = [
        task_id for task_id, task in state["tasks"].items()
        if effective_slice_id(task) == target_slice
    ]
    if not task_ids or any(state["tasks"][task_id].get("status") != "reviewed" for task_id in task_ids):
        raise CogitoError("integration requires every task in the target Slice to be independently reviewed")
    latest_implementation = {
        item.get("task_id"): item for item in state["agent_results"]
        if item.get("role") == "implementer" and item.get("status") == "complete"
    }
    source_heads = []
    for task_id in task_ids:
        result = latest_implementation.get(task_id)
        if not result:
            raise CogitoError("integration is missing a Gate-recorded implementation Result")
        source_heads.append(result["head_commit"])
    prior_integrations = [
        item for item in events if item["type"] in {
            "slice-integration-complete", "wave-integration-complete", "integration-complete",
        }
    ]
    starts = [item for item in events if item["type"] == "start-gate-passed"]
    previous_head = (
        prior_integrations[-1]["payload"]["commit_id"] if prior_integrations
        else starts[-1]["payload"]["delivery_head"]
    )
    remaining_reviewed = any(
        task_id not in task_ids and task.get("status") == "reviewed"
        for task_id, task in state["tasks"].items()
    )
    remaining_unintegrated = any(
        task_id not in task_ids and task.get("status") != "integrated"
        for task_id, task in state["tasks"].items()
    )
    event: IntegrationEvent
    if remaining_reviewed:
        event = "slice-integration-complete"
    elif remaining_unintegrated:
        event = "wave-integration-complete"
    else:
        event = "integration-complete"
    return IntegrationDecision(
        event=event, task_ids=tuple(sorted(task_ids)),
        source_heads=tuple(sorted(source_heads)), previous_delivery_head=previous_head,
    )
