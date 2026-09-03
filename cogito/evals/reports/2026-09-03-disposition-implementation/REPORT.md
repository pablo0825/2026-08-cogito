# 獨立成果處置實作與人工驗收模擬

日期：2026-09-03。分支：`codex/disposition-lifecycle`。

## 實作結果

採用方案 2，以獨立 `DP-*` 事件歷史管理取消後移除、保留、恢復及重新規劃撤回。原任務狀態與待處置成果分開。方案經獨立覆核與使用者核准，精確綁定後續 Package；後續任務使用原有開發、驗證、覆核、人工驗收與 finalization Gates。

- 一般取消與 RP cancel-source 共用停止、保存、取消與 Graph 釋放，重送不重複處理。
- 已核准／部分 handoff 的 RP 可保存所有來源及 successor 成果後交給 DP；舊 RP 不能再執行。
- 核准後改變決定先停止、保存、取消舊 follow-up，再修訂方案；舊核准及執行資格失效。
- 保存 HEAD、index、content 三種樹，透過 Git refs 保持可匯出；release 只處理已保存且屬於影響範圍的未提交修改。
- 不受影響的 Package 可核准及執行，相關 paths、Slice lineage、傳遞相依及登錄來源受限制。
- 人工來源恢復必須明確撤回變更、驗證原契約／內容，重跑 post checks 後回人工驗收；舊自動結案授權不沿用，額度不重設。
- 保留既有已提交成果需要有效受控 evidence 與新的人工驗收；沒有任何實作成果的取消也能以經審核的無成果證明結束。

## 驗證

| 檢查 | 結果 |
|---|---|
| 完整回歸 | 509 tests，176.256 秒，全部通過 |
| 最後處置及人工驗收模擬／回歸 | 30 tests，21.710 秒，全部通過 |
| 規劃文件漂移相容性定向驗證 | 9 tests，1.857 秒，全部通過 |
| Git whitespace check | 通過 |

完整回歸完成後，補入無成果取消案例及核准前可執行性檢查，最後以全部 30 項處置測試重新驗證；沒有將它宣稱為另一次完整回歸。log 為實際 unittest 輸出，見 `regression.log` 與 `simulation.log`。

完整回歸命令：

```sh
python3 -B -m unittest discover -s cogito/tests -v
```

最後處置模擬命令：

```sh
python3 -B -m unittest discover -s cogito/tests -p 'test_disposition_*.py' -v
```

測試以臨時 Git repository、實際工作樹、受控 checks 及公開 Gates 執行。CLI 模擬使用 `cogito_gate.main` 的 JSON 介面；沒有手工偽造正常流程狀態。停止確認需要讀取 `ps`，測試在允許該權限的環境執行。未對使用者產品專案執行真實取消或 release。

## 人工驗收模擬情境

| 情境 | 實際結果 |
|---|---|
| 取消已整合 Feature，改為無修改保留 | 原 run 維持 cancelled；review、方案核准後，缺少明確人工驗收不能完成；驗收後 DP completed |
| 一般取消，後續另開工作 | Graph owner 清除；重疊工作拒絕核准，不相關工作可核准 |
| 取消後以 Change 任務補修保留，人工再次退回 | 新 Package 精確綁定，完成實作／checks／獨立 review／整合後強制人工驗收；局部修正重驗及覆核，實際建立 final commit 並 accepted，DP 才完成 |
| 人工變更進 RP，使用者明確撤回要求 | 原 RP 交由 DP；原 run 回 post-integration-verification，fresh checks 後 awaiting-human，再經新的人工作業與 finalization accepted |
| Maintenance 有未提交成果，取消後繼續無關工作 | archive 可讀回原修改，release 不移動 HEAD；不相關任務通過 Start Gate |
| 處置已核准，Worker 做到一半時改變決定 | 活躍 Worker 未停止時保持 pausing；確認終止後保存部分 commit、取消舊 follow-up 並釋放佔用；舊核准不能繼續 |
| 已 release 的原成果要求直接恢復 | 拒絕核准，避免檔案已回 baseline 卻沿用完成標記；需另提恢復方案 |
| 尚未開始、沒有實作成果就取消 | 比對所有保存／當前產品及 staging 未改變；經覆核與明確驗收可完成，不捏造補修 |

## 稽核修正與限制

獨立覆核發現並修正：Maintenance release 後恢復可能沿用錯誤完成狀態、assessment-only 否決造成 KeyError。完整回歸另發現恢復預檢漏掉規劃文件漂移驗證，已補回。已保存的 partial-handoff 工作樹亦納入快照，對應真實 Git 回歸通過。

語意影響、相依清單與方案是否符合使用者意圖仍由 Agent 分析、Reviewer 覆核及使用者審核。Gate 驗證已記錄範圍、版本、證據與授權，不以 hash 取代語意判斷。遇到未知漂移保留現場，不覆寫或自動猜測恢復。專案仍維持單一執行中 run，未擴充多 run 並行。

共使用多輪子代理接續分工，每位在約 4–8 分鐘內完成或交接；無子代理超過 10 分鐘。
