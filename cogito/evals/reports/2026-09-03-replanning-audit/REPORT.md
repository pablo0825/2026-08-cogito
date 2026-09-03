# Cogito 多 Worker 契約變更：重新規劃流程模擬

日期：2026-09-03（Asia/Taipei）  
來源版本：`9bd13425652f2f34282ef2fbc6e1c8d47c53c25b`

**確認問題存在。Cogito 能登錄阻塞、保留原契約與執行歷史，但尚無完整流程把「使用者同意改 API／邊界」轉成新核准契約，並安全承接原本的開發成果。**

這是隔離環境的流程實測：使用真正的 Git repository、worktree、CLI／RunStore Gate、controlled runner 及 OS subprocess。B／C／D 的產品程式是合成 fixture；沒有實作真正的清單篩選、統計及 JSON 匯出，也沒有修改正式專案的 Package、Project Graph 或產品程式。所有 fixture 核准皆為合成測試資料。此次未 commit。

## 模擬結果

| 檢查項目 | 實測結果 | 對使用者的意義 |
|---|---|---|
| 已核准 Package 能否換新版 | 在 `reviewing` 重新 prepare／approve 均拒絕；原 Package bytes 不變 | 同意新 API 後，不能直接換掉原開發契約 |
| 能否重做需求釐清／Boundary | 從 `reviewing` 提交相關事件被拒 | 沒有回到前期規劃的路徑 |
| Amendment 能否擴張邊界 | 新增 `approved_paths`、替換 Boundary、加入範圍外 task／path fix 均拒絕 | 技術修正機制不能合法承擔這次變更 |
| `resume` 能否指定新階段 | 沒有 `--target`；只回到記錄的 `blocked_from` | 只能按原契約續行，無法藉此重新核准 |
| 能否只讓 C 重新核准 | 狀態屬於整個 run；沒有 Slice 級重核准路徑 | 無法讓 C 退回規劃、B／D 自動照常推進 |
| `block` 能否停 Worker | B／D 程序仍存活，並在 block 之後成功寫入 worktree | 停流程不等於停止程式；Coordinator 必須另行停止或收尾 |
| 已啟動 check 是否停止 | check 在 block 後完成，新增 `passed: true` evidence；run 仍為 `blocked` | 仍會有執行中的結果回流，不能假設現場已完全凍結；這不代表 Gate 已驗收通過 |
| cancel 後能否直接承接 | 舊 Project Graph 的 `active_run_id` 仍存在，新 run 核准被擋 | cancel 不是完整的資源釋放與交接操作 |
| 人工組合新 run 能否開始 | 清 Graph active run、使用新 Slice ID／lineage／branch／worktree 後可以 | 有可用零件，但不是正式且可中斷復原的交接流程 |
| 成果與證據能否沿用 | 已整合內容可留在新 baseline；新 tasks 都是 pending，evidence 為空；直接提交舊 Result／evidence 被拒 | 程式碼能保留，不代表工作狀態與驗證可自動繼承 |
| `accepted` 能否重開 | 原 run 的 resume／block 均拒絕；另開 change run 可行 | 終態限制原 run，不禁止產品後續變更 |

## B／C／D 的具體模擬

1. 同一 Feature Package 派出 B、C、D 三個 task，各有自己的 branch、worktree 與 lease。
2. C 完成實作並提交 Result；B、D 的真實程序仍停留在開發途中。模擬此時發現新的共用 API 契約需求。
3. 嘗試進入正式驗證，被 `tasks_complete` guard 拒絕，因 B、D 尚在執行。
4. 登錄 `block` 後，Gate 拒絕 B 的 task 更新，但 task 仍顯示 B=running、C=complete、D=running。
5. B、D 程序沒有被終止，收到測試控制訊號後仍各自寫入 `finished after block`。
6. `resume` 回到原來的 `executing`，Package 未變；沒有新 API 的核准事件或新契約。

