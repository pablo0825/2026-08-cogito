import json
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (COGITO / relative_path).read_text(encoding="utf-8")


class SequentialPackageContractTests(unittest.TestCase):
    def test_execution_mode_is_opt_in_and_legacy_is_the_fallback(self) -> None:
        skill = read("SKILL.md")
        blueprint = read("references/blueprint-template.md")

        self.assertIn("Execution Mode", blueprint)
        self.assertIn("legacy-staged", blueprint)
        self.assertIn("sequential-package", blueprint)
        self.assertIn("缺少 `Execution Mode`", skill)
        self.assertIn("`legacy-staged`", skill)

    def test_package_reference_is_routed_from_every_affected_stage(self) -> None:
        reference = "development-package-workflow.md"
        self.assertTrue((COGITO / "references" / reference).is_file())
        for relative_path in (
            "SKILL.md",
            "references/grilling-workflow.md",
            "references/spec-plan-workflow.md",
            "references/implementation-workflow.md",
            "references/verification-acceptance-workflow.md",
            "references/commit-workflow.md",
        ):
            with self.subTest(path=relative_path):
                self.assertIn(reference, read(relative_path))

    def test_package_authority_has_preparation_execution_and_stop_boundaries(self) -> None:
        workflow = read("references/development-package-workflow.md")

        for required in (
            "Preparation Authority",
            "Package Approval",
            "Final Approval",
            "內部實作與測試",
            "公開契約",
            "資料模型",
            "安全邊界",
            "Slice 責任範圍",
            "不得開始實作",
            "最多 3 輪",
            "獨立 Review Agent",
            "無法取得獨立 Reviewer",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)

    def test_split_can_be_prepared_but_not_executed_before_approval(self) -> None:
        workflow = read("references/development-package-workflow.md")

        self.assertIn("拆分候選", workflow)
        self.assertIn("Spec／Plan draft", workflow)
        self.assertIn("恰好一個 `Execution Candidate`", workflow)
        self.assertIn("等待 Package Approval", workflow)
        self.assertIn("不啟動任何候選 Slice", workflow)

    def test_plan_and_verification_templates_capture_package_evidence(self) -> None:
        plan = read("references/plan-template.md")
        verification = read("references/verification-template.md")

        for field in (
            "## Development Package",
            "Execution Mode",
            "Approved Baseline",
            "Autonomy Budget",
            "Review-Fix Budget",
            "Stop Conditions",
        ):
            self.assertIn(field, plan)
        for field in (
            "## Independent Code Review",
            "Risk Classification",
            "Risk Hotspots",
            "Recommendation",
        ):
            self.assertIn(field, verification)

    def test_behavioral_evals_cover_package_happy_and_stop_paths(self) -> None:
        scenarios = {
            case.get("scenario")
            for case in json.loads(read("evals/evals.json"))["evals"]
        }
        self.assertTrue(
            {
                "package-mode-auto-prepares-after-grilling",
                "package-mode-split-prepares-and-waits",
                "package-approval-runs-through-independent-review",
                "package-review-fix-budget-exhausted",
                "package-review-high-risk-stops",
                "package-reviewer-unavailable-stops",
            }.issubset(scenarios)
        )

    def test_version_adds_package_mode_as_a_minor_release(self) -> None:
        self.assertGreaterEqual(tuple(map(int, read("VERSION").strip().split("."))), (2, 1, 0))


if __name__ == "__main__":
    unittest.main()
