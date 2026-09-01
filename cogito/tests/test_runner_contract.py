"""Black-box safety tests for the controlled verification runner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]
RUNNER = COGITO / "scripts" / "cogito_runner.py"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    )
    return result.stdout.strip()


class ControlledRunnerContractTests(unittest.TestCase):
    def prepare_repo(self, root: Path) -> tuple[Path, str]:
        repo = root / "repo"
        repo.mkdir()
        git(repo, "init", "-q")
        git(repo, "config", "user.email", "cogito@example.invalid")
        git(repo, "config", "user.name", "Cogito Test")
        (repo / "tracked.txt").write_text("baseline\n")
        git(repo, "add", "tracked.txt")
        git(repo, "commit", "-qm", "baseline")
        return repo, git(repo, "rev-parse", "HEAD")

    def invoke(
        self,
        package: Path,
        check_id: str,
        repo: Path,
        evidence: Path,
        *,
        env: dict[str, str] | None = None,
    ):
        return subprocess.run(
            [
                sys.executable,
                str(RUNNER),
                "run-check",
                "--package",
                str(package),
                "--check-id",
                check_id,
                "--worktree",
                str(repo),
                "--evidence-dir",
                str(evidence),
            ],
            text=True,
            capture_output=True,
            env=env,
        )

    def write_package(self, root: Path, commit: str, checks: list[dict]) -> Path:
        package = {
            "schema_version": "3.0",
            "run_id": "DEV-20260901-001",
            "kind": "feature",
            "mini_package": False,
            "delivery_branch": "main",
            "baseline_commit": commit,
            "shared_understanding": {"hash": "a" * 64},
            "boundary": {"decision": "single-slice", "evidence": ["small surface"]},
            "slices": [{
                "id": "FS-001", "type": "feature",
                "spec": {"path": "docs/spec.md", "hash": "b" * 64},
                "plan": {"path": "docs/plan.md", "hash": "c" * 64},
                "worker": {"branch": "codex/fs-001", "worktree": ".cogito/worktrees/FS-001", "allowed_paths": ["src/**", "tests/**"]},
            }],
            "execution_dag": {"tasks": [{"id": "T-1", "slice_id": "FS-001", "paths": ["src"]}], "edges": []},
            "approved_paths": ["src/**", "tests/**"],
            "human_gate": {"predicates": [], "high_risk_hotspots": []},
            "checks": checks,
            "policy_snapshot": {"max_workers": 3, "fetch_allowed": False},
            "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
            "stop_conditions": ["contract boundary change"],
            "source_registry": [],
        }
        path = root / "package.json"
        path.write_text(json.dumps(package))
        return path

    def test_runner_uses_argv_without_shell_and_binds_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            marker = repo / "must-not-exist"
            literal = f"$(touch {marker})"
            package = self.write_package(
                root,
                commit,
                [{"id": "C-1", "argv": ["printf", "%s", literal], "timeout_seconds": 2}],
            )
            evidence_dir = root / "evidence"
            result = self.invoke(package, "C-1", repo, evidence_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(marker.exists(), "runner evaluated shell syntax")
            evidence_files = list(evidence_dir.glob("*.json"))
            self.assertEqual(len(evidence_files), 1)
            evidence = json.loads(evidence_files[0].read_text())
            self.assertEqual(evidence["head_commit"], commit)
            self.assertEqual(evidence["check_id"], "C-1")
            self.assertRegex(evidence["effective_contract_hash"], r"^[0-9a-f]{64}$")
            self.assertIn("tree_hash", evidence)
            self.assertIn("check_hash", evidence)

    def test_runner_timeout_is_a_failed_machine_evidence_record(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            package = self.write_package(
                root,
                commit,
                [{
                    "id": "C-timeout",
                    "argv": [sys.executable, "-c", "import time; time.sleep(2)"],
                    "timeout_seconds": 1,
                }],
            )
            evidence_dir = root / "evidence"
            result = self.invoke(package, "C-timeout", repo, evidence_dir)
            self.assertNotEqual(result.returncode, 0)
            evidence_files = list(evidence_dir.glob("*.json"))
            self.assertEqual(len(evidence_files), 1)
            evidence = json.loads(evidence_files[0].read_text())
            self.assertEqual(evidence["status"], "failed")
            self.assertTrue(evidence["timed_out"])

    def test_runner_redacts_and_caps_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            package = self.write_package(
                root,
                commit,
                [{
                    "id": "C-output",
                    "argv": [
                        sys.executable,
                        "-c",
                        "print('SECRET-1234'); print('x' * 70000)",
                    ],
                    "redact_patterns": [r"SECRET-\d+"],
                }],
            )
            evidence_dir = root / "evidence"
            result = self.invoke(package, "C-output", repo, evidence_dir)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(next(evidence_dir.glob("*.json")).read_text())
            self.assertNotIn("SECRET-1234", evidence["stdout"])
            self.assertIn("[REDACTED]", evidence["stdout"])
            self.assertTrue(evidence["truncated"])
            self.assertLessEqual(len(evidence["stdout"].encode()), 64 * 1024)

    def test_runner_exposes_only_allowlisted_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            package = self.write_package(
                root,
                commit,
                [{
                    "id": "C-env",
                    "argv": [
                        sys.executable,
                        "-c",
                        "import os; print(os.getenv('COGITO_ALLOWED')); print(os.getenv('COGITO_BLOCKED'))",
                    ],
                    "env_allowlist": ["COGITO_ALLOWED"],
                }],
            )
            value = json.loads(package.read_text())
            value["policy_snapshot"]["allowed_environment"] = ["COGITO_ALLOWED"]
            package.write_text(json.dumps(value))
            evidence_dir = root / "evidence"
            environment = dict(os.environ)
            environment.update({"COGITO_ALLOWED": "visible", "COGITO_BLOCKED": "hidden"})
            result = self.invoke(package, "C-env", repo, evidence_dir, env=environment)
            self.assertEqual(result.returncode, 0, result.stderr)
            evidence = json.loads(next(evidence_dir.glob("*.json")).read_text())
            self.assertEqual(evidence["stdout"].splitlines(), ["visible", "None"])

    def test_runner_rejects_cwd_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            package = self.write_package(
                root,
                commit,
                [{"id": "C-cwd", "argv": ["true"], "cwd": ".."}],
            )
            evidence_dir = root / "evidence"
            result = self.invoke(package, "C-cwd", repo, evidence_dir)
            self.assertEqual(result.returncode, 2)
            self.assertIn("check cwd escapes the worktree", result.stderr)
            self.assertFalse(evidence_dir.exists())

    def test_runner_rejects_invalid_redaction_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, commit = self.prepare_repo(root)
            package = self.write_package(
                root,
                commit,
                [{
                    "id": "C-redact",
                    "argv": ["printf", "sensitive"],
                    "redact_patterns": ["["],
                }],
            )
            evidence_dir = root / "evidence"
            result = self.invoke(package, "C-redact", repo, evidence_dir)
            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid redaction pattern", result.stderr)
            self.assertFalse(evidence_dir.exists())


if __name__ == "__main__":
    unittest.main()
