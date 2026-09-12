# Result 草稿與結案提示連動

日期：2026-09-12。交付版本：4.7.0。Repository 維護，未建立產品 Cogito Run。

## 連動評估與實作

新增 `result-draft --run-id <ID> --event-hash <hash>`，從同一份事件快照組合 Result 與 Project Graph 草稿。只在 `finalizing` 使用，經既有 mutation fence 保護，命令不接受 action ID、不追加事件。每次建立新的 runtime 草稿目錄，不覆蓋既有檔案或直接修改正式資料。

本次先確認並一起處理以下連動：

| 位置 | 處理 |
| --- | --- |
| Result 事實欄位 | 保存凍結 Package／effective hash、整合 commits、最後驗證 evidence、Reviewer、amendments、human outcome 與 delivery summary |
| 修正與歷史變體 | 保留 commit、working-tree snapshot、path proposal hash 三種 amendment；Reviewer 包含 adoption 與 retention；人工修正採用最新結案證據集合 |
| Project Graph | 複製目前 Graph，只關閉本 run 的 Slice；原驗證器拒絕其他 active run、無關歷史或 dependencies 漂移 |
| 人工判斷 | 輸出的 Result 刻意不含 remaining_risks，必須由 Agent 評估後加入；status accepted 僅為預定 Result 格式，不是 Gate verdict |
| 既有驗證權威 | 草稿事實使用原 Result／Graph／finalization records 與 evidence snapshot validators 核對；不修改契約或原 finalize 規則。缺風險的草稿本身不能 finalize |
| 正式檔案與提交 | 回傳 draft 路徑、canonical destinations、待填欄位、kind-specific commit scope、Maintenance trailers 及既有 finalize 命令；不自動 stage／commit／覆寫正式檔案 |
| 已提交與恢復 | next 發現 HEAD 已有合法結案紀錄時，沿用原完整 finalization validator 核對後提供該 commit 的 finalize 命令，不要求重複 commit。既有結案檔案不符時回 blocker |
| accepted 清理 | 保持原 accepted hints、原 action／request fingerprint 重送及 cleanup 行為，不重新產生草稿 |
| 文件／CLI | 更新 finalization 順序與草稿操作，釐清 runtime action ID 規則，避免 Agent 對無事件的草稿命令加上不存在的參數 |

新增向後相容 CLI 功能，版本升 MINOR 至 4.7.0。沒有新增事件、核准、Result schema 或 workflow state。既有手動 Result 與 delivery-summary 操作保留。

草稿驗證不代表將來的 final commit 會通過；Git 提交內容、範圍、證據與歷史仍由 finalize 再核對。寫第二個草稿失敗不回成功，保留部分檔案，修復後另建草稿。流程不判定風險文字是否充分，也不量測模型成本。

## 自動驗證

共 **61 個不同測試通過**：

| 測試檔 | 數量 | 重點 |
| --- | ---: | --- |
| test_result_draft.py | 8 | 真 CLI draft→canonical→commit→finalize→accepted／cleanup replay；Feature 與 Maintenance 人工修正；真實 review retention；三類 amendments 與 adoption Reviewer 純資料；staging／事件／正式檔案保護；風險缺漏、錯階段、hash、內容／evidence 漂移、symlink、部分寫檔拒絕與恢復 |
| test_finalization_rules.py | 12 | 原紀錄與 Graph／approval 驗證 |
| test_finalization_content.py | 11 | 原提交、驗證內容與範圍 |
| test_delivery_summary.py | 11 | 準備／執行／驗收摘要與歷史相容性 |
| test_cleanup_finalization.py | 7 | accepted 清理、原 action 重送與保留 |
| test_next_operations.py | 12 | 既有提示、驗證、整合與恢復 |

新測試最初直接寫不可變 evidence 以注入破壞，遭測試檔案權限阻擋；已限於隔離 fixture 調整測試檔 mode 後再注入，最終通過。不改產品 evidence 保護。

mypy 1.20.2：設定範圍 27 source files 通過。文件相對連結與 git diff --check 通過。Git／程序測試使用隔離暫存 repositories，在允許 ps 查詢測試程序的環境執行。

## 獨立評估與限制

獨立唯讀盤查先列出 amendment、human、Reviewer／Graph、canonical commit 與恢復五組連動，再審查實作及文件。指出 action ID 通則與草稿命令不一致，修正後 focused recheck 未發現剩餘必修問題。

Focused reading simulation 涵蓋 Feature、Maintenance、HEAD 已有合法結案檔案、HEAD 紀錄失效、accepted 清理；為合成 Agent 決策，不等同產品使用者驗收。真 Git／CLI 結案結果由上述自動測試支持。

未執行完整 regression、CI、skill 格式 validator 或真實產品 Agent 效率測量；沒有宣稱節省多少 token。尚未 commit 或 push。
