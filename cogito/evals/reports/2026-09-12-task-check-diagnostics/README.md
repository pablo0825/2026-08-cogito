# Task 檢查證據的查錯提示

版本：4.9.0。僅擴充 running Atomic Task 的 `next` 操作提示，不修改共用 validator、Task 完成條件、事件、契約或恢復規則。

## 行為與連動

- 完整候選證據格式可讀但 Task 驗證拒絕時，在原 `task-finish` operation 增加 `check_evidence`，包含 check ID、證據路徑、記錄結果與閱讀提示；保留原 blocker。
- `recorded_status=failed` 指該次執行失敗，提示閱讀 evidence 的 stdout/stderr 與執行旗標；不推斷是程式錯誤、逾時或環境問題。`passed` 只描述歷史執行，不能當成本輪有效性的判定。多筆證據不會全部被標成失敗。
- 既有驗證、atomic commit 與乾淨目錄檢查通過後，若 content tree 不符，只為不符的紀錄附上內容不同、準備好後重新驗證的提示。
- 缺 check 仍沿用 4.8.0 命令提示；未提交或目錄不乾淨不分類為證據過期。selector 損壞／讀取失敗保留原 blocker，不猜測結果。
- 所有新增資訊位於既有 operation 內；恢復流程覆蓋 operations 時一併清除。沿用 executing、review-fix、correcting 的既有 Atomic Task 入口，未擴張其他階段。
- 不複製完整輸出、不新增修復或重跑命令，也不改變診斷之外的流程。操作文件同步說明歷史結果與當前有效性的差別。

## 自動驗證

36 項相關測試通過：

| 測試檔 | 通過數 |
| --- | ---: |
| test_task_check_hints.py | 8 |
| test_task_finish.py | 10 |
| test_review_fix_start.py | 6 |
| test_next_operations.py | 12 |

逐檔執行：`PYTHONPATH=cogito/scripts python3 -m unittest discover -s cogito/tests -p '<測試檔名>' -v`。

新增真實隔離 Git fixture 檢查失敗證據路徑、混合成功／失敗紀錄、內容不匹配與 task-finish 拒絕；補上未提交、dirty checkout、最新失敗、損壞紀錄不誤判的斷言。查錯查詢維持事件、index 與 Git objects 不變。恢復覆蓋使用 fault injection，並跑既有 next 恢復回歸。

mypy 1.20.2：設定範圍內 27 個檔案通過。`git diff --check` 通過。未跑全套回歸、CI 或 skill 格式驗證，未量測 token 成本。

## 獨立審查與合成閱讀

獨立 agent 唯讀審查程式與文件，未發現阻擋缺陷。六項合成閱讀情境涵蓋失敗先讀證據、passed 不代表當前有效、內容不符再驗證、未提交、dirty checkout、恢復 action。依審查建議修正文案，避免暗示 commit 檢查先於 evidence 驗證。

獨立 agent 未另跑自動測試；以上閱讀模擬不是實際產品 Run 或使用者驗收。
