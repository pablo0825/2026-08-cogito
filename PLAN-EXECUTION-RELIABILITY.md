# 第一批：任務登記與審查修正可靠性計畫

日期：2026-09-07。基準：Cogito 3.4.0。狀態：使用者核准後已實作，交付版本 3.5.0；實際驗證與限制見第 7 節。

本文件記錄 repository maintenance 的修改計畫與交付，不是新的 Cogito Run、Package 或 Gate 授權。最初僅撰寫計畫，之後依使用者「計畫 commit 後開始修改」的指示實作。不修改後端專案與 DEV-003 帳本。

## 1. 需求與交付界線

使用者已確認：

1. 保留小包 Task、targeted checks、單一責任的獨立 commit 與完成紀錄；減少 Coordinator 的機械性登記。
2. 既定規則可驗證的登記錯誤可自動恢復。產品契約、授權或安全邊界改變，以及需要臨時修改工具才能繼續時，交由使用者決定。
3. 最終方向為固定 commit 的獨立審查與後續實作並行。Coordinator 決定修正時機；同檔修改串行，基礎邏輯錯誤先停受影響工作。
4. 最終方向為保留未受影響成果，由 Coordinator 提出選測理由，Reviewer 確認；完整 regression 留給 CI。
5. 先完成本批可靠性修改，並行正式審查與選擇性審查／證據採認留給第二批。

本批只有五項能力：完成登記簡化、審查修正啟動整合、已知錯誤入口檢查、兩種既有阻塞的限縮恢復，以及這些操作的具體 `next` 提示。

不新增自動派工 daemon、通用工作流引擎、通用 metadata 編輯器、任意批次命令、跨 Run Task 採認或新的審查階段。不重做 3.4.0 的路徑補正。Task 的 lease、實際測試、commit、獨立審查、整合與 accepted 仍各有既有責任；本批不承諾無人介入地完成整個 Run。

## 2. 實證與目前缺口

| 已確認問題 | 目前程式依據 | 本批對策 |
| --- | --- | --- |
| completed Implementer Result 可填 `executing`，整波完成才要求 `verifying` | `submit_agent_result`／`update_task`／`implementation-complete`；contract 只驗 transition 列舉值 | 統一新 Result 的組合規則，並由完成入口產生固定值 |
| `amend` 可在 reviewing 接受，但 closure 要求 amendment 在 review-fix start 之後 | `add_amendment`、`enter_review_fix`、`validate_review_fix_completion` | 一次提供 finding 與 amendment，先驗完整啟動輸入，再按正確順序登記 |
| `next` 只回傳 dispatch 類階段名称 | `derive_next_action` | 本批操作提供可執行參數、必要輸入、缺失與重送資訊 |
| 歷史 Result 更正遇 RP successor 初始化未記 atomic 模式 | 後端工具分支 `c3f6d2f`、`3935e65` 與 DEV-003 恢復紀錄 | 依核准 hash 綁定的契約判定，不以初始化缺欄當非 atomic，也不一律補 atomic |

後端 DEV-003 最新讀取狀態為 blocked，第 57 筆 amendment、第 58 筆 review-fix start、第 67 筆 T-005 complete、第 68 筆 block。此資料只用於設計及隔離 fixture，不直接執行真實修復。既有工具分支須審核後移植必要行為，不能直接整包 cherry-pick 或覆蓋 3.4.0。

「入口拒絕死路」限於當下已知的欄位、finding、契約、依賴、階段及計數器必要條件；不保證未來產品測試與 Reviewer 一定通過。

## 3. 最小操作設計

### 3.1 完成 Atomic Task

擬新增 `task-finish --run-id <ID> --task-id <ID> --input <file> --action-id <ID>`。僅用於已 lease／running 的 Atomic Development Task，且 Implementer 已完成相關測試及一個產品 commit。Maintenance、Documentation、Reviewer 與 Integrator 繼續既有入口。

輸入保留 Agent 需要判斷的 `risks`（可明確為空）。run/task 是操作目標；agent 身分從既有 lease 引用，不創造新的身分或假裝能證明呼叫者身分。工具取得 base、branch、worktree、HEAD、實際 changed paths、有效 Task check IDs，產生既有完整 Result（role=implementer、status=complete、requested_transition=verifying）。

