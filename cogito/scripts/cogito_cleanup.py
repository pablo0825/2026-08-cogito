"""Conservative, best-effort removal of accepted runs' disposable worktrees."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_contracts import package_hash
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


def _pin(store, current, final, head, *, read_only=False):
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
            if not read_only:
                git.run('update-ref', ref, oid, '0' * len(oid))
        else:
            if existing != oid:
                raise CogitoError('cleanup evidence ref changed')
        pinned.append(oid)
    return pinned


def read_run_references(root, run_id):
    """Read only supported reference facts; never repair another Run's cache."""
    from cogito_run_store import RunStore
    from cogito_slice_inventory import read_accepted_source
    from cogito_slice_inventory_compat import EVENT

    other = RunStore(root, run_id)
    if other.events_path.resolve() != other.events_path or other.run_dir.resolve() != other.run_dir:
        raise CogitoError('reference history traverses a symlink')
    def frozen_package(state):
        path = other.root / state['package_path']
        if path.resolve() != path:
            raise CogitoError('reference Package traverses a symlink')
        return other._approved_package_from_state(state)
    events = other._events.read()  # Verify the original chain before compatibility projection.
    if any(e['type'] == 'finalization-complete' for e in events):
        source = read_accepted_source(root, run_id, workflow=other.workflow,
                                      event_repository=other._events,
                                      package_fallback=frozen_package)
        state, package = source['state'], source['package']
    else:
        if any(e['type'] == EVENT for e in events):
            raise CogitoError('historical compatibility requires accepted history')
        state = other._events.snapshot().state
        package = frozen_package(state) if state.get('package_hash') else {}
    if state.get('run_id') != run_id or (package and package.get('run_id') != run_id):
        raise CogitoError('reference history belongs to another Run')
    references = list(state.get('tasks', {}).values())
    references += [item['worker'] for item in package.get('slices', [])]
    references += [{'worktree': path, 'branch': binding.get('branch')}
                   for path, binding in state.get('carryover_worktrees', {}).items()]
    return references


def _other_use(store, path, branch):
    for registered in _registrations(GitRepository(store.root)):
        nested = Path(registered).resolve()
        if nested != path and nested.is_relative_to(path):
            raise CogitoError('another registered worktree is nested inside this worktree')
    if any(item['state'] not in RP_TERMINAL for item in replans(store.root)):
        raise CogitoError('an active replan may still use worktrees')
    if any(item['state'] not in DP_TERMINAL for item in dispositions(store.root)):
        raise CogitoError('an active disposition may still use worktrees')
    for directory in (store.root / '.cogito' / 'runs').iterdir():
        if directory.name == store.run_id or not directory.is_dir():
            continue
        if directory.resolve() != directory:
            raise CogitoError('another runtime traverses a symlink')
        try:
            references = read_run_references(store.root, directory.name)
        except (CogitoError, OSError, KeyError, TypeError, ValueError) as exc:
            raise CogitoError(f'reference_unknown: {directory.name}: {exc}') from exc
        for item in references:
            candidate = item.get('worktree')
            referenced = (store.root / candidate).resolve() if candidate else None
            if item.get('branch') == branch or (referenced is not None and referenced != store.root and
                    (referenced.is_relative_to(path) or path.is_relative_to(referenced))):
                raise CogitoError('another run references this worktree or branch')


