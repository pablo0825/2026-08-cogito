# Cogito 3.0

Cogito 是以程式化 Gate 管理多 Agent 軟體開發的 Codex skill。3.0 是 clean break：單一狀態機取代 Blueprint 與舊執行模式，Project Graph 表達 Slice DAG，Development Package 是唯一正式開發核准；實作、測試、獨立審查與受控修正可自動前進，只有適用的 human gate 會中途通知使用者。

## 結構

```text
cogito/
├── SKILL.md
├── VERSION
├── agents/openai.yaml
├── workflows/cogito-v3.json
├── schemas/
├── scripts/
├── references/
├── tests/
└── evals/
```

- `SKILL.md`：精簡的語意政策與 progressive-disclosure 路由。
- `workflows/`：狀態、合法轉移、guard 與重試上限。
- `schemas/`：Project Graph、Package、Run、Agent Result 與 Result 的機器契約。
- `scripts/`：Gate runtime 與 controlled runner。
- `references/`：依 `next_action` 才載入的作業規則與模板。
- `tests/`、`evals/`：狀態機、邊界與行為回歸。

3.0 不讀取或遷移舊 Blueprint。既有 `docs/project/`、舊 Spec 與其他文件保持原位並作為 read-only sources；第一次觸及相關能力時，以 lazy adoption 在同一 Package 收編必要來源，不建立額外核准點，也不搬移無關文件。

Runtime 不接受 Agent 自行宣告核准、驗證通過或獨立審查成立；這些 verdict 由 CLI 從 Package、lease/result identity 與不可變 machine evidence 計算。Technical Amendments 先 materialize 為 effective contract，才能執行或驗證。Final commit 包含 Result 與 Project Graph，而該 commit 的 ID 由後續 event 與結案報告記錄，避免 Result 自我引用。

維護時先執行 runtime/unit tests，再執行 skill validation 與 behavioral evals。狀態轉移的正確性應由程式測試證明，不以文字斷言代替。
