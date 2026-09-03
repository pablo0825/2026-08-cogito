"""Public CLI JSON-file decoding failures stay inside the structured error contract."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, SCRIPTS, git, init_repo, package
from cogito_common import CogitoError, load_json


class JsonFileEncodingTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        init_repo(self.repo)
        (self.repo / '.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n', encoding='utf-8')
        git(self.repo, 'add', '.')
        git(self.repo, 'commit', '-qm', 'baseline')
        self.run_id = 'MNT-json-encoding'
        initialized = self.gate('init', '--no-stage-commits', '--run-id', self.run_id, '--kind', 'maintenance')
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.events = self.repo / '.cogito/runs' / self.run_id / 'events.jsonl'
        draft = package('maintenance')
        draft.update({
            'run_id': self.run_id, 'baseline_commit': git(self.repo, 'rev-parse', 'HEAD'),
            'stop_conditions': ['核准範圍發生變更'],
        })
        draft['checks'][0]['argv'] = [sys.executable, '-I', '-c', "print('驗證成功')"]
        self.draft = draft
        self.package_path = self.write_json('有效套件.json', draft)
        self.evidence_dir = self.root / 'evidence'

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def gate(self, *arguments):
        return subprocess.run(
            [sys.executable, '-B', str(SCRIPTS / 'cogito_gate.py'), '--repo', str(self.repo),
             *map(str, arguments)], capture_output=True, text=True, timeout=20,
        )

    def runner(self, package_path, *amendments):
        arguments = [sys.executable, '-B', str(SCRIPTS / 'cogito_runner.py'), 'run-check',
                     '--package', str(package_path), '--check-id', 'C-1',
                     '--worktree', str(self.repo), '--evidence-dir', str(self.evidence_dir)]
        for amendment in amendments:
            arguments.extend(['--amendment', str(amendment)])
        return subprocess.run(arguments, capture_output=True, text=True, timeout=20)

    def assert_json_error(self, result, path, *, object_error=False):
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('Traceback', result.stderr)
        error = json.loads(result.stderr)
        self.assertIs(error['ok'], False)
        self.assertTrue(error['error'])
        # A path-specific loader diagnostic proves argparse and state guards
        # did not reject the command before the input file was examined.
        self.assertIn(str(path), error['error'])
        self.assertIn('object' if object_error else 'cannot read', error['error'])

    def bad_files(self):
        invalid = self.root / 'invalid-utf8.json'
        invalid.write_bytes(b'{"reason":"\xff"}')
        utf16 = self.root / 'utf16.json'
        utf16.write_bytes(json.dumps({'reason': '需修正'}, ensure_ascii=False).encode('utf-16'))
        return [('invalid-utf8', invalid), ('utf16', utf16)]

    def test_gate_file_entrypoints_reject_bad_encoding_without_events_or_index_changes(self):
        events_before = self.events.read_bytes()
        index_before = (self.repo / '.git/index').read_bytes()
        for encoding, path in self.bad_files():
            for command, flag in (
                ('prepare-package', '--package'), ('approve', '--package'),
                ('agent-result', '--input'), ('amend', '--amendment'),
                ('verify', '--evidence'), ('post-verify', '--evidence'),
            ):
                with self.subTest(encoding=encoding, command=command):
                    result = self.gate(command, '--run-id', self.run_id, flag, path,
                                       '--action-id', f'{command}-{encoding}')
                    self.assert_json_error(result, path)
                    self.assertEqual(self.events.read_bytes(), events_before)
                    self.assertEqual((self.repo / '.git/index').read_bytes(), index_before)

    def test_runner_package_and_amendment_reject_bad_encoding_without_evidence(self):
        for encoding, path in self.bad_files():
            for field in ('package', 'amendment'):
                with self.subTest(encoding=encoding, field=field):
                    result = self.runner(path) if field == 'package' else self.runner(self.package_path, path)
                    self.assert_json_error(result, path)
                    self.assertFalse(self.evidence_dir.exists())

    def test_gate_existing_malformed_nonobject_and_missing_file_errors_are_preserved(self):
        malformed = self.root / 'malformed.json'
        malformed.write_text('{', encoding='utf-8')
        array = self.write_json('array.json', [])
        missing = self.root / 'missing.json'
        before = self.events.read_bytes()
        for path in (malformed, array, missing):
            with self.subTest(path=path.name):
                result = self.gate('prepare-package', '--run-id', self.run_id, '--package', path,
                                   '--action-id', path.stem)
                self.assert_json_error(result, path, object_error=path == array)
                self.assertEqual(self.events.read_bytes(), before)

    def test_runner_existing_malformed_nonobject_and_missing_file_errors_are_preserved(self):
        malformed = self.root / 'malformed.json'
        malformed.write_text('{', encoding='utf-8')
        array = self.write_json('array.json', [])
        missing = self.root / 'missing.json'
        for path in (malformed, array, missing):
            for field in ('package', 'amendment'):
                with self.subTest(path=path.name, field=field):
                    result = self.runner(path) if field == 'package' else self.runner(self.package_path, path)
                    self.assert_json_error(result, path, object_error=path == array)
                    self.assertFalse(self.evidence_dir.exists())

    def test_gate_valid_utf8_chinese_package_can_be_prepared_and_approved(self):
        for command in ('prepare-package', 'approve'):
            result = self.gate(command, '--run-id', self.run_id, '--package', self.package_path,
                               '--action-id', command)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIs(json.loads(result.stdout)['ok'], True)
        approved_path = self.repo / 'docs/cogito/packages' / f'{self.run_id}.json'
        approved = json.loads(approved_path.read_text(encoding='utf-8'))
        self.assertEqual(approved['stop_conditions'], ['核准範圍發生變更'])

    def test_runner_valid_utf8_chinese_package_and_amendment_complete_check(self):
        amendment = self.write_json('修正.json', {
            'id': 'TA-1', 'reason': '補上說明', 'path_fixes': ['src'],
        })
        result = self.runner(self.package_path, amendment)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertIs(output['ok'], True)
        evidence = json.loads(Path(output['evidence']).read_text(encoding='utf-8'))
        self.assertEqual(evidence['stdout'], '驗證成功\n')
        self.assertIs(evidence['passed'], True)

    def test_common_loader_rejects_invalid_encoding_and_preserves_valid_unicode(self):
        for encoding, path in self.bad_files():
            with self.subTest(encoding=encoding):
                before = path.read_bytes()
                with self.assertRaisesRegex(CogitoError, 'cannot read valid JSON'):
                    load_json(path)
                self.assertEqual(path.read_bytes(), before)
        valid = self.write_json('中文資料.json', {'reason': '保留中文'})
        self.assertEqual(load_json(valid), {'reason': '保留中文'})

    def test_status_rejects_invalid_event_encoding_without_changing_authoritative_bytes(self):
        original = self.events.read_bytes()
        cache = self.events.with_name('state.json')
        cache_before = cache.read_bytes()
        for encoding, path in self.bad_files():
            with self.subTest(encoding=encoding):
                damaged = original + path.read_bytes() + b'\n'
                self.events.write_bytes(damaged)
                result = self.gate('status', '--run-id', self.run_id)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertNotIn('Traceback', result.stderr)
                error = json.loads(result.stderr)
                self.assertIs(error['ok'], False)
                self.assertIn('cannot read event log', error['error'])
                self.assertEqual(self.events.read_bytes(), damaged)
                self.assertEqual(cache.read_bytes(), cache_before)

    def test_status_rebuilds_invalid_encoding_cache_from_unchanged_events(self):
        expected = json.loads(self.gate('status', '--run-id', self.run_id).stdout)['data']
        original_events = self.events.read_bytes()
        cache = self.events.with_name('state.json')
        for encoding, path in self.bad_files():
            with self.subTest(encoding=encoding):
                cache.write_bytes(path.read_bytes())
                result = self.gate('status', '--run-id', self.run_id)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)['data'], expected)
                self.assertEqual(load_json(cache), expected)
                self.assertEqual(self.events.read_bytes(), original_events)
