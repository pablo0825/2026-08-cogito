"""Narrow Git process adapter used by the Gate coordinator."""

from __future__ import annotations

import subprocess
from pathlib import Path

from cogito_common import CogitoError


class GitRepository:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def run(self, *args: str) -> str:
        return self.run_at(self.root, *args, error_prefix="Git validation failed")

    def run_at(self, directory: str | Path, *args: str, error_prefix: str = "worktree Git validation failed") -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(directory), *args], check=True, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CogitoError(f"{error_prefix}: {exc}") from exc
        # NUL-delimited paths may begin with whitespace; do not normalize them.
        return result.stdout if "-z" in args else result.stdout.strip()