證據只從該 Run 已登記的 controlled evidence 選取，依當前有效契約、Task、內容樹及各 check 的最新執行狀態判定；不得選舊成功掩蓋較新的失敗／未結束執行。證據缺失、歧義或失效時列出 check IDs 與原因，不能任選一筆成功或自動補造。具體選取規則在共用 evidence rules 層實作，不能在 CLI 另寫較寬鬆版本。

一次完成 Result 登記與 Task complete。輸出包括 Task、commit、選用 evidence、完成／待恢復狀態與下一步。工具不在此命令執行產品測試、git commit、lease 下一個 Task、進入 verification 或宣告通過審查。Agent 可依成功回應走既有下一 Task 流程，不必再由 Coordinator 手拼 Result。

舊完整 `agent-result`／`task --status complete` 保留，新增錯誤組合在入口被拒絕；不在 validator 中偷偷改寫輸入。歷史錯誤事件依原始 bytes 重播，透過明確更正事件處理，不能新增全域 validation 使舊帳本突然讀不開。

### 3.2 一次啟動審查修正

擬擴充既有 `review-fix-start`，接受輸入：精確 finding event reference（sequence/hash）及完整 amendment。Agent 仍須判斷修正責任、路徑、依賴與 checks；工具只消除操作順序與重複綁定。

工具在任何權威寫入前驗證：合法 reviewing、當輪未被取代的 needs-fix、對應 reviewer/task/head、獨立 Reviewer、計數器、非歧義綁定、amendment 合約、可完成的 Task 依賴與現有各 fence。成功後以既有正規順序 start → amendment 建立修正，回傳 amendment ID 與可派發 Task。

舊 start → amend 介面仍可用；舊 reviewing → amend 的使用不能再種下未來才發現的死路。針對新增修正 Task 的舊錯序呼叫，在新寫入入口即拒絕並提示整合入口；其他合法 check-only、verification、human 或 post-integration amendment 不一律禁止。歷史已接受的錯序使用 3.4 的受限條件。

### 3.3 固定操作的中斷與重送

不以兩個無保護的 CLI 呼叫拼接上述入口。沿用既有 project lock、request fingerprint、append-only event 與 action replay，為每個固定操作保存最小且不可變的綁定：原始輸入、起始 event hash、Task/finding、契約 hash、commit/evidence 與子步驟識別。

寫入前完整 preflight；持久化採既有事件順序並提供專用操作進度，避免新增通用 transaction framework。實作時先核對現有 action storage 能力；若必須新增資料，僅容納這兩個固定操作，不能另做可執行任意命令的日誌。

第一筆事件已接受但第二筆或 cache 寫入失敗，不宣称整體完成，也不刪除前一筆事件。恢復資訊必須能從權威事件與不可變操作綁定重建，cache 不是完成依據。待恢復期間拒絕依賴該操作的 lease、amendment、transition 與相關 executor/check admission；允許精確重送、查詢與合法停止。

相同 action ID／相同輸入只完成缺少的步驟；同 ID 不同輸入拒絕。重送不能重新選另一個 HEAD、finding 或較新的 evidence。若內容或契約已漂移就保持阻塞並說明，不自動借用新內容完成舊操作。全部已完成但回應遺失，重送仍回報既有完成，不重計 counter、不重登記 Result。

### 3.4 兩種既有阻塞的受限恢復

**Result 欄位錯誤：**只允許已接受且已完成的 atomic Implementer Result，將 `requested_transition: executing` 更正為 `verifying`。限定 blocked，精確引用最新有效原 Result 的 sequence/hash；其餘欄位相等。重驗歷史 lease、commit parent/tree、當時有效契約與原 controlled evidence；原 commit 必須仍在目前已完成 Task 提交鏈，checkout 保持最後已完成內容，實際 Worker/check 已停止，RP/DP/human 限制仍適用。追加更正事件，原歷史及證據不變，更正後不自動 resume。

更正必須在原 Result 的投影位置生效，不能把舊 T-001 移到結果尾端而影響「最新結果」判定。delivery summary／Result metadata hash 與重播同步理解更正事件。也要能讀取後端已存在的四筆更正事件，不能要求使用者再更正一次。

