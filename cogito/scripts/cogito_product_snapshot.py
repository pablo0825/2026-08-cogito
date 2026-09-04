"""Neutral Git-tree primitives for workspace and product snapshots.

This module deliberately knows nothing about RP, DP, runtime event types, or
workflow policy.  Callers classify and validate paths before asking it to
project a product tree.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from cogito_common import CogitoError


def git_bytes(
    root: Path,
    *args: str,
    env=None,
    data=None,
    error_context: str = 'workspace snapshot',
) -> bytes:
    """Run a bounded Git object operation without adding workflow policy."""
    try:
        return subprocess.run(
            ['git', '-C', str(root), *args], input=data, env=env,
            check=True, capture_output=True, timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f'cannot {error_context}: {exc}') from exc


def tree_entries(
    root: Path,
    tree: str,
    *,
    error_context: str = 'read workspace snapshot',
) -> dict[str, tuple[str, str]]:
    """Return recursive path bindings for a Git tree."""
    result = {}
    output = git_bytes(root, 'ls-tree', '-r', '-z', tree, error_context=error_context)
    for record in output.split(b'\0'):
        if record:
            metadata, name = record.split(b'\t', 1)
            mode, _, oid = metadata.decode('ascii').split()
            result[name.decode('utf-8', errors='surrogateescape')] = (mode, oid)
    return result


def sha256_digest(data: bytes) -> str:
    """Return the content digest used by runtime journal bindings."""
    return hashlib.sha256(data).hexdigest()


def tree_without_paths(
    root: Path,
    tree: str,
    paths: list[str],
    *,
    temporary_prefix: str = 'cogito-product-',
    error_context: str = 'project workspace snapshot',
) -> str:
    """Derive a Git tree with caller-validated paths removed."""
    if not paths:
        return tree
    with tempfile.TemporaryDirectory(prefix=temporary_prefix) as directory:
        env = {**os.environ, 'GIT_INDEX_FILE': str(Path(directory) / 'index')}
        git_bytes(root, 'read-tree', tree, env=env, error_context=error_context)
        names = b''.join(
            path.encode('utf-8', errors='surrogateescape') + b'\0'
            for path in paths
        )
        git_bytes(
            root, 'update-index', '--force-remove', '-z', '--stdin',
            env=env, data=names, error_context=error_context,
        )
        return git_bytes(
            root, 'write-tree', env=env, error_context=error_context,
        ).decode().strip()
