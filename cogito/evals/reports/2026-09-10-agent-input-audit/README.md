# Agent 手動資料搬運與 Gate 提示盤查

日期：2026-09-10。對象：目前 4.4.5 工作目錄，包含上一輪尚未提交的修正。本次只盤查，不修改執行行為。

## 結論

值得改善的不是 Gate 數量，而是幾個入口仍要求 Agent 查找、重抄工具已知的資料。採兩種小改法即可：已知欄位產生草稿；既有操作補齊帶值提示。保留目前契約與執行時驗證，不新增流程種類。

優先順序是維護成本與正常路徑效益的判斷，並非實測使用頻率或 token 排名。建議第一批只處理派工／一般審查提示；RP Package 與結案 Result 草稿另各做一個有界改動。

## 手動輸入盤點

| 入口 | Agent 目前搬什麼、來源 | 為何手動／是否必要 | 最小改善與優先度 |
| --- | --- | --- | --- |
| 正常派工 | 從有效 Task／Slice 找責任、允許路徑、checks、工作目錄，再準備派工與 lease 參數 | `next` 目前只回 ready Task IDs 與容量；查找屬機械工作，實際執行者身分則來自派工結果 | **第一批**：提供待派 Task 的必要上下文與已有操作參數；保留真實 agent ID／handle 輸入，不回傳整份 state |
| 執行中檢查 | 找 check 的執行命令與 checkout | 已有 `task-finish` 提示，但缺 check 時只說 blocker，未附對應操作 | **第一批可一併處理**：附缺少／過期 check 的命令；仍由 Agent 判斷實作何時可測，不自動立即執行 |
| 一般 Reviewer Result | 填 `run_id`、`task_id`、`base_commit`、`head_commit`、`reviewed_implementer`；來自 lease 與最新 completed Implementer Result | 通用 `agent-result` 要完整 JSON；其中固定引用本來就必須與 Gate 記錄相同，無須人抄 | **第一批**：在 `next` 提供待審 Task 與固定欄位草稿，沿用 `agent-result`。Reviewer 本人身分、判定、風險與意見仍需真實輸入；不直接代填 `changed_paths` 或 evidence，其審查語意須保留 |
| RP 提案 | 將 successor 已凍結 Package 整份放進 `proposal.package` | 提案要綁定完整核准內容，但不代表必須人工重抄；工具已有候選內容並再次核對 hash | **後續獨立小改動**：產生含凍結 Package 的 proposal 草稿；保留候選 hash／版本綁定與漂移拒絕。差異、成果保留／廢棄、target mapping 仍人工判斷 |
| 最終 Result | 複製 `delivery_summary`，重建 integration commits、amendments、checks/evidence、審查與驗收歷史 | 持久化 Result 目前由 Agent 組裝，但 Gate 已有權威事件且會精確核對多數資料 | **後續獨立小改動**：產生事實欄位草稿；風險與敘述由 Agent 補充，保留 finalize 驗證。只引用已記錄的核准，不能代做核准或自動發布 |
| Human 修正驗證 | 收集適用 evidence paths，組 `human verify` 命令 | 正常 verification 已有選證據功能，但 human phase 沒接上提示 | **第二批**：沿用現有候選證據與提示機制，另外驗證當輪 completion binding、內容與 freshness；optional checks 不擅自全選 |
| Human 修正開始／完成 | 搬 amendment、feedback ID、delivery HEAD | 欄位可推導，但顯式綁定有助拒絕錯輪或過時操作 | **第二批**：帶值 input 草稿，仍以原 validator 拒絕漂移；resolved items、summary、文件修改理由不代判 |
| 一般／整合後 correction closure | 搬 amendment ID 與適用 commit | review-fix 已有同類推導，其他 correction 缺少對稱提示 | **第二批**：資格可證明時，沿用 preflight + operation hint；歧義時說明缺什麼，不猜 commit 或自動合併 |
| RP／DP 導航 | 查命令用法，從 status 找 ID／proposal hash | exact hash 綁定有價值；手動拼命令沒有額外保護 | **延後**：先補 status 導航，再按實際需求補有限操作。核准命令不可預填授權並暗示可以直接執行 |
| Stage checkpoint | 使用已生成的 paths/message 做 commit，再將 HEAD 傳入 record | manifest、hash、branch、base 已自動生成；剩下主要是操作發現性 | **低優先**：補 prepare／符合條件的 record 提示；不要新增 staging 管理層或自動全 add |

## Gate 提示實際表現

用既有 `AtomicVerificationTests` fixture 在隔離暫存 Git repositories 呼叫真實 Gate，取得以下五個階段輸出。這是有限的入口探查，並非後端產品 Run 或完整行為驗收。

