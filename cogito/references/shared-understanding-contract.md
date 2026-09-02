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

等待確認期間修訂摘要後，重新計算 hash，以新的 `action_id` 提交 `shared-understanding-ready`。Gate 追加候選版本並維持 `awaiting-shared-confirmation`，`next` 回傳目前的 `shared_understanding_hash`。再次向使用者呈現此版本；收到確認後，以 `shared-understanding-confirmed` 提交 `{"confirmed":true,"shared_understanding_hash":"<目前摘要hash>"}`。曾修訂摘要的 run 必須明確帶最新 hash，缺少或沿用舊 hash 都會被拒絕；未曾修訂的歷史操作仍相容原本僅有 `confirmed` 的 payload。摘要確認後不接受此自循環，不以修訂摘要偷偷改動後續契約。
