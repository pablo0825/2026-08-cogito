# RP runtime 隔離與人工驗收流程模擬

執行日期：2026-09-03；核心實作 commit：`cdce97c`。結果：**PASS，1 個端到端測試，6.728 秒**。

這是暫存 Git 專案中的行為模擬。人工回饋、提案同意與最後驗收同意均為測試提供的合成決策，**不代表使用者已核准任何真實專案的提案或成果**。

## 重跑方式

從此 repository 根目錄執行：

```sh
python3 -B -m unittest discover -s cogito/tests -p test_replan_runtime_human_e2e.py -v
```

測試檔：`cogito/tests/test_replan_runtime_human_e2e.py`。

測試建立真實 Git repository、來源 Worker 與 successor Worker，執行實際受控程式檢查、commit 與 merge。RP 的 begin、stop、propose、review、approve、handoff，以及最後的 human-approve，均以各自全新 CLI process 執行。其餘來源建置、人工回饋分類、任務、驗證與整合流程使用正式 RunStore Gate 方法，未直接捏造事件或覆寫 state.json。

受控執行器需要作業系統 process inspection；本次在允許 `ps` 的工具執行環境完成測試。

## 實際模擬與觀察

| 階段 | 模擬動作 | 已驗證結果 |
| --- | --- | --- |
| 原成果待驗收 | 完成原 Worker、review、整合與程式檢查 | 來源進入 awaiting-human |
| 人工退回 | 合成「修一個字＋改變自動查詢行為」混合回饋並分類 | 路由為 change；不能以 local correction 繞過 RP |
| 重現環境差異 | RP 前在主目錄提交移除 `.cogito/` 忽略規則，原 Worker 保有該規則 | `git check-ignore` 確認主目錄 runtime 未被忽略 |
| 停止保存 | 真實 CLI begin → stop | 成功進入 analyzing |
| 準備 successor | 正常建立 successor 事件、新 Spec／Plan、新 Package 與 RP drafts 輸入 | 這些合法變動未造成 delivery drift 誤判 |
| 提案覆核 | 真實 CLI propose → review → approve | 成功進入 reviewing 並完成合成提案同意 |
| 交接 | 真實 CLI handoff | RP completed；successor executing；來源 superseded |
| 保存完整性 | 比較來源、Worker、Git index 與事件歷史 | 原 Package 與人工回饋 hash 不變；來源／RP 歷史保留為原始 prefix；原 Worker commit 與乾淨狀態不變；真實 index bytes 不變 |
| successor 實作 | 真實 Worker 修改 a1/b1 為 a2/b2、提交、review、程式檢查與整合 | 完成後仍進入 awaiting-human，雖然新版 Package predicates 為空 |
| 舊同意不可沿用 | 檢查 successor human-review mandate 及事件重建，重送同一 handoff | 原回饋作為來源依據保存；沒有自動產生 human-approved；重送 handoff 不追加 successor 事件 |
| 新一輪人工驗收 | 用新 CLI process 提交僅適用暫存測試的 fresh human-approve | successor 從 awaiting-human 進入 finalizing；原事件保持 append-only |

## 模擬範圍與限制

主目錄的 runtime 從 RP begin 到 handoff 完成均未被忽略，因此本測試直接涵蓋本次 RP 缺陷與後續交接。

**handoff 完成後**，測試才在暫存 repository 的 `.git/info/exclude` 加入 `.cogito/`，用來滿足一般 post-integration runner 的既有內容快照隔離條件。此設定不修改 tracked 檔案、Git 全域設定、RP 舊快照或事件歷史。因此本結果不宣稱所有非 RP runner 都已支援未忽略 runtime 的環境。

模擬停在 finalizing，驗證的是重新規劃後「必須取得 fresh 人工驗收決策」的流程。它未執行最終結果報告封存，也不代表真實專案已 accepted。

舊版含 runtime 快照的相容恢復，以及產品、凍結文件、Worker、事件竄改拒絕案例，由其他 RP regression 測試驗證，不計入此處的 1 個行為模擬結果。
