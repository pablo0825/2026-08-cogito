# Blueprint Workflow

用於建立、同步、審查或修訂 Feature Slice blueprint，以及管理需求文件變更。

## 需求來源與 Slice 邊界

一般模式只使用 `docs/project/`、使用者明確確認的需求，以及可追溯至需求文件的既有 blueprint 內容。Rolling Adoption 依 [rolling-adoption-workflow.md](rolling-adoption-workflow.md) 將相關舊文件、程式、測試與 Git history 視為 Legacy Baseline 證據，只有使用者確認且寫入 `docs/project/` 的內容才成為權威需求。將 `AGENTS.md`、架構規範與程式碼視為限制或現況，不視為產品需求。

使用者提出新的或實質改變既有的產品行為時，先完整讀取並執行 [grilling-workflow.md](grilling-workflow.md)，再依 [spec-plan-workflow.md](spec-plan-workflow.md) 執行 Feature Slice Boundary Gate。`Shared Understanding: confirmed` 且 `Readiness: ready` 後，Gate 通過才可提出產品需求文件修改 Proposal、建立 Slice 或提出一般 Blueprint Slice Revision Proposal；Gate 未通過時只可提出 Boundary Gate 要求的垂直拆分 Proposal，不修改任何文件。摘要確認與 Gate 通過都不構成修改 `docs/project/`、blueprint 或其他文件的授權。單純依清楚且未改變的權威需求 reconcile blueprint 時，不重做產品決策訪談或 Boundary Gate。

讓每個 Slice 對應一個可觀察、可獨立驗收且本身有價值的使用者目標，並能用一句話描述完成結果；Slice 包含完成該結果所需的各層工作。若內容包含兩個以上可獨立驗收的結果、可分階段交付且前一階段已有價值、需要多套獨立 Human Acceptance，或新 agent 難以在單一 context 中理解並完成，先提出拆分 Proposal。不要依元件、API client、type、store、tests、重構或 tooling 等技術層拆分。

需求缺漏、矛盾或無法形成可驗收結果時，記錄 Open Questions，將 Slice 維持 `proposed` 或設為 `blocked`，並等待使用者決定。

## 建立 blueprint

完整建立只適用於已有完整 canonical 需求、且目標是建立完整產品 Slice 地圖的專案。已上線但 canonical coverage 不完整的專案不得掃描所有舊文件後建立一批 `proposed` Slice；改走 Rolling Adoption，建立 `Coverage: partial` 的最小 blueprint。

1. 完整讀取 [blueprint-template.md](blueprint-template.md) 與 [slice-brief-template.md](slice-brief-template.md)。
2. 讀取需求文件並建立可追溯的需求清單。
3. 建立 Slice、Type、`Depends On`、`Revises` 與 `Corrects`；所有新 Slice 設為 `proposed`。
4. 建立主 blueprint 與每個 Slice Brief。
5. 確認每項需求有歸屬或 Open Question、每個 Source Reference 有效、ID 唯一且文件連結正確。
6. 依 commit workflow 建立 `docs(blueprint): create feature slice blueprint` commit。
7. 回報 Commit ID、Slice 摘要與 Open Questions，提供下一步的精確 `$cogito` 指令，然後停止。

## Rolling Adoption

依 [rolling-adoption-workflow.md](rolling-adoption-workflow.md) 只收編本次能力。Gate 通過與 Proposal 核准後，在同一 Documentation Batch 建立或更新 canonical requirement、退役舊章節、建立或更新 partial blueprint，並新增一個 `proposed` Slice 與 Brief。

- 第一次修改既有行為：`Type: change`、`Revises: none`，Brief 記錄 `Legacy Baseline`。
- 後續修改已 accepted 的相同行為：使用一般 `Revises`，不得再次建立 Legacy Baseline。
- 未收編能力不建立 placeholder Slice，也不列為 Open Question；blueprint 必須揭露 Coverage 為 `partial`。
- `docs/project/` 寫入與舊章節退役必須同批，避免兩份權威內容。