def _clean(git, path):
    for entry in git.run_at(path, 'ls-files', '-v', '-z').split('\0'):
        if entry and (entry[0].islower() or entry[0] == 'S'):
            raise CogitoError('worktree index hides tracked content from status')
    if git.run_at(path, '--no-optional-locks', 'status', '--porcelain', '--untracked-files=all'):
        raise CogitoError('worktree contains tracked changes or untracked files')
    for name in git.run_at(path, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z').split('\0'):
        if name and not any(part in _CACHE_DIRS for part in Path(name).parts[:-1]):
            raise CogitoError('worktree contains unknown ignored data')


def _owned_task(task, branch, package):
    if task.get('status') != 'integrated':
        return False
    if task.get('branch'):
        return task['branch'] == branch
    # Reused RP tasks have a Gate-recorded adoption instead of a Worker lease.
    adoption = task.get('adoption') or {}
    return (adoption.get('successor_run_id') == package['run_id']
            and adoption.get('successor_package_hash') == package_hash(package)
            and adoption.get('target_task_id') == task.get('id'))


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


def cleaned_content_tree(store, path) -> str | None:
    """Use the retained clean HEAD for existing RP evidence-adoption checks."""
    if not cleaned_worktree(store, path):
        return None
    item = load_json(_receipt_path(store))['worktrees'][str(path)]
    return GitRepository(store.root).run('rev-parse', item['head'] + '^{tree}')


def _candidate(store, worker, current, final, package, git):
    """Shared safety assessment. Apply calls this again under its original locks."""
    path = _managed(store, store.root / worker['worktree'])
    if cleaned_worktree(store, path):
        return None
    registration = _registrations(git).get(str(path))
    branch = worker['branch']
    leases = [task for task in current['tasks'].values() if task.get('worktree') == str(path)]
    if not leases or any(not _owned_task(task, branch, package) for task in leases):
        raise CogitoError('recorded task leases do not establish completed ownership')
    if not registration or registration.get('branch') != 'refs/heads/' + branch or 'locked' in registration or 'prunable' in registration:
        raise CogitoError('Git worktree registration differs or is locked')
    if git.run_at(path, 'rev-parse', '--path-format=absolute', '--git-common-dir') != git.run('rev-parse', '--path-format=absolute', '--git-common-dir'):
        raise CogitoError('worktree belongs to another repository')
    _other_use(store, path, branch)
    head = git.run_at(path, 'rev-parse', 'HEAD')
    git.run('merge-base', '--is-ancestor', head, final['payload']['final_commit'])
    _clean(git, path)
    return path, head


def assess_cleanup(store):
    """Advisory current blockers; no registry locks, refs, receipts or removals."""
    from types import SimpleNamespace
    from cogito_execution_registry import observe_read_only
    result = {'removable': [], 'retained': [], 'observation_only': True}
    try:
        state = store._events.snapshot().state
        view = SimpleNamespace(root=store.root, run_id=store.run_id, run_dir=store.run_dir,
            _events=store._events, load=lambda: state,
            approved_package=lambda: store._approved_package_from_state(state),
            completion_report=lambda: store._load_completion_report(state))
        if not observe_read_only(store.root, store.run_id, allow_external_receipts=True)['quiescent']:
            raise CogitoError('executors have not terminated')
        current, final = _final(view)
        package, git = view.approved_package(), GitRepository(store.root)
        receipt_path = _receipt_path(view)
        if receipt_path.exists():
            receipt = load_json(receipt_path)
            if receipt.get('run_id') != store.run_id or receipt.get('accepted_event_hash') != final['event_hash']:
                raise CogitoError('cleanup receipt does not match acceptance')
        for worker in (item['worker'] for item in package.get('slices', [])):
            try:
                candidate = _candidate(view, worker, current, final, package, git)
                if candidate is not None:
                    path, head = candidate
                    _pin(view, current, final, head, read_only=True)
                    result['removable'].append(str(path))
            except (CogitoError, OSError, KeyError, TypeError, ValueError) as exc:
                result['retained'].append({'worktree': str(store.root / worker['worktree']), 'reason': str(exc)[:600]})
    except (CogitoError, OSError, KeyError, TypeError, ValueError, IndexError) as exc:
        result['retained'].append({'reason': str(exc)[:600]})
    return result


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
                    candidate = _candidate(store, worker, current, final, package, git)
                    if candidate is None:
                        continue
                    path, head = candidate
                    branch = worker['branch']
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
