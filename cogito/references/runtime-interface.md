# Runtime Interface

Gate 是所有狀態操作的介面。Agent 必須先取得 `next_action`，完成後提交由 Python executable contract 驗證的 JSON payload，再查詢下一步。不得直接編輯 `state.json`、偽造 event 或依 Markdown 推進狀態。

CLI 是敏感 verdict 的唯一寫入介面。Agent payload 可提供觀察、原始證據引用與 requested transition，但 approval validity、Boundary pass、check/Acceptance closure、review independence、human applicability 與 finalization 不能由 `passed: true`、`independent: true` 或其他 Agent boolean 決定。Gate 必須從核准記錄、結構化契約、lease/result identity 與 controlled-runner evidence 自行推導；無法推導即 fail closed。

先以 `python3 cogito/scripts/cogito_gate.py --repo <root> next --run-id <ID>` 取得下一步。敏感操作使用專用 subcommand：`prepare-package`、`approve`、`start`、`amend`、`task`、`agent-result`、`run-check`、`verify`、`correction-start`、`correction-complete`、`review-fix-start`、`review-fix-complete`、`integrate`、`retry`、`post-verify`、`human-approve`、`finalize`、`resume`、`report`；實際參數以各 subcommand 的 `--help` 為準。`implementation-complete` 與 `review-approved` 由通用 `transition` 提交，但 Gate 仍會從已登錄 Result 與 task milestone 推導 verdict。不要透過通用 `transition`、直接呼叫 runner 或直接呼叫 runtime `record()` 寫入其他敏感事件。每個有副作用的呼叫都提供穩定 `--action-id`；只有 `run-check` 產生並登錄的 evidence 可用於 Gate closure。

`render --type workflow` 與 `render --type project` 可由權威 JSON 即時產生 Mermaid 狀態圖或 Slice 相依圖。圖是衍生 view，不得反向編輯或取代 workflow／Project Graph。

Package／Result JSON 繼續用於保存、交接與顯示，Spec／Plan 維持 Markdown。Package 核准前，從已通過 `prepare-package` 的相同草稿呈現範圍、Spec／Plan 路徑、checks 與風險；核准與執行須綁定同一 candidate hash。顯示層不得補預設值或改寫契約；草稿有變動時重新驗證並確認核准。Python contract 不轉型、不修改輸入；格式錯誤不可透過改寫已凍結資料來掩蓋。

## 儲存與復原

- `.cogito/runs/<run-id>/events.jsonl` 是 append-only source of truth；event 包含 sequence、action ID、前一事件 hash 與 payload。
- `state.json` 是 events 可重建的 projection。內容不一致時以 events 重建並 fail closed 檢查。
- 每個有副作用的 action 使用穩定 `action_id`。重送相同 action 必須冪等；payload 不同則阻塞。
- Resume Gate 驗證 Package/effective contract hashes、baseline、Git commits、worktrees、evidence bindings 與未完成 action。crash window 以 action ID 及 commit trailer 對帳。
- Technical Amendment event 是 append-only overlay。Gate 按序驗證後必須 materialize effective contract 快照與 hash；dispatch 與 runner 只能使用該快照。Controlled runner 以內容 hash 建立新 evidence 檔，既有 evidence 不得覆寫或就地更新。

Agent Result 至少回報 run/task/agent/role、status、base/head commit、changed paths、checks/evidence、risks 與 requested transition。Implementer identity 取自 Gate 發出的 task lease；Reviewer Result 必須逐 task 指向該 implementer，Gate 自行比對兩者不同。Package 只固定 role 與獨立性要求，不預先指定真人或 Agent ID。格式修復最多兩次，只能修結構，不能更改實際 code、evidence 或風險判斷。

Finalization 先產生不含自身 final commit ID 的 Result 與 Project Graph，以單一 commit 寫入。Commit 成功後，Gate 才把實際 ID 追加到 event history 與結案報告並轉為 `accepted`；不得為了讓 Result 記錄自身 commit 而 amend 或重寫該 commit。

Gate 或 Python contract 不可用、資料驗證失敗、狀態不合法、證據遺失、hash 不符、DAG 有環、超出允許路徑或 action 無法對帳時，一律 `blocked`；不要用自然語言推測下一狀態。
