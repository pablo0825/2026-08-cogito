"""Closure drafts use canonical finalization and preserve evidence and user files."""
import copy
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

from cogito_test_support import GitTestCase, git
from cogito_common import CogitoError
from cogito_result_draft import build_result_facts
import test_atomic_task_verification as atomic
import test_finalization_rules as rules
import test_maintenance_amendment_records as maintenance
import test_human_acceptance as human
import test_review_retention_flow as retention


class ResultDraftTests(GitTestCase):
    def fixture(self, cls):
        fixture = cls()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        return fixture

    def finalizing(self):
        fixture = self.fixture(atomic.AtomicVerificationTests)
        repo, worker, store, _, _, _, _ = fixture.integrated()
        store.decide_post_verification([fixture.check(store, repo, 'C-b', 'post')])
        return repo, worker, store

    def invoke(self, operation, *, commit=None, action='finalize-draft', success=True):
        values = {'<actual-final-commit>': commit, '<action-id>': action}
        argv = [values.get(arg, arg) for arg in operation['argv']]
        process = subprocess.run(argv, cwd=operation['cwd'], capture_output=True, text=True, timeout=40)
        self.assertEqual(process.returncode, 0 if success else 2, process.stdout + process.stderr)
        return json.loads(process.stdout)['data'] if success else None

    def save_records(self, repo, output, *, risks=None):
        for key, path in output['drafts'].items():
            value = json.loads(Path(path).read_text())
            if key == 'result' and risks is not None:
                value['remaining_risks'] = risks
            destination = repo / output['destinations'][key]
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(value))

    def test_next_cli_draft_commit_finalize_and_accepted_cleanup_replay(self):
        repo, worker, store = self.finalizing()
        # Unrelated staged content must survive both querying and drafting.
        unrelated = repo / 'unrelated.txt'
        unrelated.write_text('user staging')
        git(repo, 'add', 'unrelated.txt')
        index = (repo / '.git/index').read_bytes()
        head = git(repo, 'rev-parse', 'HEAD')
        events = store.events_path.read_bytes()
        graph = (repo / 'docs/cogito/project-graph.json').read_bytes()
        operation, = store.next_action()['operations']
        self.assertEqual(operation['operation'], 'result-draft')
        output = self.invoke(operation)
        result = json.loads(Path(output['drafts']['result']).read_text())
        self.assertNotIn('remaining_risks', result)
        self.assertEqual(result['delivery_summary'], store.delivery_summary())
        self.assertEqual(store.events_path.read_bytes(), events)
        self.assertEqual((repo / '.git/index').read_bytes(), index)
        self.assertEqual((repo / 'docs/cogito/project-graph.json').read_bytes(), graph)
        self.assertEqual(git(repo, 'rev-parse', 'HEAD'), head)
        self.save_records(repo, output, risks=['Performance not evaluated'])
        git(repo, 'add', '--', *output['destinations'].values())
        git(repo, 'commit', '--only', '-qm', 'closure', '--', *output['destinations'].values())
        self.assertEqual(git(repo, 'diff', '--cached', '--name-only'), 'unrelated.txt')
        command, = store.next_action()['operations']
        self.assertEqual(command['operation'], 'finalize')
        self.assertIn(git(repo, 'rev-parse', 'HEAD'), command['argv'])
        self.invoke(command)
        self.assertEqual(store.load()['state'], 'accepted')
        self.assertEqual(store.completion_report()['remaining_risks'], ['Performance not evaluated'])
        before = store.events_path.read_bytes()
        self.invoke(store.next_action()['operations'][0])
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_unfilled_risks_are_rejected_and_invalid_committed_record_gets_blocker(self):
        repo, _, store = self.finalizing()
        output = store.result_draft(store.load()['last_event_hash'])
        self.save_records(repo, output)
        git(repo, 'add', '--', *output['destinations'].values())
        git(repo, 'commit', '-qm', 'incomplete closure')
        self.invoke(output['operations'][0], commit=git(repo, 'rev-parse', 'HEAD'), success=False)
        hint = store.next_action()
        self.assertEqual(hint['operations'], [])
        self.assertTrue(hint['blockers'])

    def test_repeat_drift_evidence_tampering_and_wrong_phase(self):
        repo, worker, store = self.finalizing()
        digest = store.load()['last_event_hash']
        first = store.result_draft(digest)
        Path(first['drafts']['result']).write_text('user edit')
        second = store.result_draft(digest)
        self.assertNotEqual(first['drafts'], second['drafts'])
        self.assertEqual(Path(first['drafts']['result']).read_text(), 'user edit')
        with self.assertRaisesRegex(CogitoError, 'history changed'):
            store.result_draft('f' * 64)
        self.save_records(repo, second, risks=[])
        (repo / 'src/a.txt').write_text('unverified')
        git(repo, 'add', '--', 'src/a.txt', *second['destinations'].values())
        git(repo, 'commit', '-qm', 'invalid final content')
        self.invoke(second['operations'][0], commit=git(repo, 'rev-parse', 'HEAD'), success=False)
        result = json.loads(Path(second['drafts']['result']).read_text())
        evidence_path = Path(result['checks'][0]['evidence'])
        evidence_path.chmod(0o644)
        evidence_path.write_text('{}')
        with self.assertRaises(CogitoError):
            store.result_draft(digest)
        f = self.fixture(atomic.AtomicVerificationTests)
        _, _, executing, _ = f.executing()
        with self.assertRaisesRegex(CogitoError, 'only available in finalizing'):
            executing.result_draft(executing.load()['last_event_hash'])

    def test_human_corrections_feature_and_maintenance_reach_accepted(self):
        for kind in ('feature', 'maintenance'):
            with self.subTest(kind=kind):
                f = self.fixture(human.HumanAcceptanceTests)
                repo, store = f.fixture(kind)
                with self.assertRaises(CogitoError):
                    store.result_draft(store.load()['last_event_hash'])
                f.begin(store, close=True)
                base, head = f.implement(repo, store)
                f.review(repo, store, 1, base, head)
                self.assertEqual(store.load()['state'], 'finalizing')
                output = store.result_draft(store.load()['last_event_hash'])
                result = json.loads(Path(output['drafts']['result']).read_text())
                self.assertEqual(result['human_gate'], {'required': True, 'outcome': 'approved'})
                self.assertEqual({c['id'] for c in result['checks']}, {'C-1', 'C-human-label'})
                self.save_records(repo, output, risks=[])
                paths = list(output['destinations'].values())
                if kind == 'maintenance':
                    paths.append('src/note.txt')
                    self.assertEqual(output['required_final_commit_trailers'], ['Cogito-Amendment: TA-1'])
                    self.assertIn('content_tree', result['amendments'][0])
                else:
                    self.assertIn('commit_id', result['amendments'][0])
                git(repo, 'add', '--', *paths)
                git(repo, 'commit', '-qm', 'closure\n\n' + '\n'.join(output['required_final_commit_trailers']))
                self.invoke(output['operations'][0], commit=git(repo, 'rev-parse', 'HEAD'), action='human-final')
                self.assertEqual(store.load()['state'], 'accepted')

    def test_graph_drift_and_partial_file_failure_preserve_existing_data(self):
        repo, _, store = self.finalizing()
        graph_path = repo / 'docs/cogito/project-graph.json'
        original = graph_path.read_bytes()
        graph = json.loads(original)
        graph['active_run_id'] = 'DEV-another'
        graph_path.write_text(json.dumps(graph))
        with self.assertRaisesRegex(CogitoError, 'another active run'):
            store.result_draft(store.load()['last_event_hash'])
        graph_path.write_bytes(original)
        write = Path.write_text
        def failure(path, *args, **kwargs):
            if path.name == 'project-graph.json' and path.parent.name.startswith('closure-'):
                raise OSError('disk full')
            return write(path, *args, **kwargs)
        before = store.events_path.read_bytes()
        with patch.object(Path, 'write_text', failure):
            with self.assertRaisesRegex(CogitoError, 'no finalization was submitted'):
                store.result_draft(store.load()['last_event_hash'])
        output = store.result_draft(store.load()['last_event_hash'])
        self.assertTrue(Path(output['drafts']['project_graph']).is_file())
        self.assertEqual(graph_path.read_bytes(), original)
        self.assertEqual(store.events_path.read_bytes(), before)

    def test_pure_facts_preserve_amendment_shapes_and_reviewer_sources(self):
        for context in (rules.context(), maintenance.snapshot_context()):
            events = copy.deepcopy(context.events)
            events.append({'type': 'technical-amendment-added', 'payload': {
                'amendment': {'id': 'TA-path', 'path_additions': ['src/new']}, 'scope_review': {'proposal_hash': 'a' * 64}}})
            for sequence, event in enumerate(events, 1):
                event['sequence'] = sequence
            state = copy.deepcopy(context.state)
            state['tasks'] = {'T-adopt': {'adoption': {'source_reviewers': ['adopt-reviewer']}}}
            events.append({'sequence': len(events)+1, 'type': 'review-approved',
                           'payload': {'retention': {'reviewer_id': 'retention-reviewer'}}})
            evidence = {'/evidence/C-1.json': {'check_id': 'C-1'}}
            before = copy.deepcopy((state, events))
            result = build_result_facts(context.package, state, events, evidence)
            self.assertEqual(result['amendments'][:-1], context.result['amendments'])
            self.assertEqual(result['amendments'][-1], {'id': 'TA-path', 'proposal_hash': 'a' * 64})
            self.assertTrue({'adopt-reviewer', 'retention-reviewer'} <= {r['reviewer'] for r in result['reviews']})
            self.assertEqual((state, events), before)

    def test_retained_reviews_and_correction_commit_reach_accepted(self):
        f = self.fixture(retention.ReviewRetentionFlowTests)
        repo, _, store, package, correction_head = f.corrected_wave()
        store.transition('review-approved', {'retention': f.proposal(store)}, 'retained')
        git(repo, 'merge', '--no-ff', '-qm', 'integrate', package['slices'][0]['worker']['branch'])
        store.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        store.decide_post_verification([f.check(store, repo, 'C-b', 'post')])
        output = store.result_draft(store.load()['last_event_hash'])
        result = json.loads(Path(output['drafts']['result']).read_text())
        self.assertEqual({r['reviewer'] for r in result['reviews']}, {'reviewer', 'retention-reviewer'})
        self.assertEqual(result['amendments'], [{'id': 'TA-review', 'commit_id': correction_head}])
        self.save_records(repo, output, risks=[])
        git(repo, 'add', '--', *output['destinations'].values())
        git(repo, 'commit', '-qm', 'closure')
        self.invoke(output['operations'][0], commit=git(repo, 'rev-parse', 'HEAD'))
        self.assertTrue(store.completion_report()['review_retentions'])

    def test_symlink_draft_directory_is_rejected(self):
        repo, _, store = self.finalizing()
        outside = repo / 'outside'
        outside.mkdir()
        drafts = store.run_dir / 'drafts'
        self.assertFalse(drafts.exists())
        drafts.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(CogitoError, 'symlinks'):
            store.result_draft(store.load()['last_event_hash'])
        self.assertEqual(list(outside.iterdir()), [])
