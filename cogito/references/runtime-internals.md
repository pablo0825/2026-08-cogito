# Runtime 實作與證據保護

本檔供維護 runner、Git snapshot 與 evidence 發布程式時查閱。執行 Task 的操作順序見 [Execution Policy](execution-policy.md)；一般 Agent 不需要先理解底層實作才能使用 Gate。

## 程序與輸出擷取

stdout／stderr 關閉只代表輸出結束，runner 仍等待直接子程序正常退出或原本的 timeout，不因 EOF 提前終止程序。正常完成時保留實際 exit code；超時或超量時沿用有界的 process group/tree 終止與 capture 清理。

Controlled runner 不把完整 stdout/stderr 寫入暫存檔；每個 stream 只保留固定大小的 head/tail 診斷資料。兩者合計超過 Package policy snapshot 的 `max_check_output_bytes` 時，runner 嘗試終止受控 process group/tree、在固定期限後關閉 capture pipes，記錄 `output_limit_exceeded: true` 並判定失敗。平台限制導致只能終止 direct child 時另記錄 `termination_degraded: true`；不得把該次執行當成通過 evidence。缺少 Package 欄位時使用 10 MiB 相容預設值，但舊 evidence 若沒有實際上限欄位必須重跑。

## 內容快照與證據發布

Gate 先將 immutable base Package 與有序 append-only Amendments materialize 為 effective contract 快照；runner 在 check 前後各建立 worktree snapshot，兩者不同時該次 check 失敗。evidence 綁定前後 snapshot hash、effective contract hash、HEAD/tree 與 check definition，並在發布前及 Gate 讀取後通過同一個 Python Evidence Contract。Evidence 以檔案系統 exclusive-create 語意發布新的內容尋址檔案，不得原地覆寫；不支援安全發布時 fail closed，任何綁定改變使舊 evidence 失效。

內容快照複製 Git index 時，從同一個開啟的檔案取得內容與時間戳，保留時間戳於可寫的暫存副本，讓 Git 仍能重新檢查同秒、同長度的檔案修改。只更新暫存 index，不改動使用者 index 的內容、修改時間或權限。

升級前產生且缺少目前 Evidence Contract 欄位的 evidence 不得補寫或遷移，必須由 controlled runner 重跑。

啟動前 probe 重用真實 snapshot adapter，因此會建立 Git objects 與 temporary index，但不改使用者 staging；它不產生 evidence，不能取代原 pre/post snapshots。Popen 與 registry publication 之間仍有中斷空窗，本批不新增未知結果解除機制。

`next` 的新增 Atomic 內容觀察使用臨時 object directory、原 object store 的 alternates 與 private index，取得 tree hash／變更路徑後清除自己建立的暫存區。候選分類沿用 evidence validator 的 query-only inspection；正式 closure 仍檢查完整 required set。`select_task_evidence` 與提示共用按 check＋checkout 的 latest-attempt 收集，未知 started 仍採原本全 Run 阻擋範圍。

## 契約相容性與內部資料流

驗證不做型別轉換、不補欄位、不排序、不移除擴充資料，因此不改既有 JSON 與 hash。保留既有 optional defaults、一般 artifacts 的擴充欄位、簡化 Graph metadata，以及 Result review 可省略 `outcome` 的行為；Amendment 與 evidence 繼續拒絕未知欄位。錯誤型別、非法 ID／路徑、無法執行的 check 定義改為提早回報 `CogitoError`。舊資料若含這些錯誤會被拒絕，不會自動改寫已核准文件；應修正草稿並重新核准，或依既有 correction／blocked 流程處理。

已移除的六份 `schemas/*.schema.json` 可由 Git 歷史取回；外部工具若曾直接依賴它們，需改用 Python contract。目前不提供 Schema generator；若未來有明確需求，再從單一可描述的 Python 模型衍生，不能從任意驗證函式猜測生成。

證據驗證由 Gate 一次取得同一份事件歷史與狀態快照，讀取必要的不可變 evidence，再交給純資料規則判斷；整合前與整合後階段明確指定。寫入驗證結果時會比對快照的事件版本，若歷史已變更則拒絕並要求以相同 action_id 重試。整合後驗證的 evidence 與事件使用同一個 HEAD，寫入前再次確認 HEAD 未變更。

`RunStore` 可用 keyword-only 的 `event_repository`／`git_repository` 注入依賴，省略時使用原本的檔案與 Git adapter。介面定義於 `cogito_ports.py`：事件 adapter 必須回傳已驗證的權威歷史、以相同 workflow 建立 snapshot，並在 append 時遵守 expected hash 衝突檢查；approval recovery 的 read 必須取得最新歷史。RunStore 仍管理 run 與 runner attempt 的檔案目錄，注入事件儲存不會取消這些保護。

