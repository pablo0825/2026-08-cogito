"""Scheduling and lease acceptance agree on task dependency readiness."""

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_projection import _apply_task_update
from cogito_scheduler import ready_tasks
from cogito_task_rules import dependency_satisfied, effective_slice_id, is_active_task


class TaskReadinessTests(unittest.TestCase):
    def test_scheduler_and_lease_accept_the_same_dependency_status_matrix(self):
        statuses = ("pending", "leased", "running", "complete", "verified", "reviewed", "integrated", "blocked", "unknown")
        for same_slice in (False, True):
            for status in statuses:
                with self.subTest(same_slice=same_slice, status=status):
                    predecessor = {"id": "P", "slice_id": "FS-A", "status": status}
                    task = {"id": "T", "slice_id": "FS-A" if same_slice else "FS-B", "status": "pending", "depends_on": ["P"]}
                    expected = status in ({"complete", "verified", "reviewed", "integrated"} if same_slice else {"integrated"})
                    before = copy.deepcopy((predecessor, task))
                    self.assertEqual(dependency_satisfied(predecessor, task), expected)
                    scheduled = ready_tasks([predecessor, task], [{"from": "P", "to": "T"}])
                    self.assertEqual("T" in [item["id"] for item in scheduled], expected)
                    self.assertEqual((predecessor, task), before)
                    state = {"tasks": {"P": copy.deepcopy(predecessor), "T": copy.deepcopy(task)}, "max_workers": 3}
                    update = {"task_id": "T", "status": "leased", "agent_id": "worker"}
                    if expected:
                        _apply_task_update(state, update)
                        self.assertEqual(state["tasks"]["T"]["status"], "leased")
                    else:
                        with self.assertRaises(CogitoError):
                            _apply_task_update(state, update)

    def test_missing_none_and_explicit_mini_slice_have_identical_readiness(self):
        variants = ({}, {"slice_id": None}, {"slice_id": ""}, {"slice_id": "mini-package"})
        for source in variants:
            for target in variants:
                with self.subTest(source=source, target=target):
                    predecessor = {**source, "id": "P", "status": "complete"}
                    task = {**target, "id": "T", "status": "pending", "depends_on": ["P"]}
                    self.assertEqual(effective_slice_id(task), "mini-package")
                    self.assertTrue(dependency_satisfied(predecessor, task))
                    self.assertEqual([item["id"] for item in ready_tasks([predecessor, task], [["P", "T"]])], ["T"])
                    state = {"tasks": {"P": predecessor, "T": task}, "max_workers": 1}
                    _apply_task_update(state, {"task_id": "T", "status": "leased", "agent_id": "worker"})
                    self.assertEqual(state["tasks"]["T"]["status"], "leased")

    def test_active_slice_occupancy_and_worker_capacity_are_preserved(self):
        for active_status in ("leased", "running"):
            with self.subTest(status=active_status):
                tasks = [
                    {"id": "active", "slice_id": "FS-A", "status": active_status},
                    {"id": "same", "slice_id": "FS-A", "status": "pending"},
                    {"id": "other", "slice_id": "FS-B", "status": "pending"},
                ]
                self.assertTrue(is_active_task(tasks[0]))
                self.assertEqual(ready_tasks(tasks, [], 1), [])
                self.assertEqual([item["id"] for item in ready_tasks(tasks, [], 2)], ["other"])
                for target, capacity, error in (("same", 2, "one active worker"), ("other", 1, "worker lease limit")):
                    state = {"tasks": {task["id"]: copy.deepcopy(task) for task in tasks}, "max_workers": capacity}
                    with self.assertRaisesRegex(CogitoError, error):
                        _apply_task_update(state, {"task_id": target, "status": "leased", "agent_id": "worker"})
        for status in ("pending", "complete", "verified", "reviewed", "integrated", "blocked"):
            self.assertFalse(is_active_task({"status": status}))


if __name__ == "__main__":
    unittest.main()
