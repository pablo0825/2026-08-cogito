# Cogito 全流程再驗證：a056941

受測版本：`a056941551c68f380078491809ff5ede5f48ea48`。2026-09-02 執行，包含此前六項修正。環境為 macOS arm64、Python 3.12.10、Git 2.50.1。

**五種 Package 的正常流程均可結案，上輪兩項修正通過重驗；但本輪額外確認 3 個問題，因此不能宣稱整體無問題。** 全套回歸 340/340 通過，額外的重複與邊界探針才找出這些問題。

本次使用全新隔離 Git repositories，沒有修改或提交 Cogito 原始碼。3 位子代理協助回歸與快照診斷、核准前與恢復流程、Maintenance／Documentation 流程；每位本輪工作均在 8 分鐘內結束，未超過 10 分鐘，無需跨代理交接。

## 已完成的流程

| 情境 | 實際結果 |
|---|---|
| 全部 Python 回歸 | 340 tests，41.166 秒，OK |
| Feature，兩個相依 Slice | 真 CLI 完成摘要、Boundary、Package 核准、Start、兩波實作／controlled checks／Reviewer Results／整合、post checks、finalize／report；accepted |
| Change、Correction | 各以兩個相依 Slice，使用專用 branch/worktree 完成上述流程；皆 accepted |
| Human Gate | post verification 後到 awaiting-human，模擬核准後 accepted |
| 故意讓產品 check 失敗 | verify 拒絕，停在 verifying；事件不被錯誤推進 |
| 最後驗證後夾帶產品修改 | finalize 拒絕，停在 finalizing；事件不變 |
| Maintenance 三段修正鏈 | technical correction → review-fix／新增 task → integration → post-integration correction → accepted |
| Documentation | 完成獨立 Reviewer Result、integration、post checks 與 accepted；未使用 Maintenance review exemption |
| 合法 staged-only Maintenance | Agent Result 可接受，唯一 final commit 後 accepted |
| Maintenance staged 越界 | Agent Result 前的漏報被拒；Result 通過後才夾帶、且 post checks 已驗過的越界檔案，也在 finalize 被拒；events/index 不變 |
| 摘要與 Package 修訂 | 摘要最新 hash 確認、Feature／Maintenance／Documentation v1→v2、舊稿拒絕、新稿核准、核准後不可修訂均通過 |
| block／resume／replay | 核准前各階段可恢復，重播不重複寫入事件 |
| 壞 UTF-8／UTF-16 JSON 檔案 | Gate／Runner 回傳 exit 2 與 JSON 錯誤，無 traceback；有效中文 JSON 正常 |
| 損壞編碼的 events 與 state cache | 權威 events 拒絕且不改檔；可重建 cache 從 events 恢復 |

核准前另跑 33 項精準測試、staged 路徑另跑 11 項，皆通過；這些包含全套測試中的重跑，不另外加到 340 的總數。

主代理七組 CLI 情境共保存 693 次呼叫；Maintenance／Documentation 軌保存 199 次，核准前軌保存 123 次。主要流程合計 1,015 次保存的 CLI 呼叫，不含 unittest 內部另外啟動的 CLI。完整逐次參數及 stdout／stderr 保存在封存中。

Maintenance 修正鏈僅建立 1 個新 commit、integration 只有 1 次；`verification_corrections=2`、`review_fix_cycles=1`。Final `ea0fef7638e547ba483a2b341ddde443fd1fc4b5` 帶齊 `TA-pre`、`TA-review`、`TA-post` 三個 trailer；Result 保留基線與快照，衍生 report 正確補上 final commit ID。此 commit 僅存在測試 repository。

## 問題 1：P1，Feature 整合仍能夾帶未核准檔案並 accepted

位置：`cogito/scripts/cogito_run_store.py:510` 的 `complete_integration()`，以及 `cogito/scripts/cogito_finalization.py:89` 的結案範圍檢查分支。

重現步驟：

