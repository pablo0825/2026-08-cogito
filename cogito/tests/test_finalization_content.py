"""Delivery must preserve the actual content captured by the controlled runner."""

from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from cogito_test_support import GitTestCase, init_repo
from cogito_common import CogitoError, hash_json
from cogito_evidence_binding import working_tree_binding
from cogito_finalization import validate_final_content_changes, validate_verified_content
from cogito_finalization_rules import validate_verification_snapshot
from cogito_git import GitRepository
from cogito_gate_validation import validate_evidence
from test_evidence_contract import valid_evidence


class VerificationSnapshotRulesTests(unittest.TestCase):
    def snapshot(self, tree="c" * 40) -> dict:
        evidence = valid_evidence()
        binding = {} if tree is None else {"content_tree": tree}
        digest = hash_json(binding)
        evidence["worktree_binding"] = {**binding, "snapshot_hash": digest}
        for field in ("tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash"):
            evidence[field] = digest
        return evidence

    def test_loaded_snapshot_returns_its_tree_without_changing_inputs(self) -> None:
        evidence = self.snapshot()
        ledger = {"evidence_hash": hash_json(evidence)}
        before = copy.deepcopy((evidence, ledger))
        self.assertEqual(validate_verification_snapshot(evidence, ledger, evidence["effective_contract_hash"]), "c" * 40)
        self.assertEqual((evidence, ledger), before)

    def test_snapshot_rejects_tampering_contract_drift_and_missing_tree_without_io(self) -> None:
        for case in ("ledger", "contract", "binding", "failed", "missing-tree", "invalid-tree"):
            with self.subTest(case=case):
                evidence = self.snapshot(None if case == "missing-tree" else "invalid" if case == "invalid-tree" else "c" * 40)
                expected_hash = evidence["effective_contract_hash"]
                if case == "binding":
                    evidence["worktree_binding"]["content_tree"] = "f" * 40
                if case == "failed":
                    evidence.update({"passed": False, "status": "failed", "exit_code": 1})
                ledger = {"evidence_hash": "0" * 64 if case == "ledger" else hash_json(evidence)}
                before = copy.deepcopy((evidence, ledger))
                with self.assertRaises(CogitoError):
                    validate_verification_snapshot(evidence, ledger, "0" * 64 if case == "contract" else expected_hash)
                self.assertEqual((evidence, ledger), before)


class FinalizationContentTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git = GitRepository(self.repo).run
        init_repo(self.repo)
        self.git("config", "core.filemode", "true")
        (self.repo / "product.bin").write_bytes(b"before\x00\xff\n")
        (self.repo / ".gitignore").write_text("ignored.txt\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.metadata = {
            "docs/cogito/results/DEV-content.json", "docs/cogito/project-graph.json",
        }

    def capture(self) -> tuple[dict, dict]:
        binding = working_tree_binding(self.repo)
        evidence = valid_evidence()
        evidence.update({
            "worktree_binding": binding, "head_commit": binding["head_commit"],
            "evidence_path": str(self.root / "evidence.json"),
        })
        for field in ("tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash"):
            evidence[field] = binding["snapshot_hash"]
        return evidence, self.save_evidence(evidence)

    def save_evidence(self, evidence: dict) -> dict:
        Path(evidence["evidence_path"]).write_text(json.dumps(evidence))
        return {
            "effective_contract_hash": evidence["effective_contract_hash"],
            "evidence": {evidence["evidence_path"]: {"evidence_hash": hash_json(evidence)}},
        }

    def finalize(self, state: dict) -> None:
        for relative in self.metadata:
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n")
        self.git("add", "--all")
        self.git("commit", "-qm", "finalize")
        validate_verified_content(
            final_commit=self.git("rev-parse", "HEAD"),
            evidence_paths=set(state["evidence"]), state=state,
            metadata_paths=self.metadata, git=self.git,
        )

    def test_only_exact_metadata_paths_are_exempt(self) -> None:
        validate_final_content_changes(sorted(self.metadata), self.metadata)
        for relative in ("docs/cogito/results/DEV-other.json", "docs/cogito/project-graph.json/child", "docs/plan.md"):
            with self.subTest(path=relative), self.assertRaisesRegex(CogitoError, "unverified content"):
                validate_final_content_changes([relative], self.metadata)

    def test_snapshot_preserves_index_and_binds_staged_unstaged_and_untracked_files(self) -> None:
        (self.repo / "product.bin").write_bytes(b"staged\x00\xff\n")
        self.git("add", "product.bin")
        (self.repo / "product.bin").write_bytes(b"verified working content\x00\xfe\n")
        (self.repo / "new file.txt").write_text("new\n")
        (self.repo / "ignored.txt").write_text("explicitly tracked\n")
        self.git("add", "--force", "ignored.txt")
        index = self.repo / ".git/index"
        before = index.read_bytes()
        _, state = self.capture()
        self.assertEqual(index.read_bytes(), before)
        self.finalize(state)

    def test_verified_deletion_can_be_committed(self) -> None:
        (self.repo / "product.bin").unlink()
        _, state = self.capture()
        self.finalize(state)

    def test_delivery_rejects_add_delete_rename_binary_mode_and_symlink_changes(self) -> None:
        for change in ("add", "delete", "rename", "binary", "mode", "symlink"):
            with self.subTest(change=change):
                self.git("reset", "--hard", "main")
                self.git("clean", "-fd")
                baseline = self.git("rev-parse", "HEAD")
                _, state = self.capture()
                product = self.repo / "product.bin"
                if change == "add":
                    (self.repo / "new file.txt").write_text("unverified\n")
                elif change == "delete":
                    product.unlink()
                elif change == "rename":
                    product.rename(self.repo / "renamed.bin")
                elif change == "binary":
                    product.write_bytes(b"after\x00\xfe\n")
                elif change == "mode":
                    product.chmod(0o755)
                else:
                    product.unlink()
                    product.symlink_to(".gitignore")
                with self.assertRaisesRegex(CogitoError, "unverified content"):
                    self.finalize(state)
                self.git("reset", "--hard", baseline)

    def test_omitting_verified_untracked_content_is_rejected(self) -> None:
        path = self.repo / "required.txt"
        path.write_text("verified\n")
        _, state = self.capture()
        path.unlink()
        with self.assertRaisesRegex(CogitoError, "unverified content"):
            self.finalize(state)

    def test_whitespace_in_git_paths_cannot_disguise_product_content_as_metadata(self) -> None:
        _, state = self.capture()
        path = self.repo / " docs/cogito/project-graph.json"
        path.parent.mkdir(parents=True)
        path.write_text("unverified\n")
        with self.assertRaisesRegex(CogitoError, "unverified content"):
            self.finalize(state)

    def test_legacy_evidence_requires_rerun_without_rewriting_it(self) -> None:
        evidence, _ = self.capture()
        del evidence["worktree_binding"]["content_tree"]
        binding = evidence["worktree_binding"]
        binding["snapshot_hash"] = hash_json({key: value for key, value in binding.items() if key != "snapshot_hash"})
        for field in ("tree_hash", "worktree_snapshot_hash", "pre_worktree_snapshot_hash", "post_worktree_snapshot_hash"):
            evidence[field] = binding["snapshot_hash"]
        state = self.save_evidence(evidence)
        before = Path(evidence["evidence_path"]).read_bytes()
        with self.assertRaisesRegex(CogitoError, "rerun controlled checks"):
            self.finalize(state)
        self.assertEqual(Path(evidence["evidence_path"]).read_bytes(), before)

    def test_legacy_evidence_is_rejected_before_leaving_post_verification(self) -> None:
        with self.assertRaisesRegex(CogitoError, "rerun controlled checks"):
            validate_evidence(
                {}, [valid_evidence()], [], {}, {},
                effective_contract={}, phase="post-integration", current_head="b" * 40,
            )

    def test_tampered_evidence_is_rejected(self) -> None:
        evidence, state = self.capture()
        evidence["worktree_binding"]["content_tree"] = self.git("rev-parse", "HEAD^{tree}")
        evidence["stdout"] = "modified after publication"
        Path(evidence["evidence_path"]).write_text(json.dumps(evidence))
        with self.assertRaisesRegex(CogitoError, "runner ledger"):
            self.finalize(state)


if __name__ == "__main__":
    unittest.main()
