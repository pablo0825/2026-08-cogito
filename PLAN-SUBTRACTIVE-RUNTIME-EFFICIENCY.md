# Cogito Runtime 效率減法計畫

日期：2026-09-07。基準：Cogito 3.6.1。狀態：實作中；第一版獨立審查後修正 receipt 邊界，待模擬驗收。

本文件記錄 repository maintenance 的修改計畫與實作邊界，不是 Cogito Run、Package 或 Gate 授權。本案不修改後端產品、DEV-002 ledger 或既有歷史事件。

## 1. 結論：本輪只保留一個必要修改

將一般 Run mutation 的 CLI 成功輸出，由完整 `RunState` 改成最小 receipt；完整狀態只由既有 `status` 查詢提供。

這是目前唯一同時符合以下條件的修改：

1. 直接切斷 FS-039 已觀察到的主要 Token 浪費。
2. 不改事件、projection、state cache、evidence 或 Gate 決策語意。
3. 不新增另一套儲存、telemetry、排程或恢復協定。
4. 可用明確輸出大小與事件不變性驗收。

本輪不外移 planning snapshot、不新增通用 output mode、不新增 evidence 瀏覽命令、不修改 interrupted-check recovery，也不將後端特定的 migration／reservation 問題做成 Cogito 通用規則。

## 2. 實證基準

以後端 DEV-002／FS-039 的既有 artifacts 唯讀量測：

- `state.json`：900,374 bytes。
- `events.jsonl`：937,620 bytes，82 筆事件。
- 目前 CLI 包裝完整最終 state：904,377 bytes。
- 等價的通用四欄 receipt（run、state、sequence、event hash）：194 bytes，輸出減少約 99.98%。
- 30 次本機唯讀量測中位數：讀取 events 4.562 ms、projection 6.512 ms、完整 JSON 序列化 1.912 ms；三者合計約 13 ms。

因此目前證據支持「大型 stdout 進入 Agent context」是必要修正；不支持為約 13 ms 的本機處理成本立即引入新的 snapshot artifact lifecycle。FS-039 約 103 分鐘的最大延誤來自 interrupted-check recovery 修補，不是 JSON replay。

上述毫秒數是單機方向性基準，不作跨平台效能承諾。驗收重點是輸出 bytes 與不改變權威資料，而不是追求不可靠的固定執行時間。

## 3. 減法評估

| 候選修改 | 本輪決定 | 理由 |
| --- | --- | --- |
| Mutation 回傳最小 receipt | 保留 | 直接移除重複輸出，收益最大、語意變動最小 |
| `status` 提供完整 state | 保留既有能力 | 已有明確查詢入口，不需再造 `--output full` |
| `--output receipt\|full\|summary` 模式矩陣 | 刪除 | 與 `status` 重複，增加文件、測試與 Agent 選擇成本 |
| 將 candidate snapshot 搬到新 artifact store | 延後 | 目前 replay 僅毫秒級；會擴張 immutable storage、GC、缺檔恢復及歷史相容性 |
| 新增常駐 Token／compaction telemetry | 刪除 | Cogito 無法量得模型 Token；持久化 metrics 反而增加資料與契約 |
| 新增 Gate bytes telemetry | 不做 runtime 功能 | 只在測試／benchmark 計算 stdout bytes，避免新狀態 |
| 新增 `show-evidence --tail` | 刪除 | runner 已限制並保存有界 head/tail；FS-039 的 900 KB 主因不是 evidence 內嵌 |
| 恢復舊 `resolve-check-attempt` | 刪除 | 3.6.1 已有較窄的 `check-preparation-failed` 受控重試 |
| 通用 SQL FK／unique preflight | 刪除 | 是後端資料庫契約，不應讓 Cogito 理解產品 SQL 語意 |
| 預測實作將需要哪些 Package 路徑 | 刪除 | Gate 無可靠資訊提前推斷；保留既有精確 path amendment |
| 依工作類型動態調整模型 reasoning effort | 延後至宿主層 | 不屬於 Gate 的權威工作流或本 repo 可驗證範圍 |

## 4. 最小輸出契約

### 4.1 Mutation receipt

一般 Run mutation 成功後只輸出：

```json
{
  "ok": true,
  "data": {
    "run_id": "DEV-002",
    "state": "executing",
    "sequence": 35,
    "last_event_hash": "<hash>"
  }
}
```

規則：

