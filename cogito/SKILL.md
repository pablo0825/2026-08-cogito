---
name: cogito
description: Use when a user explicitly invokes $cogito, or directly answers the immediately preceding unresolved Cogito prompt in the same active run.
---

# Cogito

Cogito 用程式化 Gate 管理需求確認、開發、驗證、審查與結案。Agent 負責理解需求、執行工作與判斷語意；Gate 根據契約、狀態與證據決定能否前進。

## 何時啟動

使用者明確呼叫 `$cogito` 時，啟動或恢復。沒有 invocation 時，只有直接回答同一 active run 上一個未決的 Grilling 問題、摘要確認、Package approval 或 human gate 才續接；其他訊息依一般對話處理。`$cogito` 本身不是核准。

## 核心概念

| 名稱 | 用途 |
|---|---|
| Run（`DEV-*`） | 一次工作的狀態與事件歷史；恢復時依記錄續接 |
| Development Package | 凍結本次目標、範圍、任務、checks 與核准；是正式開發授權的依據 |
| Slice／Task | Slice 是可獨立驗收的產品結果；Task 是其內可交付的工作單位 |
| Technical Amendment | 已核准邊界內的追加修正，不改寫原 Package |
| Evidence | controlled runner 產生的正式檢查證據，綁定實際內容與契約 |
| RP／DP | RP 重新規劃已核准契約；DP 管理取消、保留、移除或恢復成果 |

Coordinator 按依賴派發工作並串行整合。Feature／Change／Correction 使用專用 branch/worktree，最多三個 Slice Worker；實作與獨立 review 由不同 Agent 負責。只有符合條件的 Maintenance 可豁免一般開發 review；Documentation 與人工驗收退回修正仍須獨立 review。

## 全程遵守

