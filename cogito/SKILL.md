---
name: cogito
description: Use when a user explicitly invokes $cogito, or directly answers the immediately preceding unresolved Cogito prompt in the same active run.
---

# Cogito

以一個可執行 Gate workflow 管理需求釐清、切片、開發、驗證、獨立審查、整合與結案。Skill 定義語意政策；程式化 Gate 是狀態、轉移、計數器與下一步的唯一執行權威。

## 不變量

- 使用中文撰寫專案文件；ID、路徑、API、指令與狀態值使用英文。
- 初始化、恢復執行、執行 Gate action、修改專案或提交前，先讀適用的 `AGENTS.md`、專案政策與 Git 狀態，依 Gate 回傳的 `next_action` 操作。同一 Grilling action 內的連續純需求問答可沿用本輪已讀取的資訊，不因單題回答而重讀政策、重查 Git 或重新查詢 Gate；發現新事實缺口或資訊可能已變動時，補做相關查證。問答與保存時機依 [Grilling Workflow](references/grilling-workflow.md)。不得自行跳步、猜測狀態或繞過 guard；資料缺漏、矛盾或 Gate 失敗時 fail closed。
- 一個 Development Package approval 是唯一正式開發核准。Shared Understanding confirmation 確認理解正確並授權提交該摘要；Boundary Gate pass 後提交邊界判斷，兩者都不授權實作。
- Feature、Change、Correction 一律由 Coordinator 在專用 branch/worktree 派發 1–3 個 Worker；依 Project Graph DAG 動態安排，不存在執行模式選擇。Coordinator 串行整合回 Package 固定的 delivery branch。
- Worker 不直接整合、不 push，不改寫已發布或已登錄完成的 commits。Atomic Task 尚未發布、尚未登錄完成的暫存 commit 若檢查失敗，可在原 lease base 與 paths 內整理成一個 commit；保留舊 evidence 並重跑相關檢查。保留使用者既有變更；只修改 Package 或有效 Technical Amendment 允許的路徑。
- Feature Slice 必須由不同於 Implementer 的 Reviewer 審查。只有符合客觀低風險條件的 Maintenance 可豁免一般開發審查；人工驗收退回修正仍須獨立審查。
- 正式 checks 只由 controlled runner 執行；Agent 敘述不是證據。runner 比對 check 前後的 worktree snapshot，期間有變動即拒絕該次 evidence；只保留 bounded head/tail 診斷輸出，合計輸出超過 Policy/Package 固定上限時終止 check 並 fail closed。證據衝突時依「核准契約 > machine evidence > Agent description」保守處理。
- 核准、Boundary、check closure、獨立審查、human applicability 與狀態轉移等敏感 verdict 只能由 runtime CLI 根據可驗證輸入計算。Agent 只回報觀察、證據與建議，不得用 boolean 自行宣告 guard 通過。
- 沒有適用的 Human Integration、Human Acceptance 或高風險 hotspot 時，完成 `finalizing` 後自動 `accepted`，只向使用者提供結案報告；否則進入 human gate；人工驗收來源的 RP successor 也必須重新人工驗收。

## 啟動與續接

訊息含 `$cogito` 時啟動或恢復。沒有 invocation 時，只有直接回答上一個未決 Grilling 問題、摘要確認、Package approval 或 human gate 才可續接；其他訊息依一般對話處理。`$cogito` 本身不是核准。

## 執行協定

1. 執行 `cogito/scripts/cogito_gate.py` 查詢或建立 run；一般 run 的 `init` 預設啟用階段提交，不關閉此檢查；有效 RP successor 依既有凍結交接流程初始化。未確認草稿保存在 `.cogito/runs/DEV-*/drafts/`。
2. 完整讀取 Gate `next_action` 指定的 reference 與輸入，只執行該 action。
3. 以結構化 payload 回報 action 結果；格式錯誤最多修復兩次，修復不得改 code、evidence 或 risk。
4. 每次轉移後再次查詢 Gate。`commit-stage-artifacts` 時依 [Stage Commits](references/stage-commits.md) 提交並登記該階段的精確文件，完成後才前進。計數器跨 resume 與 Agent 更換保留；不得用對話記憶代替 event history。
5. 一般 `blocked` 經 Resume Gate 回到合法狀態；核准前修訂可依 planning Gate 的合法來源檢查開啟規劃輪次；`cancelled`、`accepted` 與 `superseded` 是終態。

狀態主路徑為：

