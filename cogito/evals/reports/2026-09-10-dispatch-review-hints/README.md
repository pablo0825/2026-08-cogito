# 派工上下文與 Reviewer 草稿

日期：2026-09-10。版本：4.5.0。Repository 維護，未建立 Cogito Run。

## 修改與相容性

- 正常執行的 `next.dispatch_tasks` 提供可派 Task 的責任、paths、check IDs、Spec／Plan／理解摘要引用、預定 branch/worktree 與既有 lease 命令。實際 Agent ID 保留 placeholder，仍須 lease → executor 登錄 → running；提示不宣稱 checkout 已準備好。
- 一般審查的 `next.review_tasks` 提供本輪尚未完成審查的 Task 上下文與既有 `agent-result` input 草稿。只填 schema/run/task/role、被審查者與 commit 引用；身分、結論、changed paths、evidence、風險和 requested transition 留給實際 Reviewer。
- 按目前 verification cycle 與既有 review decision 排除已完成審查；needs-fix 仍優先既有 correction 提示。已存在的 retention 操作保留。
- check recovery 未解決時不附派工命令。Maintenance HEAD 讀取失敗回逐 Task blocker。歷史 Task 缺少的描述不代填，缺實作／lease 不猜引用。
- 僅新增查詢輸出與文件，CLI 命令、輸入契約、事件與 hash 格式不變；原提交操作繼續驗證身分、版本及內容。新增可向後相容的提示能力，依版本規則升 MINOR。未新增 Gate、工作流、自動派工或自動審查批准。
- 本次範圍是正常派工與一般獨立審查；未擴充 human correction、RP 或結案草稿。

## 自動驗證

共 **38 個不同測試通過**：

- `test_dispatch_review_hints.py`：8 個。涵蓋真實隔離 Git／CLI lease、Reviewer 草稿登記、完整審查轉移、不完整輸入／自審／內容漂移拒絕、查詢不改寫事件或 Package；另以合成 state／故障注入檢查歷史 Task、舊 cycle、缺紀錄、Maintenance HEAD 與 recovery 優先。
- `test_next_operations.py`、`test_run_queries.py`、`test_atomic_task_verification.py`、`test_review_retention_flow.py`：合計 30 個，確認既有提示、恢復、驗證、審查與 retention 路徑。
- mypy 1.20.2：設定範圍 27 source files 通過。沿用暫存開發工具，未增加專案依賴。
- `git diff --check` 通過。

初次新測試因 import 順序失敗，已修正；受控檢查在 sandbox 內無法執行 `ps`，改於允許讀取測試程序身分的環境執行並通過。沒有將環境失敗算成測試通過。

## 獨立評估

獨立唯讀審查找出 recovery 與派工提示並存、Maintenance HEAD 查詢失敗使整份提示消失兩項問題；主代理修正並加入測試後，focused recheck 未發現剩餘必修問題。

Focused reading simulation 涵蓋 lease／executor／running 順序、真實審查後填草稿、needs-fix 路由、過時草稿與全部審查完成後沿用 `review-approved`。此為合成閱讀決策，不等同真實產品 Agent 操作或使用者驗收。

未跑完整 regression、CI、skill 格式 validator 或完整產品 Agent 使用情境；未量測 token 或耗時改善。未 commit 或 push。
