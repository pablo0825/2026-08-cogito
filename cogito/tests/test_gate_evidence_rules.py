"""Gate evidence decisions use collected data and an explicit verification phase."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, hash_json
from cogito_gate_validation import validate_evidence


def evidence_for(check: dict, contract_hash: str) -> dict:
    binding = {"head_commit": "b" * 40, "content_tree": "c" * 40}
    snapshot = hash_json(binding)
    return {
        "schema_version": "3.0", "run_id": "DEV-evidence-rules",
        "check_id": check["id"], "status": "passed", "passed": True,
        "exit_code": 0, "timed_out": False, "output_limit_exceeded": False,
        "termination_degraded": False, "output_limit_bytes": 10 * 1024 * 1024,
        "stdout_bytes": 3, "stderr_bytes": 0, "duration_seconds": 0.1,
        "started_at": "2026-09-02T00:00:00+00:00", "head_commit": "b" * 40,
        "tree_hash": snapshot, "worktree_snapshot_hash": snapshot,
        "pre_worktree_snapshot_hash": snapshot, "post_worktree_snapshot_hash": snapshot,
        "worktree_changed_during_check": False,
        "worktree_binding": {**binding, "snapshot_hash": snapshot},
        "check_hash": hash_json(check), "effective_contract_hash": contract_hash,
        "argv": check["argv"], "cwd": ".", "stdout": "ok\n", "stderr": "",
        "truncated": False, "evidence_path": f"collected/./{check['id']}.json",
    }


class GateEvidenceRulesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.package = {"policy_snapshot": {}}
        self.effective = {
            "checks": [
                {"id": "C-1", "argv": ["python3", "-V"]},
                {"id": "C-2", "argv": ["python3", "-V"], "required": True},
                {"id": "C-optional", "argv": ["python3", "-V"], "required": False},
            ],
            "effective_contract_hash": "d" * 64,
        }
        self.evidence = [
            evidence_for(check, self.effective["effective_contract_hash"])
            for check in self.effective["checks"][:2]
        ]
        self.events = [{"type": "implementation-complete", "sequence": 10}]
        self.recorded: dict = {}
        self.ledger: dict = {}
        self.collect()

    def collect(self, sequence: int = 11) -> None:
        for item in self.evidence:
            path = item["evidence_path"]
            self.recorded[path] = copy.deepcopy(item)
            self.ledger[path] = {
                "check_id": item["check_id"], "evidence_hash": hash_json(item),
                "event_sequence": sequence,
            }

    def validate(self, phase: str = "implementation", current_head: str | None = None) -> None:
        validate_evidence(
            self.package, self.evidence, self.events, self.ledger, self.recorded,
            effective_contract=self.effective, phase=phase, current_head=current_head,
        )

    def test_multiple_checks_use_original_keys_without_io_or_input_mutation(self) -> None:
        before = copy.deepcopy((self.package, self.effective, self.evidence, self.events, self.ledger, self.recorded))
        with (
            patch("pathlib.Path.read_text", side_effect=AssertionError("unexpected file read")),
            patch("pathlib.Path.resolve", side_effect=AssertionError("unexpected path resolution")),
            patch("subprocess.run", side_effect=AssertionError("unexpected process")),
            patch("cogito_gate_validation.load_json", side_effect=AssertionError("unexpected JSON read")),
        ):
            self.validate()
        self.assertEqual((self.package, self.effective, self.evidence, self.events, self.ledger, self.recorded), before)

    def test_every_required_check_must_be_supplied(self) -> None:
        self.evidence.pop()
        with self.assertRaisesRegex(CogitoError, "required verification evidence is missing"):
            self.validate()

    def test_missing_collected_record_and_missing_ledger_are_rejected(self) -> None:
        path = self.evidence[0]["evidence_path"]
        del self.recorded[path]
        with self.assertRaisesRegex(CogitoError, "immutable evidence file is missing"):
            self.validate()
        self.collect()
        del self.ledger[path]
        with self.assertRaisesRegex(CogitoError, "produced and recorded"):
            self.validate()

    def test_tampered_file_and_ledger_hash_are_rejected(self) -> None:
        path = self.evidence[0]["evidence_path"]
        self.recorded[path]["stdout"] = "tampered"
        with self.assertRaisesRegex(CogitoError, "does not match its immutable file"):
            self.validate()
        self.collect()
        self.ledger[path]["evidence_hash"] = "f" * 64
        with self.assertRaisesRegex(CogitoError, "produced and recorded"):
            self.validate()

    def test_each_phase_uses_its_latest_cycle_anchor(self) -> None:
        for phase, anchor in (
            ("implementation", "implementation-complete"),
            ("implementation", "technical-correction-complete"),
            ("implementation", "review-fix-complete"),
            ("post-integration", "integration-complete"),
            ("post-integration", "post-integration-correction-complete"),
        ):
            with self.subTest(phase=phase, anchor=anchor):
                self.events = [{"type": anchor, "sequence": 12}]
                self.collect(sequence=12)
                with self.assertRaisesRegex(CogitoError, "predates the current verification cycle"):
                    self.validate(phase, "b" * 40)
                self.collect(sequence=13)
                self.validate(phase, "b" * 40)

    def test_phase_is_explicit_even_when_a_current_head_is_available(self) -> None:
        self.events.append({"type": "integration-complete", "sequence": 20})
        self.validate("implementation", "e" * 40)
        with self.assertRaisesRegex(CogitoError, "evidence phase"):
            self.validate("unknown")

    def test_post_integration_requires_a_valid_matching_head(self) -> None:
        for head in (None, "", "not-a-commit"):
            with self.subTest(head=head), self.assertRaisesRegex(CogitoError, "valid current HEAD"):
                self.validate("post-integration", head)
        with self.assertRaisesRegex(CogitoError, "not bound to current HEAD"):
            self.validate("post-integration", "e" * 40)
        self.validate("post-integration", "b" * 40)

    def test_post_integration_requires_content_tree_on_all_supplied_evidence(self) -> None:
        optional = evidence_for(self.effective["checks"][2], self.effective["effective_contract_hash"])
        self.evidence.append(optional)
        for tree in (None, "invalid"):
            with self.subTest(tree=tree):
                optional["worktree_binding"]["content_tree"] = tree
                with self.assertRaisesRegex(CogitoError, "lacks a content tree"):
                    self.validate("post-integration", "b" * 40)

    def test_optional_evidence_keeps_shape_validation_without_required_binding(self) -> None:
        optional = evidence_for(self.effective["checks"][2], "e" * 64)
        optional.update({"status": "failed", "passed": False, "exit_code": 1})
        self.evidence.append(optional)
        self.validate()
        self.validate("post-integration", "b" * 40)
        optional["passed"] = "false"
        with self.assertRaisesRegex(CogitoError, "must be a boolean"):
            self.validate()

    def test_contract_check_and_output_policy_bindings_are_preserved(self) -> None:
        original = copy.deepcopy(self.evidence[0])
        for field, value, message in (
            ("effective_contract_hash", "e" * 64, "evidence binding failed"),
            ("check_hash", "e" * 64, "evidence binding failed"),
            ("output_limit_bytes", 2048, "output policy binding failed"),
        ):
            with self.subTest(field=field):
                self.evidence[0] = {**original, field: value}
                self.collect()
                with self.assertRaisesRegex(CogitoError, message):
                    self.validate()

    def test_worktree_binding_hash_and_head_are_preserved(self) -> None:
        self.evidence[0]["worktree_binding"]["content_tree"] = "e" * 40
        self.collect()
        with self.assertRaisesRegex(CogitoError, "binding hash is invalid"):
            self.validate()
        item = self.evidence[0]
        binding = item["worktree_binding"]
        binding["head_commit"] = "f" * 40
        binding["snapshot_hash"] = hash_json({key: value for key, value in binding.items() if key != "snapshot_hash"})
        for field in ("tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash"):
            item[field] = binding["snapshot_hash"]
        self.collect()
        with self.assertRaisesRegex(CogitoError, "worktree stability binding failed"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
