# Feature Slice Spec Template

建立 `docs/specs/<ID>/<ID>-<name>-spec.md`。Spec 只定義產品語意與可驗收契約，不包含 approval/status、實作步驟、commit 或執行紀錄。

```markdown
# <ID> — <Feature Name> Spec

## Change Context
- Type: `feature | change | correction`
- Revises: `<ID or none>`
- Corrects: `<ID or none>`
- Source References: `<paths and sections>`

## User Outcome
<使用者、目標與價值>

## Behavior
### Current
### Target
### Preserved

## Input / Output

## Rules
1. <可驗收規則>

## Included

## Excluded

## Integration Contract
<公開輸入、輸出、錯誤與可觀察狀態；不指定不必要實作>

## AI Acceptance
| ID | Criterion |
|---|---|
| AI-001 | <客觀可驗證結果> |

## Human Acceptance
| ID | Criterion | Applicability |
|---|---|---|
| HA-001 | <只能由人判斷的高價值結果> | `<Package 固定 predicate>` |

## Open Questions
None
```

每個 Acceptance ID 在 Slice 內穩定且不重用。沒有真正需要人判斷的結果時，Human Acceptance 寫 `None`；不要把可自動驗證項目轉交人類。
