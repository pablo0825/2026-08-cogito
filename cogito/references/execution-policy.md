# Execution Policy

## 派發與隔離

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 仍可依序完成。只有 Coordinator 可串行整合到固定 delivery branch。

Implementer 完成後，由不同 Agent 進行獨立 review。Gate 逐 task 比對 Implementer task lease 的 `agent_id`、Reviewer Result 的 `reviewed_implementer` 與不同的 reviewer `agent_id`，由已登錄 Result 推導審查完成情況，不接受 Agent 回報的 `independent: true`，也不在 Package 預先綁定 Agent 身分。Coordinator 必須指派實際不同的 Agent，並維持穩定且唯一的 ID；Gate 的 ID 比對不提供外部身分驗證。Reviewer 可建議核准、提出 Package 內修正或升級風險，但不得移除 human predicate；最終 review verdict 由 Gate 計算。Maintenance 只有在 Mini Package 的低風險宣告已有足夠證據並經核准、且 Gate 的檢查通過時可豁免；語意判斷與機械檢查的分工見 [Package Authoring](package-authoring.md#package-核准後)。

## 自動修正

Coordinator 依 Package 的 `stop_conditions` 與執行證據判讀是否應停止。這些條件是凍結的政策文字，Gate 不會自動求值或依 `outcome` 轉移狀態；停止派工、登錄 `block`、取消授權與 Human Gate 的處理依 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash；commit 加上 `Cogito-Amendment: <ID>` trailer。

Amendment 只能單調增加或加強工作，不能刪除/降級 required check、擴張路徑、要求 Package policy snapshot 未核准的環境變數，或改變產品契約。超出邊界時依 [Replanning](replanning.md) 建立重新規劃單，先限制全體執行、保存現場，再提出新的核准契約與 successor 承接方案。

新增任務以 `depends_on` 指定前置任務，可引用 base Package、先前 Amendment 或同批新增的任務。Gate 在追加事件前合併完整任務圖，拒絕未知節點、自我依賴與循環；effective contract 的 edges 會包含這些依賴，原始文件與 hash 不變。追加不能修改既有任務依賴或新增跨 Slice 的依賴關係；沿用已核准跨 Slice 關係時，前置任務必須已 `integrated`，避免修正流程等待自身完成後才能進行的整合。

## 驗證、審查與整合

- 所有正式 checks 由 controlled runner 以 argv array 執行，不預設 shell；cwd 限於 worktree，套用 timeout、輸出上限、redaction 與 env allowlist。
- `fetch_allowed` 是 Coordinator 應遵守的授權政策；runner 沒有網路隔離機制，設為 false 不會阻止 check 程序連網。需要網路限制時，由執行環境提供並驗證。
- stdout／stderr 關閉只代表輸出結束，runner 仍等待直接子程序正常退出或原本的 timeout，不因 EOF 提前終止程序。正常完成時保留實際 exit code；超時或超量時沿用有界的 process group/tree 終止與 capture 清理。
- Gate 先將 immutable base Package 與有序 append-only Amendments materialize 為 effective contract 快照；runner 在 check 前後各建立 worktree snapshot，兩者不同時該次 check 失敗。evidence 綁定前後 snapshot hash、effective contract hash、HEAD/tree 與 check definition，並在發布前及 Gate 讀取後通過同一個 Python Evidence Contract。Evidence 以檔案系統 exclusive-create 語意發布新的內容尋址檔案，不得原地覆寫；不支援安全發布時 fail closed，任何綁定改變使舊 evidence 失效。
- 內容快照複製 Git index 時，從同一個開啟的檔案取得內容與時間戳，保留時間戳於可寫的暫存副本，讓 Git 仍能重新檢查同秒、同長度的檔案修改。只更新暫存 index，不改動使用者 index 的內容、修改時間或權限。
- 升級前產生且缺少目前 Evidence Contract 欄位的 evidence 不得補寫或遷移，必須由 controlled runner 重跑。
- Controlled runner 不把完整 stdout/stderr 寫入暫存檔；每個 stream 只保留固定大小的 head/tail 診斷資料。兩者合計超過 Package policy snapshot 的 `max_check_output_bytes` 時，runner 嘗試終止受控 process group/tree、在固定期限後關閉 capture pipes，記錄 `output_limit_exceeded: true` 並判定失敗。平台限制導致只能終止 direct child 時另記錄 `termination_degraded: true`；不得把該次執行當成通過 evidence。缺少 Package 欄位時使用 10 MiB 相容預設值，但舊 evidence 若沒有實際上限欄位必須重跑。
- 開發 correction 最多三輪，review/fix 最多三輪，transient retry 最多兩次；人工驗收修正另外使用同一 run 累計三輪額度，每次 start 計次，分批回饋也不重設。所有計數器不得因 resume 或換 Agent 重設。
- Controlled check 重送使用同一 action_id 與相同輸入；同 ID 不得改 check、worktree 或執行契約。已發布 evidence 可在事件追加失敗後補登錄。若 attempt 已開始但沒有完整 evidence，結果視為未知，先確認程序與外部副作用再處理，不以自動重跑假裝恢復成功。
- 每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。所有 Slice 整合完成後，在最新 delivery branch 重跑 post-integration checks；失敗共用 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

整合 Gate 除了檢查 source heads 與祖先關係，也比對前一 delivery HEAD 到 integration commit 的實際差異，拒絕超出 Package `approved_paths` 的產品檔案。此範圍包含合法 Technical Amendment 的修正，不另外縮限成原 task 路徑聯集。路徑以 NUL 分隔並將 rename 視為原路徑刪除與新路徑新增，檢查不改動 index。

準備階段依 [Stage Commits](stage-commits.md) 分別保存已確認摘要、Boundary 與已核准 Package。這些 commits 在 Start Gate 前完成；Maintenance 的單一交付 commit 從 Start Gate HEAD 起算。

核准後需隨合法 commit 保存的控制文件只按精確路徑例外處理：本 run 的凍結 Package 必須內容相符，整合時的 Project Graph 必須符合核准 hash；Package 指定的 Spec／Plan 可依既有政策在最後驗證前更新；source registry 中 `adopted`／`updated` 的來源若依賴控制文件例外提交，必須符合凍結的原始 bytes hash，已在 `approved_paths` 的來源則可按核准範圍更新。其他文件不能因位於 `docs/` 就取得例外。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整進入 `awaiting-human` 門閥。人工退回可修正後再次回到此門閥；人工來源 RP 的 successor 即使沒有這些 predicate，也須重新人工驗收。

人工退回使用專用分類、修正、驗證與審查階段，詳見 [Human Acceptance](human-acceptance.md)。局部且影響明確才可原任務修正；操作流程改變、較大邏輯調整或修正中影響擴大轉 RP。混合回饋預設整批走 RP，只有使用者明確要求分批才拆開。每輪使用新的 Amendment／task，重跑正式 post-integration checks 及獨立 review，包含 Maintenance。未表明驗收完成時先修再等待；只有本批明確授權「其餘接受、修好即可」且內容／證據相符才可進 finalizing。第三輪仍未通過就停止並回報失敗分析，不能以新回饋或恢復重設額度。

## Finalizing

以一個 final commit 原子保存 Result、Project Graph 最終 disposition、清除 `active_run_id` 及當時已知的 commit/amendment 摘要。只有該 run 的 canonical Result 與 Project Graph 可以不同於最後驗證的 `content_tree`；必要 Spec/Plan 更新必須先完成再執行最後驗證。Feature／Change／Correction 的 final commit 也只能改這兩份結案紀錄。Maintenance／documentation 可提交已驗證的工作樹內容，但不能夾帶驗證後的修改或漏交檔案。缺少 `content_tree` 或其 Git object 時必須重跑 checks，不改寫既有 evidence。Result 不能內嵌包含自身的 final commit ID；commit 成功後，Gate 將實際 ID 追加到 event history 並用於結案報告，然後才能 `accepted`。失敗不可先報結案，應進入既有 blocked／修正流程。

所有 Package kind 結案時都再次檢查 Start Gate HEAD 到 final commit 的完整交付範圍，套用上述精確控制文件規則，再驗證 Result／Project Graph 結案內容。已通過 integration、post checks 或符合 verified content tree，都不能取代核准範圍檢查。

Maintenance 的 `single_commit` 指從 Start Gate HEAD 到 final commit 只有一個新 commit。實作與 checks 在目前 checkout 的 working-tree snapshot 上完成，Agent Result 可使用相同 base/head 並以實際 dirty/untracked path 回報；integration milestone 記錄該 Start HEAD 作為尚未提交的整合檢查點。最後才把產品變更、Result 與 Project Graph 一次提交。不得先提交產品變更再另做 metadata commit。

Maintenance Agent Result 的 `changed_paths` 必須完整列出 staged、unstaged 與 untracked 的產品路徑，不能因 base/head 相同或內容已 staged 而省略；rename 按原路徑刪除與新路徑新增一起檢查。Gate 讀取 staging 狀態但不改動 index。結案另外比對 Start HEAD 到 final commit 的全部差異，除上述精確控制文件例外外，都必須在核准路徑內；通過 checks 或與 verified content tree 相同不代表可以擴張範圍。

Maintenance 的 technical correction、review-fix 與 post-integration correction 也維持此規則：completion 命令的 `--commit-id` 使用不變的 Start Gate HEAD，Gate 記錄修正工作樹的 `content_tree` 與 `completion_mode: working-tree`，不要求先建立修正 commit。新增任務仍須完成 lease／Implementer Result；完成後依原流程重跑 controlled checks 與適用的獨立審查，快照本身不代表驗證通過。Result 的對應 amendment 使用 `{id, base_commit, content_tree}`，三者必須與 completion event 一致；不填尚未存在的 final commit ID。唯一 final commit 必須以 Start HEAD 為唯一 parent，並帶齊各 amendment 的 `Cogito-Amendment: <ID>` trailer。Gate 驗證結案後，僅在衍生結案報告補上這些 amendment 的實際 final commit ID，不改寫 Result。其他 kind 仍使用原本先建立修正 commit 的流程。
