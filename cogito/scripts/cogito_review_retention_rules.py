"""Conservative, pure eligibility rules for same-run review retention."""
from typing import Any, Mapping, Sequence, cast

from cogito_common import CogitoError, hash_json
from cogito_contract_fields import (CONTENT_HASH_RE, GIT_OBJECT_RE, require_id, require_integer,
                                    require_paths, require_string)
from cogito_contracts import path_allowed
from cogito_state_types import RunState


def _text(value, name):
    require_string(value, name)
    if not value.strip():
        raise CogitoError(name + ' must describe the assessment')


def _ids(value, name, *, nonempty=False):
    if not isinstance(value, list) or (nonempty and not value):
        raise CogitoError(name + ' must be an array')
    for item in value:
        require_id(item, name)
    if len(set(value)) != len(value):
        raise CogitoError(name + ' must be distinct')


def validate_impact(value):
    fields = {'author_id', 'retained', 'affected_task_ids', 'check_ids', 'assessment'}
    if not isinstance(value, dict) or set(value) != fields:
        raise CogitoError('retention impact requires exact author, retained, affected tasks, checks and assessment')
    require_id(value['author_id'], 'retention author')
    _text(value['assessment'], 'retention impact assessment')
    _ids(value['affected_task_ids'], 'affected tasks', nonempty=True)
    _ids(value['check_ids'], 'related checks', nonempty=True)
    if not isinstance(value['retained'], list) or not value['retained']:
        raise CogitoError('retention requires candidates')
    ids = []
    for item in value['retained']:
        if not isinstance(item, dict) or set(item) != {'task_id', 'reason', 'dependency_paths'}:
            raise CogitoError('retained entry requires task_id, reason and dependency_paths')
        require_id(item['task_id'], 'retained task')
        _text(item['reason'], 'retention reason')
        require_paths(item['dependency_paths'], 'dependency paths')
        if len(set(item['dependency_paths'])) != len(item['dependency_paths']):
            raise CogitoError('dependency paths must be distinct')
        ids.append(item['task_id'])
    _ids(ids, 'retained tasks', nonempty=True)
    if set(ids) & set(value['affected_task_ids']):
        raise CogitoError('affected Task cannot be retained')


def validate_reviewer(impact, reviewer_id, assessment, implementers):
    require_id(reviewer_id, 'retention reviewer')
    _text(assessment, 'retention reviewer assessment')
    if reviewer_id in {impact['author_id'], *implementers}:
        raise CogitoError('retention reviewer must be independent of author and implementers')


def reference(event):
    return {'event_sequence': event['sequence'], 'event_hash': event['event_hash']}


def source_review(events, task_id, cycle):
    """Never fall back past a replacement, including an unresolved finding."""
    reviews = [e for e in events if e['type'] == 'agent-result-recorded'
               and e['payload']['result'].get('role') == 'reviewer'
               and e['payload']['result'].get('task_id') == task_id]
    if not reviews:
        raise CogitoError('retention requires an original approval: ' + task_id)
    event = reviews[-1]
    result = event['payload']['result']
    if (event['sequence'] >= cycle or result.get('status') != 'complete'
            or result.get('requested_transition') != 'review-approved'
            or result.get('agent_id') == result.get('reviewed_implementer')):
        raise CogitoError('retention requires an unreplaced prior independent approval: ' + task_id)
    return event


