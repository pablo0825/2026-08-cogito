# Blueprint Workflow

用於建立、同步、審查或修訂 Feature Slice blueprint，以及管理需求文件變更。

## 需求來源與 Slice 邊界

只使用 `docs/project/`、使用者明確確認的需求，以及可追溯至需求文件的既有 blueprint 內容。將 `AGENTS.md`、架構規範與程式碼視為限制或現況，不視為產品需求。

讓每個 Slice 對應一個可觀察、可獨立驗收的使用者目標，包含完成結果所需的前端各層工作。不要依元件、API client、type、store、tests、重構或 tooling 等技術層拆分。

需求缺漏、矛盾或無法形成可驗收結果時，記錄 Open Questions，將 Slice 維持 `proposed` 或設為 `blocked`，並等待使用者決定。

## 建立 blueprint

1. 完整讀取 [blueprint-template.md](blueprint-template.md) 與 [slice-brief-template.md](slice-brief-template.md)。
2. 讀取需求文件並建立可追溯的需求清單。
3. 建立 Slice、Type、`Depends On`、`Revises` 與 `Corrects`；所有新 Slice 設為 `proposed`。
4. 建立主 blueprint 與每個 Slice Brief。
5. 確認每項需求有歸屬或 Open Question、每個 Source Reference 有效、ID 唯一且文件連結正確。
6. 依 commit workflow 建立 `docs(blueprint): create feature slice blueprint` commit。
7. 回報 Commit ID、Slice 摘要與 Open Questions，然後停止。

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

核准後：

- 一般調整保留 ID。
- 拆分時讓最接近原 Goal 的子 Slice 保留 ID；無法合理保留時 withdraw 原 ID。
- 合併時保留最能代表新 Goal 的 ID；無法判定時請使用者決定。
- 停止規劃的未實作 Slice 設為 `withdrawn`。
- 新 Slice 使用從未用過的 ID 並設為 `proposed`。

只對 `proposed` Slice 直接調整結構。已有 Spec／Plan 時依實質變更規則撤銷核准；已 `accepted` 時保留歷史並在需求改變時建立 `change` Slice。

更新主索引與受影響 Brief；詳細 lineage 只放在 Brief 的簡短 Blueprint Revision 區段。確認所有受影響文件一致後建立核准的 Blueprint Revision commit，回報 Commit ID 並停止。
