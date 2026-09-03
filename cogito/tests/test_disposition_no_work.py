"""Cancellation before implementation can close without inventing repair work."""
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_run_store import RunStore


class NoWorkDispositionTests(GitTestCase):
    def test_unstarted_cancel_closes_after_review_and_human_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            init_repo(repo)
            (repo/'.gitignore').write_text('.cogito/\ndocs/cogito/packages/\n')
            (repo/'note.txt').write_text('original\n')
            git(repo,'add','.');git(repo,'commit','-qm','Baseline')
            draft = package('maintenance')
            draft.update(baseline_commit=git(repo,'rev-parse','HEAD'),approved_paths=['note.txt'],
                execution_dag={'tasks':[{'id':'T-1','paths':['note.txt']}],'edges':[]})
            source = RunStore(repo,draft['run_id'])
            source.create('maintenance');source.prepare_package(draft);source.approve_package(draft)
            disposition = DispositionStore(repo,'DP-no-work')
            disposition.begin(source.run_id,'User cancels before implementation','begin')
            saved = disposition.stop('stop')['snapshot']['delivery']
            proposal = dict(action='retain',author_id='analyst',summary='No implementation or product changes to dispose of',
                impact=dict(paths=['note.txt'],slice_ids=[],reason='Cancelled before starting'),
                acceptance='User confirms original baseline remains',
                no_change_evidence=dict(no_work=True,head=saved['head'],content_tree=saved['content_tree'],evidence_paths=[]))
            state=disposition.propose(proposal,'propose')
            disposition.review(dict(reviewer_id='reviewer',proposal_hash=state['proposal_hash'],
                findings=[],assessment='No commits, implementation results or changed product trees'),'review')
            disposition.approve(state['proposal_hash'],True,'approve')
            (repo/'note.txt').write_text('unrecorded product change')
            before=disposition.events_path.read_bytes()
            with self.assertRaises(CogitoError): disposition.complete('complete',human_accepted=True)
            self.assertEqual(disposition.events_path.read_bytes(),before)
            (repo/'note.txt').write_text('original\n')
            disposition.complete('complete',human_accepted=True)
            self.assertEqual(disposition.load()['state'],'completed')
            self.assertEqual(source.load()['state'],'cancelled')
