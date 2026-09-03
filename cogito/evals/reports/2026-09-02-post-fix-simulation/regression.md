# 回歸測試紀錄

- 執行開始：2026-09-02 14:55:49 UTC。
- 工作目錄：`/Users/pablo/Documents/project/2026-08-cogito`。
- 程式版本：`df2ee65` (`main`)。
- 環境：macOS Darwin 25.5.0 arm64；Python 3.12.10。
- 命令：`python3 -m unittest discover -s cogito/tests -v`。
- 結果：**320 tests，31.581 秒，OK，exit code 0**。
- 無測試失敗或錯誤；無 unittest 的 skip/expected-failure/unexpected-success 結果。log 中的 `skipped_nodes` 是測試名稱，結果為 ok。
- 執行前後 Git 狀態一致：`main...origin/main [ahead 46]`，既有未追蹤 `cogito/evals/reports/`；本軌未修改 source，未 commit。

## 可驗證證據

- `unittest.log`：全部 320 項測試名稱與結果。
- `unittest.exitcode`：程序結束碼。
- `environment.txt`：起始時間、作業系統、Python 與工作目錄。
- `git-log.txt`：執行時最近八筆 commit。
- `git-status-before.txt` / `git-status-after.txt`：前後狀態。

## 驗收邊界

這個結果只證明現有 Python 回歸測試在上述環境及版本全部通過。沒有執行 `cogito/evals/evals.json` 中的 14 個 Agent 行為評測情境，不可將其計入通過數，也不代表真人核准互動或所有未覆蓋流程皆無問題。獨立的全流程模擬與修復重測由其他軌提供。

## Handoff

本軌已完成，不需要下一位代理接手。沒有待分析的失敗。若主代理需要交付可持久化報告，可引用本檔及完整 log；不要把 `/tmp` 視為永久儲存。
