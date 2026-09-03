"""Real Git/Gate simulation of Option A, with explicitly synthetic human input."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase, git, init_repo, package
import test_human_acceptance as human_helpers
from cogito_common import CogitoError
from cogito_contracts import materialize_contract_with_limits, package_hash
from cogito_finalization_rules import FinalizationContext, validate_finalization_records
from cogito_run_store import RunStore


class StageDeliveryAcceptanceTests(GitTestCase):
    # Reuse helpers, without inheriting the unrelated human regression tests.
    result = staticmethod(human_helpers.HumanAcceptanceTests.result)
    check = staticmethod(human_helpers.HumanAcceptanceTests.check)
    feedback = staticmethod(human_helpers.HumanAcceptanceTests.feedback)
    begin = human_helpers.HumanAcceptanceTests.begin
    implement = human_helpers.HumanAcceptanceTests.implement
    review = human_helpers.HumanAcceptanceTests.review

    def checkpoint(self, repo, store, action):
        prepared = store.prepare_checkpoint()
        git(repo, 'add', '--', *prepared['paths'])
        git(repo, 'commit', '-qm', prepared['commit_message'], '--only', '--', *prepared['paths'])
        head = git(repo, 'rev-parse', 'HEAD')
        store.record_checkpoint(head, action)
        return head

    def fixture(self, kind):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name).resolve()
        init_repo(repo)
        (repo / '.gitignore').write_text('.cogito/\n')
        (repo / 'src').mkdir()
        (repo / 'src/note.txt').write_text('before\n')
        git(repo, 'add', '.')
        git(repo, 'commit', '-qm', 'baseline')
        baseline = git(repo, 'rev-parse', 'HEAD')
        draft = package(kind)
        draft.update({
            'run_id': f'DEV-stage-{kind}', 'baseline_commit': baseline,
            'approved_paths': ['src/note.txt'],
            'execution_dag': {'tasks': [{'id': 'T-1', 'paths': ['src/note.txt']}], 'edges': []},
            'checks': [{'id': 'C-1', 'required': True, 'argv': [
                sys.executable, '-I', '-c',
                "from pathlib import Path; text = Path('src/note.txt').read_text(); "
                "assert text.startswith('after'), text",
            ]}],
        })
        store = RunStore(repo, draft['run_id'])
        store.create(kind, stage_commits=True)
        if kind == 'feature':
            draft['execution_dag']['tasks'][0]['slice_id'] = 'FS-1'
            draft['slices'][0]['worker']['allowed_paths'] = ['src/note.txt']
            for name in ('shared', 'spec', 'plan'):
                path = f'docs/{name}.md'
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(f'# {name}\nMaintain readable text.\n')
                document = {'path': path, 'hash': hashlib.sha256(target.read_bytes()).hexdigest()}
                if name == 'shared':
                    draft['shared_understanding'] = document
                else:
                    draft['slices'][0][name] = document
            shared = draft['shared_understanding']
            store.transition('shared-understanding-ready', {
                'shared_understanding_hash': shared['hash'], 'document': shared}, 'shared-ready')
            store.transition('shared-understanding-confirmed', {
                'confirmed': True, 'shared_understanding_hash': shared['hash']}, 'shared-confirmed')
            self.checkpoint(repo, store, 'shared-commit')
            store.transition('boundary-complete', draft['boundary'], 'boundary')
            self.checkpoint(repo, store, 'boundary-commit')
        store.prepare_package(draft, 'prepare-package')
        store.approve_package(draft, 'approve-package')
        start = self.checkpoint(repo, store, 'package-commit')
        self.assertEqual([item['stage'] for item in store.load()['checkpoints']],
                         ['shared-understanding', 'boundary', 'package'] if kind == 'feature' else ['package'])
        store.start_gate('start')
        worker = repo
        if kind == 'feature':
            worker = repo / '.cogito/worktrees/FS-1'
            git(repo, 'worktree', 'add', '-q', '-b', 'codex/fs-1', str(worker), start)
        store.update_task('T-1', 'leased', 'initial-worker')
        store.update_task('T-1', 'running', 'initial-worker')
        (worker / 'src/note.txt').write_text('after with typo\n')
        if kind == 'feature':
            git(worker, 'add', 'src/note.txt')
            git(worker, 'commit', '-qm', 'feat: implement text')
        implementation = git(worker, 'rev-parse', 'HEAD')
        store.submit_agent_result(self.result(store, 'T-1', 'initial-worker', start, implementation))
        store.update_task('T-1', 'complete', 'initial-worker')
        store.transition('implementation-complete', {})
        store.complete_verification([self.check(store, worker, 'initial-pre')])
        if kind == 'feature':
            store.submit_agent_result(self.result(store, 'T-1', 'initial-reviewer', start, implementation,
                                                 reviewer_of='initial-worker'))
            store.transition('review-approved', {})
            git(repo, 'merge', '--ff-only', 'codex/fs-1')
            self.assertEqual(git(repo, 'rev-parse', 'HEAD'), implementation)
            store.complete_integration(implementation, 'FS-1')
        else:
            store.transition('review-approved', {'review_exemption': True})
            store.complete_integration(start)
        store.decide_post_verification([self.check(store, repo, 'initial-post')], reviewer_escalation=True)
        self.assertEqual(store.load()['state'], 'awaiting-human')
        return repo, store, start, implementation

    def prepare_result(self, repo, store):
        events = store._events.read()
        state = store.load()
        verified = next(event for event in reversed(events)
                        if event['type'] in {'human-correction-reviewed', 'human-correction-accepted'})
        evidence = [json.loads(Path(path).read_text()) for path in verified['payload']['evidence']]
        graph_path = 'docs/cogito/project-graph.json'
        graph = json.loads((repo / graph_path).read_text())
        graph['active_run_id'] = None
        dispositions = {}
        for item in store.approved_package()['slices']:
            dispositions[item['id']] = 'accepted'
            graph['slices'][item['id']].update({'disposition': 'accepted', 'completed_by': store.run_id})
        amendments = []
        for event in events:
            if event['type'] != 'human-correction-complete':
                continue
            item = event['payload']
            summary = {'id': item['amendment_id']}
            if item.get('completion_mode') == 'working-tree':
                summary.update({'base_commit': item['commit_id'], 'content_tree': item['content_tree']})
            else:
                summary['commit_id'] = item['commit_id']
            amendments.append(summary)
        value = {
            'schema_version': '3.0', 'run_id': store.run_id, 'status': 'accepted',
            'package_hash': package_hash(store.approved_package()),
            'effective_contract_hash': state['effective_contract_hash'],
            'integration_commits': [event['payload']['commit_id'] for event in events
                                    if event['type'] in {'integration-complete', 'slice-integration-complete'}],
            'slice_dispositions': dispositions,
            'checks': [{'id': item['check_id'], 'status': 'passed', 'evidence': item['evidence_path']}
                       for item in evidence],
            'reviews': [{'reviewer': reviewer} for reviewer in sorted({item['agent_id']
                        for item in state['agent_results'] if item['role'] == 'reviewer' and item['status'] == 'complete'})],
            'amendments': amendments, 'human_gate': {'required': True, 'outcome': 'approved'},
            'remaining_risks': [], 'delivery_summary': store.delivery_summary(),
        }
        cli = subprocess.run([
            sys.executable, str(COGITO / 'scripts/cogito_gate.py'), '--repo', str(repo),
            'delivery-summary', '--run-id', store.run_id,
        ], check=True, text=True, capture_output=True)
        self.assertEqual(json.loads(cli.stdout)['data'], value['delivery_summary'])
        effective = materialize_contract_with_limits(store.approved_package(), [
            event['payload']['amendment'] for event in events if event['type'] == 'technical-amendment-added'
        ], store.workflow['limits'])
        for defect in ('missing', 'tampered'):
            invalid = copy.deepcopy(value)
            if defect == 'missing':
                del invalid['delivery_summary']
            else:
                invalid['delivery_summary']['preparation'][0]['commit_id'] = 'f' * 40
            context = FinalizationContext(store.run_id, store.approved_package(), state,
                                          events, invalid, graph, effective)
            with self.assertRaisesRegex(CogitoError, 'delivery_summary'):
                validate_finalization_records(context)
        result_path = f'docs/cogito/results/{store.run_id}.json'
        (repo / result_path).parent.mkdir(parents=True, exist_ok=True)
        (repo / result_path).write_text(json.dumps(value, indent=2) + '\n')
        (repo / graph_path).write_text(json.dumps(graph, indent=2) + '\n')
        return result_path, graph_path, value

    def run_scenario(self, kind):
        repo, store, start, implementation = self.fixture(kind)
        transitions = [{'step': 'initial human acceptance', 'state': store.load()['state']}]
        self.begin(store, close=False)
        transitions.append({'step': 'synthetic human rejects label', 'state': store.load()['state']})
        base, correction = self.implement(repo, store)
        transitions.append({'step': 'correction complete', 'state': store.load()['state']})
        reviewed = self.review(repo, store, 1, base, correction)
        self.assertEqual(reviewed['state'], 'awaiting-human')
        self.assertFalse(any(event['type'] == 'human-approved' for event in store._events.read()))
        transitions.append({'step': 'fresh checks and independent review', 'state': reviewed['state']})
        with self.assertRaisesRegex(CogitoError, 'finalization is not legal'):
            store.finalize(f'docs/cogito/results/{store.run_id}.json', 'docs/cogito/project-graph.json', correction)
        store.approve_human_gate('synthetic-human-accept')
        self.assertEqual(store.load()['state'], 'finalizing')
        transitions.append({'step': 'explicit synthetic human acceptance', 'state': store.load()['state']})
        result_path, graph_path, value = self.prepare_result(repo, store)
        git(repo, 'add', '--', 'src/note.txt', result_path, graph_path)
        git(repo, 'commit', '-qm', 'docs: finalize accepted delivery\n\nCogito-Amendment: TA-1')
        final = git(repo, 'rev-parse', 'HEAD')
        store.finalize(result_path, graph_path, final, 'finalize')
        self.assertEqual(store.load()['state'], 'accepted')
        self.assertEqual(store.completion_report()['status'], 'accepted')
        committed = json.loads(git(repo, 'show', f'{final}:{result_path}'))
        self.assertEqual(committed['delivery_summary'], value['delivery_summary'])
        self.assertEqual(git(repo, 'status', '--porcelain'), '')
        product_commits = git(repo, 'rev-list', '--reverse', f'{start}..{final}').splitlines()
        self.assertEqual(len(product_commits), 3 if kind == 'feature' else 1)
        if kind == 'feature':
            self.assertEqual(product_commits, [implementation, correction, final])
        transitions.append({'step': 'final Result and Graph commit accepted', 'state': 'accepted'})
        return {
            'kind': kind, 'passed': True,
            'human_inputs': 'Synthetic fixture feedback and explicit approval; not real user sign-off.',
            'reviewers': 'Distinct synthetic reviewer identities; no claim of live agent quality assessment.',
            'preparation_commits': store.load()['checkpoints'], 'start_commit': start,
            'implementation_commit': implementation if kind == 'feature' else None,
            'integration_commit': implementation, 'correction_commit': correction if kind == 'feature' else None,
            'final_commit': final, 'product_commits': product_commits, 'transitions': transitions,
            'assertions': ['No finalization before explicit human acceptance',
                           'All applicable preparation stages have separate recorded commits',
                           'Missing and tampered summary rejected by finalization record rules',
                           'CLI summary matches public RunStore summary',
                           'Fresh correction checks and separate reviewer identity',
                           'Result summary persisted in final Git commit',
                           'Clean final checkout',
                           'Feature fast-forward adds no integration-only commit' if kind == 'feature'
                           else 'Maintenance retains one product commit after Start Gate'],
            'delivery_summary': committed['delivery_summary'],
        }

    def test_feature_rejection_correction_and_explicit_acceptance(self):
        self.run_scenario('feature')

    def test_maintenance_keeps_one_product_commit_after_checkpoint(self):
        self.run_scenario('maintenance')
