"""Real hash-chain and committed-artifact compatibility at the cleanup boundary."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError, hash_json
from cogito_cleanup import _other_use, cleanup_accepted, read_run_references
from cogito_delivery_summary import build_delivery_summary
from cogito_events import append_event
from cogito_run_store import RunStore
import test_cleanup_finalization as finalization


class CleanupHistoryTests(GitTestCase):
    def accepted(self):
        fixture = finalization.CleanupFinalizationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        repo, worker, store, args = fixture.finalizing(commit_package=True)
        with patch('cogito_cleanup.cleanup_accepted', return_value={'removed': [], 'retained': []}):
            store.finalize(*args)
        return store.root, worker, store, args

    @staticmethod
    def rewrite_fixture_history(store, events):
        # Only disposable test history is rebuilt to represent a historical writer.
        store.events_path.unlink()
        for event in events:
            append_event(store.events_path, {k: v for k, v in event.items()
                         if k not in {'event_hash', 'sequence', 'previous_event_hash'}})

    def legacy(self):
        repo, worker, store, args = self.accepted()
        state, events = store.load(), store._events.read()
        replacement = [e for e in events if e['type'] == 'check-evidence-recorded'][-1]
        payload = replacement['payload']
        check = next(c for c in store.effective_package()['checks'] if c['id'] == payload['check_id'])
        resolution = {'type': 'controlled-check-attempt-resolved', 'payload': {
            'interrupted_action_id': 'historical-interrupted',
            'replacement_action_id': replacement['action_id'], 'resolver_id': 'user:reviewer',
            'reason': 'historical verified interruption', 'request_hash': replacement['request_hash'],
            **{k: payload[k] for k in ('check_id', 'evidence_path', 'evidence_hash', 'effective_contract_hash')},
            'check_hash': hash_json(check),
        }, 'action_id': 'historical-resolution'}
        historical = [*events[:-1], resolution, events[-1]]
        self.rewrite_fixture_history(store, historical)
        historical = store._events.read()
        result_path = repo / args[0]
        result = json.loads(result_path.read_text())
        result['delivery_summary'] = build_delivery_summary(state, [e for e in historical
            if e['type'] != 'controlled-check-attempt-resolved'])
        result['delivery_summary']['verification'].append({
            'event_sequence': historical[-2]['sequence'], 'event': resolution['type'], **resolution['payload']})
        result_path.write_text(json.dumps(result))
        git(repo, 'add', args[0])
        git(repo, 'commit', '-qm', 'historical resolution receipt')
        historical[-1]['payload'].update(final_commit=git(repo, 'rev-parse', 'HEAD'),
                                          final_tree=git(repo, 'rev-parse', 'HEAD^{tree}'))
        self.rewrite_fixture_history(store, historical)
        return repo, worker, store, args

    def test_known_legacy_unrelated_history_does_not_block_cleanup_reference_assessment(self):
        repo, worker, store, args = self.legacy()
        before = {p: p.read_bytes() for p in (store.events_path, store.state_path, repo / args[0])}
        references = read_run_references(repo, store.run_id)
        self.assertTrue(any(r.get('worktree') == str(worker) for r in references))
        observer = SimpleNamespace(root=repo, run_id='DEV-observer')
        _other_use(observer, repo / '.cogito/worktrees/unrelated', 'unrelated-branch')
        unrelated = repo / '.cogito/worktrees/unrelated'
        git(repo, 'worktree', 'add', '-qb', 'unrelated-branch', str(unrelated))
        run_dir = repo / '.cogito/runs/DEV-observer'
        run_dir.mkdir()
        # Existing cleanup unit-test boundary: accepted current ownership is a
        # fixture, but other history, Git registration and removal are real.
        head = git(repo, 'rev-parse', 'HEAD')
        current = {'state': 'accepted', 'tasks': {'T-observer': {'status': 'integrated',
                   'worktree': str(unrelated), 'branch': 'unrelated-branch'}}}
        final = {'type': 'finalization-complete', 'event_hash': 'a' * 64,
                 'payload': {'final_commit': head}}
        observer.run_dir = run_dir
        observer.load = lambda: current
        observer._events = SimpleNamespace(read=lambda: [final])
        observer.completion_report = lambda: {'status': 'accepted'}
        observer.approved_package = lambda: {'run_id': 'DEV-observer', 'slices': [{'worker': {
            'worktree': '.cogito/worktrees/unrelated', 'branch': 'unrelated-branch'}}]}
        outcome = cleanup_accepted(observer)
        self.assertEqual(outcome['removed'], [str(unrelated)], outcome)
        self.assertFalse(unrelated.exists())
        with self.assertRaisesRegex(CogitoError, 'references'):
            _other_use(observer, worker, 'unrelated-branch')
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_legacy_check_hash_and_unknown_event_fail_closed(self):
        repo, _, store, args = self.legacy()
        events = store._events.read()
        events[-2]['payload']['check_hash'] = '0' * 64
        self.rewrite_fixture_history(store, events)
        with self.assertRaises(CogitoError):
            read_run_references(repo, store.run_id)

    def test_legacy_missing_result_receipt_fails_closed(self):
        repo, _, store, args = self.legacy()
        result_path = repo / args[0]
        result = json.loads(result_path.read_text())
        result['delivery_summary']['verification'] = [r for r in result['delivery_summary']['verification']
            if r['event'] != 'controlled-check-attempt-resolved']
        result_path.write_text(json.dumps(result))
        git(repo, 'add', args[0])
        git(repo, 'commit', '-qm', 'fixture missing historical receipt')
        events = store._events.read()
        events[-1]['payload'].update(final_commit=git(repo, 'rev-parse', 'HEAD'),
                                    final_tree=git(repo, 'rev-parse', 'HEAD^{tree}'))
        self.rewrite_fixture_history(store, events)
        with self.assertRaisesRegex(CogitoError, 'receipt'):
            read_run_references(repo, store.run_id)
        # Even a valid chain never legitimizes an unknown historical event.
        events[-2]['type'] = 'unknown-historical-event'
        self.rewrite_fixture_history(store, events)
        with self.assertRaises(CogitoError):
            read_run_references(repo, store.run_id)

    def test_active_symlink_and_wrong_run_identity_fail_closed(self):
        repo, _, store, _ = self.accepted()
        alias = repo / '.cogito/runs/DEV-alias'
        alias.mkdir()
        (alias / 'events.jsonl').symlink_to(store.events_path)
        with self.assertRaisesRegex(CogitoError, 'symlink'):
            read_run_references(repo, 'DEV-alias')
        (alias / 'events.jsonl').unlink()
        append_event(alias / 'events.jsonl', store._events.read()[0])
        with self.assertRaisesRegex(CogitoError, 'another Run'):
            read_run_references(repo, 'DEV-alias')
