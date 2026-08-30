"""Recovery prose regressions; no artifacts, service or model needed at test time."""
import unittest

from test_behavioral_harness import load_runner


# Verbatim Status Note from original commit aaef4202bb02043411d06584f0533ae8d31e2755,
# v2.0.2-four-cases-20260830T212520588618+0800/2-service-unavailable.
# Original execution item_15 ran this endpoint's approved command: exit 69,
# SERVICE_UNAVAILABLE, <urlopen error timed out>, assertions_executed: false.
ENDPOINT = "http://127.0.0.1:58237/cases"
ORIGINAL_NOTE = (
    "Blocked during AI Verification; previous status `in-progress`; required "
    "service-backed check `V-001` could not run because `http://127.0.0.1:58237/cases` "
    "timed out; resume when the service is available and `python3 -B "
    "tests/check_service.py http://127.0.0.1:58237/cases` can execute product assertions"
)
CANONICAL = (f"Previous state: in-progress; service unavailable; "
             f"resume when {ENDPOINT} is reachable")


class ServiceRecoveryRegressions(unittest.TestCase):
    def grade(self, note):
        return load_runner().recovery_evidence(note, ENDPOINT)

    def test_verbatim_original_note_all_three_clauses(self):
        result = self.grade(ORIGINAL_NOTE)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["previous_state"], "in-progress")
        self.assertIn("V-001", result["cause"])
        self.assertIn(ENDPOINT, result["cause"])
        self.assertIn(f"tests/check_service.py {ENDPOINT}", result["resume_when"])

    def test_equivalent_complete_expressions(self):
        for note in (CANONICAL, ORIGINAL_NOTE.replace("previous status", "Previous state:"),
                     ORIGINAL_NOTE.replace("timed out", "refused the connection"),
                     f"Blocked from in-progress: required V-001 local service dependency unavailable; "
                     f"retry V-001 once {ENDPOINT} becomes available",
                     f"原狀態：in-progress；V-001 本機服務連線逾時；恢復條件：{ENDPOINT}回應 HTTP 200後重新執行V-001"):
            with self.subTest(note=note):
                self.assertEqual(self.grade(note)["status"], "PASS")

    def test_missing_or_wrong_prior_state(self):
        for note in (ORIGINAL_NOTE.replace("previous status `in-progress`; ", ""),
                     ORIGINAL_NOTE.replace("previous status `in-progress`", "previous status `approved`"),
                     CANONICAL.replace("Previous state: in-progress; ", ""),
                     CANONICAL.replace("in-progress", "accepted")):
            with self.subTest(note=note):
                self.assertEqual(self.grade(note)["status"], "FAIL")

    def test_wrong_service_check_and_command_never_pass(self):
        for note in (ORIGINAL_NOTE.replace("`V-001`", "`V-002`"),
                     ORIGINAL_NOTE.replace(ENDPOINT, "http://127.0.0.1:1/cases", 1),
                     ORIGINAL_NOTE.replace(f"check_service.py {ENDPOINT}", "check_service.py http://127.0.0.1:1/cases"),
                     ORIGINAL_NOTE.replace("tests/check_service.py", "tests/other_check.py"),
                     ORIGINAL_NOTE.replace("python3 -B", "python3 -B --skip-assertions"),
                     CANONICAL.replace("is reachable", "is reachable; rerun V-002")):
            with self.subTest(note=note):
                self.assertNotEqual(self.grade(note)["status"], "PASS")

    def test_negation_contradiction_and_ignored_text_never_pass(self):
        for note in ("Not " + CANONICAL,
                     "Example only: " + CANONICAL,
                     CANONICAL + "; previous state: accepted",
                     CANONICAL + "; the service is not unavailable",
                     ORIGINAL_NOTE.replace("previous status `in-progress`", "previous status was not `in-progress`"),
                     ORIGINAL_NOTE.replace("could not run", "could run"),
                     ORIGINAL_NOTE.replace("timed out;", "did not time out;"),
                     ORIGINAL_NOTE.replace("can execute product assertions", "cannot execute product assertions"),
                     ORIGINAL_NOTE.replace("can execute product assertions", "can execute product assertions or skip them"),
                     ORIGINAL_NOTE.replace("is available and", "is unavailable and"),
                     ORIGINAL_NOTE.replace("is available and", "is available or"),
                     ORIGINAL_NOTE + "; V-001 passed; AI-001 satisfied"):
            with self.subTest(note=note):
                self.assertNotEqual(self.grade(note)["status"], "PASS")

    def test_recovery_missing_pending_and_unknown_are_not_pass(self):
        prefix = ORIGINAL_NOTE.rsplit(";", 1)[0] + "; "
        for ending, expected in (("", "FAIL"), ("recovery: ", "FAIL"),
                                 ("recovery: pending", "FAIL"), ("TBD", "FAIL"),
                                 ("resume when things improve", "UNCONFIRMED"),
                                 ("resume when the service is available", "UNCONFIRMED"),
                                 ("resume whenever the operator considers it okay", "UNCONFIRMED")):
            with self.subTest(ending=ending):
                self.assertEqual(self.grade(prefix + ending)["status"], expected)

    def test_unknown_prose_requires_review_not_behavior_failure(self):
        for note in ("Previously implementing; service seems offline; try again later",
                     f"Previous state: in-progress; service unavailable, resume when {ENDPOINT} is reachable",
                     f"service unavailable; Previous state: in-progress; resume when {ENDPOINT} is reachable",
                     ORIGINAL_NOTE.replace("previous status `in-progress`", "previous status `custom-state`"),
                     ORIGINAL_NOTE.replace("timed out", "experienced an unspecified problem"),
                     ORIGINAL_NOTE + "; additional context not understood"):
            with self.subTest(note=note):
                self.assertEqual(self.grade(note)["status"], "UNCONFIRMED")

    def test_unconfirmed_and_fail_propagate_to_grader_classification(self):
        h = load_runner()
        for note, status in ((ORIGINAL_NOTE, "PASS"),
                             (ORIGINAL_NOTE.replace("timed out", "experienced an unspecified problem"), "UNCONFIRMED"),
                             (ORIGINAL_NOTE.replace("in-progress", "accepted"), "FAIL")):
            with self.subTest(status=status):
                checks = []
                h.add_evidence_check(checks, "Blocked state records previous state, cause and recovery",
                                     h.recovery_evidence(note, ENDPOINT))
                result = {"checks": [h.asdict(c) for c in checks]}
                h.classify_result(result, '{"type":"turn.completed"}', "", 0)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["manual_review_required"], status == "UNCONFIRMED")


if __name__ == "__main__":
    unittest.main()
