# Runtime Interface

Gate 是所有狀態操作的介面。Agent 必須先取得 `next_action`，完成後提交由 Python executable contract 驗證的 JSON payload，再查詢下一步。不得直接編輯 `state.json`、偽造 event 或依 Markdown 推進狀態。

CLI 是敏感 verdict 的唯一寫入介面。Agent payload 可提供觀察、原始證據引用與 requested transition，但 approval validity、Boundary pass、check/Acceptance closure、review independence、human applicability 與 finalization 不能由 `passed: true`、`independent: true` 或其他 Agent boolean 決定。Gate 必須從核准記錄、結構化契約、lease/result identity 與 controlled-runner evidence 自行推導；無法推導即 fail closed。

Gate 推導 verdict 的範圍限於已實作的結構、狀態、ID 與證據規則。核准的 Maintenance 語意宣告仍由 Coordinator 依來源、diff 與 checks 判斷；Agent ID 與實際執行者的對應由 Coordinator 及執行環境維護。Guard 為 true 或兩個 ID 不同，分別不代表語意等價證明或外部身分認證。具體分工見 [Package Authoring](package-authoring.md#選擇-package-類型) 與 [Execution Policy](execution-policy.md#獨立審查)。

## 呼叫 CLI

以 `python3 cogito/scripts/cogito_gate.py --repo <root> next --run-id <ID>` 取得下一步，依操作文件使用專用 subcommand，參數以其 `--help` 為準。`implementation-complete` 與 `review-approved` 使用通用 `transition`，Gate 仍從已登錄 Result 與 task milestone 推導 verdict；其他敏感事件不得透過通用 transition、直接呼叫 runner 或 runtime `record()` 寫入。只有 `run-check` 產生並登錄的 evidence 可用於 Gate closure。

每個變更 Gate 事件歷史的 action 使用穩定 `--action-id`；只產生草稿的命令依所屬流程處理。相同命令與完整輸入重送不重做已完成操作，不同命令或輸入不得使用同一 ID。舊 action 缺少 request fingerprint 時先確認既有結果，不推測原始請求。發生部分失敗先查 Gate 與既有成果，不先重做 Git 或外部操作。

## JSON 輸入與顯示

Atomic 執行與審查修正的 `next.operations` 提供絕對 repo/script 路徑、`cwd`、argv、已知 `input`、尚待 Agent 判斷的 `required_inputs` 與 `blockers`。合併已知輸入及必要判斷，存成 JSON 檔再填入 argv；`<input.json>`／`<action-id>` 等佔位符不可原樣執行。`<new-action-id>`、`<retry-action-id>`、`<replacement-action-id>` 分別填不同 ID；已填實值的恢復命令沿用原值。提示不構成授權，執行時仍重新驗證。

一般 Run mutation 成功時，`data` 回傳 `run_id`、目前 `state`、`sequence` 與 `last_event_hash`，不含完整歷史或 `next`。需要繼續工作時另查 `next`，由 Gate 統一決定 RP／DP、checkpoint、human、path amendment、fixed action 與 recovery 等路由優先順序。只有明確診斷完整 projection 時才查 `status`；舊狀態從 append-only events 核對，不從 mutation stdout 推測。重送 receipt 反映目前權威 projection，不保證重現原 action 當時的 bytes。

`ok: true` 與 CLI exit code `0` 只表示 Gate 操作成功；`run-check` 是否通過看 `check_status`，不能把 evidence 登錄成功當成 check 通過。驗證與 check recovery 提示依 [正式驗證](execution-policy.md#正式驗證)，整合選項依 [串行整合](execution-policy.md#串行整合)。`task-finish` 與帶 `amendment` 的 `review-fix-start --input` 保留 commit、evidence、amendment、task 與 next 專用 receipt；finding-only 啟動使用一般 receipt。這兩項固定操作部分失敗時依下方[恢復規則](#固定操作與歷史登記恢復)；accepted 後的 `next.cleanup` 只表示當下觀察，真正清理與 receipt 依 [Finalization](finalization.md#worktree-清理)。

Gate／Runner 的 JSON 檔案輸入使用 UTF-8。`transition --payload-json` 接受 JSON object 字串或 UTF-8 檔案路徑，優先解析 inline JSON；若檔名恰為合法 JSON（如 `null`），使用 `./null` 或絕對路徑。兩種輸入都必須解析為 object；格式、編碼或讀取失敗回傳 exit code `2`，stderr 為含 `ok: false`／`error` 的 JSON，不嘗試轉碼、推進流程或輸出 traceback。

Package／Result 使用 JSON，Spec／Plan 使用 Markdown。顯示層不得補預設值或改寫契約；Python contract 不轉型、不修改輸入，格式錯誤不能靠改寫已凍結資料掩蓋。核准候選的呈現依 [Package Authoring](package-authoring.md#development-package)。

## 儲存與復原

`init` 將 `/.cogito/runs/` 與 `/.cogito/worktrees/` 加入 Git 本地 `info/exclude`，保留使用者既有規則，不修改 `.gitignore` 或取消追蹤已提交檔案。其他儲存與相容性細節供維護者查閱 [Runtime Internals](runtime-internals.md#查詢receipt-與事件儲存)。

`.cogito/runs/<run-id>/events.jsonl` 是 append-only 權威歷史；`state.json` 只是由 events 重建並驗證的 projection。不可手動修補事件或 cache 來放行。Controlled check 的原始請求與執行紀錄另存於 `check-actions/`；已開始但沒有完整 evidence 的 attempt 是未知結果，不能刪 marker 強制重試。先讀 `next.check_recovery`，依 [Check 重送](execution-policy.md#check-重送)處理。

Resume Gate 驗證 Package、baseline、Git commits、worktrees 與已登錄 evidence。整合或結案 commit 已成功而事件未記錄時，先查 run、確認既有 commit ID 與原始請求，再以原參數及 action ID 重送 Gate 命令補登記，不再次 merge 或 commit。`resume` 不會掃描 Git trailers 自動找 commit 或補記事件；無法確認成果或驗證失敗時，停止並保留現場。

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

## 固定操作與歷史登記恢復

`task-finish` 與帶 `amendment` 的 `review-fix-start --input` 只串接各自固定的兩項登記。`.cogito/runs/<run-id>/fixed-actions/` 保存不可變的輸入、起始契約／事件、內容與子事件綁定；完成與否以權威事件核對，不以 cache 或可改寫的 done flag 判定。不得手動修改或刪除這些綁定來重試。

一部分事件成功、後續寫入或回應失敗時，停止接續派工與檢查，查 `next` 的 `retry-fixed-action`，以原輸入及原 action ID 重送。工具只完成缺少的登記，不重新選 commit、finding 或 evidence，也不重計修正次數。若已 `blocked`，先處理原阻塞並通過既有 Resume Gate，再重送；重送不能穿透 blocked、RP、DP 或 human 限制。契約、內容、事件或身分無法對帳時保持停止，不自行改工具放行。

舊版接受的兩種已知登記錯誤，沿用同 Run 的受限恢復：

- **Result 下一階段填錯：**限 blocked-from-executing、已完成的 Atomic Implementer Result，將 `executing` 更正為 `verifying`，其餘內容不變。`next` 的 `recover-result-metadata` 提供原 event sequence/hash 與更正輸入；以 `correct-result-metadata --run-id <ID> --input <file> --action-id <ID>` 提交。Gate 重驗原 lease、提交鏈、當時契約、證據、目前完成 tip 及實際 executor/check 停止情況；只追加更正事件，在原 Result 位置投影生效。全部必要更正後另走 Resume Gate，不自動 resume。RP successor 的 atomic 判定只能來自核准 hash 綁定的 snapshot，不能替缺欄資料臆測模式。
- **Amendment 在 review-fix start 之前：**不更動事件次序、不另建 Task。舊資料須能唯一對應本輪 finding → amendment → start，且 Amendment 未被其他 closure 消耗、所有新增 Task 的 lease／running／Result／complete 都在 start 後。恢復後以原 `review-fix-complete` 重新驗證提交、trailer 與證據；錯輪或歧義資料拒絕。

以上已定義且通過驗證的行政恢復由 Coordinator 執行，不為相同既有授權再加一次人工確認。若需要新增產品／授權範圍，或現有工具沒有安全恢復方式而必須修改工具，停止受影響工作並向使用者說明。保留原事件與證據；舊版 CLI 不保證可讀新版恢復事件，工具切換時須驗證完整歷史相容性。

## 其他查詢

`render --type workflow` 與 `render --type project` 從權威 JSON 衍生 Mermaid 狀態圖／Slice 相依圖，不能反向編輯或取代 workflow／Project Graph。`slice-inventory` 的適用性、輸出及失敗處理見 [Package Authoring](package-authoring.md#歷史-slice-查詢)。其餘流程入口依 [SKILL.md](../SKILL.md#目前要讀哪份文件)，本檔不另維護第二份路由表。
