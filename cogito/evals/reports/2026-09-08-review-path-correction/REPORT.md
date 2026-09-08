# 審查階段同範圍補正驗證

## 交付範圍

版本 `4.3.0`。Atomic Development 在既有 `review-fix` 階段，可使用 `amend-paths` 同時追加新修正 Tasks 與必要精確檔案授權。既有獨立 Reviewer 可覆核，不新增流程單、角色、使用者核准或 successor run。finding-only `review-fix-start --input` 保留精確 finding 引用；一般帶 Amendment 的合併啟動仍適用於已授權路徑內的修正。

新補正限當前 finding 的 Slice；原 Task、Package、commit、Result 與 evidence 不改寫。原 executing 路徑補正及非 Atomic 流程維持既有規則。新 Amendment 組合需本版工具支援，未宣稱舊工具能讀取新增事件內容。

選測與複審沿用既有 Atomic 政策：相關 Task checks、本波目前內容驗證、可選的未受影響 approval 採認，以及最終整合版本的 CI 完整回歸。不新增測試影響分析或跨 run 證據採用能力。

## 自動化驗證

以下為實際執行結果，各組有重疊，不相加為唯一測試數：

| 範圍 | 結果 |
|---|---|
| 原路徑補正、新審查補正、review-fix 啟動、Atomic correction／verification、review retention 規則／流程／對抗案例、next 與 correction rules | 71 tests 通過 |
| 路徑契約、contract materialization／shapes、Atomic contract、next 與 correction rules | 64 tests 通過 |
| 路由修正後的審查補正、review-fix 啟動及 Gate CLI contract | 15 tests 通過 |
| 最後新增 finding Slice 限制等案例後，審查補正流程聚焦複查 | 6 tests 通過 |
| mypy 1.20.2，`cogito/mypy.ini` 指定範圍 | 27 source files 通過 |
| `git diff --check` | 通過 |

新 CLI 案例由 Reviewer needs-fix 開始，依 finding-only start、proposal、原 Reviewer scope review、新修正 Task、相關檢查、複審、整合至 finalization `accepted`。檢查序列為 `C-a`、`C-b`、`C-map`、整合後 `C-b`；修正後的階段切換沒有額外重跑，原 Package、Task 與 evidence bytes 保持不變。這是隔離 Git 專案的合成產品案例，不是後端 FS-041 的實際驗收。

負向與恢復涵蓋：錯誤階段、修改舊 Task、未授權先改檔、非當前 finding Slice、跨 Slice predecessor 未 integrated、缺漏 paths/checks、獨立性、proposal HEAD 漂移、pending check fence、event 重播、封存失敗後重送及撤回。完成 action 重送不重複新增 Task 或事件。

初次沙箱流程測試因 `ps` 權限失敗，未能驗證行為；允許程序檢查後重跑通過。系統 Python 缺少 mypy／PyYAML，後續使用既有離線 uv 快取執行型別與格式檢查，未增加 runtime dependency。

未執行全套 regression，未宣稱 CI 已執行或通過；本次選測涵蓋變更契約、事件投影、審查修正、證據沿用、CLI、結案與恢復相依。

## Skill 格式與 Agent 評估

- Skill 格式：`quick_validate.py cogito` 實際通過，與行為測試分開記錄。
- 獨立程式審查：子 Agent 唯讀檢查實作及新增測試，並執行路徑契約測試；增量複查後無剩餘必要修正。
- 聚焦閱讀模擬：另一子 Agent 模擬原需求欄位缺漏、新權限需求、未受影響 approval 採認及 review 後封存失敗四個情境。發現 next 將 Amendment 誤列必填、文件總則漏列審查入口兩項問題，主 Agent 修正後聚焦複查通過。
- 閱讀模擬是合成 Agent 決策與靜態文件核對，不是實際 Gate 執行或使用者驗收。實際 CLI 執行結果另列於自動化驗證。
