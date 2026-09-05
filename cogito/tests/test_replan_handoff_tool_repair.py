"""An interrupted RP may adopt an exact committed Gate-only repair."""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest import mock

from cogito_test_support import COGITO, GitTestCase, git
from cogito_common import CogitoError, hash_json
from cogito_events import read_events
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import test_feature_multitask as feature_support
import test_replan_runtime_snapshot as runtime_support
import test_replan_toolchain as tool_support


class HandoffToolCli(tool_support.ToolchainCli):
    def handoff_tool_propose(self, value, action_id):
        return self.call('handoff-tool-propose', action_id, value)

    def handoff_tool_review(self, value, action_id):
        return self.call('handoff-tool-review', action_id, value)

    def handoff_tool_approve(self, digest, approver, action_id):
        return self.call('handoff-tool-approve', action_id,
                         proposal_hash=digest, approver_id=approver)


class ReplanHandoffToolRepairTests(GitTestCase):
    result = staticmethod(feature_support.FeatureMultitaskTests.result)
    TOOL_ROOT = '.codex/skills/cogito'

    def handing_off(self):
        repo, worker, source, _ = tool_support.ReplanToolchainTests.fixture(self)
        rp = ReplanStore(repo, 'RP-handoff-repair')
        rp.begin(source.run_id, 'DEV-runtime-next', 'Change dependency contract', 'begin')
        rp.stop('stop')
        successor, proposal = runtime_support.ReplanRuntimeSnapshotTests.prepare_successor(
            self, repo, source)
        state = rp.propose(proposal, 'product-propose')
        digest = state['proposal_hash']
        review = dict(
            proposal_hash=digest, reviewer_id='independent-product-reviewer', findings=[],
            assessment={key: 'Checked exact preserved product proposal' for key in
                        ('impact', 'reuse', 'revalidation', 'handoff')})
        rp.review(review, 'product-review')
        rp.approve(digest, 'product-approve')
        rp._emit('handoff-started', {'proposal_hash': digest},
                 'handoff-intent:' + rp.replan_id, 'handoff-intent', {})
        state = rp.load()
        self.assertEqual(state['state'], 'handing-off')
        self.assertEqual(successor.load()['state'], 'start-gate')
        self.assertFalse(state['transfer_plans'])
        self.assertFalse(state['transfers'])
        protected = {key: state[key] for key in
                     ('proposal', 'proposal_hash', 'review', 'approval', 'handoff')}
        return repo, source, successor, rp, protected

    def commit_repair(self, repo, *, product=False):
        (repo / self.TOOL_ROOT / 'VERSION').write_bytes((COGITO / 'VERSION').read_bytes())
        git(repo, 'add', self.TOOL_ROOT)
        if product:
            (repo / 'src/a.txt').write_text('unauthorized product change\n')
            git(repo, 'add', 'src/a.txt')
        git(repo, 'commit', '-qm', 'Repair interrupted RP Gate')

    @staticmethod
    def request():
        return dict(author_id='tool-maintainer', reason='Repair interrupted handoff Gate',
                    tool_root='.codex/skills/cogito')

    @staticmethod
    def review(digest):
        return dict(
            proposal_hash=digest, reviewer_id='independent-tool-reviewer', findings=[],
            assessment={key: 'Verified exact repair and preserved handoff' for key in
                        ('events', 'contracts', 'projection', 'workflow', 'revalidation')})

    def assert_product_authorization(self, rp, protected):
        state = rp.load()
        self.assertEqual(state['state'], 'handing-off')
        for key, value in protected.items():
            self.assertEqual(state[key], value)

    def test_committed_gate_only_repair_preserves_handoff_and_replays(self):
        repo, source, successor, store, protected = self.handing_off()
        self.commit_repair(repo)
        rp = HandoffToolCli(store)
        proposed = rp.handoff_tool_propose(self.request(), 'repair-propose')
        digest = proposed['handoff_tool_proposal_hash']
        reviewed = rp.handoff_tool_review(self.review(digest), 'repair-review')
        self.assertEqual(reviewed['handoff_tool_status'], 'awaiting-approval')
        approved = rp.handoff_tool_approve(digest, 'synthetic-user', 'repair-approve')
        self.assertEqual(approved['handoff_tool_status'], 'approved')
        self.assert_product_authorization(rp, protected)
        history = rp.events_path.read_bytes()
        for operation in (
            lambda: rp.handoff_tool_propose(self.request(), 'repair-propose'),
            lambda: rp.handoff_tool_review(self.review(digest), 'repair-review'),
            lambda: rp.handoff_tool_approve(digest, 'synthetic-user', 'repair-approve')):
            self.assertEqual(operation()['state'], 'handing-off')
        self.assertEqual(rp.events_path.read_bytes(), history)
        self.assert_product_authorization(rp, protected)
        types = [event['type'] for event in read_events(rp.events_path)]
        self.assertEqual(types.count('handoff-tool-proposed'), 1)
        self.assertEqual(types.count('handoff-tool-reviewed'), 1)
        self.assertEqual(types.count('handoff-tool-approved'), 1)
        self.assertEqual(rp.handoff('original-handoff')['state'], 'completed')
        self.assertEqual(successor.load()['state'], 'executing')
        self.assertEqual(source.load()['state'], 'superseded')

    def test_pending_repair_blocks_original_handoff(self):
        repo, _, successor, store, protected = self.handing_off()
        self.commit_repair(repo)
        rp = HandoffToolCli(store)
        proposed = rp.handoff_tool_propose(self.request(), 'repair-propose')
        digest = proposed['handoff_tool_proposal_hash']
        self.assertIn('independently review', proposed['next_action'])
        self.assertIn('exact', proposed['next_action'])
        for status in ('reviewing', 'awaiting-approval'):
            with self.subTest(status=status):
                self.assertEqual(rp.load()['handoff_tool_status'], status)
                before = rp.events_path.read_bytes()
                with self.assertRaisesRegex(CogitoError, 'pending handoff tool repair'):
                    rp.handoff('resume-original-handoff')
                self.assertEqual(rp.events_path.read_bytes(), before)
                self.assertEqual(successor.load()['state'], 'start-gate')
                self.assert_product_authorization(rp, protected)
            if status == 'reviewing':
                reviewed = rp.handoff_tool_review(self.review(digest), 'repair-review')
                self.assertIn('human approval', reviewed['next_action'])
                self.assertIn('exact', reviewed['next_action'])
        approved = rp.handoff_tool_approve(digest, 'synthetic-user', 'repair-approve')
        self.assertNotIn('human approval', approved['next_action'])
        self.assertEqual(rp.handoff('resume-original-handoff')['state'], 'completed')
        self.assertEqual(successor.load()['state'], 'executing')

    def test_mixed_product_commit_and_uncommitted_repair_are_rejected(self):
        for mode in ('mixed', 'uncommitted'):
            with self.subTest(mode=mode):
                repo, _, _, store, protected = self.handing_off()
                if mode == 'mixed':
                    self.commit_repair(repo, product=True)
                else:
                    (repo / self.TOOL_ROOT / 'VERSION').write_bytes((COGITO / 'VERSION').read_bytes())
                rp = HandoffToolCli(store)
                before = rp.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    rp.handoff_tool_propose(self.request(), 'invalid-repair')
                self.assertEqual(rp.events_path.read_bytes(), before)
                self.assert_product_authorization(rp, protected)

    def test_repair_is_rejected_after_transfer_or_successor_start(self):
        for boundary in ('transfer', 'started'):
            with self.subTest(boundary=boundary):
                repo, _, successor, store, protected = self.handing_off()
                self.commit_repair(repo)
                if boundary == 'transfer':
                    store._emit('work-transfer-planned', {'task_id': 'T-1'},
                                'synthetic-plan', 'transfer-plan', {'row': {}})
                    before = store.events_path.read_bytes()
                    with self.assertRaisesRegex(CogitoError, 'before successor start and work transfer'):
                        store.handoff_tool_propose(self.request(), 'late-repair')
                else:
                    original = RunStore.load
                    def executing(instance):
                        state = original(instance)
                        if instance.run_id == successor.run_id:
                            return {**state, 'state': 'executing'}
                        return state
                    before = store.events_path.read_bytes()
                    with mock.patch.object(RunStore, 'load', new=executing):
                        with self.assertRaisesRegex(CogitoError, 'before successor start and work transfer'):
                            store.handoff_tool_propose(self.request(), 'late-repair')
                self.assertEqual(store.events_path.read_bytes(), before)
                self.assert_product_authorization(store, protected)


if __name__ == '__main__':
    import unittest
    unittest.main()