再以合法 `reviewing` fixture 模擬正式驗證／審查後才發現問題：重新 prepare Package、approve Package、Shared Understanding、Boundary 都被拒絕。block／resume 只會把它送回 `reviewing`。

用生活化例子說：B、C、D 按同一份已核准圖紙施工。C 發現必須換掉共用管線；現在可以登記「停工」，但這個登記不會自動叫停仍在工作的工人。即使屋主同意換管線，系統也沒有把舊圖紙正式結束、核准新圖紙、標記哪些完工部分可以保留，再重新派工的一整套程序。

## 題述需要精確化的三處

**一、同一波開發中，C 已進入正式驗證／審查、B／D 仍 running，並不是目前可達的狀態。** 正式 `verifying`／`reviewing` 屬於整個 run；`implementation-complete` 要求沒有 active task，也沒有可派 task。因此有效的例子是「C 在個別開發／自測時發現問題，而 B／D 仍在開發」，或「B／D 在先前 wave 已整合，C 在後續 wave 的正式驗證／審查發現問題」。兩種情況都有重新規劃缺口。

**二、accepted 不能重開，不等於產品不能繼續修改。** 可以建立新的 change run。本次實測使用新 Slice ID、lineage 及新 worker 配置，可核准並開始。缺的是舊契約與新契約之間的完整承接，不是完全沒有後續開發能力。

**三、Runtime 不會自動辨識 API 的語意變化。** 我們提交 Amendment，reason 明寫「將公開 API 輸出由 list 改成 object，並替換資料模型」，但 `path_fixes` 仍在原核准路徑內，Gate 接受了它。這只證明結構與路徑檢查通過，並不代表變更符合政策。公開 API／資料模型不得以 Amendment 改動，目前仍依靠 Coordinator 正確辨識。

## 舊成果實際能保留多少

| 舊成果狀態 | 本次觀察 | 缺少的正式承接規則 |
|---|---|---|
| 未提交 | block／cancel 後仍在原 worktree | 停止確認、快照、所屬契約及可轉移內容清單 |
| 已提交／已完成 | 原 commits、Result、task 記錄仍保留；新 run 的 tasks 重新 pending | 哪些 commit 可採用、轉移後 task 與新契約如何對應 |
| 已審查 | 原 review 歷史保留，沒有跨 run 的 review 採認流程 | 哪些 review 失效、哪些可引用，以及採認依據 |
| 已整合 | 新 baseline 可包含已整合的程式；本次已直接確認 | 新 API 對既有成果的影響、需替換或重驗的範圍 |
| 測試 evidence | 原 evidence 保留；直接跨 run 提交被拒 | 有條件的重驗／重用決策與新契約綁定 |

拒絕跨 run 直接沿用 Result／evidence 是既有的隔離保護，不能為了接續工作而刪除。待設計的機制應在保留此保護的前提下，明確記錄來源、影響與再次核准。

另有一個人工承接陷阱：清除 `active_run_id` 後重用仍 active 的舊 Slice ID，Gate 會接受並覆寫該節點的 `introduced_by`、Spec／Plan 等資料。本次舊 event log 仍 byte-for-byte 保留，但 Graph 中的 Slice 來源身分被新 run 取代。使用新 ID 與 lineage 可避開此例，仍需要正式流程來保證操作一致性。

## 對設計議題的影響

下表是依實測提出的後續設計起點，**不是已實作能力或已取得核准的方案**。

