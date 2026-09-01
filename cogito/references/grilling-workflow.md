# Requirement Grilling Workflow

Grilling 只取得足以形成正確契約的共同理解，不要求使用者回答 AI 可從專案查證的事實，也不預先建立 Slice ID。

## 執行

1. 建立 `DEV-*` run，讀取適用需求來源、程式、測試與 Git 證據，區分 `Decision`、`Verified Fact`、`Assumption`。
2. 以使用者結果為根建立 decision frontier。每輪最多五個必要題目，先列題名，再逐題詢問；回答後重排剩餘問題。
3. 優先釐清 Scope、Acceptance、保留行為、公開整合、相容性與重大風險。內部實作細節留給 Plan。
4. 依 [shared-understanding-contract.md](shared-understanding-contract.md) 判斷 readiness。`ready` 才產出摘要；`blocked` 說明缺少的決策或證據。
5. 草稿保存在 `.cogito/runs/<run-id>/drafts/shared-understanding.md`。使用者確認後凍結其 hash，提交 Gate；不要 commit 草稿。

摘要確認只表示內容正確。確認後 Gate 自動進入 Boundary analysis；不得把確認解讀成建立文件、commit 或實作授權。若後續發現會改變 Scope、Acceptance、公開契約、資料模型、安全邊界或 Slice 責任的差異，回到 Grilling；純技術缺口則走 Technical Amendment 或 correction loop。
