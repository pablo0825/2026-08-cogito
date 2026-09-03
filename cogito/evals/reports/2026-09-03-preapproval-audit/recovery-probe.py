"""Read-only product audit; all run mutations occur in disposable repositories."""
import copy
import json
import sys
import unittest
from pathlib import Path

COGITO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(COGITO / "tests"))
from test_package_revisions import PackageRevisionTests
from cogito_contracts import package_hash
from cogito_run_store import RunStore

RESULTS = []


class RecoveryAudit(PackageRevisionTests):
    # Inherit fixture helpers, but run only the three audit methods below.
    def prepare(self, repo, draft, path, action):
        path.write_text(json.dumps(draft))
        return self.invoke(repo, "prepare-package", "--run-id", draft["run_id"],
                           "--package", str(path), "--action-id", action)

    def new_run(self, repo, draft):
        successor = copy.deepcopy(draft)
        successor["run_id"] = "DEV-new-independent"
        successor["shared_understanding"]["hash"] = "e" * 64
        successor["boundary"] = {"decision": "single-slice", "evidence": ["Only filtering is included"]}
        store = RunStore(repo, successor["run_id"])
        store.create("feature")
        store.transition("shared-understanding-ready", {"shared_understanding_hash": "e" * 64}, "ready")
        store.transition("shared-understanding-confirmed", {"confirmed": True, "shared_understanding_hash": "e" * 64}, "confirmed")
        store.transition("boundary-complete", successor["boundary"], "boundary")
        store.prepare_package(successor, "prepare")
        return store

    def test_recovery_preserves_latest_candidate_and_hash_history(self):
        repo, draft, path = self.fixture("feature")
        self.prepare(repo, draft, path, "v1")
        revised = copy.deepcopy(draft)
        revised["stop_conditions"].append("Pause if new ambiguity is found")
        path2 = path.with_name("v2.json")
        self.prepare(repo, revised, path2, "v2")
        store = RunStore(repo, draft["run_id"])
        history = store.events_path.read_bytes()
        store.state_path.unlink()  # Simulate lost disposable state after restart.
        recovered = json.loads(self.invoke(repo, "status", "--run-id", draft["run_id"]).stdout)["data"]
        self.assertEqual(recovered["candidate_package_hash"], package_hash(revised))
        self.prepare(repo, draft, path, "v1")
        self.assertEqual(store.events_path.read_bytes(), history)
        rejected = self.invoke(repo, "approve", "--run-id", draft["run_id"], "--package", str(path),
                               "--action-id", "old-approval", ok=False)
        candidates = [event["payload"] for event in map(json.loads, history.splitlines()) if event["type"] == "package-ready"]
        self.assertEqual(len(candidates), 2)
        self.assertTrue(all(set(item) == {"package_valid", "candidate_package_hash"} for item in candidates))
        self.assertFalse((repo / "docs/cogito/packages" / f"{draft['run_id']}.json").exists())
        RESULTS.append({"case": "cache_loss_and_old_action_replay", "latest_hash_restored": True,
                        "history_unchanged": True, "old_approval_error": rejected.stderr.strip(),
                        "candidate_event_payloads": candidates,
                        "note": "Candidate events retain hashes, not a full draft snapshot or revision reason."})

    def test_independent_new_run_does_not_retire_old_candidate(self):
        repo, draft, path = self.fixture("feature")
        self.prepare(repo, draft, path, "v1")
        old = RunStore(repo, draft["run_id"])
        before = old.events_path.read_bytes()
        successor = self.new_run(repo, draft)
        self.assertEqual(old.events_path.read_bytes(), before)
        self.assertEqual(old.load()["state"], "awaiting-package-approval")
        approved = old.approve_package(draft, "old-still-approvable")
        self.assertEqual(approved["state"], "start-gate")
        RESULTS.append({"case": "independent_new_run", "new_state": successor.load()["state"],
                        "old_history_unchanged_by_new_run": True, "old_approval_state": approved["state"],
                        "note": "New independent run is not a linked replacement and does not invalidate old approval."})

    def test_explicit_cancel_then_fresh_run_is_possible(self):
        repo, draft, path = self.fixture("feature")
        self.prepare(repo, draft, path, "v1")
        old = RunStore(repo, draft["run_id"])
        before = old.events_path.read_bytes()
        old.transition("cancel", {"authorized": True, "reason": "Simulated explicit user cancellation before starting over"}, "cancel")
        successor = self.new_run(repo, draft)
        rejected = self.invoke(repo, "approve", "--run-id", draft["run_id"], "--package", str(path),
                               "--action-id", "cancelled-approval", ok=False)
        self.assertEqual(old.load()["state"], "cancelled")
        self.assertTrue(old.events_path.read_bytes().startswith(before))
        RESULTS.append({"case": "explicit_cancel_then_new_run", "old_state": "cancelled",
                        "new_state": successor.load()["state"], "old_history_preserved": True,
                        "old_approval_error": rejected.stderr.strip(),
                        "note": "Manual restart is possible, but no automatic replanning lineage or downstream invalidation."})


if __name__ == "__main__":
    suite = unittest.TestSuite(RecoveryAudit(name) for name in (
        "test_recovery_preserves_latest_candidate_and_hash_history",
        "test_independent_new_run_does_not_retire_old_candidate",
        "test_explicit_cancel_then_fresh_run_is_possible",
    ))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    Path(__file__).with_name("recovery-results.json").write_text(json.dumps(RESULTS, indent=2, ensure_ascii=False) + "\n")
    sys.exit(not result.wasSuccessful())
