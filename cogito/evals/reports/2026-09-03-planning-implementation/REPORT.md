# 核准前同一 run 多輪規劃：實作驗收

日期：2026-09-03。來源版本：`7a6b2b0`。本次採用使用者選定的方案一：在同一 run 的事件紀錄中管理規劃輪次，保留完整新舊候選，不另建立規劃修訂單。

## 實作結果

- `planning begin` 先保存來源並清除可核准候選，依 plan／boundary／requirements 回到正確準備階段。
- 所有不同候選都要開始新輪次，原先直接替換草稿、沿用舊共識／Boundary 的入口已封住。
- 新輪次逐項記錄需求、Boundary、Spec、Plan、DAG、Acceptance 的沿用／重做與理由。機械比對 reuse 欄位，檢查 revised Boundary 與 Slice 數量一致。
- requirements 輪次要求新的摘要文件、真實內容 hash、明確本輪確認，再完成 Boundary；preparation 操作與 Package 都綁定輪次。
- 每次候選事件保存 Package JSON、引用文件 bytes 與快照 hash。`history` 提供可讀文件文字；`compare` 提供前後欄位與文件 diff，磁碟上的後續修改不會改寫保存版本。
- 必須由不同於作者的 Reviewer 提交完整評估，覆核綁定完整 proposal hash，包含本輪、候選快照與修訂請求。新版核准必須引用同一覆核內容。
- 核准前及正式核准事件寫入前都檢查文件；在核准發布途中發現文件漂移，回復未提交的 Package／Graph 發布。
- 同一 journal 與原有 action identity／CAS 保護支援快取重建、同操作重送、中斷後接續；已確認且仍有效的需求不需重複詢問。
- 未完成候選時可重新開下一輪，但不能降低尚未完成的影響層級。撤回需明確授權，並驗證完整原版檔案、政策與 delivery 狀態；不自動覆寫工作檔案。
- 既有 RP 的未核准 successor 也可修訂。原 RP 提案失效時回報 `proposal_stale`，必須重新提案與覆核；仍由 RP approval／handoff 完成契約承接。RP 核准已落盤後禁止再變更 successor 規劃。

## 具體驗收

測試使用真實暫存 Git repository 與 CLI；沒有修改真實專案的 run、Project Graph 或產品功能實作。

1. 三功能、三 Slice 改成只做篩選：重新確認需求、Boundary、文件與候選，覆核後核准，Start Gate 成功，只派生篩選任務，原事件歷史完整保留。
2. plan-only 調整實作安排：保留需求、Spec、Boundary 及驗收；越級更改內容被拒。
3. boundary 輪次：不得跳過 Boundary；宣告沿用驗收卻更改 checks 被拒。
4. 舊候選、舊輪次、舊覆核、舊 action replay 不會恢復過期授權。
5. 自我覆核、錯誤 proposal hash、未解決 findings、缺必要 assessment 均被拒。
6. 確認後文件變動、覆核後文件變動、核准發布期間文件變动，均有具體攔截案例。
7. 刪除／破壞 cache 可重建；begin、review、withdraw 的事件已落盤後 cache 寫入失敗，CLI 以同 action 恢復，沒有重複事件。
8. 同一路徑的需求摘要更新：保留新版 bytes 時不能恢復舊版；核對並還原原檔後，可撤回、核准及通過 Start Gate。
9. 未完成需求輪次再次改需求可開新輪；未完成 requirements→boundary／plan 或 boundary→plan 降級被拒，原事件不變。
10. Legacy 候選只有 hash 時，缺少精確原 Package 被拒；提供匹配 Package 與原檔後可補齊來源快照，並比較新舊輪次。
11. RP successor 修訂後舊 RP 提案不能核准；重新覆核提案後，handoff 完成並進入 executing。RP 授權已落盤但尚未發布時，重新修訂與撤回都被攔住。

對應測試：

- `cogito/tests/test_planning_rounds.py`
- `cogito/tests/test_planning_cli.py`
- `cogito/tests/test_planning_integrity.py`
- `cogito/tests/test_planning_rp_interop.py`
- `cogito/tests/test_planning_withdrawal.py`
- 更新 `cogito/tests/test_package_revisions.py`，保留原先三種 Package、舊候選與競態回復斷言，改走明確輪次與覆核。

## 驗證紀錄

- 修正相容性問題後，全套 443 項通過，113.228 秒，見 `regression-final.log`。
- 最終提交前全套 **449 項測試通過，116.906 秒**（包含最後補強），見 `acceptance.log`。
- 7 份操作文件的相對連結檢查全部通過，`git diff --check` 通過。
- mypy 無法執行：環境回報 `No module named mypy`。未宣稱型別檢查通過。
- 子代理分批處理設計審查、測試、CLI／復原、文件及最後覆核，各代理均在 10 分鐘內結束並交接。

重跑完整驗收：

```sh
python3 -B -m unittest discover -s cogito/tests -v
```

程序相關測試需要允許檢查暫存測試程序的 OS 資訊。完整原始輸出保存在本資料夾。

## 已知範圍

- 語意一致性仍由 Coordinator 與獨立 Reviewer 判斷。hash、輪次與結構驗證不能證明任意自然語言需求與程式規格語意等價。
- 歷史初版的共識可能只有 hash，文件可能未曾保存；不能從 hash 還原原文。缺完整來源時要求原 Package／原檔，不以新資料冒充舊歷史。
- Mini Package 只支援範圍不變的 plan 修訂；尚未提供 same-run Mini 升級為 Feature。
- recover 只驗證已綁定內容。尚未保存的草稿與未知外部修改仍需 Coordinator 檢查；錯誤會停止操作，不會自動猜測版本或自動寫入 blocked。
- 本次保存比較與操作介面為 CLI／JSON／文件，沒有新增圖形介面。

正式操作說明：`cogito/references/planning-revisions.md`。

## 提交

- `f8aaf95`：同一 run 的多輪規劃、版本快照、覆核／核准／撤回／復原與測試。
- `30ec78a`：規劃修訂操作文件及相關流程更新。

兩筆均在驗收後完成本機提交，未 push。本資料夾為本機驗證證據，不納入產品提交。
