# Runtime Interface

Gate 是所有狀態操作的介面。Agent 必須先取得 `next_action`，完成後提交由 Python executable contract 驗證的 JSON payload，再查詢下一步。不得直接編輯 `state.json`、偽造 event 或依 Markdown 推進狀態。

CLI 是敏感 verdict 的唯一寫入介面。Agent payload 可提供觀察、原始證據引用與 requested transition，但 approval validity、Boundary pass、check/Acceptance closure、review independence、human applicability 與 finalization 不能由 `passed: true`、`independent: true` 或其他 Agent boolean 決定。Gate 必須從核准記錄、結構化契約、lease/result identity 與 controlled-runner evidence 自行推導；無法推導即 fail closed。

Gate 推導 verdict 的範圍限於已實作的結構、狀態、ID 與證據規則。核准的 Maintenance 語意宣告仍由 Coordinator 依來源、diff 與 checks 判斷；Agent ID 與實際執行者的對應由 Coordinator 及執行環境維護。Guard 為 true 或兩個 ID 不同，分別不代表語意等價證明或外部身分認證。具體分工見 [Package Authoring](package-authoring.md#選擇-package-類型) 與 [Execution Policy](execution-policy.md#獨立審查)。

## 呼叫 CLI

先以 `python3 cogito/scripts/cogito_gate.py --repo <root> next --run-id <ID>` 取得下一步。敏感操作使用專用 subcommand：`prepare-package`、`approve`、`start`、`amend`、`task`、`agent-result`、`run-check`、`verify`、`correction-start`、`correction-complete`、`review-fix-start`、`review-fix-complete`、`integrate`、`retry`、`post-verify`、`human`、`human-approve`、`finalize`、`resume`、`report`；實際參數以各 subcommand 的 `--help` 為準。`implementation-complete` 與 `review-approved` 由通用 `transition` 提交，但 Gate 仍會從已登錄 Result 與 task milestone 推導 verdict。不要透過通用 `transition`、直接呼叫 runner 或直接呼叫 runtime `record()` 寫入其他敏感事件。每個有副作用的呼叫都提供穩定 `--action-id`；只有 `run-check` 產生並登錄的 evidence 可用於 Gate closure。

`render --type workflow` 與 `render --type project` 可由權威 JSON 即時產生 Mermaid 狀態圖或 Slice 相依圖。圖是衍生 view，不得反向編輯或取代 workflow／Project Graph。

## JSON 輸入與顯示

`transition --payload-json` 可直接接 JSON object 字串或 UTF-8 JSON 檔案路徑；CLI 優先解析 inline JSON，不會把合法長 JSON 當檔名查詢。若檔名本身恰為合法 JSON（例如 `null`），使用 `./null` 或絕對路徑明確指定檔案。兩種輸入都必須解析為 object；格式、編碼或讀取失敗會回傳結構化錯誤。

Gate 與 Runner 的 JSON 檔案輸入使用 UTF-8；非 UTF-8 或損壞編碼與 JSON 格式錯誤一樣，回傳 exit code `2`，並在 stderr 輸出包含 `ok: false` 與 `error` 的 JSON，不輸出 Python traceback，也不嘗試轉碼或推進流程。

Package／Result JSON 繼續用於保存、交接與顯示，Spec／Plan 維持 Markdown。Package 核准前，從已通過 `prepare-package` 的相同草稿呈現範圍、Spec／Plan 路徑、checks 與風險；核准與執行須綁定同一 candidate hash。顯示層不得補預設值或改寫契約；草稿有變動時重新驗證並確認核准。Python contract 不轉型、不修改輸入；格式錯誤不可透過改寫已凍結資料來掩蓋。

## 儲存與復原

`init` 在 Git repository 的本地 `info/exclude` 補入 `/.cogito/runs/` 與 `/.cogito/worktrees/`；linked worktree 使用共用的 Git 設定位置。預設規則置於既有內容之前，保留原始內容與使用者例外的優先權，重複初始化不重複加入。不修改 `.gitignore`，也不取消追蹤已提交的檔案；`status`／`report` 不安裝這些規則。非 Git 目錄仍可使用 `init --no-stage-commits`。

- `.cogito/runs/<run-id>/events.jsonl` 是 append-only source of truth；event 包含 sequence、action ID、前一事件 hash、payload，以及新增 Gate 命令的 `request_hash`。此指紋綁定命令名稱與原始輸入，納入 event hash；衍生 verdict 保持在 payload。
- Event JSONL 每一行必須是 JSON object；array、null、字串、數值或布林值會回傳含行號的結構化錯誤與 exit code `2`，不產生 traceback，不跳過該行或修補權威事件，也不改寫 state cache。
- `state.json` 是 events 可重建的 projection。內容不一致時以 events 重建並 fail closed 檢查。
- 每個有副作用的 action 使用穩定 `action_id`。相同命令與輸入的重送返回目前狀態，不重做已完成操作；不同輸入或命令使用相同 ID 一律拒絕。Evidence 比對完整輸入內容，不能只比路徑。`run-check` 的 worktree 路徑先 resolve，再計算指紋。舊事件不改寫；舊 action 缺少指紋時不能推測其原始請求，先確認既有結果再決定後續 action。
- `.cogito/runs/<run-id>/check-actions/` 保存每個 controlled check 的原始請求指紋與開始執行時的契約／check hash，並以檔案鎖串行處理同一 action。證據已發布、事件未寫入時，同一請求可驗證並補登錄既有證據。已開始但沒有完整證據的 attempt 代表結果未知，不自動重跑；應確認程序與外部副作用後才決定是否以新 action 執行，不能刪除 marker 來強制重試。
- Resume Gate 驗證 Package、baseline、Git commits、worktrees 與已登錄 evidence。整合與結案的 Git commit 由 Coordinator 建立；若 commit 已成功而 Gate 事件未記錄，Coordinator 先查詢 run 狀態並確認既有 commit ID 與原始請求，再沿用原始 action ID 與相同參數重送對應 Gate 命令，由 Gate 驗證後補記事件，不再次 merge 或 commit。`resume` 不會掃描 Git trailers 自動尋找 commit 或補記整合／結案事件；無法確認既有 commit 或驗證失敗時，Coordinator 停止推進並保留現場。
- Technical Amendment event 是 append-only overlay。Gate 按序驗證後必須 materialize effective contract 快照與 hash；dispatch 與 runner 只能使用該快照。Controlled runner 以內容 hash 建立新 evidence 檔，既有 evidence 不得覆寫或就地更新。

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

Gate 或 Python contract 不可用、資料驗證失敗、狀態不合法、證據遺失、hash 不符、DAG 有環、超出允許路徑或 action 無法對帳時，Coordinator 必須停止推進並依上述方式處理。命令報錯不等於已寫入 `block` 事件；提交後的快取或權限錯誤也可能發生在事件已落盤之後，應先查詢事件還原的狀態。若 Gate 不可用、歷史無法驗證、Package 漂移或儲存故障使 `block` 本身也被拒絕，保留現場並回報無法登錄阻塞，不編輯 `state.json`，也不宣稱 run 已變為 `blocked`。

## 各流程操作入口

以下流程各自保存完整步驟；本檔的 action ID、資料完整性與停止規則共用，不另外重述其狀態機。

| 目前工作 | 操作文件 |
|---|---|
| 摘要、Boundary、Package 準備與核准 | [Package Authoring](package-authoring.md)，摘要依 [Grilling Workflow](grilling-workflow.md) |
| Task、checks、review、integration、Technical Amendment | [Execution Policy](execution-policy.md) |
| 核准前規劃修訂 | [Planning Revisions](planning-revisions.md) |
| 已核准契約重新規劃與承接 | [Replanning](replanning.md) |
| RP 途中工具更新 | [RP Toolchain](replan-toolchain.md) |
| 人工驗收退回 | [Human Acceptance](human-acceptance.md) |
| 取消與成果處置 | [Dispositions](dispositions.md) |
| 準備階段 checkpoint | [Stage Commits](stage-commits.md) |
| 結案、回報及 cleanup 重試 | [Finalization](finalization.md) |
