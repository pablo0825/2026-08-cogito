# Cogito

Cogito 是以 Feature Slice 為核心的 Codex 軟體工程工作流程 skill，適用於前端、後端與全端專案，協助釐清需求、控制 Slice 邊界、建立 Spec／Plan、執行實作與驗證，以及逐步收編既有專案。

Cogito 2.0.8 採 stage-scoped invocation：使用者以 `$cogito` 明確開始或恢復每個治理階段；對目前未決問題、摘要或 Proposal 的直接回答可在同階段隱式續接。一般請求、新 Scope、新階段與中斷恢復不會隱式啟動 Cogito。

2.0.8 將 Grilling 每輪題目數調整為最多五題，不設最低題數；只選取 frontier 中的必要問題，不為湊數增加問題。一次一題、回答後重排、Readiness 與停止條件均不變。

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
