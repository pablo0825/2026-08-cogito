"""Reject incompatible imports before approving an atomic successor."""

import copy

from cogito_test_support import GitTestCase
from cogito_common import CogitoError
from cogito_run_store import RunStore
from cogito_replan_store import ReplanStore
import test_atomic_task_execution as execution


class AtomicReplanTests(GitTestCase):
    executing = execution.AtomicTaskTests.executing
    lease = staticmethod(execution.AtomicTaskTests.lease)
    commit = staticmethod(execution.AtomicTaskTests.commit)
    check = staticmethod(execution.AtomicTaskTests.check)
    result = staticmethod(execution.AtomicTaskTests.result)
    implement = execution.AtomicTaskTests.implement

    def test_carryover_is_rejected_before_approval_and_omit_preserves_source(self):
        repo, worker, source, original = self.executing()
        self.implement(source, worker)
        rp = ReplanStore(repo, 'RP-atomic')
        rp.begin(source.run_id, 'DEV-atomic-next', 'changed public contract', 'begin')
        rp.stop('stop')
        preserved = source.events_path.read_bytes()
        draft = copy.deepcopy(original)
        draft.update(run_id='DEV-atomic-next', kind='change')
        for sl in draft['slices']:
            sl.update(id='FS-next', type='change', lineage=['FS-1'])
            sl['worker'].update(branch='codex/next', worktree='.cogito/worktrees/next')
        for task in draft['execution_dag']['tasks']:
            task['slice_id'] = 'FS-next'
        successor = RunStore(repo, draft['run_id'])
        successor.create('change')
        successor.transition('shared-understanding-ready', {'shared_understanding_hash': draft['shared_understanding']['hash']})
        successor.transition('shared-understanding-confirmed', {'confirmed': True})
        successor.transition('boundary-complete', draft['boundary'])
        successor.prepare_package(draft)
        proposal = {
            'author_id': 'planner', 'package': draft,
            'differences': {key: 'Reviewed ' + key for key in
                            ('requirements', 'api', 'boundary', 'acceptance', 'cost', 'revalidation')},
            'work': [dict(source_task_id=task, target_task_id=task, disposition='adapt',
                          validation='rerun', reason='adapt changed contract')
                     for task in source.load()['tasks']],
        }
        with self.assertRaisesRegex(CogitoError, 'fresh Tasks'):
            rp.propose(proposal, 'propose')
        self.assertEqual(rp.load()['state'], 'analyzing')
        self.assertEqual(successor.load()['state'], 'awaiting-package-approval')
        for row in proposal['work']:
            row.update(disposition='omit', target_task_id=None, reason='preserve source; implement successor separately')
        rp.propose(proposal, 'propose')
        self.assertEqual(rp.load()['state'], 'reviewing')
        self.assertEqual(source.events_path.read_bytes(), preserved)
        self.assertEqual((worker / 'src/a.txt').read_text(), 'after\n')
