import json
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (COGITO / relative_path).read_text(encoding="utf-8")


class ControlledParallelContractTests(unittest.TestCase):
    def test_parallel_mode_is_opt_in_and_preserves_existing_modes(self) -> None:
        skill = read("SKILL.md")
        blueprint = read("references/blueprint-template.md")
        workflow = read("references/controlled-parallel-workflow.md")

        for mode in ("legacy-staged", "sequential-package", "controlled-parallel"):
            self.assertIn(mode, skill)
            self.assertIn(mode, blueprint)
        self.assertIn("既有 blueprint 不會自動升級", workflow)
        self.assertIn("project-level Blueprint Revision", workflow)

    def test_parallel_reference_is_routed_from_affected_stages(self) -> None:
        reference = "controlled-parallel-workflow.md"
        self.assertTrue((COGITO / "references" / reference).is_file())
        for relative_path in (
            "SKILL.md",
            "references/grilling-workflow.md",
            "references/spec-plan-workflow.md",
            "references/blueprint-workflow.md",
            "references/implementation-workflow.md",
            "references/verification-acceptance-workflow.md",
            "references/commit-workflow.md",
        ):
            with self.subTest(path=relative_path):
                self.assertIn(reference, read(relative_path))

    def test_wave_requires_analysis_approval_and_is_time_bounded(self) -> None:
        workflow = read("references/controlled-parallel-workflow.md")

        for required in (
            "Parallel Readiness Analysis",
            "Read Set",
            "Write Set",
            "Integration Surface",
            "Parallel Wave Proposal",
            "Approval Expires At",
            "有效期固定為 2 小時",
            "不得建立 worktree、branch、commit 或啟動 Worker",
        ):
            with self.subTest(required=required):
                self.assertIn(required, workflow)

    def test_compatibility_classes_make_shared_work_explicit(self) -> None:
        workflow = read("references/controlled-parallel-workflow.md")

        for classification in (
            "independent",
            "coordinated-overlap",
            "shared-predecessor-required",
            "serial-only",
        ):
            self.assertIn(classification, workflow)
        self.assertIn("不得靜默建立、核准或執行該 Slice", workflow)
        self.assertIn("orchestration change", workflow)

    def test_workers_are_isolated_and_cannot_change_approved_boundaries(self) -> None:
        workflow = read("references/controlled-parallel-workflow.md")

        self.assertIn("同時最多 `3` 個 Worker", workflow)
        self.assertIn("Wave 的 1–3 個 exact Execution Candidates", workflow)
        self.assertIn("專用 worktree", workflow)
        self.assertIn("專用 branch", workflow)
        for boundary in (
            "已核准行為",
            "公開契約",
            "資料模型",
            "安全邊界",
            "Slice 責任",
            "依賴或順序",
        ):
            self.assertIn(boundary, workflow)

    def test_review_and_integration_use_one_serial_gate(self) -> None:
        workflow = read("references/controlled-parallel-workflow.md")
        verification = read("references/verification-template.md")

        self.assertIn("序列 Review／Integration Gate", workflow)
        self.assertIn("任何時刻不得同時 review 或 integrate 兩個 Slice", workflow)
        self.assertIn("low", workflow)
        self.assertIn("可依核准 strategy 自動序列整合", workflow)
        self.assertIn("high", workflow)
        self.assertIn("明確核准該 code checkpoint 前不得整合", workflow)
        self.assertIn("Integration Status", verification)
        self.assertIn("Integration Checks", verification)

    def test_behavioral_evals_cover_parallel_happy_and_stop_paths(self) -> None:
        scenarios = {
            case.get("scenario")
            for case in json.loads(read("evals/evals.json"))["evals"]
        }
        self.assertTrue(
            {
                "parallel-wave-proposal-does-not-start-workers",
                "parallel-wave-expired-approval-does-not-run",
                "parallel-shared-predecessor-requires-decision",
                "parallel-workers-only-change-internal-code-and-tests",
                "parallel-review-and-integration-are-serialized",
                "parallel-unexpected-conflict-stops-integration",
            }.issubset(scenarios)
        )

    def test_version_adds_controlled_parallel_as_a_minor_release(self) -> None:
        self.assertEqual(read("VERSION").strip(), "2.2.0")


if __name__ == "__main__":
    unittest.main()
