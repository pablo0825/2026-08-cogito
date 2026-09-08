# Cogito

Cogito 是以程式化 Gate 管理多 Agent 軟體開發的 Codex skill；目前版本以 [`VERSION`](VERSION) 為準。Development Package 凍結正式開發授權，Agent 負責需求理解、實作與語意判斷，Gate 根據契約、狀態與證據決定能否前進。既有 workflow 與 JSON contract 使用 `3.0` schema，檔名維持 `workflows/cogito-v3.json`。

## 使用入口

明確呼叫 `$cogito` 後，依 [SKILL.md](SKILL.md) 的啟動條件、操作迴圈與 `next_action` 路由閱讀文件。各操作程序位於 `references/`，不需預先讀取全部文件。

既有專案依 [Project Bootstrap](references/project-bootstrap.md) 採納本次必要來源。準備相近的 Package 時，可明確指定已 accepted 的單一 Development Slice，以唯讀 `slice-inventory` 取得歷史候選清單；適用性仍由 Coordinator 判斷。操作、輸出與限制見 [Package Authoring](references/package-authoring.md#歷史-slice-查詢)。

## 結構與維護

| 位置 | 責任 |
|---|---|
| `SKILL.md`、`agents/openai.yaml`、`VERSION` | 操作入口、Agent metadata 與版本 |
| `workflows/cogito-v3.json` | 合法狀態、轉移、guards 與重試上限 |
| `scripts/` | Python executable contracts、Gate runtime 與 controlled runner |
| `references/` | 按目前工作讀取的操作程序與模板 |
| `tests/`、`mypy.ini` | 自動化測試及靜態型別檢查 |
| `evals/` | Agent 情境定義與有範圍限制的執行紀錄 |

Repository 維護、測試選擇與版本政策依 [AGENTS.md](../AGENTS.md)。Python executable contracts 是資料驗證的唯一權威；模組責任見 contributor guide，實作與相容性細節見 [Runtime Internals](references/runtime-internals.md)。[RP 設計紀錄](RP-SUBTRACTIVE-REDESIGN.md) 保存分期設計歷史，不取代目前操作規則。

## 驗證紀錄

個別閱讀模擬與 Gate 執行紀錄保存在 [evals/reports/](evals/reports/)，例如 [2026-09-06 閱讀流程整理](evals/reports/2026-09-06-skill-readability/REPORT.md)；各結果只支持報告記錄的版本、環境與範圍，不驗證後續變更。

自動化測試、skill 格式驗證、合成 Agent 閱讀模擬與實際使用者驗收分別回報。執行方式與檢查範圍依 contributor guide，不以歷史報告或情境定義代替本次驗證。
