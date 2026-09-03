# 人工驗收流程模擬

日期：2026-09-03。驗證的流程實作提交：`677815e`。

從 repository 根目錄執行：

```sh
python3 -B cogito/evals/reports/2026-09-03-human-acceptance/simulate.py
```

模擬器建立可丟棄的真實 Git repositories，以公開 Gates 走到 awaiting-human。人工回饋、分類、修正開始／完成、驗證、審查與升級皆呼叫真實 CLI。Implementer／Reviewer 的身分及結果由測試 fixture 提供，經公開 Agent Result 介面驗證；沒有偽造 workflow 事件。受控 Python checks 在實際 delivery 內容上執行，新增的文字檢查會拒絕原始錯字。

`simulation.json` 保存五個情境的實際 CLI 結果、計數器、下一步及從事件重建的完整狀態路徑：

| 情境 | 預期結果 |
|---|---|
| 其餘已接受，局部修好即可 | 完成修正、checks、獨立 reviewer 記錄與 final commit，accepted |
| 使用者尚未驗收完畢 | 修正與審查後回 awaiting-human |
| 混合局部修正與變更 | route=change，拒絕開始局部修正 |
| 修正途中影響擴大 | blocked，下一步準備 RP |
| 開發已修兩輪，再做人工作業三輪 | 開發／人工計數分別保持 2／3，第四輪 blocked |

額外的真實 Git 回歸測試涵蓋 RP successor 強制重新人工驗收、Feature 與 Maintenance 結案、Spec／Plan 修改的新舊快照、第三輪檢查／審查失敗立即停止，以及修正途中新回饋撤銷舊結案授權。測試指令：

```sh
python3 -B -m unittest discover -s cogito/tests -p 'test_human*.py' -v
```

這是 runtime／CLI 流程模擬；自然語言分類與 Reviewer 的實質判斷由 fixture 明確提供，不能將結果當成真實 Agent 判讀 UI 品質或使用者意圖的行為評測。RP successor 另由 `test_human_replan.py` 的端到端測試驗證。執行後清除暫存 repository，保留事件狀態路徑及結果摘要。此環境的 controlled runner 需要查詢測試 subprocess 的程序資訊，因此在已授權的程序檢查權限下執行。
