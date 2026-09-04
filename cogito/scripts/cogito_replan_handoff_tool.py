"""Append-only adoption of a committed Gate repair during an interrupted handoff."""
from __future__ import annotations

from cogito_common import CogitoError, hash_json, load_json
from cogito_contracts import package_hash
from cogito_replan_toolchain import (
    TOOL_ROOT, _assert_scope, _commits, _compatibility, _required_installation,
    assert_executing, binding, differences,
)
from cogito_replan_toolchain_rules import text, validate_binding, validate_review


EVENTS = {'handoff-tool-proposed', 'handoff-tool-reviewed',
          'handoff-tool-approved', 'handoff-tool-rejected'}


def checkpoint(store, state):
    successor = store.successor().load()
    graph = load_json(store.root / 'docs/cogito/project-graph.json')
    return {
        'snapshot_hash': hash_json(state['snapshot']),
        'product_proposal_hash': state['proposal_hash'],
        'product_approval_hash': hash_json(state['approval']),
        'handoff_started_hash': state['handoff']['proposal_hash'],
        'source_event_hash': store.source().load()['last_event_hash'],
        'successor_event_hash': successor['last_event_hash'],
        'successor_package_hash': successor['package_hash'],
        'graph_hash': hash_json(graph),
        'transfers_hash': hash_json({'plans': state['transfer_plans'], 'receipts': state['transfers']}),
    }


def eligible(store, state):
    if state['state'] != 'handing-off':
        raise CogitoError('handoff tool repair requires an interrupted handing-off RP')
    successor = store.successor().load()
    if successor['state'] != 'start-gate' or state['transfer_plans'] or state['transfers']:
        raise CogitoError('handoff tool repair is only allowed before successor start and work transfer')
    if store.source().load()['state'] == 'superseded':
        raise CogitoError('handoff tool repair cannot change tools after source closure')
    graph = load_json(store.root / 'docs/cogito/project-graph.json')
    if graph not in (state['snapshot']['graph'], state['approval']['graph']):
        raise CogitoError('Project Graph must remain at a journaled handoff boundary')


def effective_before(store, state):
    adopted = state.get('runtime_toolchain') or state.get('toolchain')
    if adopted:
        return adopted['proposal']['after']
    return binding(store.root, state['snapshot']['delivery'])


def validate_proposal(value, state):
    if not isinstance(value, dict) or value.get('schema_version') != 1:
        raise CogitoError('unsupported handoff tool repair proposal')
    for key in ('author_id', 'reason'):
        text(value.get(key), key)
    if value.get('tool_root') != TOOL_ROOT:
        raise CogitoError('handoff repair only supports ' + TOOL_ROOT)
    for key in ('before', 'after'):
        validate_binding(value.get(key))
    if value['before']['branch'] != value['after']['branch']:
        raise CogitoError('handoff tool repair cannot change delivery branch')
    if value.get('differences') != differences(value['before'], value['after']):
        raise CogitoError('handoff tool repair differences do not match its manifests')
    manifests = value['after']['manifests']
    if not (manifests['head'] == manifests['index'] == manifests['content']):
        raise CogitoError('handoff tool repair must be committed exactly before review')
    if not value.get('commits') or value['commits'][-1] != value['after']['head']:
        raise CogitoError('handoff tool repair requires a committed linear history')
    checkpoint_value = value.get('checkpoint')
    if (not isinstance(checkpoint_value, dict)
            or checkpoint_value.get('snapshot_hash') != hash_json(state['snapshot'])
            or checkpoint_value.get('product_proposal_hash') != state.get('proposal_hash')
            or checkpoint_value.get('product_approval_hash') != hash_json(state.get('approval'))
            or checkpoint_value.get('handoff_started_hash') != state.get('handoff', {}).get('proposal_hash')
            or checkpoint_value.get('transfers_hash') != hash_json({
                'plans': state.get('transfer_plans', {}), 'receipts': state.get('transfers', {})})):
        raise CogitoError('handoff tool repair is not bound to the approved handoff checkpoint')
    if value.get('compatibility', {}).get('revalidation') != [
            'resume original handoff action', 'rerun successor Start Gate',
            'rerun all successor checks; no evidence reuse']:
        raise CogitoError('handoff tool repair compatibility is incomplete')
    previous = (state.get('runtime_toolchain') or {}).get('proposal_hash')
    if value.get('previous_repair_hash') != previous:
        raise CogitoError('handoff tool repair does not extend the current runtime binding')


