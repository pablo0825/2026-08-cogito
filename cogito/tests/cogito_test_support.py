"""Shared test setup; each Package builder returns independent mutable data."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

COGITO = Path(__file__).resolve().parents[1]
SCRIPTS = COGITO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


@contextmanager
def isolated_git_environment():
    """Isolate this test and its product subprocesses; restore the caller on exit.

    Tests run sequentially in this process. Removing all inherited GIT_* values
    also prevents repository paths and command-line config from escaping into
    temporary repositories. Tests can still set explicit overrides inside this
    context when they need to exercise environment handling.
    """
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("GIT_")
    }
    environment.update({
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
    })
    with mock.patch.dict(os.environ, environment, clear=True):
        yield


class GitTestCase(unittest.TestCase):
    """Base for tests that create repositories or invoke product Git processes."""

    def setUp(self) -> None:
        super().setUp()
        context = isolated_git_environment()
        context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def init_repo(repo: Path, *, branch: str = "main") -> None:
    """Initialize inside GitTestCase/isolated_git_environment, without commits."""
    git(repo, "init", "-q", "--template=", "-b", branch)
    git(repo, "config", "user.email", "cogito@example.invalid")
    git(repo, "config", "user.name", "Cogito Test")
    git(repo, "config", "commit.gpgsign", "false")
    git(repo, "config", "tag.gpgsign", "false")
    git(repo, "config", "core.hooksPath", os.devnull)


def minimal_package() -> dict:
    return {
        "schema_version": "3.0",
        "run_id": "DEV-20260901-001",
        "kind": "feature",
        "delivery_branch": "main",
        "baseline_commit": "a" * 40,
        "shared_understanding": {"hash": "a" * 64},
        "boundary": {"decision": "single-slice", "evidence": ["small surface"]},
        "mini_package": False,
        "slices": [{
            "id": "FS-001", "type": "feature",
            "spec": {"path": "docs/spec.md", "hash": "b" * 64},
            "plan": {"path": "docs/plan.md", "hash": "c" * 64},
            "worker": {"branch": "codex/fs-001", "worktree": ".cogito/worktrees/FS-001", "allowed_paths": ["src/**", "tests/**"]},
        }],
        "approved_paths": ["src/**", "tests/**"],
        "checks": [{"id": "C-1", "argv": ["python3", "-m", "unittest"], "required": True}],
        "execution_dag": {
            "tasks": [{"id": "T-1", "slice_id": "FS-001", "paths": ["src"]}],
            "edges": [],
        },
        "human_gate": {"predicates": [], "high_risk_hotspots": []},
        "policy_snapshot": {"max_workers": 3, "fetch_allowed": False},
        "limits": {"transient_retries": 2, "verification_corrections": 3, "review_fix_cycles": 3, "format_repairs": 2},
        "stop_conditions": ["contract boundary change"],
        "source_registry": [],
    }


def package(kind: str = "feature") -> dict:
    """Build the safety-suite contract, including the existing mini variants."""
    value = minimal_package()
    mini = kind in {"maintenance", "documentation"}
    value.update({
        "run_id": "DEV-safe-001",
        "kind": kind,
        "mini_package": mini,
        "shared_understanding": {"hash": "b" * 64},
        "checks": [{"id": "C-1", "argv": [sys.executable, "-c", "print('ok')"], "required": True}],
        "human_gate": {
            "predicates": [{"id": "public-api", "applicable": True}],
            "high_risk_hotspots": [],
        },
        "stop_conditions": ["contract-boundary-change"],
    })
    if mini:
        value.pop("boundary")
        value["slices"] = []
        value["execution_dag"]["tasks"] = [{"id": "T-1", "paths": ["src"]}]
        value["human_gate"]["predicates"] = []
        value["maintenance_guards"] = {
            key: True for key in (
                "behavior_unchanged", "public_contract_unchanged",
                "data_model_unchanged", "security_boundary_unchanged",
                "slice_responsibility_unchanged", "deterministic_evidence",
                "single_commit",
            )
        }
    else:
        value["boundary"] = {"decision": "single-slice", "evidence": ["bounded"]}
        value["execution_dag"]["tasks"][0]["slice_id"] = "FS-1"
        value["slices"] = [{
            "id": "FS-1", "type": kind, "spec": {"path": "docs/spec.md", "hash": "c" * 64},
            "plan": {"path": "docs/plan.md", "hash": "d" * 64},
            "worker": {"branch": "codex/fs-1", "worktree": ".cogito/worktrees/FS-1", "allowed_paths": ["src/**", "tests/**"]},
        }]
    return value
