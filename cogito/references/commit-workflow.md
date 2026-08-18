# Commit Workflow

每次會建立 commit 的操作或中斷後恢復 sequence 時完整讀取一次。同一 continuous sequence 的 batches 共用本規則，不在每批重讀。

## 授權對照

| 明確授權 | 對應 commit |
|---|---|
| 建立或同步 blueprint | Blueprint Creation／Reconcile |
| 核准 Blueprint Revision Proposal | Proposal 指定的 Blueprint Revision |
| 核准 `docs/project/` 變更 | 已說明的下一個 Documentation Batch |
| 核准 Rolling Adoption Proposal | Proposal 指定的 Adoption Documentation commit |
| 建立 Spec／Plan | Draft Documentation |
| 核准 Spec／Plan | Commit Plan approval＋Approval Documentation |
| 開始 `continuous` implementation | 所有尚未完成的 implementation batches＋完整 AI Verification＋Verification Documentation |
| 開始或繼續 legacy `per-batch` Plan | 下一個 implementation batch |
| 提供 Human Acceptance 結果 | Final 或 Acceptance Feedback Documentation |
| 核准 Maintenance Proposal | Proposal 指定的單一 Maintenance commit |

核准 Spec／Plan本身不授權實作；但同一訊息若也明確要求開始實作，Approval commit 後直接進入 sequence。取得工作授權後不再另問是否 commit。模糊回覆不構成授權。

## Working tree 邊界

操作開始前記錄 `git status`、staged files 與目標檔案狀態。

- 有既存 staged changes 時停止，避免混入自動 commit。
- 保留無關的 unstaged／untracked 變更，不 stage 或提交。
- 目標檔案已有無法安全分離的使用者修改時停止。
- 只有使用者明確要求採納時，才將其既有修改納入本次範圍。
- 不建立空 commit，不 push，不 amend、rebase、squash、reset、cherry-pick 或 force push。

## Batch 設計

每個 batch 恰好對應一個 commit，回答一個清楚的審查問題，包含有限檔案與風險相稱的 Required Verification。保持可理解、可合理回退，且不包含其他 Slice 或無關變更。

可依 dependency／tooling、runtime／routing、使用者可見功能、tests 與 documentation 等目的拆分，但不要為追求 commit 數量拆開不可分割的工作，也不要以 `foundation` 或 `setup` 包入多種目的。

Commit message 使用：

```text
<type>(<scope>): <English summary>
```

Type 只使用 `docs`、`chore`、`build`、`feat`、`test`、`fix`、`refactor`。Feature Slice implementation scope 使用穩定英文模組名，body 加入：

```text
Feature-Slice: <ID>
```

文件 checkpoint 的 scope 使用 Slice ID；跨 Slice blueprint 使用 `blueprint`。

Maintenance 使用 `refactor`、`test` 或 `chore` 等符合實際目的的 type 與穩定英文模組 scope，不加入 `Feature-Slice` trailer。

## Maintenance commit

Maintenance 的 eligibility、Proposal、Invariants 與 proof sufficiency 由 [maintenance-workflow.md](maintenance-workflow.md) 唯一定義。本文件只負責 working-tree 邊界、exact staging、staged diff、message 與 commit creation。核准後建立一個 commit，不建立或更新 Plan row；commit 後回報並停止。

## 建立 commit

完成已授權 batch 後：

1. 執行核准的 Required Verification。
2. 檢查 working tree、實際 diff、untracked files 與 staged 狀態。
3. 確認 Files、Purpose、Scope、message 與 batch 順序符合授權。
4. 執行適用的 diff 檢查，包括 `git diff --check`。
5. 若本 batch 完成 Plan checkpoint，從 Commit Plan 移除該 row；阻礙性 Verification Documentation 只保存目前 evidence／state，保留 Verification row。第一個 implementation commit 同步保存 blueprint `approved -> in-progress`。這些是已核准 lifecycle housekeeping，不改變其他尚未完成 row。
6. 只 stage 本 batch 的明確檔案、Plan housekeeping，以及上一步允許的 blueprint lifecycle housekeeping。
7. 檢查 staged file list、staged diff 與排除項目。
8. 使用核准 message 建立 commit。
9. 在對話回報 Commit ID、message、檔案、排除項目與驗證結果；不寫入 Spec、Plan 或 Verification。
10. continuous sequence 直接進入 Plan 中下一個 batch；最後一個 implementation batch 後直接執行完整 AI Verification。

