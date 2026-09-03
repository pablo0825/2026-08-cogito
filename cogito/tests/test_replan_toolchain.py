"""RP tool upgrades require a separate, exact and append-only approval."""

from __future__ import annotations

import copy
import shutil
import json
import subprocess
import sys
import importlib.util
import importlib._bootstrap_external
from unittest import mock
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase, git
from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_events import read_events
from cogito_run_store import RunStore
import test_feature_multitask as feature_support
import test_replan_runtime_snapshot as runtime_support


class ToolchainCli:
    """Every protected operation runs the actual source-bound public CLI."""

    def __init__(self, store):
        self.store = store
        self.root, self.replan_id = store.root, store.replan_id
        self.events_path, self.directory = store.events_path, store.directory

    def load(self):
        return self.store.load()

    def call(self, operation, action_id, value=None, **options):
        argv = [sys.executable, '-B', str(self.root / '.codex/skills/cogito/scripts/cogito_gate.py'),
                '--repo', str(self.root), 'replan', operation, '--replan-id', self.replan_id,
                '--action-id', action_id]
        if value is not None:
            path = self.directory / 'drafts' / (action_id + '.json')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            options['input'] = path
        for key, value in options.items():
            argv.extend(['--' + key.replace('_', '-'), str(value)])
        result = subprocess.run(argv, text=True, capture_output=True, timeout=60)
        if result.returncode:
            raise CogitoError(result.stderr)
        return json.loads(result.stdout)['data']

    def toolchain_propose(self, value, action_id):
        return self.call('toolchain-propose', action_id, value)

    def toolchain_review(self, value, action_id):
        return self.call('toolchain-review', action_id, value)

    def toolchain_approve(self, digest, approver, action_id):
        return self.call('toolchain-approve', action_id, proposal_hash=digest, approver_id=approver)

    def toolchain_reject(self, digest, reason, action_id):
        return self.call('toolchain-reject', action_id, proposal_hash=digest, reason=reason)

    def propose(self, value, action_id):
        return self.call('propose', action_id, value)

    def review(self, value, action_id):
        return self.call('review', action_id, value)

    def approve(self, digest, action_id):
        return self.call('approve', action_id, proposal_hash=digest)

    def handoff(self, action_id):
        return self.call('handoff', action_id)

    def abandon(self, disposition, reason, action_id):
        return self.call('abandon', action_id, disposition=disposition, reason=reason)


