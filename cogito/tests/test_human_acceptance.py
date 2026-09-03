"""Human acceptance simulations use real repositories, workers and controlled checks.

Run ``python -B -m unittest discover -s cogito/tests -p test_human_acceptance.py -v``.
No workflow event is fabricated: fixtures enter awaiting-human through public Gates.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
import cogito_runtime as runtime
from cogito_projection import project_events


class HumanAcceptanceTests(GitTestCase):
    def fixture(self, kind="maintenance", development_rounds=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        (repo / '.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
        (repo / 'src').mkdir()
        (repo / 'src/note.txt').write_text('before\n')
        (repo / 'docs').mkdir()
        for name in ('spec', 'plan'):
            (repo / f'docs/{name}.md').write_text(f'# {name}\nMaintain readable text.\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        baseline = git(repo, 'rev-parse', 'HEAD')
        draft = package(kind)
        draft.update({
            'run_id': 'MNT-human-simulation' if kind == 'maintenance' else 'DEV-human-simulation',
            'baseline_commit': baseline, 'approved_paths': ['src/note.txt'],
            'execution_dag': {'tasks': [{'id': 'T-1', 'paths': ['src/note.txt']}], 'edges': []},
            'checks': [{'id': 'C-1', 'required': True, 'argv': [
                sys.executable, '-I', '-c',
                "from pathlib import Path; text = Path('src/note.txt').read_text(); "
                "assert text.startswith('after'), text",
            ]}],
        })
        if kind == 'feature':
            draft['execution_dag']['tasks'][0]['slice_id'] = 'FS-1'
            draft['slices'][0]['worker']['allowed_paths'] = ['src/note.txt']
            for name in ('spec', 'plan'):
                draft['slices'][0][name]['hash'] = hashlib.sha256((repo / f'docs/{name}.md').read_bytes()).hexdigest()
        store = runtime.RunStore(repo, draft['run_id'])
        store.create(kind)
        if kind == 'feature':
            store.transition('shared-understanding-ready', {'shared_understanding_hash': 'b' * 64})
            store.transition('shared-understanding-confirmed', {'confirmed': True})
            store.transition('boundary-complete', draft['boundary'])
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        worker = repo
        if kind == 'feature':
            worker = repo / '.cogito/worktrees/FS-1'
            git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-1', str(worker), baseline)
        store.update_task('T-1', 'leased', 'initial-worker')
        store.update_task('T-1', 'running', 'initial-worker')
        (worker / 'src/note.txt').write_text('after with typo\n')
        if kind == 'feature':
            git(worker, 'add', 'src/note.txt')
            git(worker, 'commit', '-qm', 'implement text')
        head = git(worker, 'rev-parse', 'HEAD')
        store.submit_agent_result(self.result(store, 'T-1', 'initial-worker', baseline, head))
        store.update_task('T-1', 'complete', 'initial-worker')
        store.transition('implementation-complete', {})
        for number in range(1, development_rounds + 1):
            self.assertEqual(kind, 'maintenance')
            amendment = f'TA-development-{number}'
            store.add_amendment({'id': amendment, 'reason': 'Repair original implementation',
                                 'path_fixes': ['src/note.txt']})
            store.enter_correction(f'development-start-{number}')
            (repo / 'src/note.txt').write_text(f'after development repair {number}\n')
            store.complete_correction(amendment, baseline, f'development-complete-{number}')
        store.complete_verification([self.check(store, worker, 'initial-pre')])
        if kind == 'feature':
            store.submit_agent_result(self.result(store, 'T-1', 'initial-reviewer', baseline, head,
                                                 reviewer_of='initial-worker'))
            store.transition('review-approved', {})
            git(repo, 'merge', '--no-ff', '-qm', 'integrate text', 'codex/fs-1')
            store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        else:
            store.transition('review-approved', {'review_exemption': True})
            store.complete_integration(baseline)
        store.decide_post_verification([self.check(store, repo, 'initial-post')], reviewer_escalation=True)
        self.assertEqual(store.load()['state'], 'awaiting-human')
        return repo, store

    @staticmethod
    def result(store, task, agent, base, head, reviewer_of=None):
        value = {
            'schema_version': '3.0', 'run_id': store.run_id, 'task_id': task,
            'agent_id': agent, 'role': 'reviewer' if reviewer_of else 'implementer',
            'status': 'complete', 'base_commit': base, 'head_commit': head,
            'changed_paths': [] if reviewer_of else ['src/note.txt'],
            'evidence': [], 'risks': [],
            'requested_transition': 'review-approved' if reviewer_of else 'verifying',
        }
        if reviewer_of:
            value['reviewed_implementer'] = reviewer_of
        return value

    @staticmethod
    def check(store, repo, action, check_id='C-1'):
        before = set((store.run_dir / 'evidence').glob(f'{check_id}-*.json'))
        store.run_controlled_check(check_id, repo, action)
        path, = set((store.run_dir / 'evidence').glob(f'{check_id}-*.json')) - before
        evidence = json.loads(path.read_text())
        return evidence

    @staticmethod
    def feedback(number=1, close=False, mixed=False):
        value = {
            'id': f'HF-{number}', 'message': 'Correct the label.' if not close else 'Everything else accepted; fix this and close.',
            'items': [{'id': 'I-1', 'description': 'Correct the label typo'}],
            'acceptance_complete': close, 'close_after_fixes': close,
        }
        if mixed:
            value['items'].append({'id': 'I-2', 'description': 'Automatically query after choosing a date'})
        return value

    def begin(self, store, number=1, close=False):
        request = self.feedback(number, close)
        state = store.human_feedback(request, f'feedback-{number}')
        self.assertEqual(state['state'], 'human-feedback-triage')
        self.assertEqual(store.human_feedback(request, f'feedback-{number}'), state)
        store.human_triage({
            'feedback_id': f'HF-{number}',
            'assessments': [{'id': 'I-1', 'disposition': 'local', 'reason': 'One label; bounded scope'}],
        }, f'triage-{number}')
        amendment = {
            'id': f'TA-{number}', 'reason': 'Repair the accepted label',
            'added_tasks': [{'id': f'T-H-{number}',
                             'slice_id': 'FS-1' if store.load()['kind'] == 'feature' else 'mini-package',
                             'paths': ['src/note.txt']}],
        }
        if number == 1:
            amendment['added_checks'] = [{'id': 'C-human-label', 'required': True, 'argv': [
                sys.executable, '-I', '-c',
                "from pathlib import Path; import re; text = Path('src/note.txt').read_text(); "
                "assert re.fullmatch(r'after corrected [1-9][0-9]*\\n', text), text",
            ]}]
        store.add_amendment(amendment, f'amend-{number}')
        return store.human_correction_start({'amendment_id': f'TA-{number}'}, f'start-{number}')

    def implement(self, repo, store, number=1):
        task, agent = f'T-H-{number}', f'human-worker-{number}'
        base = git(repo, 'rev-parse', 'HEAD')
        store.update_task(task, 'leased', agent)
        store.update_task(task, 'running', agent)
        (repo / 'src/note.txt').write_text(f'after corrected {number}\n')
        if store.load()['kind'] == 'feature':
            git(repo, 'add', 'src/note.txt')
            git(repo, 'commit', '-qm', f'correct label\n\nCogito-Amendment: TA-{number}')
        head = git(repo, 'rev-parse', 'HEAD')
        store.submit_agent_result(self.result(store, task, agent, base, head))
        store.update_task(task, 'complete', agent)
        state = store.human_correction_complete({
            'feedback_id': f'HF-{number}', 'amendment_id': f'TA-{number}',
            'commit_id': head, 'resolved_item_ids': ['I-1'], 'summary': 'Corrected label',
        }, f'complete-{number}')
        self.assertEqual(state['state'], 'human-correction-verifying')
        return base, head

    def review(self, repo, store, number, base, head):
        evidence = self.check(store, repo, f'human-check-{number}')
        self.assertTrue(evidence['passed'])
        label = self.check(store, repo, f'human-label-{number}', 'C-human-label')
        self.assertTrue(label['passed'])
        store.human_verify([evidence, label], f'human-verify-{number}')
        self.assertEqual(store.load()['state'], 'human-correction-reviewing')
        store.submit_agent_result(self.result(store, f'T-H-{number}', f'human-reviewer-{number}', base, head,
                                             reviewer_of=f'human-worker-{number}'))
        return store.human_review(f'human-review-{number}')

    def finalize_delivery(self, repo, store):
        """Publish verified result/graph and prove the real final Gate accepts it."""
        events = [json.loads(line) for line in store.events_path.read_text().splitlines()]
        completions = [event['payload'] for event in events if event['type'] == 'human-correction-complete']
        evidence = json.loads(sorted((store.run_dir / 'evidence').glob('C-1-*.json'))[-1].read_text())
        # File ordering is not a freshness guarantee; use the matching verified event.
        for event in reversed(events):
            paths = event['payload'].get('evidence')
            if isinstance(paths, list) and paths and isinstance(paths[0], str):
                evidence = json.loads(Path(paths[0]).read_text())
                evidence_set = [json.loads(Path(path).read_text()) for path in paths]
                break
        graph_rel = 'docs/cogito/project-graph.json'
        graph = json.loads((repo / graph_rel).read_text())
        graph['active_run_id'] = None
        dispositions = {}
        for item in store.approved_package()['slices']:
            dispositions[item['id']] = 'accepted'
            graph['slices'][item['id']].update({'disposition': 'accepted', 'completed_by': store.run_id})
        (repo / graph_rel).write_text(json.dumps(graph))
        amendments = []
        for item in completions:
            summary = {'id': item['amendment_id']}
            if item.get('completion_mode') == 'working-tree':
                summary.update({'base_commit': item['commit_id'], 'content_tree': item['content_tree']})
            else:
                summary['commit_id'] = item['commit_id']
            amendments.append(summary)
        integrations = [event['payload']['commit_id'] for event in events
                        if event['type'] in {'integration-complete', 'slice-integration-complete'}]
        reviewers = sorted({item['agent_id'] for item in store.load()['agent_results']
                            if item['role'] == 'reviewer' and item['status'] == 'complete'})
        result_rel = f'docs/cogito/results/{store.run_id}.json'
        result = repo / result_rel
        result.parent.mkdir(parents=True, exist_ok=True)
        result.write_text(json.dumps({
            'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': runtime.package_hash(store.approved_package()),
            'effective_contract_hash': store.load()['effective_contract_hash'],
            'integration_commits': integrations, 'slice_dispositions': dispositions,
            'checks': [{'id': item['check_id'], 'status': 'passed', 'evidence': item['evidence_path']}
                       for item in evidence_set],
            'reviews': [{'reviewer': reviewer} for reviewer in reviewers],
            'amendments': amendments, 'human_gate': {'required': True, 'outcome': 'approved'},
            'remaining_risks': [],
        }))
        git(repo, 'add', 'src/note.txt', graph_rel, result_rel)
        trailers = '\n'.join(f"Cogito-Amendment: {item['id']}" for item in amendments)
        git(repo, 'commit', '-qm', 'Finalize accepted human corrections\n\n' + trailers)
        store.finalize(result_rel, graph_rel, git(repo, 'rev-parse', 'HEAD'))
        self.assertEqual(store.completion_report()['status'], 'accepted')
        return [{'event': event['type'], 'state': project_events(events[:index + 1], store.workflow)['state']}
                for index, event in enumerate(events) if event['type'].startswith('human-')]

    def test_conditional_acceptance_and_unknown_acceptance_are_distinct(self):
        for kind in ('maintenance', 'feature'):
            for close in (False, True):
                with self.subTest(kind=kind, close=close):
                    repo, store = self.fixture(kind)
                    self.begin(store, close=close)
                    base, head = self.implement(repo, store)
                    state = self.review(repo, store, 1, base, head)
                    self.assertEqual(state['state'], 'finalizing' if close else 'awaiting-human')
                    if close:
                        self.finalize_delivery(repo, store)

    def test_mixed_feedback_cannot_begin_local_repairs(self):
        repo, store = self.fixture()
        store.human_feedback(self.feedback(mixed=True), 'mixed-feedback')
        store.human_triage({
            'feedback_id': 'HF-1', 'assessments': [
                {'id': 'I-1', 'disposition': 'local', 'reason': 'One typo'},
                {'id': 'I-2', 'disposition': 'change', 'reason': 'Changes the interaction flow'},
            ],
        }, 'mixed-triage')
        with self.assertRaises(runtime.CogitoError):
            store.human_correction_start({'amendment_id': 'TA-1'}, 'mixed-start')
        self.assertNotEqual(store.load()['state'], 'human-correction')
        self.assertEqual((repo / 'src/note.txt').read_text(), 'after with typo\n')

    def test_stale_evidence_and_self_review_do_not_close_run(self):
        repo, store = self.fixture()
        old = json.loads(sorted((store.run_dir / 'evidence').glob('C-1-*.json'))[-1].read_text())
        self.begin(store, close=True)
        base, head = self.implement(repo, store)
        before = store.events_path.read_bytes()
        with self.assertRaises(runtime.CogitoError):
            store.human_verify([old], 'stale-verify')
        self.assertEqual(store.events_path.read_bytes(), before)
        store.human_verify([self.check(store, repo, 'fresh-human-check'),
                            self.check(store, repo, 'fresh-label-check', 'C-human-label')], 'fresh-verify')
        with self.assertRaises(runtime.CogitoError):
            store.submit_agent_result(self.result(store, 'T-H-1', 'human-worker-1', base, head,
                                                 reviewer_of='human-worker-1'))
        with self.assertRaises(runtime.CogitoError):
            store.human_review('missing-independent-review')
        self.assertEqual(store.load()['state'], 'human-correction-reviewing')

    def test_three_round_budget_persists_across_feedback_and_reload(self):
        repo, store = self.fixture()
        for number in range(1, 4):
            self.begin(store, number)
            base, head = self.implement(repo, store, number)
            state = self.review(repo, store, number, base, head)
            self.assertEqual(state['state'], 'awaiting-human')
            store = runtime.RunStore(repo, store.run_id)
        state = self.begin(store, 4)
        self.assertEqual(state['state'], 'blocked')
        self.assertEqual(state['counters']['human_corrections'], 3)

    def test_scope_expansion_stops_repairs_before_review_or_closure(self):
        repo, store = self.fixture()
        self.begin(store, close=True)
        state = store.human_escalate({'reason': 'Shared date parsing affects other pages'}, 'expanded-scope')
        self.assertEqual(state['state'], 'blocked')
        with self.assertRaises(runtime.CogitoError):
            store.update_task('T-H-1', 'leased', 'replacement-worker')
        with self.assertRaises(runtime.CogitoError):
            store.approve_human_gate('old-closure-grant')

    def test_development_rounds_do_not_consume_human_budget_and_replays_do_not_increment(self):
        repo, store = self.fixture(development_rounds=2)
        self.assertEqual(store.load()['counters']['verification_corrections'], 2)
        for number in range(1, 4):
            started = self.begin(store, number)
            self.assertEqual(started['counters']['human_corrections'], number)
            before = store.events_path.read_bytes()
            replay = store.human_correction_start({'amendment_id': f'TA-{number}'}, f'start-{number}')
            self.assertEqual(replay, started)
            self.assertEqual(store.events_path.read_bytes(), before)
            base, head = self.implement(repo, store, number)
            self.review(repo, store, number, base, head)
            store = runtime.RunStore(repo, store.run_id)
            self.assertEqual(store.load()['counters']['verification_corrections'], 2)
        self.assertEqual(self.begin(store, 4)['state'], 'blocked')

    def test_new_feedback_replaces_previous_resolution_and_uses_new_grant(self):
        repo, store = self.fixture()
        self.begin(store, 1, close=False)
        base, head = self.implement(repo, store, 1)
        self.review(repo, store, 1, base, head)
        old_hash = store.load()['human']['feedback_hash']
        self.begin(store, 2, close=True)
        human = store.load()['human']
        self.assertNotEqual(human['feedback_hash'], old_hash)
        self.assertIsNone(human['resolution'])
        self.assertNotIn('decision', human)
        with self.assertRaises(runtime.CogitoError):
            store.human_correction_complete({
                'feedback_id': 'HF-1', 'amendment_id': 'TA-2', 'commit_id': git(repo, 'rev-parse', 'HEAD'),
                'resolved_item_ids': ['I-1'], 'summary': 'Old batch already resolved',
            }, 'stale-resolution')
        base, head = self.implement(repo, store, 2)
        self.assertEqual(self.review(repo, store, 2, base, head)['state'], 'finalizing')
        self.finalize_delivery(repo, store)

    def test_unclassified_feedback_cannot_bypass_to_human_approval(self):
        repo, store = self.fixture()
        store.human_feedback(self.feedback(close=True), 'needs-triage')
        with self.assertRaises(runtime.CogitoError):
            store.approve_human_gate('premature-approval')
        self.assertEqual(store.load()['state'], 'human-feedback-triage')


if __name__ == '__main__':
    import unittest
    unittest.main()
