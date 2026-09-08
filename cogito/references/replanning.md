# 重新規劃與承接

本流程處理 Package 已核准後，公開 API、資料模型、Acceptance、Boundary 或核准範圍需要變更，且已超出 Technical Amendment 的情況。不可改寫原 Package，也不可只因使用者說「同意改 API」就按新契約實作。

Package 尚未核准的修訂使用 [Planning Revisions](planning-revisions.md)：在同一 run 保留多輪規劃，不需建立 RP 或 successor。若已存在 RP，其 successor 在核准前仍可使用 planning 修訂；完成 planning 獨立覆核後，必須將最新候選重新送入 RP propose／review／approve。RP status 的 `proposal_stale` 表示舊提案已不對應目前候選，舊 RP 提案不能核准；普通 approve 也不能繞過 RP。

## 先確認承接方式

先依已核准 Package 的 `task_delivery` 選擇適用規則，再準備 successor 與 RP 提案。新的 Feature／Change／Correction 使用 Atomic Task；不要先規劃成果移植，最後才檢查是否支援。

| Package | `work` 提案與來源成果 | 原驗證證據 |
|---|---|---|
| Atomic | 每筆 source task 都列 `omit`、target 為 null；已整合內容留在 delivery baseline，未整合內容保留在 source，後續工作另建新 Task | 不跨 run 採用 |
| 受支援的非 Atomic／既有凍結交接 | 依下文選擇 `retain`、`adapt` 或 `omit` | 僅符合採認條件才可 `reuse`，其他情況 `rerun` |

Atomic 開發 Package 的 successor 仍須保留 `task_delivery: "atomic"`。本版不把先於 lease 建立的 RP carryover commits 當成新 Task 的獨立交付，也不跨 run 採用 atomic Task 的舊 evidence。核准前的 RP proposal 會拒絕這類承接；將未整合來源標記 `omit`、保留來源快照，另在 successor 規劃與執行新的 Task。已在保存 delivery baseline 的內容仍是 successor 起點，不需重做已整合行為。`omit` 不刪除 source 成果。舊的非 atomic Package／已凍結交接與事件維持原協定，不改寫舊 hash 或 evidence。

## 核准與流程單位

每次重新規劃建立獨立 `RP-*` 單，保存在 `.cogito/replans/<ID>/events.jsonl`。它連結原 run 與全新 successor run。事件歷史包含停止快照、提案各版本、獨立覆核、明確核准、逐項承接與交接完成紀錄；`state.json` 只是可重建快取。

階段為 `stopping → analyzing → reviewing → awaiting-approval → ready-for-handoff → handing-off → completed`。拒絕提案進入 `awaiting-decision`。放棄方案先進 `resolving-decision`，完成已選定的原流程處置後才進 `abandoned`；中斷時不提前解除執行限制。

原 run 在停止期間保持 blocked；新 Package 核准時尚不轉移正式 Project Graph，也不允許 successor 派工。交接的 durable intent 落盤後才開始 Graph／worktree 操作；核對完成後原 run 進 `superseded`，新流程解除限制。accepted 來源始終保持 accepted，其事件與 Result 均不改寫。

## 停止與保存