**review-fix 錯序：**不新增任意調整 event sequence 的命令。擴充共用 closure 的同輪判定，保留 start → amendment，另接受可證明的 finding → amendment → start。要求唯一有效 finding 精確對應 start 保存的 reviewer/task/head，amendment 未被先前 closure 消耗，所有新增 Task 的 lease、running、Implementer Result、complete 都在該 start 後；保留 commit、trailer、內容、檢查與各 fence 驗證。錯輪、歧義、過期或已被通過結果取代的 finding 都拒絕。

針對既有 blocked run，驗證恢復條件後仍走原 Resume 與 closure，不創造新 Task、新 commit、新 Run 或新核准。既定工具入口可由 Coordinator 自行操作，不增加一次使用者確認；若驗證失敗或需要修改工具／擴張權限，停止並說明。

### 3.5 具體下一步

保留既有 `state`／`next_action`，本批相關狀態追加結構化 operation、argv、known inputs、required inputs、missing checks／拒絕原因。參數用 argv 資料，不拼 shell 字串；未知的風險說明與 amendment 不虛構成已完成輸入。

優先序：既有 RP/DP/human/路徑補正 fence及待恢復操作 → 本批可執行操作 → 既有一般提示。Result 只登記未 complete 時應提示補完；全部 Task complete 時不能仍只提示空的 dispatch。不要把 Runtime repair 的一般 blocked 一律判成可自動恢復。

新操作預設精簡輸出，詳細 state/history 仍走既有查詢；不全面更改所有 CLI stdout schema，也不新增一套任務排程判定。`next` 不新增權威狀態，執行入口一律重新驗證。

## 4. 分包實作、檔案範圍與驗收

每包通過相關檢查、記錄結果、完成獨立 commit 後才進下一包。下列 paths 為規劃範圍，實作前以依賴追蹤確認；不可藉本文件擴張至後端產品或真實帳本。新增模組名稱可在責任不變時微調並同步本表。共用檔案串行修改。

| Task | 單一責任／Acceptance IDs | 預計 production allowed paths（均在 `cogito/` 下） | Targeted checks／commit |
| --- | --- | --- | --- |
| P1-01 | 新 Result 立即拒絕錯誤組合；歷史原事件仍能讀取。AC-01 | `scripts/cogito_contracts.py`、`scripts/cogito_run_store.py`；必要時新增 `scripts/cogito_task_completion_rules.py` | atomic execution/verification、JSON/event compatibility；`fix(cogito): reject invalid atomic completion metadata at entry` |
| P1-02 | 同輪錯序可受限結案，新錯序提前拒絕。AC-02 | `scripts/cogito_correction_rules.py`、`scripts/cogito_run_store.py` | correction rules、atomic/maintenance corrections、錯輪與歷史 CLI fixture；`fix(cogito): bind review fixes to their actual review cycle` |
| P1-03 | 既有 Result 單欄更正及 RP successor 相容。AC-03 | `scripts/cogito_result_metadata.py`（新增）、`scripts/cogito_projection.py`、`scripts/cogito_run_store.py`、`scripts/cogito_state_types.py`、`scripts/cogito_event_types.py`、`scripts/cogito_delivery_summary.py`、`scripts/cogito_gate.py` | 隔離 metadata recovery、RP successor、summary、event replay、真 CLI；`fix(cogito): recover accepted atomic result metadata safely` |
| P1-04 | 一次完成 Task 登記，凍結證據選取及可恢復中斷。AC-04、AC-06 | `scripts/cogito_task_finish.py`（新增）、`scripts/cogito_run_store.py`、`scripts/cogito_gate.py`、`scripts/cogito_actions.py`、`scripts/cogito_replan_lock.py`、`scripts/cogito_execution_registry.py`；必要時 `scripts/cogito_task_completion_rules.py` | task-finish CLI、atomic execution、controlled evidence、action replay、admission/fence；`feat(cogito): finish atomic tasks from recorded evidence` |
| P1-05 | 一次啟動 finding 綁定的審查修正，可恢復部分成功。AC-05、AC-06 | `scripts/cogito_review_fix_start.py`（新增）、`scripts/cogito_run_store.py`、`scripts/cogito_gate.py`、`scripts/cogito_actions.py`、`scripts/cogito_correction_rules.py`、`scripts/cogito_replan_lock.py`、`scripts/cogito_execution_registry.py` | review-fix CLI 全路徑、錯序/重送/失敗注入、既有 correction/human 邊界；`feat(cogito): start review fixes with bound amendments` |
| P1-06 | 操作指引與整批交付確認。AC-07、AC-08 | `scripts/cogito_run_queries.py`、`scripts/cogito_run_store.py`、`SKILL.md`、`references/execution-policy.md`、`references/runtime-interface.md`、`references/finalization.md`、`VERSION` | next/CLI contracts、跨 P1-01～05 的隔離生命週期、文件閱讀模擬、skill format；`feat(cogito): guide reliable task completion and correction` |

