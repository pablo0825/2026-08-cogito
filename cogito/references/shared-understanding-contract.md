# Shared Understanding Contract

定義 Grilling 的共同理解摘要格式、確認方式與確認效力；提問、停止條件與確認後的階段流程仍由 [grilling-workflow.md](grilling-workflow.md) 管理。

## 摘要格式與確認

停止時在對話中輸出目前有效的摘要：

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

等待使用者明確確認摘要。摘要確認屬於同一 Grilling 階段，不需要重複 `$cogito`；修正摘要時直接取代失效結論，不累積 revision history。

## 確認效力與保存

摘要確認只表示內容正確，不授權修改 `docs/project/`、Blueprint、Spec 或 Plan，不核准實作，也不授權 commit。

完整問答留在對話中。Canonical 文件只在取得適用授權後保存目前有效的結論，不建立 Requirement Interview history 文件。
