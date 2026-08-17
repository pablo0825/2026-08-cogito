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
| Tests | `<command>` | not-run | <reason> | <human follow-up> |

Result 只使用 `passed`、`failed`、`not-run`、`not-applicable`。

同一 check 只保留一列目前結果。重跑後直接取代先前列；已解決的 `failed` 不移入其他章節。

## Acceptance Evidence

| Spec Criterion | Result | Evidence |
|---|---|---|
| <Target or Preserved Behavior> | <result> | <evidence> |

## Human Integration

- Status: `pending | passed | failed | not-applicable`
- Confirmed By: `pending`
- Confirmed At: `pending`
- Notes: `pending`

## Human Acceptance Instructions

### Preconditions and Test Data

- <環境、帳號及測試資料>

### Browser / Device / Viewport

- <建議驗收環境>

### Steps and Expected Results

| Step | Action | Expected Result |
|---|---|---|
| 1 | <操作> | <預期結果> |

### Known Limitations

- <限制；若沒有填寫 `None`>

## Human Acceptance Result

- Status: `pending | passed | failed | changes-requested`
- Confirmed By: `pending`
- Confirmed At: `pending`
- User Feedback: `pending`

## Remaining Issues

- <未解決問題；若沒有填寫 `None`>
