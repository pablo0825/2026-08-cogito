"""Adversarial retention adapter checks using real isolated Git histories."""
import copy
from contextlib import contextmanager
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from cogito_common import CogitoError, hash_json
from cogito_projection import project_events
from cogito_review_retention import _touches
from cogito_test_support import GitTestCase, git, init_repo
import test_review_retention_flow as flow


class RetentionAdversarialTests(GitTestCase):
    lease = staticmethod(flow.ReviewRetentionFlowTests.lease)
    check = staticmethod(flow.ReviewRetentionFlowTests.check)
    commit = staticmethod(flow.ReviewRetentionFlowTests.commit)
    implement = flow.ReviewRetentionFlowTests.implement
    result = staticmethod(flow.ReviewRetentionFlowTests.result)
    review = staticmethod(flow.ReviewRetentionFlowTests.review)
    impact = staticmethod(flow.ReviewRetentionFlowTests.impact)
    corrected_wave = flow.ReviewRetentionFlowTests.corrected_wave
    proposal = flow.ReviewRetentionFlowTests.proposal

    def test_missing_historical_runtime_declines_retention_but_normal_review_works(self):
        _, _, store, _, _ = self.corrected_wave()
        history = copy.deepcopy(store._events.read())
        first = next(e for e in history if e['type'] == 'verification-passed')
        first['payload'].pop('review_runtime')
        before = store.events_path.read_bytes()
        with patch.object(store._events, 'read', return_value=history):
            with self.assertRaisesRegex(CogitoError, 'executor binding'):
                self.proposal(store)
        self.assertEqual(store.events_path.read_bytes(), before)
        original = next(r for r in store.load()['agent_results']
                        if r['task_id'] == 'T-a' and r['role'] == 'implementer')
        self.review(store, original)
        store.transition('review-approved', {})
        self.assertEqual(store.load()['state'], 'integrating')

    def test_original_wave_is_whole_verified_wave_not_candidate_task_commit(self):
        _, _, store, _, _ = self.corrected_wave()
        proposal = self.proposal(store)
        source, = proposal['binding']['sources']
        history = store._events.read()
        impl_a = next(e['payload']['result'] for e in history if e['type'] == 'agent-result-recorded'
                      and e['payload']['result']['role'] == 'implementer'
                      and e['payload']['result']['task_id'] == 'T-a')
        impl_b = next(e['payload']['result'] for e in history if e['type'] == 'agent-result-recorded'
                      and e['payload']['result']['role'] == 'implementer'
                      and e['payload']['result']['task_id'] == 'T-b')
        self.assertEqual(source['base_head'], impl_b['head_commit'])
        self.assertNotEqual(source['base_head'], impl_a['head_commit'])

    def test_new_finding_cannot_hide_behind_old_approval(self):
        _, _, store, _, _ = self.corrected_wave()
        original = next(r for r in store.load()['agent_results']
                        if r['task_id'] == 'T-a' and r['role'] == 'implementer')
        self.review(store, original, finding=True)
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'unreplaced prior'):
            self.proposal(store)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_newer_real_failed_check_cannot_fall_back_to_old_success(self):
        from cogito_run_store import RunStore
        complete = RunStore.complete_verification
        def verify_with_failure(store, evidence, *args, **kwargs):
            if len(evidence) > 1:
                worker = Path(store.load()['tasks']['T-a']['worktree'])
                path = worker / 'src/a.txt'
                original = path.read_text()
                path.write_text('force new check failure\n')
                failed = self.check(store, worker, 'C-a', 'new-failed-a')
                self.assertFalse(failed['passed'])
                path.write_text(original)
            return complete(store, evidence, *args, **kwargs)
        with patch.object(RunStore, 'complete_verification', verify_with_failure):
            _, _, store, _, _ = self.corrected_wave()
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, 'newer failed check'):
            self.proposal(store)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_unknown_attempt_and_tampered_success_block_retention(self):
        _, _, store, _, _ = self.corrected_wave()
        attempt = store.run_dir / 'check-actions' / 'unknown-new-check'
        attempt.mkdir()
        (attempt / 'started.json').write_text('{}')
        (attempt / 'request.json').write_text(json.dumps({'action_id': 'unknown-new-check'}))
        with self.assertRaisesRegex(CogitoError, 'unfinished controlled check'):
            self.proposal(store)
        (attempt / 'started.json').unlink()
        evidence_event = next(e for e in store._events.read() if e['type'] == 'check-evidence-recorded'
                              and e['payload']['check_id'] == 'C-a')
        path = Path(evidence_event['payload']['evidence_path'])
        original = path.read_text()
        evidence = json.loads(original)
        evidence['passed'] = False
        path.chmod(0o600)
        path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(CogitoError, 'evidence changed|recorded hash'):
            self.proposal(store)
        path.write_text(original)
        self.proposal(store)

    def test_executor_guard_remains_held_through_durable_append(self):
        _, _, store, _, _ = self.corrected_wave()
        proposal = self.proposal(store)
        held = []
        appended = []
        append = store._events.append
        @contextmanager
        def guard(*args, **kwargs):
            held.append(True)
            try:
                yield True
            finally:
                held.pop()
        def guarded_append(event, **kwargs):
            if event['type'] == 'review-approved':
                self.assertTrue(held, 'executor guard released before append')
                appended.append(event['type'])
            return append(event, **kwargs)
        with patch('cogito_execution_registry.quiescent_guard', guard), patch.object(
                store._events, 'append', side_effect=guarded_append):
            store.transition('review-approved', {'retention': proposal}, 'guarded-approval')
        self.assertEqual(appended, ['review-approved'])
        self.assertFalse(held)

    def test_projection_rejects_malformed_and_false_references_even_with_rehashed_proposal(self):
        _, _, store, _, _ = self.corrected_wave()
        store.transition('review-approved', {'retention': self.proposal(store)})
        history = store._events.read()
        self.assertEqual(project_events(history, store.workflow)['state'], 'integrating')
        for mode in ('hash', 'source-hash', 'implementation-hash', 'verification-hash', 'sources-type', 'reference-type', 'sequence-type',
                     'source-extra', 'checks-empty', 'touched-unsafe'):
            with self.subTest(mode=mode):
                changed = copy.deepcopy(history)
                record = changed[-1]['payload']['retention']
                if mode == 'hash':
                    record['binding_hash'] = '0' * 64
                elif mode == 'sources-type':
                    record['binding']['sources'] = None
                elif mode == 'reference-type':
                    record['binding']['sources'][0]['implementation'] = []
                elif mode == 'sequence-type':
                    record['binding']['sources'][0]['review']['event_sequence'] = True
                elif mode == 'source-extra':
                    record['binding']['sources'][0]['extra'] = 'not allowed'
                elif mode == 'checks-empty':
                    record['binding']['checks'] = []
                elif mode == 'touched-unsafe':
                    record['binding']['sources'][0]['touched_paths'] = ['../escape']
                else:
                    key = {'source-hash': 'review', 'implementation-hash': 'implementation',
                           'verification-hash': 'verification'}[mode]
                    record['binding']['sources'][0][key]['event_hash'] = '0' * 64
                if mode != 'hash':
                    record['binding_hash'] = hash_json({'impact': record['impact'], 'binding': record['binding']})
                with self.assertRaises(CogitoError):
                    project_events(changed, store.workflow)


