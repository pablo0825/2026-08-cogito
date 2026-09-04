"""Cancellation before implementation can close without inventing repair work."""
import tempfile
from pathlib import Path
from unittest import mock

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_disposition_store import DispositionStore
from cogito_events import read_events
from cogito_run_store import RunStore


class NoWorkDispositionTests(GitTestCase):
    def unignored_source(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        (repo/'note.txt').write_text('original\n')
        git(repo,'add','.');git(repo,'commit','-qm','Baseline')
        draft = package('maintenance')
        draft.update(baseline_commit=git(repo,'rev-parse','HEAD'),approved_paths=['note.txt'],
            execution_dag={'tasks':[{'id':'T-1','paths':['note.txt']}],'edges':[]})
        source = RunStore(repo,draft['run_id'])
        source.create('maintenance');source.prepare_package(draft);source.approve_package(draft)
        return repo, source

    def test_stop_validates_its_own_runtime_when_cogito_is_not_ignored(self):
        repo, source = self.unignored_source()
        disposition = DispositionStore(repo,'DP-unignored')
        disposition.begin(source.run_id,'User cancels before implementation','begin')
        emit = disposition._emit
        interrupted = False
        def fail_once(kind, *args, **kwargs):
            nonlocal interrupted
            if kind == 'disposition-stopped' and not interrupted:
                interrupted = True
                raise CogitoError('interrupted after Graph release')
            return emit(kind, *args, **kwargs)
        with mock.patch.object(disposition,'_emit',side_effect=fail_once):
            with self.assertRaisesRegex(CogitoError,'interrupted after Graph release'):
                disposition.stop('stop')
            refs = git(repo,'for-each-ref','--format=%(refname) %(objectname)',
                       'refs/cogito/dispositions/DP-unignored')
            graph = (repo/'docs/cogito/project-graph.json').read_bytes()
            state = disposition.stop('stop')
        self.assertEqual(state['state'],'analyzing')
        self.assertEqual(source.load()['state'],'cancelled')
        self.assertEqual(git(repo,'for-each-ref','--format=%(refname) %(objectname)',
                             'refs/cogito/dispositions/DP-unignored'),refs)
        self.assertEqual((repo/'docs/cogito/project-graph.json').read_bytes(),graph)
        self.assertEqual(len([e for e in read_events(source.events_path)
                              if e['type']=='cancel']),1)

    def test_stop_does_not_hide_unexpected_cogito_drift(self):
        repo, source = self.unignored_source()
        disposition = DispositionStore(repo,'DP-unexpected-runtime')
        disposition.begin(source.run_id,'User cancels before implementation','begin')
        emit = disposition._emit
        def inject(kind, *args, **kwargs):
            result = emit(kind, *args, **kwargs)
            if kind == 'disposition-stop-started':
                (disposition.directory/'unexpected.json').write_text('{}')
            return result
        with mock.patch.object(disposition,'_emit',side_effect=inject):
            with self.assertRaisesRegex(CogitoError,'saved product content changed'):
                disposition.stop('stop')
        self.assertEqual(disposition.load()['state'],'stopping')

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