## 同步 blueprint

1. 比對需求文件與既有 Slice，保留 ID、狀態、Status Note、文件與演進關係。
2. 修正失效的 Source Reference；為全新需求建立 `feature` Slice。
3. 已 `accepted` 行為改變時建立新 ID 的 `change` Slice，不覆寫舊 Brief 或 Spec。
4. 將移除、衝突或無法判定的需求列為待確認，不自行刪除 Slice 或標示為 `accepted`。
5. 確認需求覆蓋、文件連結與狀態一致。
6. 有已授權差異時建立 `docs(blueprint): reconcile feature slice blueprint` commit；沒有差異時不建立空 commit。
7. 回報差異與 Commit ID，然後停止。

若差異影響已核准或已驗收 Slice，先列出影響並取得使用者決定，不自行重設狀態。

## 需求文件變更

討論結果不構成修改 `docs/project/` 的授權。修改前提出：

- 原因與預計內容。
- 文件與章節。
- 受影響 Slice。
- Scope、Acceptance、依賴與既有行為影響。
- Documentation Batch 範圍與 proposed message。

等待明確核准後只修改核准內容，重新 reconcile，更新 Source Reference、Slice Brief 與目前 Slice 已存在的 Spec／Plan，並確認所有文件一致。

實際核准內容若超出已確認摘要或改變已通過的 Slice 邊界，停止文件修改，讓原 Boundary Gate 結果失效，並要求使用者以 `$cogito` 回到 Grilling。

- 未 `accepted`：保留 ID；實質變更時將既有 Spec／Plan 改為 `draft`，blueprint 改為 `awaiting-approval`。
- 已 `accepted`：保留歷史，建立新 ID 的 `change` Slice。
- 純文字修正：不建立新 ID或撤銷核准，但修正失效 reference。

跨 Slice 變更先取得整體核准。無法安全歸屬單一 Slice 的 diff 必須請使用者決定拆分或 commit 歸屬。

## Blueprint Slice Revision

討論期間只讀取主 blueprint、相關 Brief 與 Source Reference，不修改文件。提出 Proposal，包含：

- 原因及修改前後結構。
- Goal、Included／Excluded、Acceptance 與依賴差異。
- 保留、新增與停止使用的 ID。
- 文件清單、需求影響與 proposed commit。

拆分 Proposal 必須採用垂直的使用者結果，且：

- 每個候選 Slice 用一句話描述可觀察的完成結果，並能獨立產生價值與接受或拒絕。
- 說明各候選 Slice 的 Included／Excluded、Human Acceptance 重點、依賴與 ID 影響。
- 將原 Slice 的每項需求分派至候選 Slice、明確排除或列為 Open Question，不得在拆分時遺漏需求。
- 將完成某個結果所必需的錯誤恢復保留在該 Slice；只有本身形成獨立使用者結果時才另成 Slice。
- 不建立 component、API client、type、store、tests、重構或 tooling 等技術層 Slice。

多步驟、多狀態、多檔案或多個 implementation batches 不會單獨構成拆分理由；若只有完整結果才有使用者價值，維持單一 Slice。

核准後：

- 一般調整保留 ID。
- 拆分時讓最接近原 Goal 的子 Slice 保留 ID；無法合理保留時 withdraw 原 ID。
- 合併時保留最能代表新 Goal 的 ID；無法判定時請使用者決定。
- 停止規劃的未實作 Slice 設為 `withdrawn`。
- 新 Slice 使用從未用過的 ID 並設為 `proposed`。

只對 `proposed` Slice 直接調整結構。已有 Spec／Plan 時依實質變更規則撤銷核准；已 `accepted` 時保留歷史並在需求改變時建立 `change` Slice。

更新主索引與受影響 Brief；詳細 lineage 只放在 Brief 的簡短 Blueprint Revision 區段。確認所有受影響文件一致後建立核准的 Blueprint Revision commit，回報 Commit ID、提供下一步的精確 `$cogito` 指令並停止。
