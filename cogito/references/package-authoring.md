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
- 適用的 global/project policy snapshot。

Package approval 是唯一正式開發核准。核准後 Package JSON 不可變；任何後續 overlay 必須是 Technical Amendment。Package 不包含文件 status/approval metadata，也不包含 Commit Plan。

## Package 核准後

Start Gate 在最新的授權本地主線重新驗證 baseline、hashes、working tree、Project Graph、DAG、政策與 worktree 可建立性。不自動 fetch，除非 Project Policy 明確授權。驗證失敗就 `blocked`，不得沿用過期推論。

Mini Package 不建立 Slice、Spec 或 Plan，只可用於 Gate 能以客觀證據證明的 profile：

- Maintenance：不改產品行為、Acceptance、公開契約、資料模型、安全邊界、依賴或 Slice 責任；允許路徑是有限清單，deterministic checks 可覆蓋變更，並在目前 checkout 以單一 commit 完成。
- Documentation-only adoption：只封存、索引或重組已有來源，不新增或修改產品語意，且 reference/hash checks 能客觀驗證。

任一 guard 缺少證據、結果取決於 Agent 判斷，或出現語意歧義，就回到 Grilling 並升級為完整 Development Package。