- 專案文件使用中文；ID、路徑、API、指令與狀態值使用英文。
- 初始化、恢復、Gate action、修改或提交前，讀適用的 `AGENTS.md`、專案政策與 Git 狀態。同一 Grilling action 內的連續純問答可沿用本輪資訊；只有新事實缺口、資訊可能變動或 Gate 操作需要時補查，詳見 [Grilling Workflow](references/grilling-workflow.md)。
- 一個 Package approval 是唯一正式開發核准。摘要確認授權提交該摘要；Boundary 通過後提交邊界判斷；兩者都不授權實作。
- 保留使用者既有變更，只修改 Package 或有效 Amendment 允許的路徑。Worker 不整合、不 push；已發布或已登錄完成的 commits 不改寫。未登錄的 Atomic 暫存 commit 修正依 [Execution Policy](references/execution-policy.md#task-中斷或檢查失敗)。
- 正式 checks 只透過 Gate 的 controlled runner 執行。核准、Boundary、check closure、review independence、human applicability 與狀態轉移由 CLI 計算，不能用 Agent boolean 或敘述取代。證據衝突時依「核准契約 > machine evidence > Agent description」保守處理。
- Package、歷史事件與 evidence 不覆寫；Technical Amendments 是 append-only。Python executable contracts 驗證資料，workflow JSON 定義合法轉移，Markdown 說明操作與語意，不另維護手寫 JSON Schema。
- 依 Gate 的 `next_action` 前進，不猜狀態或繞過 guard。缺漏、矛盾、超限或不可恢復錯誤時停止，依 [Runtime Interface](references/runtime-interface.md#停止條件與狀態操作) 核對與登錄阻塞；命令失敗不代表已進入 blocked。

## 啟動與操作迴圈

1. 首次操作 Gate 先讀 [Runtime Interface](references/runtime-interface.md) 開頭至「停止條件與狀態操作」的共通 CLI、輸入、儲存與重送規則；後面的固定操作恢復與其他查詢依需要讀取。使用 `cogito/scripts/cogito_gate.py` 查詢或建立 run；一般 `init` 保留預設的階段提交，有效 RP successor 依其凍結交接流程處理。未確認草稿放在 `.cogito/runs/<run-id>/drafts/`。
2. 準備文件前先按 [Package Authoring](references/package-authoring.md#選擇-package-類型) 選 `kind`。完整 Package 經摘要確認、Boundary 與 Slice／Spec／Plan；Mini 不建立這些文件，只準備 Package。Maintenance 單一交付 commit 從 Start Gate HEAD 起算。
3. 查詢 `next --run-id <ID>`，按下表找到目前流程。首次進入時完整讀取目前流程小節、其明列的前置規則與必要輸入；操作文件有入口說明時先依其選擇適用小節。同一流程後續步驟按需查閱，資料或規則改變時補讀，不因同一文件包含其他流程而預載無關分支或維護者實作說明。
4. 完成當前 action，以結構化 payload 回報。格式錯誤最多修復兩次，只修結構，不更改實際 code、evidence 或 risk。一般 mutation receipt 不含路由；需要繼續工作時另查 `next`，只有明確診斷才查完整 `status`，專用 receipt 見 [Runtime Interface](references/runtime-interface.md#json-輸入與顯示)。`commit-stage-artifacts` 必須先完成並登記精確文件提交。
5. 恢復時依事件歷史與現有成果核對，再續接合法下一步；計數器不因 resume 或換 Agent 重設。`cancelled`、`accepted`、`superseded` 是終態，不能用普通 resume 重新開發。

## 目前要讀哪份文件

| 目前工作或 `next_action` | 操作文件 |
|---|---|
| 需求問答、`draft-shared-understanding`、摘要呈現／確認／修訂 | [Grilling Workflow](references/grilling-workflow.md)；產出時讀其摘要格式 |
| `assess-mini-package-eligibility`、Boundary、Package 草擬／核准 | [Package Authoring](references/package-authoring.md)；需要 Spec／Plan 時讀對應 template |
| `commit-stage-artifacts` | [Stage Commits](references/stage-commits.md) |
| Start Gate、派工、Task、checks／重送、review、integration、`complete-implementation`、`start-leased-workers`、`resolve-executor-registration`、`submit-verification`、`submit-post-verification`、`complete-review`、`resolve-check-recovery` | [Execution Policy](references/execution-policy.md) |
| 範圍內 Amendment／correction、`prepare-review-fix`、`complete-review-fix`、`review-path-amendment`、`retry-path-amendment`、必要路徑補列與審查採認 | [Execution Corrections](references/execution-corrections.md) |
| `retry-fixed-action`、`recover-result-metadata` | [Runtime Interface](references/runtime-interface.md#固定操作與歷史登記恢復) |
| Package 核准前的規劃輪次、比較、覆核或撤回 | [Planning Revisions](references/planning-revisions.md) |
| 超出 Amendment 的已核准契約變更、`prepare-human-feedback-replan` | [Replanning](references/replanning.md) |
| RP 途中更新 Cogito 工具 | [RP Toolchain](references/replan-toolchain.md) |
| 人工驗收回饋、分類、修正、追加回饋或額度決策 | [Human Acceptance](references/human-acceptance.md) |
| 取消、放棄或撤回方案，移除／保留／恢復成果 | [Dispositions](references/dispositions.md) |
| `write-result-and-finalize`、結案回報、worktree cleanup 重試 | [Finalization](references/finalization.md) |
| 首次處理既有專案的能力與文件 | [Project Bootstrap](references/project-bootstrap.md) |

每份流程說明何時完成以及下一個入口；只在 Gate 要求或該條件確實適用時切換。沒有適用人工作業、判斷或高風險 hotspot 時，Gate 可自動進入 finalizing；有適用項目則等待人工。人工來源 RP successor 仍須重新人工驗收，DP follow-up 也須人工驗收。

## 正式資料放在哪裡

| 位置 | 內容與用途 |
|---|---|
| `docs/cogito/packages/DEV-*.json` | 不可變 Package；與有序 Amendments 形成 effective contract |
| `docs/cogito/project-graph.json` | Slice、依賴、lineage、disposition 與 `active_run_id` |
| `.cogito/runs/<run-id>/events.jsonl` | append-only 歷史；`state.json` 只是可重建快取 |
| controlled runner evidence | 不覆寫的內容尋址檔案，綁定 HEAD/tree、check 與 effective contract |
| `docs/cogito/shared-understanding/`、`docs/cogito/checkpoints/<run-id>/` | 摘要原文與階段提交記錄 |
| `docs/cogito/results/DEV-*.json` | 正式 Result；自身 final commit ID 由後續事件與報告記錄 |

Spec 定義產品語意，Plan 定義實作與驗證方法，Git 保存提交歷史。實際規則與資料不由對話記憶或衍生圖取代。
