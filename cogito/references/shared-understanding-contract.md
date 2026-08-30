# Shared Understanding Contract

定義 Grilling 的共同理解摘要格式、Readiness 判準、確認方式與確認效力；何時停止問答、產出摘要及確認後的階段流程由 [grilling-workflow.md](grilling-workflow.md) 管理。

## Readiness 判準

Readiness 判斷目前需求是否足以建立準確 Spec；Shared Understanding 只記錄使用者是否確認摘要正確，兩者分開判定。

- `ready`：目前 Spec 所需的產品決策與關鍵事實已釐清，沒有阻塞需求成立或驗收的未決事項。
- `blocked`：仍有必要產品決策未定，或支撐目前需求的關鍵事實尚未確認。摘要可以被確認為正確，但確認本身不解除阻塞。

關鍵事實是查證結果可能迫使目前 Spec 的 Scope、使用者可見行為、Acceptance、必要相容性或可行性改變的事實。這些事實必須有證據支持；尚未驗證的關鍵假設，即使使用者表示願意承擔風險，也不能據此標為 `ready`，或以 `default`、`defer`、`prune` 的分類解除阻塞。

已查明的風險，若產品應對行為與驗收條件明確，且經使用者明確接受，不阻擋 `ready`。風險接受不等於將未知的關鍵能力視為已驗證，也不保證外部系統每次都成功。

不影響目前 Spec 的內部實作安排，可留到 Plan 或實作階段；不阻塞目前 Spec 的其他未知事項可揭露並延後，不要求所有工程細節都已決定。

## 摘要格式與確認

共同理解摘要使用以下格式：

```text
Confirmed Decisions
Verified Facts
Recommended Defaults
Deferred Decisions
Explicitly Excluded
Remaining Risks
Blocking Questions

Shared Understanding: awaiting-confirmation | confirmed
Readiness: ready | blocked
```

沿用上述欄位記錄查證與阻塞，不另外建立文件：

- `Verified Facts`：已確認的事實及其證據來源；未驗證假設不得列為事實。
- `Remaining Risks`：已查明風險、產品應對行為、驗收條件與使用者接受情況。
- `Deferred Decisions`：不阻塞目前 Spec 的延後事項，說明為何不影響目前需求與驗收；待查事實仍標明未驗證。
- `Blocking Questions`：必要未決事項、對 Spec 的影響與解除阻塞的條件；註明是由 AI 查證或由使用者決策。AI 查證受阻時列出缺少的證據或存取條件，不把事實調查改成要求使用者猜答案。

等待使用者明確確認摘要。摘要確認屬於同一 Grilling 階段，不需要重複 `$cogito`；修正摘要時直接取代失效結論，不累積 revision history。

## 確認效力與保存

摘要確認只表示內容正確，不授權修改 `docs/project/`、Blueprint、Spec 或 Plan，不核准實作，也不授權 commit。

完整問答留在對話中。Canonical 文件只在取得適用授權後保存目前有效的結論，不建立 Requirement Interview history 文件。
