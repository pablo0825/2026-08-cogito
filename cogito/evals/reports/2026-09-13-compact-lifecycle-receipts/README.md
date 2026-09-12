# Executor、RP／DP 與結案回傳精簡

交付版本 5.0.0。實作使用者核准的①②④；不修改修正／Human 階段上下文。以 4.10.0 為基礎，保留準備階段提示、candidate 匯出與 checkpoint recovery。

## 範圍與相容性

| 入口 | 新回傳與保留條件 |
| --- | --- |
| register-executor／executor-receipt | 只回本次 executor 身分、觀察與停止憑據索引；全局 stop_request、stop_requested、quiescent 仍由全體 registry 觀察計算，不能由單一 executor 推論全部已停止。 |
| executor-status | 新增唯讀完整查詢，保留所有 entries 與 raw_response，不建立 registry lock，也不提供恢復授權。收據提供可直接使用的 registry_query argv。 |
| RP mutation | CLI 回流程 ID、來源／承接 ID、state、sequence/hash、proposal hash/stale、工具接軌及 handoff tool 綁定、next_action。完整 Package、snapshot、transfer plans 等留在 Store／status。 |
| DP mutation | CLI 回流程 ID、state、sequence/hash、proposal hash、followup ID 與 next_action；status/history 保留完整內容。RP abandon cancel-source 轉交 DP，使用 DP 收據。 |
| advance-adoptions | 使用一般四欄 Run 收據，原 adoption 驗證與後續 next 不變。 |
| accepted next | 改 report_query，保留原 cleanup 評估與 finalize 重送 operations；DP followup accepted 保留 complete-disposition 路由。 |
| report | 仍讀 recorded final commit，資料 shape 與驗證不變。文件要求向使用者報結案前讀報告；單純重查清理不重讀。清理仍在內部驗證報告，並非刪除檢查。 |

刪除 mutation 的完整投影欄位與 next.report 屬不相容公開 CLI 回傳變更，因此升 MAJOR。呼叫者應改讀 registry_query、RP／DP status 或 report_query。內部 Store API、events、hashes、正式 Package／Result 格式不變，不遷移或重寫歷史；workflow filename 仍為 cogito-v3.json。

## 實際驗證

87 項針對性測試通過（重跑不重複計數）：

| unittest module | 通過數 |
| --- | ---: |
| test_compact_lifecycle_receipts | 5 |
| test_run_queries | 5 |
| test_disposition_flow | 4 |
| test_disposition_recovery | 3 |
| test_replan_draft | 9 |
| test_replan_toolchain | 23 |
| test_replan_handoff_tool_repair | 4 |
| test_cleanup_finalization | 7 |
| test_next_operations | 12 |
| test_preparation_hints | 9 |
| test_feature_e2e | 4 |
| test_replan_reuse_e2e | 2 |

執行形式：`PYTHONPATH=cogito/scripts:cogito/tests python3 -m unittest <module> -v`。

真實隔離 Git／CLI fixture 驗證登錄、停止憑據與全局未停止、完整 registry 命令、query 不建 lock、RP review/approve/handoff/replay、cancel-source→DP、adoption、DP followup report 入口與正式交付。人工大資料 fixture 驗證 presentation 排除 bulk 而保留工具／followup hashes，不改輸入。完整 registry 保留原始停止回應；錯誤核准 hash、停止後登錄與讀取報告失敗仍拒絕。

首次驗證與獨立審查找到 registry_query 子命令順序错误，已修正並實際執行。新 RP fixture 最初把輸入寫入已凍結來源 runtime，改為獨立暫存目錄；清理仍內部驗證報告，因此移除錯誤的零讀取／固定讀取次數假設。既有交付測試改驗 report_query 與 cleanup，而非舊完整回應；修正後相關測試通過。

mypy 1.20.2：27 個設定範圍檔案通過；git diff --check 通過。未跑全套回歸、CI 或 skill 格式驗證。未量測模型 token 或真實產品使用频率，不能宣稱節省比例。

## 獨立審查與閱讀模擬

獨立 agent 唯讀檢查 CLI 邊界、全局停止、RP/DP 特殊分支、報告與清理路由，最後無剩餘阻擋問題。四項合成閱讀情境涵蓋 executor 登錄後查 next／必要時查完整 registry、RP 收據不能代替核准前讀完整提案、accepted 首次必讀 report、DP followup 不誤認為 DP 已完成。

閱讀模擬是合成決策，不是實際使用者驗收；獨立 agent 未另跑自動化測試。
