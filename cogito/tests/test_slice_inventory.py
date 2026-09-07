"""Read-only accepted Slice inventory behavior."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, hash_json
from cogito_contracts import materialize_contract_with_limits, package_hash
from cogito_delivery_summary import build_delivery_summary
from cogito_event_repository import EventSnapshot
from cogito_events import append_event
from cogito_slice_inventory import build_slice_inventory
from cogito_slice_inventory_rules import MAX_SLICE_INVENTORY_BYTES, build_inventory_view
from cogito_test_support import atomic_package, minimal_package
from cogito_workflow import load_workflow


class ReadOnlyEventRepository:
    def __init__(
        self, snapshot: EventSnapshot, *, exists: bool = True,
        snapshot_error: CogitoError | None = None,
    ):
        self.value = snapshot
        self.exists_value = exists
        self.snapshot_error = snapshot_error
        self.calls: list[str] = []

    def exists(self) -> bool:
        self.calls.append("exists")
        return self.exists_value

    def snapshot(self) -> EventSnapshot:
        self.calls.append("snapshot")
        if self.snapshot_error is not None:
            raise self.snapshot_error
        return self.value

    def read(self) -> list[dict]:
        self.calls.append("read")
        return self.value.events


class ReadOnlyGitRepository:
    def __init__(self, blobs: dict[tuple[str, str], bytes], final_tree: str, changed: list[str]):
        self.blobs = blobs
        self.final_tree = final_tree
        self.changed = changed
        self.calls: list[tuple[str, ...]] = []

    def read_blob(self, commit_id: str, path: str) -> bytes:
        self.calls.append(("read_blob", commit_id, path))
        return self.blobs[(commit_id, path)]

    def run(self, *args: str) -> str:
        self.calls.append(args)
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:1] == ("rev-parse",):
            return self.final_tree
        if args[:2] == ("diff", "--name-only"):
            return "\0".join([*self.changed, ""])
        raise AssertionError(f"unexpected Git query: {args}")


class SliceInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load_workflow()
        self.package = atomic_package(minimal_package())
        self.package["package_hash"] = package_hash(self.package)
        self.amendment = {
            "id": "TA-1",
            "reason": "include the shared mapper found during implementation",
            "path_additions": [{
                "task_id": "T-1",
                "paths": ["shared/mapper.py"],
                "reason": "required response mapping",
                "check_ids": ["C-2"],
            }],
            "added_checks": [{
                "id": "C-2", "phase": "task", "argv": ["python3", "-V"],
                "required": True,
            }],
        }
        self.second_amendment = {
            "id": "TA-2",
            "reason": "add a focused regression task",
            "added_tasks": [{
                "id": "T-2", "slice_id": "FS-001", "paths": ["tests/regression.py"],
                "depends_on": ["T-1"], "responsibility": "Cover the regression",
                "check_ids": ["C-3"],
            }],
            "added_checks": [{
                "id": "C-3", "phase": "task", "argv": ["python3", "-V"],
                "required": True,
            }],
        }
        self.effective = materialize_contract_with_limits(
            self.package, [self.amendment, self.second_amendment], self.workflow["limits"],
        )
        self.final_commit = "f" * 40
        self.delivery_head = "d" * 40
        self.final_tree = "e" * 40
        self.package_path = f"docs/cogito/packages/{self.package['run_id']}.json"
        self.result_path = f"docs/cogito/results/{self.package['run_id']}.json"
        self.result = {
            "schema_version": "3.0",
            "run_id": self.package["run_id"],
            "status": "accepted",
            "package_hash": package_hash(self.package),
            "effective_contract_hash": self.effective["effective_contract_hash"],
            "integration_commits": ["c" * 40],
            "slice_dispositions": {"FS-001": "accepted"},
            "checks": [],
            "reviews": [],
            "amendments": [
                {"id": "TA-1", "proposal_hash": "a" * 64},
                {"id": "TA-2", "commit_id": "b" * 40},
            ],
            "human_gate": {"required": False, "outcome": "not-required"},
            "remaining_risks": [],
        }
        self.events = [
            {"sequence": 2, "type": "start-gate-passed", "payload": {
                "delivery_head": self.delivery_head,
            }},
            {"sequence": 7, "type": "technical-amendment-added", "payload": {
                "amendment": self.amendment,
                "effective_contract_hash": "1" * 64,
            }},
            {"sequence": 8, "type": "technical-amendment-added", "payload": {
                "amendment": self.second_amendment,
                "effective_contract_hash": self.effective["effective_contract_hash"],
            }},
            {"sequence": 12, "type": "finalization-complete", "payload": {
                "final_commit": self.final_commit,
                "final_tree": self.final_tree,
                "result_path": self.result_path,
                "project_graph_path": "docs/cogito/project-graph.json",
            }},
        ]
        self.state = {
            "run_id": self.package["run_id"],
            "state": "accepted",
            "package_path": self.package_path,
            "package_hash": package_hash(self.package),
            "effective_contract_hash": self.effective["effective_contract_hash"],
            "agent_results": [
                {
                    "task_id": "T-1", "agent_id": "worker-1", "role": "implementer",
                    "status": "complete", "base_commit": "a" * 40,
                    "head_commit": "b" * 40,
                    "changed_paths": ["src/handler.py", "shared/mapper.py"],
                },
                {
                    "task_id": "T-1", "agent_id": "reviewer-1", "role": "reviewer",
                    "status": "complete", "base_commit": "b" * 40,
                    "head_commit": "b" * 40, "changed_paths": ["review-notes.md"],
                },
                {
                    "task_id": "T-2", "agent_id": "worker-2", "role": "implementer",
                    "status": "complete", "base_commit": "b" * 40,
                    "head_commit": "c" * 40,
                    "changed_paths": ["shared/mapper.py", "tests/regression.py"],
                },
            ],
        }

    def inventory(self, *, state: dict | None = None, result: dict | None = None):
        snapshot = EventSnapshot(self.events, state or self.state)  # type: ignore[arg-type]
        ledger = ReadOnlyEventRepository(snapshot)
        git = ReadOnlyGitRepository({
            (self.final_commit, self.package_path): json.dumps(self.package).encode(),
            (self.final_commit, self.result_path): json.dumps(result or self.result).encode(),
        }, self.final_tree, [
            "src/handler.py", "shared/mapper.py", self.result_path,
            "docs/cogito/project-graph.json",
        ])
        value = build_slice_inventory(
            Path("/does/not/need/to/exist"), self.package["run_id"], "FS-001",
            workflow=self.workflow, event_repository=ledger, git_repository=git,
        )
        return value, ledger, git

    def test_inventory_separates_frozen_amendment_and_committed_facts(self) -> None:
        before = copy.deepcopy((
            self.package, self.amendment, self.second_amendment,
            self.events, self.state, self.result,
        ))
        value, ledger, git = self.inventory()

        self.assertEqual(value["source"]["package_hash"], package_hash(self.package))
        self.assertEqual(value["package_references"]["spec"], self.package["slices"][0]["spec"])
        self.assertEqual(value["paths"]["frozen_approved"], ["src/**", "tests/**"])
        self.assertEqual(
            value["paths"]["implementer_reported"],
            ["src/handler.py", "shared/mapper.py", "tests/regression.py"],
        )
        self.assertEqual(
            value["paths"]["start_to_final"], [
                "src/handler.py", "shared/mapper.py", self.result_path,
                "docs/cogito/project-graph.json",
            ],
        )
        self.assertEqual([item["event_sequence"] for item in value["amendments"]], [7, 8])
        self.assertEqual(value["amendments"][0]["path_additions"], self.amendment["path_additions"])
        self.assertEqual(value["amendments"][1]["added_tasks"], self.second_amendment["added_tasks"])
        self.assertEqual(len(value["implementer_results"]), 2)
        self.assertNotIn("review-notes.md", str(value["implementer_results"]))
        self.assertEqual(ledger.calls, ["exists", "snapshot"])
        self.assertTrue(all(call[0] in {"read_blob", "merge-base", "rev-parse", "diff"} for call in git.calls))
        self.assertEqual((
            self.package, self.amendment, self.second_amendment,
            self.events, self.state, self.result,
        ), before)

    def test_nonaccepted_or_mismatched_hashes_fail_closed(self) -> None:
        with self.subTest("nonaccepted"), self.assertRaisesRegex(CogitoError, "accepted run"):
            self.inventory(state={**self.state, "state": "finalizing"})
        with self.subTest("effective hash"), self.assertRaisesRegex(CogitoError, "hashes do not match"):
            self.inventory(result={**self.result, "effective_contract_hash": "0" * 64})

    def test_unknown_or_additional_slice_is_rejected(self) -> None:
        with self.assertRaisesRegex(CogitoError, "does not match accepted Slice FS-001"):
            build_slice_inventory(
                "/unused", self.package["run_id"], "FS-999",
                workflow=self.workflow,
                event_repository=ReadOnlyEventRepository(EventSnapshot(self.events, self.state)),  # type: ignore[arg-type]
                git_repository=ReadOnlyGitRepository({
                    (self.final_commit, self.package_path): json.dumps(self.package).encode(),
                    (self.final_commit, self.result_path): json.dumps(self.result).encode(),
                }, self.final_tree, []),
            )

        multi = copy.deepcopy(self.package)
        multi["approved_paths"].append("other/**")
        multi["slices"].append({
            "id": "FS-002", "type": "feature",
            "spec": {"path": "docs/other-spec.md", "hash": "1" * 64},
            "plan": {"path": "docs/other-plan.md", "hash": "2" * 64},
            "worker": {
                "branch": "codex/fs-002", "worktree": ".cogito/worktrees/FS-002",
                "allowed_paths": ["other/**"],
            },
        })
        multi["package_hash"] = package_hash(multi)
        effective = materialize_contract_with_limits(
            multi, [self.amendment, self.second_amendment], self.workflow["limits"],
        )
        state = {
            **self.state,
            "package_hash": package_hash(multi),
            "effective_contract_hash": effective["effective_contract_hash"],
        }
        result = {
            **self.result,
            "package_hash": package_hash(multi),
            "effective_contract_hash": effective["effective_contract_hash"],
            "slice_dispositions": {"FS-001": "accepted", "FS-002": "accepted"},
        }
        with self.assertRaisesRegex(CogitoError, "single-Slice Package"):
            build_slice_inventory(
                "/unused", multi["run_id"], "FS-001", workflow=self.workflow,
                event_repository=ReadOnlyEventRepository(EventSnapshot(self.events, state)),  # type: ignore[arg-type]
                git_repository=ReadOnlyGitRepository({
                    (self.final_commit, self.package_path): json.dumps(multi).encode(),
                    (self.final_commit, self.result_path): json.dumps(result).encode(),
                }, self.final_tree, []),
            )

    def test_missing_run_stops_before_projection(self) -> None:
        ledger = ReadOnlyEventRepository(EventSnapshot([], self.state), exists=False)  # type: ignore[arg-type]
        with self.assertRaisesRegex(CogitoError, "does not exist"):
            build_slice_inventory(
                "/unused", self.package["run_id"], "FS-001",
                workflow=self.workflow, event_repository=ledger,
                git_repository=ReadOnlyGitRepository({}, self.final_tree, []),
            )
        self.assertEqual(ledger.calls, ["exists"])

    def test_view_has_a_fixed_output_limit(self) -> None:
        oversized = copy.deepcopy(self.package)
        oversized["source_registry"] = [{
            "path": "docs/source.md", "hash": "a" * 64,
            "relevance": "x" * MAX_SLICE_INVENTORY_BYTES,
            "disposition": "read-only-source",
        }]
        with self.assertRaisesRegex(CogitoError, "exceeds"):
            build_inventory_view(
                package=oversized,
                result=self.result,
                effective_contract={**oversized, "effective_contract_hash": "a" * 64},
                agent_results=[],
                amendments=[], slice_id="FS-001", final_commit=self.final_commit,
                package_path=self.package_path, result_path=self.result_path,
                committed_paths=[],
            )

    def test_default_event_repository_does_not_touch_state_cache_or_create_lock(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / ".cogito" / "runs" / self.package["run_id"]
            state_path = run_dir / "state.json"
            events_path = run_dir / "events.jsonl"
            run_dir.mkdir(parents=True)
            for event in self.events:
                append_event(events_path, {"type": event["type"], "payload": event["payload"]})
            lock_path = events_path.with_suffix(".jsonl.lock")
            lock_path.unlink()
            state_path.write_text('{"stale":true}\n')
            before = state_path.read_bytes()
            git = ReadOnlyGitRepository({
                (self.final_commit, self.package_path): json.dumps(self.package).encode(),
                (self.final_commit, self.result_path): json.dumps(self.result).encode(),
            }, self.final_tree, [])
            with mock.patch("cogito_event_repository.project_events", return_value=self.state):
                build_slice_inventory(
                    root, self.package["run_id"], "FS-001", workflow=self.workflow,
                    git_repository=git,
                )
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse(lock_path.exists())
            state_path.unlink()
            with mock.patch("cogito_event_repository.project_events", return_value=self.state):
                build_slice_inventory(
                    root, self.package["run_id"], "FS-001", workflow=self.workflow,
                    git_repository=git,
                )
            self.assertFalse(state_path.exists())
            self.assertFalse(lock_path.exists())

    def test_historical_resolution_flows_through_the_complete_query(self) -> None:
        request_hash = "a" * 64
        evidence_hash = "b" * 64
        evidence_path = "/historical/evidence.json"
        replacement = {
            "sequence": 5, "type": "check-evidence-recorded",
            "action_id": "replacement", "request_hash": request_hash,
            "payload": {
                "check_id": "C-1", "evidence_path": evidence_path,
                "evidence_hash": evidence_hash,
                "effective_contract_hash": self.effective["effective_contract_hash"],
            },
        }
        resolution_payload = {
            "interrupted_action_id": "interrupted",
            "replacement_action_id": "replacement",
            "resolver_id": "user:reviewer", "reason": "verified quiescent",
            "request_hash": request_hash, "check_id": "C-1",
            "evidence_path": evidence_path, "evidence_hash": evidence_hash,
            "check_hash": hash_json(self.package["checks"][0]),
            "effective_contract_hash": self.effective["effective_contract_hash"],
        }
        resolution = {
            "sequence": 6, "type": "controlled-check-attempt-resolved",
            "payload": resolution_payload,
        }
        events = [
            self.events[0], replacement, resolution,
            {**self.events[1], "sequence": 7},
            {**self.events[2], "sequence": 8},
            self.events[3],
        ]
        filtered = [item for item in events if item is not resolution]
        result = copy.deepcopy(self.result)
        result["delivery_summary"] = build_delivery_summary(self.state, filtered)
        result["delivery_summary"]["verification"].append({
            "event_sequence": 6,
            "event": "controlled-check-attempt-resolved",
            **resolution_payload,
        })
        ledger = ReadOnlyEventRepository(
            EventSnapshot(events, self.state),  # type: ignore[arg-type]
            snapshot_error=CogitoError("unsupported historical event"),
        )
        git = ReadOnlyGitRepository({
            (self.final_commit, self.package_path): json.dumps(self.package).encode(),
            (self.final_commit, self.result_path): json.dumps(result).encode(),
        }, self.final_tree, ["src/handler.py"])
        state_before = {
            **self.state, "state": "executing",
            "effective_contract_hash": self.effective["effective_contract_hash"],
        }
        with mock.patch(
            "cogito_slice_inventory_compat.project_events",
            side_effect=[state_before, self.state],
        ):
            inventory = build_slice_inventory(
                "/unused", self.package["run_id"], "FS-001",
                workflow=self.workflow, event_repository=ledger, git_repository=git,
            )
        self.assertEqual(inventory["source"]["slice_id"], "FS-001")
        self.assertEqual(ledger.calls, ["exists", "snapshot", "read"])


if __name__ == "__main__":
    unittest.main()
