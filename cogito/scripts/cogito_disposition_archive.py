"""Pin stopped artifacts and reversibly release only their saved delivery paths.

Refs can be exported with ``git archive <ref>``. Worker checkouts and delivery
HEAD never move. The caller must hold the disposition/project mutation lock.
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

from cogito_common import CogitoError, atomic_write_json, hash_json, load_json
from cogito_evidence_binding import capture_index_and_worktree_trees

_GRAPH = 'docs/cogito/project-graph.json'


def _git(root, *args, data=None):
    try:
        return subprocess.run(['git', '-C', str(root), *args], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError('disposition archive Git operation failed: '+str(exc)) from exc


def _text(root, *args):
    return _git(root, *args).decode().strip()


def _directory(root, disposition_id):
    if not re.fullmatch(r'DP-[A-Za-z0-9._-]+', disposition_id):
        raise CogitoError('unsafe disposition identifier')
    directory = root/'.cogito/dispositions'/disposition_id
    for parent in (root/'.cogito', root/'.cogito/dispositions', directory):
        if parent.is_symlink(): raise CogitoError('disposition archive directory cannot be a symlink')
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _entries(root, tree):
    entries = {}
    for record in _git(root, 'ls-tree', '-r', '-z', tree).split(b'\0'):
        if not record: continue
        metadata, name = record.split(b'\t', 1)
        mode, kind, oid = metadata.decode().split()
        entries[os.fsdecode(name)] = [mode, kind, oid]
    return entries


def _checkout_path(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or relative.startswith('/') or any(p in {'.', '..', '.git', '.cogito'} for p in parts):
        raise CogitoError('unsafe archive product path: '+relative)
    path = root
    for part in parts[:-1]:
        path /= part
        if path.is_symlink(): raise CogitoError('archive path has symlink parent: '+relative)
    return root/relative


def _matches(path, patterns):
    return any(pattern in {'.', '**', '*'} or fnmatchcase(path, pattern)
        or path == pattern.rstrip('/') or path.startswith(pattern.rstrip('/')+'/') for pattern in patterns)


def _locations(root, snapshot):
    common = _text(root, 'rev-parse', '--path-format=absolute', '--git-common-dir')
    locations = [('delivery', root, snapshot['delivery'])]
    for location, saved in sorted(snapshot.get('worktrees', {}).items()):
        worker = Path(location).resolve()
        try: worker.relative_to(root)
        except ValueError as exc: raise CogitoError('archive worker escapes project') from exc
        if _text(worker, 'rev-parse', '--path-format=absolute', '--git-common-dir') != common:
            raise CogitoError('archive worker is not in source repository')
        locations.append(('worker-'+hash_json(str(worker))[:16], worker, saved))
    return locations


def _validate_manifest(root, disposition_id, snapshot, binding, manifest, locations):
    if (not isinstance(manifest, dict) or set(manifest) != {'root', 'snapshot_hash', 'refs'}
            or manifest.get('snapshot_hash') != binding or manifest.get('root') != str(root)
            or not isinstance(manifest.get('refs'), list)):
        raise CogitoError('archive snapshot binding changed')
    expected = {}
    for label, location, saved in locations:
        trees = {'head': _text(location, 'rev-parse', saved['head']+'^{tree}'),
                 'index': saved['index_tree'], 'content': saved['content_tree']}
        for kind, tree in trees.items():
            ref = f'refs/cogito/dispositions/{disposition_id}/{binding}/{label}/{kind}'
            expected[ref] = (str(location), saved['head'], tree)
    actual = {}
    for entry in manifest['refs']:
        if (not isinstance(entry, dict)
                or set(entry) != {'repository', 'ref', 'commit', 'tree'}
                or any(not isinstance(entry.get(key), str)
                       for key in ('repository', 'ref', 'commit', 'tree'))
                or entry['ref'] in actual):
            raise CogitoError('archive manifest contains invalid refs')
        actual[entry['ref']] = entry
    if set(actual) != set(expected):
        raise CogitoError('archive manifest does not contain the exact snapshot refs')
    for ref, (repository, parent, tree) in expected.items():
        entry = actual[ref]
        if entry['repository'] != repository or entry['tree'] != tree:
            raise CogitoError('archive manifest ref binding changed')
        location = Path(repository)
        try:
            resolved = _text(location, 'rev-parse', '--verify', ref+'^{commit}')
            parents = _text(location, 'rev-list', '--parents', '-n', '1', entry['commit']).split()
            actual_tree = _text(location, 'rev-parse', entry['commit']+'^{tree}')
        except CogitoError as exc:
            raise CogitoError('pinned archive ref changed') from exc
        if (resolved != entry['commit'] or parents != [entry['commit'], parent]
                or actual_tree != tree):
            raise CogitoError('pinned archive ref changed')


def pin_snapshot(root, disposition_id, snapshot):
    """Keep source trees reachable through immutable refs before cancellation."""
    root = Path(root).resolve()
    directory = _directory(root, disposition_id)
    binding = hash_json(snapshot)
    archive_directory = directory/'archives'
    if archive_directory.is_symlink(): raise CogitoError('archive directory cannot be a symlink')
    manifest_path = archive_directory/(binding+'.json')
    locations = _locations(root, snapshot)
    if manifest_path.exists():
        manifest = load_json(manifest_path)
        _validate_manifest(root, disposition_id, snapshot, binding, manifest, locations)
        return manifest
    # Preflight every checkout before publishing any ref.
    for _, location, saved in locations:
        if _text(location, 'rev-parse', 'HEAD') != saved['head']:
            raise CogitoError('archive checkout HEAD changed')
        if 'branch' in saved and _text(location, 'branch', '--show-current') != saved['branch']:
            raise CogitoError('archive checkout branch changed')
        for tree in ('index_tree', 'content_tree'):
            if _text(location, 'cat-file', '-t', saved[tree]) != 'tree':
                raise CogitoError('archive requires saved tree objects')
    refs = []
    for label, location, saved in locations:
        for kind, tree in [('head', _text(location, 'rev-parse', saved['head']+'^{tree}')),
                           ('index', saved['index_tree']), ('content', saved['content_tree'])]:
            ref = f'refs/cogito/dispositions/{disposition_id}/{binding}/{label}/{kind}'
            existing = subprocess.run(['git','-C',str(location),'rev-parse','--verify',ref], capture_output=True)
            if existing.returncode == 0:
                commit = existing.stdout.decode().strip()
                if (_text(location,'rev-parse',commit+'^{tree}') != tree
                        or _text(location,'rev-parse',commit+'^') != saved['head']):
                    raise CogitoError('archive ref already belongs to different snapshot')
            else:
                commit = _git(location, 'commit-tree', tree, '-p', saved['head'],
                    data=f'Cogito {disposition_id} {label} {kind} snapshot\n'.encode()).decode().strip()
                _git(location,'update-ref',ref,commit,'0'*len(commit))
            refs.append(dict(repository=str(location),ref=ref,commit=commit,tree=tree))
    manifest = dict(root=str(root), snapshot_hash=binding, refs=refs)
    atomic_write_json(manifest_path, manifest)
    _validate_manifest(root, disposition_id, snapshot, binding, manifest, locations)
    return manifest


def _work_entry(root, relative):
    path = _checkout_path(root, relative)
    if path.is_symlink():
        value, mode = os.fsencode(os.readlink(path)), '120000'
    elif path.is_file():
        value, mode = path.read_bytes(), '100755' if path.stat().st_mode & 0o111 else '100644'
    elif path.exists():
        raise CogitoError('archive product path became a directory: '+relative)
    else:
        return None
    options = ('--path='+relative,) if mode != '120000' else ()
    return [mode, 'blob', _git(root,'hash-object',*options,'--stdin',data=value).decode().strip()]


def _restore_work(root, relative, entry):
    path = _checkout_path(root, relative)
    if entry is None:
        if path.exists() or path.is_symlink(): path.unlink()
        return
    mode, kind, oid = entry
    if kind != 'blob' or mode not in {'100644','100755','120000'}:
        raise CogitoError('archive cannot release submodules or unsupported modes')
    value = (_git(root,'cat-file','blob',oid) if mode == '120000' else
             _git(root,'cat-file','--filters','--path='+relative,oid))
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically, without following symlinks or mutating hardlink peers.
    fd, temporary = tempfile.mkstemp(prefix='.cogito-release-',dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd,'wb') as stream:
            if mode != '120000':
                stream.write(value); stream.flush(); os.fsync(stream.fileno())
        if mode == '120000':
            temporary_path.unlink(); temporary_path.symlink_to(os.fsdecode(value))
        else:
            temporary_path.chmod(0o755 if mode == '100755' else 0o644)
        os.replace(temporary_path,path)
    finally:
        if temporary_path.exists() or temporary_path.is_symlink(): temporary_path.unlink()


def _release_records(root, snapshot, before_index, before_work, target):
    records = {}
    for path in sorted(set(before_index)|set(before_work)|set(target)):
        if (path == _GRAPH or path.startswith(('.cogito/','.git/'))
                or not _matches(path,snapshot['scope']['paths'])):
            continue
        if before_index.get(path) == before_work.get(path) == target.get(path):
            continue
        _checkout_path(root,path)
        for entry in (before_index.get(path),before_work.get(path),target.get(path)):
            if entry and (entry[1] != 'blob' or entry[0] not in {'100644','100755','120000'}):
                raise CogitoError('cannot release submodule path: '+path)
        records[path] = dict(index_before=before_index.get(path),
            work_before=before_work.get(path),after=target.get(path),status='pending')
    return records


def _validate_release_journal(journal, archive, saved, expected):
    if (not isinstance(journal, dict)
            or set(journal) != {'snapshot_hash', 'head', 'paths', 'completed'}
            or journal.get('snapshot_hash') != archive['snapshot_hash']
            or journal.get('head') != saved['head']
            or type(journal.get('completed')) is not bool
            or not isinstance(journal.get('paths'), dict)
            or set(journal['paths']) != set(expected)):
        raise CogitoError('release journal does not match the saved snapshot')
    for path, derived in expected.items():
        record = journal['paths'][path]
        if (not isinstance(record, dict)
                or set(record) != {'index_before', 'work_before', 'after', 'status'}
                or record.get('status') not in {'pending', 'completed'}
                or any(record.get(key) != derived[key]
                       for key in ('index_before', 'work_before', 'after'))):
            raise CogitoError('release journal path binding changed: '+path)
    if journal['completed'] and any(
            record['status'] != 'completed' for record in journal['paths'].values()):
        raise CogitoError('completed release journal contains pending paths')


def release_delivery(root, disposition_id, snapshot):
    """Restore saved scoped dirt to HEAD, retaining replayable before/after proof."""
    root = Path(root).resolve()
    directory = _directory(root, disposition_id)
    archive = pin_snapshot(root, disposition_id, snapshot)
    saved = snapshot['delivery']
    if (_text(root,'rev-parse','HEAD') != saved['head'] or
            ('branch' in saved and _text(root,'branch','--show-current') != saved['branch'])):
        raise CogitoError('delivery HEAD or branch changed before release')
    journal_path = directory/'archives'/(archive['snapshot_hash']+'.release.json')
    before_index = _entries(root,saved['index_tree'])
    before_work = _entries(root,saved['content_tree'])
    target = _entries(root,saved['head'])
    expected_records = _release_records(root, snapshot, before_index, before_work, target)
    if journal_path.exists():
        journal = load_json(journal_path)
        _validate_release_journal(journal, archive, saved, expected_records)
    else:
        index, work = capture_index_and_worktree_trees(root)
        current_index, current_work = _entries(root,index), _entries(root,work)
        for expected, actual in [(before_index,current_index),(before_work,current_work)]:
            if {k:v for k,v in expected.items() if k != _GRAPH} != {k:v for k,v in actual.items() if k != _GRAPH}:
                raise CogitoError('delivery changed after saved snapshot; release refused')
        journal = dict(snapshot_hash=archive['snapshot_hash'],head=saved['head'],
                       paths=expected_records,completed=False)
        atomic_write_json(journal_path,journal)
    # Check every path before starting or resuming a partially applied release.
    current_index = _entries(root,_text(root,'write-tree'))
    for path, record in journal['paths'].items():
        expected_index = [record['after']] if record['status']=='completed' else [record['index_before'],record['after']]
        expected_work = [record['after']] if record['status']=='completed' else [record['work_before'],record['after']]
        if current_index.get(path) not in expected_index or _work_entry(root,path) not in expected_work:
            raise CogitoError('delivery path changed during release: '+path)
    for path, record in journal['paths'].items():
        if record['status']=='completed': continue
        _restore_work(root,path,record['after'])
        entry = record['after']
        line = f'{entry[0]} {entry[2]}\t' if entry else '0 '+'0'*len(saved['head'])+'\t'
        _git(root,'update-index','--add','--remove','-z','--index-info',data=line.encode()+os.fsencode(path)+b'\0')
        record['status']='completed'
        atomic_write_json(journal_path,journal)
    journal['completed']=True
    atomic_write_json(journal_path,journal)
    return journal
