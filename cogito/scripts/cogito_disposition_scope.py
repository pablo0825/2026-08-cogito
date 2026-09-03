"""Read durable disposition scope and fence dependent or overlapping Packages."""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, Mapping

from cogito_common import CogitoError, load_json
from cogito_contracts import package_hash
from cogito_disposition_state import TERMINAL, project_disposition
from cogito_events import read_events


def dispositions(root):
    """Read authoritative histories, never disposable state.json caches."""
    for path in sorted((Path(root) / '.cogito' / 'dispositions').glob('DP-*/events.jsonl')):
        yield project_disposition(read_events(path))


def _literal_prefix(pattern: str) -> str:
    return pattern[:min((pattern.find(c) for c in '*?[' if c in pattern), default=len(pattern))]


def paths_overlap(first: str, second: str) -> bool:
    """Conservative intersection: uncertainty fences; disjoint literal roots pass.

    Approved plain paths also authorize descendants in Cogito. Glob intersections
    are deliberately approximated by literal prefixes, avoiding false negatives
    when neither glob matches the spelling of the other glob.
    """
    first, second = first.rstrip('/'), second.rstrip('/')
    if not first or not second or first == '.' or second == '.':
        return True
    if fnmatchcase(first, second) or fnmatchcase(second, first):
        return True
    a, b = _literal_prefix(first), _literal_prefix(second)
    if not a or not b:
        return True
    wild_a, wild_b = a != first, b != second
    if not wild_a and not wild_b:
        return a == b or a.startswith(b + '/') or b.startswith(a + '/')
    if a.startswith(b) or b.startswith(a):
        return True
    # A plain directory authorizes descendants, including a glob under it.
    return (not wild_a and b.startswith(a + '/')) or (not wild_b and a.startswith(b + '/'))


def _affected_slices(root: Path, initial: set[str]) -> set[str]:
    graph_path = root / 'docs/cogito/project-graph.json'
    if not graph_path.exists():
        return initial
    graph = load_json(graph_path)
    edges = {(edge['from'], edge['to']) for edge in graph.get('dependencies', [])}
    for slice_id, item in graph.get('slices', {}).items():
        edges.update((dependency, slice_id) for dependency in item.get('dependencies', []))
    affected = set(initial)
    while True:
        additions = {target for source, target in edges if source in affected}
        if additions <= affected:
            return affected
        affected.update(additions)


def check_package(root, package: Mapping[str, Any], run_id: str, *, skip_disposition_id: str | None = None, extra_paths=()) -> None:
    """Block unresolved impact, except the exact approved disposition follow-up."""
    root = Path(root)
    for state in dispositions(root):
        disposition_id = state['disposition_id']
        if disposition_id == skip_disposition_id:
            continue
        if run_id in {*state.get('retired_followup_run_ids', []), state.get('successor_run_id')}:
            raise CogitoError(f'follow-up was retired by disposition {disposition_id}')
        if state['state'] in TERMINAL:
            continue
        proposal = state.get('proposal') or {}
        approval = state.get('approval') or {}
        expected_run = proposal.get('followup_run_id', approval.get('followup_run_id'))
        expected_hash = proposal.get('followup_package_hash', approval.get('followup_package_hash'))
        if (state['state'] == 'executing' and approval.get('authorized') is True
                and expected_run == run_id and expected_hash == package_hash(package)):
            continue
        fenced_runs = set(state.get('run_ids', [])) | {state.get('source_run_id'), state.get('successor_run_id')}
        if run_id in fenced_runs:
            raise CogitoError(f'run is fenced by disposition {disposition_id}')
        scopes = [scope for scope in (state.get('scope'), state.get('snapshot', {}).get('scope')) if scope is not None]
        for version in state.get('proposal_history', []):
            if version.get('proposal', {}).get('impact'):
                scopes.append(version['proposal']['impact'])
        scopes.extend(state.get('additional_scopes', []))
        if proposal.get('impact'):
            scopes.append(proposal['impact'])
        if state['state'] in {'stopping', 'pausing'} or not scopes or any(scope.get('unknown', False) for scope in scopes):
            raise CogitoError(f'disposition {disposition_id} impact is not yet established; remain paused')
        blocked_paths = {path for scope in scopes for path in scope.get('paths', [])}
        blocked_slices = _affected_slices(root, {item for scope in scopes for item in scope.get('slice_ids', [])})
        candidate_paths = [*package.get('approved_paths', []), *extra_paths]
        for item in package.get('slices', []):
            candidate_paths.extend(item.get('worker', {}).get('allowed_paths', []))
        for task in package.get('execution_dag', {}).get('tasks', []):
            candidate_paths.extend(task.get('paths', []))
        candidate_paths.extend(item['path'] for item in package.get('source_registry', []) if item.get('path'))
        candidate_slices = set()
        for item in package.get('slices', []):
            candidate_slices.add(item['id'])
            candidate_slices.update(item.get('lineage', []))
            candidate_slices.update(item.get('dependencies', []))
        candidate_slices.update(package.get('depends_on_slices', []))
        if (candidate_slices & blocked_slices or any(
                paths_overlap(path, blocked) for path in candidate_paths for blocked in blocked_paths)):
            raise CogitoError(f'Package overlaps or depends on unresolved disposition {disposition_id}; {scopes[-1]["reason"]}')
