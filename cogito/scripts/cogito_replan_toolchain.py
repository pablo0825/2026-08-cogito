"""RP-only, journaled adoption of exact in-repository Cogito installations.

No directory exemption: all three Git views and live executable bytes must match
the reviewed manifest before only those exact paths leave product comparison.
"""
from __future__ import annotations

import hashlib
import stat
import sys
from pathlib import Path

from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash, validate_package_with_limits
from cogito_events import read_events
from cogito_replan_snapshot import _git, entries
from cogito_replan_toolchain_rules import (
    TOOL_ROOT, STAGES, VIEWS, REVALIDATION, differences, text, validate_binding, validate_proposal, validate_review,
)

EXECUTING_ROOT = Path(__file__).resolve().parents[1]


def _disk_files(directory):
    if directory.resolve() != directory or not directory.is_dir():
        raise CogitoError('toolchain directory must exist without symlinks')
    result = {}
    for path in sorted(directory.rglob('*')):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            raise CogitoError('toolchain must not contain symlinks: ' + relative)
        if '__pycache__' in path.relative_to(directory).parts:
            continue
        mode = path.stat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise CogitoError('toolchain must contain only regular files: ' + relative)
        result[relative] = ('100755' if mode & 0o111 else '100644', path.read_bytes())
    return result


def _execution_files(directory):
    # Bind the complete executable surface, including non-Python imports/data.
    files = {}
    for subdir in ('scripts', 'workflows'):
        files.update({subdir + '/' + p: value for p, value in _disk_files(directory / subdir).items()})
    version = directory / 'VERSION'
    if version.resolve() != version or not version.is_file():
        raise CogitoError('toolchain VERSION must be a regular file')
    files['VERSION'] = ('100755' if version.stat().st_mode & 0o111 else '100644', version.read_bytes())
    return {p: {'mode': mode, 'sha256': hashlib.sha256(data).hexdigest()}
            for p, (mode, data) in files.items()}


def execution_digest():
    """Bind the complete code and workflow surface executing the Gate."""
    return hash_json(_execution_files(EXECUTING_ROOT))


def effective_tool_digest(state):
    """Choose the approved in-project tool binding, with external-tool compatibility."""
    if state.get('toolchain'):
        return hash_json(state['toolchain']['proposal']['after'])
    saved = (state.get('snapshot') or {}).get('toolchain')
    return hash_json(saved) if saved is not None else execution_digest()


def _manifest(root, tree):
    return {path: dict(mode=mode, oid=oid) for path, (mode, oid) in entries(root, tree).items()
            if path.startswith(TOOL_ROOT + '/')}


def binding(root, delivery):
    manifests = dict(head=_manifest(root, delivery['head']),
                     index=_manifest(root, delivery['index_tree']),
                     content=_manifest(root, delivery['content_tree']))
    version = manifests['content'].get(TOOL_ROOT + '/VERSION')
    try:
        label = (_git(root, 'cat-file', 'blob', version['oid']).decode('utf-8').strip()
                 if version and version['mode'] in {'100644', '100755'} else 'unrecorded')
    except UnicodeDecodeError as exc:
        raise CogitoError('toolchain VERSION must contain UTF-8 text') from exc
    return dict(head=delivery['head'], branch=delivery['branch'], version=label, manifests=manifests)


def _required_installation(value):
    validate_binding(value)
    for name in ('VERSION', 'SKILL.md', 'scripts/cogito_gate.py', 'workflows/cogito-v3.json'):
        if TOOL_ROOT + '/' + name not in value['manifests']['content']:
            raise CogitoError('preserved toolchain installation is incomplete: ' + name)


