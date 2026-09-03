# Requirement Grilling Workflow

Grilling 只取得足以形成正確契約的共同理解，不要求使用者回答 AI 可從專案查證的事實，也不預先建立 Slice ID。

## 執行

1. 建立 `DEV-*` run，讀取適用需求來源、程式、測試與 Git 證據，區分 `Decision`、`Verified Fact`、`Assumption`。
2. 以使用者結果為根建立 decision frontier。每輪最多五個必要題目，先列題名，再逐題詢問；回答後重排剩餘問題。
3. 優先釐清 Scope、Acceptance、保留行為、公開整合、相容性與重大風險。內部實作細節留給 Plan。
4. 依 [shared-understanding-contract.md](shared-understanding-contract.md) 判斷 readiness。`ready` 才產出摘要；`blocked` 說明缺少的決策或證據。
5. 未確認草稿保存在 `.cogito/runs/<run-id>/drafts/shared-understanding.md`。準備呈現摘要時，將相同 bytes 放到 `docs/cogito/shared-understanding/<run-id>-r<round>.md`；`shared-understanding-ready` 帶此文件的 `document: {"path": "...", "hash": "..."}` 及相同的 `shared_understanding_hash`。使用者確認後提交 confirmation，立即依 [Stage Commits](stage-commits.md) 建立摘要 commit。只提交確認的版本，不提交整個 drafts 目錄。

摘要確認表示內容正確，並授權保存此版摘要及階段紀錄的本地 Git commit。Gate 進入 Boundary analysis 前的下一步先要求完成摘要 checkpoint；此確認不授權實作。若後續發現會改變 Scope、Acceptance、公開契約、資料模型、安全邊界或 Slice 責任的差異，回到 Grilling；純技術缺口則走 Technical Amendment 或 correction loop。
