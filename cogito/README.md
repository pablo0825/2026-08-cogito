# Cogito 3.0

Cogito 是以程式化 Gate 管理多 Agent 軟體開發的 Codex skill。3.0 是 clean break：單一狀態機取代 Blueprint 與舊執行模式，Project Graph 表達 Slice DAG，Development Package 是唯一正式開發核准；實作、測試、獨立審查與受控修正可自動前進，只有適用的 human gate 會中途通知使用者。

## 結構

```text
cogito/
├── SKILL.md
├── VERSION
├── agents/openai.yaml
├── workflows/cogito-v3.json
├── scripts/
├── references/
├── tests/
└── evals/
```

- `SKILL.md`：精簡的語意政策與 progressive-disclosure 路由。
- `workflows/`：狀態、合法轉移、guard 與重試上限。
- `scripts/`：Python executable contracts、Gate runtime 與 controlled runner。
- `references/`：依 `next_action` 才載入的作業規則與模板。
- `tests/`、`evals/`：狀態機、邊界與行為回歸。

3.0 不讀取或遷移舊 Blueprint。既有 `docs/project/`、舊 Spec 與其他文件保持原位並作為 read-only sources；第一次觸及相關能力時，以 lazy adoption 在同一 Package 收編必要來源，不建立額外核准點，也不搬移無關文件。

Runtime 不接受 Agent 自行宣告核准、驗證通過或獨立審查成立；這些 verdict 由 CLI 從 Package、lease/result identity 與不可變 machine evidence 計算。Technical Amendments 先 materialize 為 effective contract，才能執行或驗證。Final commit 包含 Result 與 Project Graph，而該 commit 的 ID 由後續 event 與結案報告記錄，避免 Result 自我引用。

Controlled runner 以獨立的暫存 Git index 記錄工作樹的 `content_tree`，不改動使用者的 staging 狀態。結案必須與最後驗證的內容一致，僅允許該 run 的 Result 與 Project Graph 在驗證後更新；Spec／Plan 變更必須在最後驗證前完成。Maintenance／documentation 的未提交內容也必須完整對應此快照。舊 evidence 缺少 `content_tree`，或本機快照 Git objects 已不可用時，必須重跑 checks，不補寫既有證據。

## 契約與 JSON 資料

Python 驗證函式是唯一契約規則來源，不再維護手寫 JSON Schema。Package、Result、Project Graph 與 Agent Result 仍以 JSON 保存與交接；Spec／Plan 維持 Markdown。核准摘要與其他顯示 view 從同一份已驗證資料衍生，不另定規則，也不修改待核准內容。

- `cogito_contracts.py`：Package、Amendment、check、Agent Result、Project Policy；Gate 與 runner 共用。
- `cogito_project_graph.py`：Project Graph 驗證及衍生圖。
- `cogito_result_contract.py`、`cogito_evidence_contract.py`：Result 與 evidence 的純資料驗證；Git／event history 綁定另外由 Gate 驗證。
- `cogito_projection.py`：Run state 由事件重建，不另讀取外部 Run Schema。

驗證不做型別轉換、不補欄位、不排序、不移除擴充資料，因此不改既有 JSON 與 hash。保留既有 optional defaults、一般 artifacts 的擴充欄位、簡化 Graph metadata，以及 Result review 可省略 `outcome` 的行為；Amendment 與 evidence 繼續拒絕未知欄位。錯誤型別、非法 ID／路徑、無法執行的 check 定義改為提早回報 `CogitoError`。舊資料若含這些錯誤會被拒絕，不會自動改寫已核准文件；應修正草稿並重新核准，或依既有 correction／blocked 流程處理。

已移除的六份 `schemas/*.schema.json` 可由 Git 歷史取回；外部工具若曾直接依賴它們，需改用 Python contract。方案 A 不提供 Schema generator；若未來有明確需求，再從單一可描述的 Python 模型衍生，不能從任意驗證函式猜測生成。

執行回歸測試：`python3 -m unittest discover -s cogito/tests -v`。測試涵蓋非法輸入、相容資料與 hash、CLI／Gate 邊界及端到端流程。

維護時先執行 runtime/unit tests，再執行 skill validation 與 behavioral evals。狀態轉移的正確性應由程式測試證明，不以文字斷言代替。
