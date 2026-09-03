"""Withdraw an in-place requirements revision using the original saved files."""
import unittest

import test_planning_rounds as support
from cogito_common import CogitoError
from cogito_contracts import package_hash


class PlanningWithdrawalTests(unittest.TestCase):
    def test_unfinished_requirements_cannot_downgrade_and_same_level_can_restart(self):
        f = support.PlanningRoundTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.begin()
        document = f.new['shared_understanding']
        f.store.transition('shared-understanding-ready', {
            'planning_round': 2, 'shared_understanding_hash': document['hash'],
            'document': document}, 'ready-for-downgrade-probe')
        f.store.transition('shared-understanding-confirmed', {
            'planning_round': 2, 'shared_understanding_hash': document['hash'],
            'confirmed': True}, 'confirm-for-downgrade-probe')
        before = f.store.events_path.read_bytes()
        for level in ('boundary', 'plan'):
            request = {**f.request(level), 'round': 2}
            with self.assertRaises(CogitoError):
                f.store.planning_begin(request, 'downgrade-' + level)
            self.assertEqual(f.store.events_path.read_bytes(), before)
        f.store.planning_begin({**f.request(), 'round': 2}, 'restart-requirements')
        self.assertEqual(f.store.load()['planning']['round'], 3)
        self.assertEqual(f.store.load()['state'], 'preparing')

    def test_unfinished_boundary_cannot_downgrade_to_plan(self):
        f = support.PlanningRoundTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        f.store.planning_begin(f.request('boundary'), 'start-boundary-round')
        before = f.store.events_path.read_bytes()
        with self.assertRaises(CogitoError):
            f.store.planning_begin({**f.request('plan'), 'round': 2}, 'downgrade-boundary')
        self.assertEqual(f.store.events_path.read_bytes(), before)
        self.assertEqual(f.store.load()['state'], 'boundary-analysis')

    def test_same_path_shared_understanding_can_restore_original_and_withdraw(self):
        f = support.PlanningRoundTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        old_path = f.repo / f.old['shared_understanding']['path']
        original = old_path.read_bytes()
        revised = (f.repo / f.new['shared_understanding']['path']).read_bytes()
        f.begin()
        old_path.write_bytes(revised)
        f.new['shared_understanding']['path'] = f.old['shared_understanding']['path']
        f.prepare_revision()
        preserved = f.store.events_path.read_bytes()
        request = {'round': 2, 'authorized': True, 'reason': 'User explicitly chose the original scope.'}
        with self.assertRaises(CogitoError):
            f.store.planning_withdraw(request, 'withdraw-unrestored-files')
        old_path.write_bytes(original)
        f.store.planning_withdraw(request, 'withdraw-restored-files')
        f.store.state_path.unlink()
        self.assertEqual(f.store.load()['state'], 'awaiting-package-approval')
        self.assertEqual(f.store.load()['candidate_package_hash'], package_hash(f.old))
        self.assertTrue(f.store.events_path.read_bytes().startswith(preserved))
        f.store.approve_package(f.old, 'approve-original-after-withdraw')
        f.store.start_gate('start-original-after-withdraw')
        self.assertEqual(len(f.store.load()['tasks']), 3)


if __name__ == '__main__':
    unittest.main()
