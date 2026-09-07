"""Real isolated Git delivery with selective review retention."""
import copy
import json
import sys
from unittest.mock import patch

from cogito_common import CogitoError
from cogito_contracts import package_hash
from cogito_test_support import GitTestCase, git
import test_atomic_task_execution as execution


class ReviewRetentionFlowTests(GitTestCase):
    lease = staticmethod(execution.AtomicTaskTests.lease)
    check = staticmethod(execution.AtomicTaskTests.check)
    commit = staticmethod(execution.AtomicTaskTests.commit)
    implement = execution.AtomicTaskTests.implement
    result = staticmethod(execution.AtomicTaskTests.result)

    def corrected_wave(self):
        def configure(draft):
            draft['checks'][1]['argv'][-1] = (
                "from pathlib import Path; assert Path('src/b.txt').read_text().startswith('after\\n')")
        repo, worker, store, draft = execution.AtomicTaskTests.executing(self, configure)
        first, _ = self.implement(store, worker, 'a')
        second, evidence = self.implement(store, worker, 'b')
        store.transition('implementation-complete', {})
        store.complete_verification([evidence])
        self.review(store, first)
        self.review(store, second, finding=True)
        event = store._events.read()[-1]
        amendment = {'id': 'TA-review', 'reason': 'Correct b text',
            'added_tasks': [{'id': 'T-fix', 'slice_id': 'FS-1', 'paths': ['src/b.txt'],
                'responsibility': 'Correct b text', 'check_ids': ['C-fix', 'C-b']}],
            'added_checks': [{'id': 'C-fix', 'phase': 'task', 'argv': [sys.executable, '-I', '-c',
                "from pathlib import Path; assert Path('src/b.txt').read_text() == 'after\\nfixed\\n'"]}]}
        store.start_review_fix_with_amendment({'finding': {'event_sequence': event['sequence'],
            'event_hash': event['event_hash']}, 'amendment': amendment}, 'start-fix')
        self.lease(store, 'T-fix')
        (worker / 'src/b.txt').write_text('after\nfixed\n')
        head = self.commit(worker, 'fix b\n\nCogito-Amendment: TA-review')
        checks = [self.check(store, worker, cid, 'fixed-' + cid) for cid in ('C-fix', 'C-b')]
        fixed = self.result(store, worker, checks, 'T-fix')
        store.submit_agent_result(fixed)
        store.update_task('T-fix', 'complete', 'worker')
        store.complete_review_fix('TA-review', head)
        store.complete_verification(checks)
        self.review(store, second)
        self.review(store, fixed)
        return repo, worker, store, draft, head

    @staticmethod
    def review(store, result, finding=False):
        store.submit_agent_result({**result, 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'changed_paths': [], 'evidence': [],
            'status': 'needs-fix' if finding else 'complete',
            'risks': ['b text needs correction'] if finding else [],
            'requested_transition': 'review-fix' if finding else 'review-approved'})

    @staticmethod
    def impact():
        return {'author_id': 'coordinator', 'retained': [{'task_id': 'T-a',
            'reason': 'Independent a behavior unchanged by b text correction',
            'dependency_paths': ['src/a.txt']}], 'affected_task_ids': ['T-b', 'T-fix'],
            'check_ids': ['C-fix', 'C-b'],
            'assessment': 'Only b text changed; a has no dependency on b. Fresh b checks cover correction.'}

    def proposal(self, store):
        return {**store.prepare_review_retention(self.impact()), 'reviewer_id': 'retention-reviewer',
            'assessment': 'Verified cumulative diff and dependencies; selected checks are sufficient.'}

    def test_retained_review_reaches_accepted_without_rechecking_unaffected_task(self):
        repo, _, store, draft, head = self.corrected_wave()
        proposal = self.proposal(store)
        before = store.events_path.read_bytes()
        store.transition('review-approved', {'retention': proposal}, 'retain-approve')
        retained = store.events_path.read_bytes()
        self.assertTrue(retained.startswith(before))
        store.transition('review-approved', {'retention': proposal}, 'retain-approve')
        self.assertEqual(store.events_path.read_bytes(), retained)
        git(repo, 'merge', '--no-ff', '-qm', 'integrate', draft['slices'][0]['worker']['branch'])
        integration = git(repo, 'rev-parse', 'HEAD')
        store.complete_integration(integration, 'FS-1')
        post = self.check(store, repo, 'C-b', 'post')
        store.decide_post_verification([post])
        graph_path = repo / 'docs/cogito/project-graph.json'
        graph = json.loads(graph_path.read_text())
        graph['active_run_id'] = None
        graph['slices']['FS-1'].update(disposition='accepted', completed_by=store.run_id)
        graph_path.write_text(json.dumps(graph))
        relative = f'docs/cogito/results/{store.run_id}.json'
        final = repo / relative
        final.parent.mkdir(parents=True, exist_ok=True)
        final.write_text(json.dumps({'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': package_hash(store.approved_package()),
            'effective_contract_hash': store.load()['effective_contract_hash'],
            'integration_commits': [integration], 'slice_dispositions': {'FS-1': 'accepted'},
            'checks': [{'id': 'C-b', 'status': 'passed', 'evidence': post['evidence_path']}],
            'reviews': [{'reviewer': 'reviewer'}], 'amendments': [{'id': 'TA-review', 'commit_id': head}],
            'human_gate': {'required': False, 'outcome': 'not-required'}, 'remaining_risks': []}))
        git(repo, 'add', relative, 'docs/cogito/project-graph.json')
        git(repo, 'commit', '-qm', 'record delivery')
        store.finalize(relative, 'docs/cogito/project-graph.json', git(repo, 'rev-parse', 'HEAD'))
        self.assertEqual(store.completion_report()['status'], 'accepted')
        events = store._events.read()
        self.assertEqual(sum(e['type'] == 'check-evidence-recorded' and
            e['payload']['check_id'] == 'C-a' for e in events), 1)
        self.assertEqual(sum(e['type'] == 'agent-result-recorded' and
            e['payload']['result']['role'] == 'reviewer' and
            e['payload']['result']['task_id'] == 'T-a' for e in events), 1)

    def test_rejections_leave_events_unchanged_and_normal_review_remains_available(self):
        _, worker, store, _, _ = self.corrected_wave()
        proposal = self.proposal(store)
        before = store.events_path.read_bytes()
        for mode in ('author', 'implementer', 'hash', 'impact', 'checkout'):
            with self.subTest(mode=mode):
                bad = copy.deepcopy(proposal)
                if mode in ('author', 'implementer'):
                    bad['reviewer_id'] = 'coordinator' if mode == 'author' else 'worker'
                elif mode == 'hash':
                    bad['binding_hash'] = '0' * 64
                elif mode == 'impact':
                    bad['impact']['assessment'] += ' changed'
                else:
                    (worker / 'src/a.txt').write_text('unreviewed\n')
                with self.assertRaises(CogitoError):
                    store.transition('review-approved', {'retention': bad}, 'bad-' + mode)
                self.assertEqual(store.events_path.read_bytes(), before)
                if mode == 'checkout':
                    (worker / 'src/a.txt').write_text('after\n')
        first = next(r for r in store.load()['agent_results'] if
                     r['task_id'] == 'T-a' and r['role'] == 'implementer')
        self.review(store, first)
        store.transition('review-approved', {})
        self.assertEqual(store.load()['state'], 'integrating')

    def test_lost_approval_response_replays_once_and_rejects_changed_input(self):
        _, _, store, _, _ = self.corrected_wave()
        proposal = self.proposal(store)
        append = store._events.append
        def lost_response(event, **kwargs):
            result = append(event, **kwargs)
            if event['type'] == 'review-approved':
                raise OSError('lost response after durable approval')
            return result
        with patch.object(store._events, 'append', side_effect=lost_response):
            with self.assertRaisesRegex(OSError, 'lost response'):
                store.transition('review-approved', {'retention': proposal}, 'lost-approval')
        committed = store.events_path.read_bytes()
        store.transition('review-approved', {'retention': proposal}, 'lost-approval')
        self.assertEqual(store.events_path.read_bytes(), committed)
        changed = copy.deepcopy(proposal)
        changed['assessment'] += ' changed'
        with self.assertRaises(CogitoError):
            store.transition('review-approved', {'retention': changed}, 'lost-approval')
        self.assertEqual(store.events_path.read_bytes(), committed)
        self.assertEqual(sum(e['type'] == 'review-approved' for e in store._events.read()), 1)
