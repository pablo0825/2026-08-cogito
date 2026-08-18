# Feature Slice Plan Template

## Contents

- Document and implementation assessment
- Files, steps, and risks
- Verification and human checkpoints
- Commit Plan and approval

建立 `docs/plans/<ID>/<ID>-<name>-plan.md`。Plan 定義目前有效的實作方式、Acceptance-to-check mappings 與尚未完成的工作，不重述 Spec criteria。每個尚未完成的 implementation batch 對應一個 commit，Files 使用有限且具體的路徑。完成 checkpoint 時從 Commit Plan 移除該 row，不新增 status、execution result、commit ID 或 revision summary；詳細歷史由 Git 保存。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# <ID> — <Feature Name> Plan

## Document Information

- Feature Slice: `<ID>`
- Change Type: `feature | change | correction`
- Document Status: `draft`
- Based On Spec: `docs/specs/<ID>/<ID>-<name>-spec.md`
- Spec Last Updated: `<YYYY-MM-DD>`
- Created: `<YYYY-MM-DD>`
- Last Updated: `<YYYY-MM-DD>`

## Implementation Goal

<簡述如何完成 Spec，不增加需求>

## Current Implementation Assessment

### Existing Behavior and Gaps

- <現有實作與 Spec 的落差>

### Reusable Components and Integration Points

- `<path or interface>`：<重用或整合方式>

### Preserved Behavior and Regression Risks

- <必須維持的行為與風險>

### Constraints and Unknowns

- <架構、相容性、環境限制或未知事項；若沒有填寫 `None`>

## Scope Delta

`None`

## Files

### Create

- `<path>`：<用途>

### Modify

- `<path>`：<原因>

### Tests

- `<path>`：<測試範圍>

## Implementation Steps

1. <具體實作與整合步驟>
2. <錯誤與邊界處理>
3. <測試與必要文件更新>

## Risks / Open Issues

| Risk / Issue | Impact | Mitigation / Decision Needed |
|---|---|---|
| <risk> | <impact> | <mitigation> |

若沒有，填寫 `None`。

## Verification Gates

| Check ID | Acceptance IDs | Check | Gate | Applicability | Command / Method |
|---|---|---|---|---|---|
| V-001 | AI-001 | Typecheck | `required` | `always` | `<full verification command>` |
| V-002 | AI-001, AI-002 | <補充檢查> | `advisory` | `<objective predicate>` | `<command or method>` |
| V-003 | HA-001 | <產品判斷> | `human` | `always` | `Human Acceptance` |

Gate 只使用 `required`、`advisory`、`human`。`Applicability` 使用 `always` 或 Plan 核准時即可客觀判定的 predicate；predicate 只控制該 check，不縮小 Spec criterion，也不能依賴 Agent 可操控來迴避檢查的實作選擇。映射到不同 applicability 的 criteria 必須拆成不同 check rows。

每個 `AI-*` 必須有足以完成 criterion 的客觀證據，原則上至少映射一個 `required` check；只有 advisory evidence 不足以完成 Acceptance。每個 `HA-*` 必須映射到 `human`，但一個高價值場景可以涵蓋多個 `HA-*`。AI check 的 `not-run` 不得轉交 Human Acceptance。

## Human Integration

| ID | Requirement | Applicability |
|---|---|---|
| HI-001 | <credentials、OAuth、webhook、部署或第三方服務設定> | `always` 或 <objective predicate> |

若不需要 Human Integration，填寫 `None`。`HI-*` 是 Plan／Verification 的整合前提，不是 Spec Acceptance。

## Commit Plan

Draft Documentation Batch 由建立 Spec／Plan 的要求授權，不受下列 pending 狀態限制。

- Commit Plan Approval: `pending`
- Approved By: `pending`
- Approved At: `pending`
- Implementation Execution: `continuous`

| Batch | Purpose | Files | Required Verification | Proposed Message |
|---|---|---|---|---|
| Approval | 保存核准文件與狀態 | Slice Brief、Spec、Plan、blueprint | 文件一致性 | `docs(<ID>): approve <feature> specification` |
| I1 | <原子實作目的> | `<specific paths>` | <最小充分 checks> | `<type>(<module>): <English summary>` |
| I2 | <依需要增減> | `<specific paths>` | <最小充分 checks> | `<type>(<module>): <English summary>` |
| Verification | 保存完整 AI Verification 與狀態 | Plan、Verification、blueprint | 完整 AI Verification 證據 | `docs(<ID>): record <feature> verification` |
| Final | 記錄最終驗收與狀態 | Spec、Plan、Verification、blueprint、必要 lineage | 文件一致性 | `docs(<ID>): record <feature> acceptance` |

表格只列尚未完成的 checkpoints。Approval、implementation、Verification 或 Final checkpoint 完成並提交時，在同一 commit 移除對應 row；沒有未完成 checkpoint 時以 `None` 取代表格。單純移除已完成 row 不將 Commit Plan Approval 設為 `pending`；修改任何尚未完成 row 仍依實質性重新核准。

Commit Plan 的 `Required Verification` 是 batch commit gate，不取代上方控制 Slice 狀態的完整 Verification Gates。

## Approval

- Approved By: `pending`
- Approved At: `pending`
- Approval Note: `pending`
