"""Task dependency additions must preserve the approved execution boundaries."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, hash_json
from cogito_contracts import materialize_contract, package_hash, validate_amendment, validate_package
from cogito_scheduler import edge_pair
from cogito_scheduler import ready_tasks
from cogito_run_store import RunStore
from test_runtime_contract import minimal_package
from test_v3_safety_regressions import package as mini_package


def task(task_id: str, dependencies: list[str], slice_id: str = "FS-001") -> dict:
    return {"id": task_id, "slice_id": slice_id, "paths": ["src"], "depends_on": dependencies}


def amendment(amendment_id: str, tasks: list[dict]) -> dict:
    return {"id": amendment_id, "reason": "repair a verification finding", "added_tasks": tasks}


class AmendmentDependencyTests(unittest.TestCase):
    def test_mini_tasks_share_one_logical_slice(self) -> None:
        package = mini_package("maintenance")
        for slice_id in (None, "mini-package"):
            with self.subTest(slice_id=slice_id):
                package["execution_dag"]["tasks"][0]["slice_id"] = slice_id
                validate_package(package)
        package["execution_dag"]["tasks"][0]["slice_id"] = "FS-other"
        with self.assertRaises(CogitoError):
            validate_package(package)
        self.assertEqual([item["id"] for item in ready_tasks(
            [{"id": "T-1", "status": "complete"}, task("T-2", ["T-1"], "mini-package")],
            [{"from": "T-1", "to": "T-2"}],
        )], ["T-2"])

    def test_gate_requires_cross_slice_predecessors_already_integrated(self) -> None:
        package = minimal_package()
        package["slices"].append({**copy.deepcopy(package["slices"][0]), "id": "FS-002"})
        package["execution_dag"]["tasks"].append(task("T-2", ["T-1"], "FS-002"))
        package["execution_dag"]["edges"] = [{"from": "T-1", "to": "T-2"}]
        changes = [amendment("TA-1", [task("T-3", ["T-1"], "FS-002")]),
                   amendment("TA-1", [task("T-3", ["T-4"], "FS-002"), task("T-4", [], "FS-001")])]
        with tempfile.TemporaryDirectory() as directory:
            store = RunStore(directory, package["run_id"])
            store.create("feature")
            before = store.events_path.read_bytes()
            for status in ("complete", "verified", "reviewed", "integrated"):
                snapshot = {"state": "verifying", "tasks": {
                    task["id"]: {**task, "status": status} for task in package["execution_dag"]["tasks"]}}
                for change in changes:
                    with self.subTest(status=status, change=change), \
                         mock.patch.object(store, "approved_package", return_value=package), \
                         mock.patch.object(store, "load", return_value=snapshot), \
                         mock.patch.object(store, "record") as record:
                        if status == "integrated" and change is changes[0]:
                            store.add_amendment(change)
                            record.assert_called_once()
                        else:
                            with self.assertRaisesRegex(CogitoError, "already be integrated"):
                                store.add_amendment(change)
                            record.assert_not_called()
                        self.assertEqual(store.events_path.read_bytes(), before)

    def test_package_edges_are_authoritative_and_depends_on_is_optional(self) -> None:
        for explicit in (False, True):
            with self.subTest(explicit_dependencies=explicit):
                package = minimal_package()
                package["execution_dag"]["tasks"].append(task("T-2", ["T-1"]))
                package["execution_dag"]["edges"] = [{"from": "T-1", "to": "T-2"}]
                if explicit:
                    package["execution_dag"]["tasks"][0]["depends_on"] = []
                else:
                    del package["execution_dag"]["tasks"][1]["depends_on"]
                before = copy.deepcopy(package)
                digest = package_hash(package)
                validate_package(package)
                effective = materialize_contract(package, [])
                self.assertEqual(effective["execution_dag"]["edges"], before["execution_dag"]["edges"])
                self.assertEqual(package, before)
                self.assertEqual(package_hash(package), digest)
                self.assertEqual(effective["effective_contract_hash"], digest)

    def test_package_rejects_depends_on_that_disagrees_with_incoming_edges(self) -> None:
        for dependencies in ([], ["missing"], ["T-2"], ["T-1", "missing"]):
            with self.subTest(dependencies=dependencies):
                package = minimal_package()
                package["execution_dag"]["tasks"].append(task("T-2", dependencies))
                package["execution_dag"]["edges"] = [{"from": "T-1", "to": "T-2"}]
                before = copy.deepcopy(package)
                with self.assertRaises(CogitoError):
                    validate_package(package)
                self.assertEqual(package, before)

    def test_amendment_rejects_unknown_self_and_same_batch_cycle_dependencies(self) -> None:
        for name, added in (
            ("unknown", [task("T-2", ["missing"])]),
            ("self", [task("T-2", ["T-2"])]),
            ("cycle", [task("T-2", ["T-3"]), task("T-3", ["T-2"])]),
        ):
            with self.subTest(invalid_dependency=name):
                package = minimal_package()
                change = amendment("TA-1", added)
                before = copy.deepcopy(change)
                with self.assertRaises(CogitoError):
                    validate_amendment(package, [], change)
                with self.assertRaises(CogitoError):
                    materialize_contract(package, [change])
                self.assertEqual(change, before)

    def test_base_prior_and_forward_same_batch_dependencies_become_effective_edges(self) -> None:
        package = minimal_package()
        prior = amendment("TA-1", [task("T-2", ["T-1"])])
        # T-4 deliberately references T-3 before its declaration in this batch.
        change = amendment("TA-2", [task("T-4", ["T-1", "T-2", "T-3"]), task("T-3", ["T-2"])])
        changes = [prior, change]
        before = copy.deepcopy((package, changes))
        original_hash = package_hash(package)
        expected_hash = hash_json({"base_package_hash": original_hash, "amendments": changes})
        validate_amendment(package, [prior], change)
        effective = materialize_contract(package, changes)
        self.assertEqual(
            set(map(edge_pair, effective["execution_dag"]["edges"])),
            {("T-1", "T-2"), ("T-2", "T-3"), ("T-1", "T-4"), ("T-2", "T-4"), ("T-3", "T-4")},
        )
        by_id = {item["id"]: item for item in effective["execution_dag"]["tasks"]}
        for added in [*prior["added_tasks"], *change["added_tasks"]]:
            self.assertEqual(by_id[added["id"]]["depends_on"], added["depends_on"])
        self.assertEqual((package, changes), before)
        self.assertEqual(package_hash(package), original_hash)
        self.assertEqual(effective["effective_contract_hash"], expected_hash)

    def test_cross_slice_additions_require_an_existing_approved_slice_edge(self) -> None:
        for approved_edge in (False, True):
            with self.subTest(approved_slice_dependency=approved_edge):
                package = minimal_package()
                second = copy.deepcopy(package["slices"][0])
                second["id"] = "FS-002"
                second["worker"]["branch"] = "codex/fs-002"
                second["worker"]["worktree"] = ".cogito/worktrees/FS-002"
                package["slices"].append(second)
                package["execution_dag"]["tasks"].append(task("T-2", [], "FS-002"))
                if approved_edge:
                    package["execution_dag"]["edges"] = [{"from": "T-1", "to": "T-2"}]
                    package["execution_dag"]["tasks"][1]["depends_on"] = ["T-1"]
                change = amendment("TA-1", [task("T-3", ["T-1"], "FS-002")])
                before = copy.deepcopy(package)
                validate_package(package)
                if approved_edge:
                    validate_amendment(package, [], change)
                    effective = materialize_contract(package, [change])
                    self.assertEqual(
                        set(map(edge_pair, effective["execution_dag"]["edges"])),
                        {("T-1", "T-2"), ("T-1", "T-3")},
                    )
                else:
                    with self.assertRaises(CogitoError):
                        validate_amendment(package, [], change)
                self.assertEqual(package, before)


if __name__ == "__main__":
    unittest.main()
