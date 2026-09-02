# Runtime Interface

Gate 是所有狀態操作的介面。Agent 必須先取得 `next_action`，完成後提交由 Python executable contract 驗證的 JSON payload，再查詢下一步。不得直接編輯 `state.json`、偽造 event 或依 Markdown 推進狀態。

CLI 是敏感 verdict 的唯一寫入介面。Agent payload 可提供觀察、原始證據引用與 requested transition，但 approval validity、Boundary pass、check/Acceptance closure、review independence、human applicability 與 finalization 不能由 `passed: true`、`independent: true` 或其他 Agent boolean 決定。Gate 必須從核准記錄、結構化契約、lease/result identity 與 controlled-runner evidence 自行推導；無法推導即 fail closed。

先以 `python3 cogito/scripts/cogito_gate.py --repo <root> next --run-id <ID>` 取得下一步。敏感操作使用專用 subcommand：`prepare-package`、`approve`、`start`、`amend`、`task`、`agent-result`、`run-check`、`verify`、`correction-start`、`correction-complete`、`review-fix-start`、`review-fix-complete`、`integrate`、`retry`、`post-verify`、`human-approve`、`finalize`、`resume`、`report`；實際參數以各 subcommand 的 `--help` 為準。`implementation-complete` 與 `review-approved` 由通用 `transition` 提交，但 Gate 仍會從已登錄 Result 與 task milestone 推導 verdict。不要透過通用 `transition`、直接呼叫 runner 或直接呼叫 runtime `record()` 寫入其他敏感事件。每個有副作用的呼叫都提供穩定 `--action-id`；只有 `run-check` 產生並登錄的 evidence 可用於 Gate closure。

`render --type workflow` 與 `render --type project` 可由權威 JSON 即時產生 Mermaid 狀態圖或 Slice 相依圖。圖是衍生 view，不得反向編輯或取代 workflow／Project Graph。

Package／Result JSON 繼續用於保存、交接與顯示，Spec／Plan 維持 Markdown。Package 核准前，從已通過 `prepare-package` 的相同草稿呈現範圍、Spec／Plan 路徑、checks 與風險；核准與執行須綁定同一 candidate hash。顯示層不得補預設值或改寫契約；草稿有變動時重新驗證並確認核准。Python contract 不轉型、不修改輸入；格式錯誤不可透過改寫已凍結資料來掩蓋。

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

`outcome` 不會放寬 workflow：`cancelled` 需先有取消授權，再以 `transition --event cancel` 提交授權結果；不能只因 Package 寫了 `cancelled` 就自行宣告授權。`awaiting-human` 只能經合法的 `post-verify` Human Gate 判定進入；若在較早階段需要使用者決策，先 `block` 並說明問題，不直接寫入 `human-review-required` 或修改狀態。`accepted` 與 `cancelled` 均不能再轉移。

## 儲存與復原

- `.cogito/runs/<run-id>/events.jsonl` 是 append-only source of truth；event 包含 sequence、action ID、前一事件 hash、payload，以及新增 Gate 命令的 `request_hash`。此指紋綁定命令名稱與原始輸入，納入 event hash；衍生 verdict 保持在 payload。
- `state.json` 是 events 可重建的 projection。內容不一致時以 events 重建並 fail closed 檢查。
- 每個有副作用的 action 使用穩定 `action_id`。相同命令與輸入的重送返回目前狀態，不重做已完成操作；不同輸入或命令使用相同 ID 一律拒絕。Evidence 比對完整輸入內容，不能只比路徑。`run-check` 的 worktree 路徑先 resolve，再計算指紋。舊事件不改寫；舊 action 缺少指紋時不能推測其原始請求，先確認既有結果再決定後續 action。
- `.cogito/runs/<run-id>/check-actions/` 保存每個 controlled check 的原始請求指紋與開始執行時的契約／check hash，並以檔案鎖串行處理同一 action。證據已發布、事件未寫入時，同一請求可驗證並補登錄既有證據。已開始但沒有完整證據的 attempt 代表結果未知，不自動重跑；應確認程序與外部副作用後才決定是否以新 action 執行，不能刪除 marker 來強制重試。
- Resume Gate 驗證 Package、baseline、Git commits、worktrees 與已登錄 evidence。整合與結案的 Git commit 由 Coordinator 建立；若 commit 已成功而 Gate 事件未記錄，Coordinator 先查詢 run 狀態並確認既有 commit ID 與原始請求，再沿用原始 action ID 與相同參數重送對應 Gate 命令，由 Gate 驗證後補記事件，不再次 merge 或 commit。`resume` 不會掃描 Git trailers 自動尋找 commit 或補記整合／結案事件；無法確認既有 commit 或驗證失敗時，Coordinator 停止推進並保留現場。
- Technical Amendment event 是 append-only overlay。Gate 按序驗證後必須 materialize effective contract 快照與 hash；dispatch 與 runner 只能使用該快照。Controlled runner 以內容 hash 建立新 evidence 檔，既有 evidence 不得覆寫或就地更新。

Agent Result 至少回報 run/task/agent/role、status、base/head commit、changed paths、checks/evidence、risks 與 requested transition。Implementer identity 取自 Gate 發出的 task lease；Reviewer Result 必須逐 task 指向該 implementer，Gate 自行比對兩者不同。Package 只固定 role 與獨立性要求，不預先指定真人或 Agent ID。格式修復最多兩次，只能修結構，不能更改實際 code、evidence 或風險判斷。

Finalization 先產生不含自身 final commit ID 的 Result 與 Project Graph，以單一 commit 寫入。Gate 比對 final commit 與最後驗證 evidence 的 `worktree_binding.content_tree`，僅允許該 run 的 canonical Result 與 Project Graph 不同；Spec／Plan 必須在最後驗證前更新。舊 evidence 沒有此 tree 或其 Git object 不可用時，需重跑 controlled checks。Commit 成功且內容驗證通過後，Gate 才把實際 ID 追加到 event history 與結案報告並轉為 `accepted`；不得為了讓 Result 記錄自身 commit 而 amend 或重寫該 commit。

Gate 或 Python contract 不可用、資料驗證失敗、狀態不合法、證據遺失、hash 不符、DAG 有環、超出允許路徑或 action 無法對帳時，Coordinator 必須停止推進並依上述方式處理。命令報錯不等於已寫入 `block` 事件；提交後的快取或權限錯誤也可能發生在事件已落盤之後，應先查詢事件還原的狀態。若 Gate 不可用、歷史無法驗證、Package 漂移或儲存故障使 `block` 本身也被拒絕，保留現場並回報無法登錄阻塞，不編輯 `state.json`，也不宣稱 run 已變為 `blocked`。