def validate_candidate(task_id: str, tasks: Mapping[str, Any], touched_paths: Sequence[str],
                       impact: Mapping[str, Any], old_task: Mapping[str, Any],
                       new_task: Mapping[str, Any], old_checks: Mapping[str, Any],
                       new_checks: Mapping[str, Any]) -> None:
    """Use declared paths/DAG only; semantic dependency assessment stays human/agent work."""
    validate_impact(impact)
    entry = next((i for i in impact['retained'] if i['task_id'] == task_id), None)
    if entry is None or task_id not in tasks or old_task != new_task:
        raise CogitoError('retained Task contract changed or is missing')
    if any(old_checks.get(key) is None or old_checks[key] != new_checks.get(key)
           for key in old_task['check_ids']):
        raise CogitoError('retained Task check definition changed')
    ancestors, pending = set(), [task_id]
    while pending:
        key = pending.pop()
        if key in ancestors:
            continue
        if key not in tasks:
            raise CogitoError('retained Task dependency is unknown')
        ancestors.add(key)
        pending.extend(tasks[key].get('depends_on', []))
    if ancestors & set(impact['affected_task_ids']):
        raise CogitoError('retained Task depends on affected work')
    paths = [p for key in ancestors for p in tasks[key]['paths']]
    paths.extend(entry['dependency_paths'])
    if any(path_allowed(path, paths) for path in touched_paths):
        raise CogitoError('retained Task or dependency was touched')


def validate_retention_shape(record):
    """One executable shape contract for closure, replay and portable summaries."""
    if not isinstance(record, dict) or set(record) != {'impact', 'binding', 'binding_hash', 'reviewer_id', 'assessment'}:
        raise CogitoError('invalid recorded retention')
    impact, binding = record['impact'], record['binding']
    validate_impact(impact)
    if not isinstance(binding, dict) or set(binding) != {
        'run_id', 'verification', 'correction', 'effective_contract_hash', 'runtime',
        'head', 'tree', 'sources', 'checks',
    }:
        raise CogitoError('invalid retention binding')
    if record['binding_hash'] != hash_json({'impact': impact, 'binding': binding}):
        raise CogitoError('recorded retention binding hash changed')
    require_id(binding['run_id'], 'retention Run')
    for key in ('effective_contract_hash', 'runtime'):
        require_string(binding[key], 'retention ' + key, CONTENT_HASH_RE)
    for key in ('head', 'tree'):
        require_string(binding[key], 'retention ' + key, GIT_OBJECT_RE)
    validate_reviewer(impact, record['reviewer_id'], record['assessment'], [])

    def require_ref(ref):
        if not isinstance(ref, dict) or set(ref) != {'event_sequence', 'event_hash'}:
            raise CogitoError('retention requires exact event references')
        require_integer(ref['event_sequence'], 'retention sequence', 1, 2**63 - 1)
        require_string(ref['event_hash'], 'retention event hash', CONTENT_HASH_RE)

    for key in ('verification', 'correction'):
        require_ref(binding[key])
    if not isinstance(binding['sources'], list) or not binding['sources']:
        raise CogitoError('retention requires source approvals')
    ids = []
    for source in binding['sources']:
        if not isinstance(source, dict) or set(source) != {
            'task_id', 'review', 'implementation', 'verification', 'base_head', 'base_tree', 'touched_paths',
        }:
            raise CogitoError('invalid retention source fields')
        require_id(source['task_id'], 'retention source Task')
        ids.append(source['task_id'])
        for key in ('review', 'implementation', 'verification'):
            require_ref(source[key])
        for key in ('base_head', 'base_tree'):
            require_string(source[key], 'retention source ' + key, GIT_OBJECT_RE)
        require_paths(source['touched_paths'], 'retention touched paths')
        if len(set(source['touched_paths'])) != len(source['touched_paths']):
            raise CogitoError('retention touched paths must be distinct')
    if len(set(ids)) != len(ids) or set(ids) != {i['task_id'] for i in impact['retained']}:
        raise CogitoError('retention source set differs from the reviewed proposal')
    if not isinstance(binding['checks'], list) or not binding['checks']:
        raise CogitoError('retention requires current check references')
    paths = []
    for check in binding['checks']:
        if not isinstance(check, dict) or set(check) != {'path', 'hash'}:
            raise CogitoError('invalid retention check reference')
        # Evidence references are absolute runner artifact paths, not repo paths.
        require_string(check['path'], 'retention evidence path')
        require_string(check['hash'], 'retention evidence hash', CONTENT_HASH_RE)
        paths.append(check['path'])
    if len(set(paths)) != len(paths):
        raise CogitoError('retention evidence references must be distinct')


