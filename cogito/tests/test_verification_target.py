"""驗證 Atomic 工作樹資格與其他狀態的拒絕邊界。"""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cogito_common import CogitoError
from cogito_runner import validate_check_target

class VerificationTargetTests(unittest.TestCase):
    root = Path("/tmp/cogito-target-root").resolve()
    a = root / "slice-a"
    b = root / "slice-b"

    def state(self, status="verified", phase="verifying"):
        return {"state": phase, "tasks": {
            "A": {"status": "complete", "worktree": str(self.a)},
            "B": {"status": status, "worktree": str(self.b), "check_ids": ["V-B"]}}}

    def check(self, state, target=None, package=None):
        validate_check_target(package or {"task_delivery": "atomic"}, state,
                              "V-B", target or self.b, self.root)

    def test_atomic_verified_slice_can_refresh_after_other_slice_correction(self):
        self.check(self.state())

    def test_complete_checkout_remains_eligible(self):
        for package in ({"task_delivery": "atomic"}, {"task_delivery": "non-atomic"}):
            self.check(self.state("complete"), package=package)

    def test_atomic_other_milestones_are_rejected(self):
        for status in ("pending", "leased", "running", "reviewed", "integrated", "blocked"):
            with self.subTest(status=status), self.assertRaises(CogitoError):
                self.check(self.state(status))

    def test_unknown_and_delivery_checkouts_are_rejected(self):
        for target in (self.root, self.root / "unknown"):
            with self.subTest(target=target), self.assertRaises(CogitoError):
                self.check(self.state(), target)

    def test_non_atomic_verified_checkout_remains_rejected(self):
        for package in ({"kind": "documentation"}, {"task_delivery": "non-atomic"}):
            with self.subTest(package=package), self.assertRaises(CogitoError):
                self.check(self.state(), package=package)

    def test_other_phases_do_not_gain_verified_permission(self):
        for phase in ("executing", "review-fix", "reviewing", "blocked"):
            with self.subTest(phase=phase), self.assertRaises(CogitoError):
                self.check(self.state(phase=phase))

    def test_post_integration_still_requires_delivery_checkout(self):
        state = self.state(phase="post-integration-verification")
        self.check(state, self.root)
        with self.assertRaises(CogitoError):
            self.check(state)

if __name__ == "__main__":
    unittest.main()