- receipt 使用該 mutation 已產生的 projection，不為輸出再讀一次 events 或 state cache。
- `sequence` 與 `last_event_hash` 讓呼叫者確認實際落盤位置；不複製 tasks、planning、history、agent results、evidence 或完整 Package。
- 通用 receipt 不含 `next`。`RunStore.next_action` 還會套用 RP／DP、path amendment、fixed action 與 recovery overrides，不能由純 `derive_next_action` 取代；mutation 後需要路由時另查既有 `next`。
- 已有專用 receipt 的 `task-finish`、`review-fix-start` 等命令保留其必要欄位，不先轉回完整 state 再裁切。
- `run-check` 使用 action ID 精確綁定其 `check-evidence-recorded` event，專用 receipt 加回 `check_id`、`evidence_path`、`evidence_hash`、`head_commit` 與 `effective_contract_hash`；重送舊 action 不得改指向較新的 evidence。
- `finalize` 專用 receipt 加回不可由 `status` 重建的 transient `cleanup.removed`、`cleanup.retained` 與存在時的 `cleanup.error`，讓 Coordinator 能按既有 finalization 流程回報或重試。
- action replay 不追加事件；receipt 反映重送完成時的目前權威 projection。既有 replay 本來就回傳目前 state，因此不新增儲存去保證兩次 receipt bytes 完全相同。
- 失敗維持 stderr 的 `{ "ok": false, "error": ... }` 與 exit code `2`，不為本案另建錯誤格式。

### 4.2 Query 輸出

- `status`：維持完整、經驗證的 `RunState`，作為唯一一般完整狀態入口。
- `next`、`report`、`delivery-summary`、planning history／compare、RP／DP status 等唯讀查詢：維持各自既有目的與資料 shape，不套用 mutation receipt。
- `validate`、`render` 等非 Run mutation：維持既有輸出。

這個分界以「命令是否追加權威事件或完成固定 mutation」判定，不以輸出大小猜測，也不建立多種可組合 output mode。

## 5. 相容性決策

將 mutation 預設輸出從完整 state 改成 receipt，會改變公開 CLI stdout contract。依本 repository 的版本政策，直接採用此減法方案應視為不相容變更，實作完成時升至 `4.0.0`；計畫本身不更新 VERSION。

建議直接採此方案，理由是：

- `status` 已提供完整 state，不會失去能力。
- 保留 mutation 的完整輸出只為相容而重複大量資料，正是本案要移除的成本。
- 新增暫時性的 `--receipt` 再於未來移除，會多維護一個過渡介面與兩組行為。

若使用者確認有外部腳本依賴 mutation 的完整 stdout，停止實作此預設變更，另擬 3.x 相容過渡方案；不得在實作中臨時加入隱藏 fallback 或環境變數。

## 6. 分包實作

本案只需兩個小包，共用檔案串行修改。

| Task | 單一責任 | 預計 production／文件範圍 | 驗收重點 |
| --- | --- | --- | --- |
| T-001 | 建立通用四欄 formatter 與必要的 check／finalize 專用 receipt，讓 Run mutations 在 CLI 邊界裁切輸出 | `cogito/scripts/cogito_run_queries.py`、`cogito/scripts/cogito_run_store.py`、`cogito/scripts/cogito_gate.py`；相關 tests | receipt shape、精確 evidence replay、cleanup、錯誤輸出、query 不變、通用 formatter 不推導路由 |
| T-002 | 更新唯一輸出規則文件、操作範例與版本 | `cogito/references/runtime-interface.md`、必要的 `SKILL.md` 短提醒、`cogito/VERSION`；相關 tests | 文件只有一份完整規則、範例不要求 Agent 讀 mutation full state、版本符合不相容變更 |

若 T-001 顯示某個 mutation 只有完整 state 才能安全判斷下一步，先縮小成該命令的必要 receipt 欄位；不因此恢復全部 state。若必要欄位無法有界化，停止並回報該命令，不擴張成通用查詢語言。

## 7. Acceptance Criteria

