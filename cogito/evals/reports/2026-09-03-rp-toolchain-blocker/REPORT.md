# FS-038 RP 快照與工具更新阻擋模擬

日期：2026-09-03。受測程式：`537b40629ab95017cc3ab991171244a66e25a273`。

結論：兩項描述的阻擋都可以重現。第一項是已修復的歷史缺陷；第二項仍存在，目前缺少正式的工具版本接軌機制。工具提交也無法解除 RP 凍結。

## 實際模擬

重跑命令（從 repository 根目錄）：

```sh
python3 -B cogito/evals/reports/2026-09-03-rp-toolchain-blocker/simulate.py
```

結果：**9/9 情境符合預期**。完整輸出保存在 `simulation.json`，重跑會更新此輸出。

| 檢查程式與快照 | 停止後變動 | 實際結果 |
| --- | --- | --- |
| 修復前 Store＋舊快照 | 正常事件、草稿、新規劃文件 | content drift，維持 analyzing |
| 現行 Store＋新／舊快照，各 1 次 | 正常事件、草稿、新規劃文件 | propose 成功，進入 reviewing |
| 現行 Store＋新／舊快照，各 1 次 | 另修改專案內 Cogito 工具檔 | content drift，明確列出工具檔 |
| 現行 Store＋新／舊快照，各 1 次 | 將工具更新提交 | baseline drift，維持 analyzing |
| 現行 Store＋新／舊快照，各 1 次 | 未授權產品變更 | content drift，明確列出產品檔 |

實際錯誤包括：

```text
delivery content drifted outside new control documents
delivery content drifted outside new control documents: .codex/skills/cogito/scripts/cogito_gate.py
delivery baseline drifted since stop checkpoint
delivery content drifted outside new control documents: src/a.txt
```

每個情境都驗證：停止快照、來源事件、原核准 Package、successor 候選 hash／事件、Worker commit 與乾淨狀態維持不變。被拒絕時不追加 RP 事件、不產生 proposal hash；成功提案仍未核准 successor Package。

方法與限制：使用真實暫存 Git repository、真實 Worker、既有測試 fixture 與 Store 呼叫。工具更新用代表性檔案內容變更模擬，沒有重演全部 24 個檔案或 qs 安裝。修復前情境載入 `9c28b1de9f15acb4a3d182bbd4a7d6afa53c8b3c` 的實際 Store 程式，搭配目前 fixture／依賴模組，執行 `_assert_source`；不是完整舊版 CLI 端到端評估。舊格式快照在 stop 當下產生，沒有覆寫既存歷史。來源 fixture 的核准為合成資料，不代表真實專案取得核准。

## 另外執行的既有回歸

兩位子代理各於 10 分鐘內完成唯讀分析與測試。

- `python3 -m unittest discover -s cogito/tests -p 'test_replan_runtime_snapshot.py' -v`：15 tests，67.559 秒，OK。涵蓋新舊快照、runtime 歷史保留、真實內容漂移拒絕與 handoff 恢復。
- `python3 -m unittest discover -s cogito/tests -p 'test_replan_adoption.py' -v`：10 tests，OK。此處 adoption 是成果與驗證證據採認，不是工具接軌。

共 25 項既有自動化回歸通過，與上述 9 個行為模擬分開計算。受控 runner 需 `ps`；runtime 測試首次在 sandbox 內因程序查詢被禁止而無法完成 fixture，獲准在 sandbox 外重跑後通過。模擬也在獲准環境執行。

## 真實專案的唯讀核對

來源：`/Users/pablo/Documents/project/2025-06-pointsReview-backend`。未在此專案呼叫會寫入狀態快取的 Gate 操作，未變更其檔案、index、Git objects、分支或事件。

