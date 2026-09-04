# Runtime Interface

Gate 是所有狀態操作的介面。Agent 必須先取得 `next_action`，完成後提交由 Python executable contract 驗證的 JSON payload，再查詢下一步。不得直接編輯 `state.json`、偽造 event 或依 Markdown 推進狀態。

CLI 是敏感 verdict 的唯一寫入介面。Agent payload 可提供觀察、原始證據引用與 requested transition，但 approval validity、Boundary pass、check/Acceptance closure、review independence、human applicability 與 finalization 不能由 `passed: true`、`independent: true` 或其他 Agent boolean 決定。Gate 必須從核准記錄、結構化契約、lease/result identity 與 controlled-runner evidence 自行推導；無法推導即 fail closed。

Gate 推導 verdict 的範圍限於已實作的結構、狀態、ID 與證據規則。核准的 Maintenance 語意宣告仍由 Coordinator 依來源、diff 與 checks 判斷；Agent ID 與實際執行者的對應由 Coordinator 及執行環境維護。Guard 為 true 或兩個 ID 不同，分別不代表語意等價證明或外部身分認證。具體分工見 [Package Authoring](package-authoring.md#package-核准後) 與 [Execution Policy](execution-policy.md#派發與隔離)。

先以 `python3 cogito/scripts/cogito_gate.py --repo <root> next --run-id <ID>` 取得下一步。敏感操作使用專用 subcommand：`prepare-package`、`approve`、`start`、`amend`、`task`、`agent-result`、`run-check`、`verify`、`correction-start`、`correction-complete`、`review-fix-start`、`review-fix-complete`、`integrate`、`retry`、`post-verify`、`human`、`human-approve`、`finalize`、`resume`、`report`；實際參數以各 subcommand 的 `--help` 為準。`implementation-complete` 與 `review-approved` 由通用 `transition` 提交，但 Gate 仍會從已登錄 Result 與 task milestone 推導 verdict。不要透過通用 `transition`、直接呼叫 runner 或直接呼叫 runtime `record()` 寫入其他敏感事件。每個有副作用的呼叫都提供穩定 `--action-id`；只有 `run-check` 產生並登錄的 evidence 可用於 Gate closure。

`render --type workflow` 與 `render --type project` 可由權威 JSON 即時產生 Mermaid 狀態圖或 Slice 相依圖。圖是衍生 view，不得反向編輯或取代 workflow／Project Graph。

`transition --payload-json` 可直接接 JSON object 字串或 UTF-8 JSON 檔案路徑；CLI 優先解析 inline JSON，不會把合法長 JSON 當檔名查詢。若檔名本身恰為合法 JSON（例如 `null`），使用 `./null` 或絕對路徑明確指定檔案。兩種輸入都必須解析為 object；格式、編碼或讀取失敗會回傳結構化錯誤。

Gate 與 Runner 的 JSON 檔案輸入使用 UTF-8；非 UTF-8 或損壞編碼與 JSON 格式錯誤一樣，回傳 exit code `2`，並在 stderr 輸出包含 `ok: false` 與 `error` 的 JSON，不輸出 Python traceback，也不嘗試轉碼或推進流程。

Package／Result JSON 繼續用於保存、交接與顯示，Spec／Plan 維持 Markdown。Package 核准前，從已通過 `prepare-package` 的相同草稿呈現範圍、Spec／Plan 路徑、checks 與風險；核准與執行須綁定同一 candidate hash。顯示層不得補預設值或改寫契約；草稿有變動時重新驗證並確認核准。Python contract 不轉型、不修改輸入；格式錯誤不可透過改寫已凍結資料來掩蓋。

`shared-understanding-ready` 與 `boundary-complete` 在寫入前使用與 Package 相同的驗證：摘要 hash 為 64 位小寫十六進位字串；Boundary decision 是 `single-slice`／`split-required`，evidence 是非空字串陣列。錯型輸入不追加事件、不推進狀態，修正資料後可沿用尚未成功寫入的 action ID。歷史事件不自動改寫；舊 run 的錯誤摘要若仍未確認，可重新發布合法摘要後確認，新 confirmation 不會接受已存的非法 hash。若錯誤 Boundary 已在舊版本完成，尚未核准且已有候選時依規劃輪次重做；其他情況依合法停止／取消與重建決策處理，不手改權威事件。

在 `awaiting-package-approval` 需要不同候選時，先以 `planning begin` 保存來源並停用舊候選核准，再依 `plan`／`boundary`／`requirements` 層級建立同一 run 的新一輪規劃。新版使用目前 `planning_round`，以 `prepare-package` 保存完整候選與文件快照，經獨立 planning review 後才可取得使用者核准。直接替換不同候選會被拒絕；相同操作重送沿用原 ID，不能用舊 ID 提交新內容。候選、覆核與核准都比對輪次及事件版本。操作格式與恢復規則見 [Planning Revisions](planning-revisions.md)。正式核准後改依 Technical Amendment 或 [Replanning](replanning.md) 處理。

## 停止條件與狀態操作

Package 的 `stop_conditions` 由 Coordinator 在派工、驗證與狀態推進前，依目前證據逐項判讀。條件是否成立或證據是否足夠，不由 Gate 的欄位驗證代為決定。Gate 強制執行的是已實作的狀態轉移、重試上限、路徑、hash、DAG 與 evidence 等規則。

停止條件成立或無法排除時，Coordinator 先停止新的派工與流程推進，記錄條件 ID、觀察與證據位置。若 Gate 能載入 run、通過既有 Package 與儲存檢查，且目前尚非終態，透過 `transition --event block` 登錄原因；例如：

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> transition \
  --run-id <ID> --event block \
  --payload-json '{"reason":"SC-001: observed contract drift; evidence: docs/review.md"}' \
  --action-id stop-SC-001
```

相同操作重送沿用同一 action ID 與相同原因；不同發現使用新 ID。已在 `blocked` 時可用新 `block` 事件補記新原因，但 `blocked_from` 保留本次阻塞前的狀態。問題排除後使用 `resume` Gate；恢復會清除本次來源，下一次阻塞再記錄新的來源。舊版連續 `block` 造成的錯誤快取可從既有事件重新還原，不改寫事件歷史。`block` 不會終止已啟動的 subprocess 或 Worker，Coordinator 仍須依其執行介面停止或收尾。

`outcome` 不會放寬 workflow：`cancelled` 需先有取消授權，再以 `disposition begin/stop` 完成停止保存；既有 `transition --event cancel` 也會轉交獨立 DP 並安全釋放執行佔用，操作及待處置範圍見 [成果處置](dispositions.md)；不能只因 Package 寫了 `cancelled` 就自行宣告授權。首次 `awaiting-human` 經合法的 `post-verify` Human Gate 判定進入，人工退回修正也可經專用 review 回到該狀態；若在較早階段需要使用者決策，先 `block` 並說明問題，不直接寫入 `human-review-required` 或修改狀態。`accepted` 與 `cancelled` 均不能再轉移。

## 儲存與復原

- `.cogito/runs/<run-id>/events.jsonl` 是 append-only source of truth；event 包含 sequence、action ID、前一事件 hash、payload，以及新增 Gate 命令的 `request_hash`。此指紋綁定命令名稱與原始輸入，納入 event hash；衍生 verdict 保持在 payload。
- Event JSONL 每一行必須是 JSON object；array、null、字串、數值或布林值會回傳含行號的結構化錯誤與 exit code `2`，不產生 traceback，不跳過該行或修補權威事件，也不改寫 state cache。
- `state.json` 是 events 可重建的 projection。內容不一致時以 events 重建並 fail closed 檢查。
- 每個有副作用的 action 使用穩定 `action_id`。相同命令與輸入的重送返回目前狀態，不重做已完成操作；不同輸入或命令使用相同 ID 一律拒絕。Evidence 比對完整輸入內容，不能只比路徑。`run-check` 的 worktree 路徑先 resolve，再計算指紋。舊事件不改寫；舊 action 缺少指紋時不能推測其原始請求，先確認既有結果再決定後續 action。
- `.cogito/runs/<run-id>/check-actions/` 保存每個 controlled check 的原始請求指紋與開始執行時的契約／check hash，並以檔案鎖串行處理同一 action。證據已發布、事件未寫入時，同一請求可驗證並補登錄既有證據。已開始但沒有完整證據的 attempt 代表結果未知，不自動重跑；應確認程序與外部副作用後才決定是否以新 action 執行，不能刪除 marker 來強制重試。
- Resume Gate 驗證 Package、baseline、Git commits、worktrees 與已登錄 evidence。整合與結案的 Git commit 由 Coordinator 建立；若 commit 已成功而 Gate 事件未記錄，Coordinator 先查詢 run 狀態並確認既有 commit ID 與原始請求，再沿用原始 action ID 與相同參數重送對應 Gate 命令，由 Gate 驗證後補記事件，不再次 merge 或 commit。`resume` 不會掃描 Git trailers 自動尋找 commit 或補記整合／結案事件；無法確認既有 commit 或驗證失敗時，Coordinator 停止推進並保留現場。
- Technical Amendment event 是 append-only overlay。Gate 按序驗證後必須 materialize effective contract 快照與 hash；dispatch 與 runner 只能使用該快照。Controlled runner 以內容 hash 建立新 evidence 檔，既有 evidence 不得覆寫或就地更新。

Agent Result 至少回報 run/task/agent/role、status、base/head commit、changed paths、checks/evidence、risks 與 requested transition。Implementer identity 取自 Gate 發出的 task lease；Reviewer Result 必須逐 task 指向該 implementer，Gate 自行比對兩者不同。Package 只固定 role 與獨立性要求，不預先指定真人或 Agent ID。格式修復最多兩次，只能修結構，不能更改實際 code、evidence 或風險判斷。

Feature／Change／Correction／Documentation 的 Reviewer Result 使用該 task 最新完成 Implementer Result 的 `base_commit`／`head_commit`，不把後續 task 的 commit 範圍併入。該 head 必須仍是目前 worktree HEAD 的祖先；目前 HEAD 與內容須對應本輪 `verification-passed` 採用的正式 evidence。修正後重新驗證，即需重新提交本輪各 task 的 review，不能沿用上一輪核准。審查結束轉移也會重新比對 worktree，拒絕 review 後才加入的未驗證內容。只有 optional checks 的 Package 仍需至少一份本輪已登錄、未竄改且通過的 controlled evidence 作為審查內容依據。

Maintenance 的新 lease 由 Gate 記錄 working tree 與 index 兩份起始快照；Implementer Result 的 `changed_paths` 只列本次任務相對這兩份快照的增量。Gate 另驗整個 checkout 的累積修改是否仍在 Package 範圍內，且不更動使用者 index。請在取得 lease 後才修改或 stage 任務負責的檔案，不要替其他 task stage；一般執行階段的任務間隙若出現未登錄修改，下一個 lease 會拒絕。獨立 Reviewer 使用 Gate 保存的該任務完成快照判定責任，並確認目前內容仍是本輪正式驗證的內容。舊 lease 完全沒有快照時，維持原本保守的 baseline 全範圍驗證，不從目前檔案倒填起始快照；因此舊版多 task run 可能仍需另外處理，不能自動套用新的增量規則。不完整或 Git object 遺失的快照會拒絕操作。

Finalization 先產生不含自身 final commit ID 的 Result 與 Project Graph，以單一 commit 寫入。Gate 比對 final commit 與最後驗證 evidence 的 `worktree_binding.content_tree`，僅允許該 run 的 canonical Result 與 Project Graph 不同；Spec／Plan 必須在最後驗證前更新。舊 evidence 沒有此 tree 或其 Git object 不可用時，需重跑 controlled checks。Commit 成功且內容驗證通過後，Gate 才把實際 ID 追加到 event history 與結案報告並轉為 `accepted`；不得為了讓 Result 記錄自身 commit 而 amend 或重寫該 commit。

Maintenance 修正使用未提交快照：`correction-complete`／`review-fix-complete` 的 `--commit-id` 指定 Start Gate HEAD，checkout 必須仍在原 delivery branch 與相同 HEAD。Gate 追加的 completion payload 包含 `completion_mode: working-tree`、`commit_id`（基線檢查點）與 `content_tree`。Result amendment 將後兩者記為 `base_commit`、`content_tree`，不含 `commit_id`；final commit 帶齊 trailers，結案報告再補實際 amendment commit ID。不可把此格式套用到其他 kind，或跳過修正後的正式 checks；詳見 Execution Policy。

Gate 或 Python contract 不可用、資料驗證失敗、狀態不合法、證據遺失、hash 不符、DAG 有環、超出允許路徑或 action 無法對帳時，Coordinator 必須停止推進並依上述方式處理。命令報錯不等於已寫入 `block` 事件；提交後的快取或權限錯誤也可能發生在事件已落盤之後，應先查詢事件還原的狀態。若 Gate 不可用、歷史無法驗證、Package 漂移或儲存故障使 `block` 本身也被拒絕，保留現場並回報無法登錄阻塞，不編輯 `state.json`，也不宣稱 run 已變為 `blocked`。

## 重新規劃 Gate

`replan` 子命令管理獨立 `RP-*` 單，提供 begin、stop、propose、review、approve、reject、handoff、abandon、status，以及 executor 登錄／停止回報與 advance-adoptions。執行規則與 payload 見 [Replanning](replanning.md)。`next` 在原或新 run 被限制時會回傳 replan ID 與下一階段，不再建議普通 resume。

RP 內的 `toolchain-propose`、`toolchain-review`、`toolchain-approve`、`toolchain-reject` 獨立承接 `.codex/skills/cogito` 的精確內容與 Git 基線，保留原 snapshot，成功後要求重做 RP 提案與覆核；格式、核准邊界與舊 RP 恢復見 [RP 工具接軌](replan-toolchain.md)。

已在 `handing-off` 且尚未開始 successor／transfer 的 RP，使用 `handoff-tool-propose`、`handoff-tool-review`、`handoff-tool-approve`、`handoff-tool-reject` 接軌已提交的 tool-only 修復。這組操作不回退 RP 階段、不清除原產品核准；核准後以原 action ID 重送 `handoff`。


`planning` 子命令處理同一 run 核准前的 begin、review、withdraw、history、compare、recover；與核准後的 `replan` 分開。`history` 可讀取各輪保存的文件內容，`compare --from-round N --to-round M` 輸出前後欄位與文件差異。`recover` 檢查目前綁定資料後回報下一步，發現漂移時拒絕繼續，不默默選用某一版。有效 RP 的未核准 successor 可建立 planning 輪次，但最後仍須以最新候選重新提出 RP proposal、獨立覆核及 RP approval，不能用普通 approve 越過承接流程。

## 人工驗收退回 Gate

`human feedback|triage|start|complete|verify|review|escalate --run-id <ID> --action-id <action>` 管理同一 run 的專用人工退回流程。除 `verify` 使用可重複的 `--evidence <path>`、`review` 不接輸入外，其餘操作使用 `--input <JSON-file>`。不得以通用 transition 偽造 `human-*` 敏感事件。完整 payload、分類及三輪計數規則見 [Human Acceptance](human-acceptance.md)。

修正仍使用 `amend`、task lease、Agent Results 與 controlled `run-check`；每輪 start 消耗人工專用額度，verify 核對最新 delivery 及 effective contract 的 post-integration evidence，review 核對驗證後登錄的本輪獨立 Reviewer Results。Maintenance 同樣需人工退回審查，completion JSON 的 commit_id 使用不變的 Start Gate HEAD 及工作樹快照。未明確完成驗收時回 awaiting-human；有效的本批條件式授權才能進 finalizing，最後仍由 finalize 驗證結案。

`human escalate` 登錄阻塞與升級，不會直接終止外部執行者；Coordinator 必須停止實際程序並依 RP 留存停止回報。已升級或額度耗盡不能透過普通 resume 取得修正或自動結案權限。人工來源 RP 的 successor 保留重新人工驗收要求。

## 階段提交

在 `finalizing` 使用 `delivery-summary --run-id <ID>` 取得 Result 的 `delivery_summary` 欄位，查詢不建立 commit 或追加事件。Gate 從同一份事件快照產生摘要，`finalize` 再與已提交 Result 逐項核對。啟用階段提交的 run 必填，舊 run 可省略；若提供也須與事件相符。`report` 讀取 final commit 內的摘要，並另外提供 final commit ID，不從目前工作副本重建或改寫 Result。

一般 run 的 `init` 預設啟用 `stage_commits`，有效 RP successor 保留既有 frozen-delivery 協定。Shared Understanding confirmation、Boundary complete 與 Package approval 後，`next` 先回傳 `commit-stage-artifacts`；未登記對應 commit 前拒絕推進。`checkpoint prepare` 產生精確路徑清單與不可變階段紀錄，Coordinator 建立本地 commit，再以 `checkpoint record --commit-id ... --action-id ...` 交給 Gate 驗證。操作與相容性詳見 [Stage Commits](stage-commits.md)。