1. 核准 Feature Package，`approved_paths` 只有 `src/**`、`tests/**`。
2. Worker 在專用 worktree 完成合法變更；Agent Result、controlled check 與 Reviewer Result 均合法。
3. Coordinator 以 `git merge --no-ff --no-commit` 整合第一個 Slice，額外修改已存在的 `unrelated.txt`，一起建立 merge commit。
4. `integrate` 接受該 commit；第二個 Slice、post checks 與 metadata-only final commit 也都成功。
5. 最後狀態為 `accepted`，但 final commit 的 `unrelated.txt` 從 `preserve` 變成 `unapproved integration change`。

現場 first integration：`24263b06c8c36165135d1d622f7caf2b26a1da99`。Final：`d4ce4ad506232ab369596f1b446c08c7cbd4cb1b`。

`complete_integration()` 驗證分支、HEAD、已審查 task 與祖先關係，沒有驗證實際整合差異是否超出核准路徑。Feature 結案驗的是最後 metadata commit 與已驗證 tree，沒有覆蓋從 Start 到最終交付的整體範圍。因此「內容已通過 post checks」仍可能和「內容在核准範圍內」不一致。

這是不同於上一輪 Maintenance staged 漏檢的入口；Maintenance 的新範圍檢查本輪仍有效。直接完成重現的是 Feature；Change／Correction 共用相關程式分支，但沒有把它們列為此漏洞的額外實跑案例。另一位子代理已獨立驗證 Package hash、事件 hash chain、投影狀態與 Git objects。

建議：整合時檢查實際 delivery diff 的路徑責任，結案時再檢查完整交付範圍，保留必要且精確的控制檔案例外。驗收需包含正常多 Slice 整合，以及 merge 時加入未核准內容後仍通過產品 checks 的負例。

證據：[整合漏洞摘要](integration-outside.json)。完整 fixture、CLI transcript、events 與 Git repository 在封存的 `integration-outside/`；重跑腳本為 `run_cli_simulation.py --scenario integration-outside`，需使用新的輸出目錄。此情境沿用正常流程斷言，`assertions_passed=true` 表示流程確實走通；`unexpected_acceptance=true` 才是漏洞判定。

## 問題 2：P2，runner 內容快照可能取到舊檔案，誤判驗證期間有變更

位置：`cogito/scripts/cogito_evidence_binding.py:16` 的 `working_tree_content_tree()`，特別是 `shutil.copyfile(index_path, temporary_index)`。

對既有正向 `test_review_fix_records_snapshot_and_reverifies_added_task` 重跑 30 次，29 次通過、第 30 次失敗，總耗時 14.090 秒。這次捕捉到上一輪未能定位的偶發失敗：check 只讀 `note.txt`，程序 exit code 0、stderr 空、未 timeout，卻因 `worktree_changed_during_check=true` 被判失敗。

保留的 Git objects 與 evidence 可精確重建 pre-binding，重算 hash 完全一致：

| 資料 | check 前 | check 後 |
|---|---|---|
| note.txt 的內容快照 | `after\n\n`，正確 | `before\n`，舊基線 |
| HEAD／HEAD tree | 相同 | 相同 |
| tracked diff hash | 相同 | 相同 |
| untracked 路徑與檔案 hash | 相同 | 相同 |

只有 `content_tree` 變了，工作檔仍是正確的 `after\n\n`。這不是產品 check 失敗，也不是預期拒絕案例。

另外已用最小 repository 重現：同一秒內把 `before\n` 改成等長的 `after\n\n`，原 index 的 `git diff` 正確，但產品函式複製 index 後產生的 tree 卻保留舊內容。受控對照只把暫存 index 的修改時間設回原 index 的時間，其餘 copy／git add／write-tree 相同，就能取得正確內容。此結果支持複製 index 後改變時間戳，破壞 Git 對同秒修改的重新檢查機制。

