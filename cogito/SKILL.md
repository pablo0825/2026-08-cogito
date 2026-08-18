---
name: cogito
description: End-to-end Feature Slice governance for software work in Codex.
---

# Cogito

以 canonical requirements 定義產品行為，以 Feature Slice 管理規劃、實作、驗證與驗收。Cogito 只由使用者以 `$cogito` 明確啟動；每則要繼續治理流程的使用者訊息都必須再次包含 `$cogito`。

## 核心模型

- 使用中文撰寫專案文件；路徑、API、ID、slug、指令、程式識別字與狀態值使用英文。
- `docs/project/` 是已收編產品意圖與正式規則的唯一權威來源；Slice Brief 定義本次使用者結果與高階邊界；Spec 將 canonical requirements 整理成可實作、可驗收的 Slice contract；Plan 定義實作與驗證方法；Verification 保存目前證據；Git 保存歷史。
- `docs/blueprint/feature-slice-blueprint.md` 是 Slice 狀態、active slot 與目前收編範圍的唯一權威來源。
- 程式碼、測試、TODO、舊文件與 Git history 只提供現況、限制或 Legacy Baseline 證據；只有使用者確認且寫入 `docs/project/` 的產品規則才成為 canonical requirement。
- 同一項產品規則只有一個 canonical 位置。Spec 的 Slice contract 必須可追溯至 canonical source；兩者語義衝突時停止並確認，不自行選擇其中一份。
- 同一時間只處理一個 active Feature Slice 或一個 Maintenance；已核准且本質上跨 Slice 的 Blueprint 操作除外。`blocked` 若阻礙前狀態為 active，仍占用 active slot。
- Slice 依可獨立驗收且具有使用者價值的垂直結果切分。Spec 定義「做什麼」，Plan 定義「怎麼做」，實作只依已核准的 Spec、Plan 與 Commit Plan 進行。
- 分開記錄 committed、AI verified 與 human accepted；只有使用者能確認 Human Integration 與 Human Acceptance。
- 使用者授權只涵蓋明確指定的 Proposal、文件 checkpoint、implementation sequence 或驗收結果。完成目前授權後停止；下一階段等待新的明確授權。
- 保留操作開始前的使用者變更；不擴張核准 Scope、不修改未核准檔案、不把未執行檢查標成通過、不 push、不改寫 Git history。

## 開始操作

1. 確認專案根目錄並讀取適用的 `AGENTS.md` 與專案指示。
2. 讀取 blueprint、目標 Slice 文件與 canonical sources，確認目前狀態、active slot、coverage 與 lineage。Maintenance 只需確認 blueprint 不存在或沒有占用 active slot 的 Slice。
3. 記錄 working tree、staged 狀態與目標檔案既有修改。
4. 從使用者訊息辨識一個操作，依下表完整讀取所需 reference；templates 只在實際產出時載入。

若已有 staged changes，或目標檔案有無法安全分離的使用者修改，停止並說明。只有使用者明確要求採納時才能納入目前操作。

## 操作路由

| 操作 | 必須完整讀取 |
|---|---|
| 已上線能力缺少完整 canonical coverage 或 accepted lineage，需要第一次收編或修改 | [rolling-adoption-workflow.md](references/rolling-adoption-workflow.md)、[grilling-workflow.md](references/grilling-workflow.md)、[spec-plan-workflow.md](references/spec-plan-workflow.md)；產出時再讀 blueprint、Brief、Spec 與 Plan templates |
| 建立、同步或審查 blueprint；依既有清楚需求調整 Slice；拆分、合併或撤回 Slice | [blueprint-workflow.md](references/blueprint-workflow.md)；產出時再讀 [blueprint-template.md](references/blueprint-template.md) 與 [slice-brief-template.md](references/slice-brief-template.md) |
| 建立 Spec、修改產品語義，或 Bug 的正確行為未由有效 Spec 唯一決定 | [grilling-workflow.md](references/grilling-workflow.md)，共同理解確認後接 [spec-plan-workflow.md](references/spec-plan-workflow.md)；產出時再讀 Spec／Plan templates |
| 核准完全未變更的 draft Spec／Plan | [spec-plan-workflow.md](references/spec-plan-workflow.md) 與 [commit-workflow.md](references/commit-workflow.md)；不載入 Grilling |
| 只修訂實作方法、Files、batches、commands 或 Verification Gates，產品 Scope、行為、Acceptance 與 Integration Contract 不變 | [spec-plan-workflow.md](references/spec-plan-workflow.md)；需要 commit 時再讀 [commit-workflow.md](references/commit-workflow.md) |
| 執行不改產品行為且可用自動化證明的小型 rename、refactor、formatting、test cleanup 或 type cleanup | [maintenance-workflow.md](references/maintenance-workflow.md) 與 [commit-workflow.md](references/commit-workflow.md) |
| 開始、繼續或修正已核准 implementation sequence | [implementation-workflow.md](references/implementation-workflow.md) 與 [commit-workflow.md](references/commit-workflow.md) |
| 執行 AI Verification；記錄 Human Integration 或 Human Acceptance | [verification-acceptance-workflow.md](references/verification-acceptance-workflow.md) 與 [commit-workflow.md](references/commit-workflow.md)；建立 Verification 時再讀 [verification-template.md](references/verification-template.md) |

