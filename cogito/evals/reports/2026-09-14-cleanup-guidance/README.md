# 清理阻擋診斷與結案收尾指引

交付版本 5.1.0。實作使用者核准的②清理具體下一步、③開發結案與清理結果分開呈現。沿用 JSON、英文欄位與提示、既有 argv 操作；文件與使用者回報使用中文。不做④歷史工作樹盤點。

## 修改與連動

| 位置 | 結果與保留邊界 |
| --- | --- |
| cleanup observation | 非 quiescent 時只列未確認終止的 executor_id、kind、observation、原因及 handle 或 PID／PGID；不複製全體 registry 或 raw_response。 |
| next.cleanup | 新增 pending／no_pending_cleanup 與觀察說明。有 executor 阻擋時提供 registry_query；外部缺憑據且有匹配 lease 才提供 executor-receipt argv，receipt-path 留給真實工具憑據。程序存活或不確定狀態不提供外部補登操作。 |
| finalize CLI receipt | 保留 removed／retained／error，新增 status、note、next_query；complete 只表示本次嘗試沒有保留，pending 表示有保留或錯誤。查詢後才決定後續操作。 |
| accepted DP followup | 增加 cleanup 觀察，保留 report_query 與 complete-disposition 優先；不增加頂層 finalize 重試。active DP 的既有保留判斷仍生效。 |
| 一般 accepted | 保留原 finalize request fingerprint、字面參數及 action ID 的重送；缺原指紋仍回 blocker，不改造新 action。 |
| 文件 | report 後檢查清理結果，處理可排除的阻擋；向使用者分開回報開發與清理。保留資料須如實說明，不為清理完成而刪除。 |

CLI/query 新增資訊屬相容功能，因此升 MINOR。既有一般收據欄位、完整 registry 查詢、正式 report、事件／hash／保存契約及 cleanup mutation 安全規則不變；不需資料遷移。內部 build_finalization_receipt 增加 root 參數，CLI 與直接呼叫測試已同步。

清理觀察先讀整體 registry；registry 損壞或 OS 觀察失敗仍保守保留，此時不能保證列出其他 executor 的細節。無相符 Worker lease 時只有診斷，不偽造 lease。外部工具憑據仍是既有信任邊界，不把代理文字說「完成」當成終止證明。

## 自動化驗證

57 個不同測試通過，重跑不重複計數：

| unittest module | 通過數 |
| --- | ---: |
| test_cleanup_guidance | 5 |
| test_run_queries | 5 |
| test_cleanup_finalization | 7 |
| test_next_operations | 13 |
| test_disposition_flow | 4 |
| test_compact_lifecycle_receipts | 5 |
| test_cleanup | 14 |
| test_cleanup_history | 4 |

```sh
PYTHONPATH=cogito/scripts:cogito/tests python3 -m unittest test_cleanup_guidance test_run_queries test_cleanup_finalization test_next_operations test_disposition_flow test_compact_lifecycle_receipts test_cleanup test_cleanup_history -q
```

第一輪 56 項通過，新增整合測試因 fixture 假設失敗；依序修正完整 registry 包含歷史 check 程序、macOS /var 路徑正規化、隔離 Git 無預設 info/exclude 三項測試設定後，僅重跑該案例並通過。這些修正沒有改變產品行為。

新增整合測試實際執行 finalize receipt 的 next_query、report_query、registry_query、缺憑據項目的 executor-receipt，以及原 finalize argv。它確認不完整憑據被拒絕、已終止項目不回拷、query 不建 registry lock／cleanup receipt／refs、不改 runtime files；補登後預覽可清理仍是 pending，隨後新增 ignored .env 會阻止真正清理。移除 fixture 的 .env 後以原請求成功清理，重送不追加事件，正式報告保持相同。

其餘新增情境包括多個外部阻擋、無 lease、running／descendants-running／identity-mismatch／unverified-shared-group、registry 與 OS 查詢失敗、收據深拷貝及 cleanup error 不能顯示 complete。程序觀察與終止工具回應使用明確合成 fixture，不是對產品代理的實際停止驗證。DP 原端到端測試增加路由與 active disposition 保留斷言。

既有回歸覆蓋清理歷史、RP／DP 後續使用、原 finalize 重送、正式報告驗證、受管目錄／引用／本地資料保護。隔離 Git／runner 測試透過 sandbox escalation 取得 ps 程序觀察能力。

mypy 1.20.2：27 個設定範圍檔案通過。舊暫存依賴不完整，另安裝至 /private/tmp/cogito-cleanup-mypy-1.20.2，未新增專案依賴。git diff --check 通過。未跑完整回歸、CI 或 skill 格式驗證。

## 獨立審查與閱讀模擬

獨立子代理唯讀檢查收據／觀察語意、DP 優先順序、lease 與 registry 邊界、測試及文件，最終無必修問題。發現直接測試呼叫須配合新增 root 參數，已同步。

另一子代理完成 5 項合成閱讀模擬：缺外部憑據、程序存活／身分不明、預覽後新增 .env、DP followup 優先、report 失敗或已讀報告僅查清理。文件中 handle／status 與 raw_response 對應說明曾有歧義，已明確列出頂層及內層對應與 completed／interrupted 合法值，聚焦複查通過。

子代理未另跑測試。閱讀模擬不是實際 Gate 執行或真實使用者驗收；本輪未進行後端產品任務驗收，也未量測 token 節省。
