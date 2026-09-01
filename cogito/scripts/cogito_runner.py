#!/usr/bin/env python3
"""Controlled argv-only verification runner for Cogito 3.0."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from cogito_runtime import CogitoError, ID_RE, atomic_write_json, hash_json, materialize_contract, validate_package

OUTPUT_CAP = 64 * 1024
BASE_ENV = ("PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "PATHEXT")


def _git(worktree: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), *args], shell=False, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f"cannot establish Git evidence binding: {exc}") from exc
    return proc.stdout.strip()


def _working_tree_binding(worktree: Path) -> dict[str, Any]:
    """Bind evidence to HEAD plus actual unstaged and untracked tested content."""
    try:
        diff = subprocess.run(
            ["git", "-C", str(worktree), "diff", "--binary", "HEAD", "--"],
            shell=False, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        ).stdout
        untracked_raw = subprocess.run(
            ["git", "-C", str(worktree), "ls-files", "--others", "--exclude-standard", "-z"],
            shell=False, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f"cannot snapshot working tree: {exc}") from exc
    untracked: list[dict[str, str]] = []
    for raw in filter(None, untracked_raw.split(b"\0")):
        relative = raw.decode("utf-8", errors="surrogateescape")
        path = _safe_file(worktree, relative)
        digest = hashlib.sha256()
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise CogitoError(f"cannot hash untracked file {relative}: {exc}") from exc
        untracked.append({"path": relative, "sha256": digest.hexdigest()})
    binding = {
        "head_tree": _git(worktree, "rev-parse", "HEAD^{tree}"),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked": sorted(untracked, key=lambda item: item["path"]),
    }
    binding["snapshot_hash"] = hash_json(binding)
    return binding


def _safe_file(worktree: Path, relative: str) -> Path:
    root = worktree.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CogitoError("working-tree path escapes worktree") from exc
    if not candidate.is_file():
        raise CogitoError(f"working-tree path is not a regular file: {relative}")
    return candidate


def _safe_cwd(worktree: Path, relative: str) -> Path:
    root = worktree.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise CogitoError("check cwd escapes the worktree") from exc
    if not candidate.is_dir():
        raise CogitoError("check cwd does not exist or is not a directory")
    return candidate


def _limited(value: bytes, cap: int) -> tuple[str, bool]:
    truncated = len(value) > cap
    return value[:cap].decode("utf-8", errors="replace"), truncated


def _redact(text: str, patterns: Sequence[str]) -> str:
    for pattern in patterns:
        try:
            text = re.sub(pattern, "[REDACTED]", text)
        except re.error as exc:
            raise CogitoError(f"invalid redaction pattern: {exc}") from exc
    return text


def run_check(
    package: Mapping[str, Any], check_id: str, worktree: str | Path,
    amendments: Sequence[Mapping[str, Any]] = (), output_cap: int = OUTPUT_CAP,
) -> dict[str, Any]:
    validate_package(package)
    effective = materialize_contract(package, amendments)
    matching = [item for item in effective["checks"] if item.get("id") == check_id]
    if len(matching) != 1:
        raise CogitoError(f"expected exactly one check named {check_id!r}")
    check = matching[0]
    argv = check.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(value, str) and value for value in argv):
        raise CogitoError("check argv must be a non-empty string array")
    timeout = int(check.get("timeout_seconds", 300))
    if not 1 <= timeout <= 3600:
        raise CogitoError("timeout_seconds must be between 1 and 3600")
    cap = max(1024, min(int(output_cap), 1024 * 1024))
    worktree = Path(worktree).resolve()
    cwd = _safe_cwd(worktree, str(check.get("cwd", ".")))
    allowed = set(BASE_ENV) | set(check.get("env_allowlist", []))
    env = {key: value for key, value in os.environ.items() if key in allowed}
    started_at = datetime.now(timezone.utc).isoformat()
    start = time.monotonic()
    timed_out = False
    exit_code: int | None
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        try:
            proc = subprocess.run(
                argv, cwd=cwd, env=env, shell=False, stdin=subprocess.DEVNULL,
                stdout=stdout_file, stderr=stderr_file, timeout=timeout, check=False,
            )
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out, exit_code = True, None
        except OSError as exc:
            exit_code = 127
            stderr_file.write(str(exc).encode("utf-8", errors="replace"))
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_raw = stdout_file.read(cap + 1)
        stderr_raw = stderr_file.read(cap + 1)
    duration = time.monotonic() - start
    stdout, out_truncated = _limited(stdout_raw, cap)
    stderr, err_truncated = _limited(stderr_raw, cap)
    patterns = check.get("redact_patterns", [])
    if not isinstance(patterns, list):
        raise CogitoError("redact_patterns must be an array")
    stdout, stderr = _redact(stdout, patterns), _redact(stderr, patterns)
    binding = _working_tree_binding(worktree)
    evidence = {
        "schema_version": "3.0", "run_id": package["run_id"], "check_id": check_id,
        "status": "passed" if exit_code == 0 and not timed_out else "failed", "passed": exit_code == 0 and not timed_out,
        "exit_code": exit_code, "timed_out": timed_out, "duration_seconds": round(duration, 6),
        "started_at": started_at, "head_commit": _git(worktree, "rev-parse", "HEAD"),
        "tree_hash": binding["snapshot_hash"], "worktree_snapshot_hash": binding["snapshot_hash"], "worktree_binding": binding, "check_hash": hash_json(check),
        "effective_contract_hash": effective["effective_contract_hash"],
        "argv": argv, "cwd": str(cwd.relative_to(worktree)) or ".",
        "stdout": stdout, "stderr": stderr, "truncated": out_truncated or err_truncated,
    }
    return evidence


def write_evidence_once(directory: str | Path, record_id: str, evidence: Mapping[str, Any]) -> Path:
    if not ID_RE.fullmatch(record_id):
        raise CogitoError("evidence record id is not a safe filename")
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = (root / f"{record_id}.json").resolve()
    try:
        destination.relative_to(root)
    except ValueError as exc:  # defensive in case identifier policy changes
        raise CogitoError("evidence path escapes evidence directory") from exc
    if destination.exists():
        raise CogitoError("immutable evidence record already exists")
    value = dict(evidence)
    value["evidence_path"] = str(destination)
    atomic_write_json(destination, value)
    destination.chmod(0o444)
    return destination


def _object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CogitoError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CogitoError(f"{path} must contain an object")
    return value


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run-check")
    run.add_argument("--package", required=True)
    run.add_argument("--check-id", required=True)
    run.add_argument("--worktree", required=True)
    run.add_argument("--evidence-dir", required=True)
    run.add_argument("--amendment", action="append", default=[])
    run.add_argument("--output-cap", type=int, default=OUTPUT_CAP)
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        evidence = run_check(
            _object(args.package), args.check_id, args.worktree,
            [_object(path) for path in args.amendment], args.output_cap,
        )
        destination = Path(args.evidence_dir).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        if not ID_RE.fullmatch(args.check_id):
            raise CogitoError("check id is not safe for evidence storage")
        content_hash = hash_json(evidence)
        record_id = f"{args.check_id}-{evidence['head_commit'][:12]}-{evidence['effective_contract_hash'][:12]}-{content_hash[:12]}"
        evidence_path = write_evidence_once(destination, record_id, evidence)
    except CogitoError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "evidence": str(evidence_path), "status": evidence["status"]}, ensure_ascii=False))
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
