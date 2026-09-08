# Package Authoring

## 選擇 Package 類型

準備文件前，先依本次工作的行為與範圍選擇 `kind`。檔案數少或修改容易，不代表符合 Mini Package 條件。

| `kind` | Package 與準備流程 | 獨立審查 |
|---|---|---|
| `feature`、`change`、`correction` | 完整 Development Package：確認需求、Boundary、Slice／Spec／Plan，再核准 Package | 必須 |
| `maintenance` | 符合下列條件的 Mini Package；不建立 Slice／Spec／Plan | 只有符合條件且 Gate 通過時可豁免一般開發審查 |
| `documentation` | 只整理既有語意的 Mini Package；不建立 Slice／Spec／Plan | 必須 |

Mini Package 不建立 Slice、Spec 或 Plan，只適用於以下兩種 `kind`，且必須有符合各項條件的證據：

- Maintenance：不改產品行為、Acceptance、公開契約、資料模型、安全邊界、依賴或 Slice 責任；允許路徑是有限清單，deterministic checks 可覆蓋變更，並在目前 checkout 以 Start Gate HEAD 之後的單一交付 commit 完成。
- Documentation-only adoption：只封存、索引或重組已有來源，不新增或修改產品語意，且 reference/hash checks 能客觀驗證。

Coordinator 在提出 Mini Package 前，需以來源、diff 與行為相關 checks 支持各項不變條件，供 Package 核准時確認。`maintenance_guards` 保存凍結的宣告；Gate 驗證必填 guard 為 true、路徑限制與正式 check evidence，並對 Maintenance 驗證單一提交等可機械檢查的條件，不會證明任意程式變更的語意等價。證據不足或有語意歧義時，先釐清需求並改按完整 Development Package 準備；已建立的 Mini run 不可直接改 kind，依 [Planning Revisions](planning-revisions.md) 處理原 run 與新 run。

Package 類型由 `cogito_contracts.validate_package()` 依 `kind` 判定：`feature`、`change`、`correction` 使用 Development Package，`maintenance`、`documentation` 使用 Mini Package。獨立審查豁免由 `cogito_gate_validation.derive_review_decision()` 檢查，只適用於符合條件的 `maintenance`；`documentation` 仍須獨立審查。`workflows/cogito-v3.json` 定義狀態轉移、guard 名稱與執行上限，沒有可調整 Package 類型或審查豁免的 `profiles` 設定。

Mini Package 使用同一 Gate 引擎，準備階段只建立 Package checkpoint，不經摘要與 Boundary checkpoint；核准後仍須通過 Start Gate。完整 Package 依下列 Boundary 與文件準備流程進行。階段提交操作見 [Stage Commits](stage-commits.md)。人工驗收退回修正不適用 Maintenance 的一般審查豁免。

## 政策與文件位置

適用邊界由 global defaults、可選 project policy 與 Package snapshot 疊加，較嚴格者優先；缺少 project policy 不阻塞。永久放寬或修改 project policy 需另行取得 project-level approval。

Feature Slice ID 使用穩定的 `FS-001` 格式。Spec 路徑為 `docs/specs/<ID>/<ID>-<name>-spec.md`；Plan 路徑為 `docs/plans/<ID>/<ID>-<name>-plan.md`。新的正式控制文件放在 `docs/cogito/`。

## Boundary Gate

AI 以 Shared Understanding 與專案證據提出結構化判斷：`single-slice`、`split-required` 或 `blocked`。Gate 驗證必要欄位、證據、DAG 無環與路徑邊界；AI 不得自行宣告 guard 通過。

`boundary-complete` 通過後，立即依 [Stage Commits](stage-commits.md) 提交 Boundary 判斷、證據與階段紀錄，再開始 Package 草擬。Boundary 階段只建立 provisional Slice IDs。Package 核准時才正式寫入 Project Graph。拆分依可獨立驗收的垂直結果；依賴必須說明輸出、消費者與整合順序。Worker 上限為三個，不代表一定要平行。

## Development Package

一張 Package 摘要必須讓使用者一次判斷：

- 目標、Included／Excluded 與 Shared Understanding hash。
- 經 hash 封存的 source registry，列出每個來源的路徑、內容 hash、關聯性與 disposition；核准後不得另用 run draft 取代。
- Slice 結構、DAG、依賴、lineage 與 delivery branch。
- Spec／Plan 路徑及其內容 hash。
- 每個 Worker 的允許路徑、任務、worktree/branch 策略與整合順序。
- required/advisory/human checks、固定 applicability predicates。
- Human Integration、Human Acceptance、高風險 hotspots。
- correction/review-fix/retry 上限與 stop conditions。
- 適用的 global/project policy snapshot，包括 `max_check_output_bytes`；預設為 10 MiB，Package 只能採用相同或更嚴格的上限。

Package approval 是唯一正式開發核准。核准後 Package JSON 不可變；任何後續 overlay 必須是 Technical Amendment。Package 不包含文件 status/approval metadata，也不包含 Commit Plan。

任務依賴以 `execution_dag.edges` 為準，`from` 是前置任務、`to` 是後續任務。Task 可省略 `depends_on`；若提供，其集合必須與 edges 的入邊一致，Gate 不會默默覆蓋矛盾的宣告。Mini Package 的 task 可省略 `slice_id` 或使用 `mini-package`，兩者都代表同一個工作單位。

