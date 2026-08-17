---
name: frontend-feature-slice-workflow
description: Govern frontend work as Feature Slices from requirements and blueprint through Spec, Plan, implementation, AI verification, human acceptance, and scoped Git checkpoints. Use when creating or reconciling a frontend Feature Slice blueprint, changing requirements or Slice structure, or planning, approving, implementing, verifying, accepting, revising, or committing work identified by Feature Slice IDs.
---

# Frontend Feature Slice Workflow

以需求文件定義產品行為，以 Feature Slice 管理規劃、實作、驗證與驗收。只載入目前操作需要的 reference。

## 核心不變量

- 使用中文撰寫專案文件；路徑、API、ID、slug、指令、程式識別字與狀態值使用英文。
- 將 `docs/project/` 視為產品需求來源；將 `docs/blueprint/feature-slice-blueprint.md` 視為 Slice 狀態的唯一權威來源。
- 只從需求文件與使用者明確確認的內容定義產品需求，不從程式碼、測試、TODO 或既有行為推論需求。
- 一次只處理一個 Feature Slice；已核准且本質上跨 Slice 的 Blueprint 操作除外。
- 建立任何 Spec 前必須通過 Feature Slice Boundary Gate；若 Slice 包含多個可獨立驗收的使用者結果，先停止 Spec／Plan 並提出 Blueprint Slice Revision Proposal。
- Slice 必須以垂直的使用者結果切分；不得依 component、API client、type、store、tests、重構或 tooling 等技術層切分。
- 先完成 Spec，再分析程式碼並建立 Plan；取得 Spec 與 Plan 明確核准前不修改實作程式碼。
- 分開記錄 committed、AI verified 與 human accepted；只有使用者能確認 Human Integration 與 Human Acceptance。
- AI Verification 負責可重複的技術檢查；Human Acceptance 不重跑 build、lint、typecheck、unit、integration、E2E、accessibility automation 或已自動覆蓋的狀態／viewport matrix。
- Plan 以 `required`、`advisory`、`human` 分級每項 Verification Gate；核准後不得因結果失敗或未執行而自行降級，改變 Gate 必須修訂並重新核准 Plan。
- `required` 的 `failed` 或 `not-run` 阻止 Slice 進入 `awaiting-human`；`advisory` 的 `failed` 或 `not-run` 可前進但必須揭露原因、風險與 release impact；`human` 未完成時可進入 `awaiting-human`，不得進入 `accepted`。
- Human Acceptance 原則上只提供 3–5 個高價值場景，聚焦真實環境與外部服務、視覺／文案／互動感受、代表性真實裝置、自動化無法可靠判斷的情境，以及產品是否符合使用者期待；沒有足夠獨立判斷時不湊數。
- AI Verification 的 `not-run` 保持技術風險，不自動轉成人工測試；只有該結果本質上需要人類判斷或使用者明確要求人工補驗時，才納入 Human Acceptance。
- 將未執行的檢查如實標示為 `not-run` 或 `not-applicable`，不得標示為 `passed`。
- 將 Spec、Plan 與 Verification 視為活文件：只保存目前有效內容，不追加 revision summary、已完成 batch、被取代的驗證結果或 commit record；詳細歷史由 Git 保存。
- Spec 保存目前提出或核准的產品行為；Plan 保存目前有效的實作方式與尚未完成的工作；Verification 保存每項檢查的最新結果、人工驗收與未解決問題。
- 只保留理解目前需求所需的語義 lineage，例如 `Revises`、`Corrects`、`Previous Spec`、`Authoritative Spec` 與 replacement link；不以文件重建 commit lineage。
- 保留無關的既有變更；不覆寫、還原、stage 或提交操作開始前的使用者修改。
- 不擴張核准 Scope、不自行處理下一個 Slice、不 push、不改寫 Git history。

## 開始操作

1. 確認專案根目錄並讀取適用的 `AGENTS.md` 與專案指示。
2. 確認 `docs/project/` 與 blueprint；缺少需求來源時停止並詢問位置。
3. 記錄 working tree、staged 狀態與目標檔案既有修改。
4. 從使用者要求辨識單一操作，讀取下表指定的 reference，不載入其他分支。

若已有 staged changes，或目標檔案存在無法安全分離的使用者修改，停止並說明。只有使用者明確要求採納其修改時才能納入目前操作。

## 操作路由