def validate_recorded_retention(events, state, payload):
    """Replay exact references without turning historical Results into new ones."""
    record = payload['retention']
    validate_retention_shape(record)
    impact, binding = record['impact'], record['binding']
    if (state['state'] != 'reviewing' or state.get('task_delivery') != 'atomic'
            or binding['run_id'] != state['run_id']
            or binding['effective_contract_hash'] != state['effective_contract_hash']):
        raise CogitoError('retention is outside its recorded contract')
    verifications = [e for e in events if e['type'] == 'verification-passed']
    corrections = [e for e in events if e['type'] == 'review-fix-complete']
    if (not verifications or not corrections
            or binding['verification'] != reference(verifications[-1])
            or binding['correction'] != reference(corrections[-1])
            or corrections[-1]['sequence'] >= verifications[-1]['sequence']
            or binding['runtime'] != verifications[-1]['payload'].get('review_runtime')):
        raise CogitoError('retention references a different verification cycle')
    validate_reviewer(impact, record['reviewer_id'], record['assessment'],
                      [t.get('agent_id') for t in state['tasks'].values()])
    retained = {i['task_id'] for i in impact['retained']}
    if (not isinstance(binding['sources'], list) or any(not isinstance(s, dict) for s in binding['sources'])
            or len(binding['sources']) != len(retained)
            or {s.get('task_id') for s in binding['sources']} != retained):
        raise CogitoError('retention source set differs from the reviewed proposal')
    by_sequence = {e['sequence']: e for e in events}
    for source in binding['sources']:
        approval = source_review(events, source['task_id'], verifications[-1]['sequence'])
        if source.get('review') != reference(approval):
            raise CogitoError('retention approval was replaced')
        for key, kind in (('implementation', 'agent-result-recorded'), ('verification', 'verification-passed')):
            ref = source.get(key, {})
            event = by_sequence.get(ref.get('event_sequence')) if isinstance(ref, dict) else None
            if not event or event['type'] != kind or reference(event) != ref or event['sequence'] >= approval['sequence']:
                raise CogitoError('retention history reference is invalid')
        impl = by_sequence[source['implementation']['event_sequence']]['payload']['result']
        review = approval['payload']['result']
        original_wave = [e for e in events if e['type'] == 'verification-passed'
                         and e['sequence'] < approval['sequence']][-1]
        implementations = [e for e in events if e['type'] == 'agent-result-recorded'
                           and e['payload']['result'].get('role') == 'implementer'
                           and e['payload']['result'].get('task_id') == source['task_id']]
        if (source['verification'] != reference(original_wave)
                or original_wave['payload'].get('review_runtime') != binding['runtime']
                or not implementations or source['implementation'] != reference(implementations[-1])):
            raise CogitoError('retention source belongs to a different wave or implementation')
        if (impl.get('role') != 'implementer' or impl.get('status') != 'complete'
                or impl.get('task_id') != source['task_id']
                or impl.get('agent_id') != review.get('reviewed_implementer')
                or any(impl.get(k) != review.get(k) for k in ('base_commit', 'head_commit'))):
            raise CogitoError('retention implementation reference is invalid')
    for check in binding['checks']:
        entry = state['evidence'].get(check['path'])
        if not entry or entry['evidence_hash'] != check['hash']:
            raise CogitoError('retention check differs from recorded evidence')
    from cogito_gate_validation import derive_review_decision
    current = cast(RunState, {**state, 'agent_results': [e['payload']['result'] for e in events
        if e['type'] == 'agent-result-recorded' and e['sequence'] > verifications[-1]['sequence']]})
    decision = derive_review_decision({'kind': state['kind']}, current, retained_task_ids=retained)
    if any(payload.get(k) != v for k, v in decision.items()) or payload.get('review_exemption'):
        raise CogitoError('retention closure differs from its recorded reviews')
