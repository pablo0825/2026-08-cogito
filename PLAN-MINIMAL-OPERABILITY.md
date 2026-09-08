# Cogito 最小操作性修正方案

日期：2026-09-08。基準：Cogito 4.1.0。狀態：已實作並完成本地聚焦驗證，交付版本 4.2.0。

本文保存 repository maintenance 的設計與驗收範圍，不啟動 Cogito Run，不授予後端產品、資料庫或既有 Run 歷史的修改權限。第 11 節記錄本次實作結果及保留限制；實際操作介面以更新後的 runtime 文件與 CLI 為準。

## 1. 目標與範圍

保留三項必要修改：減少可預防的 check 未知結果、修正 cleanup 對無關歷史 Run 的依賴、讓既有 `next` 提供可用的操作資料與命令。

成功標準是已知故障可依法恢復、無關歷史不再錯誤阻擋清理，以及操作者不需手選 evidence 或猜測 Git 操作。不得以減少驗證條件達成目標。

本批不新增 CLI subcommand、workflow state、通用 recovery event、ownership index、持久化 plan store、排程器或 telemetry journal。沿用 `run-check`、`retry`、`verify`、`post-verify`、`integrate`、`finalize` 與 `next`。

## 2. 現有基礎與實際缺口

| 現有能力 | 缺口 | 修改位置 |
| --- | --- | --- |
| `run_controlled_check` 綁定 action、marker 與 evidence；Atomic running Task 的 pre-snapshot failure 已可追加 `check-preparation-failed` | 程序能力故障可能在啟動後才發現；其他 phase 沒有相同 retry 資格 | `cogito/scripts/cogito_run_store.py`、`cogito_runner.py`、`cogito_process_capture.py`、`cogito_execution_registry.py`、`cogito_check_retry.py` |
| cleanup 保護 ownership、未知資料、executor 與 evidence Git objects | `_other_use` 呼叫每個其他 Run 的 `load()`，把完整恢復、Package 工作副本與 cache 寫入耦合到引用檢查 | `cogito/scripts/cogito_cleanup.py`、`cogito_event_repository.py`、`cogito_slice_inventory_compat.py` |
| `task-finish` 已選最新 attempt；`next.operations` 已提供部分 argv/input/blockers | verifying、integration、accepted cleanup 的資訊仍不足 | `cogito/scripts/cogito_task_finish.py`、`cogito_gate_validation.py`、`cogito_run_queries.py`、`cogito_run_store.py` |

既有 `review-retention`、Atomic 歷史 Task evidence 保留、compact mutation receipts 繼續使用，不重做。

## 3. 修改 A：check 啟動防錯與有限恢復

### 3.1 正常執行順序

1. 保留原 action replay 與 published evidence 補登錄優先順序。已完成的 action 不因現在環境缺少工具而被迫重跑。
2. 對真正需要啟動的新 attempt，在建立 `started.json` 前檢查 state、worktree、check definition、cwd，以及 runner 必需的程序檢視能力。程序檢視需涵蓋 identity 與 group inspection；檢查失敗不能留下暗示已啟動的 marker。
3. 在實際目標 checkout 驗證 Git snapshot 能力。優先重用既有 snapshot adapter；snapshot 會建立 Git objects／temporary index，不宣稱此能力檢查完全零寫入，且不得改動使用者 index、branch 或工作檔案。
4. 保留啟動當下的 fence、process registration 與 check 前後 snapshot 驗證。前置成功不能充當稍後仍具備權限或內容未變的證明。
5. 正式結果仍由原 controlled runner 保存與登錄。Gate receipt 增量回傳該 action 的 `check_status` 及已存在的機械失敗 flags，避免操作者把登錄成功誤認為測試通過。

前置 probe 只確認已知必要能力，不啟動產品 command、不安裝依賴、不連接或重建 DB、不建立 `.env`。`env_allowlist` 表示允許傳入，不代表變數必填；本批不把缺少 allowlist 變數自動認定為錯誤。Executable probe 若加入，只檢查 runner 實際 env/cwd 可解析的情況；不得將 `npm` 或專案 wrapper 內部命令不存在偽裝成已檢查完成。