| 操作 | 必須完整讀取 |
|---|---|
| 建立、同步或審查 blueprint；變更需求；拆分、合併或撤回 Slice | [blueprint-workflow.md](references/blueprint-workflow.md)；需要產出時再讀 [blueprint-template.md](references/blueprint-template.md) 與 [slice-brief-template.md](references/slice-brief-template.md) |
| 建立、修訂或核准 Spec／Plan | [spec-plan-workflow.md](references/spec-plan-workflow.md)；需要產出時再讀 [spec-template.md](references/spec-template.md) 與 [plan-template.md](references/plan-template.md) |
| 開始、繼續或修正 implementation sequence | [implementation-workflow.md](references/implementation-workflow.md) |
| 執行 AI Verification；記錄 Human Integration 或 Human Acceptance | [verification-acceptance-workflow.md](references/verification-acceptance-workflow.md)；需要建立 verification 時再讀 [verification-template.md](references/verification-template.md) |
| 任何會建立 commit 的操作 | [commit-workflow.md](references/commit-workflow.md)，每次操作或恢復中斷 sequence 時讀取一次 |

使用者的要求若同時明確授權連續操作，讀取所有相關分支並依授權順序執行。例如「核准並開始實作」同時授權 Approval Documentation checkpoint 與 implementation sequence。

## Feature Slice 模型

ID 使用 `FS-001` 格式並保持穩定。名稱使用英文 kebab-case。文件路徑使用：

```text
docs/blueprint/feature-slice-blueprint.md
docs/blueprint/slices/<ID>-<name>.md
docs/specs/<ID>/<ID>-<name>-spec.md
docs/plans/<ID>/<ID>-<name>-plan.md
docs/verification/<ID>/<ID>-<name>-verification.md
```

每個 ID 使用獨立資料夾。不要在已 `accepted` Slice 的資料夾建立 `v2`、`final` 或 `new` 文件，也不要覆寫原始 Spec。

Type 只使用：

- `feature`：新增使用者可見功能。
- `change`：改變已 `accepted` 功能的需求或行為，以 `Revises` 指向原 Slice。
- `correction`：修正不符合有效 Spec 的實作，以 `Corrects` 指向原 Slice。

`Depends On` 只表示實作依賴，不代替 `Revises` 或 `Corrects`。已 `accepted` 的需求或 Acceptance 改變時建立新 ID；未 `accepted` 時更新原文件並依實質性撤銷核准。純文字修正不建立新 ID。

## 狀態機

只使用 `proposed`、`awaiting-approval`、`approved`、`in-progress`、`awaiting-human`、`accepted`、`blocked`、`withdrawn`。

```text
proposed -> awaiting-approval -> approved -> in-progress -> awaiting-human -> accepted
```

- `awaiting-approval`、`approved`、`in-progress`、`awaiting-human` 為 active status；同時最多一個 active Slice。
- `blocked` 必須記錄阻礙前狀態、原因與恢復條件；解除後回到適當狀態。
- `withdrawn` 為終止狀態；保留 ID 與文件，不刪除、重用或重新啟用。
- 每次狀態轉移都同步更新 blueprint 的 Status、Status Note 與 Last Updated；建立文件時同步更新 Documents link。

## 授權與完成條件

- 只將使用者針對需求變更、Proposal、Spec／Plan、開始實作或 Human Acceptance 的明確表達視為對應授權。
- Spec／Plan 核准同時核准 Commit Plan 與 Approval Documentation commit，但單獨核准不授權實作。
- 若使用者在同一訊息明確要求「核准並開始實作」，完成 Approval commit 後直接進入 implementation sequence，不增加第二次確認。
- `continuous` implementation 授權涵蓋所有已核准 implementation batches、各 batch 驗證、完整 AI Verification 與 Verification Documentation commit。
- 每個步驟以已授權產出完成、必要檢查實際執行且狀態與文件一致為完成條件。
- 遇到 Scope、需求、Integration Contract、未核准檔案、重疊修改或需要人類決策的變更時停止。
- 完成目前授權的操作後停止；不因某個 checkpoint 完成而推論下一項授權。

## 既有文件相容性

- 不因 Skill 更新重寫既有 Spec、Plan、Verification、撤銷核准或改變已核准 Commit Plan。
- 缺少 `Implementation Execution` 的已核准 Plan 視為 legacy `per-batch`，每個 batch 維持明確授權。
- 已標示 `continuous` 的既有 Plan 依其核准 Commit Plan 執行。
- 既有 Plan 沒有 Gate 欄位時，`AI Verification Requirements` 視為完整驗證的 `required`，每個尚未完成 batch 的 `Required Verification` 視為該 batch 的必要檢查，Human Integration／Acceptance 視為 `human`；額外補充檢查預設為 `advisory`，但專案指示明定的 release gate 仍為 `required`。
- 新文件直接使用活文件規則。已授權操作需要更新既有 active Spec、Plan 或 Verification 時，同步移除其中被取代的 revision summary、完成紀錄與舊驗證結果；這項 housekeeping 不改變有效內容或核准狀態。
- 已 `accepted` Slice 的產品內容是完成當時的不可變快照；後續需求或行為改變建立新的 `change` Slice，不覆寫舊內容。只有 change／correction workflow 要求的狀態與最小語義 lineage 可以更新。
