# Feature Slice Verification Template

建立 `docs/verification/<ID>/<ID>-<name>-verification.md`。以 Plan Check ID 記錄最新執行結果，以 Spec Acceptance ID 記錄目前 closure；重跑時取代舊結果，已解決 failure、revision summary、batch history 與 commit record 由 Git 保存。不要複製 Spec、Plan 或 Git history。Blueprint 是 Slice 狀態的唯一來源；只有使用者能更新 Human Integration 與 Human Acceptance。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# <ID> — <Feature Name> Verification

## Document Information

- Feature Slice: `<ID>`
- Verification Status: `in-progress | awaiting-human | completed`
- Created: `<YYYY-MM-DD>`
- Last Updated: `<YYYY-MM-DD>`

## Implementation Summary

- <主要實作>
- <已知限制或未執行項目>

## Changed Files

| File | Change |
|---|---|
| `<path>` | <摘要> |

## AI Verification

| Check ID | Acceptance IDs | Gate | Applicability Evaluation | Command / Method | Result | Evidence | Notes |
|---|---|---|---|---|---|---|---|
| V-001 | AI-001 | `required` | `always` | `<command>` | passed | exit code 0 | <notes> |
| V-002 | AI-001, AI-002 | `advisory` | `<approved predicate>: false` | `<method>` | not-applicable | <objective predicate evidence> | <risk or release impact> |

Result 只使用 `passed`、`failed`、`not-run`、`not-applicable`。
Gate 在此表只使用 `required` 或 `advisory`；`human` 項目記錄於 Human Integration／Acceptance。`required` 的 `failed` 或 `not-run` 必須列入 Remaining Issues 並阻止進入 `awaiting-human`；`advisory` 的 `failed` 或 `not-run` 不阻擋，但必須揭露風險與 release impact。

同一 Check ID 只保留一列目前結果。重跑後直接取代先前列；已解決的 `failed` 不移入其他章節。`not-applicable` 必須引用 Plan 核准的 predicate 並記錄其為 false 的客觀證據；環境、權限、依賴或工具限制使用 `not-run`。

## Acceptance Evidence

| Acceptance ID | Result | Supporting Check IDs | Evidence |
|---|---|---|---|
| AI-001 | `satisfied | unsatisfied | pending` | V-001 | <current objective evidence> |

此表記錄目前證據，不是要求使用者逐項重跑的 Human Acceptance checklist。

## Independent Code Review

`Execution Mode: legacy-staged` 且沒有獨立 review 要求時填寫 `Not applicable — legacy-staged`。`sequential-package` 與 `controlled-parallel` 必須由未參與該 Slice 實作的獨立 Review Agent 完整填寫；無法取得 Reviewer 時不得建立自我審查結果。parallel mode 另須保存 Wave 與 integration evidence。

- Review Status: `pending | passed | blocked`
- Reviewer: `<independent agent identity or pending>`
- Reviewed Baseline: `<approved baseline and reviewed diff>`
- Risk Classification: `low | high`
- Review-Fix Rounds Used: `<0-3>`
- Recommendation: `approve | fix | block`
- Conformance: <Spec／Plan、Scope、Files 與停止條件的一致性結論>
- Test Adequacy: <Acceptance coverage 與 evidence 缺口>
- Wave / Queue: `<Wave ID and review queue position or not-applicable>`
- Worker Baseline: `<Base Revision, worker branch and actual Write Set or not-applicable>`
- Integration Status: `not-applicable | queued | awaiting-human-code-review | integrated | blocked`
- Integration Baseline: `<post-integration revision or pending>`
- Integration Checks: `<commands and current results or pending>`

### Risk Hotspots

| File / Lines | Risk | Worst Impact | Evidence / Gap | Rollback | User Action |
|---|---|---|---|---|---|
| `<path>:<line>` | <風險或 `None`> | <最壞影響> | <證據或缺口> | <回滾方式> | `review | none` |

低風險且沒有 hotspot 時填寫一列 `None`。高風險必須精確指出需要使用者閱讀的程式碼段落；blocking finding 未解決、required evidence 不足或 Recommendation 不是 `approve` 時不得進入 `awaiting-human`。

## Human Integration

| ID | Requirement | Status | Evidence | Confirmed By | Confirmed At |
|---|---|---|---|---|---|
| HI-001 | <Plan requirement> | `pending | passed | failed | not-applicable` | <evidence> | pending | pending |

## Human Acceptance Instructions

原則上只列 3–5 個最高價值場景；只有較少獨立人類判斷時可以少於 3 個。不要複製 AI Verification、技術 assertions 或 browser／viewport／state matrix。

### Context

- Environment / Service: <只有需要真實環境或外部服務時填寫>
- Account / Test Data: <完成場景所需的最少資料>
- Representative Device: <只有裝置體驗需要人類判斷時填寫>

每項 Context 最多一句；不加入準備流程或技術檢查清單。

### High-Value Scenarios

| Acceptance IDs | Scenario | User Goal | Human Judgment |
|---|---|---|---|
| HA-001, HA-002 | <高價值場景> | <以一句話描述要完成的使用者目標> | <以一句話描述自動化無法可靠判斷的產品結果> |

只使用此表呈現場景。每格使用一句簡短文字；不要改成逐場景章節，也不要加入操作步驟、Expected Results 清單、時間預算、技術檢查或多組排列組合。

### Known Limitations

- <限制；若沒有填寫 `None`>

## Human Acceptance Result

- Confirmed By: `pending`
- Confirmed At: `pending`

| Acceptance IDs | Status | User Feedback |
|---|---|---|
| HA-001, HA-002 | `pending | passed | failed | changes-requested` | pending |

## Remaining Issues

- <未解決問題；若沒有填寫 `None`>