def _live_manifest(root):
    algorithm = _git(root, 'rev-parse', '--show-object-format').decode().strip()
    result = {}
    for relative, (mode, data) in _disk_files(root / TOOL_ROOT).items():
        oid = hashlib.new(algorithm, b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        result[TOOL_ROOT + '/' + relative] = dict(mode=mode, oid=oid)
    return result


def snapshot_binding(root, delivery):
    value = binding(root, delivery)
    validate_binding(value)
    if value['manifests']['content'] != _live_manifest(root):
        raise CogitoError('toolchain files must be represented in the captured content tree, not ignored')
    return value


def assert_executing(root, expected):
    if _live_manifest(root) != expected['manifests']['content']:
        raise CogitoError('live toolchain differs from its content manifest (including ignored files)')
    actual = _execution_files(EXECUTING_ROOT)
    startup = getattr(sys.modules.get('__main__'), 'COGITO_SOURCE_BINDING', None)
    if startup is None:
        raise CogitoError('toolchain adoption and continuation require a fresh cogito_gate.py replan CLI process')
    if {str(EXECUTING_ROOT / p): item['sha256'] for p, item in actual.items()} != startup:
        raise CogitoError('executing toolchain changed in this process; restart Gate')
    for name, module in list(sys.modules.items()):
        if not name.startswith('cogito_') or module is None:
            continue
        path = getattr(module, '__file__', None)
        digest = getattr(getattr(module, '__loader__', None), 'cogito_source_hash', None)
        if not path or str(Path(path).parent) != str(EXECUTING_ROOT / 'scripts') or digest != startup.get(path):
            raise CogitoError('loaded Cogito module differs from the source-bound CLI: ' + name)
    if _execution_files(root / TOOL_ROOT) != actual:
        raise CogitoError('run the exact candidate toolchain before requesting adoption')
    return hash_json(actual)


def _candidate(store):
    from cogito_run_store import RunStore
    state = store.load()
    successor = RunStore(store.root, state['successor_run_id'])
    if not successor.events_path.exists():
        return None
    current = successor.load()
    if current.get('package_hash'):
        raise CogitoError('toolchain adoption cannot change an approved successor Package')
    saved = (current.get('planning') or {}).get('candidate')
    if not saved:
        if current.get('candidate_package_hash'):
            raise CogitoError('successor candidate snapshot is unavailable')
        return None
    from cogito_planning import validate_snapshot
    validate_snapshot(saved)
    package = saved['package']
    if current.get('candidate_package_hash') != package_hash(package):
        raise CogitoError('successor candidate differs from its recorded hash')
    validate_package_with_limits(package, successor.workflow['limits'])
    documents = [d for sl in package['slices'] for d in (sl['spec'], sl['plan'])]
    documents += package.get('source_registry', [])
    if package['shared_understanding'].get('path'):
        documents.append(package['shared_understanding'])
    for document in documents:
        successor._validate_content_hash(document['path'], document['hash'])
    return package


def _assert_scope(store, candidate):
    from cogito_disposition_scope import paths_overlap
    state = store.load()
    source = store.source().effective_package()
    for package in (source, candidate):
        if not package:
            continue
        paths = list(package.get('approved_paths', []))
        paths += [d['path'] for sl in package['slices'] for d in (sl['spec'], sl['plan'])]
        paths += [d['path'] for d in package.get('source_registry', [])]
        if package.get('shared_understanding', {}).get('path'):
            paths.append(package['shared_understanding']['path'])
        paths += [p for task in package['execution_dag']['tasks'] for p in task['paths']]
        for sl in package['slices']:
            paths += sl['worker']['allowed_paths'] + [sl['worker']['worktree']]
        if any(paths_overlap(path, TOOL_ROOT) for path in paths):
            raise CogitoError('toolchain overlaps protected product or contract scope')
    for worker in state['snapshot']['worktrees']:
        if Path(worker) == store.root:
            continue
        if paths_overlap(Path(worker).relative_to(store.root).as_posix(), TOOL_ROOT):
            raise CogitoError('toolchain overlaps a preserved Worker')


def _commits(root, before, after):
    if before['branch'] != after['branch']:
        raise CogitoError('toolchain adoption cannot change delivery branch')
    if before['head'] == after['head']:
        return []
    _git(root, 'merge-base', '--is-ancestor', before['head'], after['head'])
    rows = _git(root, 'rev-list', '--reverse', '--parents',
                before['head'] + '..' + after['head']).decode().splitlines()
    previous, commits = before['head'], []
    for row in rows:
        parts = row.split()
        if len(parts) != 2 or parts[1] != previous:
            raise CogitoError('toolchain adoption requires a linear tool-only commit history')
        changed = _git(root, 'diff', '--name-only', '--no-renames', '-z', previous, parts[0]).decode().split('\0')
        if any(path and not path.startswith(TOOL_ROOT + '/') for path in changed):
            raise CogitoError('toolchain commit contains product or control-document changes')
        validate_binding(dict(head=parts[0], branch=after['branch'], version='intermediate',
                              manifests={view: _manifest(root, parts[0]) for view in VIEWS}))
        commits.append(parts[0])
        previous = parts[0]
    if previous != after['head']:
        raise CogitoError('toolchain commit history is incomplete')
    return commits


def _compatibility(store, candidate, target):
    from cogito_contracts import materialize_contract_with_limits
    from cogito_workflow import load_workflow
    source = store.source()
    current = source.load()  # Replay actual old events with the executing projection.
    workflow = load_workflow()
    package = source.approved_package()
    amendments = [e['payload']['amendment'] for e in read_events(source.events_path)
                  if e['type'] == 'technical-amendment-added']
    effective = materialize_contract_with_limits(package, amendments, workflow['limits'])
    if current['tasks'] != store.load()['snapshot']['tasks']:
        raise CogitoError('new toolchain changes the frozen source task projection')
    if effective['effective_contract_hash'] != current['effective_contract_hash']:
        raise CogitoError('new toolchain changes the effective source contract')
    if candidate:
        validate_package_with_limits(candidate, workflow['limits'])
    return dict(schema_version=1, events=True, contracts=True, projection=True,
                workflow=True, revalidation=True, executor_hash=assert_executing(store.root, target),
                workflow_hash=hash_json(workflow), source_package_hash=package_hash(package),
                effective_contract_hash=current['effective_contract_hash'],
                candidate_package_hash=package_hash(candidate) if candidate else None,
                required_revalidation=list(REVALIDATION))


def _effective_before(store, state):
    adopted = state.get('toolchain')
    original = binding(store.root, state['snapshot']['delivery'])
    if state['snapshot'].get('toolchain', original) != original:
        raise CogitoError('toolchain snapshot does not match preserved raw trees')
    return adopted['proposal']['after'] if adopted else original


def _build(store, request):
    state = store.load()
    if state['state'] not in STAGES:
        raise CogitoError('toolchain adoption requires an unapproved, stopped RP')
    if not isinstance(request, dict) or set(request) != {'author_id', 'reason', 'tool_root'}:
        raise CogitoError('toolchain proposal requires author_id, reason and tool_root')
    if request['tool_root'] != TOOL_ROOT:
        raise CogitoError('RP toolchain adoption only supports ' + TOOL_ROOT)
    for key in ('author_id', 'reason'):
        text(request[key], key)
    candidate = _candidate(store)
    _assert_scope(store, candidate)
    before = _effective_before(store, state)
    after = binding(store.root, store._capture()['delivery'])
    for value in (before, after):
        _required_installation(value)
    commits = _commits(store.root, before, after)
    compatibility = _compatibility(store, candidate, after)
    # The override is private to generating/rechecking this exact proposal. It
    # never suppresses product, frozen artifact, Worker or event checks.
    store._assert_source({'package': candidate} if candidate else None, toolchain_binding=after)
    proposal = dict(schema_version=1, **request,
                    source_snapshot_hash=hash_json(state['snapshot']),
                    previous_toolchain_hash=(state.get('toolchain') or {}).get('proposal_hash'),
                    before=before, after=after, differences=differences(before, after),
                    commits=commits, compatibility=compatibility)
    validate_proposal(proposal, state)
    return proposal


def propose(store, request, action_id):
    wrapped = {'proposal': request}
    if store._replay(action_id, 'toolchain-propose', wrapped):
        return store.load()
    proposal = _build(store, request)
    return store._emit('toolchain-proposed', dict(proposal=proposal, proposal_hash=hash_json(proposal)),
                       action_id, 'toolchain-propose', wrapped)


def _revalidate(store):
    saved = store.load()['toolchain_proposal']
    actual = _build(store, {key: saved[key] for key in ('author_id', 'reason', 'tool_root')})
    if actual != saved:
        raise CogitoError('toolchain proposal changed; prepare and independently review a new proposal')


def review(store, value, action_id):
    request = {'review': value}
    if store._replay(action_id, 'toolchain-review', request):
        return store.load()
    state = store.load()
    if state.get('toolchain_status') != 'reviewing':
        raise CogitoError('toolchain review requires a current proposal')
    validate_review(value, state['toolchain_proposal'], state['toolchain_proposal_hash'])
    _revalidate(store)
    return store._emit('toolchain-reviewed', dict(value), action_id, 'toolchain-review', request)


def approve(store, digest, approver_id, action_id):
    request = dict(proposal_hash=digest, approver_id=approver_id)
    if store._replay(action_id, 'toolchain-approve', request):
        return store.load()
    text(approver_id, 'approver_id')
    state = store.load()
    if (state.get('toolchain_status') != 'awaiting-approval'
            or digest != state.get('toolchain_proposal_hash')):
        raise CogitoError('toolchain approval requires the independently reviewed exact proposal')
    _revalidate(store)
    # A single append is the commit point; cache-write failure is recovered by
    # replaying this action, without rewriting the snapshot or Package.
    return store._emit('toolchain-approved', request, action_id, 'toolchain-approve', request)


def assert_binding(store, state, actual_delivery, override=None, candidate=None):
    adopted = state.get('runtime_toolchain') or state.get('toolchain')
    if override is None and (state.get('toolchain_status') in {'reviewing', 'awaiting-approval'}
                             or state.get('handoff_tool_status') in {'reviewing', 'awaiting-approval'}):
        raise CogitoError('finish independent toolchain approval before continuing the RP')
    expected = override or (adopted['proposal']['after'] if adopted else None)
    if expected is None:
        return set(), state['snapshot']['delivery']
    validate_binding(expected)
    actual = binding(store.root, actual_delivery)
    if actual != expected:
        raise CogitoError('toolchain or delivery binding drifted; request a new toolchain adoption')
    assert_executing(store.root, expected)
    _assert_scope(store, candidate)
    original = binding(store.root, state['snapshot']['delivery'])
    paths = set()
    for view in VIEWS:
        paths.update(original['manifests'][view])
        paths.update(expected['manifests'][view])
    return paths, expected


def reject(store, digest, reason, action_id):
    request = dict(proposal_hash=digest, reason=reason)
    if store._replay(action_id, 'toolchain-reject', request):
        return store.load()
    state = store.load()
    text(reason, 'reason')
    if (state['state'] not in STAGES or state.get('toolchain_status') not in {'reviewing', 'awaiting-approval'}
            or digest != state.get('toolchain_proposal_hash')):
        raise CogitoError('toolchain rejection must reference the pending proposal')
    return store._emit('toolchain-rejected', request, action_id, 'toolchain-reject', request)


def require_committed(state):
    if state.get('toolchain'):
        manifests = state['toolchain']['proposal']['after']['manifests']
        if not (manifests['head'] == manifests['index'] == manifests['content']):
            raise CogitoError('commit the exact tool update and adopt its new HEAD before RP Package approval')


def effective_head(state):
    return (state['toolchain']['proposal']['after']['head'] if state.get('toolchain')
            else state['snapshot']['delivery']['head'])
