# Execution Policy

正常執行依 Start Gate → 派工／Task → 正式驗證 → 獨立審查 → 整合推進。首次派工先讀「Start Gate 前」「派發與隔離」及適用 Task 小節。正式 correction、review-fix 或必要路徑補列時，依 [Execution Corrections](execution-corrections.md) 處理；未完成 Task 的檢查失敗與 check 重送依本檔。其餘依 `next_action` 讀取完整對應小節及其必要引用，狀態轉移仍由 Gate 決定。共通 CLI、action ID 與停止／重送規則見 [Runtime Interface](runtime-interface.md)。

## Start Gate 前

準備階段依 [Stage Commits](stage-commits.md) 分別保存已確認摘要、Boundary 與已核准 Package。這些 commits 在 Start Gate 前完成；Maintenance 的單一交付 commit 從 Start Gate HEAD 起算。

Package checkpoint 登記成功後才通過 Start Gate，再派工。Maintenance 與 Documentation 的適用條件先依 [Package Authoring](package-authoring.md#選擇-package-類型) 判斷。

## 派發與隔離

lease 後重查 `next`：`leased_tasks` 列出未進入 running 的 Task。未登錄 executor 時，從 `registration_choices` 選擇實際使用的 handle 或 PID 命令，只執行其中一種；登錄後再次查詢，使用既有 `task running` 命令。沒有其他可派任務時，入口為 `start-leased-workers`。`resolve-executor-registration` 或 Task blocker 表示目前無法確認可啟動的 executor，先查明原因，不編造新身分或把停止紀錄當成仍可工作。登錄與查詢不代表開始實作，Gate 仍會在操作時核對狀態。

正常執行的 `next.dispatch_tasks` 提供目前可派 Task 的責任、路徑、checks IDs、文件引用、預定 branch/worktree 與 `task leased` 命令；歷史 Task 沒有的描述不會代填。先準備所列 checkout，使用真正派工取得的 Agent ID 取代命令 placeholder。提示不是 lease 或 checkout 已就緒的證明；一次登記一個 lease 後重查 `next`，Gate 仍核對最新依賴、容量、範圍與工作目錄。取得 lease 後依下方規則登錄 executor，再進入 running。

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 依序完成；Atomic Task 依[完成 Task](#完成-task)流程完成後才開始下一項。同一 Implementer 可連續處理，無須每項重新建立代理。只有 Coordinator 可串行整合到固定 delivery branch。

每個 Worker 取得 lease 後，先以 `replan register-executor --run-id <ID> --agent-id <lease-agent-id>` 登錄真正的執行身分，再進入 `task running`：外部 Agent 提供 `--handle <executor-handle>`，OS executor 提供獨立 process group 的 `--pid <PID>`。命令沿用 `replan` 命名，但正常派工不執行 `replan begin`。Coordinator 在派工前後查詢 Gate，已要求停止後不得啟動工作；不能編造 handle／PID。需要停止時依 [executor 停止與憑據](replanning.md#停止與保存) 保留真正工具回報，只更新 Task status 不代表程序已停。

Worker 在完成、失敗、阻塞或預期明顯延遲時主動回報。Coordinator 優先等待通知；較長工作可約定下次確認時間，未收到預期回報時主動詢問。進度回報先提供足以判斷繼續等待、協助或推進的摘要，資訊不足或異常時再讀相關細節。

## 完成 Task

### Atomic Task

Atomic Task 依下列順序完成，才能開始下一項 Task：

1. 登記 `task leased`，依[派發與隔離](#派發與隔離)完成 executor 登錄，再登記 `task running`。
2. 實作該 Task，使用 `run-check` 執行其 targeted checks。
3. 建立該 Task 的獨立 commit。
4. 執行 `task-finish --run-id <ID> --task-id <ID> --input <finish.json> --action-id <ID>`，輸入為 `{ "risks": [] }`，有剩餘風險時如實填寫字串陣列。Gate 一次登記 Implementer Result 與 Task complete；成功後依既有 lease 流程接續下一項。

也可先 commit 再檢查；提交前 evidence 只有在提交後內容完全相同時才有效。Result 的 `evidence` 精確列出 Task `check_ids` 的 controlled evidence 路徑。Gate 驗證非空、單一 parent 的 commit，parent 必須是 lease base；拒絕未提交產品內容、過期或不完整證據。

`task-finish` 從既有 lease、Git 與已登記 controlled checks 產生 agent/base/head/changed paths/evidence 與 `requested_transition: verifying`，不要求 Agent 重填。每項 targeted check 使用該 checkout 最新啟動且已登記的 attempt；新失敗、未知結果、歧義或失效證據都不能退回選舊成功。命令不代跑測試、不建立 commit、不自動派工或進入審查。舊 `agent-result` → `task complete` 仍可用，但 completed atomic Implementer Result 的下一階段必須是 `verifying`，新錯誤會立即拒絕；歷史錯誤依 [Runtime Interface](runtime-interface.md#固定操作與歷史登記恢復) 更正。

原 Task 漏列必要路徑時，先停止受影響執行者，依[實作中補列必要路徑](execution-corrections.md#實作中補列必要路徑)取得授權，不先改未授權檔案。

### Maintenance 任務快照

Maintenance 的新 lease 由 Gate 記錄 working tree 與 index 兩份起始快照；Implementer Result 的 `changed_paths` 完整列出本次任務相對這兩份快照的產品增量，包括 staged、unstaged 與 untracked 路徑。不能因 base/head 相同或已 staged 而省略；rename 同時列原路徑刪除與新路徑新增。Gate 另驗整個 checkout 的累積修改是否仍在 Package 範圍內，且不更動使用者 index。請在取得 lease 後才修改或 stage 任務負責的檔案，不要替其他 task stage；一般執行階段的任務間隙若出現未登錄修改，下一個 lease 會拒絕。獨立 Reviewer 使用 Gate 保存的該任務完成快照判定責任，並確認目前內容仍是本輪正式驗證的內容。

Maintenance 在目前 delivery checkout 執行，保留 Start Gate HEAD，任務與修正先保存未提交快照；最後以 [Finalization](finalization.md) 規定的一個交付 commit 保存所有已驗證內容。Documentation 不自動取得 Maintenance 的單一 commit 規則或審查豁免。

### 登錄 Agent Result

一般獨立審查的 `next.review_tasks` 列出本輪尚未完成審查的 Task 與 `agent-result` 草稿。將 operation 的 `input` 保存為 JSON，完成真實審查後補齊 `required_inputs`，再代入 `--input` 與 action ID 執行；草稿只預填 run/task、role、被審查者及 commit 引用，不預填 Reviewer 身分、通過結論、changed paths、evidence、風險或 requested transition。沒有可確認的實作／lease 時回 blocker，不猜引用；Maintenance 仍依任務快照與目前 HEAD 審查。既有 Result 格式與版本／內容驗證不變，提示不保證過時資料可登記。登記後重查 `next`；本輪全部審查完成時，`complete-review` 提供既有 `review-approved` transition，由 Gate 重新核對內容並判定能否推進，不再派 Reviewer。

使用手動 `agent-result`（包含 Reviewer 登記）時，至少回報 run/task/agent/role、status、base/head commit、changed paths、checks/evidence、risks 與 requested transition。Implementer identity 取自 Gate 發出的 task lease；Reviewer Result 必須逐 task 指向該 implementer，Gate 自行比對兩者不同。Package 只固定 role 與獨立性要求，不預先指定真人或 Agent ID。格式修復最多兩次，只能修結構，不能更改實際 code、evidence 或風險判斷。

### Task 中斷或檢查失敗

尚未發布且尚未登錄完成的 Atomic Task 暫存 commit 若檢查失敗，可在原 lease base 與 paths 內整理成一個 commit；保留舊 evidence 並重跑相關檢查。已發布或已登錄完成的 commits 不得改寫。

Atomic 下一個 Task 取得 lease 前仍會檢查 checkout，避免任務間隙混入未登錄修改。正式檢查失敗時留在該 Task 修正並以新 action ID 重跑，不能先宣告完成。一般 run 的 block／resume 保留原 lease 與證據歷史。Task 本身走 `blocked → pending → leased` 時保留原 base，允許原 paths 內未完成的修改或尚未登錄的一個 commit，但須在新 lease 後重新執行 targeted checks；已登錄的完成 commit 不得改寫，也不能吸收其他 Task 的變更。

### 舊 Maintenance lease

舊 lease 完全沒有快照時，維持原本保守的 baseline 全範圍驗證，不從目前檔案倒填起始快照；因此舊版多 task run 可能仍需另外處理，不能自動套用新的增量規則。不完整或 Git object 遺失的快照會拒絕操作。

## 正式驗證

### 選擇與執行 checks

Atomic Package（包含審查退回的修正 Task）本地只執行變更行為與受影響依賴的相關檢查，完整 regression 集中於最終整合版本並交給 CI，不固定在本地執行完整 build／lint／migration；其中任一項若是 Task 或整合的必要驗證，仍列為相關 check。Coordinator 在 Plan 記錄選測理由，影響擴大時依 Amendment 補充，不只看哪些測試檔被修改。Gate 不自動推算測試影響範圍，也不以本地通過宣稱 CI 已通過；合併依既有 CI 要求，未執行／等待／失敗如實回報。

- 所有正式 checks 由 controlled runner 以 argv array 執行，不預設 shell；cwd 限於 worktree，套用 timeout、輸出上限、redaction 與 env allowlist。
- `fetch_allowed` 是 Coordinator 應遵守的授權政策；runner 沒有網路隔離機制，設為 false 不會阻止 check 程序連網。需要網路限制時，由執行環境提供並驗證。

Gate 先 materialize 核准 Package 與有序 Amendments，runner 只使用該 effective contract。check 前後的工作樹快照必須相同；HEAD／內容／契約或 check definition 綁定不同時，舊 evidence 不再適用。

runner 只保存有界 head/tail 輸出。合計輸出超過凍結的 `max_check_output_bytes` 時終止檢查並判定失敗；`output_limit_exceeded` 或 `termination_degraded` 不得當成通過 evidence。缺少目前必要 evidence 欄位時重新執行，不補寫舊證據。程序等待、快照與發布細節供維護者查閱 [Runtime Internals](runtime-internals.md)。

`run-check` receipt 回傳原 action 的 `check_status`、`exit_code`、`timed_out`、`output_limit_exceeded`、`termination_degraded`、`worktree_changed_during_check`，不含 stdout/stderr。`ok: true`／exit code `0` 只代表 Gate 操作成功，是否通過看 `check_status`。Receipt 的 `check_id`、`evidence_path`、`evidence_hash`、`head_commit` 與 `effective_contract_hash` 精確指向該 action 原本登錄的 evidence，重送不改指向新 evidence；schema 與 hashes 不變。

需要 Amendment 補充工作或正式驗證失敗進入 correction 時，依 [Execution Corrections](execution-corrections.md#自動修正)處理。

### 本波驗證與整合後驗證

先確認 `task_delivery`。以下表格與跨狀態證據沿用規則只適用 `task_delivery: "atomic"`。非 Atomic（包含目前的 Maintenance／Documentation Mini Package）依本輪完成事件與驗證階段檢查全部 required checks；不能只因 HEAD／內容／契約相同，就沿用完成事件之前的 evidence。歷史 Package 也保留其原驗證規則。

`next` 的驗證提示列出 `eligible_evidence`、`missing_checks`、`stale_checks` 與已填 evidence 的 `verify`／`post-verify` argv；完整組合無法驗證時不提供 closure。提示有範圍限制時，不能以截斷清單宣稱可完成。

必要證據齊全時，`submit-verification`／`submit-post-verification` 提供使用現有 evidence 的 `verify`／`post-verify` 命令，不要求重跑測試；缺少或過期時仍提示適用的檢查。執行後重查 `next`，過時提示不免除操作時的驗證。

Atomic 本波 Task 完成後，依 Gate 執行 `verify`；整合全部完成後再執行 `post-verify`。兩者核對的內容不同：

| 操作 | evidence 對象 |
|---|---|
| Task Result | 精確涵蓋該 Task 的 `check_ids`，保存該 Task 的歷史驗證 |
| `verify --evidence` | 本波每個 checkout 最新完整內容；不能拿早期 Task evidence 代替目前內容 |
| `post-verify --evidence` | 最新 delivery HEAD 的 required integration checks，至少一項作為最後內容依據 |

早期 Task 的 required evidence 已由 Result 驗證並保留，不要求在後續 HEAD 重跑。最後 Task 的提交前 evidence 若與提交後完整內容一致，可用於本輪驗證及該 Task Result 綁定的 review。相同 HEAD、完整 content tree 與 effective contract 的 evidence 可跨狀態沿用；階段切換本身不要求重跑。任一綁定變更時重跑必要的相關 checks，不改綁或補寫歷史 evidence。

`Result.checks` 記錄最後整合驗證採用的 checks；Task checks 保留在 Implementer Results 與 delivery summary。不建立純跑測試的 Task 或空 commit。舊 Package 維持原驗證規則。

### Check 重送

`resolve-check-recovery` 優先於正常驗證、Task 完成與派工；此時只提供可確認安全的恢復操作，不保留先前的推進命令。恢復資料無法讀取或超出查詢範圍時，說明原因並停止推進；成功恢復後重查 `next`。只有尚未開始的非阻塞請求仍為 optional，不影響正常下一步。

先讀 `next.check_recovery` 的操作與 blockers：Gate 區分未啟動、已發布 evidence、已綁替代檢查與未知結果。非阻塞的未啟動請求僅列在 `optional_recovery_operations`，不取代正常驗證；不自行依 marker 猜測資格或另造 resolver。Transient retry 最多兩次，跨 resume 與 Agent 更換保留；超限或不可恢復錯誤時依 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)停止並登錄 block。以下說明各種提示的處理界線。

新 attempt 在建立 `started.json` 前，先驗證合法 checkout、cwd、必要的程序 identity／group inspection 與實際 Git snapshot 能力；不安裝依賴、不建立 `.env` 或重建資料庫。`env_allowlist` 是允許傳入的名稱，不代表必填變數。前置拒絕時 command 未啟動，修復環境後使用原 action ID 與原輸入重送，不消耗 transient retry；原 `request.json` 保留以防同 ID 改輸入。啟動當下仍重新檢查 snapshot、fence 與實際程序登錄，前置成功不是稍後安全的證明。

Controlled check 重送使用同一 action_id 與相同輸入；同 ID 不得改 check、worktree 或執行契約。已發布 evidence 可在事件追加失敗後補登錄。若 attempt 已開始但沒有完整 evidence，結果視為未知，先確認程序與外部副作用再處理，不以自動重跑假裝恢復成功。

已完成 action replay 與已發布 evidence 補登錄不重新做啟動能力 probe。marker 後原 runner pre-snapshot 的正式失敗證明，仍僅依[受控重試](#執行前-snapshot-失敗的受控重試)恢復；spawn 後 registry 失敗、post-snapshot 中斷及空 registry 都不能視為未啟動。無合法恢復命令時保留現場，不刪 marker。

### 執行前 snapshot 失敗的受控重試

Atomic Task 執行中，只有 Gate 在檢查命令啟動前捕捉 snapshot 失敗，並追加 `check-preparation-failed`，才可使用此恢復路徑。先確認失敗原因已排除，再登錄既有 transient retry，明確綁定原 action 與全新的替代 action：

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> retry --run-id <ID> --kind transient --reason "<已排除的原因>" --check-action-id <原-check-action> --replacement-action-id <新-check-action> --action-id <retry-action>
python3 cogito/scripts/cogito_gate.py --repo <root> run-check --run-id <ID> --check-id <原-check-id> --worktree <原-worktree> --action-id <新-check-action>
```

Gate 驗證相同 Task lease、worktree、check 定義與有效契約；替代檢查登錄有效的成功 evidence 後，原未完成 marker 才不再阻擋結案。原 marker、事件與 evidence 全數保留，這不會免除其他失敗或過期檢查。

替代檢查若實際執行失敗，修正後可在剩餘 transient retry 額度內，將同一原 action 綁定另一個全新 action；Gate 會確認上一替代檢查有失敗 evidence 且 executor 已停止。若替代檢查也在啟動前失敗，則以該替代 action 作為下一次 retry 的來源。沒有 outcome、仍在執行或已成功的替代檢查不可重綁。

只有理由文字的舊 retry、歷史上無法確認執行階段的 marker，以及命令執行後的 snapshot 失敗，都維持未知結果的阻擋；不得手動補造失敗紀錄或刪除 marker。

## 獨立審查

完成本波正式驗證後，由不同 Agent 逐 Task 進行獨立 review。Gate 逐 task 比對 Implementer task lease 的 `agent_id`、Reviewer Result 的 `reviewed_implementer` 與不同的 reviewer `agent_id`，由已登錄 Result 推導審查完成情況，不接受 Agent 回報的 `independent: true`，也不在 Package 預先綁定 Agent 身分。Coordinator 必須指派實際不同的 Agent，並維持穩定且唯一的 ID；Gate 的 ID 比對不提供外部身分驗證。Reviewer 可建議核准、提出 Package 內修正或升級風險，但不得移除 human predicate；最終 review verdict 由 Gate 計算。Maintenance 只有在 Mini Package 的低風險宣告已有足夠證據並經核准、且 Gate 的檢查通過時可豁免；語意判斷與機械檢查的分工見 [Package Authoring](package-authoring.md#選擇-package-類型)。

Feature／Change／Correction／Documentation 的 Reviewer Result 使用該 task 最新完成 Implementer Result 的 `base_commit`／`head_commit`，不把後續 task 的 commit 範圍併入。該 head 必須仍是目前 worktree HEAD 的祖先；目前 HEAD 與內容須對應本輪 `verification-passed` 採用的正式 evidence；atomic 模式也接受最後 Task Result 綁定的相同內容提交前證據。修正後重新驗證，預設重新提交本輪各 task 的 review；需要採認原 approval 時，另依[保留未受影響審查](execution-corrections.md#保留未受影響審查)核對資格。審查結束轉移也會重新比對 worktree，拒絕 review 後才加入的未驗證內容。只有 optional checks 的 Package 仍需至少一份本輪已登錄、未竄改且通過的 controlled evidence 作為審查內容依據。

Reviewer 登記 `needs-fix` 後，依[啟動審查修正](execution-corrections.md#啟動審查修正)處理，不重開已完成 Task／Result。

## 串行整合

Atomic Development 可先使用 `next.integration_choices`：提示從正式 Task Results 推導 source tip，核對 delivery branch／HEAD、祖先與核准範圍。首版只產生可確定的 `git merge --ff-only <source-sha>` 與既有 `integrate` 命令，不做普通 merge 預演、不提供 cherry-pick。多個選項一次只執行一個，完成後重查 `next`；Git 已 fast-forward 而尚未登記時可只補 `integrate`。非 fast-forward、delivery 漂移或缺少資料會回 blocker，改依下方原有整合程序檢查，不能把提示當成無衝突保證或新授權。

每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。

Atomic 整合另以 Git `merge-tree --write-tree` 比對前一 delivery HEAD 與已審查 Task tip 的正常合併結果，拒絕在 integration commit 夾帶產品修改或撤銷已完成 Task；僅沿用 canonical Package／Project Graph 的精確控制文件例外。需要支援此命令的 Git。合併衝突或額外修改不能假裝成已驗證整合：保留現場、登錄 block，依既有 RP 重新安排需修改的工作；本版不新增整合修正狀態。一般無衝突的串行、平行 Slice 合併與 fast-forward 均可沿用。

整合 Gate 除了檢查 source heads 與祖先關係，也比對前一 delivery HEAD 到 integration commit 的實際差異，拒絕超出 Package `approved_paths` 的產品檔案。此範圍包含合法 Technical Amendment 的修正，不另外縮限成原 task 路徑聯集。路徑以 NUL 分隔並將 rename 視為原路徑刪除與新路徑新增，檢查不改動 index。

### 核准路徑與控制文件

核准後需隨合法 commit 保存的控制文件只按精確路徑例外處理：本 run 的凍結 Package 必須內容相符，整合時的 Project Graph 必須符合核准 hash；Package 指定的 Spec／Plan 可依既有政策在最後驗證前更新；source registry 中 `adopted`／`updated` 的來源若依賴控制文件例外提交，必須符合凍結的原始 bytes hash，已在 `approved_paths` 的來源則可按核准範圍更新。其他文件不能因位於 `docs/` 就取得例外。

### 整合後的下一步

所有 Slice 整合完成後，在最新 delivery branch 驗證 post-integration checks；失敗依[正式修正](execution-corrections.md#自動修正)處理並共用開發 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整進入 `awaiting-human` 門閥。人工退回可修正後再次回到此門閥；人工來源 RP 的 successor 即使沒有這些 predicate，也須重新人工驗收。

人工退回依 [Human Acceptance](human-acceptance.md) 的分類、修正與結案授權操作；Maintenance 人工修正仍需本輪獨立 review。Gate 進入 `finalizing` 後改讀 [Finalization](finalization.md)。
