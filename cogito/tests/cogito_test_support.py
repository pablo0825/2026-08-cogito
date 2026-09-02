"""Shared test setup; each Package builder returns independent mutable data."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

COGITO = Path(__file__).resolve().parents[1]
SCRIPTS = COGITO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, text=True, capture_output=True
    ).stdout.strip()


def init_repo(repo: Path, *, branch: str = "main") -> None:
    """Initialize an existing directory without creating fixture files or commits."""
    git(repo, "init", "-q", "-b", branch)
    git(repo, "config", "user.email", "cogito@example.invalid")
    git(repo, "config", "user.name", "Cogito Test")


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
