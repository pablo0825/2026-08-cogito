# Execution Policy

## 派發與隔離

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 仍可依序完成。只有 Coordinator 可串行整合到固定 delivery branch。

Implementer 完成後，由不同 Agent 進行獨立 review。獨立性逐 Slice 由 Gate 比對 implement/review lease 與 Agent Result 的穩定 `agent_id` 推導，不接受 Agent 回報的 `independent: true`，也不在 Package 預先綁定 Agent 身分。Reviewer 可建議核准、提出 Package 內修正或升級風險，但不得移除 human predicate；最終 review verdict 由 Gate 計算。Maintenance 只有在 Mini Package 的客觀低風險條件全部成立時可豁免。

## 自動修正

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash；commit 加上 `Cogito-Amendment: <ID>` trailer。

Amendment 只能單調增加或加強工作，不能刪除/降級 required check、擴張路徑或改變產品契約。超出邊界就 `blocked` 並回到需要人類決策的流程。

## 驗證、審查與整合

- 所有正式 checks 由 controlled runner 以 argv array 執行，不預設 shell；cwd 限於 worktree，套用 timeout、輸出上限、redaction 與 env allowlist。
- Gate 先將 immutable base Package 與有序 append-only Amendments materialize 為 effective contract 快照；evidence 綁定該快照 hash、HEAD/tree 與 check definition。Evidence 以新的內容尋址檔案追加，不得原地覆寫；任何綁定改變使舊 evidence 失效。
- correction 最多三輪，review/fix 最多三輪，transient retry 最多兩次；計數器不得因 resume 或換 Agent 重設。
- 每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。所有 Slice 整合完成後，在最新 delivery branch 重跑 post-integration checks；失敗共用 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整成唯一一次 `awaiting-human` 門閥。

## Finalizing

以一個 final commit 原子保存 Result、Project Graph 最終 disposition、清除 `active_run_id`、當時已知的 commit/amendment 摘要及必要 Spec/Plan 合法更新。Result 不能內嵌包含自身的 final commit ID；commit 成功後，Gate 將實際 ID 追加到 event history 並用於結案報告，然後才能 `accepted`。失敗必須 `blocked`，不可先報結案。

Maintenance 的 `single_commit` 指從 Start Gate HEAD 到 final commit 只有一個新 commit。實作與 checks 在目前 checkout 的 working-tree snapshot 上完成，Agent Result 可使用相同 base/head 並以實際 dirty/untracked path 回報；integration milestone 記錄該 Start HEAD 作為尚未提交的整合檢查點。最後才把產品變更、Result 與 Project Graph 一次提交。不得先提交產品變更再另做 metadata commit。