已觀察的影響是正常流程被誤拒，以及內容快照不正確；本輪沒有示範因此錯誤 accepted，不將推測列為已證實影響。

建議：讓暫存 index 保留正確的 Git 時間戳語義或強制重新檢查內容，同時維持不改使用者 index。新增同秒、同長內容修改的穩定回歸案例，並驗證產生的 tree 確實等於工作檔，不能只增加重試來掩蓋問題。

證據：[快照差異](snapshot-binding.json)、[最小重現與時間戳對照](snapshot-reproduction.json)、[完整回歸與診斷報告](regression.md)。封存內 `regression/reproduce_racy_snapshot.py`、`compare_index_timestamp.py`、失敗第 30 次的 repo 與 evidence 可供查核。時序案例在其他檔案系統上不保證每次觸發。

## 問題 3：P2，事件 JSONL 的非 object 行會造成 traceback

位置：`cogito/scripts/cogito_events.py:31`。

在隔離 repository 的 `events.jsonl` 追加合法 UTF-8 的 `[]` 或 `null` 行後，執行 `status`。`json.loads()` 成功，但接著直接呼叫 `event.get()`，因此產生 `AttributeError` traceback、exit code 1。預期是帶有行號或事件形狀說明的結構化 JSON 錯誤與 exit code 2。

兩種輸入都已實跑，事件與 state cache 的原始 bytes 均未改變；沒有觀察到錯誤推進或資料覆寫。這和上輪已修好的非法 UTF-8 是不同情形：編碼有效，但 JSON 值的型別不是 event object。

建議：在讀取事件欄位前驗證每行必須是 object，再檢查必要欄位與 hash chain；不可跳過或自動修補權威事件。驗收 `[]`、`null` 等合法 JSON 非 object 值，確認 exit 2、無 traceback、events/cache 不變。

證據：[兩組錯誤與檔案 hash](event-shape.json)、[核准前與恢復驗證](preapproval.md)。完整 probe 與現場在封存的 `preapproval/event-shape/`。

## 已知規格議題與驗證限制

- Eval #11 的「Human approval 前不得 merge」和目前 workflow 的 `integrating → post-integration-verification → awaiting-human` 次序不一致。這是先前已知的評測文字議題，未算作本輪新增的 3 項 runtime 問題；本次沒有更改規格。
- Fixture 的摘要確認、Package approval、Human Gate approval 與 Worker／Reviewer IDs 都是合成資料。3 位真實子代理負責測試與查核，不等同 fixture 中的產品角色；本輪證明的是 CLI／Git／runner／Gate 的機械流程。
- 14 個自然語言 Agent eval 已檢視覆蓋，但未逐一執行或評分。Grilling 問答品質、語意等價判斷、真實審查效果、舊專案文件採用，以及所有 crash／並行排程情形沒有被完整證明；詳見 regression.md 的逐項表格。
- 本次沒有執行 mypy、外部服務整合或部署。正常路徑通過不代表可以忽略額外探針找出的問題。
- 核准前初版損壞 Package 注入被檔案既有唯讀模式拒絕，屬探針準備問題；改在新的測試 repository 明確改權限後完成注入並重跑。原始紀錄保留，沒有把準備失敗算作產品問題。

## 證據與後續順序

建議依序處理：1. 整合範圍漏檢；2. 快照正確性；3. 事件形狀錯誤處理。本次只模擬與整理，尚未修正這 3 項，也未建立修正 commit。

[機器摘要](summary.json)、[主流程各情境](main-scenarios.json)、[完整回歸 log](unittest.log)、[Maintenance／Documentation 報告](corrections.md)、[完整證據封存](evidence.tar.gz)。

封存包含 scripts、CLI 輸入輸出、events、runner evidence、隔離 repositories 與 Git objects。腳本含原始絕對路徑；搬移後重跑應調整來源／輸出目錄並建立新現場，不能把搬移當成可直接 resume 的工作樹，也不要覆寫既有失敗證據。
