# Execution Policy

本檔按 Start Gate → Task → 正式驗證 → 獨立審查 → 整合的順序說明操作。依目前 `next_action` 閱讀對應小節；狀態轉移仍由 Gate 決定。共通 CLI、action ID 與停止／重送規則見 [Runtime Interface](runtime-interface.md)。

## Start Gate 前

準備階段依 [Stage Commits](stage-commits.md) 分別保存已確認摘要、Boundary 與已核准 Package。這些 commits 在 Start Gate 前完成；Maintenance 的單一交付 commit 從 Start Gate HEAD 起算。

Package checkpoint 登記成功後才通過 Start Gate，再派工。Maintenance 與 Documentation 的適用條件先依 [Package Authoring](package-authoring.md#選擇-package-類型) 判斷。

## 派發與隔離

Coordinator 只派發 Project Graph 中依賴已滿足的 task，同時最多三個 Slice Worker；同一 Slice 同時只能有一個 active lease。Feature／Change／Correction Worker 各用專用 branch/worktree，且首次派發必須以當下最新 delivery HEAD 為起點。跨 Slice 相依只有在上游到達 `integrated` milestone 後才滿足；同 Slice 內部 task 依序完成；Atomic Task 依下一節完成後才開始下一項。同一 Implementer 可連續處理，無須每項重新建立代理。只有 Coordinator 可串行整合到固定 delivery branch。

## 完成 Task

### Atomic Task

Atomic Task 依下列順序完成，才能開始下一項 Task：

1. 登記 `task leased`，再登記 `task running`。
2. 實作該 Task，使用 `run-check` 執行其 targeted checks。
3. 建立該 Task 的獨立 commit。
4. 以 `agent-result` 登錄 Implementer Result，再登記 `task complete`。

也可先 commit 再檢查；提交前 evidence 只有在提交後內容完全相同時才有效。Result 的 `evidence` 精確列出 Task `check_ids` 的 controlled evidence 路徑。Gate 驗證非空、單一 parent 的 commit，parent 必須是 lease base；拒絕未提交產品內容、過期或不完整證據。

### Maintenance 任務快照

Maintenance 的新 lease 由 Gate 記錄 working tree 與 index 兩份起始快照；Implementer Result 的 `changed_paths` 完整列出本次任務相對這兩份快照的產品增量，包括 staged、unstaged 與 untracked 路徑。不能因 base/head 相同或已 staged 而省略；rename 同時列原路徑刪除與新路徑新增。Gate 另驗整個 checkout 的累積修改是否仍在 Package 範圍內，且不更動使用者 index。請在取得 lease 後才修改或 stage 任務負責的檔案，不要替其他 task stage；一般執行階段的任務間隙若出現未登錄修改，下一個 lease 會拒絕。獨立 Reviewer 使用 Gate 保存的該任務完成快照判定責任，並確認目前內容仍是本輪正式驗證的內容。

Maintenance 在目前 delivery checkout 執行，保留 Start Gate HEAD，任務與修正先保存未提交快照；最後以 [Finalization](finalization.md) 規定的一個交付 commit 保存所有已驗證內容。Documentation 不自動取得 Maintenance 的單一 commit 規則或審查豁免。

### 登錄 Agent Result

Agent Result 至少回報 run/task/agent/role、status、base/head commit、changed paths、checks/evidence、risks 與 requested transition。Implementer identity 取自 Gate 發出的 task lease；Reviewer Result 必須逐 task 指向該 implementer，Gate 自行比對兩者不同。Package 只固定 role 與獨立性要求，不預先指定真人或 Agent ID。格式修復最多兩次，只能修結構，不能更改實際 code、evidence 或風險判斷。

### Task 中斷或檢查失敗

尚未發布且尚未登錄完成的 Atomic Task 暫存 commit 若檢查失敗，可在原 lease base 與 paths 內整理成一個 commit；保留舊 evidence 並重跑相關檢查。已發布或已登錄完成的 commits 不得改寫。

Atomic 下一個 Task 取得 lease 前仍會檢查 checkout，避免任務間隙混入未登錄修改。正式檢查失敗時留在該 Task 修正並以新 action ID 重跑，不能先宣告完成。一般 run 的 block／resume 保留原 lease 與證據歷史。Task 本身走 `blocked → pending → leased` 時保留原 base，允許原 paths 內未完成的修改或尚未登錄的一個 commit，但須在新 lease 後重新執行 targeted checks；已登錄的完成 commit 不得改寫，也不能吸收其他 Task 的變更。

### 舊 Maintenance lease

舊 lease 完全沒有快照時，維持原本保守的 baseline 全範圍驗證，不從目前檔案倒填起始快照；因此舊版多 task run 可能仍需另外處理，不能自動套用新的增量規則。不完整或 Git object 遺失的快照會拒絕操作。

## 正式驗證

### 選擇與執行 checks

Atomic Package 本地只執行變更行為與受影響依賴的相關檢查，完整 regression 交給 CI，不固定在本地執行完整 build／lint／migration；其中任一項若是 Task 或整合的必要驗證，仍列為相關 check。Coordinator 在 Plan 記錄選測理由，影響擴大時依 Amendment 補充，不只看哪些測試檔被修改。Gate 不自動推算測試影響範圍，也不以本地通過宣稱 CI 已通過；合併依既有 CI 要求，未執行／等待／失敗如實回報。

- 所有正式 checks 由 controlled runner 以 argv array 執行，不預設 shell；cwd 限於 worktree，套用 timeout、輸出上限、redaction 與 env allowlist。
- `fetch_allowed` 是 Coordinator 應遵守的授權政策；runner 沒有網路隔離機制，設為 false 不會阻止 check 程序連網。需要網路限制時，由執行環境提供並驗證。

Gate 先 materialize 核准 Package 與有序 Amendments，runner 只使用該 effective contract。check 前後的工作樹快照必須相同；HEAD／內容／契約或 check definition 綁定不同時，舊 evidence 不再適用。

runner 只保存有界 head/tail 輸出。合計輸出超過凍結的 `max_check_output_bytes` 時終止檢查並判定失敗；`output_limit_exceeded` 或 `termination_degraded` 不得當成通過 evidence。缺少目前必要 evidence 欄位時重新執行，不補寫舊證據。程序等待、快照與發布細節供維護者查閱 [Runtime Internals](runtime-internals.md)。

### 本波驗證與整合後驗證

先確認 `task_delivery`。以下表格與跨狀態證據沿用規則只適用 `task_delivery: "atomic"`。非 Atomic（包含目前的 Maintenance／Documentation Mini Package）依本輪完成事件與驗證階段檢查全部 required checks；不能只因 HEAD／內容／契約相同，就沿用完成事件之前的 evidence。歷史 Package 也保留其原驗證規則。

Atomic 本波 Task 完成後，依 Gate 執行 `verify`；整合全部完成後再執行 `post-verify`。兩者核對的內容不同：

| 操作 | evidence 對象 |
|---|---|
| Task Result | 精確涵蓋該 Task 的 `check_ids`，保存該 Task 的歷史驗證 |
| `verify --evidence` | 本波每個 checkout 最新完整內容；不能拿早期 Task evidence 代替目前內容 |
| `post-verify --evidence` | 最新 delivery HEAD 的 required integration checks，至少一項作為最後內容依據 |

早期 Task 的 required evidence 已由 Result 驗證並保留，不要求在後續 HEAD 重跑。最後 Task 的提交前 evidence 若與提交後完整內容一致，可用於本輪驗證及該 Task Result 綁定的 review。相同 HEAD、完整 content tree 與 effective contract 的 evidence 可跨狀態沿用；任一綁定變更時重跑必要的相關 checks。

`Result.checks` 記錄最後整合驗證採用的 checks；Task checks 保留在 Implementer Results 與 delivery summary。不建立純跑測試的 Task 或空 commit。舊 Package 維持原驗證規則。

### Check 重送

Controlled check 重送使用同一 action_id 與相同輸入；同 ID 不得改 check、worktree 或執行契約。已發布 evidence 可在事件追加失敗後補登錄。若 attempt 已開始但沒有完整 evidence，結果視為未知，先確認程序與外部副作用再處理，不以自動重跑假裝恢復成功。

## 獨立審查

完成本波正式驗證後，由不同 Agent 逐 Task 進行獨立 review。Gate 逐 task 比對 Implementer task lease 的 `agent_id`、Reviewer Result 的 `reviewed_implementer` 與不同的 reviewer `agent_id`，由已登錄 Result 推導審查完成情況，不接受 Agent 回報的 `independent: true`，也不在 Package 預先綁定 Agent 身分。Coordinator 必須指派實際不同的 Agent，並維持穩定且唯一的 ID；Gate 的 ID 比對不提供外部身分驗證。Reviewer 可建議核准、提出 Package 內修正或升級風險，但不得移除 human predicate；最終 review verdict 由 Gate 計算。Maintenance 只有在 Mini Package 的低風險宣告已有足夠證據並經核准、且 Gate 的檢查通過時可豁免；語意判斷與機械檢查的分工見 [Package Authoring](package-authoring.md#選擇-package-類型)。

Feature／Change／Correction／Documentation 的 Reviewer Result 使用該 task 最新完成 Implementer Result 的 `base_commit`／`head_commit`，不把後續 task 的 commit 範圍併入。該 head 必須仍是目前 worktree HEAD 的祖先；目前 HEAD 與內容須對應本輪 `verification-passed` 採用的正式 evidence；atomic 模式也接受最後 Task Result 綁定的相同內容提交前證據。修正後重新驗證，即需重新提交本輪各 task 的 review，不能沿用上一輪核准。審查結束轉移也會重新比對 worktree，拒絕 review 後才加入的未驗證內容。只有 optional checks 的 Package 仍需至少一份本輪已登錄、未竄改且通過的 controlled evidence 作為審查內容依據。

## 串行整合

每一執行波依 `complete -> verified -> reviewed -> integrated` 推進；Reviewer closure 逐 task 計算，不能用一筆結果關閉整個 Slice。Coordinator 串行記錄每個 Slice 的 source heads、前一 delivery head 與 integration commit。相依 Slice 只在這一步完成後解鎖。

Atomic 整合另以 Git `merge-tree --write-tree` 比對前一 delivery HEAD 與已審查 Task tip 的正常合併結果，拒絕在 integration commit 夾帶產品修改或撤銷已完成 Task；僅沿用 canonical Package／Project Graph 的精確控制文件例外。需要支援此命令的 Git。合併衝突或額外修改不能假裝成已驗證整合：保留現場、登錄 block，依既有 RP 重新安排需修改的工作；本版不新增整合修正狀態。一般無衝突的串行、平行 Slice 合併與 fast-forward 均可沿用。

整合 Gate 除了檢查 source heads 與祖先關係，也比對前一 delivery HEAD 到 integration commit 的實際差異，拒絕超出 Package `approved_paths` 的產品檔案。此範圍包含合法 Technical Amendment 的修正，不另外縮限成原 task 路徑聯集。路徑以 NUL 分隔並將 rename 視為原路徑刪除與新路徑新增，檢查不改動 index。

### 核准路徑與控制文件

核准後需隨合法 commit 保存的控制文件只按精確路徑例外處理：本 run 的凍結 Package 必須內容相符，整合時的 Project Graph 必須符合核准 hash；Package 指定的 Spec／Plan 可依既有政策在最後驗證前更新；source registry 中 `adopted`／`updated` 的來源若依賴控制文件例外提交，必須符合凍結的原始 bytes hash，已在 `approved_paths` 的來源則可按核准範圍更新。其他文件不能因位於 `docs/` 就取得例外。

### 整合後的下一步

所有 Slice 整合完成後，在最新 delivery branch 驗證 post-integration checks；失敗共用 correction 預算，修正完直接回到 post-integration verification，不重做已完成的 integration。

沒有適用的人工作業或判斷時直接 `finalizing`。有適用 `HI-*`、`HA-*` 或高風險 hotspot 時，彙整進入 `awaiting-human` 門閥。人工退回可修正後再次回到此門閥；人工來源 RP 的 successor 即使沒有這些 predicate，也須重新人工驗收。

人工退回依 [Human Acceptance](human-acceptance.md) 的分類、修正與結案授權操作；Maintenance 人工修正仍需本輪獨立 review。Gate 進入 `finalizing` 後改讀 [Finalization](finalization.md)。

## 自動修正

Coordinator 依 Package 的 `stop_conditions` 與執行證據判讀是否應停止。這些條件是凍結的政策文字，Gate 不會自動求值或依 `outcome` 轉移狀態；停止派工、登錄 `block`、取消授權與 Human Gate 的處理依 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash；commit 加上 `Cogito-Amendment: <ID>` trailer。

Technical Amendment 只能在已核准路徑內增加 checks、tests、tasks，或修正內部實作；新增 check 的 `env_allowlist` 不得超出 Package 凍結的 `allowed_environment`。不得刪除或降級 required checks、擴張路徑、改 Acceptance、公開 API、資料模型、安全邊界、依賴或 DAG。有效契約 hash 由 base Package 與有序 amendments 計算；相關 commit 使用 `Cogito-Amendment` trailer。

Amendment 只能單調增加或加強工作。超出上述邊界時依 [Replanning](replanning.md) 限制全體執行、保存現場，再提出新的核准契約與 successor 承接方案。

Atomic 的產品 correction 必須使用新增 Task；只增加檢查可直接重新 verify，不開啟無任務的產品修正。新增任務以 `depends_on` 指定前置任務，可引用 base Package、先前 Amendment 或同批新增的任務。Gate 在追加事件前合併完整任務圖，拒絕未知節點、自我依賴與循環；effective contract 的 edges 會包含這些依賴，原始文件與 hash 不變。追加不能修改既有任務依賴或新增跨 Slice 的依賴關係；沿用已核准跨 Slice 關係時，前置任務必須已 `integrated`，避免修正流程等待自身完成後才能進行的整合。

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
