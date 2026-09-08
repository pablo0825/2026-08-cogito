# 同輪相關問題集中修正

本增量接續已提交的 `4.3.0` 審查補列交付，經相關驗證後以向後相容功能擴充升至 `4.4.0`。原驗證報告保留其歷史結果。

## 修改

- 操作政策預設每輪、每個受影響 Slice 使用一個修正 Task，引用既有 Reviewer findings；不新增清單 schema 或流程單。此為 Agent 執行政策，不是 Gate 強制每輪只能有一個 Task。
- `next` 提示沿用未完成的修正 Task、branch/worktree，以及相關選測；不因每個 finding 自動新增 Task 或複製全部 integration checks。
- `review-fix` 中的 `amend-paths` 可補列本輪已新增且未完成的 Task。由權威事件前綴確認 Task 所屬輪次，原 Task ID、lease base、狀態與已授權未完成修改保留。必要 evidence 綁定新有效契約，不能採用舊失敗或失效結果。
- 原 Package、已完成 Task／Result 與歷史 events/evidence 不改寫；修正完成仍引用建立 Task 的 Amendment，後續路徑補正保留其 scope review。
- 未擴充相容依賴更新或整合後補列入口，未放寬 API／資料／安全契約，未新增跨 run evidence 採用。

## 實際驗證

`PYTHONPATH=cogito/tests:cogito/scripts python3 -m unittest test_batched_review_correction test_path_amendment_flow test_review_path_amendment test_review_fix_start test_path_amendment_contract test_contract_materialization test_correction_rules test_run_queries test_atomic_task_verification -q`

66 tests 通過。選測涵蓋本次路徑投影、現有修正、Task evidence、CLI、路由、恢復及相容性；未執行全套 regression，未執行或宣稱 CI 通過。

新增 Git 流程案例：兩筆 Reviewer findings 共用一個修正 Task；相關測試先失敗，保留失敗 evidence；停止 Worker 後補列格式 helper 與相關 check，scope review 事件落盤而 executor 封存失敗，再以原 action 重送成功。Task／base／branch 不變，沒有額外 Task 或 RP。舊 evidence 無法完成修正，取得新契約的兩項相關 checks 後，同一 Task 完成、verification 與本輪正常複審通過，進入 integrating。階段切換未增加測試次數。

純規則案例拒絕前一輪 Task、已完成 Task 與已有完成 Implementer Result，並確認輸入資料不被修改。

mypy 1.20.2 使用既有離線環境檢查 `cogito/mypy.ini` 指定的 27 source files，通過。系統 Python 的 mypy 不可用；沒有安裝新依賴。`git diff --check` 通過。

## 文件核對與限制

本側對話禁止子 Agent，因此本增量沒有獨立審查或獨立閱讀模擬；不沿用原報告的獨立審查來宣稱此增量已被覆核。主 Agent 直接核對以下閱讀情境：同 Slice 多問題彙整；原 paths 內持續修正；中途補檔先停程序再授權；已完成 Task 留待下一輪；越過產品邊界仍需 RP。這是靜態文件核對，與實際 Git 測試及使用者驗收分開。

本增量未修改 SKILL frontmatter，未重跑 Skill 格式驗證。後端專案及其已完成 run 未修改；本報告不代表已推送或更新後端使用的技能。
