"""RP runtime changes must not invalidate delivery or rewrite frozen history."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError, canonical_json, hash_json, load_json
from cogito_events import read_events
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import test_feature_multitask as feature_support


class ReplanRuntimeSnapshotTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)

    def stopped(self):
        repo, worktree, source, _ = self.fixture()
        # Reproduce an existing checkout whose Worker alone ignores runtime.
        (repo / '.gitignore').write_text('docs/cogito/packages/\n')
        git(repo, 'add', '.gitignore')
        git(repo, 'commit', '-qm', 'Delivery checkout without runtime ignore')
        self.assertEqual(git(worktree, 'status', '--porcelain'), '')
        rp = ReplanStore(repo, 'RP-runtime')
        rp.begin(source.run_id, 'DEV-runtime-next', 'Dependency contract changed', 'begin')
        index_path = Path(git(repo, 'rev-parse', '--git-path', 'index'))
        if not index_path.is_absolute():
            index_path = repo / index_path
        before_index = index_path.read_bytes()
        state = rp.stop('stop')
        self.assertEqual(state['state'], 'analyzing')
        self.assertEqual(index_path.read_bytes(), before_index)
        return repo, worktree, source, rp, index_path, before_index

    def prepare_successor(self, repo, source):
        draft = copy.deepcopy(source.approved_package())
        draft.pop('package_hash', None)
        draft.update(run_id='DEV-runtime-next', kind='change',
                     baseline_commit=git(repo, 'rev-parse', 'HEAD'))
        for sl in draft['slices']:
            old_id = sl['id']
            sl.update(id=old_id + '-V2', type='change', lineage=[old_id])
            sl['worker']['branch'] += '-v2'
            sl['worker']['worktree'] += '-v2'
            for key in ('spec', 'plan'):
                path = repo / f'docs/new-{key}.md'
                path.write_text(f'Successor {key}: revise dependency contract\n')
                sl[key] = dict(path=str(path.relative_to(repo)),
                               hash=hashlib.sha256(path.read_bytes()).hexdigest())
        for task in draft['execution_dag']['tasks']:
            task['slice_id'] += '-V2'
        new = RunStore(repo, draft['run_id'])
        new.create('change')
        new.transition('shared-understanding-ready', {
            'shared_understanding_hash': draft['shared_understanding']['hash']})
        new.transition('shared-understanding-confirmed', {'confirmed': True})
        new.transition('boundary-complete', draft['boundary'])
        new.prepare_package(draft)
        notes = new.run_dir / 'drafts/rp-analysis.md'
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text('Dependency impact assessed; original work preserved.\n')
        proposal = dict(
            author_id='planner', package=draft,
            differences={key: 'Explicit ' + key + ' assessment' for key in (
                'requirements', 'api', 'boundary', 'acceptance', 'cost', 'revalidation')},
            work=[dict(source_task_id=task, target_task_id=task,
                       disposition='adapt', validation='rerun',
                       reason='Dependency contract changed') for task in source.load()['tasks']])
        return new, proposal

    def test_stop_alone_does_not_invalidate_its_own_checkpoint(self):
        _, _, source, rp, index_path, index_bytes = self.stopped()
        events = rp.events_path.read_bytes()
        source_events = source.events_path.read_bytes()
        snapshot = copy.deepcopy(rp.load()['snapshot'])
        rp._assert_source()
        self.assertEqual(rp.stop('stop')['snapshot'], snapshot)
        self.assertEqual(rp.events_path.read_bytes(), events)
        self.assertEqual(source.events_path.read_bytes(), source_events)
        self.assertEqual(index_path.read_bytes(), index_bytes)

    def test_snapshot_without_current_runtime_version_is_rejected(self):
        for corruption in ('missing', 'unknown-field', 'missing-journal'):
            with self.subTest(corruption=corruption):
                _, _, _, rp, _, _ = self.stopped()
                saved = copy.deepcopy(rp.load()['snapshot'])
                if corruption == 'missing':
                    saved.pop('runtime')
                elif corruption == 'unknown-field':
                    saved['runtime']['unknown'] = True
                else:
                    saved['runtime']['logs'] = {}
                with self.assertRaisesRegex(CogitoError, 'unsupported RP runtime snapshot version'):
                    rp._runtime().assert_snapshot(saved)

    def test_unignored_runtime_completes_handoff_and_preserves_history(self):
        repo, worker, source, rp, index_path, index_bytes = self.stopped()
        checkpoint = copy.deepcopy(rp.load()['snapshot'])
        rp_events = rp.events_path.read_bytes()
        source_events = source.events_path.read_bytes()
        source_package = source.approved_package()
        worker_head = git(worker, 'rev-parse', 'HEAD')
        new, proposal = self.prepare_successor(repo, source)
        notes = rp.directory / 'drafts/review-notes.md'
        notes.parent.mkdir(parents=True, exist_ok=True)
        notes.write_text('Ready for independent proposal review.\n')
        state = rp.propose(proposal, 'propose')
        self.assertEqual(state['state'], 'reviewing')
        digest = state['proposal_hash']
        state = rp.review(dict(
            proposal_hash=digest, reviewer_id='independent-reviewer', findings=[],
            assessment={key: 'Checked preserved sources and proposal' for key in (
                'impact', 'reuse', 'revalidation', 'handoff')}), 'review')
        self.assertEqual(state['state'], 'awaiting-approval')
        graph_bytes = (repo / 'docs/cogito/project-graph.json').read_bytes()
        self.assertEqual(rp.approve(digest, 'approve')['state'], 'ready-for-handoff')
        self.assertEqual((repo / 'docs/cogito/project-graph.json').read_bytes(), graph_bytes)
        self.assertEqual(rp.handoff('handoff')['state'], 'completed')
        self.assertEqual(new.load()['state'], 'executing')
        self.assertEqual(source.load()['state'], 'superseded')
        self.assertEqual(source.approved_package(), source_package)
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), worker_head)
        self.assertEqual(git(worker, 'status', '--porcelain'), '')
        self.assertEqual(rp.load()['snapshot'], checkpoint)
        self.assertTrue(rp.events_path.read_bytes().startswith(rp_events))
        self.assertTrue(source.events_path.read_bytes().startswith(source_events))
        self.assertEqual(index_path.read_bytes(), index_bytes)
        target = repo / proposal['package']['slices'][0]['worker']['worktree']
        self.assertEqual((target / 'src/a.txt').read_text(), 'a1\n')
        self.assertEqual((target / 'src/b.txt').read_text(), 'b1\n')

    def test_product_worker_frozen_documents_and_unknown_runtime_still_rejected(self):
        for location in ('product', 'worker', 'spec', 'plan', 'unknown-runtime'):
            with self.subTest(location=location):
                repo, worker, source, rp, _, _ = self.stopped()
                _, proposal = self.prepare_successor(repo, source)
                path = {
                    'product': repo / 'src/a.txt',
                    'worker': worker / 'src/a.txt',
                    'spec': repo / 'docs/spec.md',
                    'plan': repo / 'docs/plan.md',
                    'unknown-runtime': repo / '.cogito/unmanaged.txt',
                }[location]
                path.write_text('Unapproved modification\n')
                events = rp.events_path.read_bytes()
                with self.assertRaises(CogitoError):
                    rp.propose(proposal, 'tampered-propose')
                self.assertEqual(rp.events_path.read_bytes(), events)
                self.assertEqual(rp.load()['state'], 'analyzing')

    def test_graph_drift_still_rejected(self):
        repo, _, source, rp, _, _ = self.stopped()
        _, proposal = self.prepare_successor(repo, source)
        path = repo / 'docs/cogito/project-graph.json'
        graph = load_json(path)
        graph['active_run_id'] = None
        path.write_text(json.dumps(graph))
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'tampered-graph')
        self.assertEqual(rp.load()['state'], 'analyzing')

    def test_ignored_frozen_spec_cannot_be_hidden_in_managed_drafts(self):
        prepare = RunStore.prepare_package

        def prepare_with_runtime_spec(store, draft, *args, **kwargs):
            if store.run_id == 'DEV-feature-multitask':
                spec = draft['slices'][0]['spec']
                path = store.root / '.cogito/replans/RP-runtime/drafts/frozen-spec.md'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((store.root / spec['path']).read_bytes())
                spec['path'] = path.relative_to(store.root).as_posix()
            return prepare(store, draft, *args, **kwargs)

        with mock.patch.object(RunStore, 'prepare_package', new=prepare_with_runtime_spec):
            repo, _, source, rp, _, _ = self.stopped()
        _, proposal = self.prepare_successor(repo, source)
        exclude = repo / '.git/info/exclude'
        exclude.parent.mkdir(exist_ok=True)
        exclude.write_text('.cogito/\n')
        path = repo / source.approved_package()['slices'][0]['spec']['path']
        path.write_text('Changed frozen contract under runtime drafts\n')
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'hidden-frozen-spec')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_historical_events_cannot_be_rewritten_under_runtime_exemption(self):
        for owner in ('source', 'rp', 'successor'):
            with self.subTest(owner=owner):
                repo, _, source, rp, _, _ = self.stopped()
                new, proposal = self.prepare_successor(repo, source)
                path = {'source': source, 'rp': rp, 'successor': new}[owner].events_path
                records = path.read_text().splitlines()
                first = json.loads(records[0])
                first['payload']['unapproved_change'] = True
                records[0] = json.dumps(first)
                path.chmod(0o600)
                path.write_text('\n'.join(records) + '\n')
                with self.assertRaises(CogitoError):
                    rp.propose(proposal, 'tampered-event')

    def test_successor_rehashed_history_is_rejected_after_proposal_anchor(self):
        repo, _, source, rp, _, _ = self.stopped()
        new, proposal = self.prepare_successor(repo, source)
        state = rp.propose(proposal, 'propose')
        events = read_events(new.events_path)
        # Keep the projected state and Package identical while rewriting a
        # historical timestamp and recomputing every subsequent chain hash.
        events[0]['timestamp'] = '2000-01-01T00:00:00+00:00'
        previous = '0' * 64
        for event in events:
            event['previous_event_hash'] = previous
            event.pop('event_hash')
            event['event_hash'] = hash_json(event)
            previous = event['event_hash']
        new.events_path.write_text(''.join(canonical_json(event) + '\n' for event in events))
        self.assertEqual(new.load()['state'], 'awaiting-package-approval')
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.review(dict(
                proposal_hash=state['proposal_hash'], reviewer_id='independent', findings=[],
                assessment={key: 'Checked' for key in ('impact', 'reuse', 'revalidation', 'handoff')}),
                'review-rewritten-history')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_immutable_source_evidence_is_not_exempted_as_runtime(self):
        repo, _, source, rp, _, _ = self.stopped()
        _, proposal = self.prepare_successor(repo, source)
        path = Path(next(iter(source.load()['evidence'])))
        path.chmod(0o600)
        evidence = load_json(path)
        evidence['stdout'] = 'Rewritten after stop'
        path.write_text(json.dumps(evidence))
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'tampered-evidence')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_adding_local_runtime_ignore_after_stop_can_continue_proposal(self):
        repo, _, source, rp, _, _ = self.stopped()
        snapshot = copy.deepcopy(rp.load()['snapshot'])
        before = rp.events_path.read_bytes()
        exclude = repo / '.git/info/exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open('a') as output:
            output.write('\n.cogito/\n')
        _, proposal = self.prepare_successor(repo, source)
        self.assertEqual(rp.propose(proposal, 'propose-after-ignore')['state'], 'reviewing')
        self.assertEqual(rp.load()['snapshot'], snapshot)
        self.assertTrue(rp.events_path.read_bytes().startswith(before))

    def test_ignoring_runtime_does_not_hide_frozen_evidence_changes(self):
        repo, _, source, rp, _, _ = self.stopped()
        exclude = repo / '.git/info/exclude'
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open('a') as output:
            output.write('\n.cogito/\n')
        _, proposal = self.prepare_successor(repo, source)
        path = Path(next(iter(source.load()['evidence'])))
        original_mode = path.stat().st_mode & 0o777
        evidence = load_json(path)
        evidence['stdout'] = 'Tampered after local ignore was added'
        path.chmod(0o600)
        path.write_text(json.dumps(evidence))
        path.chmod(original_mode)
        before = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'tampered-ignored-evidence')
        self.assertEqual(rp.events_path.read_bytes(), before)

    def test_unignored_successor_worktree_handoff_recovers_each_transfer_crash_point(self):
        for crash_point in ('before-plan', 'after-plan', 'before-receipt'):
            with self.subTest(crash_point=crash_point):
                repo, _, source, rp, index_path, index_bytes = self.stopped()
                new, proposal = self.prepare_successor(repo, source)
                state = rp.propose(proposal, 'propose')
                digest = state['proposal_hash']
                rp.review(dict(
                    proposal_hash=digest, reviewer_id='independent-reviewer', findings=[],
                    assessment={key: 'Checked transfer recovery' for key in (
                        'impact', 'reuse', 'revalidation', 'handoff')}), 'review')
                rp.approve(digest, 'approve')
                checkpoint = copy.deepcopy(rp.load()['snapshot'])
                original_emit = rp._emit

                def interrupt_transfer(kind, *args):
                    if kind == 'work-transfer-planned' and crash_point == 'before-plan':
                        raise OSError('interrupted after worktree creation')
                    if kind == 'work-transferred' and crash_point == 'before-receipt':
                        raise OSError('interrupted after applying transfer')
                    result = original_emit(kind, *args)
                    if kind == 'work-transfer-planned' and crash_point == 'after-plan':
                        raise OSError('interrupted after durable transfer plan')
                    return result

                with mock.patch.object(rp, '_emit', side_effect=interrupt_transfer):
                    with self.assertRaisesRegex(CogitoError, 'interrupted'):
                        rp.handoff('handoff')
                self.assertEqual(rp.load()['state'], 'handing-off')
                history = rp.events_path.read_bytes()
                self.assertEqual(rp.handoff('handoff')['state'], 'completed')
                self.assertEqual(new.load()['state'], 'executing')
                self.assertEqual(rp.load()['snapshot'], checkpoint)
                self.assertTrue(rp.events_path.read_bytes().startswith(history))
                self.assertEqual(index_path.read_bytes(), index_bytes)
                target = repo / proposal['package']['slices'][0]['worker']['worktree']
                self.assertEqual((target / 'src/a.txt').read_text(), 'a1\n')
                self.assertEqual((target / 'src/b.txt').read_text(), 'b1\n')

    def test_staged_source_worker_pointer_cannot_hide_behind_verified_live_worker(self):
        repo, worker, source, rp, _, _ = self.stopped()
        _, proposal = self.prepare_successor(repo, source)
        worker_head = git(worker, 'rev-parse', 'HEAD')
        wrong_head = git(worker, 'rev-parse', 'HEAD^')
        self.assertNotEqual(worker_head, wrong_head)
        git(repo, 'update-index', '--add', '--cacheinfo',
            '160000,' + wrong_head + ',' + worker.relative_to(repo).as_posix())
        history = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'tampered-worker-pointer')
        self.assertEqual(git(worker, 'rev-parse', 'HEAD'), worker_head)
        self.assertEqual(git(worker, 'status', '--porcelain'), '')
        self.assertEqual(rp.events_path.read_bytes(), history)

    def test_malformed_staged_event_prefix_is_not_a_legitimate_runtime_update(self):
        repo, _, source, rp, _, _ = self.stopped()
        _, proposal = self.prepare_successor(repo, source)
        source_history = source.events_path.read_bytes()
        self.assertTrue(source_history.startswith(b'{'))
        # This byte is a prefix of valid live history, but does not
        # preserve any complete event and cannot be appended safely.
        oid = subprocess.run(
            ['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
            input=b'{', capture_output=True, check=True,
        ).stdout.decode().strip()
        relative = source.events_path.relative_to(repo.resolve()).as_posix()
        git(repo, 'update-index', '--add', '--cacheinfo', '100644,' + oid + ',' + relative)
        history = rp.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            rp.propose(proposal, 'malformed-staged-history')
        self.assertEqual(source.events_path.read_bytes(), source_history)
        self.assertEqual(rp.events_path.read_bytes(), history)