```text
preparing -> awaiting-shared-confirmation -> boundary-analysis
-> package-preparing -> awaiting-package-approval -> start-gate
-> executing -> verifying -> reviewing -> integrating -> executing (下一個 DAG wave)
-> post-integration-verification -> awaiting-human | finalizing -> accepted
```

允許的受控循環：`verifying -> technical-correction -> verifying`，總計最多三輪；`reviewing -> review-fix -> verifying -> reviewing`，最多三輪；`post-integration-verification -> post-integration-correction -> post-integration-verification` 共用前者 correction 預算，修正後不重複 integration。Transient retry 最多兩次。任何超限、契約漂移或不可恢復衝突，Coordinator 都須停止推進並依 Runtime Interface 登錄 `block`；命令報錯不代表狀態已自動改變。

人工退回走 `awaiting-human -> human-feedback-triage -> human-correction -> human-correction-verifying -> human-correction-reviewing -> awaiting-human | finalizing`。人工修正同一 run 獨立累計三輪；每輪實際 start 計次，不因分批、resume 或換 Agent 重設。局部修正若沒有明確「其餘已接受、修好可結案」授權，完成後仍回人工驗收；混合變更或影響擴大依 RP 處理。先讀 [Human Acceptance](references/human-acceptance.md)。

Package 的 `stop_conditions` 是供 Coordinator 依證據判讀的凍結政策，Gate 只驗證欄位格式，不解析任意條件文字。宣告的 `outcome` 不會取代合法狀態轉移、Human Gate 判定或取消授權。

Package 核准前候選需變更時，先讀 [Planning Revisions](references/planning-revisions.md)，以 `planning begin` 在同一 run 建立新輪次，保存舊方案並暫停其核准。依影響重新確認需求／Boundary／文件；不同候選都需新輪次，經獨立覆核後才呈現新版供使用者核准。語意影響與沿用理由由 Agent 判斷，不能把 hash 一致當作內容正確。

核准契約需要變更時，使用獨立 `RP-*` 重新規劃單管理全體停止、影響分析、獨立覆核、明確核准與 successor 交接；先讀 [Replanning](references/replanning.md)。不得用普通 resume、改寫 Package 或人工清 Project Graph 代替交接。新流程核准不等於已完成交接。

取消、放棄或撤回已核准方案使用獨立 `DP-*` 成果處置，先讀 [Dispositions](references/dispositions.md)。停止與保存後，原任務取消和成果處置分別追蹤；Agent 提案、獨立覆核、使用者審核後才執行移除／保留／恢復。受影響任務暫停，其他任務可繼續；DP follow-up 必須人工驗收。

## 操作路由

| Gate action | 必須完整讀取 |
|---|---|
| 核准前候選修訂、規劃輪次、比較、撤回與恢復 | [planning-revisions.md](references/planning-revisions.md) |
| 人工驗收回饋、修正、條件式結案與升級 | [human-acceptance.md](references/human-acceptance.md) |
| 取消、成果移除／保留、撤回核准與恢復原方案 | [dispositions.md](references/dispositions.md) |
| 已核准契約變更、重新規劃、承接與恢復 | [replanning.md](references/replanning.md) |
| RP 途中更新專案內 Cogito、工具版本接軌 | [replan-toolchain.md](references/replan-toolchain.md) |
| Grilling、摘要確認 | [grilling-workflow.md](references/grilling-workflow.md)、[shared-understanding-contract.md](references/shared-understanding-contract.md) |
| Boundary 分析、Package 草擬或核准 | [package-authoring.md](references/package-authoring.md)，產出時再讀 Spec／Plan template |
| 階段文件提交與登記 | [stage-commits.md](references/stage-commits.md) |
| Start Gate、Worker、驗證、審查、整合、修正或結案 | [execution-policy.md](references/execution-policy.md)、[runtime-interface.md](references/runtime-interface.md) |
| 首次在舊專案處理能力 | [project-bootstrap.md](references/project-bootstrap.md) |

不要預載其他 reference。Python executable contracts 是資料驗證規則的唯一來源，workflow JSON 定義狀態轉移；Markdown reference 解釋 Agent 應遵守的語意。JSON 是實際資料，不另維護手寫 JSON Schema。

## 權威資料

