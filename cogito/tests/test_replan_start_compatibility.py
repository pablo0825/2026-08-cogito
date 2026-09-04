"""End-to-end compatibility for approved RP histories predating Start artifacts."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

import cogito_test_support
import cogito_replan_start
from cogito_common import CogitoError, canonical_json, hash_json
from cogito_events import read_events
from cogito_replan_start import _cleanup_checkout, checkout, manifest
from cogito_test_support import GitTestCase, git, init_repo
import test_feature_multitask as feature_support
import test_replan_store as replan_support


class LegacyReplanStartCompatibilityTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)

    def legacy_reviewing(self):
        repo, worker, source, successor, rp, proposal = (
            replan_support.ReplanStoreTests.setup_replan(self))
        events = read_events(rp.events_path)
        prepared = events[-1]
        self.assertEqual(prepared["type"], "proposal-prepared")
        legacy = prepared["payload"]["proposal"]
        legacy.pop("start_artifact", None)
        legacy.pop("start_artifact_hash", None)
        prepared["payload"]["proposal_hash"] = hash_json(legacy)
        body = {key: value for key, value in prepared.items() if key != "event_hash"}
        prepared["event_hash"] = hash_json(body)
        rp.events_path.write_text(
            "".join(canonical_json(event) + "\n" for event in events), encoding="utf-8")
        return repo, successor, rp

    def approved_legacy(self):
        repo, successor, rp = self.legacy_reviewing()
        digest = rp.load()["proposal_hash"]
        rp.review({
            "proposal_hash": digest,
            "reviewer_id": "legacy-independent-reviewer",
            "findings": [],
            "assessment": {key: "Reviewed legacy approved controls"
                           for key in ("impact", "reuse", "revalidation", "handoff")},
        }, "legacy-review")
        rp.approve(digest, "legacy-approve")
        return repo, successor, rp

    def test_legacy_proposal_completes_with_append_only_isolated_recovery(self) -> None:
        _, successor, rp = self.approved_legacy()
        before_handoff = rp.events_path.read_bytes()
        self.assertEqual(rp.handoff("legacy-handoff")["state"], "completed")
        self.assertTrue(rp.events_path.read_bytes().startswith(before_handoff))
        rp_types = [event["type"] for event in read_events(rp.events_path)]
        run_types = [event["type"] for event in read_events(successor.events_path)]
        self.assertEqual(rp_types.count("handoff-start-isolated"), 1)
        self.assertEqual(rp_types.count("handoff-start-validated"), 1)
        self.assertEqual(run_types.count("start-gate-passed"), 1)
        recorded = rp.events_path.read_bytes()
        self.assertEqual(rp.handoff("legacy-handoff")["state"], "completed")
        self.assertEqual(rp.events_path.read_bytes(), recorded)

    def test_legacy_interruptions_retry_with_the_same_action_once(self) -> None:
        for point in ("after-isolation-created", "after-isolation-validated", "after-start-event"):
            with self.subTest(point=point):
                _, successor, rp = self.approved_legacy()

                def interrupt(label):
                    if label == point:
                        raise CogitoError("injected " + point)

                with mock.patch.object(rp, "_isolated_start_fault", side_effect=interrupt):
                    with self.assertRaisesRegex(CogitoError, "injected " + point):
                        rp.handoff("legacy-handoff")
                self.assertEqual(rp.handoff("legacy-handoff")["state"], "completed")
                rp_types = [event["type"] for event in read_events(rp.events_path)]
                run_types = [event["type"] for event in read_events(successor.events_path)]
                self.assertEqual(rp_types.count("handoff-start-isolated"), 1)
                self.assertEqual(rp_types.count("handoff-start-validated"), 1)
                self.assertEqual(run_types.count("start-gate-passed"), 1)


class LegacyStartCheckoutSecurityTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = (Path(self.temporary.name) / "repo").resolve()
        self.repo.mkdir()
        init_repo(self.repo)
        (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")

    def test_source_parent_symlink_cannot_read_outside_repository(self) -> None:
        outside = self.repo.parent / "outside-source"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret\n", encoding="utf-8")
        (self.repo / "controls").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(CogitoError, "real directory parents"):
            manifest(self.repo, ["controls/secret.txt"])

    def test_target_parent_symlink_cannot_write_outside_checkout(self) -> None:
        outside = self.repo.parent / "outside-target"
        outside.mkdir()
        sentinel = outside / "spec.md"
        sentinel.write_text("outside\n", encoding="utf-8")
        (self.repo / "docs").symlink_to(outside, target_is_directory=True)
        git(self.repo, "add", "docs")
        git(self.repo, "commit", "-qm", "baseline parent symlink")
        head = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "docs").unlink()
        (self.repo / "docs").mkdir()
        (self.repo / "docs/spec.md").write_text("approved\n", encoding="utf-8")
        controls = manifest(self.repo, ["docs/spec.md"])
        with self.assertRaisesRegex(CogitoError, "real directory parents"):
            with checkout(self.repo, head, controls):
                self.fail("unsafe checkout unexpectedly materialized")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside\n")
        self.assertEqual(len(git(self.repo, "worktree", "list", "--porcelain").split("worktree ")) - 1, 1)

    def test_target_symlink_is_rejected_without_touching_its_referent(self) -> None:
        outside = self.repo.parent / "outside-file.txt"
        outside.write_text("outside\n", encoding="utf-8")
        (self.repo / "control.txt").symlink_to(outside)
        git(self.repo, "add", "control.txt")
        git(self.repo, "commit", "-qm", "baseline target symlink")
        head = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "control.txt").unlink()
        (self.repo / "control.txt").write_text("approved\n", encoding="utf-8")
        controls = manifest(self.repo, ["control.txt"])
        with self.assertRaisesRegex(CogitoError, "refuses a symlink"):
            with checkout(self.repo, head, controls):
                self.fail("unsafe checkout unexpectedly materialized")
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_target_replacement_race_cannot_write_through_symlink(self) -> None:
        outside = self.repo.parent / "race-target.txt"
        outside.write_text("outside\n", encoding="utf-8")
        head = git(self.repo, "rev-parse", "HEAD")
        controls = manifest(self.repo, ["base.txt"])
        original_open = cogito_replan_start.os.open
        attacked = False

        def replace_before_create(path, flags, *args, **kwargs):
            nonlocal attacked
            if path == "base.txt" and flags & os.O_EXCL and not attacked:
                attacked = True
                os.symlink(outside, path, dir_fd=kwargs["dir_fd"])
            return original_open(path, flags, *args, **kwargs)

        with mock.patch("cogito_replan_start.os.open", side_effect=replace_before_create):
            with self.assertRaisesRegex(CogitoError, "cannot safely write"):
                with checkout(self.repo, head, controls):
                    self.fail("target race unexpectedly succeeded")
        self.assertTrue(attacked)
        self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

    def test_partial_add_with_matching_registration_is_cleaned_and_retryable(self) -> None:
        head = git(self.repo, "rev-parse", "HEAD")
        controls = manifest(self.repo, ["base.txt"])
        original_git = cogito_replan_start._git
        interrupted = False

        def interrupt_after_add(root, *args):
            nonlocal interrupted
            result = original_git(root, *args)
            if args[:3] == ("worktree", "add", "--detach") and not interrupted:
                interrupted = True
                raise CogitoError("injected post-add timeout")
            return result

        with mock.patch("cogito_replan_start._git", side_effect=interrupt_after_add):
            with self.assertRaisesRegex(CogitoError, "injected post-add timeout"):
                with checkout(self.repo, head, controls):
                    pass
        self.assertEqual(len(git(self.repo, "worktree", "list", "--porcelain").split("worktree ")) - 1, 1)
        with checkout(self.repo, head, controls):
            pass

    def test_partial_add_with_wrong_registration_is_preserved(self) -> None:
        expected_head = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "second.txt").write_text("second\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "second")
        wrong_head = git(self.repo, "rev-parse", "HEAD")
        controls = manifest(self.repo, ["base.txt"])
        original_git = cogito_replan_start._git
        captured: list[Path] = []

        def register_wrong_head(root, *args):
            if args[:3] == ("worktree", "add", "--detach"):
                captured.append(Path(args[-2]))
                original_git(root, *args[:-1], wrong_head)
                raise CogitoError("injected ambiguous add")
            return original_git(root, *args)

        with mock.patch("cogito_replan_start._git", side_effect=register_wrong_head):
            with self.assertRaisesRegex(CogitoError, "does not match this operation"):
                with checkout(self.repo, expected_head, controls):
                    pass
        self.assertTrue(captured[0].exists())
        self.assertIn(str(captured[0]), git(self.repo, "worktree", "list", "--porcelain"))
        git(self.repo, "worktree", "remove", "--force", str(captured[0]))

    def test_partial_add_with_unreadable_registry_is_preserved(self) -> None:
        head = git(self.repo, "rev-parse", "HEAD")
        controls = manifest(self.repo, ["base.txt"])
        original_git = cogito_replan_start._git
        captured: list[Path] = []

        def lose_registry_access(root, *args):
            if args[:3] == ("worktree", "add", "--detach"):
                captured.append(Path(args[-2]))
                original_git(root, *args)
                raise CogitoError("injected post-add timeout")
            if args[:3] == ("worktree", "list", "--porcelain"):
                raise CogitoError("injected registry failure")
            return original_git(root, *args)

        with mock.patch("cogito_replan_start._git", side_effect=lose_registry_access):
            with self.assertRaisesRegex(CogitoError, "registry state cannot be inspected"):
                with checkout(self.repo, head, controls):
                    pass
        self.assertTrue(captured[0].exists())
        self.assertIn(str(captured[0]), git(self.repo, "worktree", "list", "--porcelain"))
        git(self.repo, "worktree", "remove", "--force", str(captured[0]))

    def test_git_remove_failure_is_reported_and_blocks_retry(self) -> None:
        head = git(self.repo, "rev-parse", "HEAD")
        controls = manifest(self.repo, ["base.txt"])
        original = subprocess.run
        captured: list[Path] = []

        def fail_remove(argv, *args, **kwargs):
            if "worktree" in argv and "remove" in argv:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="injected remove failure")
            result = original(argv, *args, **kwargs)
            if "worktree" in argv and "add" in argv:
                captured.append(Path(argv[-2] if argv[-1] == head else argv[-1]))
            return result

        with mock.patch("cogito_replan_start.subprocess.run", side_effect=fail_remove):
            with self.assertRaisesRegex(CogitoError, "injected remove failure"):
                with checkout(self.repo, head, controls):
                    pass
        self.assertTrue(captured)
        directory = captured[0]
        self.assertTrue(directory.exists())
        self.assertIn(str(directory), git(self.repo, "worktree", "list", "--porcelain"))
        with self.assertRaisesRegex(CogitoError, "previous isolated Start Gate cleanup"):
            with checkout(self.repo, head, controls):
                pass
        git(self.repo, "worktree", "remove", "--force", str(directory))

    def test_directory_removal_failure_is_not_ignored(self) -> None:
        directory = Path(tempfile.mkdtemp(prefix="cogito-cleanup-test-"))
        self.addCleanup(shutil.rmtree, directory, True)
        with mock.patch("cogito_replan_start.shutil.rmtree", side_effect=OSError("injected rmtree failure")):
            with self.assertRaisesRegex(CogitoError, "injected rmtree failure"):
                _cleanup_checkout(self.repo, directory, None)
