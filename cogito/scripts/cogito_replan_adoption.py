"""Conservative, pure cross-run adoption receipts; never rewrite source evidence.

Callers must load authenticated event logs/packages and capture both complete
content trees. A receipt is provenance, not new runner evidence or permission to
skip successor integration verification.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash, validate_agent_result
from cogito_evidence_contract import validate_check_evidence


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CogitoError(f"Evidence adoption requires rerun: {reason}")


def _task(package: Mapping[str, Any], task_id: str) -> Mapping[str, Any]:
    matches = [task for task in package['execution_dag']['tasks'] if task['id'] == task_id]
    _require(len(matches) == 1, 'task is not uniquely present in the Package')
    task = matches[0]
    incoming = [edge for edge in package['execution_dag']['edges']
                if (edge.get('to') if isinstance(edge, dict) else edge[1]) == task_id]
    _require(not incoming and not task.get('depends_on'), 'dependent tasks need fresh verification')
    return task


def _semantics(task: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in task.items()
            if key not in {'id', 'slice_id', 'status', 'depends_on'}}


def validate_adoption(
    source_package: Mapping[str, Any], successor_package: Mapping[str, Any],
    source_state: Mapping[str, Any], source_events: Sequence[Mapping[str, Any]],
    source_task_id: str, target_task_id: str,
    evidence_records: Mapping[str, Mapping[str, Any]],
    source_content_tree: str, target_content_tree: str,
) -> dict[str, Any]:
    """Return an immutable-source provenance receipt, or require revalidation.

    This first version deliberately rejects dependent tasks and all changed
    global verification inputs. It never infers semantic non-impact from paths.
    """
    _require(bool(source_content_tree) and source_content_tree == target_content_tree,
             'complete source and target content trees differ')
    source_run = source_package['run_id']
    _require(source_run != successor_package['run_id'], 'source and successor must differ')
    _require(source_state.get('run_id') == source_run, 'source state run mismatch')
    _require(source_state.get('package_hash') == package_hash(source_package), 'source Package hash mismatch')
    effective_hash = source_state.get('effective_contract_hash')
    _require(bool(effective_hash), 'source effective contract is missing')
    # Amendments can alter checks/DAG. A base-only comparison cannot prove these
    # effective inputs unchanged; do not silently adopt amended verification.
    _require(effective_hash == package_hash(source_package), 'amended contracts need fresh verification')
    source = _task(source_package, source_task_id)
    target = _task(successor_package, target_task_id)
    current = source_state.get('tasks', {}).get(source_task_id, {})
    _require(current.get('status') in {'reviewed', 'integrated'}, 'source task is not reviewed or integrated')
    _require(_semantics(source) == _semantics(target), 'task responsibility or acceptance changed')
    for field in ('shared_understanding', 'checks', 'policy_snapshot', 'human_gate',
                  'limits', 'stop_conditions', 'approved_paths', 'source_registry',
                  'acceptance', 'acceptance_criteria', 'maintenance_guards'):
        _require(source_package.get(field) == successor_package.get(field), f'{field} changed')
    source_slices = {item['id']: item for item in source_package['slices']}
    target_slices = {item['id']: item for item in successor_package['slices']}
    _require(source.get('slice_id') in source_slices and target.get('slice_id') in target_slices,
             'Mini Package or missing Slice needs fresh verification')
    old_slice, new_slice = source_slices[source['slice_id']], target_slices[target['slice_id']]
    for field in ('spec', 'plan'):
        _require(bool(old_slice.get(field, {}).get('hash')) and
                 old_slice[field]['hash'] == new_slice.get(field, {}).get('hash'), f'Slice {field} changed')
    _require(old_slice['worker']['allowed_paths'] == new_slice['worker']['allowed_paths'],
             'Slice allowed paths changed')
    for field in ('acceptance', 'acceptance_criteria'):
        _require(old_slice.get(field) == new_slice.get(field), f'Slice {field} changed')

    results = [(event['sequence'], event['payload']['result']) for event in source_events
               if event['type'] == 'agent-result-recorded'
               and event['payload']['result'].get('task_id') == source_task_id]
    implementations = [(seq, result) for seq, result in results
                       if result.get('role') == 'implementer' and result.get('status') == 'complete']
    _require(bool(implementations), 'no recorded implementation')
    implementation_seq, implementation = implementations[-1]
    validate_agent_result(implementation)
    _require(implementation['run_id'] == source_run and implementation['agent_id'] == current.get('agent_id'),
             'implementation identity mismatch')
    approvals = [event for event in source_events if event['type'] == 'review-approved'
                 and source_task_id in event['payload'].get('reviews', [])
                 and event['sequence'] > implementation_seq]
    _require(bool(approvals), 'no actual review approval for this implementation')
    approval = approvals[-1]
    verifications = [event for event in source_events if event['type'] == 'verification-passed'
                     and implementation_seq < event['sequence'] < approval['sequence']]
    _require(bool(verifications), 'no verification preceding review')
    verification = verifications[-1]
    reviews = [(seq, result) for seq, result in results if result.get('role') == 'reviewer'
               and verification['sequence'] < seq < approval['sequence']]
    _require(bool(reviews), 'no independent reviewer Result in the verification cycle')
    latest_by_reviewer = {result['agent_id']: result for _, result in reviews}
    for review in latest_by_reviewer.values():
        validate_agent_result(review)
        _require(review['run_id'] == source_run and review['status'] == 'complete'
                 and review['requested_transition'] == 'review-approved'
                 and review.get('reviewed_implementer') == implementation['agent_id']
                 and review['agent_id'] != implementation['agent_id']
                 and (review['base_commit'], review['head_commit']) ==
                     (implementation['base_commit'], implementation['head_commit']),
                 'review does not approve the latest implementation range')
    _require(not any(seq > approval['sequence'] and result.get('role') in {'implementer', 'reviewer'}
                     for seq, result in results),
             'task has Agent Results newer than its review approval')
    checks = {item['id']: item for item in source_package['checks']}
    anchors = [event['sequence'] for event in source_events
               if event['type'] in {'implementation-complete', 'technical-correction-complete', 'review-fix-complete'}
               and event['sequence'] < verification['sequence']]
    _require(bool(anchors), 'verification cycle anchor missing')
    evidence_receipts = []
    for path in verification['payload'].get('evidence', []):
        evidence = evidence_records.get(path)
        _require(evidence is not None, 'verification evidence is unavailable')
        # Other workers may be part of this verification wave; only adopt this
        # implementation's evidence, never evidence from a different worktree.
        if evidence.get('head_commit') != implementation['head_commit']:
            continue
        validate_check_evidence(evidence)
        ledger = source_state.get('evidence', {}).get(path, {})
        check = checks.get(evidence['check_id'])
        recorded = [event for event in source_events
                    if event['type'] == 'check-evidence-recorded'
                    and event['sequence'] == ledger.get('event_sequence')
                    and event['payload'].get('evidence_path') == path
                    and event['payload'].get('check_id') == evidence['check_id']
                    and event['payload'].get('evidence_hash') == hash_json(evidence)]
        _require(len(recorded) == 1, 'evidence is not authenticated by its source event')
        _require(evidence['run_id'] == source_run and evidence['evidence_path'] == path
                 and evidence['passed'] is True and check is not None
                 and evidence['check_hash'] == hash_json(check)
                 and evidence['effective_contract_hash'] == effective_hash
                 and evidence['worktree_binding'].get('content_tree') == source_content_tree
                 and ledger.get('evidence_hash') == hash_json(evidence)
                 and ledger.get('check_id') == evidence['check_id']
                 and max(anchors) < (ledger.get('event_sequence') or 0) < verification['sequence'],
                 'evidence hash, contract, content or verification cycle mismatch')
        evidence_receipts.append({'evidence_path': path, 'evidence_hash': hash_json(evidence),
                                  'check_id': evidence['check_id'], 'check_hash': evidence['check_hash']})
    required = {key for key, check in checks.items() if check.get('required', True)}
    _require(bool(evidence_receipts) and required <= {item['check_id'] for item in evidence_receipts},
             'required checks were not verified for this implementation')
    return {'schema_version': '1.0', 'source_run_id': source_run,
            'successor_run_id': successor_package['run_id'], 'source_task_id': source_task_id,
            'target_task_id': target_task_id, 'source_package_hash': package_hash(source_package),
            'successor_package_hash': package_hash(successor_package),
            'source_effective_contract_hash': effective_hash,
            'content_tree': source_content_tree, 'source_implementation_head': implementation['head_commit'],
            'source_implementation_base': implementation['base_commit'],
            'source_implementer': implementation['agent_id'],
            'source_reviewers': sorted(latest_by_reviewer),
            'source_review_hashes': sorted(hash_json(value) for value in latest_by_reviewer.values()),
            'source_verification_sequence': verification['sequence'],
            'source_review_sequence': approval['sequence'], 'evidence': evidence_receipts,
            'integration_verification_required': True}
