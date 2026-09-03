# Cogito 三項流程修正與驗收

依使用者要求逐項修正、驗收並提交；第二項提交前另補一個第一項的 index 保護修正。沒有 push，既有模擬報告未改寫。測試使用隔離的暫存 Git repositories，CLI 核准與角色皆為合成測試資料。

## 1. Maintenance 多任務

主修正 `f6e502c`，index 保護補充修正 `3b3fbe2`。

新 task lease 由 Gate 保存 working tree 與 index 起始快照，Result 只核對該 task 的增量；累積交付另驗 Package 範圍。因此 T-1 留下的修改不再被錯歸給 T-2，但 T-2 偷改 T-1 的檔案（包括還原至 HEAD、stage 後恢復工作檔案）仍被拒絕。

任務中斷後換人接手，保留該 task 原始起點，不吞掉半成品；新 lease 不能把任務間未認領的修改當成合法既有內容。Maintenance 獨立審查使用該 task 的完成快照，並核對目前已驗證內容。舊 lease 完全沒有快照時保留原本保守的累積範圍驗證，不倒填歷史；不完整或遺失的快照拒絕操作。

完整回歸初次 370 項通過，最後續接／scope 精準驗收 53 項通過。後續第二項回歸重現 Git diff 更新 real index stat cache 的偶發問題，精確追蹤後改為在 private index 執行 live diff。未採用停用 refresh 的方案，因其會改變 name-only 判讀。補充修正的 15 項驗收通過，原失敗情境重跑 30 次全部通過，真 index bytes 保持不變。

永久測試：`test_maintenance_multitask.py`、`test_snapshot_index_timestamp.py`。兩任務各自負責不同路徑，包含 review exemption 與兩任務獨立 review 的真正 CLI 結案，均只產生一個 final commit。

## 2. 同一 Feature Slice 的多任務審查

修正 `514f8ac`。

Reviewer 使用該 task 已登錄 Implementer Result 的 base/head 範圍；該 head 必須仍為目前 Slice HEAD 的祖先。另比對目前 HEAD、內容、有效契約與本輪正式 runner evidence，不能把其他 task 的範圍混入，也不能用未驗證的新 commit 或 dirty files 通過。

每次重新驗證後都需要本輪 review，上一輪核准不能沿用。審查 closure 會再次核對 worktree，避免先審查、再偷偷改內容。只有 optional checks 時仍可使用真實 runner evidence，但未登錄、過期或竄改的 optional evidence 不能充當驗證依據。

真正 CLI 的同 Slice／同 Worker 兩 task 全流程達到 accepted；review-fix 新增 task 後，原任務與新任務各自重審可繼續。獨立 probe 亦驗證 technical correction 與 optional-only 情境。

全套回歸 **379 項通過（72.270 秒）**；mypy **1.20.2、18 個檔案通過**。新增的證據竄改測試初稿被 read-only fixture 權限阻擋，明確調整該暫存 fixture 的權限後重新注入與驗收；這個初稿錯誤不列為產品缺陷。永久回歸：`test_feature_multitask.py`。

## 3. 核准前錯型資料

修正 `9bd1342`。

Package 與新摘要／Boundary 事件共用同一套驗證：摘要 hash 為 64 位小寫十六進位；Boundary decision 為合法列舉，evidence 為非空字串陣列。驗證不改寫、轉型或刪除 extension。

在 `transition` 與直接 `record` 寫入前皆執行檢查；錯誤輸入不消耗 action ID、不追加事件、不刷新快取。修正輸入後可用原 action ID 正常發布，再完成 prepare、模擬 approve 與 Start Gate。陣列／物件 decision 也會結構化拒絕，不再觸發 unhashable traceback。

不把更嚴格的規則倒套歷史 projection；舊錯誤摘要仍可讀取、停止或取消。若仍未確認，可重新發布合法摘要；新 confirmation 會驗證已存 hash，避免再次凍結壞資料。舊版已完成的錯誤 Boundary 不自動改寫，仍需既有停止／取消與重建決策。

專門驗收 **7 項通過（4.187 秒）**，涵蓋 events/state/index 逐 byte 不變、直接 API 不可繞過、合法中文與 extension 保留、旧壞 hashchain 可讀且修訂後可繼續。永久回歸：`test_preparation_inputs.py`。最終全套 **386 項通過（78.340 秒）**，mypy 1.20.2 的 18 個檔案通過；詳見 `summary.json`。

## 子代理與執行限制

第一項兩位子代理約 6–7 分鐘完成。第二項原兩位子代理未及時換手，超過 10 分鐘後已依使用者提醒中止；資料保存在 workspace 與交接訊息，再交給兩位新代理完成，接手段約 2–3 分鐘。第三項兩位子代理約 3 分鐘完成。沒有隱瞞原第二項工作段超時，也沒有讓原代理繼續執行。

本輪驗收包含 Python、真 CLI、Git／runner／Gate 與靜態型別檢查；不宣稱 14 個自然語言 Agent 行為評測全部通過。未部署、未 push。完整最後狀態、commit IDs、測試數見 `summary.json`，相關輸出保存於本目錄。