### 3.2 恢復矩陣

| 可觀察情況 | 行為 | action／額度 |
| --- | --- | --- |
| 前置能力檢查拒絕，尚未有 started marker | 回報具體缺失；環境修復後可重送 | 相同輸入沿原 action；不記 transient retry，不增加 correction counter |
| 原有 Atomic running Task pre-snapshot failure，且正式 failure event 已落盤 | 沿用 `retry --kind transient`，綁來源與 replacement | retry action、來源 action、replacement action 彼此不同；維持現有額度 |
| evidence 已發布，ledger 尚未登錄 | 重送原命令，驗證後補登錄 | 原 action、原輸入；不重新執行 |
| failure event 寫入也中斷，或有 started marker 卻無完整 evidence／未啟動證明 | 回報未知結果，保留現場 | 不刪 marker、不從空 registry 推測、不自動 replacement |
| process 已啟動後 registry、post-snapshot、輸出發布失敗 | 維持 unknown policy，指出缺少的證據 | 不轉換為 pre-execution failure |
| 正式 failed evidence | 顯示原 check verdict 與原因 flags，依目前 Task／correction 規則處理 | 不因顯示分類自動豁免 retry 或修正額度 |

本批保留 `check-preparation-failed` 的既有語意與適用範圍，不把它悄悄泛化成所有 phase 的 preflight failure。新增的 marker 前拒絕走安全重送；既有 `request.json` 可保留以鎖定請求，相同 ID 不得更換輸入。marker 後仍執行原本的實際 pre-snapshot，該處可證明的 snapshot failure 繼續走原 retry。若實作發現必須擴大事件語意，先提交該擴充的獨立設計。

`Popen` 與 registry publication 之間仍有空窗；前置 probe 只能降低已知故障機率。此方案不承諾所有中斷都能恢復。

### 3.3 顯示與相容性

`ok` 與 CLI exit code 維持原操作語意。`check_status` 從 action 精確指向的 immutable evidence 推導；舊 action replay 仍顯示舊 action 的結果。錯誤保留 `error` 文字，只在本批路徑增加有界的 code／操作提示，不全面改造 exception framework，不修改 evidence schema 或既有 hashes。

## 4. 修改 B：cleanup 使用受限歷史引用讀取

### 4.1 讀取與判斷

1. 保留目前對被清理 Run 的 accepted、Result、ownership、executor 與 Git 登記驗證。
2. 對其他 Run 先驗證原始 event hash chain，以不修復 cache 的讀取介面取得引用事實。支援正常歷史與明確列出的已知歷史格式。
3. 首版已知相容格式限 accepted history 的 `controlled-check-attempt-resolved`，重用既有 inventory compatibility 的對帳規則。此格式的 reader 支援不恢復舊寫入命令，也不讓一般 runtime resume 自動取得相容資格。
4. 相容性不得只做事件過濾：核對 replacement event、當時有效契約／check hash、final Result receipt 與所需 artifacts；沿用現有驗證條件。共用狹窄的驗證 helper，避免把 inventory 的單一 Slice 限制或所有展示內容搬進 cleanup。
5. accepted Run 的凍結 Package 優先從記錄的 final commit 讀取並比對 hash；active Run 保留其有效 Package 與事件要求。引用來源至少涵蓋既有 Task／worker 判斷，逐一確認支援格式中的 adoption／carryover 等是否可新增資源引用，不能遺漏後宣稱無關。
6. 正規化 repo/path/branch 後，比對相同 branch、相同 worktree、父子路徑與巢狀 Git 登記。能證明無引用才允許繼續清理。

### 4.2 失敗與保護

未知事件、損壞 hash chain、缺少必要 artifacts、symlink 或不完整引用語意，回傳 `reference_unknown`，附 Run 與原因。若無法界定可能受影響的範圍，可保守保留多個甚至全部候選 worktrees；不能憑空指定只有某個 worktree 受影響。

