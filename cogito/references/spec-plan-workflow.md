# Spec and Plan Workflow

用於建立、修訂與核准指定 Feature Slice 的 Spec 和 Plan。

## 進入 Feature Slice

確認 ID 存在、不是 `withdrawn`、沒有其他 active Slice、必要依賴已完成，並讀取 Slice Brief 與 Source Reference。Rolling Adoption 在建立 Slice 前執行 Boundary Gate 時，改用 confirmed summary、Legacy Sources 與目標使用者結果；Adoption Documentation commit 完成後，建立 Spec 前仍必須有 Brief 與 canonical Source Reference。操作必須符合目前狀態；依賴未完成時設為或維持 `blocked`，說明恢復條件後停止。

## Pre-Spec Grilling Gate

建立或實質修訂 Spec 前，完整讀取並執行 [grilling-workflow.md](grilling-workflow.md)。先使用需求來源、Slice Brief 與有效 Spec 避免重問已確定內容；修改舊功能或判斷 Bug 時，再以程式、測試與必要 Git 歷史調查現況和差異，不從這些證據發明需求。

只有 `Shared Understanding: confirmed` 且 `Readiness: ready` 才能繼續 Pre-Spec Boundary Gate。`Readiness: blocked` 時停止，不建立或修訂 Spec／Plan，也不建立 Draft Documentation commit。共同理解摘要的確認只核對內容，不構成任何文件修改、核准、實作或 commit 授權。

Boundary Gate 必須是共同理解確認後的下一個產品工作步驟。Gate 通過前不得提出或套用 `docs/project/` 修改、建立或修訂 Blueprint、Spec 或 Plan。若同一份 confirmed 摘要與 Scope 已通過 Gate，後續建立 Spec 時沿用該結果；不要重複執行。需求文件或 Proposal 超出該摘要時，原結果失效並回到 Grilling。

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

1. 不提出或套用產品需求文件修改，不建立或修訂 Blueprint、Spec、Plan，也不建立 Documentation commit。
2. 完整讀取 [blueprint-workflow.md](blueprint-workflow.md) 的 Blueprint Slice Revision 規則。
3. 提出垂直拆分的 Blueprint Slice Revision Proposal；每個候選 Slice 都必須有一句話的使用者可見結果、本身可獨立驗收且有價值，並說明 Included／Excluded、Human Acceptance 重點、依賴與 ID 影響。
4. 確認原 Slice 的每項需求都已分派、明確排除或列為 Open Question，然後等待使用者明確核准。

多個畫面、步驟、狀態、檔案、測試或 implementation batches 本身不是拆分理由。若它們共同完成一個不可分割、只有整體才有價值的使用者結果，維持單一 Slice。拆分只能依使用者結果，不得依技術層或為降低檔案數而切分。

## 建立 Spec 與 Plan

1. 完整讀取 [spec-template.md](spec-template.md) 與 [plan-template.md](plan-template.md)。
2. 僅根據需求來源、Slice Brief 與 Grilling 中使用者已確認的目前有效結論建立 Spec；Spec 定義「做什麼」，不分析程式碼。
3. 完成 Spec 草稿後才分析程式碼、架構、整合點、測試、工具、落差與回歸風險。
4. 根據 Spec 建立 Plan，定義「怎麼做」、必要檔案、風險、Verification Gates 與 Commit Plan。
5. 讓新 Plan 使用 `Implementation Execution: continuous`，並依序列出 Approval、一個以上 implementation batches、Verification 與 Final。
6. Scope Delta 預設填寫 `None`；只有技術限制需要不同實作表達時才記錄差異，產品 Scope 改變則先修訂 Spec。
7. 將 Spec／Plan 設為 `draft`，blueprint 設為 `awaiting-approval`，確認需求、Acceptance、檔案與 batch 一致。
8. 建立 `docs(<ID>): draft <feature> specification` commit，回報 Scope、風險與 Open Questions，然後停止。

每個 implementation batch 回答一個清楚的審查問題並對應一個 commit。不要為增加 commit 數量拆開不可分割的工作。

### Verification Gate 分級

Plan 必須在核准前為每項完整驗證指定 Gate：

- `required`：AI 可重複執行且此 Slice 前進所必需的檢查。依專案與風險選擇適用的 typecheck、核心 unit／integration tests、production build、重要 API contract、資料完整性與安全檢查；不把不適用的固定套餐全部列入。
- `advisory`：補充信心但不阻擋狀態前進的檢查，例如次要 browser smoke、非關鍵效能、bundle size 或特定瀏覽器補充驗證。
- `human`：只有人類能可靠確認的真實環境、帳號、OAuth／權限、第三方服務、視覺互動、真實裝置或產品期待；對應 Human Integration 或 Human Acceptance，不用來承接自動化 `not-run`。

`not-applicable` 是有證據支持的執行結果，不是 Gate。因環境、權限、依賴或工具限制無法執行時使用 `not-run`，不得改寫為 `not-applicable`。Batch 的 `Required Verification` 仍是建立該 batch commit 前的必要檢查；完整 Verification Gate 則控制 Slice 能否進入 `awaiting-human`。

### 變更類型

- 一般 `change`：記錄 Previous Spec、Current Behavior、Target Behavior 與 Preserved Behavior，並以 `Revises` 指向原 accepted Slice。
- Rolling Adoption 第一次 `change`：`Previous Spec` 與 `Revises` 為 `none`，引用 Brief 的 `Legacy Baseline`，記錄 Current／Target／Preserved Behavior；本次 Spec 是收編後的第一份 Authoritative Spec。
- `correction`：引用 Authoritative Spec 與必須恢復的 Acceptance，不修改原 Spec。

第一次收編不得補造 Previous Spec 或 accepted Slice，也不得將既有 change 誤記為 feature。沒有 Cogito Authoritative Spec 的舊問題不能使用 `correction`。

現有程式碼與 Spec 不一致時，以 Spec 為準並在 assessment 記錄差異。若差異會改變 Scope、使用者行為或 Integration Contract，停止並詢問使用者。

## 修訂

Spec 的 Goal、Rules、Input／Output、Included／Excluded、Integration Contract 或 Acceptance，或 Plan 的 Scope、主要方式、核心檔案、Verification check、Gate、command／method 發生實質變更時：

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
