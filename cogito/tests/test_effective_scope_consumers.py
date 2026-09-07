"""Downstream scope fences retain paths granted by Technical Amendments."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cogito_test_support import package
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_disposition_lock import check_disposition_fence
from cogito_replan_toolchain import _assert_scope
from cogito_replan_toolchain_rules import TOOL_ROOT
from cogito_result_contract import validate_result
from cogito_run_queries import build_completion_report
from test_finalization_rules import context


class EffectiveScopeConsumerTests(unittest.TestCase):
    def test_path_summary_shape_and_report_do_not_fabricate_completion_commit(self):
        result = deepcopy(context().result)
        result['amendments'] = [{'id': 'TA-path', 'proposal_hash': 'a' * 64}]
        validate_result(result)
        report = build_completion_report(result['run_id'], 'b' * 40, result)
        self.assertEqual(report['amendments'], result['amendments'])
        for extra in ({'commit_id': 'b' * 40}, {'content_tree': 'c' * 40}, {'proposal_hash': 'bad'}):
            with self.subTest(extra=extra):
                changed = deepcopy(result)
                changed['amendments'][0].update(extra)
                with self.assertRaises(CogitoError):
                    validate_result(changed)

    def test_pending_disposition_blocks_new_and_recorded_path_additions(self):
        original = package('feature')
        amendment = {'path_additions': [{'task_id': 'T-1', 'paths': ['mappers/value.py']}]}
        pending = dict(
            disposition_id='DP-other', state='analyzing', source_run_id='DEV-other',
            scope=dict(paths=['mappers/value.py'], slice_ids=[], reason='Unresolved shared data'),
        )
        with tempfile.TemporaryDirectory(prefix='cogito-amendment-fence-') as temporary:
            events_path = Path(temporary) / 'events.jsonl'
            events_path.touch()
            for recorded in (False, True):
                state = dict(
                    package_path='docs/cogito/packages/DEV-scope.json',
                    amendments=[amendment] if recorded else [],
                )
                store = SimpleNamespace(
                    root=Path(temporary), run_id='DEV-scope', events_path=events_path,
                    approved_package=lambda: original,
                    _events=SimpleNamespace(project=lambda: state),
                )
                with self.subTest(recorded=recorded), patch(
                    'cogito_disposition_scope.dispositions', return_value=[pending],
                ), self.assertRaisesRegex(CogitoError, 'unresolved disposition'):
                    check_disposition_fence(
                        store, 'submit_agent_result' if recorded else 'add_amendment',
                        () if recorded else (amendment,),
                    )

    def test_toolchain_cannot_adopt_newly_authorized_product_path(self):
        original = package('feature')
        effective = deepcopy(original)
        effective['approved_paths'].append(TOOL_ROOT + '/VERSION')
        source = SimpleNamespace(
            approved_package=lambda: original, effective_package=lambda: effective,
        )
        store = SimpleNamespace(
            source=lambda: source, load=lambda: {'snapshot': {'worktrees': {}}},
        )
        with self.assertRaisesRegex(CogitoError, 'protected product or contract scope'):
            _assert_scope(store, None)

    def test_disposition_snapshot_fences_amended_paths(self):
        original = package('feature')
        effective = deepcopy(original)
        effective['approved_paths'].append('mappers/value.py')
        current = dict(
            state='blocked', last_event_hash='a' * 64, tasks={},
            package_hash='b' * 64, effective_contract_hash='c' * 64,
        )
        source = SimpleNamespace(
            approved_package=lambda: original, effective_package=lambda: effective,
            load=lambda: current, _git=Mock(return_value='d' * 40),
        )
        with tempfile.TemporaryDirectory(prefix='cogito-effective-scope-') as temporary:
            store = DispositionStore(Path(temporary), 'DP-scope')
            state = dict(run_ids=['DEV-scope'], source_run_id='DEV-scope', reason='Hold product')
            with patch.object(store, 'load', return_value=state), patch.object(
                store, 'source', return_value=source,
            ), patch('cogito_disposition_store.RunStore', return_value=source), patch(
                'cogito_disposition_store.capture_index_and_worktree_trees',
                return_value=('e' * 40, 'f' * 40),
            ), patch('cogito_disposition_store.capture_runtime', return_value={}):
                saved = store._capture()
        self.assertIn('mappers/value.py', saved['scope']['paths'])
        self.assertEqual(saved['package_hash'], current['package_hash'])
        self.assertEqual(saved['effective_contract_hash'], current['effective_contract_hash'])


if __name__ == '__main__':
    unittest.main()
