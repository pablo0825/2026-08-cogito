"""Pure contracts for separately authorized RP toolchain transitions."""
from __future__ import annotations

from pathlib import PurePosixPath
import re

from cogito_common import CogitoError, hash_json

TOOL_ROOT = '.codex/skills/cogito'
STAGES = {'analyzing', 'reviewing', 'awaiting-approval', 'awaiting-decision'}
ASSESSMENTS = ('events', 'contracts', 'projection', 'workflow', 'revalidation')
VIEWS = ('head', 'index', 'content')
REVALIDATION = ['fresh RP proposal', 'independent RP review', 'successor Package approval',
                'all successor checks; no evidence reuse']


def digest(value, label, *, git=False):
    pattern = r'(?:[0-9a-f]{40}|[0-9a-f]{64})' if git else r'[0-9a-f]{64}'
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise CogitoError('invalid ' + label + ' hash')


def text(value, name):
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise CogitoError(f'{name} must be nonempty text')


def validate_binding(binding):
    if not isinstance(binding, dict):
        raise CogitoError('invalid toolchain binding')
    for key in ('head', 'branch', 'version'):
        text(binding.get(key), 'toolchain ' + key)
    digest(binding['head'], 'toolchain HEAD', git=True)
    manifests = binding.get('manifests')
    if not isinstance(manifests, dict) or set(manifests) != set(VIEWS):
        raise CogitoError('toolchain requires separate HEAD, index and content manifests')
    for manifest in manifests.values():
        if not isinstance(manifest, dict):
            raise CogitoError('invalid toolchain manifest')
        for path, entry in manifest.items():
            if (not isinstance(path, str) or not path.startswith(TOOL_ROOT + '/')
                    or str(PurePosixPath(path)) != path or '..' in PurePosixPath(path).parts
                    or '\\' in path or '\0' in path):
                raise CogitoError('invalid toolchain manifest path')
            if (not isinstance(entry, dict) or set(entry) != {'mode', 'oid'}
                    or not isinstance(entry['mode'], str) or entry['mode'] not in {'100644', '100755'}
                    or not isinstance(entry['oid'], str)
                    or not re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', entry['oid'])):
                raise CogitoError('toolchain manifest requires regular Git blobs')


def differences(before, after):
    return {view: {path: {'before': before['manifests'][view].get(path),
                         'after': after['manifests'][view].get(path)}
                   for path in sorted(before['manifests'][view].keys() | after['manifests'][view].keys())
                   if before['manifests'][view].get(path) != after['manifests'][view].get(path)}
            for view in VIEWS}


def validate_proposal(proposal, state):
    if (not isinstance(proposal, dict) or type(proposal.get('schema_version')) is not int
            or proposal.get('schema_version') != 1):
        raise CogitoError('unsupported toolchain proposal version')
    if proposal.get('tool_root') != TOOL_ROOT:
        raise CogitoError('RP toolchain adoption only supports ' + TOOL_ROOT)
    for key in ('author_id', 'reason'):
        text(proposal.get(key), key)
    if proposal.get('source_snapshot_hash') != hash_json(state['snapshot']):
        raise CogitoError('toolchain proposal is not bound to the original snapshot')
    if proposal.get('previous_toolchain_hash') != (state.get('toolchain') or {}).get('proposal_hash'):
        raise CogitoError('toolchain proposal refers to a stale effective toolchain')
    for key in ('before', 'after'):
        validate_binding(proposal.get(key))
    prior = state.get('toolchain')
    if prior and proposal['before'] != prior['proposal']['after']:
        raise CogitoError('toolchain proposal does not start at the approved binding')
    if not prior and (proposal['before']['head'] != state['snapshot']['delivery']['head']
                      or proposal['before']['branch'] != state['snapshot']['delivery']['branch']):
        raise CogitoError('toolchain proposal does not start at the stopped delivery baseline')
    if proposal['before']['branch'] != proposal['after']['branch']:
        raise CogitoError('toolchain proposal cannot change branch')
    commits = proposal.get('commits')
    if not isinstance(commits, list):
        raise CogitoError('toolchain proposal requires a commit list')
    for commit in commits:
        digest(commit, 'toolchain commit', git=True)
    if (len(commits) != len(set(commits))
            or (proposal['before']['head'] == proposal['after']['head'] and commits)
            or (proposal['before']['head'] != proposal['after']['head']
                and (not commits or commits[-1] != proposal['after']['head']))):
        raise CogitoError('toolchain commit list does not bind the effective HEAD')
    if proposal.get('differences') != differences(proposal['before'], proposal['after']):
        raise CogitoError('toolchain differences do not match the manifests')
    if proposal['before'] == proposal['after']:
        raise CogitoError('toolchain proposal contains no change')
    compatibility = proposal.get('compatibility')
    if (not isinstance(compatibility, dict) or type(compatibility.get('schema_version')) is not int
            or compatibility.get('schema_version') != 1
            or any(compatibility.get(key) is not True for key in ASSESSMENTS)
            or compatibility.get('required_revalidation') != REVALIDATION):
        raise CogitoError('toolchain compatibility checks are incomplete')
    for key in ('executor_hash', 'workflow_hash', 'source_package_hash', 'effective_contract_hash'):
        digest(compatibility.get(key), key)
    if compatibility.get('candidate_package_hash') is not None:
        digest(compatibility['candidate_package_hash'], 'candidate Package')
    if (compatibility['source_package_hash'] != state['snapshot']['package_hash']
            or compatibility['effective_contract_hash'] != state['snapshot']['effective_contract_hash']):
        raise CogitoError('toolchain compatibility does not preserve the stopped contract')


def validate_review(review, proposal, digest):
    if not isinstance(review, dict) or review.get('proposal_hash') != digest:
        raise CogitoError('toolchain review must reference the current proposal hash')
    text(review.get('reviewer_id'), 'reviewer_id')
    if review['reviewer_id'] == proposal['author_id']:
        raise CogitoError('toolchain proposal author cannot independently review it')
    if review.get('findings') != [] or not isinstance(review.get('assessment'), dict):
        raise CogitoError('resolve toolchain findings and provide structured assessment')
    for key in ASSESSMENTS:
        text(review['assessment'].get(key), 'toolchain assessment.' + key)


def project_tool_review(result, kind, payload, *, handoff=False):
    """Project shared review steps; callers validate family eligibility/proposals."""
    prefix = 'handoff_tool' if handoff else 'toolchain'
    family = 'handoff-tool' if handoff else 'toolchain'
    label = 'handoff tool' if handoff else 'toolchain'
    status = result.get(prefix + '_status')
    if kind == family + '-proposed':
        proposal = payload.get('proposal')
        if payload.get('proposal_hash') != hash_json(proposal):
            raise CogitoError(label + ' proposal hash mismatch')
        result.update({prefix + '_proposal': proposal,
                       prefix + '_proposal_hash': payload['proposal_hash'],
                       prefix + '_review': None, prefix + '_status': 'reviewing'})
    elif kind == family + '-reviewed':
        if status != 'reviewing':
            raise CogitoError(label + ' review requires a current proposal')
        validate_review(payload, result[prefix + '_proposal'], result[prefix + '_proposal_hash'])
        result.update({prefix + '_review': payload, prefix + '_status': 'awaiting-approval'})
    elif kind == family + '-approved':
        if status != 'awaiting-approval' or payload.get('proposal_hash') != result[prefix + '_proposal_hash']:
            raise CogitoError(label + ' approval requires the independently reviewed exact proposal')
        text(payload.get('approver_id'), 'approver_id')
        proposal = result[prefix + '_proposal']
        result.update({'runtime_toolchain' if handoff else 'toolchain': {
            'proposal_hash': payload['proposal_hash'], 'proposal': proposal,
            'review': result[prefix + '_review'], 'approver_id': payload['approver_id']},
            prefix + '_status': 'approved'})
    elif kind == family + '-rejected':
        if status not in {'reviewing', 'awaiting-approval'} or payload.get('proposal_hash') != result.get(prefix + '_proposal_hash'):
            raise CogitoError(label + ' rejection must reference the pending proposal')
        text(payload.get('reason'), 'reason')
        result.update({prefix + '_status': 'rejected', prefix + '_rejection': payload})
    else:
        raise CogitoError('invalid ' + label + ' event')


def project_toolchain(result, kind, payload):
    if result['state'] not in STAGES:
        raise CogitoError('toolchain adoption requires an unapproved, stopped RP')
    if kind == 'toolchain-proposed':
        validate_proposal(payload.get('proposal'), result)
    elif (kind == 'toolchain-approved' and result.get('toolchain_status') == 'awaiting-approval'
          and payload.get('proposal_hash') == result.get('toolchain_proposal_hash')):
        validate_proposal(result['toolchain_proposal'], result)
    project_tool_review(result, kind, payload)
    if kind == 'toolchain-approved':
        result['state'] = 'analyzing'
        for key in ('proposal', 'proposal_hash', 'review', 'approval', 'rejection', 'proposal_stale'):
            result.pop(key, None)