已知且確定無關的歷史相容差異不阻擋清理。不得 catch 所有 replay errors 後直接忽略，也不得把可改寫 cache 當 ownership authority。

保留現有 active RP／DP 保守限制、未知 ignored data 保留、一般 `git worktree remove`、branch/runtime 保留與 Git object pinning。`.env`、`dist`、tool lock 檔案的可刪除政策不在本批擴張。

cleanup 仍在 accepted 後 best-effort 執行，重送原 `finalize` 重試。每個候選分別回報 removed／retained；清理問題不撤銷交付。

## 5. 修改 C：把必要操作協助集中到 next

### 5.1 共通輸出原則

保留 `state`、`next_action`、既有 `operations` 與所有 RP／DP、checkpoint、path amendment、fixed-action recovery override 的優先序。只補目前階段所需欄位，不把完整 projection、Package、evidence stdout/stderr 塞回輸出。

機械事實由 helper 計算；候選由既有 validator 確認。`next` 是觀察與提示，查詢與執行間可能漂移，真正 mutation 仍重新驗證。新提示不建立 action request、plan journal、event、cleanup receipt 或 executor registry。既有 `next` 若會 refresh cache，該既有行為需明確保留或另案處理，不假稱整個命令已嚴格零寫入。

輸出採現有 `operations` array。argv 使用絕對 script/repo 路徑與 argv array；每個 operation 明列 cwd。可機械推導的輸入填好；需要新 ID 時用明確 placeholder／required_inputs，原 action 重送則提供可驗證的精確 ID。提示不足時省略可執行命令並回報 blockers。

### 5.2 各階段的必要資訊

| 階段 | 提供內容 | 執行入口 |
| --- | --- | --- |
| check 受阻 | attempt/check/worktree、已知阻塞、是否有合法 retry、來源／replacement ID 規則、剩餘額度 | `run-check` 或既有 `retry` |
| verifying | 可用 evidence 引用、缺少 checks、失效原因、已填入 evidence 路徑的完整 argv | `verify` |
| post-integration-verification | 當前 delivery HEAD 的 required integration evidence、缺失原因與 argv；保留 reviewer escalation 的人工判斷 | `post-verify` |
| integrating | 可整合 Slice、source heads/tip、前一 delivery HEAD、目前 branch/HEAD、適用 merge argv 或 blocker | Git 操作後呼叫原 `integrate` |
| accepted | 現在可觀察的 cleanup retained 原因、可驗證的原 finalize request | 原 `finalize` 重送 |

### 5.3 Evidence 選擇

從 `select_task_evidence` 抽出可共用的候選收集邏輯，避免另一套有效性規則。按 check、checkout、phase、最新 attempt、ledger/file hash、契約、HEAD/content tree 與 cycle anchor 判斷。

Atomic wave 按每個 checkout 的目前完整內容組合，保留歷史 Task Result；不能把所有 Task evidence 合併後直接送 verify。非 Atomic 保留 cycle freshness；post-integration 保留當前 delivery HEAD 與 required checks。同一 check 出現在不同 checkout 時按既有 wave validator 處理，不以全域 check ID 去重。

較新失敗、未知、歧義或未完成 attempt 不回退到舊成功；不在本批縮小既有 unfinished-marker 阻擋範圍。失效項目用短 reason code 加必要實際／預期資訊。required set 是既有驗證規則的結果，不以缺失清單刪除 required checks。

能產生合法 evidence 組合時提供 `verify --evidence ... --action-id <new-action-id>` argv；若不能，列出缺失與合法 run-check 提示，不代跑。候選清單過大時明示需篩選或資訊未完整，不靜默截斷後宣稱可以 closure。

### 5.4 Integration 提示

重用 `derive_integration_decision` 的任務／歷史資訊與現有 ancestry、scope、atomic merge 規則。首版精確 merge 提示限定 Atomic Development；Maintenance／Documentation 維持原流程提示，不誤用 Atomic 操作。

多個 eligible Slice 時列出選項，且標示一次只能執行一項、完成後重新查 `next`；不要提供一批可直接連續執行的過期 merge 命令。source tip 由記錄的 Result 推導，不從 branch 名猜測。

