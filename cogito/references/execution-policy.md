# Execution Policy

## 派發與隔離

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 仍可依序完成。只有 Coordinator 可串行整合到固定 delivery branch。

Implementer 完成後，由不同 Agent 進行獨立 review。獨立性逐 Slice 由 Gate 比對 implement/review lease 與 Agent Result 的穩定 `agent_id` 推導，不接受 Agent 回報的 `independent: true`，也不在 Package 預先綁定 Agent 身分。Reviewer 可建議核准、提出 Package 內修正或升級風險，但不得移除 human predicate；最終 review verdict 由 Gate 計算。Maintenance 只有在 Mini Package 的客觀低風險條件全部成立時可豁免。

## 自動修正

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash；commit 加上 `Cogito-Amendment: <ID>` trailer。

Amendment 只能單調增加或加強工作，不能刪除/降級 required check、擴張路徑、要求 Package policy snapshot 未核准的環境變數，或改變產品契約。超出邊界就 `blocked` 並回到需要人類決策的流程。

## 驗證、審查與整合

- 所有正式 checks 由 controlled runner 以 argv array 執行，不預設 shell；cwd 限於 worktree，套用 timeout、輸出上限、redaction 與 env allowlist。
- stdout／stderr 關閉只代表輸出結束，runner 仍等待直接子程序正常退出或原本的 timeout，不因 EOF 提前終止程序。正常完成時保留實際 exit code；超時或超量時沿用有界的 process group/tree 終止與 capture 清理。
- Gate 先將 immutable base Package 與有序 append-only Amendments materialize 為 effective contract 快照；runner 在 check 前後各建立 worktree snapshot，兩者不同時該次 check 失敗。evidence 綁定前後 snapshot hash、effective contract hash、HEAD/tree 與 check definition，並在發布前及 Gate 讀取後通過同一個 Python Evidence Contract。Evidence 以檔案系統 exclusive-create 語意發布新的內容尋址檔案，不得原地覆寫；不支援安全發布時 fail closed，任何綁定改變使舊 evidence 失效。
- 升級前產生且缺少目前 Evidence Contract 欄位的 evidence 不得補寫或遷移，必須由 controlled runner 重跑。
- Controlled runner 不把完整 stdout/stderr 寫入暫存檔；每個 stream 只保留固定大小的 head/tail 診斷資料。兩者合計超過 Package policy snapshot 的 `max_check_output_bytes` 時，runner 嘗試終止受控 process group/tree、在固定期限後關閉 capture pipes，記錄 `output_limit_exceeded: true` 並判定失敗。平台限制導致只能終止 direct child 時另記錄 `termination_degraded: true`；不得把該次執行當成通過 evidence。缺少 Package 欄位時使用 10 MiB 相容預設值，但舊 evidence 若沒有實際上限欄位必須重跑。
- correction 最多三輪，review/fix 最多三輪，transient retry 最多兩次；計數器不得因 resume 或換 Agent 重設。
- Controlled check 重送使用同一 action_id 與相同輸入；同 ID 不得改 check、worktree 或執行契約。已發布 evidence 可在事件追加失敗後補登錄。若 attempt 已開始但沒有完整 evidence，結果視為未知，先確認程序與外部副作用再處理，不以自動重跑假裝恢復成功。
- 每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。所有 Slice 整合完成後，在最新 delivery branch 重跑 post-integration checks；失敗共用 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整成唯一一次 `awaiting-human` 門閥。

## Finalizing

以一個 final commit 原子保存 Result、Project Graph 最終 disposition、清除 `active_run_id` 及當時已知的 commit/amendment 摘要。只有該 run 的 canonical Result 與 Project Graph 可以不同於最後驗證的 `content_tree`；必要 Spec/Plan 更新必須先完成再執行最後驗證。Feature／Change／Correction 的 final commit 也只能改這兩份結案紀錄。Maintenance／documentation 可提交已驗證的工作樹內容，但不能夾帶驗證後的修改或漏交檔案。缺少 `content_tree` 或其 Git object 時必須重跑 checks，不改寫既有 evidence。Result 不能內嵌包含自身的 final commit ID；commit 成功後，Gate 將實際 ID 追加到 event history 並用於結案報告，然後才能 `accepted`。失敗不可先報結案，應進入既有 blocked／修正流程。

Maintenance 的 `single_commit` 指從 Start Gate HEAD 到 final commit 只有一個新 commit。實作與 checks 在目前 checkout 的 working-tree snapshot 上完成，Agent Result 可使用相同 base/head 並以實際 dirty/untracked path 回報；integration milestone 記錄該 Start HEAD 作為尚未提交的整合檢查點。最後才把產品變更、Result 與 Project Graph 一次提交。不得先提交產品變更再另做 metadata commit。
