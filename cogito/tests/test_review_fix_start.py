"""Review correction start, interruption, historical order and final delivery."""
import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from cogito_common import CogitoError
from cogito_contracts import materialize_contract_with_limits, package_hash
from cogito_execution_registry import register_external
from cogito_test_support import GitTestCase, git
import test_atomic_task_execution as execution


class ReviewFixStartTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    check = staticmethod(execution.AtomicTaskTests.check)
    commit = staticmethod(execution.AtomicTaskTests.commit)

    def cli(self, store, command, *args, request=None, action='cli'):
        argv = [sys.executable, str(Path(__file__).resolve().parents[1] / 'scripts/cogito_gate.py'),
                '--repo', str(store.root), command, '--run-id', store.run_id, *args, '--action-id', action]
        if request is not None:
            path = store.run_dir / 'cli-input.json'
            path.write_text(json.dumps(request))
            argv.extend(['--input', str(path)])
        process = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        return json.loads(process.stdout)['data']

    def reviewing(self):
        repo, worker, store, draft = self.executing()
        results = []
        for name in ('a', 'b'):
            self.lease(store, 'T-' + name)
            (worker / ('src/' + name + '.txt')).write_text('after\n')
            self.commit(worker)
            evidence = self.check(store, worker, 'C-' + name, 'check-' + name)
            self.cli(store, 'task-finish', '--task-id', 'T-' + name,
                     request={'risks': []}, action='finish-' + name)
            results.append(store.load()['agent_results'][-1])
        store.transition('implementation-complete', {})
        self.cli(store, 'verify', '--evidence', evidence['evidence_path'], action='verify-original')
        store.submit_agent_result({**results[0], 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'status': 'needs-fix', 'changed_paths': [],
            'evidence': [], 'risks': ['fix a'], 'requested_transition': 'review-fix'})
        event = store._events.read()[-1]
        request = {'finding': {'event_sequence': event['sequence'], 'event_hash': event['event_hash']},
                   'amendment': {'id': 'TA-review', 'reason': 'fix a',
                    'added_tasks': [{'id': 'T-fix', 'slice_id': 'FS-1', 'paths': ['src/a.txt'],
                        'responsibility': 'Correct a', 'check_ids': ['C-fix', 'C-b']}],
                    'added_checks': [{'id': 'C-fix', 'phase': 'task', 'argv': [sys.executable, '-I', '-c',
                        "from pathlib import Path; assert Path('src/a.txt').read_text() == 'fixed\\n'"]}]}}
        return repo, worker, store, draft, results, request

    def fix(self, worker, store):
        self.lease(store, 'T-fix')
        (worker / 'src/a.txt').write_text('fixed\n')
        head = self.commit(worker, 'fix a\n\nCogito-Amendment: TA-review')
        checks = [self.check(store, worker, cid, 'fixed-' + cid) for cid in ('C-fix', 'C-b')]
        self.cli(store, 'task-finish', '--task-id', 'T-fix', request={'risks': []}, action='finish-fix')
        return head, checks, store.load()['agent_results'][-1]

    def test_cli_start_correction_review_and_finalize(self):
        repo, worker, store, draft, results, request = self.reviewing()
        self.cli(store, 'review-fix-start', request=request, action='start')
        prefix = store.events_path.read_bytes()
        self.cli(store, 'review-fix-start', request=request, action='start')
        self.assertEqual(store.events_path.read_bytes(), prefix)
        head, checks, result = self.fix(worker, store)
        self.cli(store, 'review-fix-complete', '--amendment-id', 'TA-review', '--commit-id', head, action='closure')
        args = [v for c in checks for v in ('--evidence', c['evidence_path'])]
        self.cli(store, 'verify', *args, action='verify-fixed')
        for i, r in enumerate([*results, result]):
            self.cli(store, 'agent-result', request={**r, 'role': 'reviewer', 'agent_id': 'reviewer',
                'reviewed_implementer': 'worker', 'changed_paths': [], 'evidence': [],
                'requested_transition': 'review-approved'}, action='review-' + str(i))
        store.transition('review-approved', {})
        git(repo, 'merge', '--no-ff', '-qm', 'integrate', draft['slices'][0]['worker']['branch'])
        integration = git(repo, 'rev-parse', 'HEAD')
        self.cli(store, 'integrate', '--commit-id', integration, '--slice-id', 'FS-1', action='integrate')
        post = self.check(store, repo, 'C-b', 'post')
        self.cli(store, 'post-verify', '--evidence', post['evidence_path'], action='post-verify')
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
        self.assertEqual(store.load()['state'], 'accepted')

    def test_invalid_finding_or_amendment_leaves_no_start_event(self):
        _, _, store, _, _, original = self.reviewing()
        for mode in ('finding', 'paths', 'empty', 'dependency'):
            request = copy.deepcopy(original)
            if mode == 'finding':
                request['finding']['event_hash'] = '0' * 64
            elif mode == 'paths':
                request['amendment']['added_tasks'][0]['paths'] = ['outside.txt']
            elif mode == 'empty':
                request['amendment']['added_tasks'] = []
            else:
                request['amendment']['added_tasks'][0]['depends_on'] = ['missing']
            before = store.events_path.read_bytes()
            with self.assertRaises(CogitoError):
                store.start_review_fix_with_amendment(request, mode)
            self.assertEqual(store.events_path.read_bytes(), before)
        self.assertFalse(list((store.run_dir / 'fixed-actions').glob('start*.json')))

    def test_partial_start_blocks_work_and_replays_same_binding(self):
        repo, worker, store, _, _, request = self.reviewing()
        append = store._events.append
        def crash(event, **kwargs):
            value = append(event, **kwargs)
            if event['type'] == 'review-fix-required':
                raise OSError('lost response')
            return value
        with patch.object(store._events, 'append', side_effect=crash):
            with self.assertRaises(OSError):
                store.start_review_fix_with_amendment(request, 'start')
        self.assertEqual(store.next_action()['next_action'], 'retry-fixed-action')
        with self.assertRaises(CogitoError):
            store.add_amendment(request['amendment'], 'manual')
        with self.assertRaises(CogitoError):
            register_external(repo, store.run_id, 'new', 'handle')
        (worker / 'src/a.txt').write_text('drift\n')
        with self.assertRaises(CogitoError):
            store.start_review_fix_with_amendment(request, 'start')
        (worker / 'src/a.txt').write_text('after\n')
        store.start_review_fix_with_amendment(request, 'start')
        self.assertEqual(sum(e['type'] == 'review-fix-required' for e in store._events.read()), 1)

    def test_replaced_finding_cannot_start_correction(self):
        _, _, store, _, results, request = self.reviewing()
        store.submit_agent_result({**results[0], 'role': 'reviewer', 'agent_id': 'reviewer',
            'reviewed_implementer': 'worker', 'changed_paths': [], 'evidence': [],
            'requested_transition': 'review-approved'})
        with self.assertRaises(CogitoError):
            store.start_review_fix_with_amendment(request, 'start')
        with self.assertRaises(CogitoError):
            store.enter_review_fix('old-start')

    def test_legacy_accepted_amendment_before_start_can_close_with_real_checks(self):
        _, worker, store, _, _, request = self.reviewing()
        # Historical accepted event fixture; new runtime admission rejects this order.
        amendment = request['amendment']
        effective = materialize_contract_with_limits(store.approved_package(), [amendment], store.workflow['limits'])
        store._events.append({'type': 'technical-amendment-added', 'payload': {
            'amendment': amendment, 'effective_contract_hash': effective['effective_contract_hash']}})
        store.enter_review_fix('legacy-start')
        head, checks, _ = self.fix(worker, store)
        prefix = store.events_path.read_bytes()
        (worker / 'src/a.txt').write_text('drift\n')
        with self.assertRaises(CogitoError):
            store.complete_review_fix('TA-review', head, 'close')
        self.assertEqual(store.events_path.read_bytes(), prefix)
        (worker / 'src/a.txt').write_text('fixed\n')
        self.cli(store, 'review-fix-complete', '--amendment-id', 'TA-review', '--commit-id', head, action='close')
        self.assertTrue(store.events_path.read_bytes().startswith(prefix))
        self.assertEqual(store.load()['state'], 'verifying')
