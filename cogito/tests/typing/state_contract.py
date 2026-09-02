"""Static-only examples; unused ignores fail if a core type regresses to Any."""

from cogito_state_types import RunState, TaskState


def inspect_state(state: RunState) -> str:
    task: TaskState = state["tasks"]["T-1"]
    task["status"] = "pending"
    task["status"] = "misspelled-status"  # type: ignore[typeddict-item]
    state["taks"]  # type: ignore[typeddict-item]
    return task["id"]


def worker_task() -> TaskState:
    return {"id": "T-1", "status": "pending", "slice_id": None}
