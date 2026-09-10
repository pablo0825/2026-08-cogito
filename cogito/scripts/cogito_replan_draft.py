"""Prepare editable RP inputs without changing proposal or approval history."""
import copy
import json
import os
from pathlib import Path
import tempfile

from cogito_common import CogitoError
from cogito_contracts import package_hash, validate_package_with_limits
from cogito_replan_lock import project_lock


def _operation(store, command, arguments):
    return {'operation': 'replan', 'argv': [
        'python3', str(Path(__file__).with_name('cogito_gate.py')), '--repo', str(store.root),
        'replan', command, '--replan-id', store.replan_id, *arguments],
        'cwd': str(store.root)}


def _candidate(store, state):
    if state['state'] not in {'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}:
        raise CogitoError('RP draft requires a stopped source and an editable proposal phase')
    if state.get('toolchain_status') in {'reviewing', 'awaiting-approval'}:
        raise CogitoError('finish or reject the pending toolchain proposal before preparing the RP draft')
    from cogito_run_store import RunStore
    successor = RunStore(store.root, state['successor_run_id'])
    current = successor.load()
    candidate = (current.get('planning') or {}).get('candidate')
    if current['state'] != 'awaiting-package-approval':
        raise CogitoError('prepare the successor Package before generating the RP draft')
    if not candidate:
        raise CogitoError('RP draft requires a frozen successor candidate snapshot; complete normal Package preparation')
    package = candidate['package']
    validate_package_with_limits(package, successor.workflow['limits'])
    if package['run_id'] != successor.run_id or package_hash(package) != current['candidate_package_hash']:
        raise CogitoError('successor candidate snapshot does not match its recorded Package hash')
    successor._planning_approval_binding(current)
    return package


def proposal_guidance(store, state):
    # Do not distract an active review/approval or a recovery with a new draft.
    if (state['state'] not in {'analyzing', 'awaiting-decision'} and not state.get('proposal_stale')):
        return {}
    try:
        package = _candidate(store, state)
    except (CogitoError, OSError) as exc:
        return {'proposal_draft': {'operations': [], 'blockers': [str(exc)[:600]]}}
    digest = package_hash(package)
    return {'proposal_draft': {'candidate_package_hash': digest,
        'operations': [_operation(store, 'draft', ['--candidate-hash', digest])],
        'note': 'Generate an editable draft, fill the remaining judgments, then use the returned propose command. '
                'This does not submit, review or approve the proposal.'}}


def write_draft(store, candidate_hash):
    with project_lock(store.root):
        state = store.load()
        package = _candidate(store, state)
        if package_hash(package) != candidate_hash:
            raise CogitoError('RP draft candidate changed; query next or replan status for the current draft command')
        draft = {'package': copy.deepcopy(package), 'differences': {},
                 'work': [{'source_task_id': task_id} for task_id in state['snapshot']['tasks']]}
        directory = store.directory / 'drafts'
        if directory.resolve() != directory:
            raise CogitoError('RP draft directory must not contain symlinks; inspect the runtime path before retrying')
        directory.mkdir(parents=True, exist_ok=True)
        # Each invocation creates a new editable file, never replacing filled judgments.
        fd, filename = tempfile.mkstemp(prefix='proposal-', suffix='.json', dir=directory)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(draft, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        return {'draft_path': filename, 'candidate_package_hash': candidate_hash,
            'required_inputs': ['author_id', 'differences.requirements', 'differences.api',
                'differences.boundary', 'differences.acceptance', 'differences.cost', 'differences.revalidation',
                'work[].target_task_id', 'work[].disposition', 'work[].validation', 'work[].reason'],
            'operations': [_operation(store, 'propose', ['--input', filename, '--action-id', '<action-id>'])],
            'note': 'Edit the draft file to supply real judgments before propose. An Atomic successor requires '
                'omit, null target and rerun under the existing RP rules. A changed candidate requires a new draft; '
                'a failed propose must be recovered with its original input file and action ID.'}
