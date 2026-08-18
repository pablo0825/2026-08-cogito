# Spec and Plan Workflow

用於建立、修訂與核准指定 Feature Slice 的 Spec 和 Plan。

## 入口分類

先依實際 delta 選擇一條入口，不按使用者訊息中的「核准」或「修改」字樣猜測：

| Delta | 路徑 |
|---|---|
| 建立 Spec，或改變 Goal、Scope、Rules、Input／Output、Integration Contract、Acceptance、canonical requirement 或 Slice boundary | 完整 Grilling → Boundary Gate → Spec／Plan revision |
| 只改變實作方法、主要 Files、batch 分組／順序、commands、Verification checks／Gates／Applicability | Plan revision 與重新核准；產品 contract 不變時不進 Grilling |
| 只修正文字、格式、失效 reference 或可證明語義不變的 active-document schema | housekeeping；依下方相容性規則決定是否保持核准 |
| 核准完全未變更的 draft | Pure Approval Gate 通過後直接進入核准；不載入 Grilling |

任何 review、implementation、Verification、Human Acceptance、requirements reconciliation 或 commit 前檢查發現的產品語義 delta 都回到第一條，不在其他 workflow 直接修改 Spec。

## 進入 Feature Slice

確認 ID 存在、不是 `withdrawn`、沒有其他 active Slice、必要依賴已完成，並讀取 Slice Brief 與 Source Reference。Rolling Adoption 在建立 Slice 前執行 Boundary Gate 時，改用 confirmed summary、Legacy Sources 與目標使用者結果；Adoption Documentation commit 完成後，建立 Spec 前仍必須有 Brief 與 canonical Source Reference。操作必須符合目前狀態；依賴未完成時設為或維持 `blocked`，說明恢復條件後停止。

`blocked` 的阻礙前狀態若為 active，該 Slice 仍占用 active slot；不要把它當成可開始另一個 Slice 或無關 Maintenance 的空位。

## Pure Approval Gate

直接核准 draft 前確認全部條件：

- Spec metadata 記錄 `Shared Understanding: confirmed`、`Boundary Gate: passed` 與 Boundary Basis。
- Spec／Plan 與相關 Brief、blueprint 自 Draft commit 後沒有未授權變更。
- Draft commit 之後 canonical sources 與 Brief 沒有產品語義漂移。
- 使用者核准的是目前 exact draft，且同一訊息沒有附帶產品或技術內容變更。
- Commit Plan、Files、Verification mappings 與 approvals 仍內部一致。

全部成立時直接進入「核准與複合授權」。任一條件不成立時依入口分類轉入適當 revision；證據不足時停止並指出缺少的核准資格，不以重新 Grilling 代替可查證的 Git／文件事實。

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
4. 為 Spec 的 `AI-*`／`HA-*` 配置 Slice-scoped stable IDs；根據 Spec 建立 Plan，定義「怎麼做」、必要檔案、風險、`V-*` Verification mappings、`HI-*` Human Integration 與 Commit Plan。
5. 讓新 Plan 使用 `Implementation Execution: continuous`，並依序列出 Approval、一個以上 implementation batches、Verification 與 Final。
6. Scope Delta 預設填寫 `None`；只有技術限制需要不同實作表達時才記錄差異，產品 Scope 改變則先修訂 Spec。
7. 將 Spec／Plan 設為 `draft`，在 Spec 保存 Shared Understanding 與 Boundary Gate provenance，blueprint 設為 `awaiting-approval`，確認 canonical sources、Brief boundary、Acceptance IDs、Verification mappings、檔案與 batch 一致。
8. 建立 `docs(<ID>): draft <feature> specification` commit，回報 Scope、風險與 Open Questions，然後停止。

每個 implementation batch 回答一個清楚的審查問題並對應一個 commit。不要為增加 commit 數量拆開不可分割的工作。

Plan 建立時可依 verification template 設計未來 Verification schema 與 ID 關係，但不要建立帶有虛構結果或佔位 `not-run` 的 Verification artifact；新 Slice 的 Verification 文件在第一次保存實際驗證證據時建立。active legacy 文件的原子 schema migration 依下方相容性規則處理。

### Verification Gate 分級

Plan 必須在核准前為每項完整驗證配置 stable `V-*` Check ID、對應的 Acceptance IDs、Gate、Applicability 與 command／method：

- `required`：AI 可重複執行且此 Slice 前進所必需的檢查。依專案與風險選擇適用的 typecheck、核心 unit／integration tests、production build、重要 API contract、資料完整性與安全檢查；不把不適用的固定套餐全部列入。
- `advisory`：補充信心但不阻擋狀態前進的檢查，例如次要 browser smoke、非關鍵效能、bundle size 或特定瀏覽器補充驗證。
- `human`：只有人類能可靠確認的真實環境、帳號、OAuth／權限、第三方服務、視覺互動、真實裝置或產品期待；對應 Human Integration 或 Human Acceptance，不用來承接自動化 `not-run`。