可 fast-forward 時提供指定 source SHA 的 `merge --ff-only`。只有完成下述隔離預演能力時，才在需要 merge 時提供固定 source SHA 的普通 merge 命令；已知衝突即阻擋，不自動 resolve。預期 HEAD 只在可確定的 fast-forward 提供；merge commit 不預言 SHA，使用預期 tree／ancestry。Git 完成後取得實際 commit ID 再提交 `integrate`，不能要求 Agent 把 placeholder 當真值。

`merge-tree --write-tree` 即使不動 branch，也可能寫入 Git objects。若預演需要它，先核對可重用的 Git adapter；目前不假設已有隔離 merge 預演介面。若需要新增，只限此操作的臨時 object directory，不引入持久化 store，清除時只處理自己建立的暫存目錄。無法用小範圍變更完成隔離預演時，首版只輸出 ancestry 可確定的 fast-forward 命令，其他情況回報需人工確認合併，不保證無衝突。不要直接從 `next` 呼叫會建立 snapshot objects 的完整 mutation validator，而應重用其純規則與受控讀取 adapter。

### 5.5 Cleanup 提示

將 cleanup 的評估與 apply 分開成內部 helper；apply 在原鎖定與 executor 保護下重新評估。查詢不得呼叫 `cleanup_accepted()`、建立 refs、寫 receipt 或移除 worktree，也不得直接使用會建立 registry／lock 檔的觀察 helper。以可用的唯讀觀察回報「查詢時的判斷」，不授予後續刪除權限。

目前 cleanup retained outcome 不在權威 projection，且 receipt 不能完整代表當前 blockers；需重新評估，不把 accepted report 當清理成功證明。

從 finalization event 取得原 action、result path、graph path、final commit，重算 request fingerprint。只有與原 `request_hash` 一致才提供可執行重送 argv。若原字面路徑／參數未完整保存、legacy action 無指紋或無法核對，明列缺失，讓操作者取回原請求；本批不新增 request store 補救，也不改用新 action 冒充重送。

## 6. 實作分包

按以下順序完成，每包獨立檢查與審查；共用核心檔案串行修改。

| Task | 交付內容 | 主要檔案／驗收 |
| --- | --- | --- |
| T-01 | check 啟動前能力檢查、精確 check receipt、保留現有 retry 邊界 | runner、process capture、registry、run store/query；AC-01～04 |
| T-02 | cleanup 的受限引用 reader 與已知 accepted history 相容 | cleanup、inventory compatibility 共用 helper；AC-05～07 |
| T-03 | 共用 evidence candidate helper、verification 與 check recovery hints | task finish、gate validation、run store/query；AC-08～10 |
| T-04 | Atomic integration hints 與 accepted cleanup 的唯讀評估／重送提示 | integration rules、Git adapters、cleanup、run store/query；AC-11～13 |
| T-05 | 更新操作文件、針對性流程驗證、版本與交付紀錄 | execution-policy、runtime-interface、finalization、必要 runtime-internals；AC-14 |

T-01 完成後才討論其他 phase 的 retry 擴充；T-02 不擴大 inventory 的公開查詢範圍；T-03／04 不加入 `verify --auto` 或新 plan 命令。具體新增 helper 名稱在對應包決定，以維持 pure decisions／I/O adapters 的既有分工。

## 7. 驗收條件

