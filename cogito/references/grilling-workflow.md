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

## 保存問答進度

決策樹更新不要求逐題寫檔。不得因單題回答而建立或重寫完整 intake、摘要或來源清冊；每輪結束或明確暫停時，集中保存精簡問答進度，記錄已確認決策、必要事實與來源、未決問題及下一步。優先沿用 `.cogito/runs/<run-id>/drafts/` 內既有的問答進度檔，沒有時只建立一份，不拆成多份配套文件。單純切換話題不觸發保存；本輪結束且已可產出摘要時，直接保存摘要，不另寫一份重複進度。

問答進度是未確認草稿，不是正式階段 checkpoint；保存進度本身不新增 Gate event 或 Git commit，也不取代 Gate event history、核准或 evidence。恢復執行或更換 Agent 時先查詢 Gate、讀取適用政策與 Git 狀態，再對照已保存進度與可用對話補齊尚未保存的答案；缺失決策仍視為未決，不自行猜測。正式 `source_registry` 與所需 hashes 在 Package 準備時整理；Gate、摘要與階段提交當下要求的文件、hash 或基線仍須即時提供。

## 呈現與確認摘要

資訊已足夠、readiness 為 `ready` 時，依 [Shared Understanding Contract](shared-understanding-contract.md) 的固定格式產出摘要，再完成以下順序：

1. 未確認摘要放在 `.cogito/runs/<run-id>/drafts/shared-understanding.md`。
2. 準備呈現時，將相同 bytes 放到 `docs/cogito/shared-understanding/<run-id>-r<round>.md`。
3. 提交 `shared-understanding-ready`，帶 `document: {"path": "...", "hash": "..."}` 與相同的 `shared_understanding_hash`，向使用者呈現此版本。
4. 收到確認後，登錄 `shared-understanding-confirmed`，指定目前摘要 hash；有 planning 輪次時也指定本輪。
5. 依 [Stage Commits](stage-commits.md) 建立摘要 checkpoint；只提交確認版本，不提交整個 drafts。Gate 登記成功後才進入 Boundary。

等待確認時明說：「確認表示摘要內容正確，並會立即將此版摘要 commit；之後準備並保存 Boundary Gate、Slice／Spec／Plan 與 Development Package。Package Approval 與 Start Gate 通過前不會實作。」使用者修正摘要不等於核准；更新後繼續等待確認。

新 run 即使是第一輪也必須提供可驗證的摘要文件，確認後依 [Stage Commits](stage-commits.md) 完成獨立 commit。Package 的 `shared_understanding` 引用同一 `path` 與 `hash`；摘要確認不改寫已凍結 bytes，確認狀態由事件及 checkpoint 表達。

## 等待確認時收到修訂

等待確認期間修訂摘要後，重新計算 hash，以新的 `action_id` 提交 `shared-understanding-ready`。Gate 追加候選版本並維持 `awaiting-shared-confirmation`，`next` 回傳目前的 `shared_understanding_hash`。再次向使用者呈現此版本；收到確認後，以 `shared-understanding-confirmed` 提交 `{"confirmed":true,"shared_understanding_hash":"<目前摘要hash>"}`。曾修訂摘要的 run 必須明確帶最新 hash，缺少或沿用舊 hash 都會被拒絕；未曾修訂的歷史操作仍相容原本僅有 `confirmed` 的 payload。摘要確認後不接受此自循環，不以修訂摘要偷偷改動後續契約。

集中保存問答的規則不適用已呈現候選的版本更新。修改摘要後必須重新發布與確認，不能沿用舊 hash。

## 已確認後需求改變

Package 尚未核准而需求已改變時，使用 [Planning Revisions](planning-revisions.md) 的 `requirements` 輪次重新進入摘要準備，不在已確認摘要上偷做自循環。`shared-understanding-ready` 需帶目前 `planning_round`、新的 `shared_understanding_hash` 與 `document: {"path": "...", "hash": "..."}`，讓 Gate 保存確認對象的精確內容；confirmation 同時指定本輪及最新 hash。未改需求的 `plan`／`boundary` 輪次沿用已確認共識；影響不明時先 Grilling，不能以較低層級略過必要確認。歷史只有 hash 的摘要不假造原文，但新 requirements 輪次必須提供可驗證文件。

需求、Scope、Acceptance、公開契約、資料模型、安全邊界或 Slice 責任改變時，先重新釐清，再依核准階段走 planning 或 [Replanning](replanning.md)。Package 已核准後，只有未改變上述邊界的純技術缺口才依 [Execution Corrections](execution-corrections.md#自動修正) 的 Technical Amendment／correction 處理。