| 議題 | 實測給出的設計約束／建議 |
|---|---|
| 重新規劃單位 | 後繼新 run 較貼近現有不可變 Package 與終態模型；需明確記錄 predecessor／successor 與各自契約 hash。Graph 雖已有 lineage／superseded 等欄位，仍缺少串起它們的交接操作 |
| 暫停範圍 | 第一版可先暫停整個 Package，並取得各 Worker 已停止或安全收尾的確認；局部續行必須另有受影響集合與相依分析作為依據 |
| 重新釐清範圍 | 需求／驗收語意改變時重新確認理解；只改實作分工但超出核准契約時，仍需重新檢視 Boundary、Spec／Plan 與 Package。具體分類需設計 |
| 核准呈現 | 同頁呈現新舊 API、資料模型、paths、Acceptance、checks、DAG、保留／重做工作及成本，核准綁定新 candidate hash |
| 工作承接 | 建立逐項清單，標明保留、移植、替換、放棄；未提交內容先保存可驗證快照，已整合內容納入新 baseline 但仍分析影響 |
| 證據有效性 | 預設受影響範圍重驗；若允許沿用，需具體證明程式內容、依賴、check 與契約相關部分未變，並記錄採認者與來源 |
| 恢復與追蹤 | Graph、task、lease、branch/worktree 與契約應由同一交接協定更新；不能只清 `active_run_id` 或改寫 Slice 來源 |
| 放棄變更 | 原契約仍可行且現場可驗證時，現有 resume 可供使用；原契約不可行時需正式結束並處置未完工作，不能把 cancel 當成已完成資源交接 |
| 中斷復原 | 需要可重送的交接 ID、各階段 checkpoint、失敗後的對帳與恢復規則；原有 event replay 不等於已具備跨 run 的交接交易 |

本次未對尚不存在的重新規劃交易進行中途崩潰注入，也沒有證明任何局部續行方案安全。上述兩點是待設計／待驗收項目。

## 驗證與證據

- 契約探測：16 項 observations，包含預期拒絕與「未寫入事件／未改 Package」核對。
- 後繼 run 探測：22 筆操作／狀態觀察，涵蓋中途取消與 accepted 後另建 change run。
- 程序探測：三 Worker fixture，以及 controlled check 在 block 前後的真實執行。
- 相關回歸：54 tests，全部通過，耗時 7.925 秒。包含 block recovery、Package revisions、Amendment dependencies、task rules、action replay、runtime contract。子代理另跑的 13 tests 與此重疊，未重複計數。未執行全套 regression。
- 子代理 2 位，分別約 4 分 38 秒與 4 分鐘，均在 10 分鐘內完成，無需換手。
- 正式專案沒有 tracked 檔案差異；僅新增本次報告／探測檔。Git 操作及測試用人工 Graph 修改均限隔離 fixture。

主要檔案：

- [契約探測報告](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/contract-audit.md)
- [契約結構化結果](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/contract-summary.json)
- [Worker／check 結構化結果](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/process-summary.json)
- [後繼 run 報告](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/successor-audit.md)
- [後繼 run 結構化結果](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/successor-results.json)
- [54 項回歸日誌](/Users/pablo/Documents/project/2026-08-cogito/cogito/evals/reports/2026-09-03-replanning-audit/targeted-regression.log)

程式依據：

- [Package 準備限制](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_run_store.py:222)、[核准限制](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_run_store.py:716)、[Resume Gate](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_run_store.py:807)。
- [同 wave 完成條件](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_run_store.py:153)、[controlled check 啟動與登錄](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_run_store.py:457)。
- [Project Graph 正式化及 Slice 來源](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_project_graph.py:75)、[終態限制](/Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_workflow.py:88)。
- [block 不終止程序的既有說明](/Users/pablo/Documents/project/2026-08-cogito/cogito/references/runtime-interface.md:36)。

可從專案根目錄重跑（將重建暫存 fixture 並更新本目錄輸出）：

```sh
python3 -B cogito/evals/reports/2026-09-03-replanning-audit/contract-probe.py
python3 -B cogito/evals/reports/2026-09-03-replanning-audit/process-probe.py
python3 -B cogito/evals/reports/2026-09-03-replanning-audit/successor_probe.py
PYTHONPATH=cogito/tests python3 -B -m unittest test_block_recovery test_package_revisions test_amendment_dependencies test_task_rules test_action_replay test_runtime_contract -v
```

`process-probe-initial.log` 保留第一次探測腳本漏帶 `--action-id` 的錯誤；修正腳本後重跑成功，正式結果為 `process-probe.log`／`process-summary.json`。該初次錯誤不列為 Cogito 缺陷。
