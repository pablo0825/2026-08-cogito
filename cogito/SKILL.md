---
name: cogito
description: Use when a user explicitly invokes $cogito, or directly answers the immediately preceding unresolved Cogito prompt in the same active run.
---

# Cogito

以一個可執行 Gate workflow 管理需求釐清、切片、開發、驗證、獨立審查、整合與結案。Skill 定義語意政策；程式化 Gate 是狀態、轉移、計數器與下一步的唯一執行權威。

## 不變量

- 使用中文撰寫專案文件；ID、路徑、API、指令與狀態值使用英文。
- 每次操作先讀適用的 `AGENTS.md`、專案政策與 Git 狀態，再執行 Gate 回傳的 `next_action`。不得自行跳步、猜測狀態或繞過 guard；資料缺漏、矛盾或 Gate 失敗時 fail closed。
- 一個 Development Package approval 是唯一正式開發核准。Shared Understanding confirmation 只確認理解正確；Boundary Gate pass 只確認邊界，兩者都不授權實作。
- Feature、Change、Correction 一律由 Coordinator 在專用 branch/worktree 派發 1–3 個 Worker；依 Project Graph DAG 動態安排，不存在執行模式選擇。Coordinator 串行整合回 Package 固定的 delivery branch。
- Worker 不直接整合、不 push、不改寫 Git history。保留使用者既有變更；只修改 Package 或有效 Technical Amendment 允許的路徑。
- Feature Slice 必須由不同於 Implementer 的 Reviewer 審查。只有符合客觀低風險條件的 Maintenance 可豁免獨立審查。
- 正式 checks 只由 controlled runner 執行；Agent 敘述不是證據。runner 只保留 bounded head/tail 診斷輸出，合計輸出超過 Policy/Package 固定上限時終止 check 並 fail closed。證據衝突時依「核准契約 > machine evidence > Agent description」保守處理。
- 核准、Boundary、check closure、獨立審查、human applicability 與狀態轉移等敏感 verdict 只能由 runtime CLI 根據可驗證輸入計算。Agent 只回報觀察、證據與建議，不得用 boolean 自行宣告 guard 通過。
- 沒有適用的 Human Integration、Human Acceptance 或高風險 hotspot 時，完成 `finalizing` 後自動 `accepted`，只向使用者提供結案報告；否則停在單一 human gate。

## 啟動與續接

訊息含 `$cogito` 時啟動或恢復。沒有 invocation 時，只有直接回答上一個未決 Grilling 問題、摘要確認、Package approval 或 human gate 才可續接；其他訊息依一般對話處理。`$cogito` 本身不是核准。

## 執行協定

1. 執行 `cogito/scripts/cogito_gate.py` 查詢或建立 run；run 草稿保存在 `.cogito/runs/DEV-*/drafts/`。
2. 完整讀取 Gate `next_action` 指定的 reference 與輸入，只執行該 action。
3. 以結構化 payload 回報 action 結果；格式錯誤最多修復兩次，修復不得改 code、evidence 或 risk。
4. 每次轉移後再次查詢 Gate。計數器跨 resume 與 Agent 更換保留；不得用對話記憶代替 event history。
5. `blocked` 只能經 Resume Gate 回到合法狀態；`cancelled` 與 `accepted` 是終態。

狀態主路徑為：

```text
preparing -> awaiting-shared-confirmation -> boundary-analysis
-> package-preparing -> awaiting-package-approval -> start-gate
-> executing -> verifying -> reviewing -> integrating -> executing (下一個 DAG wave)
-> post-integration-verification -> awaiting-human | finalizing -> accepted
```

允許的受控循環：`verifying -> technical-correction -> verifying`，總計最多三輪；`reviewing -> review-fix -> verifying -> reviewing`，最多三輪；`post-integration-verification -> post-integration-correction -> post-integration-verification` 共用前者 correction 預算，修正後不重複 integration。Transient retry 最多兩次。任何超限、契約漂移或不可恢復衝突皆進入 `blocked`。

## 操作路由

| Gate action | 必須完整讀取 |
|---|---|
| Grilling、摘要確認 | [grilling-workflow.md](references/grilling-workflow.md)、[shared-understanding-contract.md](references/shared-understanding-contract.md) |
| Boundary 分析、Package 草擬或核准 | [package-authoring.md](references/package-authoring.md)，產出時再讀 Spec／Plan template |
| Start Gate、Worker、驗證、審查、整合、修正或結案 | [execution-policy.md](references/execution-policy.md)、[runtime-interface.md](references/runtime-interface.md) |
| 首次在舊專案處理能力 | [project-bootstrap.md](references/project-bootstrap.md) |

不要預載其他 reference。Gate schema 與 workflow JSON 是機器契約；Markdown reference 解釋 Agent 應遵守的語意。

## 權威資料

- `docs/cogito/project-graph.json`：Slice 結構、依賴、lineage、disposition、`active_run_id`。
- `docs/cogito/packages/DEV-*.json`：不可變 Development Package；Technical Amendments 是 append-only overlay。
- `.cogito/runs/<run-id>/events.jsonl`：append-only 執行歷史；`state.json` 是可重建 projection/cache。
- controlled runner evidence：以不覆寫的內容尋址檔案綁定 HEAD/tree、check definition 與 effective contract hash。Gate 先將 base Package 與有序 amendments materialize 為 effective contract 快照，runner 不接受 Agent 自行組合的契約。
- `docs/cogito/results/DEV-*.json`：結案結果。
- Spec／Plan Markdown：產品語意與實作方法；Git：提交歷史。

`Blueprint`、`Slice Brief`、Verification Markdown、Commit Plan 與文件內 approval/status metadata 不再使用。

## 文件與邊界

Feature Slice ID 使用穩定的 `FS-001` 格式。Spec 路徑為 `docs/specs/<ID>/<ID>-<name>-spec.md`；Plan 路徑為 `docs/plans/<ID>/<ID>-<name>-plan.md`。新的正式控制文件放在 `docs/cogito/`。

適用邊界由 global defaults、可選 project policy 與 Package snapshot 疊加，較嚴格者優先；缺少 project policy 不阻塞。永久放寬或修改 project policy 需另行取得 project-level approval。

Technical Amendment 只能在已核准路徑內增加 checks、tests、tasks，或修正內部實作；不得刪除或降級 required checks、擴張路徑、改 Acceptance、公開 API、資料模型、安全邊界、依賴或 DAG。有效契約 hash 由 base Package 與有序 amendments 計算；相關 commit 使用 `Cogito-Amendment` trailer。

## 最終化

進入 `finalizing` 後，以單一 final commit 原子保存 Result JSON、Project Graph disposition、清除 `active_run_id`、已知 amendment/commit 摘要及必要且合法的 Spec／Plan 更新。Result 不記錄包含自身的 final commit ID；commit 成功後才把該 ID 寫入 append-only event 與結案報告，再標記 `accepted`。任一步失敗為 `blocked`。結案報告至少列出結果、checks、review、commit IDs、amendments、是否經 human gate 及剩餘風險。

Maintenance 與 documentation-only adoption 使用同一引擎的 Mini Package profile，不建立 Slice、Spec 或 Plan，僅跳過 runtime 以客觀 guard 證明不適用的節點；不是另一套 workflow。Maintenance 還必須不改產品行為或契約、不改依賴/安全/資料邊界、路徑固定、可以 deterministic checks 覆蓋並以目前 checkout 單一 commit 完成；documentation-only 還必須只整理或引用既有語意。任一條無法證明即回到 Grilling／完整 Package。
