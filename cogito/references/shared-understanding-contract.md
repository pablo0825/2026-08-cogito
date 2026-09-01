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

等待確認時明說：「確認只表示摘要內容正確；確認後會自動準備 Boundary Gate、Slice／Spec／Plan 與 Development Package，但 Package Approval 前不會實作或 commit。」使用者修正摘要不等於核准；更新後繼續等待確認。
