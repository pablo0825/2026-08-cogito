# 後繼 run／工作承接實測

## 結論

問題**確實存在**。以下案例以真正的暫存 Git repository、`RunStore` Gate 與原本 feature E2E fixture 執行；沒有偽造 event，也沒有修改產品程式。

Cogito 能保存被阻塞 run 的現場，也允許另外建立 change run；但兩者之間沒有完整、具交易性的 handoff。現有 runtime 可以在人工改 Project Graph、另訂 Slice ID／lineage、另用 branch/worktree 後開始新 run。這是一組 runtime 可接受的人工操作，**不是已有文件定義、可稽核且可中斷復原的正式重新規劃流程**。

## 反例一：cancel 不會釋放後繼 run 所需資源

舊 run 在 `FS-A/T-A` 已整合、`FS-B/T-B` 已 leased/running 且 worktree 有未提交內容時 block，再以合法 `cancel(authorized=True)` 結束：

- 舊 run 變為 `cancelled`，但 Project Graph 完全未變，`active_run_id` 仍指向舊 run。
- `T-A=integrated`、`T-B=running` 和 lease 原樣保留。
- B worktree 的未提交內容仍存在；這符合「保存現場」，但沒有停止、釋放或交接事件。
- 新 change run 可走完 shared understanding、boundary、prepare；`approve_package` 失敗：`another Cogito run is active in Project Graph`。

因此 `cancel` 不是 handoff/finalization Gate，新 run 沒有正式取得 Project Graph 控制權的路徑。

## 反例二：人工清鎖後可走，但會遺失/覆寫契約身分

人工把 Project Graph 的 `active_run_id` 設為 `null` 後：

1. 若新 run 重用仍為 `active` 的 `FS-A/FS-B` ID，`approve_package` 會成功，並把 Slice 的 `introduced_by`、spec、plan 等 metadata 覆寫成新 run；舊 event log byte-for-byte 保留，但 Project Graph 看不出原本是舊 run 引入。所有新 task 都重設為 `pending`。這不符合「保留原核准與 lineage」的核心要求。
2. 新 Package 若仍重用舊 worker worktree，Start Gate 會拒絕（實際訊息為 `guard 'start_ready' rejected event 'start-gate-passed'`）；它不會自動承接或替換 worker lease。
3. 若改用 `FS-A-V2/FS-B-V2`、以 `lineage=[舊 ID]` 記關係，並分配新 branch/worktree，則新 run 能 approve/start，Project Graph 同時保留舊、新節點。已整合的 A 會自然存在於新 baseline，可在新 worktree 看見；舊未提交 B worktree 也仍保留。
4. 不過新 run 的 tasks 全是 `pending`、evidence ledger 為空。舊 Agent Result 被拒：`agent result run_id does not match package`；舊 check evidence 被拒：`evidence path is outside this run for C-1`。沒有「依影響分析選擇性沿用證據」機制。

第 3 項是目前最接近需求的手動 workaround，但清 `active_run_id` 本身沒有 event、授權記錄或原子交易；中途失敗可能留下 graph/package/event 不一致，不能稱為完整合法承接流程。

## accepted 終態的精確邊界

原 accepted run 確實不能 `resume`（只允許 blocked run），也不能再 block（`terminal state 'accepted' cannot transition`）。但這**不代表產品永遠不可再改**：另開 change run 是可行方向。

實測 accepted Project Graph 中舊 Slice disposition 已為 `accepted`，新 run 直接重用舊 Slice ID 會被拒：`Slice id is already finalized: FS-A`。改用新 Slice ID、lineage、新 branch/worktree 後，新 change run 能 approve/start，舊 accepted history 保留；新 run 仍不會繼承 task/evidence。這證明缺的是正式 change lineage/handoff，而不是完全沒有後續改動能力。

另觀察到：正式化新 Project Graph 後，Start Gate 要求 delivery checkout 狀態符合控制檔規則；在本探測中把 formalized graph stage 後即可通過。這只是 fixture 中控制檔發布時點的操作細節，不影響上述 replan 結論。

## 對題述主張的修正

- 「已核准 Package 不可修改」：成立，後繼方案必須是新的 frozen Package。
- 「resume 只能回阻塞前狀態」：成立；實測沒有退回 requirement/boundary/package 的 Gate。
- 「舊契約結束、新契約承接缺流程」：成立，而且 cancel 後 active graph/lease 不清楚地證實缺口。
- 「accepted 不能重新開啟」：成立；但可另開 change run，前提是使用新的 Slice ID；中途取消的案例還需人工處理控制圖。這不是同一 run 重開。
- 「可避免不必要丟棄工作」：檔案/commit 可由 Git baseline 或保留 worktree 人工帶入；task 狀態、review/evidence 沒有正式且選擇性的 reuse。

原始逐步輸出在 `successor.log`，結構化結果在 `successor-results.json`，可重跑腳本為 `successor_probe.py`。
