# Runtime 實作與證據保護

本檔供維護 runner、Git snapshot 與 evidence 發布程式時查閱。執行 Task 的操作順序見 [Execution Policy](execution-policy.md)；一般 Agent 不需要先理解底層實作才能使用 Gate。

## 程序與輸出擷取

stdout／stderr 關閉只代表輸出結束，runner 仍等待直接子程序正常退出或原本的 timeout，不因 EOF 提前終止程序。正常完成時保留實際 exit code；超時或超量時沿用有界的 process group/tree 終止與 capture 清理。

Controlled runner 不把完整 stdout/stderr 寫入暫存檔；每個 stream 只保留固定大小的 head/tail 診斷資料。兩者合計超過 Package policy snapshot 的 `max_check_output_bytes` 時，runner 嘗試終止受控 process group/tree、在固定期限後關閉 capture pipes，記錄 `output_limit_exceeded: true` 並判定失敗。平台限制導致只能終止 direct child 時另記錄 `termination_degraded: true`；不得把該次執行當成通過 evidence。缺少 Package 欄位時使用 10 MiB 相容預設值，但舊 evidence 若沒有實際上限欄位必須重跑。

## 內容快照與證據發布

Gate 先將 immutable base Package 與有序 append-only Amendments materialize 為 effective contract 快照；runner 在 check 前後各建立 worktree snapshot，兩者不同時該次 check 失敗。evidence 綁定前後 snapshot hash、effective contract hash、HEAD/tree 與 check definition，並在發布前及 Gate 讀取後通過同一個 Python Evidence Contract。Evidence 以檔案系統 exclusive-create 語意發布新的內容尋址檔案，不得原地覆寫；不支援安全發布時 fail closed，任何綁定改變使舊 evidence 失效。

內容快照複製 Git index 時，從同一個開啟的檔案取得內容與時間戳，保留時間戳於可寫的暫存副本，讓 Git 仍能重新檢查同秒、同長度的檔案修改。只更新暫存 index，不改動使用者 index 的內容、修改時間或權限。

升級前產生且缺少目前 Evidence Contract 欄位的 evidence 不得補寫或遷移，必須由 controlled runner 重跑。
