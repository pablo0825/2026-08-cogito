# 文件交接與 Git 錯誤訊息修正

日期：2026-09-10。交付版本：4.4.5。Repository 維護，未建立 Cogito Run。

## 修改範圍

- 共用 `package_document_refs` 列出 Spec、Plan、具路徑的理解摘要，來源參照由呼叫端明確選入。候選快照、來源保護、Start artifact 及交接使用同一文件列舉；保留原參照順序、hash-only 摘要及原始輸入。
- RP 允許新路徑的 successor 理解摘要通過提案及交接；不允許把原產品、來源參照或停止快照中已存在的檔案重新宣告成新控制文件來修改。原文件 hash 與產品漂移檢查保留。提案在覆核／核准前檢查範圍，核准再核對候選內容，未新增 Gate 或狀態。
- Git adapter 保留失敗的 stderr。Atomic integration 只有在 `merge-tree` 回傳 code 1 且包含結果 tree 時提示真正衝突；權限、逾時、不支援命令等錯誤保留原因，說明檢查未完成，不誤導成修改程式衝突。
- 更新一個既有測試的錯誤文字預期：4.4.4 已將 frozen source 拒絕文字分開，本次不改該來源授權規則。

不新增通用文件管理、錯誤分類框架、自動修復、依賴更新捷徑或整合後審查流程。

## 實際驗證

從 repository root 以 unittest discover 執行下列相關測試；彙整腳本使用相同 discover API。程序／Git 流程測試在允許 `ps` 讀取測試程序身分的環境執行。最終 **84 個不同測試通過**，不重複計算修正後重跑。

| Pattern | 測試數 | 最終結果 |
| --- | ---: | --- |
| `test_replan_store.py` | 13 | 通過 |
| `test_replan_runtime_sources.py` | 13 | 通過 |
| `test_replan_runtime_snapshot.py` | 14 | 通過 |
| `test_start_artifact.py` | 6 | 通過 |
| `test_planning_integrity.py` | 9 | 通過 |
| `test_planning_rounds.py` | 8 | 通過 |
| `test_replan_handoff_tool_repair.py` | 4 | 通過 |
| `test_atomic_task_verification.py` | 10 | 通過 |
| `test_git_error_reporting.py` | 4 | 通過 |
| `test_git_test_support.py` | 3 | 通過 |

重點涵蓋新摘要準備→覆核→核准→handoff→相同 action 重送、immutable Start artifact 保存摘要、原 Package／Worker 歷史不變、文件漂移拒絕、產品冒充摘要拒絕、交接恢復及正常整合。Git 真衝突使用真實 repository；權限、逾時與命令失敗使用 subprocess 邊界故障注入。

mypy 1.20.2：`python3 -m mypy --config-file cogito/mypy.ini`，27 source files 通過；工具位於暫存目錄，未加入專案依賴。文件相對連結與 `git diff --check` 通過。

## 獨立檢查與限制

- 獨立程式審查發現產品路徑冒充新摘要的邊界問題；修正後以真實 fixture 確認拒絕，未再發現必修問題。
- 獨立 focused reading simulation 涵蓋新摘要、沿用既有理解、凍結文件、核准後漂移；未發現文件歧義。此為合成情境中的閱讀決策，不代表真實產品 agent 執行或使用者驗收。
- 未執行無關的全量 regression、CI、skill 格式 validator 或 token 效益量測。沒有宣稱節省模型 token。
- CLI JSON 結構、事件與 artifact 格式不變，Git 錯誤文字會更具體。新增文件例外收窄為真正新文件；停止快照內既存非控制檔案即使被新提案引用，也不因此取得修改權。
