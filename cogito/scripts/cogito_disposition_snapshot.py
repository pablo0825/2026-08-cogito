"""Disposition policy for product snapshots with mutable control journals."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from cogito_actions import request_fingerprint
from cogito_common import CogitoError
from cogito_events import read_events
from cogito_product_snapshot import (
    git_bytes,
    journal_binding,
    journal_suffix,
    tree_entries,
    tree_without_paths,
)


_GRAPH = 'docs/cogito/project-graph.json'
_REGULAR = {'100644', '100755'}


def _safe_path(root: Path, relative: str) -> Path:
    path = root / relative
    if path.resolve() != path:
        raise CogitoError('disposition runtime must not traverse symlinks: ' + relative)
    return path


def capture_runtime(root: Path, disposition_id: str, run_ids, replan_id=None) -> dict[str, Any]:
    """Bind journals which may legitimately advance after the product capture."""
    base = f'.cogito/dispositions/{disposition_id}'
    result: dict[str, Any] = {
        'version': 1,
        'disposition': journal_binding(_safe_path(root, base + '/events.jsonl')),
        'runs': {},
        'replan': None,
    }
    for run_id in sorted(set(run_ids)):
        journal = f'.cogito/runs/{run_id}/events.jsonl'
        result['runs'][run_id] = journal_binding(_safe_path(root, journal))
    if replan_id:
        result['replan'] = {
            'replan_id': replan_id,
            'cursor': journal_binding(
                _safe_path(root, f'.cogito/replans/{replan_id}/events.jsonl')),
        }
    return result


def _suffix(path: Path, cursor: Any, label: str) -> list[dict[str, Any]]:
    return journal_suffix(path, cursor, label)


def _tree_blob(root: Path, entries, relative: str) -> bytes | None:
    item = entries.get(relative)
    if item is None:
        return None
    mode, oid = item
    if mode not in _REGULAR:
        raise CogitoError('disposition runtime must be a regular file: ' + relative)
    return git_bytes(root, 'cat-file', 'blob', oid,
                     error_context='validate disposition runtime')


def _validate_tree_runtime(root: Path, first: str, second: str,
                           paths: set[str], journals: set[str], locks: set[str]) -> None:
    before, after = tree_entries(root, first), tree_entries(root, second)
    for relative in paths:
        old = _tree_blob(root, before, relative)
        new = _tree_blob(root, after, relative)
        if relative in locks and ((old is not None and old) or (new is not None and new)):
            raise CogitoError('disposition synchronization file must be empty: ' + relative)
        if relative in journals:
            live_path = _safe_path(root, relative)
            live = live_path.read_bytes() if live_path.is_file() else b''
            for content in (old, new):
                if content is not None and ((content and not content.endswith(b'\n'))
                                            or not live.startswith(content)):
                    raise CogitoError('disposition staged event history changed: ' + relative)


def _cancel_rules(events: list[dict[str, Any]], state: dict[str, Any],
                  disposition_id: str) -> dict[str, tuple[str, dict[str, Any]]]:
    rules: dict[str, tuple[str, dict[str, Any]]] = {}
    if state.get('cancel_source'):
        rules[state['source_run_id']] = (
            'disposition-cancel:' + disposition_id,
            {'authorized': True, 'reason': state['reason'],
             'disposition_id': disposition_id},
        )
    for event in events:
        if event['type'] != 'disposition-pause-started':
            continue
        run_id = event['payload'].get('retired_followup_run_id')
        action = str(event.get('action_id', ''))
        prefix = 'disposition-pause-intent:'
        if run_id and action.startswith(prefix):
            rules[run_id] = (
                'disposition-pause-cancel:' + action[len(prefix):],
                {'authorized': True, 'reason': event['payload'].get('reason'),
                 'disposition_id': disposition_id},
            )
    return rules


def validate_runtime(root: Path, disposition_id: str, saved: dict[str, Any],
                     state: dict[str, Any], *, transition=False,
                     first_tree: str | None = None,
                     second_tree: str | None = None) -> set[str]:
    """Validate owned append-only history and return exact non-product paths."""
    runtime = saved.get('runtime')
    if (not isinstance(runtime, dict) or runtime.get('version') != 1
            or set(runtime) != {'version', 'disposition', 'runs', 'replan'}
            or set(runtime.get('runs', {})) != set(saved.get('runs', {}))):
        raise CogitoError('invalid disposition runtime snapshot')
    base = f'.cogito/dispositions/{disposition_id}'
    dp_journal = base + '/events.jsonl'
    dp_path = _safe_path(root, dp_journal)
    dp_events = read_events(dp_path)
    dp_suffix = _suffix(dp_path, runtime['disposition'], 'disposition')
    if transition:
        if len(dp_suffix) != 1:
            raise CogitoError('unexpected disposition journal change during saved-work validation')
        event = dp_suffix[0]
        if event['type'] == 'disposition-stop-started':
            action = str(event.get('action_id', ''))
            valid = (action.startswith('disposition-stop-intent:')
                     and event.get('request_hash') == request_fingerprint('stop-intent')
                     and event.get('payload') == {'snapshot': saved})
        elif event['type'] == 'disposition-pause-saved':
            action = str(event.get('action_id', ''))
            prefix = 'disposition-pause-saved:'
            token = action[len(prefix):] if action.startswith(prefix) else ''
            intent_action = 'disposition-pause-intent:' + token
            intents = [item for item in dp_events[:runtime['disposition']['sequence']]
                       if item.get('type') == 'disposition-pause-started'
                       and item.get('action_id') == intent_action]
            request = {'reason': intents[-1]['payload'].get('reason')} if len(intents) == 1 else {}
            valid = (action.startswith('disposition-pause-saved:')
                     and bool(token) and set(request) == {'reason'}
                     and event.get('request_hash') == request_fingerprint('pause-saved', **request)
                     and event.get('payload') == {'snapshot': saved})
        else:
            valid = False
        if not valid:
            raise CogitoError('unexpected disposition journal change during saved-work validation')

    paths = {dp_journal, base + '/state.json', dp_journal + '.lock',
             '.cogito/project-mutation.lock'}
    from cogito_disposition_archive import validate_control_artifacts
    paths.update(validate_control_artifacts(
        root, disposition_id, saved,
        require_manifest=state.get('state') not in {'stopping', 'pausing'}))
    journals = {dp_journal}
    locks = {dp_journal + '.lock', '.cogito/project-mutation.lock'}
    rules = _cancel_rules(dp_events, state, disposition_id)
    for run_id, cursor in runtime['runs'].items():
        run_base = f'.cogito/runs/{run_id}'
        journal = run_base + '/events.jsonl'
        suffix = _suffix(_safe_path(root, journal), cursor, 'run ' + run_id)
        if suffix:
            rule = rules.get(run_id)
            if (rule is None or len(suffix) != 1 or suffix[0]['type'] != 'cancel'
                    or suffix[0].get('action_id') != rule[0]
                    or suffix[0].get('payload') != rule[1]):
                raise CogitoError('run changed after disposition snapshot: ' + run_id)
        paths.update({journal, run_base + '/state.json', journal + '.lock'})
        journals.add(journal); locks.add(journal + '.lock')

    replan = runtime['replan']
    if replan is not None:
        if (not isinstance(replan, dict) or set(replan) != {'replan_id', 'cursor'}
                or replan['replan_id'] != state.get('replan_id')):
            raise CogitoError('invalid disposition replan runtime snapshot')
        rp_base = f".cogito/replans/{replan['replan_id']}"
        journal = rp_base + '/events.jsonl'
        rp_path = _safe_path(root, journal)
        suffix = _suffix(rp_path, replan['cursor'], 'replan')
        payload = suffix[0].get('payload', {}) if suffix else {}
        if suffix and (len(suffix) != 1 or suffix[0]['type'] != 'replan-disposition-started'
                       or suffix[0].get('action_id') != 'dp-delegate:' + disposition_id
                       or set(payload) != {'disposition_id', 'runtime_logs'}
                       or payload.get('disposition_id') != disposition_id
                       or not isinstance(payload.get('runtime_logs'), dict)):
            raise CogitoError('replan changed after disposition snapshot')
        if suffix:
            from cogito_replan_snapshot import ReplanRuntime
            from cogito_replan_state import project_replan
            ReplanRuntime(root, project_replan(read_events(rp_path))).assert_logs(
                payload['runtime_logs'])
        paths.update({journal, rp_base + '/state.json', journal + '.lock'})
        journals.add(journal); locks.add(journal + '.lock')
    elif state.get('replan_id') is not None:
        raise CogitoError('disposition snapshot is missing its replan journal')

    for relative in paths:
        _safe_path(root, relative)
    for relative in locks:
        path = _safe_path(root, relative)
        if path.exists() and (not path.is_file() or path.read_bytes()):
            raise CogitoError('disposition synchronization file must be empty: ' + relative)
    if first_tree is not None and second_tree is not None:
        _validate_tree_runtime(root, first_tree, second_tree, paths, journals, locks)
    return paths


def require_same_product(root: Path, first: str, second: str, runtime_paths=(), *,
                         message='saved product content changed; use a reviewed followup') -> None:
    """Compare trees after removing only caller-validated runtime and Graph."""
    paths = set(runtime_paths)
    journals = {path for path in paths if path.endswith('/events.jsonl')}
    locks = {path for path in paths if path.endswith('.lock')}
    _validate_tree_runtime(root, first, second, paths, journals, locks)
    removed = sorted({_GRAPH, *paths})
    before = tree_without_paths(root, first, removed,
                                temporary_prefix='cogito-dp-product-',
                                error_context='project disposition product')
    after = tree_without_paths(root, second, removed,
                               temporary_prefix='cogito-dp-product-',
                               error_context='project disposition product')
    if before != after:
        raise CogitoError(message)