各包對應測試放在 `cogito/tests/` 的既有相關測試或專用 `test_task_finish.py`、`test_review_fix_start.py`、`test_result_metadata.py` 及共用隔離 fixture；不將測試工具寫進產品專案。若某包超過約 15 個 production files 或同時出現另一個可獨立驗收流程，先再拆分，不以大範圍重構掩蓋。

AC-01：新錯誤 Result 在首次登記就拒絕且不追加事件；合法舊入口與歷史錯誤帳本重播仍受支援。

AC-02：原 start → amend 和已存在的可證明同輪錯序都能完成；新錯序在造成產品工作前得到明確拒絕；不能以此接受跨輪或未驗證修正。

AC-03：重現四個已完成 Task，逐筆更正後走 Resume → implementation-complete → verify；事件前綴、原 commit、證據 bytes/hash 不變。已更正歷史、RP successor 缺初始化 mode、缺失或不符的核准 snapshot 都各有測試。

AC-04：Implementer 只選 Task 並提供 risks，即可登記由 Git/lease/controlled evidence 推導的完整 Result 和 complete；選錯或不完整證據不能完成。

AC-05：一次輸入精確 finding 與 amendment 可啟動修正；非法 amendment／finding 在任何事件寫入前被拒絕；同 Task commit／受控檢查及 closure 仍正常。

AC-06：測試每一持久化邊界的中斷、失敗回應、cache failure、重送及競態；不重複事件、counter、Task 完成或換綁內容；待恢復時不能派工越過操作。

AC-07：新正常操作與恢復操作都有足夠執行的 next 資訊；缺少人工判斷欄位明示，舊查詢必要欄位保留，其他 fence 不被覆蓋。

AC-08：兩 Task 小包完成 → 整波 verification → needs-fix → 整合啟動 → correction Task → closure → 正式重審 → integration → post checks → finalization/accepted，在隔離真 CLI 路徑通過。另以支援的 successor／歷史帳本覆蓋恢復後交付；不把只有 scenario 文件視為通過。

## 5. 測試與相容性策略

只跑本批變更、相依契約、恢復及 CLI 路徑相關測試，不預設全套。基礎選測包括 `test_atomic_task_execution`、`test_atomic_task_verification`、`test_atomic_task_corrections`、`test_correction_rules`、`test_maintenance_corrections`、`test_action_replay`、`test_run_queries`、`test_delivery_summary`、`test_atomic_replan`、`test_event_payload_compatibility`、`test_event_json_shape`、`test_gate_cli_contract`；依各包涉及行為選取，而非每包重跑全部清單。

所有 Git-backed 測試使用 `GitTestCase/init_repo()`。DEV-003 資料只取最小結構製成隔離 fixture，涵蓋它已經含 metadata correction events 的真實類型；不複製敏感 env、不改真實 events、不以偽造批准或 evidence 修好 fixture。

相關型別範圍檢查與文件／skill 格式、合成閱讀模擬分開報告。完整 regression 留 CI，未執行即明示未執行。整批測試通過不等於後端 DEV-003 已恢復或 accepted。

版本暫定 3.5.0：新增相容入口，既有合法命令、Package、歷史 events 保留。舊版讀取器不保證能理解新版更正事件；工具切換前須驗證目標 Run 的完整事件相容性，不能只覆蓋 VERSION。若實作評估必須改不相容公開 contract，重新檢視版本與範圍，不能硬稱 MINOR。只在完成實作與驗證後升版一次。

## 6. 第二輪自審與修訂紀錄

