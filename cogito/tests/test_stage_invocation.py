import json
import re
import unittest
from pathlib import Path


COGITO = Path(__file__).resolve().parents[1]


def read(relative_path: str) -> str:
    return (COGITO / relative_path).read_text(encoding="utf-8")


class StageInvocationContractTests(unittest.TestCase):
    def test_package_enables_contextual_continuation(self) -> None:
        metadata = read("agents/openai.yaml")
        skill = read("SKILL.md")

        self.assertRegex(metadata, r"allow_implicit_invocation:\s*true")
        self.assertIn("immediately preceding unresolved prompt", skill)

    def test_skill_defines_same_stage_continuation_gate(self) -> None:
        skill = read("SKILL.md")

        self.assertIn("啟動與續接閘門", skill)
        self.assertRegex(skill, r"沒有 `\$cogito`.*直接回應.*未決")
        self.assertRegex(skill, r"新階段.*必須.*`\$cogito`")
        self.assertRegex(skill, r"`\$cogito`.*不.*核准")

    def test_grilling_keeps_answers_and_summary_confirmation_in_stage(self) -> None:
        workflow = read("references/grilling-workflow.md")
        contract_path = re.search(
            r"完整讀取 \[shared-understanding-contract\.md\]\(([^)]+)\)", workflow
        )
        self.assertIsNotNone(contract_path)
        contract = read(f"references/{contract_path.group(1)}")

        self.assertRegex(workflow, r"回答.*反問.*不需要.*`\$cogito`")
        self.assertRegex(contract, r"摘要確認.*同一.*Grilling.*不需要.*`\$cogito`")
        self.assertRegex(workflow, r"Boundary Gate.*新.*`\$cogito`")

    def test_evals_cover_continuation_and_stage_boundaries(self) -> None:
        evals = json.loads(read("evals/evals.json"))["evals"]
        scenario_names = {case.get("scenario") for case in evals}

        self.assertTrue(
            {
                "same-stage-direct-answer",
                "same-stage-clarification",
                "same-stage-approval",
                "stage-handoff-requires-explicit-invocation",
                "scope-expansion-requires-explicit-invocation",
                "ordinary-request-does-not-start-cogito",
                "explicit-invocation-is-not-approval",
                "implementation-to-verification-handoff",
                "interruption-requires-explicit-invocation",
                "grilling-to-boundary-handoff",
                "boundary-to-spec-plan-handoff",
                "acceptance-feedback-to-grilling-handoff",
                "verification-to-plan-revision-handoff",
            }.issubset(scenario_names)
        )
        verification_failure = next(case for case in evals if case["id"] == 10)
        self.assertNotIn("提出 fix batch", verification_failure["expected_output"])
        self.assertIn("新的 $cogito", verification_failure["expected_output"])

    def test_spec_approval_cannot_start_implementation(self) -> None:
        workflow = read("references/spec-plan-workflow.md")
        commits = read("references/commit-workflow.md")

        self.assertNotIn("複合授權", workflow)
        self.assertNotRegex(commits, r"同一訊息.*開始實作")
        self.assertNotRegex(commits, r"複合實作授權")

    def test_implementation_stops_before_ai_verification(self) -> None:
        implementation = read("references/implementation-workflow.md")
        commits = read("references/commit-workflow.md")

        self.assertNotRegex(implementation, r"授權涵蓋.*完整 AI Verification")
        self.assertNotRegex(implementation, r"直接進入完整 AI Verification")
        self.assertNotRegex(commits, r"implementation.*完整 AI Verification")
        self.assertRegex(implementation, r"最後一個 implementation commit.*停止")
        self.assertRegex(implementation, r"\$cogito.*AI Verification")

    def test_grilling_routes_stop_before_boundary_gate(self) -> None:
        expected_text = {
            "references/blueprint-workflow.md": (
                "共同理解確認後停止",
                "以新的 `$cogito` 訊息啟動 Boundary Gate",
            ),
            "references/rolling-adoption-workflow.md": (
                "共同理解確認後停止",
                "以新的 `$cogito` 訊息啟動 Boundary Gate",
            ),
            "references/spec-plan-workflow.md": (
                "Grilling 確認後必須停止",
                "Boundary Gate 必須由新的 `$cogito` 訊息啟動",
            ),
        }
        for path, required_text in expected_text.items():
            workflow = read(path)
            for text in required_text:
                self.assertIn(text, workflow)

    def test_boundary_gate_stops_before_spec_plan(self) -> None:
        workflow = read("references/spec-plan-workflow.md")

        self.assertIn("Boundary Gate 通過後停止", workflow)
        self.assertRegex(workflow, r"新的 `\$cogito`.*Spec／Plan")

    def test_acceptance_feedback_does_not_combine_grilling_and_boundary(self) -> None:
        workflow = read("references/verification-acceptance-workflow.md")

        self.assertNotIn("`$cogito` 回到 Grilling 與 Boundary Gate", workflow)
        self.assertRegex(workflow, r"Grilling.*停止.*另一個新的 `\$cogito`.*Boundary Gate")

    def test_recovery_and_remediation_routes_require_new_stage_starts(self) -> None:
        grilling = read("references/grilling-workflow.md")
        spec_plan = read("references/spec-plan-workflow.md")
        verification = read("references/verification-acceptance-workflow.md")
        commits = read("references/commit-workflow.md")

        self.assertNotIn("重新進入 Grilling 並重跑 Gate", grilling)
        self.assertRegex(spec_plan, r"結果失效.*`\$cogito`.*Grilling.*停止.*`\$cogito`.*Boundary Gate")
        self.assertNotRegex(verification, r"取得授權後才.*修訂.*Plan")
        self.assertNotRegex(commits, r"取得明確 revision 授權後新增 `fix` batch")

    def test_version_marks_summary_title_and_prompt_patch(self) -> None:
        self.assertEqual(read("VERSION").strip(), "2.0.14")


if __name__ == "__main__":
    unittest.main()
