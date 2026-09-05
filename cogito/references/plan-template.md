# Feature Slice Plan Template

建立 `docs/plans/<ID>/<ID>-<name>-plan.md`。Plan 定義實作與驗證方法，不重述 Spec、不含 approval/status metadata、Commit Plan 或執行結果。

```markdown
# <ID> — <Feature Name> Plan

## Based On
- Spec: `<path>`

## Implementation Goal

## Current Assessment
### Gaps
### Reusable Components / Integration Points
### Preserved Behavior / Regression Risks
### Constraints / Unknowns

## Files
### Create
### Modify
### Tests

## Tasks
| Task ID | Depends On | Allowed Paths | Responsibility | Targeted Check IDs |
|---|---|---|---|---|
| T-001 | `none` | `<paths>` | <單一行為或必要共同基礎，含測試與文件> | `<check_ids>` |

每個 Task 獨立 commit。預計超過 15 個 production files 或包含可分離流程時，拆分或在此說明理由。

## Integration Strategy
<順序、共享區域 owner、衝突策略與 delivery branch>

## Checks
| Check ID | Acceptance IDs | Gate | Phase | Applicability / Selection Reason | argv / Method |
|---|---|---|---|---|---|
| V-001 | AI-001 | `required` | `task` | <變更行為及受影響依賴> | `<argv array>` |
| V-002 | AI-001 | `required` | `integration` | <整合後相關檢查> | `<argv array>` |

完整 regression 由 CI 執行；本地只列相關檢查。CI 狀態依實際結果回報，不以本地通過代替。

## Human Integration
| ID | Requirement | Applicability |
|---|---|---|
| HI-001 | <不可自動完成的整合作業> | `<固定 predicate>` |

## Risks / Open Issues
None
```

Gate 只使用 `required`、`advisory`、`human`。每個 `AI-*` 至少由充分的 required evidence 覆蓋；predicate 在 Package 核准時固定，不能依 Agent 選擇規避。沒有 Human Integration 時寫 `None`。
