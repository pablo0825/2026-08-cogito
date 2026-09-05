"""Conservative, best-effort removal of accepted runs' disposable worktrees."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_disposition_scope import dispositions
from cogito_disposition_state import TERMINAL as DP_TERMINAL
from cogito_execution_registry import quiescent_guard
from cogito_git import GitRepository
from cogito_replan_lock import project_lock, replans
from cogito_replan_state import TERMINAL as RP_TERMINAL

_CACHE_DIRS = {'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache'}
_OBJECT = re.compile(r'[0-9a-f]{40}|[0-9a-f]{64}')


def _registrations(git):
    entries = {}
    for record in git.run('worktree', 'list', '--porcelain', '-z').split('\0\0'):
        fields = dict(field.partition(' ')[::2] for field in record.split('\0') if field)
        if 'worktree' in fields:
            entries[fields['worktree']] = fields
    return entries


def _final(store):
    current = store.load()
    if current['state'] != 'accepted':
        raise CogitoError('cleanup requires accepted run')
    final = [event for event in store._events.read() if event['type'] == 'finalization-complete'][-1]
    # Revalidate the immutable, committed Result before reclaiming its source.
    store.completion_report()
    return current, final


def _managed(store, path):
    path = Path(path)
    base = store.root / '.cogito' / 'worktrees'
    if not path.is_absolute() or path.resolve() != path or not path.is_relative_to(base) or path == base:
        raise CogitoError('worktree is outside the managed directory or traverses a symlink')
    if Path.cwd().resolve().is_relative_to(path):
        raise CogitoError('worktree is the current working directory')
    return path


def _receipt_path(store):
    path = store.run_dir / 'cleanup.json'
    if path.resolve() != path:
        raise CogitoError('cleanup receipt must not traverse symlinks')
    return path


def _objects(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from _objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _objects(item)
    elif isinstance(value, str) and _OBJECT.fullmatch(value):
        yield value


def _required_objects(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if (key.endswith(('_commit', '_tree')) or key in {'head', 'review_head'}) and isinstance(item, str) and _OBJECT.fullmatch(item):
                yield item
            yield from _required_objects(item)
    elif isinstance(value, list):
        for item in value:
            yield from _required_objects(item)


def _pin(store, current, final, head):
    git = GitRepository(store.root)
    values = [store._events.read(), current, final, {'head_commit': head}]
    for evidence_path, ledger in current.get('evidence', {}).items():
        evidence = load_json(Path(evidence_path))
        if hash_json(evidence) != ledger['evidence_hash']:
            raise CogitoError('recorded evidence changed')
        values.append(evidence)
    required = set(_required_objects(values))
    pinned = []
    for oid in sorted(set(_objects(values))):
        try:
            kind = git.run('cat-file', '-t', oid)
        except CogitoError:
            if oid in required:
                raise CogitoError('recorded Git evidence object is unavailable')
            continue  # Contract and content hashes are not necessarily Git objects.
        if kind not in {'commit', 'tree', 'blob', 'tag'}:
            continue
        ref = f'refs/cogito/cleanup/{store.run_id}/{oid}'
        try:
            existing = git.run('show-ref', '--verify', '--hash', ref)
        except CogitoError:
            git.run('update-ref', ref, oid, '0' * len(oid))
        else:
            if existing != oid:
                raise CogitoError('cleanup evidence ref changed')
        pinned.append(oid)
    return pinned


def _other_use(store, path, branch):
    from cogito_run_store import RunStore
    if any(item['state'] not in RP_TERMINAL for item in replans(store.root)):
        raise CogitoError('an active replan may still use worktrees')
    if any(item['state'] not in DP_TERMINAL for item in dispositions(store.root)):
        raise CogitoError('an active disposition may still use worktrees')
    for directory in (store.root / '.cogito' / 'runs').iterdir():
        if directory.name == store.run_id or not directory.is_dir():
            continue
        if directory.resolve() != directory:
            raise CogitoError('another runtime traverses a symlink')
        other = RunStore(store.root, directory.name)
        state = other.load()
        references = list(state.get('tasks', {}).values())
        if state.get('package_hash'):
            references += [item['worker'] for item in other.approved_package().get('slices', [])]
        for item in references:
            candidate = item.get('worktree')
            if item.get('branch') == branch or (candidate and (store.root / candidate).resolve() == path):
                raise CogitoError('another run references this worktree or branch')


def _clean(git, path):
    for entry in git.run_at(path, 'ls-files', '-v', '-z').split('\0'):
        if entry and (entry[0].islower() or entry[0] == 'S'):
            raise CogitoError('worktree index hides tracked content from status')
    if git.run_at(path, 'status', '--porcelain', '--untracked-files=all'):
        raise CogitoError('worktree contains tracked changes or untracked files')
    for name in git.run_at(path, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').split('\0'):
        if name and not any(part in _CACHE_DIRS for part in Path(name).parts[:-1]):
            raise CogitoError('worktree contains unknown ignored data')


def cleaned_worktree(store, path) -> bool:
    """Prove an absent historical lease was covered by accepted cleanup."""
    try:
        path = _managed(store, path)
        current, final = _final(store)
        data = load_json(_receipt_path(store))
        item = data['worktrees'][str(path)]
        git = GitRepository(store.root)
        if (data['run_id'] != store.run_id or data['accepted_event_hash'] != final['event_hash']
                or item['final_commit'] != final['payload']['final_commit']
                or path.exists() or str(path) in _registrations(git)):
            return False
        leases = [task for task in current['tasks'].values() if task.get('worktree') == str(path)]
        workers = [s['worker'] for s in store.approved_package().get('slices', [])]
        if not leases or not any((store.root / w['worktree']) == path and w['branch'] == item['branch'] for w in workers):
            return False
        git.run('merge-base', '--is-ancestor', item['head'], item['final_commit'])
        if item['head'] not in item['pinned_objects']:
            return False
        for oid in item['pinned_objects']:
            if git.run('show-ref', '--verify', '--hash', f'refs/cogito/cleanup/{store.run_id}/{oid}') != oid:
                return False
        return True
    except (CogitoError, OSError, KeyError, TypeError, ValueError, IndexError):
        return False


def cleanup_accepted(store) -> dict[str, Any]:
    """Never changes acceptance. Call again after resolving a retained reason."""
    result: dict[str, Any] = {'removed': [], 'retained': []}
    try:
        with project_lock(store.root), quiescent_guard(store.root, store.run_id, allow_external_receipts=True) as quiet:
            if not quiet:
                raise CogitoError('executors have not terminated')
            current, final = _final(store)
            final_commit = final['payload']['final_commit']
            package = store.approved_package()
            git = GitRepository(store.root)
            receipt_path = _receipt_path(store)
            receipt = load_json(receipt_path) if receipt_path.exists() else {
                'run_id': store.run_id, 'accepted_event_hash': final['event_hash'], 'worktrees': {}}
            if receipt.get('run_id') != store.run_id or receipt.get('accepted_event_hash') != final['event_hash']:
                raise CogitoError('cleanup receipt does not match acceptance')
            for worker in (item['worker'] for item in package.get('slices', [])):
                raw = store.root / worker['worktree']
                try:
                    path = _managed(store, raw)
                    if cleaned_worktree(store, path):
                        continue
                    registration = _registrations(git).get(str(path))
                    branch = worker['branch']
                    leases = [task for task in current['tasks'].values() if task.get('worktree') == str(path)]
                    if not leases or any(task.get('branch') != branch or task.get('status') != 'integrated' for task in leases):
                        raise CogitoError('recorded task leases do not establish completed ownership')
                    if not registration or registration.get('branch') != 'refs/heads/' + branch or 'locked' in registration or 'prunable' in registration:
                        raise CogitoError('Git worktree registration differs or is locked')
                    if git.run_at(path, 'rev-parse', '--path-format=absolute', '--git-common-dir') != git.run('rev-parse', '--path-format=absolute', '--git-common-dir'):
                        raise CogitoError('worktree belongs to another repository')
                    _other_use(store, path, branch)
                    head = git.run_at(path, 'rev-parse', 'HEAD')
                    git.run('merge-base', '--is-ancestor', head, final_commit)
                    _clean(git, path)
                    pinned = _pin(store, current, final, head)
                    receipt['worktrees'][str(path)] = {'branch': branch, 'head': head,
                        'final_commit': final_commit, 'pinned_objects': pinned}
                    # Save proof first: a crash after removal is safely recoverable.
                    atomic_write_json(receipt_path, receipt)
                    git.run('worktree', 'remove', str(path))
                    result['removed'].append(str(path))
                except (CogitoError, OSError, KeyError, TypeError, ValueError) as exc:
                    result['retained'].append({'worktree': str(raw), 'reason': str(exc)})
    except (CogitoError, OSError, KeyError, TypeError, ValueError, IndexError) as exc:
        result['retained'].append({'reason': str(exc)})
    return result