| 探查狀態 | 實際結果 | 判斷 |
| --- | --- | --- |
| executing，Task 可派工 | `dispatch-ready-workers`、`ready_tasks: [T-a]`、容量 | 能告訴 Agent 做什麼，未供派工所需上下文 |
| executing，Task 執行中且無 checks | 有 `task-finish` argv、`required_inputs: [risks]`；blocker 是 `missing controlled checks: C-a` | 有阻擋原因，但修復下一步不完整；頂層仍顯示派工，儘管 ready 清單為空 |
| verifying，已有有效 evidence | 已列 `eligible_evidence`，missing/stale 都空，直接提供 `verify --evidence ...` | 證據搬運已解；頂層仍叫 `run-controlled-checks`，名稱較粗，不能據此認定必須重跑測試 |
| reviewing，尚無 Reviewer Results | 只有 `dispatch-independent-reviewer` | 正常審查入口提示最明顯不足 |
| integrating，可 fast-forward | 完整來源 HEAD、Git merge 與 Gate integrate argv，要求做一個 choice 後重查 | 已有足夠操作指引；不需擴成自動決策合併框架 |

提示應讓 Agent 看見「下一步、已知參數、還需判斷的欄位；若被擋，原因與可證明安全的修復操作」。沿用現有 `operations`／`input`／`required_inputs` 即可，不另造一套提示協定。

本次只抽查部分錯誤／恢復分支，未逐一觸發所有 CLI 例外；不能宣稱所有 Gate 錯誤訊息均已完整評估。

## 已完成的減法，不應重做

- `task-finish` 已組合 Implementer Result、commit、changed paths 與 checks evidence，Agent 主要補風險。
- 正常／整合後驗證已有有效證據選擇、缺少／過期資訊與帶值命令，不必新增 auto-verify 流程。
- `review-fix-complete` 已推導 amendment／head，預檢後給命令；不應再列成尚未解決的人工搬運。
- check recovery 已區分未開始、已發布 evidence、可證明的執行前失敗與 unknown outcome；無法證明時不能自動重跑。
- accepted cleanup 已能在原 request 可重建時提示恢復；缺少原請求時不能猜 action ID 或參數。
- mutation receipt 已精簡；改善 `next` 不代表將完整快照塞回每次回應。

## 必須保留的輸入

需求與範圍、成果取捨、Reviewer 判定、未解風險、回饋是否解決、optional check 適用性、使用者核准，以及真正執行者身分／停止 receipt，不能由「資料自動填入」代替。草稿須固定當時引用，執行時繼續驗證；不可改成隱式永遠採用最新值，削弱過時輸入保護。

## 程式與文件依據

以下行號以本次工作目錄為準，後續可能移動：

- 派工／階段提示與精簡 receipt：`scripts/cogito_run_queries.py:39–115`。
- 提示組裝、human 路由缺口：`scripts/cogito_run_store.py:1671–1765`。
- Task finish blockers、一般 Reviewer 提示、既有 review-fix closure：`scripts/cogito_run_store.py:1767–1870`。
- Reviewer 固定引用檢查：`scripts/cogito_run_store.py:469–497`；操作要求：`references/execution-policy.md:44,120`。
- 自動 Task Result：`scripts/cogito_task_finish.py:146,156`。
- 驗證、check recovery、integration 與 accepted 提示：`scripts/cogito_next_operations.py:41–254`。
- RP Package 搬運與 hash 比對：`references/replanning.md:51–57`、`scripts/cogito_replan_store.py:376–399`。
- Human 修正輸入／驗證：`references/human-acceptance.md:85–127`、`scripts/cogito_human.py:124–270`。
- 結案資料搬運與精確核對：`references/finalization.md:29,37`、`scripts/cogito_delivery_summary.py:48,235`、`scripts/cogito_finalization_rules.py:115–204`。
- Checkpoint 自動準備與 record：約 `scripts/cogito_checkpoints.py:110–159`。

## 本次檢查範圍

- 主代理查閱程式、CLI 與程序文件，並執行上述五個隔離 Gate 狀態探查。
- 兩個子代理分別唯讀盤查 recovery／RP／human 與 review／closure／finalization；主代理核對關鍵引用並整合排序。
- 未修改 runtime、契約、操作程序或版本；未提交 commit。
- 未跑完整 regression、skill 格式驗證、完整 Agent 使用情境驗收；歷史測試結果不當成本次通過證據。
- 未量測模型 token、人工耗時或發生頻率，因此不宣稱改善一定節省多少成本。
