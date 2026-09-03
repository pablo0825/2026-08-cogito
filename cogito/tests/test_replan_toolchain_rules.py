"""Malformed toolchain contracts must fail closed without mutating projections."""

from copy import deepcopy
import unittest

import cogito_test_support
from cogito_common import CogitoError, hash_json
from cogito_replan_state import project_replan
from cogito_replan_toolchain_rules import (
    ASSESSMENTS, TOOL_ROOT, VIEWS, differences, project_toolchain,
    validate_binding, validate_proposal, validate_review,
)


class ReplanToolchainRulesTests(unittest.TestCase):
    def setUp(self):
        self.before = dict(head='a' * 40, branch='main', version='3.0-old',
                           manifests={view: {TOOL_ROOT + '/VERSION':
                                      dict(mode='100644', oid='b' * 40)} for view in VIEWS})
        self.after = deepcopy(self.before)
        self.after['version'] = '3.0-new'
        self.after['manifests']['content'][TOOL_ROOT + '/VERSION']['oid'] = 'c' * 40
        self.state = dict(state='analyzing', snapshot=dict(
            delivery=dict(head='a' * 40, branch='main'), tasks={},
            package_hash='d' * 64, effective_contract_hash='e' * 64))
        self.proposal = dict(
            schema_version=1, tool_root=TOOL_ROOT, author_id='maintainer', reason='Repair RP',
            source_snapshot_hash=hash_json(self.state['snapshot']), previous_toolchain_hash=None,
            before=self.before, after=self.after, differences=differences(self.before, self.after),
            commits=[], compatibility=dict(
                schema_version=1, **{key: True for key in ASSESSMENTS},
                executor_hash='f' * 64, workflow_hash='1' * 64,
                source_package_hash='d' * 64, effective_contract_hash='e' * 64,
                candidate_package_hash=None,
                required_revalidation=['fresh RP proposal', 'independent RP review',
                                       'successor Package approval', 'all successor checks; no evidence reuse']))
        self.digest = hash_json(self.proposal)
        self.review = dict(proposal_hash=self.digest, reviewer_id='reviewer', findings=[],
                           assessment={key: 'Checked preserved bindings' for key in ASSESSMENTS})

    def test_valid_contracts_and_both_git_object_formats(self):
        validate_proposal(self.proposal, self.state)
        validate_review(self.review, self.proposal, self.digest)
        value = deepcopy(self.before)
        value['head'] = 'a' * 64
        for manifest in value['manifests'].values():
            manifest[TOOL_ROOT + '/VERSION']['oid'] = 'b' * 64
        validate_binding(value)

    def test_schema_versions_require_integers_not_bool_float_or_string(self):
        for target in ('proposal', 'compatibility'):
            for value in (True, False, 1.0, '1', None, [], {}):
                with self.subTest(target=target, value=value):
                    proposal = deepcopy(self.proposal)
                    container = proposal if target == 'proposal' else proposal['compatibility']
                    container['schema_version'] = value
                    with self.assertRaises(CogitoError):
                        validate_proposal(proposal, self.state)

    def test_manifest_paths_cannot_escape_or_alias_tool_root(self):
        for path in ('src/product.py', TOOL_ROOT, TOOL_ROOT + '/', TOOL_ROOT + '/../product.py',
                     TOOL_ROOT + '//gate.py', TOOL_ROOT + '/./gate.py',
                     TOOL_ROOT + '/gate\\other.py', TOOL_ROOT + '/gate\0.py',
                     '/' + TOOL_ROOT + '/gate.py', TOOL_ROOT + '-other/gate.py', 42):
            with self.subTest(path=path):
                value = deepcopy(self.before)
                value['manifests']['content'] = {path: dict(mode='100644', oid='b' * 40)}
                with self.assertRaises(CogitoError):
                    validate_binding(value)

    def test_manifest_types_modes_and_object_ids_fail_with_contract_errors(self):
        for field, values in (
            ('mode', (None, True, 100644, [], {}, '120000', '160000', '040000')),
            ('oid', (None, True, 123, [], {}, '', 'z' * 40, 'a' * 39, 'A' * 40)),
        ):
            for invalid in values:
                with self.subTest(field=field, invalid=invalid):
                    value = deepcopy(self.before)
                    value['manifests']['content'][TOOL_ROOT + '/VERSION'][field] = invalid
                    with self.assertRaises(CogitoError):
                        validate_binding(value)
        for invalid in (None, [], 'content', {'content': {}}, {**self.before['manifests'], 'extra': {}}):
            with self.subTest(manifests=invalid):
                value = deepcopy(self.before)
                value['manifests'] = invalid
                with self.assertRaises(CogitoError):
                    validate_binding(value)

    def test_compatibility_hashes_and_revalidation_cannot_be_empty_claims(self):
        for field in ('executor_hash', 'workflow_hash', 'source_package_hash', 'effective_contract_hash'):
            for invalid in ('', 'not-a-hash', True, [], None):
                with self.subTest(field=field, invalid=invalid):
                    proposal = deepcopy(self.proposal)
                    proposal['compatibility'][field] = invalid
                    with self.assertRaises(CogitoError):
                        validate_proposal(proposal, self.state)
        for invalid in (None, '', 'rerun', [], [False]):
            with self.subTest(revalidation=invalid):
                proposal = deepcopy(self.proposal)
                proposal['compatibility']['required_revalidation'] = invalid
                with self.assertRaises(CogitoError):
                    validate_proposal(proposal, self.state)
        for key in ASSESSMENTS:
            proposal = deepcopy(self.proposal)
            proposal['compatibility'][key] = 1
            with self.subTest(claim=key), self.assertRaises(CogitoError):
                validate_proposal(proposal, self.state)

    def test_snapshot_previous_approval_and_diff_are_bound(self):
        for field, invalid in (('source_snapshot_hash', '0' * 64),
                               ('previous_toolchain_hash', '0' * 64), ('differences', {})):
            proposal = deepcopy(self.proposal)
            proposal[field] = invalid
            with self.subTest(field=field), self.assertRaises(CogitoError):
                validate_proposal(proposal, self.state)
        proposal = deepcopy(self.proposal)
        proposal['after'] = deepcopy(proposal['before'])
        proposal['differences'] = differences(proposal['before'], proposal['after'])
        with self.assertRaises(CogitoError):
            validate_proposal(proposal, self.state)

    def test_commit_lists_must_match_effective_head_and_preserve_branch(self):
        for commits in (None, 'a' * 40, [True], [['a' * 40]], ['a' * 40]):
            proposal = deepcopy(self.proposal)
            proposal['commits'] = commits
            with self.subTest(commits=commits), self.assertRaises(CogitoError):
                validate_proposal(proposal, self.state)
        for commits in ([], ['b' * 40], ['c' * 40, 'c' * 40]):
            proposal = deepcopy(self.proposal)
            proposal['after']['head'] = 'c' * 40
            proposal['commits'] = commits
            with self.subTest(moved_head_commits=commits), self.assertRaises(CogitoError):
                validate_proposal(proposal, self.state)
        proposal = deepcopy(self.proposal)
        proposal['after']['branch'] = 'other-branch'
        with self.assertRaises(CogitoError):
            validate_proposal(proposal, self.state)

    def test_contract_hashes_must_match_frozen_source_contract(self):
        for field in ('source_package_hash', 'effective_contract_hash'):
            proposal = deepcopy(self.proposal)
            proposal['compatibility'][field] = '0' * 64
            with self.subTest(field=field), self.assertRaises(CogitoError):
                validate_proposal(proposal, self.state)

    def test_stale_self_review_and_unresolved_findings_are_rejected(self):
        for field, invalid in (('proposal_hash', '0' * 64), ('reviewer_id', 'maintainer'),
                               ('reviewer_id', True), ('findings', ['unresolved']),
                               ('findings', None), ('assessment', [])):
            review = deepcopy(self.review)
            review[field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(CogitoError):
                validate_review(review, self.proposal, self.digest)

    def test_out_of_order_events_do_not_mutate_projection(self):
        for kind, payload in (
            ('toolchain-reviewed', self.review),
            ('toolchain-approved', dict(proposal_hash=self.digest, approver_id='user')),
            ('toolchain-rejected', dict(proposal_hash=self.digest, reason='Withdraw')),
            ('toolchain-unknown', {}),
        ):
            state = deepcopy(self.state)
            with self.subTest(kind=kind), self.assertRaises(CogitoError):
                project_toolchain(state, kind, payload)
            self.assertEqual(state, self.state)

    def test_toolchain_events_are_rejected_after_product_approval(self):
        for stage in ('stopping', 'ready-for-handoff', 'handing-off', 'completed', 'abandoned', 'disposition'):
            state = deepcopy(self.state)
            state['state'] = stage
            before = deepcopy(state)
            with self.subTest(stage=stage), self.assertRaises(CogitoError):
                project_toolchain(state, 'toolchain-proposed', dict(proposal=self.proposal, proposal_hash=self.digest))
            self.assertEqual(state, before)

    def test_pending_toolchain_blocks_product_approval_in_event_projection(self):
        events = [
            dict(type='replan-created', payload=dict(
                replan_id='RP-contract', source_run_id='DEV-old', successor_run_id='DEV-next',
                source_package_hash='d' * 64, reason='New dependency requirement')),
            dict(type='replan-stopped', payload=dict(snapshot=deepcopy(self.state['snapshot']))),
            dict(type='proposal-prepared', payload=dict(proposal={}, proposal_hash='2' * 64)),
            dict(type='proposal-reviewed', payload=dict(proposal_hash='2' * 64)),
            dict(type='toolchain-proposed', payload=dict(proposal=self.proposal, proposal_hash=self.digest)),
        ]
        self.assertEqual(project_replan(events)['toolchain_status'], 'reviewing')
        with self.assertRaises(CogitoError):
            project_replan(events + [dict(type='successor-approved', payload=dict(proposal_hash='2' * 64))])

    def test_rejection_never_grants_toolchain_approval(self):
        state = deepcopy(self.state)
        project_toolchain(state, 'toolchain-proposed', dict(proposal=self.proposal, proposal_hash=self.digest))
        project_toolchain(state, 'toolchain-rejected', dict(proposal_hash=self.digest, reason='Incompatible'))
        self.assertEqual(state['toolchain_status'], 'rejected')
        self.assertNotIn('toolchain', state)
        before = deepcopy(state)
        with self.assertRaises(CogitoError):
            project_toolchain(state, 'toolchain-approved', dict(proposal_hash=self.digest, approver_id='user'))
        self.assertEqual(state, before)

    def test_rejected_replacement_preserves_previously_approved_binding(self):
        state = deepcopy(self.state)
        project_toolchain(state, 'toolchain-proposed', dict(proposal=self.proposal, proposal_hash=self.digest))
        project_toolchain(state, 'toolchain-reviewed', self.review)
        project_toolchain(state, 'toolchain-approved', dict(proposal_hash=self.digest, approver_id='user'))
        approved = deepcopy(state['toolchain'])
        replacement = deepcopy(self.proposal)
        replacement['previous_toolchain_hash'] = self.digest
        replacement['before'] = deepcopy(self.after)
        replacement['after']['version'] = '3.0-next'
        replacement['after']['manifests']['content'][TOOL_ROOT + '/VERSION']['oid'] = '3' * 40
        replacement['differences'] = differences(replacement['before'], replacement['after'])
        replacement_hash = hash_json(replacement)
        project_toolchain(state, 'toolchain-proposed', dict(proposal=replacement, proposal_hash=replacement_hash))
        project_toolchain(state, 'toolchain-rejected', dict(proposal_hash=replacement_hash, reason='Declined'))
        self.assertEqual(state['toolchain'], approved)
        self.assertEqual(state['toolchain_status'], 'rejected')

    def test_approval_clears_current_product_authorization_and_preserves_snapshot(self):
        state = deepcopy(self.state)
        state.update(proposal={'old': True}, proposal_hash='2' * 64, review={'old': True})
        snapshot = deepcopy(state['snapshot'])
        project_toolchain(state, 'toolchain-proposed', dict(proposal=self.proposal, proposal_hash=self.digest))
        project_toolchain(state, 'toolchain-reviewed', self.review)
        project_toolchain(state, 'toolchain-approved', dict(proposal_hash=self.digest, approver_id='user'))
        self.assertEqual(state['state'], 'analyzing')
        self.assertEqual(state['snapshot'], snapshot)
        self.assertEqual(state['toolchain']['proposal_hash'], self.digest)
        for field in ('proposal', 'proposal_hash', 'review', 'approval'):
            self.assertNotIn(field, state)


if __name__ == '__main__':
    unittest.main()