- AC-01：使用 DEV-002 規模（至少 30 份 planning 文件、約 900 KB projection）的 fixture，代表性的一般 mutation 成功 stdout 小於 2 KiB；check、finalize 與 fixed-operation 專用 receipts 依其必要欄位另驗，不用靜默截斷達成上限。
- AC-02：同一組操作在修改前後產生相同的權威 events、event hashes、projected state 與 state cache；只允許 CLI stdout 不同。
- AC-03：`status` 仍回傳完整 state；`next` 與其他 query 的既有資料不被 receipt formatter 裁切。
- AC-04：第一次成功 receipt 的 `sequence`、`last_event_hash`、`state` 與 mutation 後 projection 一致；通用 receipt 不含 `next` 或自行推導 RP／DP 等路由；相同 action ID 重送不重複事件，並清楚回報重送時的目前 projection，不假稱是原始時點的 state。
- AC-05：`task-finish`、`review-fix-start` 既有專用 receipt 的必要 commit、evidence、amendment、task 與 next 資訊不遺失；`run-check` 重送精確回傳原 action evidence，`finalize` 回傳 cleanup outcome。
- AC-06：成功輸出不含 `planning.candidate.files`、完整 tasks、agent results 或 evidence collection。
- AC-07：失敗輸出、exit code、UTF-8 JSON 與無 traceback 規則維持不變。
- AC-08：Agent 在 mutation 後需要路由時查 `next` 即能繼續正常流程；只有診斷或明確查詢時才使用 `status`。

## 8. 測試與驗證

T-001 先跑直接相關的純 formatter 與黑箱 CLI tests，至少涵蓋：

- 一個一般 mutation、專用 fixed-operation receipt、action replay、失敗路徑。
- `status`、`next`、`report` 等 query 不變。
- 大型 planning candidate 的輸出 bytes regression。
- receipt formatter 不修改傳入 projection，通用 formatter 不呼叫 `derive_next_action` 或 `RunStore.next_action`。
- 通用 receipt 不增加 EventRepository read/project；`run-check` 只以 action ID 精確讀取已登錄 event，不用 latest/max 推測 evidence。
- 真 CLI 的 `run-check` 首次、較晚重送與 `verify` 交接，以及 `finalize` cleanup retained/error 的可觀察性。

再跑受 CLI 輸出影響的既有 `test_gate_cli_contract`、`test_task_finish`、`test_review_fix_start`、`test_planning_cli`、`test_package_revisions`、`test_check_retry` 與 action replay 測試。由於 CLI 成功輸出橫跨一般 Run mutations，整批完成後執行全套 `unittest` regression；mypy、skill format、文件引用與 `git diff --check` 分開報告。測試失敗不能以更新 assertion 掩蓋必要 receipt 欄位或權威狀態差異。

另外做一次合成操作閱讀模擬：Package 準備／核准、Atomic Task、controlled check、review-fix、integration、finalization 各走一次，確認操作文件不再引導 Agent 消費完整 mutation state。這是文件／行為模擬，不是正式 Gate review evidence。

## 9. 延後項目的重新評估門檻

本輪交付後，只有符合任一條件才重新討論 snapshot artifact 化：

1. 代表性大型 Run 的 events read＋projection 在相同環境 P95 超過 100 ms，且確認成本來自 inline candidate snapshot。
2. 非外部程序型 Gate command 的 wall time 有超過 10% 可歸因於 event replay／state serialization。
3. 單一 state／event 大小接近既有檔案系統、宿主或備份流程的明確操作上限。

若觸發，另寫獨立計畫，優先評估重用現有 hardened Git object／Start artifact 能力；不預設新增平行 artifact store。新格式必須保留舊 inline events 的唯讀 replay，禁止重寫歷史 hashes。

## 10. 明確不在本案範圍

- 不修訂 FS-039 後端產品 code、migration 或 reservation tests。
- 不修改 DEV-002 events、state、evidence 或 Git 歷史。
- 不順手同步後端 FS-039 blueprint 狀態；那是獨立文件維護。
- 不修改 Package、Agent Result、evidence、workflow 或 event contracts。
- 不改 controlled runner 的 output cap、timeout 或 process termination。
- 不增加自動派工、上下文摘要、模型選擇、reasoning effort 或 Agent memory。
- 不宣稱可以從 Cogito bytes 精確推算模型 Token、cache 或 compaction。

## 11. 停止條件與待確認事項

實作前只需要確認一件事：是否接受 mutation CLI stdout 的不相容精簡，並將完成版本升為 `4.0.0`。

若答案是否定，保留本計畫的問題定義與驗收資料，但停止 T-001／T-002；另擬最小 3.x 過渡方案。若答案是肯定，依 T-001 → T-002 執行，不把已刪除或延後項目帶回本次交付。
