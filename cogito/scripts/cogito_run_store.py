#!/usr/bin/env python3
"""Gate transaction coordinator for a Cogito run."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cogito_common import CogitoError, atomic_create_json, atomic_write_json, hash_json, load_json
from cogito_actions import controlled_check_attempt, request_fingerprint, require_same_request
from cogito_contracts import (
    effective_contract_hash, materialize_contract, package_hash,
    path_allowed as _path_allowed, required as _required,
    safe_repo_path as _safe_repo_path, validate_agent_result,
    validate_package,
)
from cogito_events import append_event, read_events
from cogito_evidence_contract import validate_check_evidence
from cogito_finalization import validate_finalization
from cogito_git import GitRepository
from cogito_gate_validation import (
    validate_evidence as validate_gate_evidence,
    validate_policy as validate_gate_policy,
    derive_review_decision,
)
from cogito_projection import reduce_events
from cogito_project_graph import formalize_project_graph, validate_project_graph
from cogito_run_queries import build_completion_report, derive_next_action
from cogito_scheduler import ready_tasks, tasks_with_dependencies
from cogito_workflow import load_workflow, validate_transition

_load_json = load_json


class RunStore:
    _GATE_AUTHORITY = object()
    _PROTECTED_RECORD_EVENTS = {
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

    def __init__(self, root: str | Path, run_id: str, workflow: Mapping[str, Any] | None = None):
        if not re.fullmatch(r"(?:DEV|MNT)-[A-Za-z0-9._-]+", run_id):
            raise CogitoError("run_id must use a safe DEV-* or MNT-* identifier")
        self.root = Path(root).resolve()
        self._git_repo = GitRepository(self.root)
        self.run_id = run_id
        self.run_dir = self.root / ".cogito" / "runs" / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self.state_path = self.run_dir / "state.json"
        self.workflow = dict(workflow or load_workflow())

    def create(self, kind: str) -> dict[str, Any]:
        if self.events_path.exists():
            raise CogitoError(f"run already exists: {self.run_id}")
        self.run_dir.mkdir(parents=True, exist_ok=False)
        append_event(self.events_path, {"type": "run-created", "payload": {"run_id": self.run_id, "kind": kind}, "action_id": f"create:{self.run_id}"})
        return self._project()

    def load(self) -> dict[str, Any]:
        projection = reduce_events(read_events(self.events_path), self.workflow)
        if projection.get("package_path"):
            package_path = self.root / projection["package_path"]
            package = _load_json(package_path)
            validate_package(package)
            if package_hash(package) != projection["package_hash"]:
                raise CogitoError("approved Package content no longer matches its frozen hash")
        self._refresh_state_cache(projection)
        return projection

    def _project(self) -> dict[str, Any]:
        projection = reduce_events(read_events(self.events_path), self.workflow)
        self._refresh_state_cache(projection)
        return projection

    def _refresh_state_cache(self, projection: Mapping[str, Any]) -> None:
        """Repair only the disposable cache, never authoritative artifacts."""
        try:
            cached = _load_json(self.state_path)
        except CogitoError:
            cached = None
        if cached != projection:
            try:
                atomic_write_json(self.state_path, projection)
            except OSError as exc:
                raise CogitoError(
                    "state cache could not be refreshed; event history is unchanged; "
                    "retry with the same action_id after resolving the storage error"
                ) from exc

    def record(self, event_type: str, payload: Mapping[str, Any], action_id: str | None = None, _authority: object | None = None, *, request_hash: str | None = None) -> dict[str, Any]:
        if event_type in self._PROTECTED_RECORD_EVENTS and _authority is not self._GATE_AUTHORITY:
            raise CogitoError(f"{event_type} requires its dedicated Gate operation")
        request_hash = request_hash or request_fingerprint("record", event=event_type, payload=payload)
        replay = self._replay(action_id, event_type, request_hash)
        if replay is not None:
            return replay
        existing = read_events(self.events_path)
        # Validate the candidate against authoritative history before mutating it.
        reduce_events([*existing, {"type": event_type, "payload": dict(payload)}], self.workflow)
        expected = existing[-1]["event_hash"] if existing else "0" * 64
        append_event(self.events_path, {"type": event_type, "payload": dict(payload), "action_id": action_id, "request_hash": request_hash}, expected)
        return self._project()

    def transition(self, event: str, payload: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("transition", event=event, payload=payload)
        replay = self._replay(action_id, event, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if event in self._PROTECTED_TRANSITION_EVENTS:
            raise CogitoError(f"{event} requires its dedicated Gate operation")
        payload = dict(payload)
        if event == "implementation-complete":
            completed = {task_id for task_id, item in current["tasks"].items() if item.get("status") == "complete"}
            implemented = {item.get("task_id") for item in current["agent_results"] if item.get("role") == "implementer" and item.get("status") == "complete" and item.get("requested_transition") == "verifying"}
            active = any(item.get("status") in {"leased", "running"} for item in current["tasks"].values())
            edges = [{"from": dependency, "to": task["id"]} for task in current["tasks"].values() for dependency in task.get("depends_on", [])]
            dispatchable = ready_tasks(list(current["tasks"].values()), edges, current["max_workers"])
            payload["tasks_complete"] = bool(completed) and not active and not dispatchable and completed <= implemented
            payload["task_ids"] = sorted(completed)
        if event == "review-approved":
            decision = derive_review_decision(
                self.approved_package(), current,
                review_exemption=payload.get("review_exemption") is True,
            )
            payload = {**payload, **decision}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, request_hash=request_hash)

    def approved_package(self) -> dict[str, Any]:
        state = self.load()
        if not state.get("package_path"):
            raise CogitoError("run has no approved Package")
        package = _load_json(self.root / state["package_path"])
        validate_package(package)
        if package_hash(package) != state["package_hash"]:
            raise CogitoError("approved Package hash mismatch")
        return package

    def prepare_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("prepare-package", draft=draft)
        replay = self._replay(action_id, {"mini-package-ready", "package-ready"}, request_hash)
        if replay is not None:
            return replay
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package(package)
        self._validate_policy(package)
        current = self.load()
        mini = package["kind"] in {"maintenance", "documentation"}
        if not mini and package["shared_understanding"]["hash"] != current.get("shared_understanding_hash"):
            raise CogitoError("Package is not bound to the confirmed Shared Understanding")
        if not mini and package["boundary"] != current.get("boundary"):
            raise CogitoError("Package is not bound to the recorded Boundary Gate result")
        event = "mini-package-ready" if mini else "package-ready"
        expected_state = "preparing" if mini else "package-preparing"
        payload = {"package_valid": True, "candidate_package_hash": package_hash(package)}
        if current["state"] != expected_state:
            raise CogitoError("Package preparation is not legal in the current state")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def update_task(self, task_id: str, status: str, agent_id: str, action_id: str | None = None) -> dict[str, Any]:
        payload = {"task_id": task_id, "status": status, "agent_id": agent_id}
        request_hash = request_fingerprint("task", **payload)
        replay = self._replay(action_id, "task-updated", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] not in {"executing", "technical-correction", "review-fix", "post-integration-correction"}:
            raise CogitoError("task updates are not legal in the current state")
        task = current["tasks"].get(task_id)
        if not task:
            raise CogitoError("task is outside the effective Package")
        if status == "leased":
            package = self.approved_package()
            if current["state"] == "post-integration-correction":
                worktree, branch = self.root, package["delivery_branch"]
            else:
                worktree, branch = self._task_worktree(task, package)
            base_commit = self._git_at(worktree, "rev-parse", "HEAD")
            task_slice = task.get("slice_id") or "mini-package"
            prior_heads = [
                item["head_commit"] for item in current["agent_results"]
                if item.get("role") == "implementer"
                and (current["tasks"].get(item.get("task_id"), {}).get("slice_id") or "mini-package") == task_slice
            ]
            expected_base = prior_heads[-1] if prior_heads and current["state"] != "post-integration-correction" else self._git("rev-parse", "HEAD")
            if base_commit != expected_base:
                raise CogitoError("a Slice worktree must start from the latest delivery HEAD")
            payload.update({"worktree": str(worktree), "branch": branch, "base_commit": base_commit})
        return self.record("task-updated", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def submit_agent_result(self, result: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        payload = {"result": dict(result)}
        request_hash = request_fingerprint("agent-result", result=result)
        replay = self._replay(action_id, "agent-result-recorded", request_hash)
        if replay is not None:
            return replay
        package = self.approved_package()
        validate_agent_result(result, package)
        state = self.load()
        allowed_states = {
            "implementer": {"executing", "technical-correction", "review-fix", "post-integration-correction"},
            "reviewer": {"reviewing"}, "integrator": {"integrating"},
        }
        if state["state"] not in allowed_states[result["role"]]:
            raise CogitoError(f"{result['role']} Result is not legal in state {state['state']}")
        task = state["tasks"].get(result["task_id"])
        if not task:
            raise CogitoError("Agent Result references a task outside the effective Package")
        if result["role"] != "reviewer" and task.get("agent_id") != result["agent_id"]:
            raise CogitoError("Agent Result identity does not own the task lease")
        if result["role"] == "reviewer" and result.get("reviewed_implementer") != task.get("agent_id"):
            raise CogitoError("Reviewer Result is not bound to the task implementer")
        worktree = Path(str(task.get("worktree", "")))
        if not worktree.is_dir() or result["base_commit"] != task.get("base_commit") or result["head_commit"] != self._git_at(worktree, "rev-parse", "HEAD"):
            raise CogitoError("Agent Result commits are not bound to the leased worktree")
        if self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
            raise CogitoError("Agent Result worktree is not on its leased branch")
        self._git("cat-file", "-e", f"{result['base_commit']}^{{commit}}")
        self._git("cat-file", "-e", f"{result['head_commit']}^{{commit}}")
        self._git("merge-base", "--is-ancestor", result["base_commit"], result["head_commit"])
        actual_paths = set(filter(None, self._git_at(worktree, "diff", "--name-only", result["base_commit"], result["head_commit"], "--").splitlines()))
        if package["kind"] == "maintenance":
            actual_paths.update(filter(None, self._git_at(worktree, "diff", "--name-only", "--").splitlines()))
            actual_paths.update(filter(None, self._git_at(worktree, "ls-files", "--others", "--exclude-standard").splitlines()))
            control_paths = {self.load().get("package_path"), "docs/cogito/project-graph.json"}
            actual_paths = {path for path in actual_paths if path not in control_paths and not path.startswith(".cogito/")}
        if result["role"] != "reviewer" and set(result["changed_paths"]) != actual_paths:
            raise CogitoError("Agent Result changed_paths do not match its commit range")
        if any(not _path_allowed(path, task.get("paths", [])) for path in actual_paths):
            raise CogitoError("Agent Result exceeds its task path responsibility")
        return self.record("agent-result-recorded", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def complete_verification(self, evidence: Sequence[Mapping[str, Any]], action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("verify", evidence=evidence)
        replay = self._replay(action_id, "verification-passed", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "verifying":
            raise CogitoError("verification closure is not legal in the current state")
        package = self.approved_package()
        self._validate_evidence(package, evidence)
        payload = {"passed": True, "evidence": [item["evidence_path"] for item in evidence]}
        validate_transition(self.workflow, current["state"], "verification-passed", payload, current["counters"])
        return self.record("verification-passed", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def run_controlled_check(self, check_id: str, worktree: str | Path, action_id: str) -> dict[str, Any]:
        if not action_id:
            raise CogitoError("controlled check requires a stable action_id")
        supplied_worktree = Path(worktree).resolve()
        request_hash = request_fingerprint("run-check", check_id=check_id, worktree=str(supplied_worktree))
        replay = self._replay(action_id, "check-evidence-recorded", request_hash)
        if replay is not None:
            return replay
        if not self.events_path.is_file():
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
    ) -> dict[str, Any]:
        package = self.approved_package()
        state = self.load()
        if state["state"] == "post-integration-verification":
            if supplied_worktree != self.root:
                raise CogitoError("post-integration checks must run in the delivery checkout")
        elif state["state"] == "verifying":
            eligible = {Path(str(task.get("worktree", ""))).resolve() for task in state["tasks"].values() if task.get("status") == "complete"}
            if supplied_worktree not in eligible:
                raise CogitoError("verification checks must run in a completed Package Slice worktree")
        else:
            raise CogitoError("controlled checks are not legal in the current state")
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        effective = materialize_contract(package, prior)
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
            evidence = run_check(package, check_id, supplied_worktree, prior)
            try:
                path = write_evidence_once(self.run_dir / "evidence", record_id, evidence)
            except EvidenceAlreadyExists as collision:
                path = collision.path
        recorded = _load_json(path)
        validate_check_evidence(recorded)
        if (recorded["check_id"] != check_id
                or recorded["run_id"] != package["run_id"]
                or recorded["check_hash"] != execution["check_hash"]
                or recorded["effective_contract_hash"] != execution["effective_contract_hash"]):
            raise CogitoError("controlled-check evidence does not match its recorded attempt")
        payload = {"check_id": check_id, "evidence_path": str(path), "evidence_hash": hash_json(recorded), "head_commit": recorded["head_commit"], "effective_contract_hash": recorded["effective_contract_hash"]}
        return self.record("check-evidence-recorded", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def enter_correction(self, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("correction-start")
        replay = self._replay(action_id, {"verification-correction-required", "post-verification-correction-required"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        events = read_events(self.events_path)
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
        payload = {"scope_within_contract": True, "amendment_id": amendment["id"], "effective_contract_hash": amendments[-1]["payload"]["effective_contract_hash"]}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def complete_correction(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("correction-complete", amendment_id=amendment_id, commit_id=commit_id)
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, {"technical-correction-complete", "post-integration-correction-complete"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        event = "technical-correction-complete" if current["state"] == "technical-correction" else "post-integration-correction-complete" if current["state"] == "post-integration-correction" else None
        if event is None:
            raise CogitoError("correction completion is not legal in the current state")
        started = [item for item in read_events(self.events_path) if item["type"] in {"verification-correction-required", "post-verification-correction-required"}]
        if not started or started[-1]["payload"].get("amendment_id") != amendment_id:
            raise CogitoError("correction completion does not match the amendment that opened this correction cycle")
        amendments = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        matching = [item for item in amendments if item["id"] == amendment_id]
        if len(matching) != 1:
            raise CogitoError("correction commit references an unknown Technical Amendment")
        if any(current["tasks"].get(task["id"], {}).get("status") != "complete" for task in matching[0].get("added_tasks", [])):
            raise CogitoError("correction cannot finish before amendment tasks complete")
        added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
        implementation_results = [item for item in current["agent_results"] if item.get("task_id") in added_ids and item.get("role") == "implementer" and item.get("status") == "complete"]
        if added_ids and (added_ids != {item.get("task_id") for item in implementation_results} or commit_id not in {item.get("head_commit") for item in implementation_results}):
            raise CogitoError("correction tasks require Gate-recorded Implementer Results")
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        message = self._git("show", "-s", "--format=%B", commit_id)
        if f"Cogito-Amendment: {amendment_id}" not in message:
            raise CogitoError("correction commit is missing the Cogito-Amendment trailer")
        package = self.approved_package()
        if current["state"] == "post-integration-correction" and (self._git("branch", "--show-current") != package["delivery_branch"] or self._git("rev-parse", "HEAD") != commit_id):
            raise CogitoError("post-integration correction commit must be current delivery HEAD")
        if not added_ids and commit_id != self._git("rev-parse", "HEAD"):
            raise CogitoError("a correction without added tasks must use current delivery HEAD")
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def enter_review_fix(self, action_id: str | None = None) -> dict[str, Any]:
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

    def complete_review_fix(self, amendment_id: str, commit_id: str, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("review-fix-complete", amendment_id=amendment_id, commit_id=commit_id)
        payload = {"scope_within_contract": True, "amendment_id": amendment_id, "commit_id": commit_id}
        replay = self._replay(action_id, "review-fix-complete", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "review-fix":
            raise CogitoError("review fix completion is not legal in the current state")
        started = [item for item in read_events(self.events_path) if item["type"] == "review-fix-required"]
        if not started:
            raise CogitoError("review fix has no recorded Reviewer finding")
        amendment_events = [item for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        matching_events = [item for item in amendment_events if item["payload"]["amendment"].get("id") == amendment_id and item["sequence"] > started[-1]["sequence"]]
        matching = [item["payload"]["amendment"] for item in matching_events]
        if len(matching) != 1:
            raise CogitoError("review fix requires a new Technical Amendment bound to the current finding")
        added_ids = {task["id"] for task in matching[0].get("added_tasks", [])}
        if not added_ids or any(current["tasks"].get(task_id, {}).get("status") != "complete" for task_id in added_ids):
            raise CogitoError("review fix requires completed amendment tasks")
        implementer_results = [item for item in current["agent_results"] if item.get("task_id") in added_ids and item.get("role") == "implementer" and item.get("status") == "complete"]
        if {item.get("task_id") for item in implementer_results} != added_ids or commit_id not in {item.get("head_commit") for item in implementer_results}:
            raise CogitoError("review fix commit is not bound to its Implementer Results")
        self._git("cat-file", "-e", f"{commit_id}^{{commit}}")
        if f"Cogito-Amendment: {amendment_id}" not in self._git("show", "-s", "--format=%B", commit_id):
            raise CogitoError("review fix commit is missing the Cogito-Amendment trailer")
        validate_transition(self.workflow, current["state"], "review-fix-complete", payload, current["counters"], current["limits"])
        return self.record("review-fix-complete", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def record_retry(self, kind: str, reason: str, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("retry", kind=kind, reason=reason)
        event = {"transient": "transient-retry", "format": "format-repair-recorded"}.get(kind)
        if event is None or not reason.strip():
            raise CogitoError("retry kind must be transient or format and include a reason")
        payload = {"reason": reason}
        replay = self._replay(action_id, event, request_hash)
        if replay is not None:
            return replay
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def complete_integration(self, commit_id: str, slice_id: str | None = None, action_id: str | None = None) -> dict[str, Any]:
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
        target_slice = slice_id or "mini-package"
        task_ids = [task_id for task_id, task in current["tasks"].items() if (task.get("slice_id") or "mini-package") == target_slice]
        if not task_ids or any(current["tasks"][task_id].get("status") != "reviewed" for task_id in task_ids):
            raise CogitoError("integration requires every task in the target Slice to be independently reviewed")
        latest_implementation = {item.get("task_id"): item for item in current["agent_results"] if item.get("role") == "implementer" and item.get("status") == "complete"}
        source_heads = []
        for task_id in task_ids:
            result = latest_implementation.get(task_id)
            if not result:
                raise CogitoError("integration is missing a Gate-recorded implementation Result")
            self._git("merge-base", "--is-ancestor", result["head_commit"], commit_id)
            source_heads.append(result["head_commit"])
        history = read_events(self.events_path)
        prior_integrations = [item for item in history if item["type"] in {"slice-integration-complete", "wave-integration-complete", "integration-complete"}]
        starts = [item for item in history if item["type"] == "start-gate-passed"]
        previous_head = prior_integrations[-1]["payload"]["commit_id"] if prior_integrations else starts[-1]["payload"]["delivery_head"]
        self._git("merge-base", "--is-ancestor", previous_head, commit_id)
        remaining_reviewed = any(task_id not in task_ids and task.get("status") == "reviewed" for task_id, task in current["tasks"].items())
        remaining_unintegrated = any(task_id not in task_ids and task.get("status") != "integrated" for task_id, task in current["tasks"].items())
        event = "slice-integration-complete" if remaining_reviewed else "wave-integration-complete" if remaining_unintegrated else "integration-complete"
        payload = {"commit_id": commit_id, "slice_id": target_slice, "task_ids": sorted(task_ids), "source_heads": sorted(source_heads), "previous_delivery_head": previous_head}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"], current["limits"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def add_amendment(self, amendment: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("amend", amendment=amendment)
        replay = self._replay(action_id, "technical-amendment-added", request_hash)
        if replay is not None:
            return replay
        package = self.approved_package()
        state = self.load()
        if state["state"] not in {"verifying", "reviewing", "review-fix", "post-integration-verification"}:
            raise CogitoError("Technical Amendments are only legal while handling a verification or review finding")
        prior = [item["payload"]["amendment"] for item in read_events(self.events_path) if item["type"] == "technical-amendment-added"]
        digest = effective_contract_hash(package, [*prior, amendment])
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

    def approve_package(self, draft: Mapping[str, Any], action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("approve", draft=draft)
        relative = Path("docs") / "cogito" / "packages" / f"{self.run_id}.json"
        target = self.root / relative
        replay = self._replay(action_id, "package-approved", request_hash)
        if replay is not None:
            try:
                target.chmod(0o444)
            except OSError as exc:
                raise CogitoError(
                    "Package approval is recorded, but its file could not be made read-only; "
                    "retry with the same action_id after resolving the storage error"
                ) from exc
            return replay
        package = json.loads(json.dumps(draft))
        if package.get("run_id") != self.run_id:
            raise CogitoError("package run_id does not match run")
        validate_package(package)
        self._validate_policy(package)
        digest = package_hash(package)
        package["package_hash"] = digest
        tasks = tasks_with_dependencies(package["execution_dag"])
        current = self.load()
        if current["state"] != "awaiting-package-approval":
            raise CogitoError("Package approval is not legal in the current state")
        if current.get("candidate_package_hash") != digest:
            raise CogitoError("approved Package differs from the Gate-validated candidate")
        graph_path = self.root / "docs" / "cogito" / "project-graph.json"
        graph_before = graph_path.read_bytes() if graph_path.exists() else None
        # Finish validation before publishing anything. Package creation is
        # exclusive, so rollback can distinguish our file from an existing one.
        graph = self._formalize_project_graph(package, graph_path)
        event_payload = {"approved": True, "package_path": relative.as_posix(), "package_hash": digest, "tasks": tasks, "max_workers": package["policy_snapshot"]["max_workers"], "project_graph_hash": hash_json(graph), "project_graph_snapshot": graph, "limits": package["limits"]}
        package_created = False
        graph_write_attempted = False
        try:
            package_created = atomic_create_json(target, package)
            if not package_created and package_hash(_load_json(target)) != digest:
                raise CogitoError("canonical immutable Package already exists with different content")
            graph_write_attempted = True
            atomic_write_json(graph_path, graph)
            state = self.record(
                "package-approved",
                event_payload,
                action_id, self._GATE_AUTHORITY, request_hash=request_hash,
            )
            target.chmod(0o444)
        except Exception as exc:
            # record() appends the authoritative event BEFORE refreshing the
            # cache. An exception does not imply that approval was rolled back.
            try:
                history = read_events(self.events_path)
                reduce_events(history, self.workflow)
                if (len(history) < current["sequence"]
                        or history[current["sequence"] - 1]["event_hash"] != current["last_event_hash"]):
                    raise CogitoError("event history no longer contains the pre-approval state")
            except Exception as history_error:
                raise CogitoError(
                    "cannot determine Package approval outcome; artifacts were preserved; "
                    "inspect event history before retrying"
                ) from history_error
            if any(item["type"] == "package-approved" for item in history):
                raise CogitoError(
                    "Package approval is recorded; artifacts were preserved, but follow-up "
                    "work failed; retry with the same action_id after resolving the error: "
                    f"{exc}"
                ) from exc
            self._rollback_uncommitted_approval(
                target, package_created, graph_path, graph_before,
                graph if graph_write_attempted else None,
            )
            raise CogitoError(f"Package approval was not recorded: {exc}") from exc
        return state

    def _rollback_uncommitted_approval(
        self, target: Path, package_created: bool, graph_path: Path,
        graph_before: bytes | None, attempted_graph: Mapping[str, Any] | None,
    ) -> None:
        """Undo our publication only after confirming no approval was recorded."""
        try:
            if attempted_graph is not None:
                actual = graph_path.read_bytes() if graph_path.exists() else None
                if actual != graph_before:
                    # Do not overwrite an unrelated replacement during recovery.
                    if actual is None or json.loads(actual) != attempted_graph:
                        raise CogitoError("Project Graph changed during approval recovery")
                    if graph_before is None:
                        graph_path.unlink()
                    else:
                        graph_path.write_bytes(graph_before)
            if package_created:
                target.unlink()
        except (OSError, ValueError) as exc:
            raise CogitoError(
                f"Package approval was not recorded, but cleanup is incomplete; inspect artifacts: {exc}"
            ) from exc

    def start_gate(self, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("start")
        replay = self._replay(action_id, "start-gate-passed", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "start-gate":
            raise CogitoError("Start Gate is not legal in the current state")
        package = self.approved_package()
        self._validate_policy(package)
        head = self._git("rev-parse", "HEAD")
        self._git("cat-file", "-e", f"{package['baseline_commit']}^{{commit}}")
        if self._git("branch", "--show-current") != package["delivery_branch"]:
            raise CogitoError("Start Gate is not on the Package delivery branch")
        self._git("merge-base", "--is-ancestor", package["baseline_commit"], head)
        allowed_control = {self.load()["package_path"], "docs/cogito/project-graph.json"}
        for item in package["slices"]:
            for document in (item["spec"], item["plan"]):
                self._validate_content_hash(document["path"], document["hash"])
                allowed_control.add(document["path"])
        for source in package["source_registry"]:
            self._validate_content_hash(source["path"], source["hash"])
            if source["disposition"] in {"adopted", "updated"}:
                allowed_control.add(source["path"])
        graph = _load_json(self.root / "docs" / "cogito" / "project-graph.json")
        validate_project_graph(graph)
        if hash_json(graph) != current.get("project_graph_hash") or graph.get("active_run_id") != self.run_id or any(item["id"] not in graph.get("slices", {}) for item in package["slices"]):
            raise CogitoError("Project Graph is not formalized for this Package")
        dirty = []
        for line in self._git("status", "--porcelain", "--untracked-files=all").splitlines():
            path = line[3:].split(" -> ")[-1] if len(line) > 3 else ""
            if not path.startswith(".cogito/") and path not in allowed_control:
                dirty.append(line)
        if dirty:
            raise CogitoError("Start Gate requires a clean delivery checkout")
        payload = {
            "baseline_valid": True, "contract_valid": True, "worktrees_valid": self._worker_layout_valid(package),
            "delivery_head": head, "package_hash": package_hash(package),
        }
        validate_transition(self.workflow, current["state"], "start-gate-passed", payload, current["counters"])
        return self.record("start-gate-passed", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def decide_post_verification(self, passed_evidence: Sequence[Mapping[str, Any]], reviewer_escalation: bool = False, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("post-verify", evidence=passed_evidence, reviewer_escalation=reviewer_escalation)
        replay = self._replay(action_id, {"human-review-required", "auto-accept-ready"}, request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "post-integration-verification":
            raise CogitoError("post-verification decision is not legal in the current state")
        package = self.approved_package()
        self._validate_evidence(package, passed_evidence, require_current_head=True)
        human = package["human_gate"]
        human_required = bool(reviewer_escalation or human.get("high_risk_hotspots") or any(item["applicable"] for item in human["predicates"]))
        event = "human-review-required" if human_required else "auto-accept-ready"
        payload = {"passed": True, "human_required": human_required, "evidence": [item["evidence_path"] for item in passed_evidence], "reviewer_escalation": bool(reviewer_escalation), "delivery_head": self._git("rev-parse", "HEAD")}
        validate_transition(self.workflow, current["state"], event, payload, current["counters"])
        return self.record(event, payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def resume_gate(self, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("resume")
        replay = self._replay(action_id, "resume", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        if current["state"] != "blocked" or not current.get("blocked_from"):
            raise CogitoError("only a blocked run with a recorded origin may resume")
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
                if task.get("status") in {"leased", "running"}:
                    worktree = Path(str(task.get("worktree", "")))
                    if not worktree.is_dir() or self._git_at(worktree, "branch", "--show-current") != task.get("branch"):
                        raise CogitoError("Resume Gate found a drifted active worker lease")
                    worker_head = self._git_at(worktree, "rev-parse", "HEAD")
                    self._git("merge-base", "--is-ancestor", task.get("base_commit"), worker_head)
                    recorded = [item for item in current["agent_results"] if item.get("task_id") == task.get("id")]
                    if recorded and worker_head != recorded[-1].get("head_commit"):
                        raise CogitoError("Resume Gate worker HEAD differs from its recorded Result")
            for evidence_path, ledger in current.get("evidence", {}).items():
                evidence = _load_json(Path(evidence_path))
                if hash_json(evidence) != ledger.get("evidence_hash"):
                    raise CogitoError("Resume Gate found tampered evidence")
        reconciliation = hash_json({"target": target, "head": self._git("rev-parse", "HEAD"), "event_hash": current["last_event_hash"]})
        return self.record("resume", {"target": target, "validated": True, "reconciliation_hash": reconciliation}, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def approve_human_gate(self, action_id: str | None = None) -> dict[str, Any]:
        request_hash = request_fingerprint("human-approve")
        replay = self._replay(action_id, "human-approved", request_hash)
        if replay is not None:
            return replay
        current = self.load()
        payload = {"approved": True}
        validate_transition(self.workflow, current["state"], "human-approved", payload, current["counters"])
        return self.record("human-approved", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def finalize(self, result_path: str, project_graph_path: str, final_commit: str, action_id: str | None = None) -> dict[str, Any]:
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
            load_events=lambda: read_events(self.events_path),
            result_path=result_path,
            project_graph_path=project_graph_path,
            final_commit=final_commit,
            git=self._git,
        )
        validate_transition(self.workflow, current["state"], "finalization-complete", payload, current["counters"])
        return self.record("finalization-complete", payload, action_id, self._GATE_AUTHORITY, request_hash=request_hash)

    def completion_report(self) -> dict[str, Any]:
        return self._load_completion_report(self.load())

    def _load_completion_report(self, current: Mapping[str, Any]) -> dict[str, Any]:
        """Read the Result from the recorded final commit, never the working copy."""
        if current["state"] != "accepted":
            raise CogitoError("completion report is only available for an accepted run")
        final_events = [item for item in read_events(self.events_path) if item["type"] == "finalization-complete"]
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

    def _replay(self, action_id: str | None, event_type: str | set[str], request_hash: str) -> dict[str, Any] | None:
        if not action_id:
            return None
        pending = self.run_dir / "check-actions" / hash_json(action_id) / "request.json"
        if pending.exists():
            require_same_request(_load_json(pending), request_hash, action_id)
        if not self.events_path.exists():
            return None
        expected = {event_type} if isinstance(event_type, str) else event_type
        matches = [item for item in read_events(self.events_path) if item.get("action_id") == action_id]
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

    def _formalize_project_graph(self, package: Mapping[str, Any], path: Path) -> dict[str, Any]:
        existing = _load_json(path) if path.exists() else None
        return formalize_project_graph(existing, package, self.run_id)

    def _validate_policy(self, package: Mapping[str, Any]) -> None:
        validate_gate_policy(self.root, package)

    def _validate_evidence(self, package: Mapping[str, Any], evidence: Sequence[Mapping[str, Any]], require_current_head: bool = False) -> None:
        events = read_events(self.events_path)
        load_current_head = (
            (lambda: self._git("rev-parse", "HEAD")) if require_current_head else None
        )
        validate_gate_evidence(
            package, evidence, events, self.load, self.run_dir, load_current_head
        )

    def next_action(self) -> dict[str, Any]:
        projection = self.load()
        output = derive_next_action(projection)
        if projection["state"] == "accepted":
            output["report"] = self._load_completion_report(projection)
        return output
