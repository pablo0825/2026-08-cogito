"""Unresolved product impact fences dependent work, preserving unrelated work."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from cogito_common import CogitoError, atomic_write_json
from cogito_contracts import package_hash
from cogito_disposition_scope import check_package, paths_overlap


def pending():
    return dict(disposition_id='DP-test',state='analyzing',source_run_id='DEV-source',
                scope=dict(paths=['src/export/**'],slice_ids=['export'],reason='Removal awaiting approval'))


class DispositionScopeTests(unittest.TestCase):
    def test_glob_intersections_are_conservative(self):
        for a,b in [('src/*.py','src/export*'),('src/export','src/export/x.py'),('**/*.py','src/**')]:
            self.assertTrue(paths_overlap(a,b))
        self.assertFalse(paths_overlap('src/login/**','src/export/**'))

    def test_unrelated_work_passes_but_transitive_dependency_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            atomic_write_json(root/'docs/cogito/project-graph.json',dict(slices={},dependencies=[
                {'from':'export','to':'reports'},{'from':'reports','to':'daily'}]))
            with patch('cogito_disposition_scope.dispositions',return_value=[pending()]):
                check_package(root,dict(approved_paths=['src/login/**'],slices=[{'id':'login'}]),'DEV-login')
                with self.assertRaisesRegex(CogitoError,'depends'):
                    check_package(root,dict(approved_paths=['src/daily/**'],slices=[{'id':'daily'}]),'DEV-daily')

    def test_exact_approved_followup_exemption_does_not_release_other_fences(self):
        package=dict(approved_paths=['src/export/**'],slices=[])
        state=pending(); state.update(state='executing',approval={'authorized':True},proposal={
            'followup_run_id':'DEV-fix','followup_package_hash':package_hash(package)})
        with patch('cogito_disposition_scope.dispositions',return_value=[state]):
            check_package('/tmp',package,'DEV-fix')
            with self.assertRaises(CogitoError): check_package('/tmp',{**package,'extra':True},'DEV-fix')
        other={**pending(),'disposition_id':'DP-other'}
        with patch('cogito_disposition_scope.dispositions',return_value=[state,other]):
            with self.assertRaisesRegex(CogitoError,'DP-other'): check_package('/tmp',package,'DEV-fix')

    def test_revision_cannot_silently_release_previous_impact(self):
        state=pending(); state['proposal_history']=[{'proposal':{'impact':dict(paths=['src/shared/**'],slice_ids=[],reason='Earlier work')}}]
        with patch('cogito_disposition_scope.dispositions',return_value=[state]):
            with self.assertRaises(CogitoError):
                check_package('/tmp',dict(approved_paths=['src/shared/util.py'],slices=[]),'DEV-shared')


if __name__ == '__main__': unittest.main()
