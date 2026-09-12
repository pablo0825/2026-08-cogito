"""Editable closure records assembled from history; finalization remains authoritative."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile

from cogito_common import CogitoError, load_json
from cogito_contracts import materialize_contract_with_limits, package_hash
from cogito_delivery_summary import build_delivery_summary, CORRECTION_EVENTS, INTEGRATION_EVENTS
from cogito_finalization import validate_finalization
from cogito_finalization_rules import FinalizationContext, validate_finalization_records, validate_verification_snapshot
from cogito_project_graph import validate_project_graph
from cogito_result_contract import validate_result
from cogito_run_queries import operation_hint


def final_evidence_paths(events):
    receipts = [e['payload'] for e in events if e['type'] in {
        'human-review-required', 'auto-accept-ready', 'human-correction-reviewed', 'human-correction-accepted'}]
    if not receipts:
        raise CogitoError('Result draft requires a final verification receipt')
    return list(dict.fromkeys(receipts[-1]['evidence']))


def build_result_facts(package, state, events, evidence):
    """Assemble facts, then callers check them with the existing closure validator."""
    completions = {e['payload'].get('amendment_id'): e['payload'] for e in events
                   if e['type'] in CORRECTION_EVENTS}
    amendments = []
    for event in events:
        if event['type'] != 'technical-amendment-added':
            continue
        payload = event['payload']
        amendment = payload['amendment']
        item = {'id': amendment['id']}
        if amendment.get('path_additions'):
            item['proposal_hash'] = payload.get('scope_review', {}).get('proposal_hash')
        else:
            completion = completions.get(amendment['id'])
            if not completion:
                raise CogitoError('Result draft lacks amendment completion: ' + amendment['id'])
            if completion.get('completion_mode') == 'working-tree':
                item.update(base_commit=completion['commit_id'], content_tree=completion['content_tree'])
            else:
                item['commit_id'] = completion['commit_id']
        amendments.append(item)
    reviewers = {r['agent_id'] for r in state.get('agent_results', [])
                 if r['role'] == 'reviewer' and r['status'] == 'complete'}
    for task in state.get('tasks', {}).values():
        reviewers.update(task.get('adoption', {}).get('source_reviewers', []))
    reviewers.update(e['payload']['retention']['reviewer_id'] for e in events
                     if e['type'] == 'review-approved' and 'retention' in e['payload'])
    human_required = any(e['type'] == 'human-review-required' for e in events)
    return {'schema_version': '3.0', 'run_id': package['run_id'], 'status': 'accepted',
        'package_hash': package_hash(package), 'effective_contract_hash': state['effective_contract_hash'],
        'slice_dispositions': {s['id']: 'accepted' for s in package['slices']},
        'integration_commits': [e['payload']['commit_id'] for e in events if e['type'] in INTEGRATION_EVENTS],
        'checks': [{'id': evidence[p]['check_id'], 'status': 'passed', 'evidence': p}
                   for p in final_evidence_paths(events)],
        'reviews': [{'reviewer': reviewer} for reviewer in sorted(reviewers)],
        'amendments': amendments,
        'human_gate': {'required': human_required, 'outcome': 'approved' if human_required else 'not-required'},
        'delivery_summary': build_delivery_summary(state, events)}


def _paths(store):
    return f'docs/cogito/results/{store.run_id}.json', 'docs/cogito/project-graph.json'


def _finalize_operation(store, commit):
    result, graph = _paths(store)
    return operation_hint(store.root, store.run_id, 'finalize',
        ['--result', result, '--project-graph', graph, '--final-commit', commit])


def finalizing_hints(store, state):
    result, graph = _paths(store)
    output = {'operations': [operation_hint(store.root, store.run_id, 'result-draft',
        ['--event-hash', state['last_event_hash']], action_id=None)],
        'note': 'Generate a new draft only if needed; preserve already edited drafts. '
                'A draft is not acceptance. Complete risks, inspect and save canonical records, then commit and finalize.'}
    # A committed Result may mean only the final event is missing. Never suggest another commit then.
    try:
        head = store._git('rev-parse', 'HEAD')
        if not store._git('ls-tree', head, '--', result):
            return output
        validate_finalization(run_id=store.run_id, package=store._approved_package_from_state(state),
            state=state, load_events=store._events.read, result_path=result, project_graph_path=graph,
            final_commit=head, git=store._git, read_blob=store._git_repo.read_blob,
            workflow_limits=store.workflow['limits'])
    except (CogitoError, OSError, ValueError, KeyError) as exc:
        return {'operations': [], 'blockers': [str(exc)[:600]],
                'note': 'Inspect existing final records and history before replacing anything; do not create another commit blindly.'}
    return {'operations': [_finalize_operation(store, head)],
            'note': 'Current HEAD already contains valid closure records. Do not commit again. '
                    'For an interrupted finalize, reuse its original action ID and exact arguments.'}


def write_result_draft(store, event_hash):
    snapshot = store._events.snapshot()
    state, events = snapshot.state, snapshot.events
    if state['state'] != 'finalizing':
        raise CogitoError('Result draft is only available in finalizing')
    if state['last_event_hash'] != event_hash:
        raise CogitoError('Result draft history changed; query next for the current command')
    package = store._approved_package_from_state(state)
    if store._git('branch', '--show-current') != package['delivery_branch']:
        raise CogitoError('Result draft requires the frozen delivery branch')
    evidence = {}
    for path in final_evidence_paths(events):
        evidence[path] = load_json(Path(path))
        validate_verification_snapshot(evidence[path], state['evidence'].get(path, {}), state['effective_contract_hash'])
    result = build_result_facts(package, state, events, evidence)
    result_path, graph_path = _paths(store)
    graph = deepcopy(load_json(store.root / graph_path))
    if graph.get('active_run_id') not in {None, store.run_id}:
        raise CogitoError('Result draft cannot close another active run in Project Graph')
    graph['active_run_id'] = None
    for item in package['slices']:
        graph['slices'][item['id']].update(disposition='accepted', completed_by=store.run_id)
    effective = materialize_contract_with_limits(package,
        [e['payload']['amendment'] for e in events if e['type'] == 'technical-amendment-added'], store.workflow['limits'])
    # Empty risks exist only in this in-memory validation view, never in the editable draft.
    validation_result = {**result, 'remaining_risks': []}
    validate_result(validation_result)
    validate_project_graph(graph)
    validate_finalization_records(FinalizationContext(store.run_id, package, state, events,
                                                     validation_result, graph, effective))
    drafts = store.run_dir / 'drafts'
    if drafts.resolve() != drafts:
        raise CogitoError('Result draft directory must not contain symlinks')
    drafts.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix='closure-', dir=drafts))
    for name, value in (('result.json', result), ('project-graph.json', graph)):
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'drafts': {'result': str(directory / 'result.json'), 'project_graph': str(directory / 'project-graph.json')},
        'destinations': {'result': result_path, 'project_graph': graph_path},
        'event_hash': event_hash, 'required_inputs': ['remaining_risks'],
        'commit_scope': ('canonical Result and Project Graph only' if package['kind'] in {'feature', 'change', 'correction'}
                         else 'verified working-tree content plus canonical Result and Project Graph; inspect exact paths'),
        'required_final_commit_trailers': [f"Cogito-Amendment: {a['id']}" for a in result['amendments'] if 'base_commit' in a],
        'operations': [_finalize_operation(store, '<actual-final-commit>')],
        'note': 'Fill remaining_risks after assessment (an empty list is allowed only if appropriate). '
                'Inspect and save both drafts to their canonical destinations, preserving unrelated staging. '
                'Commit using the kind-specific finalization policy before running the command. '
                'The accepted status is the proposed Result format, not a Gate verdict; no approval or event was created.'}
