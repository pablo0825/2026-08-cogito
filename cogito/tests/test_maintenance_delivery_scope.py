"""Maintenance delivery enforces scope even after Agent Result validation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_common import CogitoError
from cogito_contracts import package_hash
from test_maintenance_corrections import MaintenanceCli
import test_maintenance_corrections as corrections


class MaintenanceDeliveryScopeTests(GitTestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="cogito-maintenance-delivery-")
        self.addCleanup(temporary.cleanup)
        repo = Path(temporary.name)
        init_repo(repo)
        (repo / ".gitignore").write_text(".cogito/\ndocs/cogito/packages/\n")
        (repo / "note.txt").write_text("before\n")
        (repo / "unrelated.txt").write_text("preserve\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "baseline")
        baseline = git(repo, "rev-parse", "HEAD")
        draft = package("maintenance")
        draft.update({
            "run_id": "MNT-delivery-scope", "baseline_commit": baseline,
            "approved_paths": ["note.txt"],
            "execution_dag": {"tasks": [{"id": "T-1", "paths": ["note.txt"]}], "edges": []},
            "checks": [{"id": "C-1", "required": True, "argv": [
                sys.executable, "-I", "-c",
                "from pathlib import Path; assert Path('note.txt').read_text() == 'after\\n'",
            ]}],
        })
        store = MaintenanceCli(repo, draft["run_id"])
        store.create("maintenance")
        store.prepare_package(draft)
        store.approve_package(draft)
        store.start_gate()
        store.update_task("T-1", "leased", "worker")
        store.update_task("T-1", "running", "worker")
        (repo / "note.txt").write_text("after\n")
        store.submit_agent_result({
            "schema_version": "3.0", "run_id": store.run_id, "task_id": "T-1",
            "agent_id": "worker", "role": "implementer", "status": "complete",
            "base_commit": baseline, "head_commit": baseline, "changed_paths": ["note.txt"],
            "evidence": [], "risks": [], "requested_transition": "verifying",
        })
        store.update_task("T-1", "complete", "worker")
        store.transition("implementation-complete", {})
        pre = corrections.MaintenanceCorrectionTests.check(store, repo, "pre")
        self.assertTrue(pre["passed"])
        store.complete_verification([pre])
        store.transition("review-approved", {"review_exemption": True})
        store.complete_integration(baseline)
        return repo, store, baseline

    def commit_result(self, repo, store, baseline, post, *, save_package=False):
        graph_relative = "docs/cogito/project-graph.json"
        graph_path = repo / graph_relative
        graph = json.loads(graph_path.read_text())
        graph["active_run_id"] = None
        graph_path.write_text(json.dumps(graph))
        result_relative = f"docs/cogito/results/{store.run_id}.json"
        result_path = repo / result_relative
        result_path.parent.mkdir(parents=True)
        state = store.load()
        result_path.write_text(json.dumps({
            "schema_version": "3.0", "run_id": store.run_id, "status": "accepted",
            "package_hash": state["package_hash"],
            "effective_contract_hash": state["effective_contract_hash"],
            "integration_commits": [baseline], "slice_dispositions": {},
            "checks": [{"id": "C-1", "status": "passed", "evidence": post["evidence_path"]}],
            "reviews": [], "amendments": [],
            "human_gate": {"required": False, "outcome": "not-required"}, "remaining_risks": [],
        }))
        git(repo, "add", "note.txt", graph_relative, result_relative)
        if save_package:
            git(repo, "add", "--force", f"docs/cogito/packages/{store.run_id}.json")
        git(repo, "commit", "-qm", "finalize Maintenance")
        final = git(repo, "rev-parse", "HEAD")
        self.assertEqual(git(repo, "rev-list", "--count", f"{baseline}..{final}"), "1")
        return result_relative, graph_relative, final

    def test_staged_outside_path_added_after_agent_result_is_rejected_at_finalization(self):
        repo, store, baseline = self.fixture()
        # The Agent Result has already passed. Include this change in the final
        # runner snapshot so content equality alone cannot detect scope escape.
        (repo / "unrelated.txt").write_text("unexpected staged modification\n")
        git(repo, "add", "unrelated.txt")
        post = corrections.MaintenanceCorrectionTests.check(store, repo, "post")
        self.assertTrue(post["passed"])
        store.decide_post_verification([post])
        result, graph, final = self.commit_result(repo, store, baseline, post)
        self.assertEqual(git(repo, "show", f"{post['worktree_binding']['content_tree']}:unrelated.txt"),
                         git(repo, "show", f"{final}:unrelated.txt"))
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "approved paths"):
            store.finalize(result, graph, final)
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual(store.load()["state"], "finalizing")

    def test_approved_canonical_package_can_be_saved_in_final_delivery(self):
        repo, store, baseline = self.fixture()
        git(repo, "add", "--force", f"docs/cogito/packages/{store.run_id}.json")
        post = corrections.MaintenanceCorrectionTests.check(store, repo, "post")
        self.assertTrue(post["passed"])
        store.decide_post_verification([post])
        result, graph, final = self.commit_result(repo, store, baseline, post, save_package=True)
        canonical = json.loads(git(repo, "show", f"{final}:docs/cogito/packages/{store.run_id}.json"))
        self.assertEqual(package_hash(canonical), store.load()["package_hash"])
        self.assertEqual(canonical["package_hash"], store.load()["package_hash"])
        self.assertEqual(store.finalize(result, graph, final)["state"], "accepted")

    def test_package_newly_tracked_after_final_check_is_still_unverified(self):
        repo, store, baseline = self.fixture()
        post = corrections.MaintenanceCorrectionTests.check(store, repo, "post")
        self.assertTrue(post["passed"])
        store.decide_post_verification([post])
        result, graph, final = self.commit_result(repo, store, baseline, post, save_package=True)
        before = store.events_path.read_bytes()
        with self.assertRaisesRegex(CogitoError, "unverified content"):
            store.finalize(result, graph, final)
        self.assertEqual(store.events_path.read_bytes(), before)
        self.assertEqual(store.load()["state"], "finalizing")