`Applicability` 使用 `always` 或 Plan 核准時即可客觀判定的 predicate。Predicate 只控制 mapped check，不縮小 Spec criterion，不依賴 Agent 可操控的實作選擇；不同 applicability 的 mappings 使用不同 rows。每個 `AI-*` 必須具有足以完成 criterion 的客觀 coverage，原則上至少一個 `required` mapping；每個 `HA-*` 必須具有 `human` mapping。孤立、未知、重複使用或已停止使用的 ID 阻止核准。

`not-applicable` 是 approved predicate 為 false 時的執行結果，不是 Gate。因環境、權限、依賴、期限或工具限制無法執行時使用 `not-run`。Batch 的 `Required Verification` 仍是建立該 batch commit 前的必要檢查；完整 Verification Gate 則控制 Slice 能否進入 `awaiting-human`。

### 變更類型

- 一般 `change`：記錄 Previous Spec、Current Behavior、Target Behavior 與 Preserved Behavior，並以 `Revises` 指向原 accepted Slice。
- Rolling Adoption 第一次 `change`：`Previous Spec` 與 `Revises` 為 `none`，引用 Brief 的 `Legacy Baseline`，記錄 Current／Target／Preserved Behavior；本次 Spec 是收編後的第一份 Authoritative Spec。
- `correction`：引用 Authoritative Spec 與必須恢復的 Acceptance，不修改原 Spec。

第一次收編不得補造 Previous Spec 或 accepted Slice，也不得將既有 change 誤記為 feature。沒有 Cogito Authoritative Spec 的舊問題不能使用 `correction`。

現有程式碼與 Spec 不一致時，以 Spec 為準並在 assessment 記錄差異。若差異會改變 Scope、使用者行為或 Integration Contract，停止並詢問使用者。

## 修訂

Spec 的 Goal、Rules、Input／Output、Included／Excluded、Integration Contract 或 Acceptance 發生實質變更時，原 Shared Understanding 與 Boundary Gate 失效；先回到 Grilling 與 Boundary Gate，再依新的明確授權修訂 Spec／Plan。

產品 contract 不變，而 Plan 的主要方式、核心檔案、Verification check、Gate、Applicability 或 command／method 發生實質變更時：

1. 更新 Plan 與受影響 mappings，不重寫 Spec criteria。
2. 將 Plan 與 Commit Plan Approval 設為 `pending`；需要 Scope Delta 時記錄技術表達差異，產品 Scope delta 改走 Grilling。
3. 將 blueprint 設為 `awaiting-approval`。
4. 若使用者已授權套用修訂，建立 `docs(<ID>): revise <feature> specification` commit，然後提示以 `$cogito 核准 <ID> Plan` 繼續。

純文字修正、證據補充與移除已完成 Commit Plan row 不撤銷核准。active Spec／Plan／目前 Verification 可在已授權 Documentation Batch 中原子補上 ID、exact mappings 與 `Applicability: always`，但只有文字、Gate、commands、results、evidence 與 coverage 全部語義相同且 mapping 無歧義時才是 housekeeping。任何推論、合併／拆分 criterion、coverage 改變或 predicate 新增都屬實質 revision。accepted snapshots 不做 schema migration。

直接更新 canonical sections：Spec 只呈現目前提出或核准的產品行為；Plan 只呈現目前有效的實作方式與尚未完成的工作。移除 revision summary、已完成 batch、execution result、commit ID 與被取代的 assessment。詳細歷史由 Git 保存；文件只保留模板定義的語義 lineage 欄位。

## 核准與複合授權

只接受明確核准。核准 Spec／Plan 同時核准 Commit Plan、核准者與時間，並授權 Approval Documentation commit；單獨核准不授權實作。

核准後：

1. 將 Spec／Plan 與 blueprint 設為 `approved`。
2. 將 Commit Plan Approval 設為 `approved`。
3. `change` 只在新 Slice、blueprint 與新 Spec 保存 `Revises`／Previous Spec lineage；`correction` 只在新 Slice 保存 `Corrects`／Authoritative Spec lineage。兩者都不修改舊 accepted Spec。
4. 建立 `docs(<ID>): approve <feature> specification` commit。
5. 若使用者只核准，回報 Commit ID 並詢問是否開始實作，然後停止。
6. 若使用者同一訊息明確要求核准並開始實作，Approval commit 後直接依 implementation workflow 執行，不再次詢問。

完成條件是文件狀態、Commit Plan 核准、blueprint 狀態與 Approval commit 全部一致。

停止時使用明確續接句：`請以 $cogito 開始 <ID> implementation`。若同一訊息已明確核准並開始，直接依 implementation workflow 執行，不再次詢問。