若 stage 後發現異常，只撤銷本次新增的 staging，不改 working tree 或操作開始前狀態。範圍內問題可修正並重跑驗證；需要新增／重組 batch、修改未核准檔案、改變 Spec／Plan／Integration Contract、處理範圍外失敗、分離重疊修改或取得人類決策時停止。

## 文件 checkpoints

| Checkpoint | Message | 內容與停止點 |
|---|---|---|
| Blueprint Creation | `docs(blueprint): create feature slice blueprint` | 主 blueprint 與 Brief；回報後停止 |
| Blueprint Reconcile | `docs(blueprint): reconcile feature slice blueprint` | 實際 reconcile 差異；無差異不 commit |
| Rolling Adoption | `docs(<ID>): adopt <capability> requirements` | canonical requirement、舊文件退役、partial blueprint 與 Brief；回報後停止，不建立 Spec |
| Blueprint Revision | `docs(<ID>): revise feature slice structure` 或 `docs(blueprint): revise feature slice structure` | 核准 Proposal 的 blueprint、Brief 與直接相關需求文件；回報後停止 |
| Draft | `docs(<ID>): draft <feature> specification` | draft Spec／Plan、必要 Brief 與 blueprint 狀態；回報後停止 |
| Approval | `docs(<ID>): approve <feature> specification` | approved Spec／Plan、必要 Brief 與 blueprint 狀態；沒有複合實作授權時停止 |
| Specification Revision | `docs(<ID>): revise <feature> specification` | 已授權修訂；實質變更回到 `awaiting-approval` |
| Verification | `docs(<ID>): record <feature> verification` | Verification 最新結果、Plan housekeeping 與 blueprint 狀態；回報後停止 |
| Final | `docs(<ID>): record <feature> acceptance` | completed 文件、accepted 狀態與必要 lineage；回報後停止 |
| Acceptance Feedback | `docs(<ID>): record <feature> acceptance feedback` | failed／changes-requested 的實際結果與狀態；回報後停止 |

建立完成的 checkpoint commit 前，從 Plan 移除對應的 Approval、Verification 或 Final row。Verification 有 `required: failed/not-run` 或未完成 `AI-*` closure 時屬於 attempt／blocker record，不完成 checkpoint，也不移除 row。合法 housekeeping 不建立額外 commit，也不將 Commit Plan Approval 改為 `pending`。

已核准但尚未提交的 `docs/project/` 變更，只納入最接近且已授權的 Documentation Batch，不重複提交。Approval 後出現新的產品語義 delta 時停止實作；下一輪以 `$cogito` 回到 Grilling 與 Boundary Gate，取得適用的文件 revision 授權後才更新 requirements、Spec／Plan 與 Commit Plan。Commit workflow 不直接建立未經該流程核准的 requirements revision。

## Commit Plan 變更

在同一 commit 移除完成的 checkpoint row 不算 Commit Plan 變更。若改變任何尚未完成 batch 的分組、順序、Files、Required Verification 或 message，更新 Plan 並將 Commit Plan Approval 設為 `pending`，等待重新核准後才執行受影響 batch。

若同時改變 Scope、主要實作方式、核心檔案、Integration Contract 或 Acceptance，撤銷 Spec／Plan 核准並回到 `awaiting-approval`。已提交實作需要修正時先提出 Plan revision proposal；取得明確 revision 授權後新增 `fix` batch，不改寫歷史。

Git history 是 Commit ID、已完成 batches、過去修訂、被取代驗證結果、已解決 failure 與詳細變更歷史的權威來源。Spec、Plan 與 Verification 不保存 commit ID、execution result、revision summary 或其他形式的 commit history；當次 commit 資訊只在對話回報。
