#!/usr/bin/env python3
"""Reproduce replanning limits through public CLI in temporary Git repositories.

Synthetic Package approval is used only in the disposable test fixture.
Run from any directory: python3 /absolute/path/to/contract-probe.py
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPORT = Path(__file__).resolve().parent
COGITO = REPORT.parents[2]
sys.path.insert(0, str(COGITO / "tests"))
from test_feature_multitask import FeatureMultitaskTests


def main():
    tempfile.tempdir = "/tmp"
    fixture = FeatureMultitaskTests()
    fixture.setUp()
    observations = []
    try:
        repo, worktree, store, ranges = fixture.fixture(cli=True)
        canonical = repo / f"docs/cogito/packages/{store.run_id}.json"
        approved_bytes = canonical.read_bytes()
        original = store.approved_package()
        assert store.load()["state"] == "reviewing"
        # Record an actual accepted review of one task before the change finding.
        store.submit_agent_result(fixture.result(store, "T-1", *ranges[0]))

        def call(label, command, args=(), *, expect_error=None, expected_state=None):
            before_events = store.events_path.read_bytes()
            process = subprocess.run(
                [sys.executable, "-B", str(COGITO / "scripts/cogito_gate.py"),
                 "--repo", str(repo), command, "--run-id", store.run_id,
                 *map(str, args), "--action-id", f"probe-{len(observations)+1}"],
                capture_output=True, text=True, timeout=30,
            )
            observation = {"case": label, "command": command, "arguments": list(map(str, args)),
                           "returncode": process.returncode, "stderr": process.stderr.strip()}
            if expect_error is not None:
                assert process.returncode != 0, observation
                assert expect_error in process.stderr, observation
                assert store.events_path.read_bytes() == before_events, observation
                assert canonical.read_bytes() == approved_bytes, observation
                observation["no_event_or_package_mutation"] = True
            else:
                assert process.returncode == 0, observation
                data = json.loads(process.stdout)["data"]
                observation["state"] = data["state"]
                observation["package_hash"] = data.get("package_hash")
                observation["effective_contract_hash"] = data.get("effective_contract_hash")
                if expected_state:
                    assert data["state"] == expected_state, observation
            observations.append(observation)
            print(json.dumps(observation, ensure_ascii=False), flush=True)

        def input_file(label, value):
            path = repo / ".cogito" / f"probe-{label}.json"
            path.write_text(json.dumps(value))
            return path

        revised = copy.deepcopy(original)
        revised.pop("package_hash", None)
        revised["approved_paths"].append("shared/**")
        revised_path = input_file("revised", revised)
        call("approved_package_cannot_prepare_new_candidate", "prepare-package",
             ["--package", revised_path], expect_error="Package preparation is not legal")
        call("user_consent_cannot_reapprove_new_package_in_reviewing", "approve",
             ["--package", revised_path], expect_error="Package approval is not legal")
        call("cannot_return_to_shared_understanding", "transition",
             ["--event", "shared-understanding-ready", "--payload-json",
              json.dumps({"shared_understanding_hash": "e" * 64})], expect_error="is not legal from state")
        call("cannot_repeat_boundary_gate", "transition",
             ["--event", "boundary-complete", "--payload-json", json.dumps(original["boundary"])],
             expect_error="is not legal from state")
        for label, amendment, error in [
            ("amendment_cannot_expand_approved_paths", {"id": "TA-wide", "reason": "new shared API path",
                "approved_paths": ["shared/**"], "path_fixes": ["shared/api.py"]}, "forbidden changes"),
            ("amendment_outside_path_fix_rejected", {"id": "TA-path", "reason": "new shared API path",
                "path_fixes": ["shared/api.py"]}, "must stay within approved paths"),
            ("amendment_outside_task_rejected", {"id": "TA-task", "reason": "new shared API task",
                "added_tasks": [{"id": "T-3", "slice_id": "FS-1", "paths": ["shared/api.py"]}]},
                "must stay within approved paths"),
            ("amendment_cannot_replace_boundary", {"id": "TA-boundary", "reason": "new boundary",
                "boundary": {"decision": "split-required", "evidence": ["shared API change"]},
                "path_fixes": ["src/a.txt"]}, "forbidden changes"),
        ]:
            call(label, "amend", ["--amendment", input_file(label, amendment)], expect_error=error)

        before_block = store.load()
        call("block_on_contract_change", "transition", ["--event", "block", "--payload-json",
             json.dumps({"reason": "C needs a new shared API contract; user decision required"})],
             expected_state="blocked")
        blocked = store.load()
        assert blocked["blocked_from"] == "reviewing"
        for key in ("tasks", "agent_results", "evidence", "package_hash", "effective_contract_hash"):
            assert blocked[key] == before_block[key], key
        observations.append({"case": "block_preserves_completed_work_reviews_and_evidence",
                             "preserved": ["tasks", "agent_results", "evidence", "package_hash", "effective_contract_hash"],
                             "blocked_from": blocked["blocked_from"]})
        call("blocked_cannot_prepare", "prepare-package", ["--package", revised_path],
             expect_error="Package preparation is not legal")
        call("blocked_cannot_update_task", "task", ["--task-id", "T-2", "--status", "blocked", "--agent-id", "slice-worker"],
             expect_error="task updates are not legal")
        call("resume_does_not_accept_target_argument", "resume", ["--target", "package-preparing"],
             expect_error="unrecognized arguments")
        call("generic_transition_cannot_forge_resume_target", "transition", ["--event", "resume", "--payload-json",
             json.dumps({"target": "package-preparing", "validated": True})], expect_error="dedicated Gate operation")
        call("resume_returns_to_original_reviewing", "resume", expected_state="reviewing")
        assert store.load()["package_hash"] == before_block["package_hash"]

        # This is deliberately policy-invalid text. The runtime sees an allowed
        # path_fixes overlay, not the public API/data-model semantics in reason.
        semantic = {"id": "TA-semantic-probe", "reason": "Change public API output from list to object and replace data model",
                    "path_fixes": ["src/a.txt"]}
        call("in_scope_path_with_api_change_reason_is_not_semantically_rejected", "amend",
             ["--amendment", input_file("semantic", semantic)], expected_state="reviewing")
        assert canonical.read_bytes() == approved_bytes
        assert store.load()["effective_contract_hash"] != before_block["effective_contract_hash"]
        (REPORT / "contract-events.jsonl").write_bytes(store.events_path.read_bytes())
        (REPORT / "contract-summary.json").write_text(json.dumps({
            "source_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=COGITO, text=True).strip(),
            "fixture": "Real CLI Feature fixture, 2 completed serial tasks in 1 Slice; formal controlled verification and 1 task review",
            "temp_repo": str(repo), "observations": observations, "passed": True,
            "scope": "No product changes, no real project approval; disposable synthetic approvals only.",
        }, ensure_ascii=False, indent=2) + "\n")
        print(f"PASS: {len(observations)} contract observations", flush=True)
    finally:
        fixture.doCleanups()


if __name__ == "__main__":
    main()