Worker 的 executor 身分在[正常派工](execution-policy.md#派發與隔離)時登錄。契約變更後：

1. 發現契約變更，使用 `begin`。它先寫入執行限制，再登錄 block 與最長 60 秒的停止期限；不等待 60 秒才阻止新派工。
2. Coordinator 透過實際 executor 工具要求 Worker 停止開發，只保存與交接。期限內不新增功能、測試或整合；逾時使用 executor 的中斷操作。OS registry 只會對身分仍吻合的獨立程序群組執行逾時中斷，不誤殺共用群組或重用 PID。
3. 外部 Agent 的停止須取得真正 executor 回報，再提交 `executor-receipt`。receipt 包含 `provider`、`control_tool`、`event_id`、`handle`、`status` 與 `raw_response`；adapter 回應須明確對應同一 handle 與 completed/interrupted 狀態。Coordinator 必須保留工具證據，不能自行填寫停止結果。
4. 使用 `stop` 確認執行者停止，保存各 worktree 的 HEAD、branch、index tree、content tree、原契約 hash、event hash 與 Graph。連續捕捉不一致，或執行者未停妥，保持 stopping。

外部 receipt 是 executor 的停止聲明，由 Coordinator 確認工具來源；CLI 的欄位驗證不提供 provider 身分認證。未知 handle、無回報、OS inspection 無權限或程序身分不一致，都不能宣稱停妥。begin 會拒絕尚未登錄 executor 的 active Worker；Coordinator 先停止派工並取得真正 handle，補登錄後再開始。不能編造 PID 或修改 registry 清除問題。

Controlled check 的 subprocess 由 runner 登錄；啟動與 replan fence 使用同一專案鎖，避免「剛停止卻又啟動」。已在執行的 check 可以在保存期限內結束，但 fence 後不得再將它加入可用 evidence ledger。原始 artifact 仍保留，不會成為新契約的驗收證據。長時間執行的 runner 會在停止期限到達時終止自己的受管程序。

停止快照將產品內容、原 Worker 與執行紀錄分開驗證。主目錄未忽略 `.cogito/` 時，正常事件與草稿更新仍可繼續；缺少目前 runtime metadata 或使用未知版本的快照會拒絕推進。分類邊界、恢復步驟與限制見 [RP Snapshots](replan-snapshots.md)。

若停止後更新專案內 Cogito，使用 [RP 工具接軌](replan-toolchain.md) 的獨立提案、覆核及核准；不能把工具差異默默納入產品 Package，也不能直接忽略工具目錄或 Git 基線變動。

## 重新釐清與提案

功能、操作方式、Acceptance 或未決定的產品行為改變時，先向使用者釐清。原需求不變時，可先分析新 API／Boundary／Spec／Plan，再提出完整方案。語意判斷屬 Coordinator 與獨立 Reviewer 的責任，Gate 不解析任意自然語言就宣稱 API 相容。

建立新的 run，使用原有 Shared Understanding、Boundary、prepare-package Gates 準備 successor。需要重新確認理解的變更仍取得使用者確認；原需求沿用則明確引用原已確認內容，不把新 run 建立視為實作授權。

提案 JSON 包含：

- `author_id`：方案作者。
- `package`：已通過新 run prepare-package 的完整候選 Package。
- `differences`：`requirements`、`api`、`boundary`、`acceptance`、`cost`、`revalidation`，每項說明具體新舊差異；沒有變更也明寫原因。
- `work`：每一筆 source task 恰好出現一次，包含 `source_task_id`、`target_task_id`、`disposition`、`validation` 與 `reason`。

Atomic 提案依前述規則使用 `omit`。非 Atomic 承接的 `disposition` 為 retain（保留）、adapt（承接後修改）、omit（新方案不採用但保留原成果）。`validation` 為 reuse 或 rerun；adapt 一律 rerun。omit 的 target 必須為 null，不能沿用證據。新 run 可有額外工作，所有承接 target 必須存在且不得重複。

Gate 在提案階段使用暫存 Git index 預演每項承接，將預期內容樹綁入 proposal hash；無法乾淨移植時先修改方案，不等使用者核准後才發現固定衝突。

successor 使用新的 Slice ID，`lineage` 明確指向原 Slice。不得直接重用原 ID 或覆寫 `introduced_by`。初始 baseline 綁定保存的 delivery HEAD；原 worktree 保持原樣。更新 Spec／Plan 時使用新文件路徑，避免改動仍被原契約引用的文件。

非 Atomic 成果沿用目前採用以下機械採認條件：原 task 已 reviewed/integrated、有完整的原受控 evidence 與獨立 review、原與目標完整 content tree 相同，且相關 task、Spec／Plan、checks、policy、Shared Understanding 等均未變。已有 amendments、相依 task、內容或相關契約改動時要求重驗。同一個沿用 worktree 不混入需要修改或新增的 task；需要混用時先拆 Slice 或整組重驗。此限制可以減少無法證明不受影響時的錯誤沿用；程式仍可承接。

## 獨立覆核與使用者核准

`review` 必須由不同於 author 的 Reviewer 提交，綁定當前 `proposal_hash`。`assessment` 必須具體說明 impact、reuse、revalidation、handoff；findings 清空代表已解決，不得為通過 Gate 刪除尚未解決的問題。Reviewer ID 由 Coordinator 對應到真正不同的 Agent。

核准前向使用者呈現：原與新 API、資料格式、Boundary、Acceptance、額外成本、每項保留／修改／不採用決策，以及需要重跑和打算沿用的測試／審查與依據。使用者核准的是這份精確提案，`approve --proposal-hash` 將 hash 綁定新 Package 與交接清單。提案修訂會使前版覆核失效；來源快照或候選 Package 漂移也不能沿用原核准。

不核准使用 `reject`，保持暫停並詢問下一步。使用者明確選擇後才使用 `abandon` 的 keep-paused、resume-source 或 cancel-source。resume-source 先保存舊 executor generation、釋放停止的 active lease 再恢復；cancel-source 轉交獨立 DP，以可恢復步驟保存成果、取消及釋放 Graph；後續移除／保留由使用者另審方案。

核准後撤回、部分 handoff 後恢復原方案，以及原變更要求撤回後的人工來源恢復，依 [成果處置](dispositions.md) 建立關聯 DP。它保存 source／successor 與已轉移成果，原 RP 轉為 `disposition`，不能繼續舊 handoff。普通 resume-source 在記錄决定前先檢查可行性；否決提案不會自行撤回人工回饋。

## 承接與中斷恢復

`handoff` 將核准的來源 task 路徑內容移入專用的新 branch/worktree，以新 commit 保留來自原 run 的來源說明。未提交內容來自已保存的 Git content tree，原 index、檔案與 commits 不改寫；omit 也不刪原成果。已整合內容自然包含在新 baseline，仍按影響分析決定是否重驗。

新的 RP proposal 在獨立審查前保存不可變的 `StartArtifactManifest`，將 successor 的精確文件與 Git tree 綁定到 proposal、review 與 approval。handoff 的 Start Gate 只驗證同一份 artifact，不建立驗證用 worktree 或 checkpoint。artifact 不符即停止；完整綁定與驗證模型見 [RP Snapshots](replan-snapshots.md#start-artifact-與交接驗證)。

所有 RP proposal 都必須包含 `start_artifact` 與 `start_artifact_hash`。缺少 immutable Start artifact 的舊 proposal 不再受支援，也不能投影、核准或執行 handoff。

每個移植先記錄 before／after tree 與 commit，再寫入新 worktree，最後追加完成 receipt。重試只接受明確的未執行／已執行狀態；衝突或未知內容保持 handing-off 並回報，不覆寫外部改動。Project Graph 也比對原始／目標內容，不能以直接清 active_run_id 來修復。

新任務的首個 lease 只允許精確符合已記錄承接 HEAD／tree 的例外起點，其他任務仍套用既有起點規則。符合 reuse 的 task 取得專用採認 receipt，引用原 evidence 與 reviewer；不改寫原 Result/evidence 的 run ID，不偽造新測試執行。`advance-adoptions` 可將完成採認且沒有其他可派工作的 wave 送入整合。新流程最後仍須執行新的 post-integration controlled checks 與既有結案 Gates。

中斷後先 `status`，再沿用原 action ID 與參數重送 `begin`、`approve`、`handoff` 或 `abandon`。已落盤的核准不要求重複核准；提案內容改變則重新取得核准。來源、Graph 或承接 worktree 不符時停止並詢問，不猜測狀態、不刪 marker、不改事件。

若 `handoff-started` 已落盤、successor 尚在 `start-gate`，且修正 Gate 本身需要新的 tool-only commit，使用 [RP 工具接軌](replan-toolchain.md) 的 handoff repair。它只適用於尚無 transfer plan／receipt、source 尚未 superseded 的邊界；修復核准後仍沿用原 handoff action ID。不得重新發布 Package、重寫產品核准或製造重複 receipt。

## CLI

以下 `<...>` 必須替換為實際值；提案與 receipt 使用 JSON 檔案。一般 run Gate 仍使用原有介面。

```sh
python3 cogito/scripts/cogito_gate.py --repo <repo> replan register-executor --run-id <old-run> --agent-id <worker> --handle <executor-handle>
python3 cogito/scripts/cogito_gate.py --repo <repo> replan begin --replan-id RP-001 --source-run <old-run> --successor-run <new-run> --reason '需要修改共用 API' --action-id rp-begin
python3 cogito/scripts/cogito_gate.py --repo <repo> replan executor-receipt --run-id <old-run> --agent-id <worker> --handle <executor-handle> --input <receipt.json>
python3 cogito/scripts/cogito_gate.py --repo <repo> replan stop --replan-id RP-001 --action-id rp-stop
python3 cogito/scripts/cogito_gate.py --repo <repo> replan propose --replan-id RP-001 --input <proposal.json> --action-id rp-propose-1
python3 cogito/scripts/cogito_gate.py --repo <repo> replan review --replan-id RP-001 --input <review.json> --action-id rp-review-1
python3 cogito/scripts/cogito_gate.py --repo <repo> replan approve --replan-id RP-001 --proposal-hash <hash> --action-id rp-approve-1
python3 cogito/scripts/cogito_gate.py --repo <repo> replan handoff --replan-id RP-001 --action-id rp-handoff
python3 cogito/scripts/cogito_gate.py --repo <repo> replan status --replan-id RP-001
```

成果移植支援具專用 Slice worktree 的非 Atomic Feature／Change／Correction 承接。Mini Package 如有未提交的 delivery 修改，不能略過 Start Gate；無法建立可核准的精確 artifact 時維持阻塞，不自動清理使用者工作目錄。

## 階段提交相容性

RP successor 保留 frozen delivery 與既有 handoff 協定；在有效 RP 內初始化 successor 時，不啟用一般 run 的階段提交。這項相容性保留撤回後恢復 source 的能力，不移動停止時的 delivery HEAD。一般 run 與同一 run 的規劃修訂依 [Stage Commits](stage-commits.md) 保存各階段。
