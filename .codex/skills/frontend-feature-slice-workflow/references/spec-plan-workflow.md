# Spec and Plan Workflow

用於建立、修訂與核准指定 Feature Slice 的 Spec 和 Plan。

## 進入 Feature Slice

確認 ID 存在、不是 `withdrawn`、沒有其他 active Slice、必要依賴已完成，並讀取 Slice Brief 與 Source Reference。操作必須符合目前狀態；依賴未完成時設為或維持 `blocked`，說明恢復條件後停止。

## Pre-Spec Boundary Gate

建立或修訂 Spec 前，根據 Slice Brief 與 Source Reference 先評估下列訊號：

| 問題 | 需要拆分的訊號 |
|---|---|
| 是否包含兩個以上可獨立驗收的使用者結果？ | 是 |
| 是否可以分階段交付，而且前一階段本身已有使用者價值？ | 是 |
| 是否需要多套彼此獨立的 Human Acceptance 流程？ | 是 |
| 新 agent 是否難以在單一 context 中理解並完成？ | 是 |
| 使用者能否用一句話描述完成結果？ | 否 |

前四題任一為「是」，或第五題為「否」，即視為 Boundary Gate 未通過。先使用現有資料自行判斷，不把五題逐題丟給使用者；只有證據不足且答案會改變拆分決策時，才提出一個聚焦問題。

Gate 未通過時：

1. 不建立或修訂 Spec、Plan，也不建立 Draft Documentation commit。
2. 完整讀取 [blueprint-workflow.md](blueprint-workflow.md) 的 Blueprint Slice Revision 規則。
3. 提出垂直拆分的 Blueprint Slice Revision Proposal；每個候選 Slice 都必須有一句話的使用者可見結果、本身可獨立驗收且有價值，並說明 Included／Excluded、Human Acceptance 重點、依賴與 ID 影響。
4. 確認原 Slice 的每項需求都已分派、明確排除或列為 Open Question，然後等待使用者明確核准。

多個畫面、步驟、狀態、檔案、測試或 implementation batches 本身不是拆分理由。若它們共同完成一個不可分割、只有整體才有價值的使用者結果，維持單一 Slice。拆分只能依使用者結果，不得依技術層或為降低檔案數而切分。

## 建立 Spec 與 Plan

1. 完整讀取 [spec-template.md](spec-template.md) 與 [plan-template.md](plan-template.md)。
2. 僅根據需求來源、Slice Brief 與使用者已確認內容建立 Spec；Spec 定義「做什麼」，不分析程式碼。
3. 完成 Spec 草稿後才分析程式碼、架構、整合點、測試、工具、落差與回歸風險。
4. 根據 Spec 建立 Plan，定義「怎麼做」、必要檔案、風險、驗證與 Commit Plan。
5. 讓新 Plan 使用 `Implementation Execution: continuous`，並依序列出 Approval、一個以上 implementation batches、Verification 與 Final。
6. Scope Delta 預設填寫 `None`；只有技術限制需要不同實作表達時才記錄差異，產品 Scope 改變則先修訂 Spec。
7. 將 Spec／Plan 設為 `draft`，blueprint 設為 `awaiting-approval`，確認需求、Acceptance、檔案與 batch 一致。
8. 建立 `docs(<ID>): draft <feature> specification` commit，回報 Scope、風險與 Open Questions，然後停止。

每個 implementation batch 回答一個清楚的審查問題並對應一個 commit。不要為增加 commit 數量拆開不可分割的工作。

### 變更類型

- `change`：記錄 Previous Spec、Current Behavior、Target Behavior 與 Preserved Behavior。
- `correction`：引用 Authoritative Spec 與必須恢復的 Acceptance，不修改原 Spec。

現有程式碼與 Spec 不一致時，以 Spec 為準並在 assessment 記錄差異。若差異會改變 Scope、使用者行為或 Integration Contract，停止並詢問使用者。

## 修訂

Spec 的 Goal、Rules、Input／Output、Included／Excluded、Integration Contract 或 Acceptance，或 Plan 的 Scope、主要方式、核心檔案發生實質變更時：

1. 同步 Spec 與 Plan。
2. 撤銷核准並設為 `draft`。
3. 將 blueprint 設為 `awaiting-approval`。
4. 若使用者已授權套用修訂，建立 `docs(<ID>): revise <feature> specification` commit 後停止。

純文字修正、證據補充與 checkbox 更新不撤銷核准。移除已完成並提交的 Commit Plan row 是 housekeeping，不撤銷核准；只要改變尚未完成 batch 的分組、順序、Files、Required Verification 或 message，才將 Commit Plan Approval 設為 `pending`。不得藉此隱藏 Scope 變更。

直接更新 canonical sections：Spec 只呈現目前提出或核准的產品行為；Plan 只呈現目前有效的實作方式與尚未完成的工作。移除 revision summary、已完成 batch、execution result、commit ID 與被取代的 assessment。詳細歷史由 Git 保存；文件只保留模板定義的語義 lineage 欄位。

## 核准與複合授權

只接受明確核准。核准 Spec／Plan 同時核准 Commit Plan、核准者與時間，並授權 Approval Documentation commit；單獨核准不授權實作。

核准後：

1. 將 Spec／Plan 與 blueprint 設為 `approved`。
2. 將 Commit Plan Approval 設為 `approved`。
3. `change` 在舊 Spec 加入 `Supersession Pending`，維持舊 Spec `completed`；`correction` 不修改原 Spec。
4. 建立 `docs(<ID>): approve <feature> specification` commit。
5. 若使用者只核准，回報 Commit ID 並詢問是否開始實作，然後停止。
6. 若使用者同一訊息明確要求核准並開始實作，Approval commit 後直接依 implementation workflow 執行，不再次詢問。

完成條件是文件狀態、Commit Plan 核准、blueprint 狀態與 Approval commit 全部一致。
