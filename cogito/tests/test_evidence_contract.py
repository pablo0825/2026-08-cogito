"""Behavioral contract for controlled-check Evidence shape and consistency."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cogito_common import CogitoError
from cogito_evidence_contract import REQUIRED_FIELDS, validate_check_evidence
from cogito_runner import write_evidence_once


def valid_evidence() -> dict:
    snapshot = "a" * 64
    return {
        "schema_version": "3.0",
        "run_id": "DEV-evidence-001",
        "check_id": "C-1",
        "status": "passed",
        "passed": True,
        "exit_code": 0,
        "timed_out": False,
        "output_limit_exceeded": False,
        "termination_degraded": False,
        "output_limit_bytes": 10 * 1024 * 1024,
        "stdout_bytes": 3,
        "stderr_bytes": 0,
        "duration_seconds": 0.1,
        "started_at": "2026-09-02T00:00:00+00:00",
        "head_commit": "b" * 40,
        "tree_hash": snapshot,
        "worktree_snapshot_hash": snapshot,
        "pre_worktree_snapshot_hash": snapshot,
        "post_worktree_snapshot_hash": snapshot,
        "worktree_changed_during_check": False,
        "worktree_binding": {},
        "check_hash": "c" * 64,
        "effective_contract_hash": "d" * 64,
        "argv": ["python3", "-V"],
        "cwd": ".",
        "stdout": "ok\n",
        "stderr": "",
        "truncated": False,
        "evidence_path": "/tmp/C-1.json",
    }


class CheckEvidenceContractTests(unittest.TestCase):
    def test_valid_record_is_accepted(self) -> None:
        self.assertIsNone(validate_check_evidence(valid_evidence()))

    def test_every_required_field_is_enforced(self) -> None:
        for field in REQUIRED_FIELDS:
            with self.subTest(field=field):
                value = valid_evidence()
                del value[field]
                with self.assertRaisesRegex(CogitoError, "missing fields"):
                    validate_check_evidence(value)

    def test_unknown_fields_are_rejected(self) -> None:
        value = valid_evidence()
        value["agent_claimed_pass"] = True
        with self.assertRaisesRegex(CogitoError, "unknown fields"):
            validate_check_evidence(value)

    def test_field_types_formats_and_ranges_are_enforced(self) -> None:
        invalid = {
            "schema_version": "4.0",
            "run_id": "unsafe/run",
            "check_id": "../escape",
            "status": "banana",
            "passed": 1,
            "exit_code": True,
            "output_limit_bytes": 100,
            "stdout_bytes": -1,
            "stderr_bytes": False,
            "duration_seconds": float("nan"),
            "started_at": "",
            "head_commit": 1234567,
            "tree_hash": "not-a-hash",
            "worktree_binding": [],
            "argv": [],
            "cwd": None,
            "stdout": b"bytes",
            "truncated": "false",
            "evidence_path": "",
        }
        for field, replacement in invalid.items():
            with self.subTest(field=field):
                value = valid_evidence()
                value[field] = replacement
                with self.assertRaises(CogitoError):
                    validate_check_evidence(value)

    def test_internal_execution_consistency_is_enforced(self) -> None:
        mutations = [
            {"status": "failed"},
            {"exit_code": 1},
            {"timed_out": True},
            {"output_limit_exceeded": True},
            {"termination_degraded": True},
            {"worktree_changed_during_check": True},
            {"post_worktree_snapshot_hash": "e" * 64},
            {"worktree_snapshot_hash": "e" * 64},
            {"tree_hash": "e" * 64},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                value = valid_evidence()
                value.update(mutation)
                with self.assertRaises(CogitoError):
                    validate_check_evidence(value)

    def test_runner_does_not_publish_invalid_evidence(self) -> None:
        draft = valid_evidence()
        del draft["evidence_path"]
        draft["status"] = "banana"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            with self.assertRaisesRegex(CogitoError, "status must be passed or failed"):
                write_evidence_once(target, "C-1", draft)
            self.assertFalse((target / "C-1.json").exists())
            self.assertEqual(list(target.glob(".C-1.json.*")), [])


if __name__ == "__main__":
    unittest.main()
