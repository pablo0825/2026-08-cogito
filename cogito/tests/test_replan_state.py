import tempfile
import unittest
from pathlib import Path
from cogito_common import CogitoError
from cogito_events import append_event, read_events
from cogito_replan_state import project_replan
from cogito_replan_lock import check_run_fence, project_lock

class ReplanStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / '.cogito/replans/RP-1/events.jsonl'
        self.payload = dict(replan_id='RP-1', source_run_id='DEV-old', successor_run_id='DEV-new', source_package_hash='a'*64, reason='API change')
        self.add('replan-created', self.payload)

    def add(self, kind, payload):
        return append_event(self.path, dict(type=kind,payload=payload))

    def test_fence_prevents_all_source_mutations_and_successor_execution(self):
        for run, operation in [('DEV-old','resume_gate'), ('DEV-old','record'), ('DEV-new','start_gate'), ('DEV-new','approve_package'), ('DEV-other','approve_package')]:
            with self.subTest(run=run, operation=operation), self.assertRaises(CogitoError):
                check_run_fence(self.root, run, operation)
        check_run_fence(self.root,'DEV-new','prepare_package')
        check_run_fence(self.root,'DEV-new','preparation-transition')

    def test_illegal_stage_and_stale_review_rejected(self):
        base=read_events(self.path)
        with self.assertRaises(CogitoError):
            project_replan([*base, {'type':'handoff-completed','payload':{}}])
        self.add('replan-stopped',{'snapshot':{}})
        self.add('proposal-prepared',{'proposal':{},'proposal_hash':'first'})
        with self.assertRaises(CogitoError):
            project_replan([*read_events(self.path),{'type':'proposal-reviewed','payload':{'proposal_hash':'stale'}}])

    def test_revision_invalidates_review_without_losing_history(self):
        self.add('replan-stopped',{'snapshot':{}})
        self.add('proposal-prepared',{'proposal':{'version':1},'proposal_hash':'first'})
        self.add('proposal-reviewed',{'proposal_hash':'first','reviewer':'R'})
        self.add('proposal-prepared',{'proposal':{'version':2},'proposal_hash':'second'})
        state=project_replan(read_events(self.path))
        self.assertEqual(state['state'],'reviewing')
        self.assertIsNone(state['review'])
        self.assertEqual(len(read_events(self.path)),5)

    def test_reentrant_project_lock(self):
        with project_lock(self.root):
            with project_lock(self.root):
                check_run_fence(self.root,'DEV-new','create')

if __name__ == '__main__': unittest.main()
