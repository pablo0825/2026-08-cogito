# Next 操作銜接修正

日期：2026-09-10。版本：4.6.1。一般 repository 維護，沒有建立 Cogito run。

## 修改範圍

1. 已 lease 的 Task 提供 executor 登錄選項，登錄後提供既有 running 命令；不猜 handle／PID，不將終止或身分不明的 executor 視為可工作。沒有其他可派工作時使用 `start-leased-workers`；registry 無法確認時使用 `resolve-executor-registration`。
2. 必要 evidence 齊全時使用 `submit-verification`／`submit-post-verification`，與既有 verify／post-verify 命令一致；缺少或過期證據仍保留檢查提示。
3. 當本輪所有獨立審查符合既有 review decision 時，使用 `complete-review` 提供 review-approved transition。實際 transition 仍核對當前內容，不把提示当成核准。
4. check recovery 優先，使用 `resolve-check-recovery`。恢復讀取錯誤、查詢範圍超限時清除正常推進操作；可重建原請求時只保留恢復命令。非阻塞 not_started 請求仍為 optional。

CLI 操作、輸入契約、workflow 狀態、事件與核准規則未變。`next_action` 在上述情況改為精確動作名称；`SKILL.md` 同步新增六個路由，Execution Policy 說明操作順序、真實輸入及阻擋處理。核對 Runtime Interface 的重送與停止規則、agents/openai.yaml 的啟動政策，無需另改或重複解釋。

本批未擴充 DP follow-up 與人工修正提示，也未修改 RP 草稿。開始時工作目錄乾淨，基礎版本為 4.6.0。

## 自動檢查

- `test_next_handoffs.py`：5 項，包含實際隔離 Git／CLI lease → 外部 executor 測試登錄 → running；合成恢復讀取失敗、超限、已發布證據、executor 停止與身分異常情境。
- `test_dispatch_review_hints.py`：8 項，全部審查登記後直接執行提示中的 transition，其餘固定引用、身分與內容漂移檢查保留。
- `test_next_operations.py`：12 項，涵蓋提交前證據、本波／整合後驗證、失敗／過期證據、恢复、整合與結案既有操作。
- `test_run_queries.py`：5 項，保留既有基礎查詢與 receipt 行為。
- 共 **30 個不同測試通過**。需要程序查詢的既有受控測試在允許 ps 的環境執行；其餘新增測試在 sandbox 內通過。
- mypy 1.20.2：設定範圍 27 source files 通過。
- `git diff --check` 通過；檢查 47 個本地文件連結與六個新 next_action 的 skill／procedure 路由。

## 文件與限制

自行進行 focused reading walkthrough：lease 尚未登錄身分、登錄完成、證據齊全、證據過期、審查全數完成與未知檢查結果，均能从 skill 路由找到相應程序及下一步。這是主代理閱讀檢查，不是獨立 Agent 評估或完整產品驗收；本側對話依使用者限制未使用子代理。

已嘗試 skill-creator 的 quick_validate.py，但環境缺少 PyYAML，格式檢查器未能執行。手動確認原 frontmatter 未變，連結／路由檢查不宣稱取代該 validator。

未執行完整 regression、CI 或 token 效益量測。未 commit、push 或安裝工具至其他專案。