- `docs/cogito/project-graph.json`：Slice 結構、依賴、lineage、disposition、`active_run_id`。
- `docs/cogito/packages/DEV-*.json`：不可變 Development Package；Technical Amendments 是 append-only overlay。
- `.cogito/runs/<run-id>/events.jsonl`：append-only 規劃輪次、候選文件快照與執行歷史；`state.json` 是可重建 projection/cache。
- controlled runner evidence：以不覆寫的內容尋址檔案綁定 HEAD/tree、check definition 與 effective contract hash。Gate 先將 base Package 與有序 amendments materialize 為 effective contract 快照，runner 不接受 Agent 自行組合的契約。
- `docs/cogito/results/DEV-*.json`：結案結果。
- `docs/cogito/shared-understanding/`：供確認及提交的摘要；`docs/cogito/checkpoints/<run-id>/`：已完成階段的事件、文件 hash 與 Git 基線紀錄。
- Spec／Plan Markdown：產品語意與實作方法；Git：提交歷史。

`Blueprint`、`Slice Brief`、Verification Markdown、Commit Plan 與文件內 approval/status metadata 不再使用。

## 文件與邊界

Feature Slice ID 使用穩定的 `FS-001` 格式。Spec 路徑為 `docs/specs/<ID>/<ID>-<name>-spec.md`；Plan 路徑為 `docs/plans/<ID>/<ID>-<name>-plan.md`。新的正式控制文件放在 `docs/cogito/`。

適用邊界由 global defaults、可選 project policy 與 Package snapshot 疊加，較嚴格者優先；缺少 project policy 不阻塞。永久放寬或修改 project policy 需另行取得 project-level approval。

Technical Amendment 只能在已核准路徑內增加 checks、tests、tasks，或修正內部實作；新增 check 的 `env_allowlist` 不得超出 Package 凍結的 `allowed_environment`。不得刪除或降級 required checks、擴張路徑、改 Acceptance、公開 API、資料模型、安全邊界、依賴或 DAG。有效契約 hash 由 base Package 與有序 amendments 計算；相關 commit 使用 `Cogito-Amendment` trailer。

Maintenance 修正先記錄未提交的工作樹快照並重跑 checks，直到唯一 final commit 才保存修正與全部 amendment trailers；Result 記錄基線與快照，結案報告再補 final commit ID。操作格式依 Execution Policy／Runtime Interface，不提前建立修正 commit。

## 最終化

啟用階段提交的 run 先執行 `delivery-summary --run-id <ID>`，將 Gate 產生的事件摘要原樣放入 Result 的 `delivery_summary`。缺少摘要或摘要與實際準備、實作、整合、驗證、審查及人工接受紀錄不符時，不得結案。Feature／Change／Correction 每個 Task 的實作、相關測試及必要文件必須獨立 commit，targeted checks 通過並記錄 Result 後才繼續；本地只跑變更及相關檢查，完整 regression 交給 CI。整合可 fast-forward，檢查本身不建立空 commit。詳見 [Stage Commits](references/stage-commits.md)。

進入 `finalizing` 後，以單一 final commit 原子保存 Result JSON、Project Graph disposition、清除 `active_run_id` 及已知 amendment/commit 摘要。結案內容必須符合最後驗證的 `content_tree`，僅該 run 的 Result 與 Project Graph 可以在驗證後更新；必要且合法的 Spec／Plan 更新須在最後驗證前完成。舊 evidence 缺少此 tree 時重跑 checks，不補寫證據。Result 不記錄包含自身的 final commit ID；commit 成功且內容驗證通過後才把該 ID 寫入 append-only event 與結案報告，再標記 `accepted`。任一步失敗先停止操作、查明事件是否已提交，再依 Runtime Interface 處理阻塞與復原。結案報告至少列出結果、checks、review、commit IDs、amendments、是否經 human gate 及剩餘風險。

`kind` 為 `maintenance` 或 `documentation` 時，使用同一引擎的 Mini Package，不建立 Slice、Spec 或 Plan。Package 類型與審查規則由 Python Gate 實作；只有符合條件的 Maintenance 可免獨立 Reviewer，documentation 仍須獨立審查。Maintenance 還必須不改產品行為或契約、不改依賴/安全/資料邊界、路徑固定、可以 deterministic checks 覆蓋並以目前 checkout 單一 commit 完成；documentation-only 還必須只整理或引用既有語意。Coordinator 依來源、diff 與行為相關 checks 提出證據，供 Package 核准時確認；Gate 驗證凍結的 guard 與正式 evidence，不能自行證明語意等價。任一條缺乏足夠證據即回到 Grilling／完整 Package。
