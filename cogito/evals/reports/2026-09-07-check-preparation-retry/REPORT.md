# 執行前 snapshot retry 修正驗證

版本：3.6.1。

## 修改與相容性

只對 Atomic running Task 新產生的執行前 snapshot 失敗追加受保護的 `check-preparation-failed`。既有 transient retry 可綁定來源與替代 action；同 Task lease、worktree、check 與有效契約的替代成功 evidence，才能讓來源 marker 不再阻擋。原始紀錄保留；既有 reason-only retry 與未知 marker 的行為不變。

替代檢查實際失敗時，下一次綁定必須確認失敗 evidence 與 executor 終止，仍受兩次 transient retry 額度限制。執行期間 lease／contract 漂移不能登錄替代 evidence。沒有新增工作流狀態或核准程序。

## 自動化測試

- `test_check_retry`：23 tests，11.162 秒，通過。使用暫存 Git repository 與受控 runner，注入 snapshot／中斷等故障；包括實際 CLI 的 retry → run-check → task-finish → 下一 Task lease。
- 相關既有測試：81 tests，71.286 秒，通過。範圍為 `test_task_finish`、`test_result_metadata`、`test_runner_contract`、`test_runner_evidence`、`test_runner_termination`、`test_gate_cli_contract`、`test_review_retention_rules`、`test_review_retention_flow`、`test_review_retention_adversarial`。
- configured mypy 1.20.2：24 files 通過；使用暫存 uv tool 環境（系統 python3 未安裝 mypy）。命令：
  `UV_TOOL_DIR=/private/tmp/cogito-uv-tools uv --offline --cache-dir /private/tmp/cogito-uv-cache tool run --from mypy==1.20.2 mypy --config-file cogito/mypy.ini`。這不代表所有 helper 都有完整靜態型別註記。
- CLI retry help 與文件參數核對通過。

未跑全套 regression，也未宣稱 CI 通過。

## 獨立審查與文件模擬

子代理完成靜態審查；主代理核對並修正 replacement markers／run 綁定、執行後再次驗證及失敗 replacement 再試路徑。複審無阻塞發現。

文件 focused reading simulation 覆蓋正式 retry、historical unknown、post-snapshot failure、failed replacement、retry chain 與其他 checks 失敗，通過。此項為合成操作判斷，不是正式使用者驗收。未執行 skill 格式驗證（未修改 SKILL.md 或 metadata 結構）。

## 後端事件限制

未修改後端專案或其 runtime。DEV-002 舊 V-001 只有無法區分前後 snapshot 的錯誤，不能補造新的執行前證明；本修正不自動解鎖它。V-003 最新 evidence 仍失敗，需後端另外修正與重新驗證。
