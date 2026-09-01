# Cogito

Cogito 是以 Feature Slice 為核心的 Codex 軟體工程工作流程 skill，適用於前端、後端與全端專案，協助釐清需求、控制 Slice 邊界、建立 Spec／Plan、執行實作與驗證，以及逐步收編既有專案。

Cogito 2.2.0 新增 opt-in 的 `controlled-parallel` execution mode。在核准前先產出 Slice compatibility、Read／Write Set、共用前置工作、worktree／branch 與預計整合方式；使用者核准兩小時內有效的 Parallel Wave 後，最多三個隔離 Worker 可平行執行 implementation／tests，完成結果再通過一次一個 Slice 的獨立 review／integration gate。低風險可在 Reviewer 核准後自動整合，高風險必須指出 exact code hotspots 並等待使用者核准；Final Acceptance 仍逐 Slice 由使用者確認。

`sequential-package` 保留 2.1.0 的單 Slice Development Package 行為，`legacy-staged` 也維持原有逐階段流程。既有專案不會自動切換 mode；Rolling Adoption 與 Maintenance 仍不平行化。

`legacy-staged` 繼續採 stage-scoped invocation：使用者以 `$cogito` 明確開始或恢復每個治理階段；對目前未決問題、摘要或 Proposal 的直接回答可在同階段隱式續接。一般請求、新 Scope、新階段與中斷恢復不會隱式啟動 Cogito。

目前版本記錄於 [VERSION](VERSION)。AI 執行時以 [SKILL.md](SKILL.md) 為唯一入口；本文件只提供給維護者快速理解封裝結構，不取代其中的規則。

## 目錄結構

```text
cogito/
├── SKILL.md
├── agents/
├── evals/
├── references/
├── VERSION
└── README.md
```

## 各項責任

- `SKILL.md`：skill 入口、核心不變量與操作路由。
- `agents/`：Codex 顯示與啟動設定。
- `evals/`：可重跑的路由、授權、狀態、追溯與 Maintenance 行為案例。
- `references/`：依操作需要才讀取的 workflow 與文件模板。
- `VERSION`：目前 skill 的語意版本。
- `README.md`：提供維護者使用的簡介與結構說明。

## 維護原則

修改 skill 後以 `evals/evals.json` 的固定案例重跑回歸測試。案例保存的是輸入與可觀察期望；執行時使用乾淨子代理讀取當前 skill，避免靠主對話記憶補足規則。更新行為規則時同步檢查入口路由、對應 reference、模板與 eval expectation，並提升 [VERSION](VERSION) 的語意版本。