| 審核問題 | 修訂後決定 |
| --- | --- |
| 是否把「接續下一包」擴大成自動派工？ | 沒有。本批只完成登記並回傳下一步；排程自動化不在範圍。 |
| 是否將機器推導等同可任選成功證據？ | 沒有。凍結明確 evidence 綁定，較新的失敗／未完成執行不可忽略，歧義拒絕。 |
| 是否在收到兩次成功回應前仍可能遺留半完成？ | 承認持久化部分成功，加入精確重送與 admission fence；不假稱多事件寫入可回滾。 |
| 是否只修新入口，舊入口仍會造成死路？ | 新舊入口共用已知前置規則，歷史讀取與新寫入的規則分開。 |
| 是否為兩個歷史錯誤各建立泛用救援系統？ | Result 只准單一指定值更正；錯序使用同輪 closure 判定，不設事件編輯器。 |
| 是否預設後端工具修補與 3.4.0 可直接合併？ | 否。先比對事件形狀、RP snapshot、summary 與最新來源，再移植必要行為。 |
| 是否悄悄加入第二批的並行審查或證據重用？ | 沒有。本批保留現有正式審查與 evidence 有效性語意，不藉自動選取放寬。 |
| 是否要求使用者每次核准已支援的行政恢復？ | 沒有。已定義且驗證通過的恢复由 Coordinator 處理；本計畫不授權臨時修改工具放行。 |

主代理第二輪審核結論：範圍可成立，但多事件操作的中斷／重送及歷史相容性是主要風險，不能簡化成 shell wrapper。六包中 P1-04／05 必須各自驗證部分成功，P1-06 才宣稱整批可交付。

規劃當時的獨立審核子代理因帳號用量限制未能執行，沒有將該次審核記為通過。之後使用者明確授權主代理實作、子代理協助測試或模擬；實作後的獨立操作及文件模擬見第 7 節，並非補造規劃時的審核結果。

## 7. 實際交付與驗證

- 計畫先提交為 `e9519ac`。P1-01～05 依序提交 `01449ea`、`71ab7dc`、`15425a1`、`3f4eee6`、`c6ddd66`；P1-06 與本記錄同次交付。未新增 branch/worktree，未 push/tag，也未在後端套用工具或恢復真實 Run。
- 主代理完成實作。固定操作使用既有事件順序、唯讀 preflight event adapter 與不可變 `fixed-actions` 綁定；實際事件決定完成狀態。未建立通用交易引擎或新 workflow states。
- 自動化測試：最後整合選測 `test_task_finish test_review_fix_start test_result_metadata test_run_queries test_gate_cli_contract test_event_repository test_atomic_task_corrections test_correction_rules test_execution_registry` 共 67 項通過。之後補強證據時間被竄改的情境，重跑 `test_task_finish` 全部 10 項通過；這兩組有重疊，不相加作為獨立測試數。
- 先前各包亦執行相依 Atomic execution/verification、Maintenance review-fix、Feature CLI、RP successor、delivery summary、event JSON/compatibility 與 3.4 path amendment flow 測試。相關驗證涵蓋正常交付直到 accepted、歷史 Result／錯序、部分事件成功、真正 cache refresh 故障、不同 action/input、checkout 漂移、較新失敗／未知檢查及篡改證據。
- 型別檢查：本次 8 個主要模組的 targeted mypy 通過。另對 projection/state types 擴查，`cogito_projection.py` 仍有 6 個既存型別錯誤；以計畫提交 `e9519ac` 的原始 projection 重跑得到相同 6 個錯誤，本批未擴大修復。不能宣稱全專案 mypy 通過。
- Skill 格式：`quick_validate.py cogito` 通過；引用路徑、CLI help 與 `git diff --check` 已檢查。
- 獨立操作模擬：子代理在臨時 Git fixture 實際測試兩種 fixed operation 第一 receipt 後中斷、block、未 resume 重送被拒絕且 events bytes 不變、Resume 後原請求重送成功。無授權取消被拒絕；完整 DP cancellation 路徑未模擬。
- 獨立文件閱讀模擬：涵蓋一般 Task 完成、needs-fix 修正、blocked 重送及歷史四筆 Result 更正。沒有阻斷性矛盾；建議補上命令列舉與限定手動 Result 回報段落，已修訂。上述屬合成驗證，不是正式 Gate review evidence 或使用者驗收。
- 未跑全套 regression、未宣稱 CI 通過；並行正式審查與選擇性保留 review 仍屬第二批。