class RetentionGitIntervalTests(GitTestCase):
    def test_touched_history_includes_revert_rename_delete_and_earlier_rounds(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_repo(repo)
            (repo / 'a.txt').write_text('original')
            (repo / 'b.txt').write_text('original')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'base')
            base = git(repo, 'rev-parse', 'HEAD')
            tree = git(repo, 'rev-parse', 'HEAD^{tree}')
            (repo / 'a.txt').write_text('changed')
            git(repo, 'commit', '-qam', 'earlier round touches a')
            (repo / 'a.txt').write_text('original')
            git(repo, 'commit', '-qam', 'restore a')
            git(repo, 'mv', 'b.txt', 'renamed.txt')
            git(repo, 'commit', '-qm', 'rename b')
            (repo / 'renamed.txt').unlink()
            git(repo, 'commit', '-qam', 'delete renamed b')
            class Adapter:
                _git_at = staticmethod(git)
            head = git(repo, 'rev-parse', 'HEAD')
            current = git(repo, 'rev-parse', 'HEAD^{tree}')
            self.assertNotIn('a.txt', git(repo, 'diff', '--name-only', base, head).splitlines())
            self.assertEqual(_touches(Adapter(), repo, base, head, tree, current),
                             {'a.txt', 'b.txt', 'renamed.txt'})
