# 獨立重新規劃流程：實作與驗收

採用使用者選定的方案二。來源基線 `9bd1342`，完成版本 `7a6b2b0`。

## 已提交

| Commit | 內容 | 驗收 |
|---|---|---|
| `804ddfc` | 獨立 RP 狀態機、專案鎖與 source/successor 執行限制 | 38 項相關測試通過 |
| `0fc3f58` | executor 停止、快照、提案與獨立覆核、精確核准、承接與採認、Graph 切換、取消與中斷恢復、CLI | 相關測試與端到端通過；全套 421 項通過，另補一項取消前停止條件負向測試通過 |
| `c7b4a29` | 核准前預演所有承接內容、綁定預期 tree，防止固定衝突直到交接才被發現 | 最新 12 項相關測試全部通過，含 CLI 至 accepted、accepted 來源、證據採認至 accepted |
| `7a6b2b0` | 操作協定、CLI、核准與限制說明 | 文件連結與 diff whitespace 檢查通過 |

測試集合有重疊，不將以上次數相加。全套日誌見 `full-regression.log`（421 tests / 95.432 秒 / OK）；其後追加的停止條件測試及承接預演修改，另以上述針對性測試驗收。mypy 未安裝，本輪未宣稱靜態型別檢查通過。

## 已實證的路徑

- 原 reviewing run 經真實 CLI begin/stop/propose/review/approve/handoff，新 run 修改後重新驗證、審查、整合並 accepted。
- 原 accepted run 再建立 successor，完成新 accepted；原 events bytes、completion report 與 accepted Slice 記錄保留。
- 原已審查工作的證據有條件採認，原 evidence bytes 不變，新 run 不偽造測試結果；採認後仍跑新的整合驗證並 accepted。
- 真 controlled check 在停止要求後完成，artifact 保留，舊 ledger 不新增可用 evidence；程序未退出前 stop 不能保存正式現場。
- 真 Worker 保存未提交內容並退出後，才允許進入影響分析。
- 核准不提前移交 Graph；交接期間不能普通 resume/start 繞過。
- 作者不能自行獨立覆核；提案修訂使前版覆核失效；來源內容漂移拒絕核准。
- Graph 寫入後、source 關閉後及取消副作用中斷，重送可對帳完成，執行限制不提前解除。
- 拒絕新方案保持暫停；明確恢復會保存 executor generation；取消需先停妥，並釋放 Graph。

## 第一版限制

- 主要驗收對象是具專用 Slice worktree 的 Feature/Change/Correction successor；Mini Package 若 delivery 尚有未提交修改，不略過乾淨 checkout 規則，也不自動清理使用者內容。
- 證據沿用保守要求完整內容與相關驗證契約相同；有 amendments、相依 task、相關全域條件改變或同 worktree 混入新工作時要求重驗。程式仍可保留、承接。
- 外部 Agent 由 Coordinator 使用實際 executor 工具停止，receipt 是 executor 聲明，CLI 不提供 provider 身分認證；PID 檢查需系統 inspection 權限。未知身分／結果不放行交接。
- 未窮舉所有平台與故障交錯。處於不一致或未知結果時保留現場並要求對帳，不猜測恢復。

本輪各子代理均在 8 分鐘內完成，同時最多兩位子代理協助。程式與操作文件均已 commit；報告維持本機產物，未混入原本未追蹤的其他驗收報告。

操作規格：[replanning.md](/Users/pablo/Documents/project/2026-08-cogito/cogito/references/replanning.md)
