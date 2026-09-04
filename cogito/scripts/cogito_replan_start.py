"""Build and validate an RP successor in a disposable delivery checkout."""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from cogito_common import CogitoError, hash_json


def _safe(path: str) -> bool:
    value = PurePosixPath(path)
    return (bool(path) and not value.is_absolute() and '..' not in value.parts
            and '.' not in value.parts and '\0' not in path
            and path == '/'.join(value.parts))


def _open_directory(parent_fd: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        return os.open(name, flags, dir_fd=parent_fd)


@contextmanager
def _parent_fd(root: Path, relative: str, *, create: bool):
    if not _safe(relative):
        raise CogitoError('isolated Start Gate contains an unsafe control path')
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    descriptors = []
    try:
        current = os.open(root, flags)
        descriptors.append(current)
        for component in PurePosixPath(relative).parts[:-1]:
            current = _open_directory(current, component, create=create)
            descriptors.append(current)
        yield current, PurePosixPath(relative).name
    except OSError as exc:
        raise CogitoError(f'isolated Start Gate path must have real directory parents: {relative}: {exc}') from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def _read_regular(root: Path, relative: str) -> tuple[bytes, str]:
    with _parent_fd(root, relative, create=False) as (parent, name):
        flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
        try:
            descriptor = os.open(name, flags, dir_fd=parent)
            try:
                info = os.fstat(descriptor)
                if not stat.S_ISREG(info.st_mode):
                    raise CogitoError('isolated Start Gate controls must be regular files')
                chunks = []
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    chunks.append(chunk)
                return b''.join(chunks), '100755' if info.st_mode & 0o111 else '100644'
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise CogitoError(f'cannot safely read isolated Start Gate control {relative}: {exc}') from exc


def _write_regular(root: Path, relative: str, content: bytes, mode: str) -> None:
    with _parent_fd(root, relative, create=True) as (parent, name):
        try:
            try:
                existing = os.stat(name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if not stat.S_ISREG(existing.st_mode):
                    raise CogitoError('isolated Start Gate refuses a symlink, directory, or special target')
                os.unlink(name, dir_fd=parent)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
            descriptor = os.open(name, flags, 0o600, dir_fd=parent)
            try:
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError('short write')
                    view = view[written:]
                os.fchmod(descriptor, 0o755 if mode == '100755' else 0o644)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as exc:
            raise CogitoError(f'cannot safely write isolated Start Gate control {relative}: {exc}') from exc


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
        content, mode = _read_regular(root, relative)
        result[relative] = {'hash': hashlib.sha256(content).hexdigest(), 'mode': mode}
    return result


def _git(root: Path, *args: str):
    try:
        return subprocess.run(['git', '-C', str(root), *args], check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f'cannot prepare isolated Start Gate checkout: {exc}') from exc


def _registered(root: Path, directory: Path) -> bool:
    output = _git(root, 'worktree', 'list', '--porcelain')
    wanted = str(directory.resolve())
    return any(line.startswith('worktree ') and str(Path(line[9:]).resolve()) == wanted
               for line in output.splitlines())


def _cleanup_checkout(root: Path, directory: Path, added: bool) -> None:
    if added:
        try:
            result = subprocess.run(
                ['git', '-C', str(root), 'worktree', 'remove', '--force', str(directory)],
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise CogitoError(f'cannot clean isolated Start Gate worktree: {exc}') from exc
        if result.returncode != 0:
            detail = result.stderr.strip()
            raise CogitoError('cannot clean isolated Start Gate worktree: '
                              + (detail or 'git worktree remove failed'))
        if _registered(root, directory):
            raise CogitoError('isolated Start Gate worktree remains registered after cleanup')
    if directory.exists() or directory.is_symlink():
        try:
            if directory.is_symlink():
                directory.unlink()
            else:
                shutil.rmtree(directory)
        except OSError as exc:
            raise CogitoError(f'cannot remove isolated Start Gate directory: {exc}') from exc
    if directory.exists() or directory.is_symlink():
        raise CogitoError('isolated Start Gate directory remains after cleanup')


@contextmanager
def checkout(root: Path, head: str, controls):
    key = hashlib.sha256((str(root.resolve()) + '\0' + head + '\0'
                          + hash_json(controls)).encode('utf-8')).hexdigest()[:24]
    directory = Path(tempfile.gettempdir()) / ('cogito-rp-start-' + key)
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise CogitoError('previous isolated Start Gate cleanup is unresolved; '
                          f'inspect Git worktree registry and {directory}') from exc
    except OSError as exc:
        raise CogitoError(f'cannot create isolated Start Gate directory: {exc}') from exc
    added = False
    try:
        _git(root, 'worktree', 'add', '--detach', str(directory), head)
        added = True
        for relative, entry in controls.items():
            content, mode = _read_regular(root, relative)
            if (hashlib.sha256(content).hexdigest() != entry['hash']
                    or mode != entry['mode']):
                raise CogitoError('isolated Start Gate source changed after manifest capture')
            _write_regular(directory, relative, content, mode)
        yield directory
    finally:
        _cleanup_checkout(root, directory, added)


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
