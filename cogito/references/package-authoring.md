# Package Authoring

## Boundary Gate

AI 以 Shared Understanding 與專案證據提出結構化判斷：`single-slice`、`split-required` 或 `blocked`。Gate 驗證必要欄位、證據、DAG 無環與路徑邊界；AI 不得自行宣告 guard 通過。

Boundary 階段只建立 provisional Slice IDs。Package 核准時才正式寫入 Project Graph。拆分依可獨立驗收的垂直結果；依賴必須說明輸出、消費者與整合順序。Worker 上限為三個，不代表一定要平行。

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

`stop_conditions` 是隨 Package hash 凍結的停止政策。每筆可為非空文字，或包含 `id`、`condition`、`outcome` 的物件；`outcome` 可為 `blocked`、`awaiting-human`、`cancelled`。應寫明可觀察的情況、所需證據與預期處理方式，供 Coordinator 判讀。`cogito_contracts._validate_stop_conditions()` 只驗證格式，runtime 不解析條件文字、不持續監看，也不因 `outcome` 自動跳轉或取得取消授權。執行方式見 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

## Package 核准後

Start Gate 在最新的授權本地主線重新驗證 baseline、hashes、working tree、Project Graph、DAG、政策與 worktree 可建立性。不自動 fetch，除非 Project Policy 明確授權。驗證失敗就 `blocked`，不得沿用過期推論。

Mini Package 不建立 Slice、Spec 或 Plan，只適用於以下兩種 `kind`，且必須有符合各項條件的證據：

- Maintenance：不改產品行為、Acceptance、公開契約、資料模型、安全邊界、依賴或 Slice 責任；允許路徑是有限清單，deterministic checks 可覆蓋變更，並在目前 checkout 以單一 commit 完成。
- Documentation-only adoption：只封存、索引或重組已有來源，不新增或修改產品語意，且 reference/hash checks 能客觀驗證。

任一 guard 缺少證據、結果取決於 Agent 判斷，或出現語意歧義，就回到 Grilling 並升級為完整 Development Package。

Package 類型由 `cogito_contracts.validate_package()` 依 `kind` 判定：`feature`、`change`、`correction` 使用 Development Package，`maintenance`、`documentation` 使用 Mini Package。獨立審查豁免由 `cogito_gate_validation.derive_review_decision()` 檢查，只適用於符合條件的 `maintenance`；`documentation` 仍須獨立審查。`workflows/cogito-v3.json` 定義狀態轉移、guard 名稱與執行上限，沒有可調整 Package 類型或審查豁免的 `profiles` 設定。
