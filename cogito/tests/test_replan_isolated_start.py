"""RP Start Gate validates immutable controls without a disposable checkout."""
from __future__ import annotations

import copy
import os
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError, hash_json, load_json
from cogito_events import read_events
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import test_feature_multitask as feature_support
import test_replan_runtime_snapshot as runtime_support


class ReplanIsolatedStartTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)

    def ready(self):
        repo, worker, source, _ = self.fixture()
        source_package = Path(source.load()['package_path'])
        (repo / '.gitignore').write_text('')
        git(repo, 'rm', '--cached', 'docs/spec.md', 'docs/plan.md')
        git(repo, 'add', '.gitignore')
        git(repo, 'commit', '-qm', 'Leave source controls outside delivery HEAD')
        for path, text in {
            'docs/FS-039-spec.md': 'Unrelated FS-039 specification\n',
            'docs/FS-039-plan.md': 'Unrelated FS-039 plan\n',
        }.items():
            (repo / path).write_text(text)
        frozen = [source_package.as_posix(), 'docs/spec.md', 'docs/plan.md',
                  'docs/FS-039-spec.md', 'docs/FS-039-plan.md']
        porcelain = git(repo, 'status', '--porcelain=v1', '--untracked-files=all').splitlines()
        self.assertTrue(all(any(row.endswith(path) for row in porcelain) for path in frozen))
        index_path = Path(git(repo, 'rev-parse', '--git-path', 'index'))
        if not index_path.is_absolute():
            index_path = repo / index_path
        rp = ReplanStore(repo, 'RP-isolated-start')
        rp.begin(source.run_id, 'DEV-runtime-next', 'Change contract', 'begin')
        rp.stop('stop')
        checkpoint = copy.deepcopy(rp.load()['snapshot'])
        tree_paths = git(repo, 'ls-tree', '-r', '--name-only',
                         checkpoint['delivery']['content_tree']).splitlines()
        self.assertLessEqual(set(frozen), set(tree_paths))
        helper = runtime_support.ReplanRuntimeSnapshotTests('runTest')
        successor, proposal = helper.prepare_successor(repo, source)
        state = rp.propose(proposal, 'propose')
        digest = state['proposal_hash']
        rp.review({
            'proposal_hash': digest, 'reviewer_id': 'independent-reviewer', 'findings': [],
            'assessment': {key: 'Checked exact preserved sources and successor scope'
                           for key in ('impact', 'reuse', 'revalidation', 'handoff')},
        }, 'review')
        rp.approve(digest, 'approve')
        return (repo, worker, source, successor, rp, proposal, frozen, checkpoint,
                index_path, index_path.read_bytes())

    def test_handoff_uses_bound_object_start_and_preserves_root(self):
        (repo, worker, source, successor, rp, proposal, frozen, checkpoint,
         index_path, index_bytes) = self.ready()
        root_bytes = {path: (repo / path).read_bytes() for path in frozen}
        root_modes = {path: (repo / path).stat().st_mode for path in frozen}
        root_status = git(repo, 'status', '--porcelain=v1', '--untracked-files=all')
        worker_head = git(worker, 'rev-parse', 'HEAD')

        self.assertEqual(rp.handoff('handoff')['state'], 'completed')
        self.assertEqual(successor.load()['state'], 'executing')
        self.assertEqual(rp.load()['snapshot'], checkpoint)
        self.assertEqual(index_path.read_bytes(), index_bytes)
        self.assertEqual({path: (repo / path).read_bytes() for path in frozen}, root_bytes)
        self.assertEqual({path: (repo / path).stat().st_mode for path in frozen}, root_modes)
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), worker_head)
        self.assertEqual(git(worker, 'status', '--porcelain=v1'), '')
        target = repo / proposal['package']['slices'][0]['worker']['worktree']
        self.assertFalse((target / 'docs/FS-039-spec.md').exists())
        self.assertFalse((target / 'docs/FS-039-plan.md').exists())
        # Only normal handoff publications may extend root porcelain.
        after_status = git(repo, 'status', '--porcelain=v1', '--untracked-files=all')
        for path in frozen:
            self.assertIn(next(row for row in root_status.splitlines() if row.endswith(path)),
                          after_status.splitlines())

        starts = [event for event in read_events(successor.events_path)
                  if event['type'] == 'start-gate-passed']
        self.assertEqual(len(starts), 1)
        binding = starts[0]['payload']['replan_start']
        self.assertEqual(binding['replan_id'], rp.replan_id)
        self.assertEqual(binding['snapshot_hash'], hash_json(checkpoint))
        self.assertEqual(binding['start_artifact_hash'], rp.load()['proposal']['start_artifact_hash'])
        rp_events = rp.events_path.read_bytes()
        successor_events = successor.events_path.read_bytes()
        self.assertEqual(rp.handoff('handoff')['state'], 'completed')
        self.assertEqual(rp.events_path.read_bytes(), rp_events)
        self.assertEqual(successor.events_path.read_bytes(), successor_events)
        altered = copy.deepcopy(rp.load()['proposal']['start_artifact'])
        altered['tool_digest'] = '0' * 64
        with self.assertRaisesRegex(CogitoError, 'different content'):
            successor.start_gate_from_artifact(
                altered, binding, 'replan-start:' + rp.replan_id,
                successor._GATE_AUTHORITY,
            )

    def test_content_mode_stage_and_path_drift_are_rejected(self):
        for drift in ('content', 'mode', 'stage', 'path'):
            with self.subTest(drift=drift):
                (repo, worker, source, successor, rp, proposal, frozen, checkpoint,
                 index_path, index_bytes) = self.ready()
                path = repo / 'docs/FS-039-spec.md'
                if drift == 'content':
                    path.write_text('Changed outside successor scope\n')
                elif drift == 'mode':
                    path.chmod(path.stat().st_mode | 0o111)
                elif drift == 'stage':
                    git(repo, 'add', path.relative_to(repo).as_posix())
                else:
                    path.rename(repo / 'docs/FS-039-moved.md')
                graph = (repo / 'docs/cogito/project-graph.json').read_bytes()
                before = rp.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    rp.handoff('drift-' + drift)
                self.assertEqual(rp.events_path.read_bytes(), before)
                self.assertEqual(rp.load()['state'], 'ready-for-handoff')
                self.assertEqual(successor.load()['state'], 'start-gate')
                self.assertEqual((repo / 'docs/cogito/project-graph.json').read_bytes(), graph)
                self.assertEqual(rp.load()['snapshot'], checkpoint)

    def test_object_start_crash_retry_needs_no_validation_checkpoint(self):
        (repo, worker, source, successor, rp, proposal, frozen, checkpoint,
         index_path, index_bytes) = self.ready()
        with mock.patch.object(
                RunStore, 'start_gate_from_artifact', side_effect=CogitoError('injected validation crash')):
            with self.assertRaisesRegex(CogitoError, 'injected validation crash'):
                rp.handoff('handoff')
        self.assertEqual(rp.handoff('handoff')['state'], 'completed')
        rp_types = [event['type'] for event in read_events(rp.events_path)]
        new_types = [event['type'] for event in read_events(successor.events_path)]
        self.assertEqual(new_types.count('start-gate-passed'), 1)
        self.assertEqual(rp_types.count('handoff-completed'), 1)
        self.assertEqual(rp.load()['snapshot'], checkpoint)
        self.assertEqual(index_path.read_bytes(), index_bytes)


if __name__ == '__main__':
    import unittest
    unittest.main()
