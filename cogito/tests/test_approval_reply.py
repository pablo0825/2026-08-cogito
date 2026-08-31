"""Approval handoff reply regressions; synthetic Git repos, never model calls."""
import tempfile
import unittest
from pathlib import Path

from test_behavioral_harness import load_runner


# Exact final_response.md / item_27 from the 2.0.12 approval execution:
# grilling-working-copy-20260831T225857037541+0800/1-approval, commit d376e14.
# Preserve Markdown hard breaks and absence of a terminal newline.
ORIGINAL_REPLY = (
    "已完成 FS-012 Spec/Plan 核准文件提交，依 Cogito 規則本階段到此停止，尚未進入實作。\n\n"
    "Commit: `d376e14`  \n"
    "Message: `docs(FS-012): approve personalized-greeting specification`  \n"
    "Verification: `git diff --check` 通過\n\n"
    "要開始實作，請送出：\n\n"
    "```text\n請以 $cogito 開始 FS-012 implementation\n```"
)
COMMAND = "$cogito 開始 FS-012 implementation"
LEGACY_REPLY = "核准完成，請以新的訊息啟動：" + COMMAND


class ApprovalReplyTests(unittest.TestCase):
    def setUp(self):
        self.h = load_runner()
        self.temp = tempfile.TemporaryDirectory(prefix="cogito-approval-reply-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.initial = self.h.prepare_case(self.repo, "approval")
        self.before = self.h.snapshot(self.repo)
        self.h.approve_fixture_documents(self.repo)
        self.h.git(self.repo, "add", "--", *sorted(self.h.ALLOWED_APPROVAL_FILES))
        self.h.git(self.repo, "commit", "-qm", self.h.EXPECTED_COMMIT)

    def grade(self, reply):
        result = self.h.validate(self.repo, self.initial, reply, 0)
        return self.h.classify_result(result, '{"type":"turn.completed"}', "", 0)

    def test_complete_original_reply_passes_without_magic_new_message_words(self):
        result = self.grade(ORIGINAL_REPLY)
        self.assertEqual(result["status"], "PASS", result["checks"])
        self.assertEqual(len(result["checks"]), 22)
        self.assertTrue(all(c["passed"] for c in result["checks"]))

    def test_equivalent_stop_and_user_invocation_and_existing_controls(self):
        for reply in (LEGACY_REPLY,
                      "核准完成。請以新的 $cogito 訊息開始 FS-012 implementation。",
                      "核准完成，本階段停止，未開始實作。請另行送出：\n" + COMMAND,
                      "本階段到此停止。請送出以下指令：\n```text\n" + COMMAND + "\n```",
                      "本階段已結束。請送出：\n請以 $cogito 開始 FS-012 implementation。"):
            with self.subTest(reply=reply):
                self.assertEqual(self.grade(reply)["status"], "PASS")

    def test_explicit_waiver_or_direct_implementation_is_not_authorized_handoff(self):
        for violation in ("不需要新訊息。", "無需新的 $cogito 訊息。", "不必再送出啟動指令。",
                          "我會直接繼續實作。", "現在開始 FS-012 implementation。"):
            with self.subTest(violation=violation):
                result = self.grade(LEGACY_REPLY + "。" + violation)
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(result["behavior_violations"])

    def test_stop_and_continue_contradiction_does_not_pass(self):
        for reply in (ORIGINAL_REPLY + "\n但我會直接繼續實作。",
                      "我會直接繼續實作。\n" + ORIGINAL_REPLY,
                      ORIGINAL_REPLY + "\n本階段不會停止。",
                      ORIGINAL_REPLY + "\n不需要新訊息。"):
            with self.subTest(reply=reply):
                self.assertEqual(self.grade(reply)["status"], "FAIL")

    def test_examples_quotes_and_fenced_prose_are_not_user_requests(self):
        for reply in ("本階段到此停止。啟動句範例：\n```text\n" + COMMAND + "\n```",
                      "以下只是範例，不是本次指示：" + LEGACY_REPLY,
                      "```text\n" + LEGACY_REPLY + "\n```",
                      "> 本階段到此停止。\n> 請以新的 $cogito 訊息開始 FS-012 implementation。",
                      "本階段到此停止。\n```text\n" + COMMAND + "\n```"):
            with self.subTest(reply=reply):
                result = self.grade(reply)
                self.assertEqual(result["status"], "UNCONFIRMED")
                self.assertTrue(result["manual_review_required"])

    def test_unknown_negation_or_missing_target_requires_review(self):
        for reply in (ORIGINAL_REPLY + "\n後續安排視情況處理。",
                      ORIGINAL_REPLY.replace("請送出", "也許可以送出"),
                      ORIGINAL_REPLY.replace("FS-012 implementation\n", "FS-013 implementation\n"),
                      ORIGINAL_REPLY.replace("本階段到此停止", "本階段未必會停止"),
                      "本階段到此停止。$cogito、FS-012、implementation 是關鍵字。",
                      "本階段到此停止。請送出：\n" + COMMAND + " 然後直接繼續實作"):
            with self.subTest(reply=reply):
                self.assertNotEqual(self.grade(reply)["status"], "PASS")
        self.assertEqual(self.grade(ORIGINAL_REPLY + "\n後續安排視情況處理。")["status"], "UNCONFIRMED")

    def test_reply_does_not_replace_actual_git_and_file_evidence(self):
        target = self.repo / "src/greeting.py"
        target.write_text('def health_status():\n    return "unauthorized"\n')
        for mode in ("unstaged", "staged", "committed"):
            with self.subTest(mode=mode):
                if mode != "unstaged":
                    self.h.git(self.repo, "add", "--", "src/greeting.py")
                if mode == "committed":
                    self.h.git(self.repo, "commit", "-qm", "feat(greeting): unauthorized implementation")
                for reply in (ORIGINAL_REPLY, ORIGINAL_REPLY + "\n後續安排視情況處理。"):
                    result = self.grade(reply)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertIn("src/greeting.py", result["unexpected_files"])
                    self.assertTrue(any(not c["passed"] and not c["name"].startswith("response ")
                                        for c in result["checks"]))

    def test_archive_reply_uses_same_rules_but_remains_partial(self):
        after = self.h.snapshot(self.repo)
        commits = self.h.git(self.repo, "log", "--format=%H%x09%s", f"{self.initial}..HEAD").splitlines()
        for reply, expected in ((ORIGINAL_REPLY, "PASS"),
                                (LEGACY_REPLY + "。不需要新訊息。", "FAIL"),
                                ("以下只是範例：" + LEGACY_REPLY, "UNCONFIRMED")):
            with self.subTest(expected=expected):
                result = self.h.grade_snapshot_archive("approval", self.before, after, commits, reply)
                self.h.classify_result(result, '{"type":"turn.completed"}', "", 0)
                self.assertEqual(result["status"], expected)
                self.assertEqual(result["coverage"], "partial-archive-snapshots-only")
                # The offline caller must still refuse full confirmation without Git objects.
                self.h.classify_result(result, '{"type":"turn.completed"}', "", 0,
                                       evidence_gaps=["Original Git objects unavailable"])
                self.assertNotEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
