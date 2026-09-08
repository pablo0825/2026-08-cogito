"""RP source classification with real Git checkpoints and immutable artifacts.

The classification fixture supplies only the source run projection. Package
validation, Amendment materialization, hashes and RP snapshots are real. The
separate flow fixture also uses real source events and Task evidence. All Git
repositories are disposable; no product database or checkout is modified.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cogito_test_support import GitTestCase, git, init_repo
from cogito_common import CogitoError, hash_json
from cogito_contracts import materialize_contract, package_hash, validate_package
from cogito_events import append_event, read_events
from cogito_replan_store import ReplanStore
from cogito_run_store import RunStore
import test_atomic_task_verification as atomic_tests


class ReplanRuntimeSourcesTest(GitTestCase):
    def setUp(self):
        super().setUp()
        self.directory = tempfile.TemporaryDirectory(prefix='rp-source-fixture-')
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        init_repo(self.root)
        self.write('.gitignore', '.cogito/\n')
        self.product = 'docs/product.md'
        self.unapproved = 'docs/reference.md'
        self.contracts = ['docs/spec.md', 'docs/plan.md', 'docs/shared.md']
        for path in [self.product, self.unapproved, *self.contracts]:
            self.write(path, 'planning baseline\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture baseline')
        self.package = {
            'schema_version': '3.0', 'run_id': 'DEV-001', 'kind': 'change',
            'delivery_branch': 'main', 'baseline_commit': self.git('rev-parse', 'HEAD'),
            'task_delivery': 'atomic',
            'shared_understanding': self.document(self.contracts[2]),
            'boundary': {'decision': 'single-slice', 'evidence': ['fixture']},
            'slices': [{'id': 'FS-001', 'type': 'change',
                        'spec': self.document(self.contracts[0]),
                        'plan': self.document(self.contracts[1]),
                        'worker': {'branch': 'codex/fixture', 'worktree': '.cogito/worktrees/fixture',
                                   'allowed_paths': [self.product]}}],
            'execution_dag': {'edges': [], 'tasks': [
                {'id': 'T-001', 'slice_id': 'FS-001', 'paths': [self.product],
                 'responsibility': 'fixture product edit', 'check_ids': ['C-001']} ]},
            'checks': [{'id': 'C-001', 'argv': ['python3', '-V'], 'required': True,
                        'phase': 'integration', 'timeout_seconds': 10, 'env_allowlist': []}],
            'approved_paths': [self.product],
            'human_gate': {'required': False, 'predicates': [], 'high_risk_hotspots': []},
            'policy_snapshot': {'allowed_environment': [], 'fetch_allowed': False,
                                'max_check_output_bytes': 10485760, 'max_workers': 1,
                                'required_checks': []},
            'limits': {'format_repairs': 2, 'human_corrections': 3, 'review_fix_cycles': 3,
                       'transient_retries': 2, 'verification_corrections': 3},
            'stop_conditions': ['fixture only'],
            'source_registry': [self.document(p, registry=True) for p in
                                [self.product, self.unapproved, *self.contracts]],
        }
        self.package_path = 'docs/cogito/packages/DEV-001.json'
        self.publish_package()
        self.source_events = self.root / '.cogito/runs/DEV-001/events.jsonl'
        append_event(self.source_events, {'type': 'run-created', 'payload': {}, 'action_id': 'fixture'})
        self.evidence_path = self.root / '.cogito/runs/DEV-001/evidence/result.json'
        self.evidence = {'run_id': 'DEV-001', 'check_id': 'C-001', 'passed': True}
        self.write(self.evidence_path.relative_to(self.root), json.dumps(self.evidence))
        self.graph = {'schema_version': '3.0', 'active_run_id': None,
                      'slices': {'FS-001': {'disposition': 'accepted'}}, 'dependencies': []}
        self.write('docs/cogito/project-graph.json', json.dumps(self.graph))
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture approved control files')
        # The projection seam avoids replaying unrelated preparation stages. The
        # real approved_package still validates both frozen bytes and hash.
        self.loader = patch.object(RunStore, 'load', autospec=True,
                                   side_effect=lambda store: self.source_state(store))
        self.loader.start()
        self.addCleanup(self.loader.stop)
        self.rp = ReplanStore(self.root, 'RP-001')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.root), *args], text=True,
                                       stderr=subprocess.PIPE).strip()

    def write(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)

    def document(self, path, registry=False):
        value = {'path': path, 'hash': hashlib.sha256((self.root / path).read_bytes()).hexdigest()}
        if registry:
            value.update(disposition='read-only-source', relevance='fixture source')
        return value

    def publish_package(self):
        self.package['package_hash'] = package_hash(self.package)
        validate_package(self.package)
        self.write(self.package_path, json.dumps(self.package))

    def source_state(self, store):
        self.assertEqual(store.root, self.root)
        self.assertEqual(store.run_id, 'DEV-001')
        events = read_events(self.source_events)
        amendments = [e['payload']['amendment'] for e in events
                      if e['type'] == 'technical-amendment-added']
        effective = materialize_contract(self.package, amendments)
        return {'state': 'accepted', 'tasks': {}, 'package_path': self.package_path,
                'package_hash': package_hash(self.package),
                'effective_contract_hash': effective['effective_contract_hash'],
                'last_event_hash': events[-1]['event_hash'],
                'evidence': {str(self.evidence_path): {'evidence_hash': hash_json(self.evidence)}}}

    def begin(self):
        self.rp.begin('DEV-001', 'DEV-002', 'fixture replan', 'fixture-begin')

    def stop(self):
        self.begin()
        result = self.rp.stop('fixture-stop')
        self.assertEqual(result['state'], 'analyzing')
        return result

    def test_approved_product_change_can_stop_and_is_protected(self):
        self.write(self.product, 'authorized implementation\n')
        saved = self.stop()
        runtime = self.rp._runtime()
        self.assertIn(self.product, runtime.protected)
        self.assertEqual(runtime.protected, {self.product, self.unapproved, *self.contracts})
        self.rp._assert_source()
        tree = saved['snapshot']['delivery']['content_tree']
        self.assertEqual(self.git('show', tree + ':' + self.product), 'authorized implementation')

    def test_unapproved_source_change_refuses_stop(self):
        self.write(self.unapproved, 'unauthorized drift\n')
        self.begin()
        with self.assertRaisesRegex(CogitoError, 'Package content hash drifted'):
            self.rp.stop('fixture-stop')
        self.assertEqual(self.rp.load()['state'], 'stopping')

    def test_contract_documents_always_validate_even_when_approved(self):
        # Include the exact paths as product scope to prove strict classification
        # has precedence, including duplicate source-registry references.
        self.package['approved_paths'].extend(self.contracts)
        self.package['slices'][0]['worker']['allowed_paths'].extend(self.contracts)
        self.package['execution_dag']['tasks'][0]['paths'].extend(self.contracts)
        self.publish_package()
        self.begin()
        for path in self.contracts:
            with self.subTest(path=path):
                self.write(path, 'contract drift\n')
                with self.assertRaisesRegex(CogitoError, 'Package content hash drifted'):
                    self.rp.stop('fixture-stop')
                self.write(path, 'planning baseline\n')

    def test_effective_amendment_paths_are_used_without_mutating_package(self):
        original = (self.root / self.package_path).read_bytes()
        added_path = 'docs/added-product.md'
        amendment = {'id': 'TA-001', 'reason': 'authorized missing product path',
                     'path_additions': [{'task_id': 'T-001', 'paths': [added_path],
                                         'reason': 'fixture', 'check_ids': ['C-001']}]}
        append_event(self.source_events, {'type': 'technical-amendment-added',
                                         'payload': {'amendment': amendment}})
        self.write(added_path, 'amendment-authorized implementation\n')
        self.write(self.product, 'authorized implementation\n')
        effective_calls = []
        real_effective_package = RunStore.effective_package

        def observe_effective_package(store):
            result = real_effective_package(store)
            effective_calls.append(result)
            return result

        # Observe the real materializer: no fabricated effective scope.
        with patch.object(RunStore, 'effective_package', autospec=True,
                          side_effect=observe_effective_package):
            self.stop()
            self.rp._assert_source()
        self.assertTrue(effective_calls)
        self.assertTrue(all(added_path in item['approved_paths'] for item in effective_calls))
        self.assertEqual((self.root / self.package_path).read_bytes(), original)
        self.assertNotIn(added_path, self.package['approved_paths'])
        self.write(added_path, 'post-stop amendment product drift\n')
        with self.assertRaisesRegex(CogitoError, 'delivery content drifted'):
            self.rp._assert_source()

    def test_amendment_cannot_bypass_existing_source_scope_guards(self):
        # Existing path-addition rules explicitly forbid adding a frozen source;
        # the runtime change must not invent a way around those rules.
        amendment = {'id': 'TA-001', 'reason': 'invalid source scope expansion',
                     'path_additions': [{'task_id': 'T-001', 'paths': [self.unapproved],
                                         'reason': 'fixture', 'check_ids': ['C-001']}]}
        append_event(self.source_events, {'type': 'technical-amendment-added',
                                         'payload': {'amendment': amendment}})
        with self.assertRaisesRegex(CogitoError, 'overlaps frozen control or safety scope'):
            self.rp._runtime({'source_run_id': 'DEV-001', 'successor_run_id': 'DEV-002',
                              'replan_id': 'RP-001'})

    def test_post_stop_product_drift_is_rejected(self):
        self.write(self.product, 'authorized implementation\n')
        self.stop()
        self.write(self.product, 'unauthorized post-stop drift\n')
        with self.assertRaisesRegex(CogitoError, 'delivery content drifted'):
            self.rp._assert_source()

    def test_history_prefix_package_and_evidence_bytes_are_preserved(self):
        self.write(self.product, 'authorized implementation\n')
        source_bytes = self.source_events.read_bytes()
        package_bytes = (self.root / self.package_path).read_bytes()
        evidence_bytes = self.evidence_path.read_bytes()
        self.begin()
        prefix = self.rp.events_path.read_bytes()
        self.rp.stop('fixture-stop')
        self.assertTrue(self.rp.events_path.read_bytes().startswith(prefix))
        self.assertEqual(self.source_events.read_bytes(), source_bytes)
        self.assertEqual((self.root / self.package_path).read_bytes(), package_bytes)
        self.assertEqual(self.evidence_path.read_bytes(), evidence_bytes)
        self.rp._assert_source()
        # Preservation is enforced on later operations, not merely observed once.
        self.evidence_path.write_text('{"tampered":true}')
        with self.assertRaisesRegex(CogitoError, 'evidence differs'):
            self.rp._assert_source()

    def test_protected_product_in_runtime_drafts_is_not_excluded(self):
        path = '.cogito/replans/RP-001/drafts/product.md'
        self.write(path, 'draft-path planning baseline\n')
        self.package['approved_paths'].append(path)
        self.package['slices'][0]['worker']['allowed_paths'].append(path)
        self.package['execution_dag']['tasks'][0]['paths'].append(path)
        self.package['source_registry'].append(self.document(path, registry=True))
        self.publish_package()
        self.git('add', '-f', path)
        self.git('commit', '-qm', 'fixture protected source in runtime directory')
        self.write(path, 'authorized draft-path product\n')
        self.stop()
        runtime = self.rp._runtime()
        self.assertIn(path, runtime.protected)
        self.assertIsNone(runtime.role(path))
        self.write(path, 'post-stop drift in draft path\n')
        with self.assertRaisesRegex(CogitoError, 'delivery content drifted'):
            self.rp._assert_source()

    def test_ignored_untracked_or_removed_from_index_source_refuses_stop(self):
        for staged_deletion in (False, True):
            with self.subTest(staged_deletion=staged_deletion):
                path = '.cogito/replans/RP-001/drafts/ignored-product.md'
                self.write(path, 'planning baseline\n')
                if staged_deletion:
                    self.git('add', '-f', path)
                    self.git('commit', '-qm', 'track ignored source')
                    self.git('rm', '--cached', path)
                if path not in self.package['approved_paths']:
                    self.package['approved_paths'].append(path)
                    self.package['slices'][0]['worker']['allowed_paths'].append(path)
                    self.package['execution_dag']['tasks'][0]['paths'].append(path)
                    self.package['source_registry'].append(self.document(path, registry=True))
                    self.publish_package()
                self.write(path, 'authorized but absent from Git snapshot\n')
                self.begin()
                with self.assertRaisesRegex(CogitoError, 'not covered by the Git snapshot'):
                    self.rp.stop('fixture-stop')
                self.assertEqual(self.rp.load()['state'], 'stopping')

    def test_ignored_source_created_after_saved_deletion_is_rejected(self):
        path = '.cogito/replans/RP-001/drafts/deleted-product.md'
        self.write(path, 'planning baseline\n')
        self.package['approved_paths'].append(path)
        self.package['slices'][0]['worker']['allowed_paths'].append(path)
        self.package['execution_dag']['tasks'][0]['paths'].append(path)
        self.package['source_registry'].append(self.document(path, registry=True))
        self.publish_package()
        (self.root/path).unlink()
        self.stop()
        self.write(path, 'untracked post-stop insertion\n')
        with self.assertRaisesRegex(CogitoError, 'not covered by the Git snapshot'):
            self.rp._assert_source()

    def test_skip_worktree_cannot_hide_product_source_drift(self):
        self.git('update-index', '--skip-worktree', self.product)
        self.write(self.product, 'invisible working-tree change\n')
        self.begin()
        with self.assertRaisesRegex(CogitoError, 'not covered by the Git snapshot'):
            self.rp.stop('fixture-stop')

    def test_skip_worktree_cannot_hide_post_stop_mode_change(self):
        self.git('update-index', '--skip-worktree', self.product)
        self.stop()
        (self.root/self.product).chmod(0o755)
        with self.assertRaisesRegex(CogitoError, 'not covered by the Git snapshot'):
            self.rp._assert_source()


class ReplanProductSourceFlowTests(GitTestCase):
    """Real source events, Task evidence and integration, without projection mocks."""
    executing = atomic_tests.AtomicVerificationTests.executing
    lease = staticmethod(atomic_tests.AtomicVerificationTests.lease)
    commit = staticmethod(atomic_tests.AtomicVerificationTests.commit)
    check = staticmethod(atomic_tests.AtomicVerificationTests.check)
    result = staticmethod(atomic_tests.AtomicVerificationTests.result)
    implement = atomic_tests.AtomicVerificationTests.implement

    def test_integrated_product_source_stops_replays_and_rejects_later_drift(self):
        def register_source(package):
            package['source_registry'] = [dict(path='src/a.txt',
                hash=hashlib.sha256(b'before\n').hexdigest(),
                disposition='updated', relevance='Approved product source')]
        repo, worker, source, package = self.executing(register_source)
        first, early = self.implement(source, worker)
        last, latest = self.implement(source, worker, 'b')
        source.transition('implementation-complete', {})
        source.complete_verification([latest])
        atomic_tests.AtomicVerificationTests.review(source, [first, last])
        git(repo, 'merge', '--no-ff', '-qm', 'integrate approved product',
            package['slices'][0]['worker']['branch'])
        source.complete_integration(git(repo, 'rev-parse', 'HEAD'), 'FS-1')
        original_package = (repo/source.load()['package_path']).read_bytes()
        original_evidence = Path(early['evidence_path']).read_bytes()
        original_events = source.events_path.read_bytes()
        rp = ReplanStore(repo, 'RP-product')
        rp.begin(source.run_id, 'DEV-product-next', 'New requested capability', 'begin')
        stopped = rp.stop('stop')
        self.assertEqual(stopped['state'], 'analyzing')
        rp._assert_source()
        self.assertEqual(git(repo, 'show', stopped['snapshot']['delivery']['content_tree'] + ':src/a.txt'), 'after')
        rp_events = rp.events_path.read_bytes()
        rp.stop('stop')
        self.assertEqual(rp.events_path.read_bytes(), rp_events)
        self.assertTrue(source.events_path.read_bytes().startswith(original_events))
        self.assertEqual((repo/source.load()['package_path']).read_bytes(), original_package)
        self.assertEqual(Path(early['evidence_path']).read_bytes(), original_evidence)
        # Index-only drift cannot hide behind restored working file bytes.
        (repo/'src/a.txt').write_text('changed after stop\n')
        git(repo, 'add', 'src/a.txt')
        (repo/'src/a.txt').write_text('after\n')
        with self.assertRaisesRegex(CogitoError, 'delivery content drifted'):
            rp._assert_source()


if __name__ == '__main__':
    unittest.main()