- AC-01：拒絕 process inspection 或 Git snapshot 時，產品 command 未執行；marker 前拒絕不留下 started marker、不改使用者 staging，修復後原請求可重送。既有 request.json 可保留；相同 action ID 換輸入仍拒絕。
- AC-02：marker 前 probe 成功後，在原 runner pre-snapshot 注入失敗，驗證正式 retry → replacement success → task-finish 可完成；額度、lease／contract drift 與 failure-event publication failure 維持正確處理。不能用一律拒絕 snapshot 的 mock 代替，因為那只會驗到 marker 前拒絕。
- AC-03：啟動後 registry failure、post-snapshot failure、未知 marker、空 registry 都不能被當成未執行或成功；預檢通過後能力消失仍在實際啟動時拒絕／安全處理。
- AC-04：run-check receipt 區分登錄成功與 check 成敗，重送舊 action 精確回原結果；evidence publication 後中斷不重跑。
- AC-05：另一 accepted Run 含已知相容事件且可證明無引用時，正常 worktree 可清理；舊 event、Result、Package、cache 不被修改。
- AC-06：相同 branch、相同／父子 worktree、nested registration、adoption／carryover 引用、未知事件、損壞 hash、缺必要 artifacts 均正確保留或拒絕，不能誤刪。
- AC-07：unknown ignored data、active executor、RP／DP、locked worktree、Git object pins、accepted 不回退與中斷重試的原保護保持有效。
- AC-08：Agent 可直接使用 next 的 verification argv；缺失、舊 tree、舊 contract、較新失敗、同時刻歧義與 unfinished attempt 分別回報，無合法組合時不生成 closure 命令。
- AC-09：覆蓋單／多 checkout Atomic wave、提交前後相同內容、non-atomic cycle freshness、post-integration HEAD 與 required checks；保留原 Task 歷史 evidence。
- AC-10：查詢後 HEAD、contract、evidence 或路由改變而使既有 validator 判定提示失效時，原 mutation 拒絕；既有合法的內容等價／歷史採認仍可接受，不另設所有變動皆失效的提示版本門檻。RP／DP、checkpoint、human、path amendment 與 fixed-action override 不被覆蓋。
- AC-11：已提供的 fast-forward／merge 提示可在隔離 Git fixture 實際執行並經 integrate 接受；衝突、錯 branch、delivery drift 與不保留 source ancestry 的結果拒絕。若採 fast-forward-only 首版，須驗證非 fast-forward 明確回報限制、沒有可誤執行的保證式 merge 提示，並在交付結果列出未提供 merge 預演。
- AC-12：accepted next 能顯示現有 retained 原因；查詢不刪除資源、不建立 cleanup refs／receipt／registry。apply 重新驗證，避免查詢後新增資料被刪。
- AC-13：只有精確匹配原 fingerprint 的 finalize 提示可執行；相對路徑差異、legacy fingerprint 缺失、參數缺失都有明確 blocker。
- AC-14：正常成功與每類故障有簡短可用的提示，不輸出 secret 值或完整 evidence；文件描述與實際 argv 一致，新增 hints 的使用不需要讀取完整 status。

## 8. 驗證與交付

依修改包選測，不預設執行全套。T-01 重點為 `test_check_retry`、`test_process_capture`、`test_execution_registry`、`test_runner_contract`、`test_runner_termination`、`test_action_replay` 與 receipt tests；T-02 為 cleanup／cleanup_finalization、slice_inventory_compat 及必要 inventory tests；T-03 為 task_finish、gate_evidence_rules、atomic_task_verification、verification_snapshot、run_queries；T-04 為 integration_rules／scope、atomic integration 相關案例、cleanup_finalization 與 route override tests。依實際改動補必要 failure／race tests，不機械地全部重跑。

Git 測試繼承 `cogito_test_support.GitTestCase`，並呼叫同模組的 `init_repo()`，隔離 personal config、hooks、signing 與環境。新增案例應驗可觀察結果與歷史不變性，不只鏡像 helper 實作。

每包測試通過後進行獨立審查。最終在 disposable repository 執行一條實際 CLI 路徑：能力失敗／修復 → run-check → task-finish → next 給 verify argv → review → next 給 merge 提示 → integrate → post-verify → finalize → retained／next／原請求重試。未知結果與 legacy cleanup 另用故障注入驗證，不碰後端正式 Run。

configured mypy、`git diff --check`、文件 focused reading simulation 分別記錄。文件模擬包括重送原 ID、新 retry IDs、多 Slice 整合後重查 next、unknown outcome 停止及缺原 finalize 請求。模擬不是正式使用者驗收；歷史報告不是本次測試結果。skill format 在修改 SKILL.md／metadata 時執行；未修改則明列未執行。全套 regression 留 CI，除非實際影響範圍需要或使用者另行要求，不宣稱 CI 已通過。

