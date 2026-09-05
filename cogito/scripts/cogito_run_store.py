#!/usr/bin/env python3
"""Gate transaction coordinator for a Cogito run."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, cast

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cogito_checkpoints import CheckpointMixin, guard_checkpoint
from cogito_disposition_run import DispositionRunMixin
from cogito_human import HumanMixin
from cogito_human_projection import HUMAN_EVENTS
from cogito_state_types import AgentResult, RunState, TaskStatus
from cogito_replan_lock import run_mutation, project_lock, check_run_fence
from cogito_planning import (
    PlanningMixin, PLANNING_EVENTS, capture_candidate, assert_files,
    document_snapshot, guard_preparation, validate_revision_candidate,
)
from cogito_event_types import (
    AgentResultRecordedEvent, AgentResultRecordedPayload,
    CheckEvidenceRecordedEvent, CheckEvidenceRecordedPayload,
    IntegrationCompletedEvent, IntegrationCompletedPayload,
    TaskUpdatedEvent, TaskUpdatedPayload, TypedGateEvent,
)
from cogito_common import CogitoError, atomic_create_json, hash_json, load_json
from cogito_approval import ApprovalArtifacts, publish_approval, restore_approval_permissions
from cogito_actions import controlled_check_attempt, request_fingerprint, require_same_request
from cogito_contracts import (
    materialize_contract_with_limits, package_hash,
    path_allowed as _path_allowed,
    safe_repo_path as _safe_repo_path, validate_agent_result,
    validate_package_with_limits, validate_preparation_event, validate_shared_understanding_hash,
)
from cogito_correction_rules import validate_correction_completion, validate_review_fix_completion
from cogito_delivery_scope import validate_committed_scope
from cogito_delivery_summary import build_delivery_summary
from cogito_event_repository import EventRepository, EventSnapshot
from cogito_evidence_contract import validate_check_evidence
from cogito_evidence_binding import capture_index_and_worktree_trees, working_tree_changed_paths
from cogito_finalization import validate_finalization
from cogito_git import GitRepository
from cogito_integration_rules import derive_integration_decision
from cogito_gate_validation import (
    validate_evidence as validate_gate_evidence,
    validate_policy as validate_gate_policy,
    derive_review_decision,
    verification_checks,
)
from cogito_project_graph import formalize_project_graph, validate_project_graph
from cogito_ports import EventRepositoryPort, GitRepositoryPort
from cogito_run_queries import build_completion_report, derive_next_action
from cogito_scheduler import ready_tasks, tasks_with_dependencies
from cogito_task_rules import effective_slice_id, is_active_task
from cogito_workflow import load_workflow, validate_transition

_load_json = load_json


class RunStore(CheckpointMixin, PlanningMixin, HumanMixin, DispositionRunMixin):
    _GATE_AUTHORITY = object()
    _PROTECTED_RECORD_EVENTS = {
        *PLANNING_EVENTS, *HUMAN_EVENTS, "human-review-mandated", "stage-committed", "disposition-resumed",
        "run-superseded", "work-carried", "work-adopted", "adoption-ready",
        "package-ready", "mini-package-ready", "package-approved", "technical-amendment-added",
        "task-updated", "agent-result-recorded", "check-evidence-recorded", "start-gate-passed",
        "verification-passed", "verification-correction-required",
        "post-verification-correction-required", "technical-correction-complete",
        "post-integration-correction-complete", "review-fix-required", "review-fix-complete",
        "slice-integration-complete", "wave-integration-complete", "integration-complete",
        "human-review-required", "auto-accept-ready", "human-approved",
        "finalization-complete", "resume", "transient-retry", "format-repair-recorded",
    }
    _PROTECTED_TRANSITION_EVENTS = _PROTECTED_RECORD_EVENTS - {
        "technical-amendment-added", "task-updated", "agent-result-recorded",
        "check-evidence-recorded",
    }

    def __init__(
        self, root: str | Path, run_id: str, workflow: Mapping[str, Any] | None = None,
        *, event_repository: EventRepositoryPort | None = None,
        git_repository: GitRepositoryPort | None = None,
    ):
        if not re.fullmatch(r"(?:DEV|MNT)-[A-Za-z0-9._-]+", run_id):
            raise CogitoError("run_id must use a safe DEV-* or MNT-* identifier")
        self.root = Path(root).resolve()
        self._git_repo: GitRepositoryPort = (
            git_repository if git_repository is not None else GitRepository(self.root)
        )
        self.run_id = run_id
        self.run_dir = self.root / ".cogito" / "runs" / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.state_path = self.run_dir / "state.json"
        self.workflow = dict(workflow or load_workflow())
        self._events: EventRepositoryPort = (
            event_repository if event_repository is not None
            else EventRepository(self.events_path, self.state_path, self.workflow)
        )

    @run_mutation
    def create(self, kind: str, *, stage_commits: bool = False, task_delivery: str | None = None) -> RunState:
        if self._events.exists():
            raise CogitoError(f"run already exists: {self.run_id}")
        payload: dict[str, Any] = {"run_id": self.run_id, "kind": kind}
        if task_delivery is not None:
            if task_delivery != "atomic" or kind not in {"feature", "change", "correction"}:
                raise CogitoError("atomic task delivery requires a Development Package")
            payload["task_delivery"] = task_delivery
        if stage_commits:
            from cogito_checkpoints import is_frozen_successor
            if is_frozen_successor(self.root, self.run_id):
                raise CogitoError("RP successors require frozen-delivery initialization; omit --stage-commits")
            payload.update(stage_commits=True, checkpoint_head=self._git("rev-parse", "HEAD"),
                           checkpoint_branch=self._git("branch", "--show-current"))
            if not payload["checkpoint_branch"]:
                raise CogitoError("stage commits require a named delivery branch")
        self.run_dir.mkdir(parents=True, exist_ok=False)
        return self._events.create({"type": "run-created", "payload": payload, "action_id": f"create:{self.run_id}"})

    def load(self) -> RunState:
        """Validate authoritative state and repair its disposable cache if needed."""
        projection = self._events.project()
        relative_package_path = projection.get("package_path")
        if relative_package_path:
            package_path = self.root / relative_package_path
            package = _load_json(package_path)
            validate_package_with_limits(package, self.workflow["limits"])
            if package_hash(package) != projection["package_hash"]:
                raise CogitoError("approved Package content no longer matches its frozen hash")
        self._events.refresh_cache(projection)
        return projection

    def _validate_preparation_input(self, event: str, payload: Mapping[str, Any]) -> None:
        validate_preparation_event(event, payload)
        guard_preparation(self._events.project(), event, payload)
        if event == "shared-understanding-confirmed":
            # An old run may contain a malformed, unconfirmed summary. Keep it
            # readable and revisable, but never freeze it via a new confirmation.
            validate_shared_understanding_hash(self._events.project().get("shared_understanding_hash"))

    def _planning_preparation_payload(self, event, payload):
        current = self._events.project()
        planning = current.get("planning")
        if not (current.get("stage_commits") or (planning and planning.get("revision"))) or event not in {
            "shared-understanding-ready", "shared-understanding-confirmed", "boundary-complete",
        }:
            return payload
        self._planning_environment(current, documents=event == "boundary-complete")
        payload = dict(payload)
        if event == "shared-understanding-ready":
            document = payload.get("document")
            if current.get("stage_commits"):
                self._checkpoint_document_path(document)
            saved = document_snapshot(self.root, document)
            if saved["hash"] != payload.get("shared_understanding_hash"):
                raise CogitoError("Shared Understanding document does not match its confirmation hash")
            if "document_snapshot" in payload and payload["document_snapshot"] != saved:
                raise CogitoError("Shared Understanding changed during preparation")
            payload["document_snapshot"] = saved
        elif event == "shared-understanding-confirmed":
            document = current.get("shared_document") if current.get("stage_commits") else (planning or {}).get("shared_document")
            if not document:
                raise CogitoError("prepare the current Shared Understanding document first")
            document_snapshot(self.root, document)
        return payload

    @run_mutation
    def record(self, event_type: str, payload: Mapping[str, Any], action_id: str | None = None, _authority: object | None = None, *, request_hash: str | None = None, expected_previous_hash: str | None = None) -> RunState:
        if event_type == "cancel":
            from cogito_disposition_lock import current_authority
            if current_authority() is None:
                raise CogitoError("cancel requires the dedicated disposition Gate")
        if event_type in self._PROTECTED_RECORD_EVENTS and _authority is not self._GATE_AUTHORITY:
            raise CogitoError(f"{event_type} requires its dedicated Gate operation")
        request_hash = request_hash or request_fingerprint("record", event=event_type, payload=payload)
        replay = self._replay(action_id, event_type, request_hash)
        if replay is not None:
            return replay
        if expected_previous_hash is not None and self._events.project().get("last_event_hash", expected_previous_hash) != expected_previous_hash:
            raise CogitoError("event history changed during validation; retry with the same action_id")
        current = self._events.project()
        guard_checkpoint(current, event_type)
        if event_type in {"shared-understanding-ready", "shared-understanding-confirmed", "boundary-complete", "package-ready", "mini-package-ready", "package-approved"}:
            self._checkpoint_baseline(current)
        if event_type == "package-approved":
            self._planning_approval_binding(self._events.project())
        payload = self._planning_preparation_payload(event_type, payload)
        self._validate_preparation_input(event_type, payload)
        return self._events.append({
            "type": event_type, "payload": dict(payload),
            "action_id": action_id, "request_hash": request_hash,
        }, expected_previous_hash=expected_previous_hash)

    def _record_gate_event(
        self, event: TypedGateEvent, action_id: str | None, *, request_hash: str,
    ) -> RunState:
        """Keep a typed event's discriminator and payload paired until persistence."""
        return self.record(
            event["type"], event["payload"], action_id, self._GATE_AUTHORITY,
            request_hash=request_hash,
        )

    @run_mutation
    def transition(self, event: str, payload: Mapping[str, Any], action_id: str | None = None) -> RunState:
        from cogito_disposition_lock import current_authority
        if event == "cancel" and current_authority() is None:
            if payload.get("authorized") is not True:
                raise CogitoError("cancellation requires explicit user authorization")
            from cogito_disposition_store import DispositionStore
            key = hash_json({"run": self.run_id, "action_id": action_id})[:20]
            disposition = DispositionStore(self.root, "DP-cancel-" + key)
            disposition.begin(self.run_id, payload.get("reason", "User authorized cancellation"), "cancel-begin:" + key)
            disposition.stop("cancel-stop:" + key)
            return self.load()
        request_hash = request_fingerprint("transition", event=event, payload=payload)
        replay = self._replay(action_id, event, request_hash)
        if replay is not None:
            return replay
        payload = self._planning_preparation_payload(event, payload)
        self._validate_preparation_input(event, payload)
        current = self.load()
        if event in self._PROTECTED_TRANSITION_EVENTS:
            raise CogitoError(f"{event} requires its dedicated Gate operation")
        payload = dict(payload)
        if event == "cancel":
            payload["disposition_id"] = current_authority()
        if event == "implementation-complete":
            completed = {task_id for task_id, item in current["tasks"].items() if item.get("status") == "complete"}
            implemented = {item.get("task_id") for item in current["agent_results"] if item.get("role") == "implementer" and item.get("status") == "complete" and item.get("requested_transition") == "verifying"}
            active = any(is_active_task(item) for item in current["tasks"].values())
            edges = [{"from": dependency, "to": task["id"]} for task in current["tasks"].values() for dependency in task.get("depends_on", [])]
            dispatchable = ready_tasks(list(current["tasks"].values()), edges, current["max_workers"])
            payload["tasks_complete"] = bool(completed) and not active and not dispatchable and completed <= implemented
            payload["task_ids"] = sorted(completed)
        if event == "review-approved":
            review_state = current
            if payload.get("review_exemption") is not True:
                events = self._events.read()
                cycle = max((item["sequence"] for item in events
                             if item["type"] == "verification-passed"), default=0)
                review_state = cast(RunState, {**current, "agent_results": [
                    item["payload"]["result"] for item in events
                    if item["type"] == "agent-result-recorded" and item["sequence"] > cycle
                ]})
            decision = derive_review_decision(
                self.approved_package(), review_state,
                review_exemption=payload.get("review_exemption") is True,
            )
            if payload.get("review_exemption") is not True:
                worktrees = {Path(current["tasks"][task_id]["worktree"]) for task_id in decision["reviews"]}
                for worktree in worktrees:
                    _, content_tree = capture_index_and_worktree_trees(worktree)
                    self._validate_review_content(worktree, content_tree)
            payload = {**payload, **decision}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(
            event, payload, action_id, request_hash=request_hash,
            expected_previous_hash=current["last_event_hash"],
        )

    def approved_package(self) -> dict[str, Any]:
        return self._approved_package_from_state(self.load())

    def _approved_package_from_state(self, state: RunState) -> dict[str, Any]:
        """Read and validate the frozen Package referenced by a captured state."""
        package_path = state.get("package_path")
        if not package_path:
            raise CogitoError("run has no approved Package")
        package = _load_json(self.root / package_path)
        validate_package_with_limits(package, self.workflow["limits"])
        if package_hash(package) != state["package_hash"]:
            raise CogitoError("approved Package hash mismatch")
        return package

    @run_mutation
    def prepare_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("prepare-package", draft=draft)
        replay = self._replay(action_id, {"mini-package-ready", "package-ready"}, request_hash)
        if replay is not None:
            return replay
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package_with_limits(package, self.workflow["limits"])
        self._validate_policy(package)
        current = self.load()
        guard_checkpoint(current, "package-ready")
        if package["kind"] != current["kind"]:
            raise CogitoError("Package kind must match the run kind")
        if current.get("task_delivery") == "atomic" and package.get("task_delivery") != "atomic":
            raise CogitoError("new Development Packages require task_delivery: atomic")
        if current.get("candidate_package_hash") and current["candidate_package_hash"] != package_hash(package):
            raise CogitoError("a different candidate requires a new planning round")
        self._planning_environment(current)
        validate_revision_candidate(current, package)
        mini = package["kind"] in {"maintenance", "documentation"}
        if not mini and package["shared_understanding"]["hash"] != current.get("shared_understanding_hash"):
            raise CogitoError("Package is not bound to the confirmed Shared Understanding")
        if not mini and package["boundary"] != current.get("boundary"):
            raise CogitoError("Package is not bound to the recorded Boundary Gate result")
        event = "mini-package-ready" if mini else "package-ready"
        expected_state = "preparing" if mini else "package-preparing"
        planning = current.get("planning")
        if planning and planning.get("shared_document") and package["shared_understanding"] != planning["shared_document"]:
            raise CogitoError("Package must use the confirmed planning document")
        if current.get("stage_commits"):
            if package["delivery_branch"] != current["checkpoint_branch"]:
                raise CogitoError("Package must use the stage checkpoint branch")
            if not mini and package["shared_understanding"] != current.get("shared_document"):
                raise CogitoError("Package must reference the committed Shared Understanding document")
        snapshot = capture_candidate(self.root, package, planning["round"] if planning else 1,
                                     strict=bool(current.get("stage_commits") or (planning and planning["revision"])))
        payload = {"package_valid": True, "candidate_package_hash": package_hash(package),
                   "candidate_snapshot": snapshot}
        if current["state"] not in {expected_state, "awaiting-package-approval"}:
            raise CogitoError("Package preparation is not legal in the current state")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(
            event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash,
            expected_previous_hash=current["last_event_hash"],
        )

    @run_mutation
    def update_task(self, task_id: str, status: TaskStatus, agent_id: str, action_id: str | None = None) -> RunState:
        payload: TaskUpdatedPayload = {"task_id": task_id, "status": status, "agent_id": agent_id}
        request_hash = request_fingerprint("task", **payload)
        replay = self._replay(action_id, "task-updated", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] not in {"executing", "technical-correction", "review-fix", "post-integration-correction", "human-correction"}:
            raise CogitoError("task updates are not legal in the current state")
        task = current["tasks"].get(task_id)
        if not task:
            raise CogitoError("task is outside the effective Package")
        if current["state"] == "human-correction" and task_id not in current["human"]["task_ids"]:
            raise CogitoError("human correction may dispatch only its current amendment tasks")
        package = self.approved_package()
        if status == "complete" and package.get("task_delivery") == "atomic":
            results = [item for item in current["agent_results"]
                       if item["task_id"] == task_id and item["role"] == "implementer"]
            if not results or results[-1]["status"] != "complete":
                raise CogitoError("atomic task completion requires an Implementer Result")
            self._validate_atomic_result(results[-1], task, self._events.snapshot())
        if status == "leased":
            if current['state'] == 'human-correction' and any(is_active_task(t) for t in current['tasks'].values()):
                raise CogitoError('human correction uses one serial delivery checkout lease')
            package = self.approved_package()
            if current["state"] in {"post-integration-correction", "human-correction"}:
                worktree, branch = self.root, package["delivery_branch"]
            else:
                worktree, branch = self._task_worktree(task, package)
            base_commit = self._git_at(worktree, "rev-parse", "HEAD")
            if package.get("task_delivery") == "atomic":
                if any(is_active_task(item) and Path(str(item.get("worktree", ""))).resolve() == worktree.resolve()
                       for item in current["tasks"].values()):
                    raise CogitoError("atomic tasks require one active lease per checkout")
                self._require_atomic_clean(worktree, base_commit, current)
            task_slice = effective_slice_id(task)
            prior_heads = [
                item["head_commit"] for item in current["agent_results"]
                if item.get("role") == "implementer"
                and effective_slice_id(current["tasks"].get(item.get("task_id"), {})) == task_slice
            ]
            expected_base = prior_heads[-1] if prior_heads and current["state"] not in {"post-integration-correction", "human-correction"} else self._git("rev-parse", "HEAD")
            if base_commit != expected_base:
                carried = current.get('carryover_worktrees', {}).get(str(worktree))
                index, tree = capture_index_and_worktree_trees(worktree)
                if (prior_heads or not carried or carried != {'head': base_commit, 'index_tree': index, 'content_tree': tree}
                        or current['state'] != 'executing'):
                    raise CogitoError("a Slice worktree must start from the latest delivery HEAD")
                self._git('merge-base', '--is-ancestor', package['baseline_commit'], expected_base)
            payload.update({"worktree": str(worktree), "branch": branch, "base_commit": base_commit})
            if package["kind"] == "maintenance":
                index_tree, content_tree = capture_index_and_worktree_trees(worktree)
                retained_tree = task.get("maintenance_start_tree")
                retained_index = task.get("maintenance_start_index_tree")
                if bool(retained_tree) != bool(retained_index):
                    raise CogitoError("Maintenance task has incomplete lease snapshots")
                if retained_tree and retained_index:
                    controls = {current.get("package_path"), "docs/cogito/project-graph.json"}
                    for before, after in ((retained_tree, content_tree), (retained_index, index_tree)):
                        changes = self._git_at(worktree, "diff", "--name-only", "--no-renames",
                                               "--no-ext-diff", "-z", before, after, "--")
                        if any(path not in controls and not path.startswith(".cogito/")
                               and not _path_allowed(path, task.get("paths", []))
                               for path in filter(None, changes.split("\0"))):
                            raise CogitoError("Maintenance handoff exceeds its task path responsibility")
                elif current["state"] == "executing":
                    completed = [item for item in current["agent_results"]
                                 if item["role"] == "implementer" and item["status"] == "complete"]
                    predecessor: Mapping[str, Any] = current["tasks"].get(completed[-1]["task_id"], {}) if completed else {}
                    expected_tree = predecessor.get("maintenance_end_tree", base_commit)
                    expected_index = predecessor.get("maintenance_end_index_tree", base_commit)
                    controls = {current.get("package_path"), "docs/cogito/project-graph.json"}
                    for before, after in ((expected_tree, content_tree), (expected_index, index_tree)):
                        changes = self._git_at(worktree, "diff", "--name-only", "--no-renames",
                                               "--no-ext-diff", "-z", before, after, "--")
                        if any(path not in controls and not path.startswith(".cogito/")
                               for path in filter(None, changes.split("\0"))):
                            raise CogitoError("Maintenance work changed outside a recorded task before lease")
                payload.update({"maintenance_start_tree": retained_tree or content_tree,
                                "maintenance_start_index_tree": retained_index or index_tree})
        return self._record_gate_event(
            TaskUpdatedEvent(type="task-updated", payload=payload), action_id,
            request_hash=request_hash,
        )

    @run_mutation
    def submit_agent_result(self, result: Mapping[str, Any], action_id: str | None = None) -> RunState:
        # This is the JSON boundary; validate_agent_result below checks its shape
        # before a new event can be recorded. Exact replays keep the early return.
        payload: AgentResultRecordedPayload = {"result": cast(AgentResult, dict(result))}
        request_hash = request_fingerprint("agent-result", result=result)
        replay = self._replay(action_id, "agent-result-recorded", request_hash)
        if replay is not None:
            return replay
        package = self.approved_package()
        validate_agent_result(result, package, workflow_limits=self.workflow["limits"])
        state = self.load()
        allowed_states = {
            "implementer": {"executing", "technical-correction", "review-fix", "post-integration-correction", "human-correction"},
            "reviewer": {"reviewing", "human-correction-reviewing"}, "integrator": {"integrating"},
        }
        if state["state"] not in allowed_states[result["role"]]:
            raise CogitoError(f"{result['role']} Result is not legal in state {state['state']}")
        task = state["tasks"].get(result["task_id"])
        if not task:
            raise CogitoError("Agent Result references a task outside the effective Package")
        if state['state'] in {'human-correction', 'human-correction-reviewing'}:
            key = 'task_ids' if result['role'] == 'implementer' else 'cohort_task_ids'
            if result['task_id'] not in state['human'][key]:
                raise CogitoError('Agent Result is outside the current human correction cohort')
        if result["role"] != "reviewer" and task.get("agent_id") != result["agent_id"]:
            raise CogitoError("Agent Result identity does not own the task lease")
        if result["role"] == "reviewer" and result.get("reviewed_implementer") != task.get("agent_id"):
            raise CogitoError("Reviewer Result is not bound to the task implementer")
        worktree = Path(str(task.get("worktree", "")))
        if not worktree.is_dir() or result["base_commit"] != task.get("base_commit"):
            raise CogitoError("Agent Result commits are not bound to the leased worktree")
        current_head = self._git_at(worktree, "rev-parse", "HEAD")
        if result["role"] == "reviewer" and package["kind"] != "maintenance":
            implemented = [item for item in state["agent_results"]
                           if item["task_id"] == result["task_id"] and item["role"] == "implementer"
                           and item["status"] == "complete"]
            if (not implemented or result["base_commit"] != implemented[-1]["base_commit"]
                    or result["head_commit"] != implemented[-1]["head_commit"]):
                raise CogitoError("Reviewer Result must name the recorded task implementation range")
            self._git_at(worktree, "merge-base", "--is-ancestor", result["head_commit"], current_head)
            _, content_tree = capture_index_and_worktree_trees(worktree)
            self._validate_review_content(worktree, content_tree)
        elif result["head_commit"] != current_head:
            raise CogitoError("Agent Result commits are not bound to the leased worktree")
        if self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
            raise CogitoError("Agent Result worktree is not on its leased branch")
        self._git("cat-file", "-e", f"{result['base_commit']}^{{commit}}")
        self._git("cat-file", "-e", f"{result['head_commit']}^{{commit}}")
        self._git("merge-base", "--is-ancestor", result["base_commit"], result["head_commit"])
        diff_options = ("--no-optional-locks", "diff", "--name-only", "--no-renames", "--no-ext-diff", "--ignore-submodules=none", "-z")
        actual_paths = set(filter(None, self._git_at(
            worktree, *diff_options, result["base_commit"], result["head_commit"], "--",
        ).split("\0")))
        if package["kind"] == "maintenance":
            index_tree, content_tree = capture_index_and_worktree_trees(worktree)
            control_paths = {state.get("package_path"), "docs/cogito/project-graph.json"}

            def changed_paths(base: str, head: str) -> set[str]:
                paths = self._git_at(worktree, *diff_options, base, head, "--")
                return {path for path in filter(None, paths.split("\0"))
                        if path not in control_paths and not path.startswith(".cogito/")}

            cumulative = (changed_paths(result["base_commit"], content_tree)
                          | changed_paths(result["base_commit"], index_tree))
            live_paths = working_tree_changed_paths(worktree, result["base_commit"])
            live_paths = {path for path in live_paths if path not in control_paths and not path.startswith(".cogito/")}
            # A dirty submodule can differ without a representable tree delta.
            # Do not silently drop a path detected by Git's live comparison.
            if live_paths - cumulative:
                raise CogitoError("Maintenance changes cannot be represented by task snapshots")
            if any(not _path_allowed(path, package["approved_paths"]) for path in cumulative):
                raise CogitoError("Maintenance working tree exceeds approved paths")
            start_tree = task.get("maintenance_start_tree")
            start_index = task.get("maintenance_start_index_tree")
            if bool(start_tree) != bool(start_index):
                raise CogitoError("Maintenance task has incomplete lease snapshots")
            if not start_tree or not start_index:
                # Old events remain usable under their original, conservative
                # whole-worktree responsibility check. Never fabricate a lease.
                actual_paths = cumulative
            elif result["role"] == "reviewer":
                end_tree = task.get("maintenance_end_tree")
                end_index = task.get("maintenance_end_index_tree")
                if not end_tree or not end_index:
                    raise CogitoError("Maintenance review lacks recorded implementation snapshots")
                self._validate_review_content(worktree, content_tree)
                actual_paths = changed_paths(start_tree, end_tree) | changed_paths(start_index, end_index)
            else:
                end_tree, end_index = content_tree, index_tree
                payload.update({"maintenance_end_tree": end_tree,
                                "maintenance_end_index_tree": end_index})
                actual_paths = changed_paths(start_tree, end_tree) | changed_paths(start_index, end_index)
        if result["role"] != "reviewer" and set(result["changed_paths"]) != actual_paths:
            raise CogitoError("Agent Result changed_paths do not match its commit range")
        if any(not _path_allowed(path, task.get("paths", [])) for path in actual_paths):
            raise CogitoError("Agent Result exceeds its task path responsibility")
        if package.get("task_delivery") == "atomic" and result["role"] == "implementer":
            if task.get("status") != "running":
                raise CogitoError("atomic Implementer Result requires a running task")
            if result["status"] == "complete":
                self._validate_atomic_result(result, task, self._events.snapshot())
        return self._record_gate_event(
            AgentResultRecordedEvent(type="agent-result-recorded", payload=payload), action_id,
            request_hash=request_hash,
        )

    def _require_atomic_clean(self, worktree: Path, head: str, state: RunState) -> str:
        index, tree = capture_index_and_worktree_trees(worktree)
        controls = {state.get("package_path"), "docs/cogito/project-graph.json"}
        changes = working_tree_changed_paths(worktree, head)
        for value in (index, tree):
            changes.update(filter(None, self._git_at(
                worktree, "diff", "--name-only", "--no-renames", "--no-ext-diff", "-z", head, value, "--",
            ).split("\0")))
        if any(path not in controls and not path.startswith(".cogito/") for path in changes):
            raise CogitoError("atomic task has uncommitted product content")
        return tree

    def _validate_atomic_result(
        self, result: Mapping[str, Any], task: Mapping[str, Any], snapshot: EventSnapshot,
    ) -> None:
        worktree = Path(task["worktree"])
        base, head = result["base_commit"], result["head_commit"]
        if (base != task["base_commit"] or self._git_at(worktree, "rev-parse", "HEAD") != head
                or self._git_at(worktree, "branch", "--show-current") != task["branch"]):
            raise CogitoError("atomic Result no longer matches its task checkout")
        parents = self._git_at(worktree, "rev-list", "--parents", "-n", "1", head).split()[1:]
        if parents != [base] or not result["changed_paths"]:
            raise CogitoError("atomic task requires exactly one nonempty commit from its leased base")
        tree = self._require_atomic_clean(worktree, head, snapshot.state)
        evidence = [_load_json(Path(path)) for path in result["evidence"]]
        self._validate_evidence(self.approved_package(), evidence, snapshot=snapshot,
                                phase="task", task_id=result["task_id"])
        for item in evidence:
            if (item["head_commit"] not in {base, head}
                    or item["worktree_binding"].get("content_tree") != tree):
                raise CogitoError("targeted evidence does not match the task commit content")

    def _validate_review_content(self, worktree: Path, content_tree: str) -> None:
        """A task review must refer to the current wave's verified content."""
        snapshot = self._events.snapshot()
        verified = [event for event in snapshot.events if event["type"] in {"verification-passed", "human-correction-verified"}]
        if not verified:
            raise CogitoError("review requires recorded verification")
        paths = verified[-1]["payload"]["evidence"]
        evidence = [_load_json(Path(path)) for path in paths]
        head = self._git_at(worktree, "rev-parse", "HEAD")
        matching = [item for item in evidence if item["head_commit"] == head]
        if not matching or any(item["worktree_binding"].get("content_tree") != content_tree for item in matching):
            raise CogitoError("review worktree differs from verified content; rerun verification")
        amendments = [event["payload"]["amendment"] for event in snapshot.events
                      if event["type"] == "technical-amendment-added"]
        effective = materialize_contract_with_limits(self.approved_package(), amendments, self.workflow["limits"])
        checks = {check["id"]: check for check in effective["checks"]}
        anchor = max((event["sequence"] for event in snapshot.events
                      if event["type"] in {"implementation-complete", "technical-correction-complete", "review-fix-complete", "human-correction-complete"}), default=0)
        for item in matching:
            entry = snapshot.state["evidence"].get(item["evidence_path"])
            check = checks.get(item["check_id"])
            if (not entry or not check or entry["evidence_hash"] != hash_json(item)
                    or not anchor < (entry.get("event_sequence") or 0) < verified[-1]["sequence"]
                    or item.get("passed") is not True or item["check_hash"] != hash_json(check)
                    or item["effective_contract_hash"] != effective["effective_contract_hash"]):
                raise CogitoError("review evidence is not bound to this verification cycle")
        self._validate_evidence(self.approved_package(), matching, snapshot=snapshot,
                                phase="post-integration" if verified[-1]["type"] == "human-correction-verified" else "implementation",
                                current_head=head if verified[-1]["type"] == "human-correction-verified" else None)

    @run_mutation
    def complete_verification(self, evidence: Sequence[Mapping[str, Any]], action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("verify", evidence=evidence)
        replay = self._replay(action_id, "verification-passed", request_hash)
        if replay is not None:
            return replay
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current["state"] != "verifying":
            raise CogitoError("verification closure is not legal in the current state")
        package = self._approved_package_from_state(current)
        self._events.refresh_cache(current)
        self._validate_evidence(package, evidence, snapshot=snapshot, phase="implementation")
        payload = {"passed": True, "evidence": [item["evidence_path"] for item in evidence]}
        validate_transition(self.workflow, current["state"], "verification-passed", payload, current["counters"])
        return self.record(
            "verification-passed", payload, action_id, self._GATE_AUTHORITY,
            request_hash=request_hash, expected_previous_hash=current["last_event_hash"],
        )

    def run_controlled_check(self, check_id: str, worktree: str | Path, action_id: str) -> RunState:
        if not action_id:
            raise CogitoError("controlled check requires a stable action_id")
        with project_lock(self.root):
            from cogito_disposition_lock import check_disposition_fence
            check_disposition_fence(self, "run_controlled_check")
            check_run_fence(self.root, self.run_id, "run_controlled_check")
        supplied_worktree = Path(worktree).resolve()
        request_hash = request_fingerprint("run-check", check_id=check_id, worktree=str(supplied_worktree))
        replay = self._replay(action_id, "check-evidence-recorded", request_hash)
        if replay is not None:
            return replay
        if not self._events.is_initialized():
            raise CogitoError("run must be initialized before controlled checks")
        with controlled_check_attempt(self.run_dir, action_id, request_hash) as started_path:
            # Another caller may have completed the action while we waited.
            replay = self._replay(action_id, "check-evidence-recorded", request_hash)
            if replay is not None:
                return replay
            return self._capture_controlled_check(check_id, supplied_worktree, action_id, request_hash, started_path)

    def _capture_controlled_check(
        self, check_id: str, supplied_worktree: Path, action_id: str,
        request_hash: str, started_path: Path,
    ) -> RunState:
        package = self.approved_package()
        state = self.load()
        if state["state"] in {"post-integration-verification", "human-correction-verifying"}:
            if supplied_worktree != self.root:
                raise CogitoError("post-integration checks must run in the delivery checkout")
        elif state["state"] == "verifying":
            eligible = {Path(str(task.get("worktree", ""))).resolve() for task in state["tasks"].values() if task.get("status") == "complete"}
            if supplied_worktree not in eligible:
                raise CogitoError("verification checks must run in a completed Package Slice worktree")
        elif package.get("task_delivery") == "atomic" and state["state"] in {
            "executing", "technical-correction", "review-fix", "post-integration-correction", "human-correction",
        }:
            active = [task for task in state["tasks"].values()
                      if task.get("status") == "running"
                      and Path(str(task.get("worktree", ""))).resolve() == supplied_worktree
                      and check_id in task.get("check_ids", [])]
            if len(active) != 1:
                raise CogitoError("task checks require the running task's checkout and targeted check ID")
        else:
            raise CogitoError("controlled checks are not legal in the current state")
        prior = [item["payload"]["amendment"] for item in self._events.read() if item["type"] == "technical-amendment-added"]
        effective = materialize_contract_with_limits(package, prior, self.workflow["limits"])
        checks = [check for check in effective["checks"] if check["id"] == check_id]
        if len(checks) != 1:
            raise CogitoError(f"expected exactly one check named {check_id!r}")
        execution = {"request_hash": request_hash, "check_hash": hash_json(checks[0]), "effective_contract_hash": effective["effective_contract_hash"]}
        try:
            from cogito_runner import EvidenceAlreadyExists, run_check, write_evidence_once
        except ImportError as exc:  # pragma: no cover - installation failure
            raise CogitoError(f"controlled runner is unavailable: {exc}") from exc
        record_id = f"{check_id}-{hash_json({'action_id': action_id})[:16]}"
        path = self.run_dir / "evidence" / f"{record_id}.json"
        if path.exists() and not started_path.exists():
            raise CogitoError("existing check evidence has no bound attempt; inspect it before issuing another action")
        if not atomic_create_json(started_path, execution):
            if _load_json(started_path) != execution:
                raise CogitoError("controlled-check contract changed since this action started")
            if not path.exists():
                raise CogitoError("controlled-check outcome is unknown; inspect the interrupted attempt before issuing another action")
        if not path.exists():
            from cogito_execution_registry import controlled_executor
            with controlled_executor(self.root, self.run_id, record_id):
                evidence = run_check(package, check_id, supplied_worktree, prior, workflow_limits=self.workflow["limits"])
            try:
                path = write_evidence_once(self.run_dir / "evidence", record_id, evidence)
            except EvidenceAlreadyExists as collision:
                path = collision.path
        recorded = _load_json(path)
        validate_check_evidence(recorded)
        if state['state'] == 'human-correction-verifying':
            latest = self.load()
            if (latest['state'] != state['state'] or latest['human'].get('escalated')
                    or latest['human'].get('attempt') != state['human'].get('attempt')):
                raise CogitoError('human correction stopped or changed while check ran; artifact cannot enter ledger')
        if (recorded["check_id"] != check_id
                or recorded["run_id"] != package["run_id"]
                or recorded["check_hash"] != execution["check_hash"]
                or recorded["effective_contract_hash"] != execution["effective_contract_hash"]):
            raise CogitoError("controlled-check evidence does not match its recorded attempt")
        payload: CheckEvidenceRecordedPayload = {"check_id": check_id, "evidence_path": str(path), "evidence_hash": hash_json(recorded), "head_commit": recorded["head_commit"], "effective_contract_hash": recorded["effective_contract_hash"]}
        return self._record_gate_event(
            CheckEvidenceRecordedEvent(type="check-evidence-recorded", payload=payload), action_id,
            request_hash=request_hash,
        )

    @run_mutation
    def enter_correction(self, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("correction-start")
        replay = self._replay(action_id, {"verification-correction-required", "post-verification-correction-required"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        events = self._events.read()
        amendments = [item for item in events if item["type"] == "technical-amendment-added"]
        if not amendments:
            raise CogitoError("correction requires a validated Technical Amendment")
        completions = [item for item in events if item["type"] in {"technical-correction-complete", "post-integration-correction-complete", "review-fix-complete"}]
        consumed = {item["payload"].get("amendment_id") for item in completions}
        if amendments[-1]["payload"]["amendment"]["id"] in consumed:
            raise CogitoError("correction requires a new, unconsumed Technical Amendment")
        if current["state"] == "verifying":
            event = "verification-correction-required"
        elif current["state"] == "post-integration-verification":
            event = "post-verification-correction-required"
        else:
            raise CogitoError("correction is not legal in the current state")
        amendment = amendments[-1]["payload"]["amendment"]
        if self.approved_package().get("task_delivery") == "atomic" and not amendment.get("added_tasks"):
            raise CogitoError("atomic corrections require amendment tasks; check-only additions can verify directly")
        payload = {"scope_within_contract": True, "amendment_id": amendment["id"], "effective_contract_hash": amendments[-1]["payload"]["effective_contract_hash"]}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    @run_mutation
    def complete_correction(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("correction-complete", amendment_id=amendment_id, commit_id=commit_id)
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, {"technical-correction-complete", "post-integration-correction-complete"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        event = "technical-correction-complete" if current["state"] == "technical-correction" else "post-integration-correction-complete" if current["state"] == "post-integration-correction" else None
        if event is None:
            raise CogitoError("correction completion is not legal in the current state")
        events = self._events.read()
        added_ids = validate_correction_completion(current, events, amendment_id, commit_id)
        package = self.approved_package()
        if package["kind"] == "maintenance":
            payload.update(self._maintenance_correction_snapshot(package, events, commit_id))
        else:
            self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
            message = self._git("show", "-s", "--format=%B", commit_id)
            if f"Cogito-Amendment: {amendment_id}" not in message:
                raise CogitoError("correction commit is missing the Cogito-Amendment trailer")
        if current["state"] == "post-integration-correction" and (self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != commit_id):
            raise CogitoError("post-integration correction commit must be current delivery HEAD")
        if not added_ids and commit_id != self._git("rev-parse", "HEAD"):
            raise CogitoError("a correction without added tasks must use current delivery HEAD")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(
            event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash,
            expected_previous_hash=current["last_event_hash"],
        )

    def _maintenance_correction_snapshot(
        self, package: Mapping[str, Any], events: Sequence[Mapping[str, Any]], commit_id: str,
    ) -> dict[str, str]:
        """Record uncommitted Maintenance work; its only commit is finalization."""
        from cogito_evidence_binding import working_tree_content_tree

        starts = [item for item in events if item["type"] == "start-gate-passed"]
        if (len(starts) != 1 or starts[0]["payload"]["delivery_head"] != commit_id
                or self._git("rev-parse", "HEAD") != commit_id
                or self._git("branch", "--show-current") != package["delivery_branch"]):
            raise CogitoError("Maintenance correction must use the unchanged Start Gate HEAD on the delivery branch")
        tree = working_tree_content_tree(self.root)
        changed = self._git("diff", "--name-only", "--no-renames", "--no-ext-diff", "-z", commit_id, tree, "--")
        control = {f"docs/cogito/packages/{self.run_id}.json", "docs/cogito/project-graph.json"}
        if any(path not in control and not _path_allowed(path, package["approved_paths"])
               for path in filter(None, changed.split("\0"))):
            raise CogitoError("Maintenance correction snapshot exceeds approved paths")
        if (self._git("rev-parse", "HEAD") != commit_id
                or self._git("branch", "--show-current") != package["delivery_branch"]):
            raise CogitoError("Maintenance delivery HEAD changed during correction snapshot")
        return {"completion_mode": "working-tree", "content_tree": tree}

    @run_mutation
    def enter_review_fix(self, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("review-fix-start")
        replay = self._replay(action_id, "review-fix-required", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "reviewing":
            raise CogitoError("review fix is not legal in the current state")
        findings = [item for item in current["agent_results"] if item.get("role") == "reviewer" and item.get("status") == "needs-fix" and item.get("requested_transition") == "review-fix"]
        if not findings:
            raise CogitoError("review fix requires a Gate-recorded Reviewer Result with needs-fix")
        finding = findings[-1]
        payload = {"scope_within_contract": True, "review_task_id": finding["task_id"], "reviewer": finding["agent_id"], "review_head": finding["head_commit"]}
        validate_transition(self.workflow, current["state"], "review-fix-required", payload, current["counters"], current["limits"])
        return self.record("review-fix-required", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    @run_mutation
    def complete_review_fix(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("review-fix-complete", amendment_id=amendment_id, commit_id=commit_id)
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, "review-fix-complete", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "review-fix":
            raise CogitoError("review fix completion is not legal in the current state")
        events = self._events.read()
        validate_review_fix_completion(current, events, amendment_id, commit_id)
        package = self.approved_package()
        if package["kind"] == "maintenance":
            payload.update(self._maintenance_correction_snapshot(package, events, commit_id))
        else:
            self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
            if f"Cogito-Amendment: {amendment_id}" not in self._git("show", "-s", "--format=%B", commit_id):
                raise CogitoError("review fix commit is missing the Cogito-Amendment trailer")
        validate_transition(self.workflow, current["state"], "review-fix-complete", payload, current["counters"], current["limits"])
        return self.record(
            "review-fix-complete", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash,
            expected_previous_hash=current["last_event_hash"],
        )

    @run_mutation
    def record_retry(self, kind: str, reason: str, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("retry", kind=kind, reason=reason)
        event = {"transient": "transient-retry", "format": "format-repair-recorded"}.get(kind)
        if event is None or not reason.strip():
            raise CogitoError("retry kind must be transient or format and include a reason")
        payload = {"reason": reason}
        replay = self._replay(action_id, event, request_hash)
        if replay is not None:
            return replay
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    @run_mutation
    def complete_integration(self, commit_id: str, slice_id: str | None = None, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("integrate", commit_id=commit_id, slice_id=slice_id)
        replay = self._replay(action_id, {"slice-integration-complete", "wave-integration-complete", "integration-complete"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "integrating":
            raise CogitoError("integration closure is not legal in the current state")
        package = self.approved_package()
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        if self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != commit_id:
            raise CogitoError("integration commit must be current HEAD on the delivery branch")
        self._validate_adopted_worktrees(current, slice_id)
        decision = derive_integration_decision(current, self._events.read(), slice_id)
        for source_head in decision.source_heads:
            self._git("merge-base", "--is-ancestor", source_head, commit_id)
        self._git("merge-base", "--is-ancestor", decision.previous_delivery_head, commit_id)
        validate_committed_scope(
            package, decision.previous_delivery_head, commit_id, self._git,
            {"docs/cogito/project-graph.json"}, self._git_repo.read_blob,
            graph_hash=current["project_graph_hash"],
        )
        payload: IntegrationCompletedPayload = {
            "commit_id": commit_id, "slice_id": slice_id or "mini-package",
            "task_ids": list(decision.task_ids), "source_heads": list(decision.source_heads),
            "previous_delivery_head": decision.previous_delivery_head,
        }
        validate_transition(self.workflow, current["state"], decision.event, payload, current["counters"], current["limits"])
        return self._record_gate_event(
            IntegrationCompletedEvent(type=decision.event, payload=payload), action_id,
            request_hash=request_hash,
        )

    @run_mutation
    def add_amendment(self, amendment: Mapping[str, Any], action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("amend", amendment=amendment)
        replay = self._replay(action_id, "technical-amendment-added", request_hash)
        if replay is not None:
            return replay
        package = self.approved_package()
        state = self.load()
        if state["state"] not in {"verifying", "reviewing", "review-fix", "post-integration-verification",
                                  "human-feedback-triage", "human-correction-verifying", "human-correction-reviewing"}:
            raise CogitoError("Technical Amendments are only legal while handling a verification or review finding")
        if state["state"].startswith("human-"):
            human = state.get("human", {})
            if not human.get("triage") or human["triage"]["route"] != "local" or human.get("escalated"):
                raise CogitoError("classify a local human correction before adding an amendment")
            human_events = self._events.read()
            last_feedback = max(e["sequence"] for e in human_events if e["type"] == "human-feedback-recorded")
            consumed = {e["payload"]["amendment_id"] for e in human_events if e["type"] == "human-correction-started"}
            if any(e["type"] == "technical-amendment-added" and e["sequence"] > last_feedback
                   and e["payload"]["amendment"]["id"] not in consumed for e in human_events):
                raise CogitoError("start the existing human amendment before adding another")
        prior = [item["payload"]["amendment"] for item in self._events.read() if item["type"] == "technical-amendment-added"]
        digest = materialize_contract_with_limits(package, [*prior, amendment], self.workflow["limits"])["effective_contract_hash"]
        # Correction tasks must finish before verification/integration can resume.
        # A cross-Slice predecessor cannot reach integrated inside this cycle.
        added_tasks = amendment.get("added_tasks", [])
        tasks = dict(state["tasks"])
        tasks.update({task["id"]: {**task, "status": "pending"} for task in added_tasks})
        for task in added_tasks:
            for dependency in task.get("depends_on", []):
                predecessor = tasks[dependency]
                same_slice = (predecessor.get("slice_id") or "mini-package") == task["slice_id"]
                if not same_slice and predecessor.get("status") != "integrated":
                    raise CogitoError("amendment cross-Slice dependencies must already be integrated")
        payload = {"amendment": dict(amendment), "effective_contract_hash": digest}
        return self.record(
            "technical-amendment-added",
            payload,
            action_id, self._GATE_AUTHORITY, request_hash=request_hash,
        )

    @run_mutation
    def approve_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("approve", draft=draft)
        relative = Path("docs") / "cogito" / "packages" / f"{self.run_id}.json"
        target = self.root / relative
        replay = self._replay(action_id, "package-approved", request_hash)
        if replay is not None:
            restore_approval_permissions(target)
            return replay
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package_with_limits(package, self.workflow["limits"])
        self._validate_policy(package)
        digest = package_hash(package)
        package["package_hash"] = digest
        tasks = tasks_with_dependencies(package["execution_dag"])
        current = self.load()
        guard_checkpoint(current, "package-ready")
        if package["kind"] != current["kind"]:
            raise CogitoError("Package kind must match the run kind")
        if current["state"] != "awaiting-package-approval":
            raise CogitoError("Package approval is not legal in the current state")
        if current.get("candidate_package_hash") != digest:
            raise CogitoError("approved Package differs from the Gate-validated candidate")
        planning_approval = self._planning_approval_binding(current)
        graph_path = self.root / "docs" / "cogito" / "project-graph.json"
        graph_before = graph_path.read_bytes() if graph_path.exists() else None
        # Finish validation before publishing anything. Package creation is
        # exclusive, so rollback can distinguish our file from an existing one.
        graph = self._formalize_project_graph(package, graph_path)
        event_payload = {"approved": True, "package_path": relative.as_posix(), "package_hash": digest, "tasks": tasks, "max_workers": package["policy_snapshot"]["max_workers"], "project_graph_hash": hash_json(graph), "project_graph_snapshot": graph, "limits": package["limits"]}
        if planning_approval:
            event_payload["planning_approval"] = planning_approval
        from cogito_disposition_scope import dispositions
        for decision in dispositions(self.root):
            proposal = decision.get('proposal') or {}
            if decision['state'] == 'executing' and proposal.get('followup_run_id') == self.run_id:
                if proposal.get('followup_package_hash') != digest:
                    raise CogitoError('follow-up differs from its approved disposition')
                event_payload['human_review_mandate'] = {
                    'disposition_id': decision['disposition_id'], 'source_run_id': decision['source_run_id']}

        return publish_approval(
            ApprovalArtifacts(target, package, graph_path, graph, graph_before),
            prior_state=current,
            workflow=self.workflow,
            load_events=self._events.read,
            record_approval=lambda: self.record(
                "package-approved", event_payload, action_id,
                self._GATE_AUTHORITY, request_hash=request_hash,
                expected_previous_hash=current["last_event_hash"],
            ),
        )

    def _validate_start_checkout(
        self, current: RunState, package: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Validate the ordinary delivery checkout without changing authoritative state."""
        self.validate_stage_commits()
        self._validate_policy(package)
        checkout = self.root
        head = self._git_at(checkout, "rev-parse", "HEAD")
        self._git_at(checkout, "cat-file", "-e", f"{package['baseline_commit']}^{{commit}}")
        if self._git_at(checkout, "branch", "--show-current") != package["delivery_branch"]:
            raise CogitoError("Start Gate is not on the Package delivery branch")
        self._git_at(checkout, "merge-base", "--is-ancestor", package["baseline_commit"], head)
        allowed_control = {current["package_path"], "docs/cogito/project-graph.json"}

        def validate_content(relative: str, expected: str) -> None:
            path = (checkout / relative).resolve()
            try:
                path.relative_to(checkout.resolve())
                actual = hashlib.sha256(path.read_bytes()).hexdigest()
            except (ValueError, OSError) as exc:
                raise CogitoError(f"cannot validate Package content {relative}: {exc}") from exc
            if actual != expected:
                raise CogitoError(f"Package content hash drifted: {relative}")

        if current.get("stage_commits") and current.get("shared_document"):
            document = current["shared_document"]
            validate_content(document["path"], document["hash"])
        for item in package["slices"]:
            for document in (item["spec"], item["plan"]):
                validate_content(document["path"], document["hash"])
                allowed_control.add(document["path"])
        for source in package["source_registry"]:
            validate_content(source["path"], source["hash"])
            if source["disposition"] in {"adopted", "updated"}:
                allowed_control.add(source["path"])
        graph = _load_json(checkout / "docs" / "cogito" / "project-graph.json")
        validate_project_graph(graph)
        if hash_json(graph) != current.get("project_graph_hash") or graph.get("active_run_id") != self.run_id or any(item["id"] not in graph.get("slices", {}) for item in package["slices"]):
            raise CogitoError("Project Graph is not formalized for this Package")
        dirty = []
        for line in self._git_at(checkout, "status", "--porcelain", "--untracked-files=all").splitlines():
            if len(line) > 2 and line[0] != " " and line[1] == " " and line[2] != " ":
                line = " " + line
            path = line[3:].split(" -> ")[-1] if len(line) > 3 else ""
            if not path.startswith(".cogito/") and path not in allowed_control:
                dirty.append(line)
        if dirty:
            raise CogitoError("Start Gate requires a clean delivery checkout")
        payload: dict[str, Any] = {
            "baseline_valid": True, "contract_valid": True,
            "worktrees_valid": self._worker_layout_valid(package),
            "delivery_head": head, "package_hash": package_hash(package),
        }
        return payload

    @run_mutation
    def start_gate(self, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("start")
        replay = self._replay(action_id, "start-gate-passed", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "start-gate":
            raise CogitoError("Start Gate is not legal in the current state")
        package = self.approved_package()
        payload = self._validate_start_checkout(current, package)
        validate_transition(self.workflow, current["state"], "start-gate-passed", payload, current["counters"])
        return self.record("start-gate-passed", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    @run_mutation
    def start_gate_from_artifact(self, manifest: Mapping[str, Any], binding: Mapping[str, Any],
                                 action_id: str, _authority: object | None = None) -> RunState:
        """Validate an approved RP Start tree without materializing it."""
        if _authority is not self._GATE_AUTHORITY:
            raise CogitoError("immutable Start Gate requires RP Gate authority")
        from cogito_git_objects import HardenedObjectReader
        from cogito_replan_toolchain import execution_digest
        from cogito_start_artifact import validate_live_publication, validate_start_artifact
        artifact_hash = hash_json(manifest)
        request = {
            "start_artifact_hash": artifact_hash,
            "proposal_hash": binding.get("proposal_hash"),
            "approval_event_hash": binding.get("approval_event_hash"),
            "verifier_digest": manifest.get("verifier_digest"),
        }
        request_hash = request_fingerprint("start", **request)
        matches = [event for event in self._events.read()
                   if event.get("action_id") == action_id]
        if matches:
            if len(matches) != 1 or matches[0]["type"] != "start-gate-passed":
                raise CogitoError(f"action_id {action_id!r} was already used for different content")
            require_same_request(matches[0], request_hash, action_id)
            return self._events.project()
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current["state"] != "start-gate":
            raise CogitoError("Start Gate is not legal in the current state")
        if (binding.get("successor_run_id") != self.run_id
                or binding.get("start_artifact_hash") != artifact_hash
                or binding.get("source_snapshot_hash") != manifest.get("source_snapshot_hash")):
            raise CogitoError("Start artifact differs from its RP approval binding")
        if manifest.get("workflow_digest") != hash_json(self.workflow):
            raise CogitoError("Start artifact workflow differs from the executing Gate")
        verifier_digest = execution_digest()
        if manifest.get("verifier_digest") != verifier_digest:
            raise CogitoError("Start artifact verifier differs from the executing Gate")
        reader = HardenedObjectReader(self.root)
        result = validate_start_artifact(
            reader, manifest, workflow_limits=self.workflow["limits"],
            expected_replan_id=binding.get("replan_id"),
            expected_source_run_id=binding.get("source_run_id"),
            expected_successor_run_id=self.run_id,
        )
        if (current.get("package_hash") != result["package_hash"]
                or current.get("package_path") != manifest.get("package_path")
                or current.get("project_graph_hash") != result["project_graph_hash"]):
            raise CogitoError("successor Package or Graph event differs from approved Start artifact")
        validate_live_publication(self.root, manifest)
        _, package_bytes = reader.blob_at(manifest["result_start_tree"], manifest["package_path"])
        try:
            package = json.loads(package_bytes)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CogitoError("Start artifact Package is not valid JSON") from exc
        if not self._worker_layout_contract_valid(package):
            raise CogitoError("successor worker layout contract is invalid")
        self._validate_policy(package)
        payload = {
            "baseline_valid": True,
            "contract_valid": True,
            "worktrees_valid": True,
            "delivery_head": result["delivery_head"],
            "package_hash": result["package_hash"],
            "project_graph_hash": result["project_graph_hash"],
            "start_artifact_hash": artifact_hash,
            "result_start_tree": result["delivery_tree"],
            "proposal_hash": binding["proposal_hash"],
            "approval_event_hash": binding["approval_event_hash"],
            "tool_digest": manifest["tool_digest"],
            "verifier_digest": verifier_digest,
            "replan_start": dict(binding),
        }
        validate_transition(self.workflow, current["state"], "start-gate-passed", payload, current["counters"])
        return self.record(
            "start-gate-passed", payload, action_id, self._GATE_AUTHORITY,
            request_hash=request_hash, expected_previous_hash=current["last_event_hash"],
        )

    def _validate_adopted_worktrees(self, current, slice_id=None):
        for task in current['tasks'].values():
            receipt=task.get('adoption')
            if not receipt or task['status']!='reviewed' or (slice_id and task.get('slice_id')!=slice_id):
                continue
            worktree=Path(task['worktree'])
            index,tree=capture_index_and_worktree_trees(worktree)
            if (index!=receipt['content_tree'] or tree!=receipt['content_tree']
                    or self._git_at(worktree,'rev-parse','HEAD')!=receipt['target_implementation_head']):
                raise CogitoError('adopted work changed after approval; fresh verification and review are required')

    @run_mutation
    def advance_adoptions(self, action_id: str) -> RunState:
        current = self.load()
        if current['state'] != 'executing':
            raise CogitoError('adoption progression requires executing state')
        tasks = list(current['tasks'].values())
        if any(is_active_task(t) or t['status'] in {'complete','verified'} for t in tasks):
            raise CogitoError('finish active implementation before adoption progression')
        edges = [{'from': d, 'to': t['id']} for t in tasks for d in t.get('depends_on', [])]
        if ready_tasks(tasks, edges, current['max_workers']):
            raise CogitoError('dispatch remaining ready work before adoption progression')
        reviewed = [t['id'] for t in tasks if t['status']=='reviewed']
        if not reviewed or not all('adoption' in current['tasks'][t] for t in reviewed):
            raise CogitoError('no fully adopted review wave is ready')
        self._validate_adopted_worktrees(current)
        return self.record('adoption-ready', {'task_ids': reviewed}, action_id, self._GATE_AUTHORITY)

    @run_mutation
    def decide_post_verification(self, passed_evidence: Sequence[Mapping[str, Any]], reviewer_escalation: bool = False, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("post-verify", evidence=passed_evidence, reviewer_escalation=reviewer_escalation)
        replay = self._replay(action_id, {"human-review-required", "auto-accept-ready"}, request_hash)
        if replay is not None:
            return replay
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current["state"] != "post-integration-verification":
            raise CogitoError("post-verification decision is not legal in the current state")
        package = self._approved_package_from_state(current)
        self._events.refresh_cache(current)
        current_head = self._git("rev-parse", "HEAD")
        self._validate_evidence(
            package, passed_evidence, snapshot=snapshot,
            phase="post-integration", current_head=current_head,
        )
        human = package["human_gate"]
        human_required = bool(current.get("human_review_mandate") or reviewer_escalation or human.get("high_risk_hotspots") or any(item["applicable"] for item in human["predicates"]))
        event = "human-review-required" if human_required else "auto-accept-ready"
        payload = {"passed": True, "human_required": human_required, "evidence": [item["evidence_path"] for item in passed_evidence], "reviewer_escalation": bool(reviewer_escalation), "delivery_head": current_head}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        if self._git("rev-parse", "HEAD") != current_head:
            raise CogitoError("delivery HEAD changed during verification; retry with the same action_id")
        return self.record(
            event, payload, action_id, self._GATE_AUTHORITY,
            request_hash=request_hash, expected_previous_hash=current["last_event_hash"],
        )

    @run_mutation
    def resume_gate(self, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("resume")
        replay = self._replay(action_id, "resume", request_hash)
        if replay is not None:
            return replay
        payload = self.validate_resume()
        return self.record("resume", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def validate_resume(self):
        """Preflight recovery without persisting a decision or changing the run."""
        current = self.load()
        if current["state"] != "blocked" or not current.get("blocked_from"):
            raise CogitoError("only a blocked run with a recorded origin may resume")
        if not current.get("package_hash") and current.get("planning", {}).get("revision"):
            self._planning_environment(current)
            candidate = current["planning"].get("candidate")
            if candidate:
                assert_files(self.root, candidate, strict=True)
                self._validate_policy(candidate["package"])
        if current.get("human", {}).get("escalated"):
            raise CogitoError("human feedback requires replanning; ordinary resume cannot clear it")
        target = current["blocked_from"]
        if target not in self.workflow["resume_targets"]:
            raise CogitoError("blocked origin is not a legal resume target")
        if current.get("package_path"):
            package = self.approved_package()
            self._validate_policy(package)
            head = self._git("rev-parse", "HEAD")
            if self._git("branch", "--show-current") != package["delivery_branch"]:
                raise CogitoError("Resume Gate delivery branch drifted")
            self._git("merge-base", "--is-ancestor", package["baseline_commit"], head)
            if target != "finalizing":
                graph = _load_json(self.root / "docs/cogito/project-graph.json")
                validate_project_graph(graph)
                if hash_json(graph) != current.get("project_graph_hash") or graph.get("active_run_id") != self.run_id:
                    raise CogitoError("Resume Gate Project Graph drifted")
            for task in current["tasks"].values():
                if is_active_task(task):
                    worktree = Path(str(task.get("worktree", "")))
                    if not worktree.is_dir() or self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
                        raise CogitoError("Resume Gate found a drifted active worker lease")
                    worker_head = self._git_at(worktree, "rev-parse", "HEAD")
                    # Active leases were recorded with a validated base commit.
                    self._git("merge-base", "--is-ancestor", cast(str, task.get("base_commit")), worker_head)
                    recorded = [item for item in current["agent_results"] if item.get("task_id") == task.get("id")]
                    if recorded and worker_head != recorded[-1].get("head_commit"):
                        raise CogitoError("Resume Gate worker HEAD differs from its recorded Result")
            for evidence_path, ledger in current.get("evidence", {}).items():
                evidence = _load_json(Path(evidence_path))
                if hash_json(evidence) != ledger.get("evidence_hash"):
                    raise CogitoError("Resume Gate found tampered evidence")
        reconciliation = hash_json({"target": target, "head": self._git("rev-parse", "HEAD"), "event_hash": current["last_event_hash"]})
        return {"target": target, "validated": True, "reconciliation_hash": reconciliation}

    @run_mutation
    def approve_human_gate(self, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("human-approve")
        replay = self._replay(action_id, "human-approved", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        payload = {"approved": True}
        if current.get("human"):
            if current['human'].get('pending_feedback'):
                raise CogitoError('process pending human feedback before accepting the delivery')
            binding = self._human_current_evidence()
            payload.update(binding=binding, feedback_hash=current["human"]["feedback_hash"])
        validate_transition(self.workflow, current["state"], "human-approved", payload, current["counters"])
        return self.record("human-approved", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    @run_mutation
    def finalize(self, result_path: str, project_graph_path: str, final_commit: str, action_id: str | None = None) -> RunState:
        request_hash = request_fingerprint("finalize", result_path=result_path, project_graph_path=project_graph_path, final_commit=final_commit)
        replay = self._replay(action_id, "finalization-complete", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "finalizing":
            raise CogitoError("finalization is not legal in the current state")
        package = self.approved_package()
        payload = validate_finalization(
            run_id=self.run_id,
            package=package,
            state=current,
            load_events=self._events.read,
            result_path=result_path,
            project_graph_path=project_graph_path,
            final_commit=final_commit,
            git=self._git,
            read_blob=self._git_repo.read_blob,
            workflow_limits=self.workflow["limits"],
        )
        validate_transition(self.workflow, current["state"], "finalization-complete", payload, current["counters"])
        return self.record("finalization-complete", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def delivery_summary(self) -> dict[str, Any]:
        """Produce the ledger-derived Result section after all acceptance Gates."""
        snapshot = self._events.snapshot()
        current = snapshot.state
        if current["state"] != "finalizing":
            raise CogitoError("delivery summary is only available in finalizing")
        self._approved_package_from_state(current)
        return build_delivery_summary(current, snapshot.events)

    def completion_report(self) -> dict[str, Any]:
        return self._load_completion_report(self.load())

    def _load_completion_report(self, current: RunState) -> dict[str, Any]:
        """Read the Result from the recorded final commit, never the working copy."""
        if current["state"] != "accepted":
            raise CogitoError("completion report is only available for an accepted run")
        final_events = [item for item in self._events.read() if item["type"] == "finalization-complete"]
        final = final_events[-1]["payload"]
        try:
            result = json.loads(self._git("show", f"{final['final_commit']}:{final['result_path']}"))
        except json.JSONDecodeError as exc:
            raise CogitoError(f"committed Result is not valid JSON: {exc}") from exc
        return build_completion_report(self.run_id, final["final_commit"], result)

    def _git(self, *args: str) -> str:
        return self._git_repo.run(*args)

    def _git_at(self, directory: Path, *args: str) -> str:
        return self._git_repo.run_at(directory, *args)

    def _task_worktree(self, task: Mapping[str, Any], package: Mapping[str, Any]) -> tuple[Path, str]:
        if package["kind"] in {"maintenance", "documentation"}:
            return self.root, package["delivery_branch"]
        slices = {item["id"]: item for item in package["slices"]}
        slice_item = slices.get(task.get("slice_id"))
        if not slice_item:
            raise CogitoError("task has no owning Slice")
        worktree = (self.root / slice_item["worker"]["worktree"]).resolve()
        try:
            worktree.relative_to(self.root)
        except ValueError as exc:
            raise CogitoError("worker worktree escapes repository root") from exc
        if not worktree.is_dir() or self._git_at(worktree, "branch", "--show-current") != slice_item["worker"]["branch"]:
            raise CogitoError("dedicated worker branch/worktree is not ready")
        return worktree, slice_item["worker"]["branch"]

    def _validate_content_hash(self, relative: str, expected: str) -> None:
        path = (self.root / relative).resolve()
        try:
            path.relative_to(self.root)
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except (ValueError, OSError) as exc:
            raise CogitoError(f"cannot validate Package content {relative}: {exc}") from exc
        if actual != expected:
            raise CogitoError(f"Package content hash drifted: {relative}")

    def _replay(self, action_id: str | None, event_type: str | set[str], request_hash: str) -> RunState | None:
        if not action_id:
            return None
        pending = self.run_dir / "check-actions" / hash_json(action_id) / "request.json"
        if pending.exists():
            require_same_request(_load_json(pending), request_hash, action_id)
        expected = {event_type} if isinstance(event_type, str) else event_type
        matches = [item for item in self._events.read() if item.get("action_id") == action_id]
        if not matches:
            return None
        if len(matches) != 1 or matches[0]["type"] not in expected:
            raise CogitoError(f"action_id {action_id!r} was already used for different content")
        require_same_request(matches[0], request_hash, action_id)
        return self.load()

    def _worker_layout_valid(self, package: Mapping[str, Any]) -> bool:
        if package["kind"] in {"maintenance", "documentation"}:
            return True
        branches = [item["worker"]["branch"] for item in package["slices"]]
        worktrees = [item["worker"]["worktree"] for item in package["slices"]]
        return (
            len(branches) == len(set(branches)) and len(worktrees) == len(set(worktrees))
            and package["delivery_branch"] not in branches
            and all(_safe_repo_path(path) and not (self.root / path).exists() for path in worktrees)
        )

    @staticmethod
    def _worker_layout_contract_valid(package: Mapping[str, Any]) -> bool:
        if package["kind"] in {"maintenance", "documentation"}:
            return True
        branches = [item["worker"]["branch"] for item in package["slices"]]
        worktrees = [item["worker"]["worktree"] for item in package["slices"]]
        return (len(branches) == len(set(branches))
                and len(worktrees) == len(set(worktrees))
                and package["delivery_branch"] not in branches
                and all(_safe_repo_path(path) for path in worktrees))

    def _formalize_project_graph(self, package: Mapping[str, Any], path: Path) -> dict[str, Any]:
        existing = _load_json(path) if path.exists() else None
        return formalize_project_graph(existing, package, self.run_id)

    def _validate_policy(self, package: Mapping[str, Any]) -> None:
        validate_gate_policy(self.root, package)

    def _validate_evidence(
        self, package: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]], *,
        snapshot: EventSnapshot, phase: Literal["task", "implementation", "post-integration"],
        current_head: str | None = None,
        validate_supplied: bool = False,
        task_id: str | None = None,
    ) -> None:
        """Collect immutable files for pure rules using the operation's snapshot.

        Resolve paths only here; the rules receive records and ledger entries
        keyed by the original supplied path, preserving evidence hashes.
        """
        for item in evidence:
            validate_check_evidence(item)
        prior = [item["payload"]["amendment"] for item in snapshot.events if item["type"] == "technical-amendment-added"]
        effective = materialize_contract_with_limits(package, prior, self.workflow["limits"])
        required = set(verification_checks(effective, phase, task_id))
        supplied = {item["check_id"]: item for item in evidence}
        if validate_supplied:
            known = {check['id'] for check in effective['checks']}
            if not supplied or len(supplied) != len(evidence) or supplied.keys() - known:
                raise CogitoError('human evidence must name distinct known checks and cannot be empty')
            required.update(supplied)
        if required - supplied.keys():
            raise CogitoError("required verification evidence is missing")
        evidence_root = (self.run_dir / "evidence").resolve()
        recorded_evidence = {}
        ledger = {}
        for check_id in sorted(required):
            original_path = supplied[check_id]["evidence_path"]
            path = Path(original_path).resolve()
            try:
                path.relative_to(evidence_root)
            except ValueError as exc:
                raise CogitoError(f"evidence path is outside this run for {check_id}") from exc
            if not path.is_file():
                raise CogitoError(f"immutable evidence file is missing for {check_id}")
            recorded_evidence[original_path] = _load_json(path)
            entry = snapshot.state.get("evidence", {}).get(str(path))
            if entry is not None:
                ledger[original_path] = entry
        validate_gate_evidence(
            package, evidence, snapshot.events, ledger, recorded_evidence,
            effective_contract=effective, phase=phase, current_head=current_head,
            validate_supplied=validate_supplied,
            task_id=task_id,
        )

    def next_action(self) -> dict[str, Any]:
        from cogito_disposition_scope import dispositions
        for disposition in dispositions(self.root):
            if self.run_id in {disposition["source_run_id"], disposition.get("successor_run_id"), (disposition.get("proposal") or {}).get("followup_run_id")} and disposition["state"] != "completed":
                metadata = {"disposition_id": disposition["disposition_id"], "disposition_state": disposition["state"],
                            "disposition_next_action": disposition["next_action"]}
                projection = self.load()
                if disposition['state'] == 'executing' and (disposition.get('proposal') or {}).get('followup_run_id') == self.run_id:
                    output = derive_next_action(projection)
                    if projection['state'] == 'accepted':
                        output['next_action'] = 'complete-disposition'
                        output['report'] = self._load_completion_report(projection)
                    return {**output, **metadata}
                return {"state": projection["state"], "next_action": "continue-disposition", **metadata}
        from cogito_replan_lock import replans
        for replan in replans(self.root):
            if self.run_id in {replan["source_run_id"], replan["successor_run_id"]} and replan["state"] not in {"completed", "abandoned", "disposition"}:
                from cogito_replan_store import ReplanStore
                replan = ReplanStore(self.root, replan["replan_id"]).load()
                projection = self.load()
                if self.run_id == replan["successor_run_id"] and not projection.get("package_hash") and projection.get("planning", {}).get("revision"):
                    output = derive_next_action(projection)
                    if output["next_action"] == "request-package-approval":
                        output["next_action"] = "prepare-replan-proposal"
                    output.update(replan_id=replan["replan_id"], replan_state=replan["state"])
                    return output
                return {"state": projection["state"], "next_action": "continue-replan", "replan_id": replan["replan_id"], "replan_state": replan["state"], "replan_next_action": replan["next_action"]}
        projection = self.load()
        output = derive_next_action(projection)
        if projection["state"] == "accepted":
            output["report"] = self._load_completion_report(projection)
        return output