整合決策由 `cogito_integration_rules.py` 根據已收集的狀態與事件，判定目標任務、來源 commits、前次 delivery HEAD 與下一個整合事件；`RunStore` 負責 Git 事實驗證與事件提交。純規則可直接用資料測試，Git ancestry 與 action replay 仍由整合測試保護。

Controlled runner 的 `run_check()` 收集時間、環境與前後工作樹快照，並執行程序；`cogito_runner_evidence.build_evidence()` 只用這些資料判定通過／失敗、遮罩輸出並組裝 evidence。結果判定可不建立 Git repository 或啟動程序就完成單元測試，程序終止與不可變 evidence 發布仍有獨立整合測試。

純契約入口 `validate_package_with_limits(package, workflow_limits)`、`materialize_contract_with_limits(package, amendments, workflow_limits)` 與純 projection `project_events(events, workflow)` 都明確接收設定，不自行讀檔。`RunStore` 將已載入的 workflow limits 傳入驗證、runner 與結案流程。原本的 `validate_package()`、`materialize_contract()` 及省略 workflow 的 `reduce_events()` 保留為會載入預設設定的便利入口；JSON 格式與 hash 計算不變。

`cogito_event_types.py` 描述 task update、Agent Result、check evidence 與三種 integration 事件的 payload，以 Literal 事件種類組成 `TypedGateEvent` union。Gate 產生端與 projection 消費端共用這些型別，靜態範例檢查缺欄位、非法 task status 與事件／payload 不匹配。型別只描述內部交接，不取代既有 runtime 驗證，也不改寫舊事件、擴充欄位或 hash。

## 查詢、receipt 與事件儲存

`init` 在 Git repository 的本地 `info/exclude` 補入 `/.cogito/runs/` 與 `/.cogito/worktrees/`；linked worktree 使用共用的 Git 設定位置。預設規則置於既有內容之前，保留原始內容與使用者例外的優先權，重複初始化不重複加入。不修改 `.gitignore`，也不取消追蹤已提交的檔案；`status`／`report` 不安裝這些規則。非 Git 目錄仍可使用 `init --no-stage-commits`。

Event JSONL 每一行必須是 JSON object；array、null、字串、數值或布林值會回傳含行號的結構化錯誤與 exit code `2`，不產生 traceback，不跳過該行或修補權威事件，也不改寫 state cache。

Gate event 的 `request_hash` 綁定命令名稱與原始輸入，納入 event hash；衍生 verdict 留在 payload。Evidence 重送比對完整輸入，不只比路徑；`run-check` worktree 先 resolve 再計算指紋。`.cogito/runs/<run-id>/check-actions/` 保存請求指紋與啟動時契約／check hash，並以檔案鎖串行處理同一 action。操作上的重送與未知結果判讀見 [Check 重送](execution-policy.md#check-重送)。

`next` 的新提示不追加事件或建立 action、cleanup receipt／refs、executor registry／lock；既有 state cache refresh 與流程預驗證仍保留，整個命令不是零寫入。必要候選或待處理 attempt 超過 50 項時明列範圍限制，不以截斷清單宣稱可完成。

`status` 是一般 Run 的完整 RunState 查詢；`report`、`delivery-summary`、planning history／compare、RP／DP status 等完整查詢維持既有資料。accepted 的 `next` 與 planning recover 所導向的 next 使用 `report_query`，不內嵌報告；cleanup 仍在內部驗證正式報告。Mutation receipt 的成功判讀與重送語意依 [Runtime Interface](runtime-interface.md#json-輸入與顯示)。

`slice-inventory` 從 hash-chain 驗證後的事件投影與 final commit Git blobs 讀取 Package、Result、有效 Amendments 與 Start-to-final diff；不讀取或修復 `state.json`，不建立 lock、event、草稿或其他檔案。輸出保留凍結順序與 hashes。對含既有 `controlled-check-attempt-resolved` 的 accepted history，先對帳 replacement evidence、當時 effective contract 與 Result receipt，再只從本次唯讀投影排除該非 transition 記錄；不恢復舊寫入命令或放寬其他歷史事件。對帳失敗、其他不支援事件或超過輸出上限均 fail closed；操作與替代處理見 [歷史 Slice 查詢](package-authoring.md#歷史-slice-查詢)。