新的 Feature／Change／Correction Package 使用 `task_delivery: "atomic"`。每個 Task 必須有非空 `responsibility`、`paths`、`check_ids`；checks 使用 `phase: "task"` 或 `"integration"`（省略時為 integration）。`check_ids` 引用 required checks，Acceptance IDs 與選測理由寫在對應 check／Plan，不再另建 Commit Plan。至少保留一項 required integration check 驗證最終整合內容；最後一個 Task 可以引用並執行這項檢查。完整 regression 交由 CI，不列為例行本地檢查；既有 Project Policy 明定的 required checks 不可藉此降級。

Coordinator 依垂直行為及依賴順序拆分 Task，不將多個可獨立驗證的使用情境合併。一項 Task 包含其行為實作、相關測試與必要文件，也可以是一項必要的共同基礎。可獨立驗證允許依賴前置 Task；多個 Task 可由同一 Worker 在同一 worktree 依序完成。共享檔案或不適合平行執行，不足以作為合併理由。每個 Task 必須獨立 commit；不能只允許分批。預計超過 15 個 production files 或涵蓋多個可分離流程時重新檢視拆分；無法拆分時，在既有 Plan 說明必須共同成立的行為或一致性條件。檔案數與責任是否單一由 Coordinator 判斷，不新增數量 Gate 或例外審批。

核准前，若有同型且已 accepted 的單一 Slice，Coordinator 先用唯讀 `slice-inventory --source-run <RUN> --source-slice <SLICE>` 取得該次凍結路徑、amendment 補列、實際提交路徑、Result 摘要、Tasks、Checks、Spec／Plan 引用與 source registry，作為候選清單；來源必須由呼叫端明確指定，不由工具猜測相似度。Inventory 只是歷史事實，不證明本次適用性或完整性，也不產生 Package skeleton。Coordinator 再沿本次行為追蹤 request／入口、service、repository、mapper、response contract 與相關測試，只檢查實際適用的層次，並逐項標記沿用、新增或不適用。沒有合適 accepted Slice 時直接進行這段目標追蹤，不做全 repository 內容搜尋作為預設起點。

確認必要修改路徑已分配到既有 Plan 的 Files／Tasks，且 Package、Worker、Task 三層授權一致；Checks 記錄對應 Acceptance 與受影響依賴的選測理由。共用 mapper 或 contract 要追蹤其他消費者，不能只列入口檔與直接測試。將依賴漏列在核准前補齊，不新增文件或核准階段。核准後才發現的漏列依 [Execution Policy](execution-policy.md#實作中補列必要路徑) 判斷是否符合輕量補正。

新 `init` 的開發 run 會要求 atomic Package；歷史 run 與已凍結的 RP successor 保留原契約，沒有標記的舊 Package 不補寫、不改 hash。Maintenance／Documentation 維持原流程。

`stop_conditions` 是隨 Package hash 凍結的停止政策。每筆可為非空文字，或包含 `id`、`condition`、`outcome` 的物件；`outcome` 可為 `blocked`、`awaiting-human`、`cancelled`。應寫明可觀察的情況、所需證據與預期處理方式，供 Coordinator 判讀。`cogito_contracts._validate_stop_conditions()` 只驗證格式，runtime 不解析條件文字、不持續監看，也不因 `outcome` 自動跳轉或取得取消授權。執行方式見 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

## Package 核准前修訂

已發布候選後，任何不同候選均先經 `planning begin` 建立同一 run 的新輪次，不直接覆蓋草稿後再次 `prepare-package`。舊候選立即停用核准，原文件 bytes 與修改原因保留在事件中。只調整實作安排使用 `plan`；重分 Slice／邊界使用 `boundary`；需求、範圍、Acceptance 改變使用 `requirements` 並重新確認摘要。每項沿用／重做都說明依據，不能以舊共識核准語意已改變的方案。

新版的 Shared Understanding、Boundary、Spec／Plan、DAG 與 Package 必須對應同一輪，經另一位 Agent 覆核一致性與沿用理由後，才呈現新舊差異請使用者核准。完整 payload、版本比較、撤回與恢復見 [Planning Revisions](planning-revisions.md)。Mini 本版只允許範圍不變的 `plan` 修訂，不支援 same-run 改 kind 升級為 Feature。

## Package 核准後

Package approval 後先依 [Stage Commits](stage-commits.md) 獨立提交 Package、Spec／Plan、採納來源與 Project Graph；Gate 登記成功後才執行 Start Gate。候選尚未核准時不提交 Spec／Plan 或候選 Package。

Start Gate 在最新的授權本地主線重新驗證 baseline、hashes、working tree、Project Graph、DAG、政策與 worktree 可建立性。Start Gate 只驗證本地 Git 狀態，不會執行 fetch。`fetch_allowed` 是凍結的授權政策，Gate 檢查其不超過 Project Policy；Coordinator 另行確認授權並執行需要的 fetch。此旗標不提供網路隔離，也不攔截 checks 的網路存取。驗證失敗時停止推進，依 Runtime Interface 登錄阻塞，不得沿用過期推論。

## 輸入錯誤與舊資料

`shared-understanding-ready` 與 `boundary-complete` 在寫入前使用與 Package 相同的驗證：摘要 hash 為 64 位小寫十六進位字串；Boundary decision 是 `single-slice`／`split-required`，evidence 是非空字串陣列。錯型輸入不追加事件、不推進狀態，修正資料後可沿用尚未成功寫入的 action ID。歷史事件不自動改寫；舊 run 的錯誤摘要若仍未確認，可重新發布合法摘要後確認，新 confirmation 不會接受已存的非法 hash。若錯誤 Boundary 已在舊版本完成，尚未核准且已有候選時依規劃輪次重做；其他情況依合法停止／取消與重建決策處理，不手改權威事件。