def build(store, request):
    state = store.load(); eligible(store, state)
    if not isinstance(request, dict) or set(request) != {'author_id', 'reason', 'tool_root'}:
        raise CogitoError('handoff tool repair requires author_id, reason and tool_root')
    for key in ('author_id', 'reason'):
        text(request.get(key), key)
    if request.get('tool_root') != TOOL_ROOT:
        raise CogitoError('handoff repair only supports ' + TOOL_ROOT)
    package = state['proposal']['package']
    before = effective_before(store, state)
    after = binding(store.root, store._capture()['delivery'])
    _required_installation(before); _required_installation(after)
    commits = _commits(store.root, before, after)
    _assert_scope(store, package)
    compatibility = _compatibility(store, package, after)
    compatibility['revalidation'] = ['resume original handoff action', 'rerun successor Start Gate',
                                     'rerun all successor checks; no evidence reuse']
    store._assert_source(package and {'package': package},
                         activated=load_json(store.root/'docs/cogito/project-graph.json') == state['approval']['graph'],
                         toolchain_binding=after)
    value = dict(schema_version=1, **request, checkpoint=checkpoint(store, state),
                 previous_repair_hash=(state.get('runtime_toolchain') or {}).get('proposal_hash'),
                 before=before, after=after, differences=differences(before, after),
                 commits=commits, compatibility=compatibility)
    validate_proposal(value, state)
    return value


def _revalidate(store):
    saved = store.load()['handoff_tool_proposal']
    actual = build(store, {key: saved[key] for key in ('author_id', 'reason', 'tool_root')})
    if actual != saved:
        raise CogitoError('handoff tool repair changed; prepare and review a new proposal')
    assert_executing(store.root, saved['after'])


def propose(store, request, action_id):
    wrapped = {'proposal': request}
    if store._replay(action_id, 'handoff-tool-propose', wrapped): return store.load()
    value = build(store, request)
    return store._emit('handoff-tool-proposed', {'proposal': value, 'proposal_hash': hash_json(value)},
                       action_id, 'handoff-tool-propose', wrapped)


def review(store, value, action_id):
    request = {'review': value}
    if store._replay(action_id, 'handoff-tool-review', request): return store.load()
    state = store.load()
    if state.get('handoff_tool_status') != 'reviewing':
        raise CogitoError('handoff tool review requires a current proposal')
    validate_review(value, state['handoff_tool_proposal'], state['handoff_tool_proposal_hash'])
    _revalidate(store)
    return store._emit('handoff-tool-reviewed', dict(value), action_id, 'handoff-tool-review', request)


def approve(store, digest, approver_id, action_id):
    request = {'proposal_hash': digest, 'approver_id': approver_id}
    if store._replay(action_id, 'handoff-tool-approve', request): return store.load()
    text(approver_id, 'approver_id'); state = store.load()
    if state.get('handoff_tool_status') != 'awaiting-approval' or digest != state.get('handoff_tool_proposal_hash'):
        raise CogitoError('handoff tool approval requires the independently reviewed exact proposal')
    _revalidate(store)
    return store._emit('handoff-tool-approved', request, action_id, 'handoff-tool-approve', request)


def reject(store, digest, reason, action_id):
    request = {'proposal_hash': digest, 'reason': reason}
    if store._replay(action_id, 'handoff-tool-reject', request): return store.load()
    text(reason, 'reason'); state = store.load()
    if state.get('handoff_tool_status') not in {'reviewing', 'awaiting-approval'} or digest != state.get('handoff_tool_proposal_hash'):
        raise CogitoError('handoff tool rejection must reference the pending proposal')
    return store._emit('handoff-tool-rejected', request, action_id, 'handoff-tool-reject', request)
