# Shared Understanding Contract

Readiness 只有：

- `ready`：建立準確契約所需的產品決策與關鍵事實均已確定。
- `blocked`：仍缺必要產品決策，或關鍵事實沒有足以支持契約的證據。

摘要使用下列固定結構；沒有 Slice ID 時不得猜測或預留：

```markdown
# Shared Understanding

## Confirmed Decisions
## Verified Facts
## Recommended Defaults
## Deferred Decisions
## Explicitly Excluded
## Remaining Risks
## Blocking Questions

---

Shared Understanding: awaiting-confirmation | confirmed
Readiness: ready | blocked
```

空欄寫「無」，未知事項不得冒充空值。Recommended Defaults 只有經使用者明確選定才成為 Decision；摘要確認本身不會轉換分類。Verified Facts 必須附來源，程式現況不自動等於產品應有行為。

本檔只定義摘要內容與 readiness。呈現、確認、修訂與保存版本依 [Grilling Workflow](grilling-workflow.md#呈現與確認摘要)；確認後不為更新 footer 改寫已凍結原文，狀態由事件與 checkpoint 表達。