方案本身不更新 VERSION。若三項作為一次向後相容交付，預期由 4.1.0 升為 4.2.0；實作前若基準已變則依當時版本判斷。公開欄位移除、exit code 改義或既有事件語意改變須另評相容性，不能當作增量 hints 混入。版本只在完整交付前更新一次；commit、push、tag 與發布依後續授權處理。

## 9. 後續調整門檻

先在實際開發中記錄具體摩擦案例，再決定是否擴充。離線整理 command 次數、讀檔次數、恢復步驟與已完成 evidence duration 即可；沒有資料的 token／等待／浪費時間不推測為精確值。

| 延後項目 | 何時重新評估 | 優先的最小方案 |
| --- | --- | --- |
| `verify --auto` | next 已給完整 argv，仍反覆發生 evidence 傳遞錯誤 | 既有 verify 加互斥的 auto 選項，共用同一 selector |
| 批次 checks | 多次實例顯示逐項派發成本明顯，而非環境修復佔大宗 | 固定一批串行 checks、獨立 action/evidence；再評估資源宣告與平行 |
| 一般 interrupted recovery | 收到本批未涵蓋、可取得可信停止／副作用證據的具體中斷案例 | 對單一故障設計明確 recovery proof，先不新增通用 resolver |
| 獨立 cleanup 命令 | 原 finalize request 不可還原或重送操作仍經常造成困難 | accepted-only 薄入口重用 cleanup helper，無新增 plan lifecycle |
| doctor／bootstrap | 多個專案重複遇到相同可機械檢查的需求 | 先共用專案準備腳本與 runner probes；DB／seed 邏輯留專案 |
| 版本化 ownership／event framework | 出現多種正式支援歷史格式，窄 adapter 已難維護 | 明確 reader 支援矩陣與共用版本分派；仍不改舊 hashes |
| integration apply | 精確提示仍反覆造成已驗證的 Git 操作錯誤 | 限單一無衝突模式並設計副作用中斷恢復 |
| evidence cache | 可證明同內容重跑是主要成本，且 checks 有可信完整環境綁定 | 先限同 Run、明示可快取的 hermetic checks；跨 Run 延後 |
| efficiency report | 需要跨多個 Run 比較改善效果 | 唯讀報告標 observed／derived／estimated／unavailable；不建常駐 telemetry |
| review-retention 擴充 | 有具體且安全、但被現有單 checkout／線性歷史限制拒絕的案例 | 逐一擴充適用條件，保留 Reviewer 語意判斷 |

通用 `advance` 不列近期路線；若往返仍昂貴，先找固定且可恢復的兩步操作。60%～80% 節省僅是原 incident 的估計，不作本方案驗收承諾。

## 10. 本次方案整理紀錄

已核對 4.1.0 的程式、CLI、操作文件與先前三份交付計畫。獨立子代理完成方案審查，主代理採納並核對四項修正：保留 marker 前 request 綁定、精確區分 probe 與原 snapshot 的故障注入位置、提示失效仍由既有 validator 判斷、隔離 merge 預演無法小範圍完成時同步收斂適用範圍與驗收。

方案整理當時僅完成文件 whitespace 檢查，沒有以驗收情境清單宣稱功能通過。使用者後續核准實作，並指定主代理修改、子代理執行審查與模擬；結果如下。

## 11. 實作與驗證紀錄

三項修改由主代理實作，子代理獨立審查、執行測試與模擬；未啟動本 repository 的 Cogito Run，未修改後端正式 Run。