同一 continuous sequence 只需讀取 commit workflow 一次；中斷後以 `$cogito` 恢復時重新讀取。Workflow 只有在實際 sequence handoff 時才載入下一個 workflow，不預載其他分支。

## Feature Slice 與文件識別

Feature Slice ID 使用 `FS-001` 格式並保持穩定；名稱使用英文 kebab-case。文件路徑使用：

```text
docs/blueprint/feature-slice-blueprint.md
docs/blueprint/slices/<ID>-<name>.md
docs/specs/<ID>/<ID>-<name>-spec.md
docs/plans/<ID>/<ID>-<name>-plan.md
docs/verification/<ID>/<ID>-<name>-verification.md
```

Type 只使用 `feature`、`change`、`correction`。`change` 使用 `Revises` 或第一次收編的 `Legacy Baseline`；`correction` 使用 `Corrects` 指向仍有效的 Authoritative Spec。已 `accepted` 的產品內容是不可變快照；後續需求改變建立新的 `change` Slice。

Spec Acceptance ID 在 Slice 內使用不重複的 `AI-001` 與 `HA-001`；Plan checks 使用 `V-001`；Human Integration 使用 `HI-001`。ID 不重新編號或重用；新 Slice 建立自己的 namespace。

## 狀態機

只使用 `proposed`、`awaiting-approval`、`approved`、`in-progress`、`awaiting-human`、`accepted`、`blocked`、`withdrawn`。

```text
proposed -> awaiting-approval -> approved -> in-progress -> awaiting-human -> accepted
```

- `awaiting-approval`、`approved`、`in-progress`、`awaiting-human` 為 active status。
- `blocked` 保存阻礙前狀態、原因與恢復條件；阻礙前狀態為 active 時，Blueprint 的 Active Feature Slice 保持該 ID。
- `withdrawn` 為終止狀態；保留 ID 與文件。
- 狀態轉移同步更新 blueprint 的 Status、Status Note 與 Last Updated；建立文件時同步 Documents link。

## 全域授權與完成條件

- Shared Understanding confirmation 只確認摘要正確；Boundary Gate pass 只確認 Slice 邊界；兩者都不授權文件修改、實作或 commit。
- Spec／Plan 核准同時核准 Commit Plan 與 Approval Documentation commit，單獨核准不授權實作。
- 同一訊息明確要求「核准並開始實作」時，Approval commit 後可直接進入已核准 sequence。
- `continuous` implementation 授權涵蓋尚未完成的已核准 batches、其 Required Verification、完整 AI Verification 與 Verification Documentation；不涵蓋未列入 Plan 的 remediation code。
- Rolling Adoption 與 Maintenance 的授權只涵蓋各自 Proposal 列出的 batch、檔案、證明與 commit。
- 每個步驟以已授權產出完成、必要檢查實際執行、狀態與文件一致為完成條件。
- 每次等待使用者時，提供包含 `$cogito` 的明確續接句，例如：`請以 $cogito 核准目前的 FS-001 Spec／Plan`。

## 相容性入口

Skill 更新本身不重寫既有文件或撤銷核准。舊文件依相關 workflow 的 legacy fallback 繼續執行；只有 active 文件在已授權操作中可做語義不變、映射無歧義且跨 Spec／Plan／Verification 原子完成的結構遷移。accepted snapshots 保持原樣。
