# Requirement Grilling Workflow

Grilling 只取得足以形成正確契約的共同理解，不要求使用者回答 AI 可從專案查證的事實，也不預先建立 Slice ID。

## 初始化與查證

建立或恢復 `DEV-*` run，依 Gate 的 `next_action` 讀取適用需求來源、程式、測試與 Git 證據，區分 `Decision`、`Verified Fact`、`Assumption`。開始時集中完成必要初始化與查證，不為問答額外建立獨立的 `intake.md`、`git-baseline` 或 `source-registry` 文件。

`preparing` 的 `draft-shared-understanding` action 涵蓋需求問答，不代表 readiness 尚未達到 `ready` 就必須建立完整摘要。

同一 Grilling action 內的連續純需求問答沿用本輪已讀取的政策與專案資訊。一般回答後直接提出下一個必要問題；只有發現影響需求判斷或下一題的新事實缺口、資訊可能已變動，或 Gate 要求操作時，才補做相關工具操作。必要事實仍須查證，不延後到 Package 階段才發現需求前提錯誤。

## 決策樹與提問

以目標使用者結果為根建立決策樹。`frontier` 是前置決策已確定、現在可詢問的必要問題；依賴本輪未決答案的問題留到後續輪次。本節的問答輪次不是 Gate 的 `planning_round`，不因開始下一輪提問而執行 `planning begin`。

優先釐清阻塞正確 Spec 的需求決策：Scope、影響後續切片的需求邊界、使用者可見行為、Acceptance、保留行為、外部整合、相容性與重大風險。內部實作細節留給 Plan。

1. 每輪選取最高價值的必要問題，最多五題、不設下限、不湊題數；先只列題目名稱，再展開第一題。
2. 每次只詢問一個獨立決策並等待回答，不合併獨立決策，也不要求填寫複合欄位。
3. 回答後更新決策樹，重排或移除剩餘題目；本輪 frontier 處理完才公布下一輪，不將依賴本輪新答案的問題插入本輪。資訊已足夠時直接形成摘要，不為完成題單而繼續追問。
4. 依 [shared-understanding-contract.md](shared-understanding-contract.md) 判斷 readiness。`ready` 才產出摘要；`blocked` 說明缺少的決策或證據。

## 集中保存與摘要確認

決策樹更新不要求逐題寫檔。不得因單題回答而建立或重寫完整 intake、摘要或來源清冊；每輪結束或明確暫停時，集中保存精簡問答進度，記錄已確認決策、必要事實與來源、未決問題及下一步。優先沿用 `.cogito/runs/<run-id>/drafts/` 內既有的問答進度檔，沒有時只建立一份，不拆成多份配套文件。單純切換話題不觸發保存；本輪結束且已可產出摘要時，直接保存摘要，不另寫一份重複進度。

問答進度是未確認草稿，不是正式階段 checkpoint；保存進度本身不新增 Gate event 或 Git commit，也不取代 Gate event history、核准或 evidence。恢復執行或更換 Agent 時先查詢 Gate、讀取適用政策與 Git 狀態，再對照已保存進度與可用對話補齊尚未保存的答案；缺失決策仍視為未決，不自行猜測。正式 `source_registry` 與所需 hashes 在 Package 準備時整理；Gate、摘要與階段提交當下要求的文件、hash 或基線仍須即時提供。

`ready` 後，未確認摘要保存在 `.cogito/runs/<run-id>/drafts/shared-understanding.md`。準備呈現摘要時，將相同 bytes 放到 `docs/cogito/shared-understanding/<run-id>-r<round>.md`；`shared-understanding-ready` 帶此文件的 `document: {"path": "...", "hash": "..."}` 及相同的 `shared_understanding_hash`。使用者確認後提交 confirmation，立即依 [Stage Commits](stage-commits.md) 建立摘要 commit。只提交確認的版本，不提交整個 drafts 目錄。

摘要已呈現、等待確認時，使用者要求修訂仍依 Shared Understanding Contract 更新文件、重新計算 hash 並提交新的 `shared-understanding-ready`；不得以集中保存規則略過候選版本更新。

摘要確認表示內容正確，並授權保存此版摘要及階段紀錄的本地 Git commit。Gate 進入 Boundary analysis 前的下一步先要求完成摘要 checkpoint；此確認不授權實作。若後續發現會改變 Scope、Acceptance、公開契約、資料模型、安全邊界或 Slice 責任的差異，回到 Grilling；純技術缺口則走 Technical Amendment 或 correction loop。