- 原紀錄中的停止 HEAD：`bb44186d6aa1c16eade88bd92a5c19d07a1372c8`。
- 本次讀取時 HEAD 已是 `e90494de03b1be2607e84dbe4c7adfd46443806f`，新增提交 `chore(cogito): sync latest skill updates`；該提交不是本次操作建立的。
- 兩個 HEAD 間恰有 24 個 `.codex/skills/cogito/` 檔案差異。讀取時工具目錄沒有未提交或未追蹤差異。
- RP journal 仍只有 `replan-created`、`replan-stopped` 兩筆，停止快照沒有 `runtime` 欄位；沒有成功 proposal。
- FS-038 最後事件是 block，Worker HEAD 仍是 `7d1a21f88a907b6f7addcc1d53475fbc4c1c7a84`，Worker 乾淨。
- FS-043 最後事件是 package-ready，候選 hash 仍是 `8dbdbd1ce7f3c65f2602395ca6af072320dca3402eb064684333f71220a2d12f`；快取狀態為 awaiting-package-approval，package_hash 為空。
- 相對停止 HEAD，當前 `package.json` 與 `package-lock.json` 無差異。

因此「尚未提交工具更新」是原阻擋紀錄當時的情況，已非本次讀取時的最新狀態。依現行 `_assert_source` 的檢查順序，真實專案現在重試預期先遇到 baseline drift；本次只作程式碼推論與隔離重現，沒有在原專案重送 propose。

## 根因與設計缺口

`cogito/scripts/cogito_evidence_binding.py` 透過私有 index 收集未忽略檔案。歷史 Store 在停止快照後追加事件，又直接比較 raw trees，故自身 runtime 寫入造成漂移。`cdce97c` 已加入 `cogito_replan_snapshot.py`：保留原始 trees，精確辨識允許變動的 runtime，同時檢查事件前綴及凍結證據；舊快照也使用此相容比較。

現行 `cogito_replan_store.py:237` 仍要求 delivery HEAD／branch 相同；`:248` 到 `:263` 的允許差異僅含指定的新控制文件。`.codex/skills/cogito/` 沒有獨立版本身分，因此更新屬真實 delivery 漂移。CLI／事件投影目前没有工具升級、相容性覆核與核准事件。`replan-snapshots.md:41` 的「更新 Gate 再重試」指引缺少專案內工具會改動凍結內容／HEAD 的限制。

建議的正式接軌範圍（尚未實作）：

1. 區分產品、受管 runtime、工具 manifest。工具以精確路徑、檔案 mode、blob hash 與實際執行程式身分綁定；VERSION 字串不能單獨代表工具內容。
2. 新增獨立的工具接軌提案、相容性覆核、核准及生效事件，綁定原 snapshot hash、新舊工具 manifest、差異與核准者。工具接軌不授權 successor Package 或產品修改。
3. 原始快照與事件不變，由追加事件定義經核准的比較基準；每次操作仍核對精確工具內容與原產品／Worker／契約／歷史。不得豁免整個目錄。
4. 相容性驗證涵蓋事件讀取、契約驗證、投影、workflow 與需要重跑的 Gate；不能只接受新版工具自報 compatible。已有 proposal／review 時，須定義是否失效並要求重審。
5. 同時處理未提交工具差異與本次已提交工具更新：若允許接軌新的 HEAD，須以明確核准事件綁定兩個 commit，證明產品投影與其他凍結資料不變。不能全面移除 HEAD guard。若候選 Package 的 baseline 因此必須改變，須重新 prepare／review／approve，不能偷偷改 hash。
6. 舊 RP 可由保留 Git trees 重建舊工具 manifest；舊工具內容若從未進入快照且無其他可信紀錄，應報告缺失，不能補造舊版本證據。接軌操作還須支援中斷、同 action 重試與冪等。

未來實作回歸需追加：新／舊 RP 正式接軌成功、staged／unstaged／committed 工具更新、工具與產品混改拒絕、核准後再次改工具拒絕、manifest 路徑欺騙／symlink／gitlink、不相容版本與中斷恢復。本次成功重現「缺少接軌」並不代表接軌功能已完成。
