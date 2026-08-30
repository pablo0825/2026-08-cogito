"""Approval checkpoint regressions; temporary Git repos only, no model calls."""
import shutil
import tempfile
import unittest
from pathlib import Path

from test_behavioral_harness import load_runner


class ApprovalMetadataTests(unittest.TestCase):
    def grade(self, mutate):
        h = load_runner()
        with tempfile.TemporaryDirectory(prefix="cogito-approval-metadata-") as directory:
            repo = Path(directory) / "repo"
            shutil.copytree(h.FIXTURE, repo)
            initial = h.initialize_fixture(repo)
            h.approve_fixture_documents(repo)
            mutate(repo, h)
            h.git(repo, "add", "--", *sorted(h.ALLOWED_APPROVAL_FILES))
            h.git(repo, "commit", "-qm", h.EXPECTED_COMMIT)
            return h.validate(repo, initial,
                              "核准完成。請以新的 $cogito 訊息開始 FS-012 implementation。", 0)

    @staticmethod
    def edit_approval(repo, relative, edit):
        path = repo / relative
        prefix, block = path.read_text().split("## Approval\n", 1)
        path.write_text(prefix + "## Approval\n" + edit(block))

    def test_complete_approval_passes_with_unrelated_pending(self):
        def mutate(repo, h):
            path = repo / h.PLAN_PATH
            path.write_text(path.read_text() + "\n## Future Checkpoint\n- Approved By: `pending`\n")
        result = self.grade(mutate)
        self.assertTrue(result["passed"], result["checks"])

    def test_plain_values_and_distinct_notes_are_valid(self):
        def mutate(repo, h):
            self.edit_approval(repo, h.PLAN_PATH, lambda block: block.replace(
                "`Exact draft approved`", "Plan and its implementation method approved").replace("`", ""))
        result = self.grade(mutate)
        self.assertTrue(result["passed"], result["checks"])

    def test_reported_plan_approval_omission_is_rejected(self):
        def mutate(repo, h):
            self.edit_approval(repo, h.PLAN_PATH, lambda block: block.replace(
                "`fixture user`", "`pending`").replace("`2026-08-29`", "`pending`").replace(
                "`Exact draft approved`", "`pending`"))
        result = self.grade(mutate)
        self.assertFalse(result["passed"])
        self.assertTrue(next(c["passed"] for c in result["checks"] if c["name"] == "Commit Plan approval"))
        self.assertFalse(next(c["passed"] for c in result["checks"] if c["name"] == "Plan approval recorded"))

    def test_each_required_approval_field_must_exist_once_and_be_complete(self):
        for relative in (load_runner().SPEC_PATH, load_runner().PLAN_PATH):
            for field, value in (("Approved By", "fixture user"), ("Approved At", "2026-08-29"),
                                 ("Approval Note", "Exact draft approved")):
                for mutation in ("pending", "blank", "missing", "duplicate", "placeholder"):
                    with self.subTest(document=relative, field=field, mutation=mutation):
                        line = f"- {field}: `{value}`"
                        replacement = {"pending": f"- {field}: `pending`",
                                       "blank": f"- {field}: ``",
                                       "missing": "", "duplicate": line + "\n" + line,
                                       "placeholder": f"- {field}: `<value>`"}[mutation]
                        result = self.grade(lambda repo, h: self.edit_approval(
                            repo, relative, lambda block: block.replace(line, replacement)))
                        self.assertFalse(result["passed"], result["checks"])

    def test_missing_duplicate_or_example_only_approval_sections_fail(self):
        for mutation in ("missing", "duplicate", "fenced-example", "nested-example"):
            with self.subTest(mutation=mutation):
                def mutate(repo, h):
                    path = repo / h.PLAN_PATH
                    prefix, block = path.read_text().split("## Approval\n", 1)
                    replacements = {"missing": prefix,
                        "duplicate": prefix + "## Approval\n" + block + "\n## Approval\n" + block,
                        "fenced-example": prefix + "## Approval\n```text\n" + block + "```\n",
                        "nested-example": prefix + "## Approval\n### Example\n" + block}
                    path.write_text(replacements[mutation])
                self.assertFalse(self.grade(mutate)["passed"])

    def test_commit_plan_metadata_is_checked_in_its_own_section(self):
        for field, value in (("Commit Plan Approval", "approved"), ("Approved By", "fixture user"),
                             ("Approved At", "2026-08-29")):
            for mutation in ("blank", "missing", "pending"):
                with self.subTest(field=field, mutation=mutation):
                    def mutate(repo, h):
                        path = repo / h.PLAN_PATH
                        prefix, approval = path.read_text().split("## Approval\n", 1)
                        line = f"- {field}: `{value}`"
                        replacement = "" if mutation == "missing" else f"- {field}: `{'' if mutation == 'blank' else 'pending'}`"
                        path.write_text(prefix.replace(line, replacement) + "## Approval\n" + approval)
                    self.assertFalse(self.grade(mutate)["passed"])

    def test_joint_approval_identity_and_time_must_be_consistent(self):
        for old, new in (("fixture user", "another approver"), ("2026-08-29", "2026-08-28")):
            with self.subTest(field=old):
                self.assertFalse(self.grade(lambda repo, h: self.edit_approval(
                    repo, h.PLAN_PATH, lambda block: block.replace(old, new)))["passed"])


if __name__ == "__main__":
    unittest.main()
