# Execution Policy

正常執行依 Start Gate → 派工／Task → 正式驗證 → 獨立審查 → 整合推進。首次派工先讀「Start Gate 前」「派發與隔離」及適用 Task 小節；遇到修正再讀「自動修正」的共通邊界與該修正程序。其餘依 `next_action` 讀取完整對應小節及其必要引用，狀態轉移仍由 Gate 決定。共通 CLI、action ID 與停止／重送規則見 [Runtime Interface](runtime-interface.md)。

## Start Gate 前

準備階段依 [Stage Commits](stage-commits.md) 分別保存已確認摘要、Boundary 與已核准 Package。這些 commits 在 Start Gate 前完成；Maintenance 的單一交付 commit 從 Start Gate HEAD 起算。

Package checkpoint 登記成功後才通過 Start Gate，再派工。Maintenance 與 Documentation 的適用條件先依 [Package Authoring](package-authoring.md#選擇-package-類型) 判斷。

## 派發與隔離

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 依序完成；Atomic Task 依[完成 Task](#完成-task)流程完成後才開始下一項。同一 Implementer 可連續處理，無須每項重新建立代理。只有 Coordinator 可串行整合到固定 delivery branch。

每個 Worker 取得 lease 後，先以 `replan register-executor --run-id <ID> --agent-id <lease-agent-id>` 登錄真正的執行身分，再進入 `task running`：外部 Agent 提供 `--handle <executor-handle>`，OS executor 提供獨立 process group 的 `--pid <PID>`。命令沿用 `replan` 命名，但正常派工不執行 `replan begin`。Coordinator 在派工前後查詢 Gate，已要求停止後不得啟動工作；不能編造 handle／PID。需要停止時依 [executor 停止與憑據](replanning.md#停止與保存) 保留真正工具回報，只更新 Task status 不代表程序已停。

Worker 在完成、失敗、阻塞或預期明顯延遲時主動回報。Coordinator 優先等待通知；較長工作可約定下次確認時間，未收到預期回報時主動詢問。進度回報先提供足以判斷繼續等待、協助或推進的摘要，資訊不足或異常時再讀相關細節。

## 自動修正

Coordinator 依 Package 的 `stop_conditions` 與執行證據判讀是否應停止。這些條件是凍結的政策文字，Gate 不會自動求值或依 `outcome` 轉移狀態；停止派工、登錄 `block`、取消授權與 Human Gate 的處理依 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash。

一般 Technical Amendment 在已核准路徑內增加 checks、tests、tasks，或修正內部實作；新增 check 的 `env_allowlist` 不得超出 Package 凍結的 `allowed_environment`。只有[實作中補列必要路徑](#實作中補列必要路徑)與[審查修正中的必要檔案補列](#審查修正中的必要檔案補列)可經獨立覆核擴充精確路徑；一般修正不得藉此擴張範圍。不得刪除或降級 required checks、改 Acceptance、公開 API、資料模型、安全邊界、依賴或 DAG。有效契約 hash 由 base Package 與有序 amendments 計算；相關 commit 使用 `Cogito-Amendment: <ID>` trailer；Maintenance 的延後提交依[修正完成方式](#maintenance-修正完成)。

Amendment 只能單調增加或加強工作。超出上述邊界時依 [Replanning](replanning.md) 限制全體執行、保存現場，再提出新的核准契約與 successor 承接方案。

Atomic 的產品 correction 必須使用新增 Task；只增加檢查可直接重新 verify，不開啟無任務的產品修正。新增任務以 `depends_on` 指定前置任務，可引用 base Package、先前 Amendment 或同批新增的任務。Gate 在追加事件前合併完整任務圖，拒絕未知節點、自我依賴與循環；effective contract 的 edges 會包含這些依賴，原始文件與 hash 不變。追加不能修改既有任務依賴或新增跨 Slice 的依賴關係；沿用已核准跨 Slice 關係時，前置任務必須已 `integrated`，避免修正流程等待自身完成後才能進行的整合。

## 完成 Task

### Atomic Task

Atomic Task 依下列順序完成，才能開始下一項 Task：

1. 登記 `task leased`，依[派發與隔離](#派發與隔離)完成 executor 登錄，再登記 `task running`。
2. 實作該 Task，使用 `run-check` 執行其 targeted checks。
3. 建立該 Task 的獨立 commit。
4. 執行 `task-finish --run-id <ID> --task-id <ID> --input <finish.json> --action-id <ID>`，輸入為 `{ "risks": [] }`，有剩餘風險時如實填寫字串陣列。Gate 一次登記 Implementer Result 與 Task complete；成功後依既有 lease 流程接續下一項。

也可先 commit 再檢查；提交前 evidence 只有在提交後內容完全相同時才有效。Result 的 `evidence` 精確列出 Task `check_ids` 的 controlled evidence 路徑。Gate 驗證非空、單一 parent 的 commit，parent 必須是 lease base；拒絕未提交產品內容、過期或不完整證據。

`task-finish` 從既有 lease、Git 與已登記 controlled checks 產生 agent/base/head/changed paths/evidence 與 `requested_transition: verifying`，不要求 Agent 重填。每項 targeted check 使用該 checkout 最新啟動且已登記的 attempt；新失敗、未知結果、歧義或失效證據都不能退回選舊成功。命令不代跑測試、不建立 commit、不自動派工或進入審查。舊 `agent-result` → `task complete` 仍可用，但 completed atomic Implementer Result 的下一階段必須是 `verifying`，新錯誤會立即拒絕；歷史錯誤依 [Runtime Interface](runtime-interface.md#固定操作與歷史登記恢復) 更正。

### 實作中補列必要路徑

僅限 `executing` 中的 Atomic Development Package：原規格所需的 mapper、response contract 或測試檔漏列時，可在同一 Run、Slice、branch 與已存在的 worktree 追加精確檔案路徑。只補入同一 Slice 未完成 Task，不新增需求、Task、successor 或改 DAG；已完成 Task 的 commit、Result 與歷史 evidence 不改寫，若需改變已完成行為，使用新增修正 Task。審查才發現缺漏時，改讀[審查修正中的必要檔案補列](#審查修正中的必要檔案補列)。

先依[路徑補列的共通程序](#路徑補列的共通程序)確認範圍並停妥受影響 Worker／checks，保留原授權路徑內未完成的內容；不得先修改未授權路徑再申請補正。Coordinator 準備以下 proposal，再依共通程序 propose／review：

```json
{
  "author_id": "coordinator-1",
  "amendment": {
    "id": "AM-path-1",
    "reason": "原核准查詢流程漏列 mapper 與相關測試",
    "path_additions": [{
      "task_id": "T-002",
      "paths": ["src/query_mapper.py", "tests/test_query_mapper.py"],
      "reason": "輸出 Spec 已核准的欄位並驗證轉換",
      "check_ids": ["C-query-mapper"]
    }],
    "added_checks": [{
      "id": "C-query-mapper",
      "argv": ["python3", "-m", "unittest", "tests.test_query_mapper"],
      "required": true,
      "phase": "task"
    }]
  }
}
```

已有適用 required check 時省略 `added_checks`。此類 amendment 不混用 `added_tasks`、`path_fixes` 或 `commit_id`。

覆核生效且 executor 封存完成後，原 leased／running Task 可重新登錄 executor，繼續實作、相關檢查與獨立 commit；目前必要 evidence 須綁定新 effective contract。已完成 Task 不要求重新交付。純路徑補正沒有獨立的產品修正 commit，Result 使用 [Finalization](finalization.md#3-準備-result-與-project-graph) 的 `proposal_hash` 記錄。

### Maintenance 任務快照

Maintenance 的新 lease 由 Gate 記錄 working tree 與 index 兩份起始快照；Implementer Result 的 `changed_paths` 完整列出本次任務相對這兩份快照的產品增量，包括 staged、unstaged 與 untracked 路徑。不能因 base/head 相同或已 staged 而省略；rename 同時列原路徑刪除與新路徑新增。Gate 另驗整個 checkout 的累積修改是否仍在 Package 範圍內，且不更動使用者 index。請在取得 lease 後才修改或 stage 任務負責的檔案，不要替其他 task stage；一般執行階段的任務間隙若出現未登錄修改，下一個 lease 會拒絕。獨立 Reviewer 使用 Gate 保存的該任務完成快照判定責任，並確認目前內容仍是本輪正式驗證的內容。

Maintenance 在目前 delivery checkout 執行，保留 Start Gate HEAD，任務與修正先保存未提交快照；最後以 [Finalization](finalization.md) 規定的一個交付 commit 保存所有已驗證內容。Documentation 不自動取得 Maintenance 的單一 commit 規則或審查豁免。

### 登錄 Agent Result

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

### 本波驗證與整合後驗證

先確認 `task_delivery`。以下表格與跨狀態證據沿用規則只適用 `task_delivery: "atomic"`。非 Atomic（包含目前的 Maintenance／Documentation Mini Package）依本輪完成事件與驗證階段檢查全部 required checks；不能只因 HEAD／內容／契約相同，就沿用完成事件之前的 evidence。歷史 Package 也保留其原驗證規則。

`next` 的驗證提示列出 `eligible_evidence`、`missing_checks`、`stale_checks` 與已填 evidence 的 `verify`／`post-verify` argv；完整組合無法驗證時不提供 closure。提示有範圍限制時，不能以截斷清單宣稱可完成。

Atomic 本波 Task 完成後，依 Gate 執行 `verify`；整合全部完成後再執行 `post-verify`。兩者核對的內容不同：

| 操作 | evidence 對象 |
|---|---|
| Task Result | 精確涵蓋該 Task 的 `check_ids`，保存該 Task 的歷史驗證 |
| `verify --evidence` | 本波每個 checkout 最新完整內容；不能拿早期 Task evidence 代替目前內容 |
| `post-verify --evidence` | 最新 delivery HEAD 的 required integration checks，至少一項作為最後內容依據 |

早期 Task 的 required evidence 已由 Result 驗證並保留，不要求在後續 HEAD 重跑。最後 Task 的提交前 evidence 若與提交後完整內容一致，可用於本輪驗證及該 Task Result 綁定的 review。相同 HEAD、完整 content tree 與 effective contract 的 evidence 可跨狀態沿用；階段切換本身不要求重跑。任一綁定變更時重跑必要的相關 checks，不改綁或補寫歷史 evidence。

`Result.checks` 記錄最後整合驗證採用的 checks；Task checks 保留在 Implementer Results 與 delivery summary。不建立純跑測試的 Task 或空 commit。舊 Package 維持原驗證規則。

### Check 重送

先讀 `next.check_recovery` 的操作與 blockers：Gate 區分未啟動、已發布 evidence、已綁替代檢查與未知結果。非阻塞的未啟動請求僅列在 `optional_recovery_operations`，不取代正常驗證；不自行依 marker 猜測資格或另造 resolver。以下說明各種提示的處理界線。

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

Feature／Change／Correction／Documentation 的 Reviewer Result 使用該 task 最新完成 Implementer Result 的 `base_commit`／`head_commit`，不把後續 task 的 commit 範圍併入。該 head 必須仍是目前 worktree HEAD 的祖先；目前 HEAD 與內容須對應本輪 `verification-passed` 採用的正式 evidence；atomic 模式也接受最後 Task Result 綁定的相同內容提交前證據。修正後重新驗證，預設重新提交本輪各 task 的 review；符合下方「保留未受影響審查」條件者可明確採認原 approval。審查結束轉移也會重新比對 worktree，拒絕 review 後才加入的未驗證內容。只有 optional checks 的 Package 仍需至少一份本輪已登錄、未竄改且通過的 controlled evidence 作為審查內容依據。

### 啟動審查修正

Atomic Development 的本輪 Reviewer 已登記 `needs-fix` 時，先彙整已完成審查中同一 Slice 的相關 findings，再查 `next` 取得 `prepare-review-fix` 的精確 finding reference。預設每輪、每個受影響 Slice 使用一個修正 Task，沿用其 branch/worktree；不按每個問題建立 Task 或分支，也不為單純修正建立 RP。不同 Slice 不合併責任範圍。

Coordinator 在既有 Amendment 的 `reason`／Task `responsibility` 引用本輪相關 Reviewer Result 與問題，說明修正範圍及選測理由；不另外建立修正清單 schema、流程單或核准關卡。`finding` 是本輪的啟動依據，不代表只能處理該筆 Result 的一個問題。Task 的 `check_ids` 僅列必要的相關檢查，不直接複製整份 Package 的 integration checks；原 required checks 不刪除，仍在其適用階段驗證。

尚未完成的修正 Task 又發現相關問題時，在原 paths、責任與核准語意內繼續修正、保留失敗 evidence 並以新 action ID 重跑相關 checks，不重建 Task 或 lease。需補授權時先依下節辦理；超出原產品契約時才評估 RP，不能以「同一輪」放寬 API、資料或安全邊界。完成的 Task／Result 不重開或改寫；完成後又有新 finding，依正常複審進入下一輪修正。

Coordinator 撰寫本輪修正 Task 與 checks 的 Amendment，保存輸入：

```json
{
  "finding": { "event_sequence": 54, "event_hash": "<next 提供的 hash>" },
  "amendment": {
    "id": "TA-001", "reason": "補齊年度列表的快取設定",
    "added_tasks": [{
      "id": "T-005", "slice_id": "FS-043",
      "paths": ["src/routes/certificate.routes.ts"],
      "responsibility": "修正年度列表的快取回應",
      "check_ids": ["V-005"]
    }]
  }
}
```

以上為欄位示意；finding 使用 `next` 的原值，Task、Slice、paths 與 check IDs 依本次有效契約撰寫。使用 `review-fix-start --run-id <ID> --input <file> --action-id <ID>`。工具在登記前驗證 finding、修正責任、依賴、checks、checkout 及現有門檻，按 start → amendment 登記事件；不再要求 Agent 分開操作。若 finding 已被本輪通過結果取代、Amendment 非法或契約／內容改變，立即拒絕。

啟動成功後依一般 Atomic Task 流程實作、相關檢查、獨立 commit 與 `task-finish`；每項修正 commit 保留 `Cogito-Amendment: <ID>` trailer。修正 Tasks 完成後依 `next` 執行 `review-fix-complete`，再正式驗證及本輪獨立審查；未受影響的原 approval 可依下節採認。正式審查仍在實作與驗證後進行，不與後續實作並行。

既有分開的 `review-fix-start` → `amend` 仍支援，包括非 Atomic 流程。新操作不得在 `reviewing` 先用 `amend` 加修正 Tasks；一般 check-only 等其他合法 Amendment 不受此限制。已被舊版接受的錯序恢復見 [Runtime Interface](runtime-interface.md#固定操作與歷史登記恢復)。

### 審查修正中的必要檔案補列

限同一 Atomic Development Run、整合前的 `review-fix`：本輪 finding 所需的檔案漏列，且 Acceptance、公開 API 語意、資料模型、安全邊界與 Slice 責任均不變。補正可授權本次新增的修正 Tasks，或本輪已新增且尚未完成的修正 Task，全部屬於該 finding 的 Slice；不更改已完成 Task 的 paths、checks、commit 或 Result。真正超出核准契約時使用 [Replanning](replanning.md)。

以下步驟用於首次建立修正 Task；已有本輪未完成 Task 時，直接依本節末段補列，不再次啟動 review-fix 或新增 Task。

1. Coordinator 或 Implementer 先說明原 finding、未超出範圍的理由、精確檔案及相關 checks。引用原規格與 finding，不重新撰寫完整 Package。以 `next` 提供的 `finding` 單獨作為 `review-fix-start --input` 的輸入，例如 `{"finding": {"event_sequence": 54, "event_hash": "<實值>"}}`，先進入既有修正階段；不要把尚未覆核的路徑補列放進合併啟動輸入。
2. 停妥受影響 Worker 與 controlled checks，保留原本已驗證的 checkout；尚未授權的檔案不可先改。依[路徑補列的共通程序](#路徑補列的共通程序)準備並 propose 以下形式：

   ```json
   {
     "author_id": "coordinator",
     "amendment": {
       "id": "TA-mapper", "reason": "修正本輪 finding：補齊原需求的年度欄位",
       "added_tasks": [{
         "id": "T-mapper", "slice_id": "FS-043",
         "paths": ["src/response_mapper.ts"],
         "responsibility": "回傳原規格要求的年度",
         "depends_on": ["T-query"], "check_ids": ["C-year"]
       }],
       "path_additions": [{
         "task_id": "T-mapper", "paths": ["src/response_mapper.ts"],
         "reason": "原核准欄位所需的 mapper 漏列", "check_ids": ["C-year"]
       }]
     }
   }
   ```

   IDs 使用實值。`added_tasks.paths` 是修正 Task 的完整範圍；`path_additions.paths` 只列需要補授權的精確檔案，且其 paths／checks 必須包含在對應新 Task。每個新 Task 都須有對應補列，不混入其他任務。必要時在同一 Amendment 增加 `added_checks`；原 required checks 仍保留。路徑須符合下方[共通限制](#路徑補列的共通程序)；跨 Slice 前置任務須已 integrated，不能改變原 Slice 相依。
3. **由原本的獨立 Reviewer 在既有審查中確認範圍即可**，不固定增加第三位 Agent 或使用者核准。Reviewer 不得是 proposal 作者或受影響 Implementer。依共通程序以 `amend-paths review` 保存具體範圍判斷與選測理由；通過後一筆 Amendment 同時登記檔案授權與新修正 Tasks。覆核前不建立可執行的新 Task。
4. 依上節完成修正 Task、相關檢查、commit、`task-finish` 與 `review-fix-complete`，再驗證目前內容並複審。原 Reviewer 聚焦確認原 finding、新增／受影響 Task 與連帶影響；符合下節條件的未受影響 approval 可採認。無法證明不受影響時擴大複審，不因補列檔案而自動重開 run。

本輪 Task 尚未完成時又發現漏列檔案，依[共通程序](#路徑補列的共通程序)執行 `amend-paths propose/review`，只提交指向該 Task 的 `path_additions` 與必要的 `added_checks`，省略 `added_tasks`。先停止受影響執行者，再提案；可保留 Task 原 paths 內未完成的修改，不得先改新檔案。Gate 保留 Task ID、lease base、分支及原修正 Amendment，追加授權後取得新 effective contract 的必要 evidence，再繼續同一 Task。`review-fix-complete` 仍引用建立該 Task 的 Amendment ID；後續純路徑補正另按 `proposal_hash` 記錄，不取代原修正完成紀錄。前一輪 Task 或已登記完成 Result 不適用。

此入口的 proposal 另綁定本次 review-fix finding。撤回不發布新 Task 或授權，仍留在原修正階段；修訂、撤回與中斷重送依共通程序，不重建修正 Task。

### 保留未受影響審查

這是可選捷徑，限同一 Atomic Development Run、整合前 `review-fix` 完成並重新 verification 的 `reviewing` 階段。首版要求所有 Task 在同一實作 checkout、修正提交區間無 merge；其他情況走正常本輪 review。已完成 Task 的 commit 與歷史測試原本就保留，不因未使用此捷徑重新實作或補空 commit。

1. Coordinator 先在修正 Plan 說明影響與選測理由；實作修正 Task、執行相關 controlled checks 並重新 verification。對原 finding 的 Task 及新增／受影響 Task，提交本輪正常 Reviewer Result。
2. Coordinator 準備 impact JSON，例如：

   ```json
   {
     "author_id": "coordinator",
     "retained": [{"task_id": "T-001", "reason": "試算不依賴此次顯示文字", "dependency_paths": ["src/rules"]}],
     "affected_task_ids": ["T-003", "T-004"],
     "check_ids": ["C-display"],
     "assessment": "追蹤共用 service、mapper、contract 與設定，修正僅影響 Reviewer 顯示；顯示及修正 Task 的必要 checks 已通過。"
   }
   ```

   IDs 與 paths 使用實際契約值；`dependency_paths` 列出 Task DAG／paths 未表達、但本次分析確認相關的依賴。Gate 不理解程式語意，不能用空清單代表已證明沒有依賴。`affected_task_ids` 必須涵蓋實際 touched 與新增 Task；工具自動加入這些 Task 的全部 targeted checks，`check_ids` 可補充其他相關檢查，不能用來刪除 required checks。
3. 執行 `review-retention --run-id <ID> --input <impact.json>`。工具只產生提案，沒有追加核准事件。保存輸出 `data`，包含原 review／verification 引用、原審查波次內容、當前 HEAD／tree、累積 touched paths、契約及證據 hash。`next.optional_operations` 的候選僅是提示，仍須通過此入口驗證。
4. 不同於提案者及本 Run Implementer 的 Reviewer 檢查實際差異、未受影響理由與選測充分性，在該 `data` object 加入 `reviewer_id` 與非空 `assessment`。不要改寫機器產生的 `impact`／`binding`／`binding_hash`；判斷需要修改 impact 時，重新產生提案。保存為 `{"retention": <覆核後的 object>}`。
5. 以 `transition --event review-approved --run-id <ID> --payload-json <approval.json> --action-id <ID>` 結束本輪審查。Gate 再次檢查目前內容與證據，在 executor 停止的同一鎖定區間內追加一筆 `review-approved`，內含採認依據。相同輸入／action ID 重送不重複寫入；不另造原 Reviewer Result。

原 approval 必須尚未被新結果取代；`needs-fix` 或本輪新結果不能被採認覆蓋。基準是原 review 當時的整個 verified wave，涵蓋其後每一筆提交的 touched paths；修改後還原也視為受影響，同檔不同區塊仍保守重審。Task／既有 targeted check 定義、已知祖先依賴、明示語意依賴及凍結產品邊界必須不受影響；共用設定、lockfile、工具鏈或執行流程變動不採認。原／新 verification 還須具有相同 executor/workflow 綁定；缺少此欄位的歷史記錄仍可讀取，但使用正常 review。

歷史 evidence 不改綁新的 tree 或契約；受影響檢查必須對應當前內容，較新失敗、未知或未完成 attempt 不能退回舊成功。無法證明安全、提案漂移或捷徑成本高於重審時，提交正常本輪 review 即可，不需另建 Run 或採認恢復流程。採認者及理由隨 [交付摘要](finalization.md#2-取得交付摘要) 保存，必要整合檢查照常執行。

## 串行整合

Atomic Development 可先使用 `next.integration_choices`：提示從正式 Task Results 推導 source tip，核對 delivery branch／HEAD、祖先與核准範圍。首版只產生可確定的 `git merge --ff-only <source-sha>` 與既有 `integrate` 命令，不做普通 merge 預演、不提供 cherry-pick。多個選項一次只執行一個，完成後重查 `next`；Git 已 fast-forward 而尚未登記時可只補 `integrate`。非 fast-forward、delivery 漂移或缺少資料會回 blocker，改依下方原有整合程序檢查，不能把提示當成無衝突保證或新授權。

每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。

Atomic 整合另以 Git `merge-tree --write-tree` 比對前一 delivery HEAD 與已審查 Task tip 的正常合併結果，拒絕在 integration commit 夾帶產品修改或撤銷已完成 Task；僅沿用 canonical Package／Project Graph 的精確控制文件例外。需要支援此命令的 Git。合併衝突或額外修改不能假裝成已驗證整合：保留現場、登錄 block，依既有 RP 重新安排需修改的工作；本版不新增整合修正狀態。一般無衝突的串行、平行 Slice 合併與 fast-forward 均可沿用。

整合 Gate 除了檢查 source heads 與祖先關係，也比對前一 delivery HEAD 到 integration commit 的實際差異，拒絕超出 Package `approved_paths` 的產品檔案。此範圍包含合法 Technical Amendment 的修正，不另外縮限成原 task 路徑聯集。路徑以 NUL 分隔並將 rename 視為原路徑刪除與新路徑新增，檢查不改動 index。

### 核准路徑與控制文件

核准後需隨合法 commit 保存的控制文件只按精確路徑例外處理：本 run 的凍結 Package 必須內容相符，整合時的 Project Graph 必須符合核准 hash；Package 指定的 Spec／Plan 可依既有政策在最後驗證前更新；source registry 中 `adopted`／`updated` 的來源若依賴控制文件例外提交，必須符合凍結的原始 bytes hash，已在 `approved_paths` 的來源則可按核准範圍更新。其他文件不能因位於 `docs/` 就取得例外。

### 整合後的下一步

所有 Slice 整合完成後，在最新 delivery branch 驗證 post-integration checks；失敗共用 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整進入 `awaiting-human` 門閥。人工退回可修正後再次回到此門閥；人工來源 RP 的 successor 即使沒有這些 predicate，也須重新人工驗收。

人工退回依 [Human Acceptance](human-acceptance.md) 的分類、修正與結案授權操作；Maintenance 人工修正仍需本輪獨立 review。Gate 進入 `finalizing` 後改讀 [Finalization](finalization.md)。

## 路徑補列的共通程序

本節供[執行中補列](#實作中補列必要路徑)與[審查修正補列](#審查修正中的必要檔案補列)共用；適用狀態、Task 是否新增及完成方式依各入口。補列只修正原規格所需的檔案授權，Acceptance、公開 API 語意、資料模型、安全邊界與 Slice 責任必須不變。不能只靠檔名判斷；超出契約時走 [Replanning](replanning.md)。

路徑必須是精確檔案，不得使用目錄、glob、symlink、控制文件、凍結來源、高風險 hotspot，或跨用其他 Task／Slice 的責任路徑。新檔案可尚不存在，但所屬 worktree 必須已建立；已完成 Task／Result 不改寫。Checks 只引用既有或本次新增的 required checks，新增檢查仍受凍結環境政策限制，不刪除原 required checks。

1. 停妥受影響 Slice 的實際 Worker 與所有 controlled checks，保留原授權範圍內未完成的內容；未授權檔案不可先改。使用[正常登錄](#派發與隔離)與 [executor 停止憑據](replanning.md#停止與保存)的 `replan register-executor`／`replan executor-receipt`，不執行 `replan begin`。身分須對應 lease agent ID；receipt 來自真正 executor 回應，只更新 Task status 不代表已停。
2. 依原入口準備 proposal JSON，執行 `amend-paths propose --run-id <ID> --input <proposal.json> --action-id <ID>`。Gate 綁定 effective contract、受影響 Task、checkout 內容及 executor 身分，回傳 `proposal_hash`。等待覆核期間，受影響 Slice 與 controlled checks 不可繼續；其他 Slice 可繼續不受影響的 Task 操作。
3. 不同於 proposal 作者及受影響 Implementer 的 Reviewer 閱讀核准規格、必要依賴、目前 diff、完整 proposal 與檢查定義。Review JSON 包含 `proposal_hash`、`reviewer_id`、`decision: "within-approved-scope"`、`assessment` 與 `findings: []`；assessment 的 `requirements`、`api`、`data_model`、`security`、`slice`、`checks` 各用具體非空說明支持邊界不變與選測充分。存在問題時不提交通過判定；修訂 proposal 重新覆核，或撤回後走 RP。
4. 執行 `amend-paths review --run-id <ID> --input <review.json> --action-id <ID>`。通過即追加 Technical Amendment，擴充有效 Package／Worker／Task 路徑與 checks，並依入口登記適用的新修正 Tasks；不再請使用者核准。原 Package 與歷史紀錄不改寫。Gate 封存已停止 executor 的 registry 後，依原入口續接 Task；目前必要 checks 須取得新 effective contract 的 evidence，歷史通過不能代替目前驗證。

Proposal 或綁定內容改變時，重新 propose 並取得新的獨立覆核，不沿用舊 `proposal_hash`。撤回使用 `amend-paths withdraw --run-id <ID> --input <withdraw.json> --action-id <ID>`，輸入為 `{ "proposal_hash": "<hash>", "reason": "<撤回原因>" }`。撤回也封存已停止 executor，完成後可依原授權範圍重新登錄；改提另一 Slice 前先撤回目前提案。

部分失敗以相同輸入及 action ID 重送。Review 或 withdraw 事件已寫入但 executor 尚未封存時，`next` 回傳 `retry-path-amendment` 與原操作輸入、action ID；保持 Worker 停止並完成原操作，不另建 Amendment。

## 修正完成與額度

### 修正與重試額度

| 流程 | 合法循環與額度 |
|---|---|
| 開發 correction | `verifying → technical-correction → verifying`，最多三輪 |
| 整合後 correction | `post-integration-verification → post-integration-correction → post-integration-verification`，共用開發 correction 預算，不重做 integration |
| Review fix | `reviewing → review-fix → verifying → reviewing`，最多三輪 |
| Transient retry | 最多兩次 |

人工驗收修正使用獨立的三輪額度，計次與處理見 [Human Acceptance](human-acceptance.md#狀態與三輪額度)。所有計數器跨 resume 與 Agent 更換保留；超限、契約漂移或不可恢復衝突時，停止推進並依 Runtime Interface 登錄 block。

### Maintenance 修正完成

Maintenance 修正使用未提交快照：`correction-complete`／`review-fix-complete` 的 `--commit-id` 指定 Start Gate HEAD，checkout 必須仍在原 delivery branch 與相同 HEAD。Gate 追加的 completion payload 包含 `completion_mode: working-tree`、`commit_id`（基線檢查點）與 `content_tree`。Result amendment 將後兩者記為 `base_commit`、`content_tree`，不含 `commit_id`；final commit 帶齊 trailers，結案報告再補實際 amendment commit ID。不可把此格式套用到其他 kind，或跳過修正後的正式 checks。

同樣適用 technical correction、review-fix 與 post-integration correction。新增任務仍須完成 lease 與 Implementer Result；completion 快照不代表驗證通過，之後重跑 controlled checks 與適用的獨立審查。Result 的 amendment 欄位及唯一 final commit trailers 依 [Finalization](finalization.md)。其他 kind 仍依原流程先建立合法修正 commit。