- T-01：新 attempt 在 started marker 前探測程序 identity／group 及實際 snapshot；保留原 request 指紋、啟動當下驗證與既有正式 retry。receipt 回傳精確 action 的 verdict／機械 flags，CLI 成功語意與 evidence schema 不變。
- T-02：共用 `read_accepted_source` 的受限歷史驗證，inventory 公開範圍仍為單一 Development Slice。cleanup 讀其他 Run 不修 cache；保護 Task／adoption、worker、carryover、symlink 與未知引用。一般 accepted history 沒有 committed Package 時，保留 hash 驗證的非 symlink 工作副本 fallback；legacy resolution 仍必須有 committed artifacts。
- T-03：latest-attempt selector 共用；正常 `next` 提供候選／失效原因／完整 verification argv 與有限恢復命令。從未啟動的舊 request 不阻塞或覆蓋有效 closure；query-only candidate 分類不能代替正式 required-set 驗證。Atomic post 可採用同 HEAD／完整內容的 Worker evidence，但較新失敗／歧義不回退。
- T-04：Atomic integration hints 首版採 fast-forward-only；普通 merge 仍走既有程序與 validator，不提供 merge 預演。cleanup assessment 與 apply 共用候選判斷，apply 在原鎖定下重驗；`next` 僅在還原參數精確符合原 fingerprint 時提供 finalize 重送。
- T-05：更新 execution-policy、runtime-interface、finalization、runtime-internals；VERSION 由 4.1.0 更新為 4.2.0，一次更新。交付後依使用者要求拆成啟動防錯、cleanup、next 提示、文件與版本四筆 commit；未 push、tag 或發布。

### 自動化測試

最終聚焦回歸共 **151 個不同測試通過**：第一組 next／task-finish／retry／replay／queries 69 項，第二組 cleanup／history／inventory／CLI 37 項，第三組 integration／path amendment／human safety／review retention／evidence rules 43 項，再加 optional-only 提示及 Package fallback symlink 兩項。最後安全補強另重跑 6 項，屬上述集合，不重複累計。早期 T-01 的 runner／process／registry 測試與故障注入亦完成，未混入此最終計數。

覆蓋新舊 action verdict、發布後補登錄、spawn 後 registry 故障維持 unknown、marker 前拒絕與 staging 保護、pre-snapshot 正式 retry、same-check 多 worktrees、precommit／post 內容等價、較新失敗與 HEAD 漂移、FF 命令實跑／non-FF blocker、accepted 查詢不發布清理 artifacts、apply 重驗，以及真實 hash chain／committed historical Result 的相容性。legacy cleanup apply 案例的「目前 accepted ownership」使用既有 cleanup unit-test fixture 邊界，其他 Run 歷史、Git 登記、objects 及實際移除是真實操作；不是執行已退役 writer。

測試環境原 sandbox 禁止 `ps`；受控 runner 測試在獲准的 process-inspection 執行環境中通過。未執行全套 regression，也未宣稱 CI 通過。configured mypy 因環境沒有 `mypy` 未執行，未安裝新工具。SKILL.md／metadata 未修改，因此未執行 skill format validation。

### 獨立審查與行為模擬

子代理完成程式複審，最後無阻擋交付的安全問題。文件 focused reading simulation 通過：原 ID 重送、retry／replacement 不同 ID、unknown 停止、多 Slice 操作後重查、non-FF 限制及缺 finalize fingerprint 均能導出正確行為；四份文件的相對連結已核對。

另一子代理在 disposable repository 執行單條 end-to-end smoke：**27 次真實 subprocess CLI 操作**（含 1 次 Git merge）及 1 次 in-process preflight 拒絕注入。涵蓋原請求修復 → run-check → 兩 Task finish → next verify argv → Reviewer CLI 登錄 → next FF／integrate → post-check／post-verify → finalize retained → next 重新觀察 → 原 finalize 重送並清理。Reviewer 內容為合成驗收情境，不冒充正式產品的獨立語意審核或使用者驗收。

### 保留限制

不提供通用 interrupted resolver、普通 merge 預演、批次 checks、bootstrap／doctor、`verify --auto` 或新 cleanup 命令。全 optional checks 時明確要求操作者選擇內容依據，不把全部 optional 變成 required。新提示不新增權威狀態；mutation 永遠按目前事實重新驗證，既有 `next` cache refresh／流程預驗證仍保留。未量測或承諾節省百分比。
