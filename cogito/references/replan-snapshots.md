# RP 產品快照與執行紀錄

RP 的停止快照同時保存產品、原 Worker 與執行證據，但不使用同一種比較規則。主目錄尚未忽略 `.cogito/` 時，正常追加 RP 事件、重建快取或準備 successor 草稿，不應被視為產品變更。

## 分類與驗證

| 內容 | 驗證方式 |
|---|---|
| delivery 產品與未列入例外的檔案 | 比較停止時與目前的 index／content trees；仍只放行既有規則允許的新控制文件 |
| 專案內 Cogito 工具 | 新快照另存工具 HEAD／index／content manifests；更新需獨立工具接軌核准，沒有目錄層級豁免 |
| 原 Spec／Plan、Shared Understanding 與 source registry 文件 | 凍結文件路徑優先於 runtime 分類，不能利用草稿目錄放寬保護 |
| 原 Worker | 完整 HEAD、branch、index tree、content tree 不變；delivery 中若有其 gitlink，也必須符合原 HEAD |
| 原 run 事件 | hash chain 與停止時 event hash；唯一既有例外是本 RP 的 `run-superseded` 接續 |
| 本 RP／successor 事件 | 合法事件投影、完整 hash chain，以及已保存的原始事件前綴；重新計算整條鏈不能取代 append-only |
| 本 RP、原 run、successor 的 `state.json` | 由合法事件重建的 disposable cache，不以舊快照的快取內容限制流程 |
| 本 RP／successor 的 `drafts/` | 允許正常新增或修訂 regular files；草稿不是核准證據，不豁免被原契約引用的凍結文件 |
| 原 run evidence、check-actions、execution-registry 等檔案 | 新快照另外保存檔案 hash／mode，包含 Git 已忽略的檔案；原始樹內的檔案也逐一比對實際 bytes 與 Git mode |
| 指定同步鎖 | 只有本次三份事件的 `.lock` 及 project-mutation.lock 可按同步檔處理，而且必須是空的 regular file |
| successor Worker | 只有核准 Package 的精確路徑，且 branch／HEAD／trees 符合起始基線、已記錄移植中間狀態或完成 receipt，才可排除 delivery 的 gitlink 差異 |
| 其他 `.cogito/` 內容 | 沒有整個目錄的例外；仍比較停止快照，未知差異拒絕 |

runtime 檔案不得透過 symlink 或 gitlink 冒充事件、快取、鎖或草稿。Git index 與工作內容分別驗證；只修復工作目錄、卻把變造事件或證據留在 index，仍不能通過。

## 快照格式

新 `replan-stopped.snapshot.runtime` 使用 `version: 1`，包含：

- `product_trees`：依上述規則分離後的產品 index／content tree。
- `logs`：事件前綴的 byte length、SHA-256、sequence 與最後 event hash。
- `source_files`：原 run 不可變 artifact 的 SHA-256 與 mode。

原 `delivery.index_tree`、`delivery.content_tree` 與 Worker bindings 均保留，供移植及完整證據追溯。產品樹必須能由原始樹重新推導，不能以新欄位覆蓋或取代來源證據。後續 RP 事件另外保存 `runtime_logs`，使提案之後的 successor 歷史也有前綴錨定。

若停止後才以 Git local exclude 忽略 runtime，已保存的原 run artifact 與 Worker gitlink 仍須通過各自驗證，不能因它們在新 Git tree 中消失就跳過保護。修改產品 `.gitignore` 本身仍是一般 delivery 差異，不能把它視為自動獲准的變更。

缺少 `runtime`、版本未知、缺少來源、內容不一致或不能建立完整性證明的快照一律拒絕推進。

## Start artifact 與交接驗證

新的 RP proposal 在獨立審查前建立 `StartArtifactManifest`：以保存的 delivery commit/tree 為 baseline，將 successor candidate snapshot 內的 Package、Project Graph、Spec／Plan、Shared Understanding 與 source registry 位元組形成精確的 Git tree，並以 content-addressed create-only ref 保持 objects 可達。proposal 綁 manifest hash，review 綁 proposal hash，approval 再綁同一個 manifest。handoff 的 successor Start Gate 只讀取並重算這些 commit/tree/blob、核對已發布的 live Package／Graph、Policy、Workflow、tool 與 verifier binding，再以 event-tip CAS 追加既有 `start-gate-passed`；不建立 worktree、不複製或 chmod 控制文件，也不寫 validation checkpoint。停止快照內既有且未變的 dirty 檔案不會進入 artifact tree。一般 Start Gate 仍使用原 checkout 規則。

## 已卡住的 RP 如何續接

1. 更新專案實際使用的 Gate 程式後，先執行 `replan status`，確認原 RP 的狀態與下一步。若更新改變專案內 `.codex/skills/cogito/` 或其提交造成 HEAD 變化，先完成 [RP 工具接軌](replan-toolchain.md)，不能直接重試或放寬基線檢查。
2. 若停在 `analyzing` 且只有合法 runtime 更新，可保留現有 successor 候選，重新執行原本失敗的 `propose`。原 action 沒有成功落盤時，可沿用相同 action ID 與輸入。經工具接軌而有效 HEAD 改變時，舊候選仍保留，但須正常建立新 planning 輪次更新 baseline、覆核候選，再提出新 RP proposal。
3. 通過後仍須正常 `review`、精確 proposal hash 的使用者 `approve`，最後執行 `handoff`。恢復比較不是新的核准。
4. 若使用者選擇暫停或恢復來源，依既有 `abandon keep-paused`／`resume-source` 流程處理；快照驗證同樣保留來源保護。

不要重新保存舊基準、刪除事件、覆寫 snapshot、直接修改 state 或取消 `_assert_source`。錯誤若仍存在，保留證據並處理實際不相符的內容。

## 範圍與驗收

此分類限定 RP 保存、比較與交接，不修改一般 controlled runner 的 evidence binding、Start Gate 或最終化規則。專案仍應配置 runtime 的 Git 忽略規則，避免意外提交執行紀錄；RP 正確性不再依賴保存前已完成這項設定。

自動化回歸涵蓋未忽略 runtime 的目前快照、正常草稿與事件、補上 local exclude、真實產品／Worker／文件／證據漂移、事件篡改、index 保護及中斷重試。人工驗收旅程以隔離專案和合成使用者決策模擬；測試通過不是實際產品的使用者核准。由人工回饋啟動的 RP successor 仍須重新進入人工驗收。

實際執行方式、觀察結果與一般 runner 的隔離條件見 [人工驗收模擬報告](../evals/reports/2026-09-03-replan-runtime-human/REPORT.md)。
