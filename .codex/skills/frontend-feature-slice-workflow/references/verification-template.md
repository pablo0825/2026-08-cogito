# Feature Slice Verification Template

建立 `docs/verification/<ID>/<ID>-<name>-verification.md`。每項檢查只記錄最新結果，並只保留目前人工驗收與未解決問題；重跑時取代舊結果，已解決 failure、revision summary、batch history 與 commit record 由 Git 保存。不要複製 Plan 或 Git history。Blueprint 是 Slice 狀態的唯一來源；只有使用者能更新 Human Integration 與 Human Acceptance。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

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

| Check | Command / Method | Result | Evidence | Notes |
|---|---|---|---|---|
| Build | `<command>` | passed | exit code 0 | <notes> |
| Tests | `<command>` | not-run | <reason> | <risk or release impact> |

Result 只使用 `passed`、`failed`、`not-run`、`not-applicable`。

同一 check 只保留一列目前結果。重跑後直接取代先前列；已解決的 `failed` 不移入其他章節。

## Acceptance Evidence

| Spec Criterion | Result | Evidence |
|---|---|---|
| <Target or Preserved Behavior> | <result> | <evidence> |

此表記錄目前證據，不是要求使用者逐項重跑的 Human Acceptance checklist。

## Human Integration

- Status: `pending | passed | failed | not-applicable`
- Confirmed By: `pending`
- Confirmed At: `pending`
- Notes: `pending`

## Human Acceptance Instructions

原則上只列 3–5 個最高價值場景；只有較少獨立人類判斷時可以少於 3 個。不要複製 AI Verification、技術 assertions 或 browser／viewport／state matrix。

### Context

- Environment / Service: <只有需要真實環境或外部服務時填寫>
- Account / Test Data: <完成場景所需的最少資料>
- Representative Device: <只有裝置體驗需要人類判斷時填寫>

每項 Context 最多一句；不加入準備流程或技術檢查清單。

### High-Value Scenarios

| Scenario | User Goal | Human Judgment |
|---|---|---|
| <高價值場景> | <以一句話描述要完成的使用者目標> | <以一句話描述自動化無法可靠判斷的產品結果> |

只使用此表呈現場景。每格使用一句簡短文字；不要改成逐場景章節，也不要加入操作步驟、Expected Results 清單、時間預算、技術檢查或多組排列組合。

### Known Limitations

- <限制；若沒有填寫 `None`>

## Human Acceptance Result

- Status: `pending | passed | failed | changes-requested`
- Confirmed By: `pending`
- Confirmed At: `pending`
- User Feedback: `pending`

## Remaining Issues

- <未解決問題；若沒有填寫 `None`>
