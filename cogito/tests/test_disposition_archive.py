"""Releasing stopped delivery dirt preserves a complete recoverable archive."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from cogito_common import CogitoError
from cogito_evidence_binding import capture_index_and_worktree_trees
from cogito_disposition_archive import pin_snapshot, release_delivery


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.git('init','-q'); self.git('config','user.name','Test'); self.git('config','user.email','test@example.test')
        (self.root/'.gitignore').write_text('.cogito/\n')
        (self.root/'product').mkdir(); (self.root/'product/file').write_text('original')
        (self.root/'outside').write_text('outside')
        self.git('add','.'); self.git('commit','-qm','baseline')
    def git(self,*args):
        return subprocess.run(['git','-C',str(self.root),*args],capture_output=True,check=True).stdout.decode().strip()
    def saved(self):
        index,tree=capture_index_and_worktree_trees(self.root)
        return dict(delivery=dict(head=self.git('rev-parse','HEAD'),index_tree=index,content_tree=tree),
                    scope=dict(paths=['product']),worktrees={})
    def test_staging_worktree_and_new_file_are_archived_separately(self):
        (self.root/'product/file').write_text('staged'); self.git('add','product/file')
        (self.root/'product/file').write_text('working')
        (self.root/'product/new').write_text('new')
        (self.root/'outside').write_text('user edit')
        saved=self.saved(); manifest=pin_snapshot(self.root,'DP-test',saved)
        receipt=release_delivery(self.root,'DP-test',saved)
        self.assertTrue(receipt['completed'])
        self.assertEqual((self.root/'product/file').read_text(),'original')
        self.assertFalse((self.root/'product/new').exists())
        self.assertEqual((self.root/'outside').read_text(),'user edit')
        self.assertEqual(self.git('rev-parse','HEAD'),saved['delivery']['head'])
        refs={r['ref'].rsplit('/',1)[1]:r['ref'] for r in manifest['refs']}
        self.assertEqual(self.git('show',refs['index']+':product/file'),'staged')
        self.assertEqual(self.git('show',refs['content']+':product/file'),'working')
        self.assertEqual(self.git('show',refs['content']+':product/new'),'new')
        self.assertEqual(release_delivery(self.root,'DP-test',saved),receipt)
    def test_multiple_snapshot_versions_in_same_disposition(self):
        (self.root/'product/file').write_text('first'); first=self.saved()
        one=pin_snapshot(self.root,'DP-test',first)
        release_delivery(self.root,'DP-test',first)
        (self.root/'product/file').write_text('second'); second=self.saved()
        two=pin_snapshot(self.root,'DP-test',second)
        self.assertNotEqual(one['snapshot_hash'],two['snapshot_hash'])
        self.assertEqual(pin_snapshot(self.root,'DP-test',first),one)
        release_delivery(self.root,'DP-test',second)
        self.assertEqual((self.root/'product/file').read_text(),'original')

    def test_graph_cancellation_update_survives_release(self):
        graph=self.root/'docs/cogito/project-graph.json'; graph.parent.mkdir(parents=True)
        graph.write_text('active'); self.git('add','.'); self.git('commit','-qm','graph')
        (self.root/'product/file').write_text('saved'); saved=self.saved()
        graph.write_text('cancelled')
        release_delivery(self.root,'DP-test',saved)
        self.assertEqual(graph.read_text(),'cancelled')

    def test_drift_refused_without_overwriting(self):
        (self.root/'product/file').write_text('saved'); saved=self.saved()
        pin_snapshot(self.root,'DP-test',saved)
        (self.root/'product/file').write_text('later')
        with self.assertRaisesRegex(CogitoError,'changed'): release_delivery(self.root,'DP-test',saved)
        self.assertEqual((self.root/'product/file').read_text(),'later')
    def test_symlink_deletion_and_literal_names(self):
        (self.root/'product/file').unlink()
        (self.root/'product/:(glob)*').symlink_to('../outside')
        saved=self.saved(); release_delivery(self.root,'DP-test',saved)
        self.assertEqual((self.root/'product/file').read_text(),'original')
        self.assertFalse((self.root/'product/:(glob)*').is_symlink())
        self.assertEqual((self.root/'outside').read_text(),'outside')
    def test_replay_after_worktree_written_but_index_not_updated(self):
        (self.root/'product/file').write_text('saved'); self.git('add','product/file'); saved=self.saved()
        import cogito_disposition_archive as archive
        original=archive._git
        def fail(root,*args,**kwargs):
            if args[0]=='update-index': raise CogitoError('simulated interruption')
            return original(root,*args,**kwargs)
        with patch.object(archive,'_git',side_effect=fail):
            with self.assertRaisesRegex(CogitoError,'interruption'): release_delivery(self.root,'DP-test',saved)
        self.assertTrue(release_delivery(self.root,'DP-test',saved)['completed'])
        self.assertEqual(self.git('status','--porcelain'),'')
    def test_completed_release_does_not_overwrite_new_work(self):
        (self.root/'product/file').write_text('saved'); saved=self.saved()
        release_delivery(self.root,'DP-test',saved)
        (self.root/'product/file').write_text('new owner')
        with self.assertRaisesRegex(CogitoError,'changed'): release_delivery(self.root,'DP-test',saved)
        self.assertEqual((self.root/'product/file').read_text(),'new owner')

if __name__=='__main__': unittest.main()
