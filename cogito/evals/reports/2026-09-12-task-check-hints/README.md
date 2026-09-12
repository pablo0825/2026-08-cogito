# Task 缺少檢查的命令提示

本次新增 running Atomic Task 的 `run-check` 提示，版本為 4.8.0。沿用既有 evidence 選取及命令組裝；不增加命令、狀態、契約或測試範圍，也不修改完成 Task 的驗證規則。

## 修改與連動範圍

- 原本 `next` 只回傳 Task 缺少 check 的 blocker；現在附上 check ID、Task ID、worktree 與可執行 argv，只需填新的 action ID。
- Agent 等實作準備好才執行，執行後重查。缺少的紀錄補齊後，其他失敗、過期或提交條件仍須通過，提示不代表已完成驗收。
- 同 check ID 在另一個 checkout 的紀錄不算本 Task 的證據。已有紀錄的 check 不被列為缺少，也不回溯選取較舊的成功紀錄。
- 有效 evidence 但尚未 commit，仍提示提交。讀取失敗或資料竄改保留 blocker，不轉成新測試命令。
- `resolve-check-recovery` 覆蓋一般操作，保留原恢復命令；`not_started` 仍為可選的原 action 重送，與新 action 擇一後重查。
- 沿用 executing、review-fix、correcting 的 Atomic Task 提示入口；不擴大到 post-integration-correction 或 human-correction。操作文件同步說明執行時機與恢復優先條件。

## 自動驗證

以下 41 項測試通過。範圍涵蓋 Task 提示、完成與恢復、審查修正，以及既有 next／派工提示的相依行為；未跑全套回歸或 CI。

| 測試檔 | 通過數 |
| --- | ---: |
| test_task_check_hints.py | 5 |
| test_task_finish.py | 10 |
| test_review_fix_start.py | 6 |
| test_next_operations.py | 12 |
| test_dispatch_review_hints.py | 8 |

逐檔執行方式：`PYTHONPATH=cogito/scripts python3 -m unittest discover -s cogito/tests -p '<測試檔名>' -v`。

新測試在隔離 Git fixture 實際執行產出的 argv，驗證「缺 check → 執行 → 未 commit blocker → commit → task-finish」；另確認查詢不變更事件、index、Git objects，及不同 checkout、失敗／過期／竄改證據的處理。恢復優先案例使用 fault injection，搭配既有 next 恢復測試；review-fix 實際閉環確認新增 C-fix 取得命令、已有 C-b 不被列為缺少。

首次測試執行發現新 fixture 遺漏必要 integration check，已修正。另有兩個既有測試檔獨立啟動時缺少 scripts 匯入路徑，補上 `PYTHONPATH` 後通過；這些初次失敗不列為成功結果。

mypy 1.20.2：27 個設定範圍內的檔案通過；`git diff --check` 通過。

## 獨立審查與閱讀模擬

獨立 agent 完成程式審查與五項合成閱讀情境：缺 check、有效 evidence 未 commit、failed/stale、強制恢復、not_started 可選重送，無剩餘必修項。依其回饋將恢復優先條件明確寫為 `resolve-check-recovery`，避免誤讀成所有舊請求都必須重送。

此為合成閱讀判斷，不是使用者驗收；獨立 agent 未另跑測試。未執行 skill 格式驗證，也未量測 token 或宣稱成本下降。
