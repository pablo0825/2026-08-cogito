"""Versioned RP product snapshots and separately validated mutable runtime.

Raw Git trees remain forensic evidence. Only explicitly owned journals, caches,
drafts and empty synchronization files are removed from the product comparison.
Worker trees and immutable source artifacts are never covered by a directory-wide
runtime exception. The same classification applies to legacy raw snapshots.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cogito_common import CogitoError
from cogito_events import read_events
from cogito_product_snapshot import (
    git_bytes,
    sha256_digest,
    tree_entries,
    tree_without_paths,
)


def _git(root: Path, *args: str, env=None, data=None) -> bytes:
    """Compatibility wrapper for RP callers while mechanics stay neutral."""
    return git_bytes(
        root, *args, env=env, data=data, error_context='compare RP snapshot',
    )


def entries(root: Path, tree: str) -> dict[str, tuple[str, str]]:
    """Compatibility wrapper for existing RP and toolchain imports."""
    return tree_entries(root, tree, error_context='compare RP snapshot')


class ReplanRuntime:
    VERSION = 1

    def __init__(self, root: Path, state: dict[str, Any], protected=()):
        self.root = root
        self.source = f".cogito/runs/{state['source_run_id']}"
        self.successor = f".cogito/runs/{state['successor_run_id']}"
        self.replan = f".cogito/replans/{state['replan_id']}"
        self.logs = {base + '/events.jsonl' for base in (self.source, self.successor, self.replan)}
        self.caches = {base + '/state.json' for base in (self.source, self.successor, self.replan)}
        self.locks = {path + '.lock' for path in self.logs} | {'.cogito/project-mutation.lock'}
        self.drafts = (self.successor + '/drafts/', self.replan + '/drafts/')
        self.protected = set(protected)

    def role(self, path: str) -> str | None:
        if path in self.protected:
            return None
        if path in self.logs:
            return 'journal'
        if path in self.caches:
            return 'cache'
        if path in self.locks:
            return 'lock'
        if path.startswith(self.drafts):
            return 'draft'
        return None

    def safe_path(self, relative: str) -> Path:
        path = self.root / relative
        if path.resolve() != path:
            raise CogitoError(f'RP runtime must not traverse symlinks: {relative}')
        return path

    def log_bindings(self) -> dict[str, Any]:
        bindings = {}
        for relative in self.locks:
            path = self.safe_path(relative)
            if path.exists() and (not path.is_file() or path.read_bytes()):
                raise CogitoError(f'RP synchronization file must be empty: {relative}')
        for relative in sorted(self.logs):
            path = self.safe_path(relative)
            events = read_events(path)
            if events:
                content = path.read_bytes()
                bindings[relative] = dict(size=len(content), sha256=sha256_digest(content),
                                          sequence=len(events), event_hash=events[-1]['event_hash'])
        return bindings

    def assert_logs(self, bindings: dict[str, Any]) -> None:
        if not isinstance(bindings, dict):
            raise CogitoError('invalid RP runtime journal bindings')
        for relative, binding in bindings.items():
            if relative not in self.logs or not isinstance(binding, dict):
                raise CogitoError('invalid RP runtime journal binding')
            events = read_events(self.safe_path(relative))
            size, count = binding.get('size'), binding.get('sequence')
            if type(size) is not int or size < 0 or type(count) is not int or count < 1:
                raise CogitoError('invalid RP runtime journal binding')
            content = self.safe_path(relative).read_bytes() if events else b''
            if (len(content) < size or sha256_digest(content[:size]) != binding.get('sha256')
                    or len(events) < count or events[count - 1]['event_hash'] != binding.get('event_hash')):
                raise CogitoError(f'RP runtime event history changed: {relative}')

    def source_files(self) -> dict[str, Any]:
        """Freeze source evidence/registry even when Git ignores its directory."""
        result = {}
        directory = self.safe_path(self.source)
        for path in sorted(directory.rglob('*')):
            relative = path.relative_to(self.root).as_posix()
            self.safe_path(relative)
            if path.is_file() and self.role(relative) is None:
                result[relative] = dict(sha256=sha256_digest(path.read_bytes()), mode=path.stat().st_mode & 0o777)
        return result

    def product_tree(self, tree: str, *, worker_links=(), immutable_files=()) -> str:
        removed = []
        for relative, (mode, oid) in entries(self.root, tree).items():
            role = self.role(relative)
            if role:
                if mode not in {'100644', '100755'}:
                    raise CogitoError(f'RP runtime must be a regular file: {relative}')
                self.safe_path(relative)
                if role == 'journal':
                    content = _git(self.root, 'cat-file', 'blob', oid)
                    live = self.safe_path(relative)
                    read_events(live)
                    if (content and not content.endswith(b'\n')) or not live.is_file() or not live.read_bytes().startswith(content):
                        raise CogitoError(f'RP runtime staged event history changed: {relative}')
                if role == 'lock' and _git(self.root, 'cat-file', 'blob', oid):
                    raise CogitoError(f'RP synchronization file must be empty: {relative}')
                removed.append(relative)
            elif relative in immutable_files:
                if mode not in {'100644', '100755'}:
                    raise CogitoError(f'source runtime evidence must be a regular file: {relative}')
                removed.append(relative)
            elif relative in worker_links:
                if mode != '160000' or oid != worker_links[relative]:
                    raise CogitoError('successor worktree must remain a separately verified Git worktree')
                removed.append(relative)
        if not removed:
            return tree
        return tree_without_paths(
            self.root,
            tree,
            removed,
            temporary_prefix='cogito-rp-product-',
            error_context='compare RP snapshot',
        )

    def worker_links(self, worktrees) -> dict[str, str]:
        return {Path(path).relative_to(self.root).as_posix(): worktrees[path]['head']
                for path in worktrees if Path(path) != self.root}

    def capture(self, delivery: dict[str, Any], worktrees=()) -> dict[str, Any]:
        frozen = self.source_files()
        for field in ('index_tree', 'content_tree'):
            self.assert_frozen_tree(delivery[field], set(frozen))
        return dict(version=self.VERSION, logs=self.log_bindings(), source_files=frozen,
                    product_trees={field: self.product_tree(delivery[field], immutable_files=frozen,
                                                           worker_links=self.worker_links(worktrees))
                                   for field in ('index_tree', 'content_tree')})

    def assert_legacy_logs(self, tree: str) -> None:
        """An old raw tree anchors exact bytes, even after runtime is ignored."""
        saved_entries = entries(self.root, tree)
        for relative in self.logs:
            if relative not in saved_entries:
                continue
            mode, oid = saved_entries[relative]
            if mode not in {'100644', '100755'}:
                raise CogitoError('invalid legacy RP journal mode')
            saved = _git(self.root, 'cat-file', 'blob', oid)
            path = self.safe_path(relative)
            read_events(path)
            if (saved and not saved.endswith(b'\n')) or not path.is_file() or not path.read_bytes().startswith(saved):
                raise CogitoError(f'RP runtime event history changed: {relative}')

    def assert_snapshot(self, saved: dict[str, Any]) -> set[str]:
        runtime = saved.get('runtime')
        frozen = set()
        if runtime is not None:
            if (not isinstance(runtime, dict) or type(runtime.get('version')) is not int
                    or runtime.get('version') != self.VERSION
                    or not {'logs', 'source_files', 'product_trees'} <= runtime.keys()
                    or not isinstance(runtime.get('source_files'), dict)):
                raise CogitoError('unsupported RP runtime snapshot version')
            self.assert_logs(runtime['logs'])
            if self.source_files() != runtime['source_files']:
                raise CogitoError('source runtime evidence drifted since stop checkpoint')
            frozen.update(runtime['source_files'])
            expected = {field: self.product_tree(saved['delivery'][field], immutable_files=frozen,
                                                 worker_links=self.worker_links(saved['worktrees']))
                        for field in ('index_tree', 'content_tree')}
            if runtime['product_trees'] != expected:
                raise CogitoError('RP product snapshot does not match preserved raw trees')
        # Validate both old raw trees, including staged journal content. Keeping
        # them untouched preserves prior snapshot/proposal hashes and approvals.
        for field in ('index_tree', 'content_tree'):
            self.assert_legacy_logs(saved['delivery'][field])
            # Source artifacts omitted by a later ignore rule still have to
            # match their old raw blob. This is verification, not an exemption.
            for relative, (mode, oid) in entries(self.root, saved['delivery'][field]).items():
                if not relative.startswith(self.source + '/') or self.role(relative):
                    continue
                path = self.safe_path(relative)
                if (mode not in {'100644', '100755'} or not path.is_file()
                        or path.read_bytes() != _git(self.root, 'cat-file', 'blob', oid)
                        or bool(path.stat().st_mode & 0o111) != (mode == '100755')):
                    raise CogitoError(f'source runtime evidence drifted: {relative}')
                frozen.add(relative)
        return frozen

    def assert_frozen_tree(self, tree: str, frozen: set[str]) -> None:
        """A staged artifact must match the independently verified live file."""
        for relative, (mode, oid) in entries(self.root, tree).items():
            if relative in frozen:
                path = self.safe_path(relative)
                if (mode not in {'100644', '100755'} or not path.is_file()
                        or _git(self.root, 'cat-file', 'blob', oid) != path.read_bytes()
                        or bool(path.stat().st_mode & 0o111) != (mode == '100755')):
                    raise CogitoError(f'staged source runtime evidence drifted: {relative}')

    def assert_index(self, before: str, after: str, frozen, workers) -> None:
        """Separately verified live files do not authorize staged deletion."""
        old, new = entries(self.root, before), entries(self.root, after)
        for relative, binding in old.items():
            if relative in frozen or relative in workers:
                if new.get(relative) != binding:
                    raise CogitoError(f'staged source runtime binding drifted: {relative}')
            elif relative in self.logs:
                current = new.get(relative)
                if current is None or current[0] != binding[0]:
                    raise CogitoError(f'staged RP journal was removed or changed mode: {relative}')
                previous_bytes = _git(self.root, 'cat-file', 'blob', binding[1])
                current_bytes = _git(self.root, 'cat-file', 'blob', current[1])
                if not current_bytes.startswith(previous_bytes):
                    raise CogitoError(f'staged RP journal history changed: {relative}')
