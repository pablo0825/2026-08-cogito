"""Build and validate an RP successor in a disposable delivery checkout."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from cogito_common import CogitoError, hash_json


def _safe(path: str) -> bool:
    value = PurePosixPath(path)
    return bool(path) and not value.is_absolute() and '..' not in value.parts and '\0' not in path


def control_paths(package, package_path):
    paths = {package_path, 'docs/cogito/project-graph.json'}
    for item in package['slices']:
        paths.update((item['spec']['path'], item['plan']['path']))
    paths.update(item['path'] for item in package['source_registry'])
    shared = package.get('shared_understanding') or {}
    if shared.get('path'):
        paths.add(shared['path'])
    if not all(_safe(path) for path in paths):
        raise CogitoError('isolated Start Gate contains an unsafe control path')
    return sorted(paths)


def manifest(root: Path, paths):
    result = {}
    for relative in paths:
        path = root / relative
        try:
            info = path.lstat()
            if path.is_symlink() or not path.is_file():
                raise CogitoError('isolated Start Gate controls must be regular files')
            result[relative] = {
                'hash': hashlib.sha256(path.read_bytes()).hexdigest(),
                'mode': '100755' if info.st_mode & 0o111 else '100644',
            }
        except OSError as exc:
            raise CogitoError(f'cannot bind isolated Start Gate control {relative}: {exc}') from exc
    return result


def _git(root: Path, *args: str):
    try:
        return subprocess.run(['git', '-C', str(root), *args], check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f'cannot prepare isolated Start Gate checkout: {exc}') from exc


@contextmanager
def checkout(root: Path, head: str, controls):
    directory = Path(tempfile.mkdtemp(prefix='cogito-rp-start-'))
    added = False
    try:
        _git(root, 'worktree', 'add', '--detach', str(directory), head)
        added = True
        for relative, entry in controls.items():
            source, target = root / relative, directory / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() or target.is_symlink():
                target.unlink()
            target.write_bytes(source.read_bytes())
            target.chmod(0o755 if entry['mode'] == '100755' else 0o644)
        yield directory
    finally:
        if added:
            subprocess.run(['git', '-C', str(root), 'worktree', 'remove', '--force', str(directory)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        shutil.rmtree(directory, ignore_errors=True)


def validation_binding(root, checkout_root, head, controls):
    actual = manifest(checkout_root, controls)
    if actual != controls:
        raise CogitoError('isolated Start Gate controls changed during materialization')
    actual_head = _git(checkout_root, 'rev-parse', 'HEAD')
    if actual_head != head:
        raise CogitoError('isolated Start Gate checkout has the wrong delivery HEAD')
    from cogito_evidence_binding import capture_index_and_worktree_trees
    _, content_tree = capture_index_and_worktree_trees(checkout_root)
    return {
        'result': 'passed', 'delivery_head': actual_head,
        'delivery_tree': content_tree,
        'control_manifest_hash': hash_json(controls),
    }
