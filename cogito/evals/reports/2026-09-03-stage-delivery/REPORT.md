# 方案 A 實際模擬結果

兩個情境均通過真實 Git／RunStore Gate／受控檢查，並完成最後的 `finalize`。原始執行時間、版本與摘要見 [simulation.json](simulation.json)，重跑方式見 [README](README.md)。

| 驗證項目 | Feature | Maintenance |
|---|---|---|
| 準備階段提交 | Shared Understanding、Boundary、Package 各一筆 | Package 一筆 |
| 初次人工驗收 | `awaiting-human` | `awaiting-human` |
| 人工退回後 | 原 run 局部修正，新增修正 commit | 原 run 局部修正，保存工作樹快照 |
| 修正通過新檢查與獨立 reviewer 後 | 仍為 `awaiting-human` | 仍為 `awaiting-human` |
| 未收到明確接受就 finalize | 拒絕 | 拒絕 |
| 合成使用者明確接受後 | `finalizing` | `finalizing` |
| 最後 Result 缺少或竄改摘要 | 結案記錄規則拒絕 | 結案記錄規則拒絕 |
| 正確 Result／Graph 提交後 | `accepted` | `accepted` |
| Start Gate 後產品 commits | 實作、修正、結案，共三筆 | 結案時唯一一筆 |

Feature 的 Slice 整合實際採 `git merge --ff-only`，整合 HEAD 與 worker commit 相同，沒有為了階段名稱增加空 commit 或 merge commit。兩個情境都驗證 CLI 產生的摘要與 RunStore 相同，最後 Git 中的 Result 保存同一份摘要，且 checkout 乾淨。

這是可重跑的流程模擬，採合成人工回饋、接受及 reviewer 身分；不代表真實使用者已驗收產品，也不宣稱 reviewer 的實際產品品質判斷已通過。受控 Python 檢查有真正執行。回歸測試定義與本次實際執行輸出分開保存。

## 自動化驗證

- 完整回歸：`python3 -m unittest discover -s cogito/tests -v`，525 項通過，301.152 秒；見 [regression.log](regression.log)。
- 行為模擬：Feature、Maintenance 兩個情境均通過；見 [simulation.log](simulation.log) 與上述原始 JSON。
- Skill 結構驗證：`quick_validate.py cogito` 通過。
- mypy 1.20.2：新增摘要模組單獨檢查通過；完整設定仍有 5 個既有錯誤，集中於本次未修改的 `cogito_projection.py` 第 91、95、107 行，見 [mypy.log](mypy.log)。完整型別檢查尚未全綠。
