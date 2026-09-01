"""Bind verification evidence to a safe snapshot of a Git worktree."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from cogito_common import CogitoError, hash_json


def git(worktree: Path, *args: str) -> str:
    """Run a bounded, read-only Git command used for evidence binding."""
    try:
        process = subprocess.run(
            ["git", "-C", str(worktree), *args],
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f"cannot establish Git evidence binding: {exc}") from exc
    return process.stdout.strip()


def safe_file(worktree: Path, relative: str) -> Path:
    """Resolve a regular file without allowing worktree escape."""
    root = worktree.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CogitoError("working-tree path escapes worktree") from exc
    if not candidate.is_file():
        raise CogitoError(f"working-tree path is not a regular file: {relative}")
    return candidate


def safe_cwd(worktree: Path, relative: str) -> Path:
    """Resolve a check working directory without allowing worktree escape."""
    root = worktree.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CogitoError("check cwd escapes the worktree") from exc
    if not candidate.is_dir():
        raise CogitoError("check cwd does not exist or is not a directory")
    return candidate


def working_tree_binding(worktree: Path) -> dict[str, Any]:
    """Hash HEAD, tracked changes, and every untracked regular file."""
    try:
        diff = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--binary", "HEAD", "--"],
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        ).stdout
        untracked_raw = subprocess.run(
            ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard", "-z"],
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f"cannot snapshot working tree: {exc}") from exc

    untracked: list[dict[str, str]] = []
    for raw in filter(None, untracked_raw.split(b"\0")):
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = safe_file(worktree, relative)
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise CogitoError(f"cannot hash untracked file {relative}: {exc}") from exc
        untracked.append({"path": relative, "sha256": digest.hexdigest()})

    binding = {
        "head_tree": git(worktree, "rev-parse", "HEAD^{tree}"),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked": sorted(untracked, key=lambda item: item["path"]),
    }
    binding["snapshot_hash"] = hash_json(binding)
    return binding