class ReplanToolchainTests(GitTestCase):
    result = staticmethod(feature_support.FeatureMultitaskTests.result)
    stopped = runtime_support.ReplanRuntimeSnapshotTests.stopped
    legacy_capture = staticmethod(runtime_support.ReplanRuntimeSnapshotTests.legacy_capture)
    legacy_emit = staticmethod(runtime_support.ReplanRuntimeSnapshotTests.legacy_emit)
    prepare_successor = runtime_support.ReplanRuntimeSnapshotTests.prepare_successor
    TOOL_ROOT = '.codex/skills/cogito'

    def fixture(self):
        result = feature_support.FeatureMultitaskTests.fixture(self)
        repo = result[0]
        tool = repo / self.TOOL_ROOT
        shutil.copytree(COGITO, tool, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.mypy_cache'))
        # The stopped installation predates the executing implementation. Restore
        # these exact current bytes only after the original snapshot is durable.
        (tool / 'VERSION').write_text('3.0.0-before-toolchain\n')
        git(repo, 'add', self.TOOL_ROOT)
        git(repo, 'commit', '-qm', 'Install original project-local Cogito')
        return result

    def upgraded(self, *, legacy=False, committed=False, staged=False):
        repo, worker, source, rp, _, _ = self.stopped(legacy=legacy)
        snapshot = copy.deepcopy(rp.load()['snapshot'])
        (repo / self.TOOL_ROOT / 'VERSION').write_bytes((COGITO / 'VERSION').read_bytes())
        if staged or committed:
            git(repo, 'add', self.TOOL_ROOT)
        if committed:
            git(repo, 'commit', '-qm', 'Upgrade only project-local Cogito')
        successor, proposal = self.prepare_successor(repo, source)
        return repo, worker, source, ToolchainCli(rp), successor, proposal, snapshot

    def request(self):
        return dict(author_id='tool-maintainer', reason='Fix RP runtime snapshot compatibility',
                    tool_root=self.TOOL_ROOT)

    @staticmethod
    def review(digest, *, reviewer='independent-tool-reviewer'):
        return dict(proposal_hash=digest, reviewer_id=reviewer, findings=[],
                    assessment={key: 'Verified preserved history and compatibility' for key in (
                        'events', 'contracts', 'projection', 'workflow', 'revalidation')})

    def approve_tool(self, rp):
        digest = rp.toolchain_propose(self.request(), 'tool-propose')['toolchain_proposal_hash']
        rp.toolchain_review(self.review(digest), 'tool-review')
        rp.toolchain_approve(digest, 'synthetic-user', 'tool-approve')
        return digest

    def test_new_and_legacy_snapshot_resume_after_exact_tool_approval(self):
        for legacy, committed, staged in ((False, False, False), (True, False, False),
                                          (False, False, True), (True, False, True),
                                          (False, True, False), (True, True, False)):
            with self.subTest(legacy=legacy, committed=committed, staged=staged):
                repo, worker, source, rp, _, proposal, snapshot = self.upgraded(
                    legacy=legacy, committed=committed, staged=staged)
                history = rp.events_path.read_bytes()
                source_history = source.events_path.read_bytes()
                package = source.approved_package()
                worker_head = git(worker, 'rev-parse', 'HEAD')
                with self.assertRaises(CogitoError):
                    rp.propose(proposal, 'blocked-before-tool-approval')
                self.assertEqual(rp.events_path.read_bytes(), history)
                self.approve_tool(rp)
                self.assertEqual(rp.load()['state'], 'analyzing')
                self.assertEqual(rp.propose(proposal, 'product-propose')['state'], 'reviewing')
                self.assertEqual(rp.load()['snapshot'], snapshot)
                self.assertTrue(rp.events_path.read_bytes().startswith(history))
                self.assertEqual(source.events_path.read_bytes(), source_history)
                self.assertEqual(source.approved_package(), package)
                self.assertEqual(git(worker, 'rev-parse', 'HEAD'), worker_head)
                self.assertEqual(git(worker, 'status', '--porcelain'), '')

    def test_committed_upgrade_completes_normal_rp_handoff(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                repo, worker, source, rp, successor, proposal, snapshot = self.upgraded(
                    legacy=legacy, committed=True)
                old_package = source.approved_package()
                old_worker = git(worker, 'rev-parse', 'HEAD')
                old_history = rp.events_path.read_bytes()
                self.approve_tool(rp)
                self.assertNotEqual(git(repo, 'rev-parse', 'HEAD'), snapshot['delivery']['head'])
                state = rp.propose(proposal, 'product-propose')
                digest = state['proposal_hash']
                rp.review(dict(proposal_hash=digest, reviewer_id='independent-product-reviewer',
                               findings=[], assessment={key: 'Validated upgraded RP and retained work' for key in (
                                   'impact', 'reuse', 'revalidation', 'handoff')}), 'product-review')
                self.assertEqual(rp.approve(digest, 'product-approve')['state'], 'ready-for-handoff')
                self.assertEqual(rp.handoff('product-handoff')['state'], 'completed')
                self.assertEqual(successor.load()['state'], 'executing')
                self.assertEqual(source.load()['state'], 'superseded')
                self.assertEqual(source.approved_package(), old_package)
                self.assertEqual(git(worker, 'rev-parse', 'HEAD'), old_worker)
                self.assertEqual(rp.load()['snapshot'], snapshot)
                self.assertTrue(rp.events_path.read_bytes().startswith(old_history))

    def test_product_change_cannot_be_laundered_through_tool_approval(self):
        for committed in (False, True):
            with self.subTest(committed=committed):
                repo, _, _, rp, _, _, snapshot = self.upgraded()
                (repo / 'src/a.txt').write_text('Unapproved dependency or product edit\n')
                if committed:
                    git(repo, 'add', self.TOOL_ROOT, 'src/a.txt')
                    git(repo, 'commit', '-qm', 'Mixed tool and product edit')
                before = rp.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    rp.toolchain_propose(self.request(), 'mixed-propose')
                self.assertEqual(rp.events_path.read_bytes(), before)
                self.assertEqual(rp.load()['snapshot'], snapshot)

    def test_tool_proposal_needs_independent_review_and_exact_hash(self):
        _, _, _, rp, _, proposal, _ = self.upgraded()
        digest = rp.toolchain_propose(self.request(), 'tool-propose')['toolchain_proposal_hash']
        history = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.toolchain_approve(digest, 'synthetic-user', 'premature-approve')
        with self.assertRaises(CogitoError):
            rp.toolchain_review(self.review(digest, reviewer='tool-maintainer'), 'self-review')
        with self.assertRaises(CogitoError):
            rp.toolchain_review(self.review('0' * 64), 'stale-review')
        self.assertEqual(rp.events_path.read_bytes(), history)
        rp.toolchain_review(self.review(digest), 'tool-review')
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'review-is-not-approval')
        with self.assertRaises(CogitoError):
            rp.toolchain_approve('0' * 64, 'synthetic-user', 'stale-approve')
        rp.toolchain_approve(digest, 'synthetic-user', 'tool-approve')
        self.assertEqual(rp.propose(proposal, 'product-propose')['state'], 'reviewing')

    def test_tool_changes_after_approval_remain_blocked(self):
        repo, _, _, rp, _, proposal, snapshot = self.upgraded()
        self.approve_tool(rp)
        history = rp.events_path.read_bytes()
        (repo / self.TOOL_ROOT / 'SKILL.md').write_text('Unexpected post-approval rule change\n')
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'tool-drift-after-approval')
        self.assertEqual(rp.events_path.read_bytes(), history)
        self.assertEqual(rp.load()['snapshot'], snapshot)

    def test_tool_changes_between_proposal_and_approval_are_rejected(self):
        repo, _, _, rp, _, _, _ = self.upgraded()
        digest = rp.toolchain_propose(self.request(), 'tool-propose')['toolchain_proposal_hash']
        rp.toolchain_review(self.review(digest), 'tool-review')
        history = rp.events_path.read_bytes()
        (repo / self.TOOL_ROOT / 'VERSION').write_text('unreviewed-next-version\n')
        with self.assertRaises(CogitoError):
            rp.toolchain_approve(digest, 'synthetic-user', 'changed-tool-approve')
        self.assertEqual(rp.events_path.read_bytes(), history)

    def test_tool_actions_replay_without_appending_or_changing_request(self):
        _, _, _, rp, _, _, snapshot = self.upgraded()
        digest = self.approve_tool(rp)
        history = rp.events_path.read_bytes()
        rp.toolchain_propose(self.request(), 'tool-propose')
        rp.toolchain_review(self.review(digest), 'tool-review')
        rp.toolchain_approve(digest, 'synthetic-user', 'tool-approve')
        self.assertEqual(rp.events_path.read_bytes(), history)
        self.assertEqual(rp.load()['snapshot'], snapshot)
        changed = {**self.request(), 'reason': 'Different approval request'}
        with self.assertRaises(CogitoError):
            rp.toolchain_propose(changed, 'tool-propose')

    def test_arbitrary_product_directory_is_not_a_tool_installation(self):
        _, _, _, rp, _, _, _ = self.upgraded()
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.toolchain_propose({**self.request(), 'tool_root': 'src'}, 'invalid-tool-root')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_product_edit_after_tool_approval_is_still_rejected(self):
        repo, _, _, rp, _, proposal, _ = self.upgraded()
        self.approve_tool(rp)
        history = rp.events_path.read_bytes()
        (repo / 'src/b.txt').write_text('Unauthorized product change after tool adoption\n')
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'changed-product-propose')
        self.assertEqual(rp.events_path.read_bytes(), history)

    def test_terminal_rp_cannot_open_another_tool_upgrade(self):
        _, _, _, rp, _, _, _ = self.upgraded()
        self.approve_tool(rp)
        rp.abandon('keep-paused', 'Synthetic user keeps original work paused', 'keep-paused')
        history = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.toolchain_propose(self.request(), 'tool-propose-after-abandon')
        self.assertEqual(rp.events_path.read_bytes(), history)

    @staticmethod
    def product_review(rp, digest):
        return rp.review(dict(proposal_hash=digest, reviewer_id='product-reviewer', findings=[],
                              assessment={key: 'Checked current tools and preserved sources' for key in (
                                  'impact', 'reuse', 'revalidation', 'handoff')}), 'fresh-product-review')

    def revise_baseline(self, successor, proposal, head):
        old = proposal['package']
        successor.planning_begin(dict(
            round=1, candidate_hash=package_hash(old), level='plan', author_id='planner',
            reason='Bind the independently adopted tool-only delivery commit',
            impact={key: dict(disposition='reuse', reason='Product authorization is unchanged')
                    for key in ('requirements', 'boundary', 'spec', 'plan', 'dag', 'acceptance')}),
            'baseline-planning-begin')
        revised = copy.deepcopy(old)
        revised.update(planning_round=2, baseline_commit=head)
        successor.prepare_package(revised, 'baseline-candidate')
        successor.planning_review(dict(
            round=2, proposal_hash=successor.load()['planning']['proposal_hash'],
            reviewer_id='planning-reviewer', findings=[],
            assessment={key: 'Verified unchanged product scope and explicit new baseline'
                        for key in ('consistency', 'impact', 'reuse')}), 'baseline-planning-review')
        return {**proposal, 'package': revised}

    def test_existing_candidate_survives_committed_adoption_then_replans_baseline(self):
        # Match FS-043: the candidate already exists before the tool commit.
        repo, worker, source, rp, successor, proposal, snapshot = self.upgraded(legacy=True)
        candidate_hash = successor.load()['candidate_package_hash']
        candidate_history = successor.events_path.read_bytes()
        git(repo, 'add', self.TOOL_ROOT)
        git(repo, 'commit', '-qm', 'Commit tool repair after successor preparation')
        self.approve_tool(rp)
        self.assertEqual(successor.load()['candidate_package_hash'], candidate_hash)
        self.assertEqual(successor.events_path.read_bytes(), candidate_history)
        with self.assertRaisesRegex(CogitoError, 'baseline'):
            rp.propose(proposal, 'old-baseline-propose')
        proposal = self.revise_baseline(successor, proposal, git(repo, 'rev-parse', 'HEAD'))
        digest = rp.propose(proposal, 'new-baseline-propose')['proposal_hash']
        self.product_review(rp, digest)
        rp.approve(digest, 'new-baseline-approve')
        self.assertEqual(rp.handoff('new-baseline-handoff')['state'], 'completed')
        self.assertEqual(rp.load()['snapshot'], snapshot)
        self.assertTrue(successor.events_path.read_bytes().startswith(candidate_history))
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), snapshot['worktrees'][str(worker.resolve())]['head'])

    def test_uncommitted_adoption_requires_second_adoption_before_package_approval(self):
        repo, _, _, rp, successor, proposal, snapshot = self.upgraded()
        first_tool_hash = self.approve_tool(rp)
        digest = rp.propose(proposal, 'first-product-propose')['proposal_hash']
        self.product_review(rp, digest)
        history = rp.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'commit the exact tool update'):
            rp.approve(digest, 'uncommitted-product-approve')
        self.assertEqual(rp.events_path.read_bytes(), history)
        self.assertIsNone(successor.load()['package_hash'])
        git(repo, 'add', self.TOOL_ROOT)
        git(repo, 'commit', '-qm', 'Commit exactly the adopted tool content')
        second = rp.toolchain_propose(self.request(), 'second-tool-propose')['toolchain_proposal_hash']
        rp.toolchain_review(self.review(second), 'second-tool-review')
        rp.toolchain_approve(second, 'synthetic-user', 'second-tool-approve')
        self.assertEqual(rp.load()['toolchain']['proposal']['previous_toolchain_hash'], first_tool_hash)
        self.assertFalse(rp.load().get('proposal_hash'))
        proposal = self.revise_baseline(successor, proposal, git(repo, 'rev-parse', 'HEAD'))
        fresh = rp.propose(proposal, 'second-product-propose')['proposal_hash']
        # Replaying the old adoption must not clear the new RP proposal.
        rp.toolchain_approve(first_tool_hash, 'synthetic-user', 'tool-approve')
        self.assertEqual(rp.load()['proposal_hash'], fresh)
        self.assertEqual(rp.load()['snapshot'], snapshot)

    def test_rejected_tool_proposal_can_restore_original_binding_and_keep_paused(self):
        repo, _, _, rp, _, _, snapshot = self.upgraded()
        digest = rp.toolchain_propose(self.request(), 'rejected-tool-propose')['toolchain_proposal_hash']
        rp.toolchain_reject(digest, 'Compatibility findings require another approach', 'reject-tool')
        self.assertEqual(rp.load()['toolchain_status'], 'rejected')
        self.assertFalse(rp.load().get('toolchain'))
        (repo / self.TOOL_ROOT / 'VERSION').write_text('3.0.0-before-toolchain\n')
        self.assertEqual(rp.abandon('keep-paused', 'Retain original work', 'pause-after-reject')['state'], 'abandoned')
        self.assertEqual(rp.load()['snapshot'], snapshot)

    def test_intermediate_product_commit_cannot_be_hidden_by_reverting_it(self):
        repo, _, _, rp, _, _, _ = self.upgraded()
        path = repo / 'src/a.txt'
        old = path.read_bytes()
        path.write_text('temporary unauthorized product content\n')
        git(repo, 'add', 'src/a.txt')
        git(repo, 'commit', '-qm', 'Product edit hidden in tool history')
        path.write_bytes(old)
        git(repo, 'add', 'src/a.txt', self.TOOL_ROOT)
        git(repo, 'commit', '-qm', 'Restore product while committing tools')
        with self.assertRaisesRegex(CogitoError, 'toolchain commit contains'):
            rp.toolchain_propose(self.request(), 'history-laundering')

    def test_new_index_binding_requires_a_new_review(self):
        repo, _, _, rp, _, _, _ = self.upgraded()
        digest = rp.toolchain_propose(self.request(), 'unstaged-propose')['toolchain_proposal_hash']
        rp.toolchain_review(self.review(digest), 'unstaged-review')
        git(repo, 'add', self.TOOL_ROOT)
        before = rp.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'proposal changed'):
            rp.toolchain_approve(digest, 'synthetic-user', 'different-index-approve')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_frozen_contract_inside_tool_root_is_never_a_tool_exception(self):
        prepare = RunStore.prepare_package

        def source_contract_in_tools(store, draft, *args, **kwargs):
            if store.run_id == 'DEV-feature-multitask':
                document = draft['slices'][0]['spec']
                path = store.root / self.TOOL_ROOT / 'frozen-product-spec.md'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((store.root / document['path']).read_bytes())
                document['path'] = path.relative_to(store.root).as_posix()
            return prepare(store, draft, *args, **kwargs)

        with mock.patch.object(RunStore, 'prepare_package', new=source_contract_in_tools):
            _, _, _, rp, _, _, _ = self.upgraded()
        with self.assertRaisesRegex(CogitoError, 'overlaps protected'):
            rp.toolchain_propose(self.request(), 'contract-laundering')

    def test_fresh_cli_ignores_timestamp_valid_old_bytecode(self):
        repo, _, _, rp, _, _, _ = self.upgraded()
        module = repo / self.TOOL_ROOT / 'scripts/cogito_replan_toolchain.py'
        code = compile("raise RuntimeError('stale tool bytecode was executed')", str(module), 'exec')
        cached = Path(importlib.util.cache_from_source(str(module)))
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(importlib._bootstrap_external._code_to_timestamp_pyc(
            code, int(module.stat().st_mtime), module.stat().st_size))
        exclude = repo / '.git/info/exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        exclude.write_text('**/__pycache__/\n')
        self.assertTrue(rp.toolchain_propose(self.request(), 'source-only-propose')['toolchain_proposal_hash'])

    def test_approval_append_survives_cache_write_failure_and_retry(self):
        repo, _, _, rp, _, _, snapshot = self.upgraded()
        digest = rp.toolchain_propose(self.request(), 'crash-propose')['toolchain_proposal_hash']
        rp.toolchain_review(self.review(digest), 'crash-review')
        gate = repo / self.TOOL_ROOT / 'scripts/cogito_gate.py'
        # Fault injection changes only os.replace in this disposable subprocess.
        # The real source-bound CLI and Store perform validation and event append.
        script = '''import json, os, runpy, sys
from pathlib import Path
gate, root, rp, digest = sys.argv[1:]
events = Path(root) / '.cogito/replans' / rp / 'events.jsonl'
cache = events.with_name('state.json')
replace = os.replace
def fail_cache(source, target):
    if Path(target).resolve() == cache.resolve() and json.loads(events.read_text().splitlines()[-1])['type'] == 'toolchain-approved':
        raise OSError('simulated cache publication failure')
    return replace(source, target)
os.replace = fail_cache
sys.argv = [gate, '--repo', root, 'replan', 'toolchain-approve', '--replan-id', rp,
            '--proposal-hash', digest, '--approver-id', 'synthetic-user', '--action-id', 'crash-approve']
runpy.run_path(gate, run_name='__main__')
'''
        failed = subprocess.run([sys.executable, '-B', '-c', script, str(gate), str(repo), rp.replan_id, digest],
                                text=True, capture_output=True, timeout=60)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn('simulated cache publication failure', failed.stderr)
        events = read_events(rp.events_path)
        self.assertEqual(events[-1]['type'], 'toolchain-approved')
        history = rp.events_path.read_bytes()
        rp.toolchain_approve(digest, 'synthetic-user', 'crash-approve')
        self.assertEqual(rp.events_path.read_bytes(), history)
        self.assertEqual(rp.load()['state'], 'analyzing')
        self.assertEqual(rp.load()['snapshot'], snapshot)
