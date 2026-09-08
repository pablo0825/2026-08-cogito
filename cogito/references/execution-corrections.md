# Execution Corrections

本檔處理已核准範圍內的 Technical Amendment、正式 correction／review-fix、必要路徑補列與修正後審查採認。先讀「自動修正」的邊界與「修正額度」，再依 `next_action` 讀取本次程序及其必要引用。未完成 Task 的原範圍內修錯與 check 重送留在 [Execution Policy](execution-policy.md#task-中斷或檢查失敗)；人工驗收退回依 [Human Acceptance](human-acceptance.md)，超出核准契約依 [Replanning](replanning.md)。

## 自動修正

Coordinator 依 Package 的 `stop_conditions` 與執行證據判讀是否應停止。這些條件是凍結的政策文字，Gate 不會自動求值或依 `outcome` 轉移狀態；停止派工、登錄 `block`、取消授權與 Human Gate 的處理依 [Runtime Interface](runtime-interface.md#停止條件與狀態操作)。

測試缺漏、內部程式錯誤或已核准路徑內的低風險調整，不改變核准的行為、公開契約、資料模型、安全邊界、DAG 或 Slice 責任時，可建立 append-only Technical Amendment 後自動修正。每個 Amendment 有穩定 ID、理由、增量任務/checks、允許路徑及 effective contract hash。

一般 Technical Amendment 在已核准路徑內增加 checks、tests、tasks，或修正內部實作；新增 check 的 `env_allowlist` 不得超出 Package 凍結的 `allowed_environment`。只有[實作中補列必要路徑](#實作中補列必要路徑)與[審查修正中的必要檔案補列](#審查修正中的必要檔案補列)可經獨立覆核擴充精確路徑；一般修正不得藉此擴張範圍。不得刪除或降級 required checks、改 Acceptance、公開 API、資料模型、安全邊界、依賴或 DAG。有效契約 hash 由 base Package 與有序 amendments 計算；相關 commit 使用 `Cogito-Amendment: <ID>` trailer；Maintenance 的延後提交依[修正完成方式](#maintenance-修正完成)。

Amendment 只能單調增加或加強工作。超出上述邊界時依 [Replanning](replanning.md) 限制全體執行、保存現場，再提出新的核准契約與 successor 承接方案。

Atomic 的產品 correction 必須使用新增 Task；只增加檢查可直接重新 verify，不開啟無任務的產品修正。新增任務以 `depends_on` 指定前置任務，可引用 base Package、先前 Amendment 或同批新增的任務。Gate 在追加事件前合併完整任務圖，拒絕未知節點、自我依賴與循環；effective contract 的 edges 會包含這些依賴，原始文件與 hash 不變。追加不能修改既有任務依賴或新增跨 Slice 的依賴關係；沿用已核准跨 Slice 關係時，前置任務必須已 `integrated`，避免修正流程等待自身完成後才能進行的整合。

## 修正額度

| 流程 | 合法循環與額度 |
|---|---|
| 開發 correction | `verifying → technical-correction → verifying`，最多三輪 |
| 整合後 correction | `post-integration-verification → post-integration-correction → post-integration-verification`，共用開發 correction 預算，不重做 integration |
| Review fix | `reviewing → review-fix → verifying → reviewing`，最多三輪 |

人工驗收修正使用獨立的三輪額度，計次與處理見 [Human Acceptance](human-acceptance.md#狀態與三輪額度)。所有計數器跨 resume 與 Agent 更換保留；超限、契約漂移或不可恢復衝突時，停止推進並依 Runtime Interface 登錄 block。

## 實作中補列必要路徑

僅限 `executing` 中的 Atomic Development Package：原規格所需的 mapper、response contract 或測試檔漏列時，可在同一 Run、Slice、branch 與已存在的 worktree 追加精確檔案路徑。只補入同一 Slice 未完成 Task，不新增需求、Task、successor 或改 DAG；已完成 Task 的 commit、Result 與歷史 evidence 不改寫，若需改變已完成行為，使用新增修正 Task。審查才發現缺漏時，改讀[審查修正中的必要檔案補列](#審查修正中的必要檔案補列)。

先依[路徑補列的共通程序](#路徑補列的共通程序)確認範圍並停妥受影響 Worker／checks，保留原授權路徑內未完成的內容；不得先修改未授權路徑再申請補正。Coordinator 準備以下 proposal，再依共通程序 propose／review：

```json
{
  "author_id": "coordinator-1",
  "amendment": {
    "id": "AM-path-1",
    "reason": "原核准查詢流程漏列 mapper 與相關測試",
    "path_additions": [{
      "task_id": "T-002",
      "paths": ["src/query_mapper.py", "tests/test_query_mapper.py"],
      "reason": "輸出 Spec 已核准的欄位並驗證轉換",
      "check_ids": ["C-query-mapper"]
    }],
    "added_checks": [{
      "id": "C-query-mapper",
      "argv": ["python3", "-m", "unittest", "tests.test_query_mapper"],
      "required": true,
      "phase": "task"
    }]
  }
}
```

已有適用 required check 時省略 `added_checks`。此類 amendment 不混用 `added_tasks`、`path_fixes` 或 `commit_id`。

覆核生效且 executor 封存完成後，原 leased／running Task 可重新登錄 executor，繼續實作、相關檢查與獨立 commit；目前必要 evidence 須綁定新 effective contract。已完成 Task 不要求重新交付。純路徑補正沒有獨立的產品修正 commit，Result 使用 [Finalization](finalization.md#3-準備-result-與-project-graph) 的 `proposal_hash` 記錄。

## 啟動審查修正

Atomic Development 的本輪 Reviewer 已登記 `needs-fix` 時，先彙整已完成審查中同一 Slice 的相關 findings，再查 `next` 取得 `prepare-review-fix` 的精確 finding reference。預設每輪、每個受影響 Slice 使用一個修正 Task，沿用其 branch/worktree；不按每個問題建立 Task 或分支，也不為單純修正建立 RP。不同 Slice 不合併責任範圍。

Coordinator 在既有 Amendment 的 `reason`／Task `responsibility` 引用本輪相關 Reviewer Result 與問題，說明修正範圍及選測理由；不另外建立修正清單 schema、流程單或核准關卡。`finding` 是本輪的啟動依據，不代表只能處理該筆 Result 的一個問題。Task 的 `check_ids` 僅列必要的相關檢查，不直接複製整份 Package 的 integration checks；原 required checks 不刪除，仍在其適用階段驗證。

尚未完成的修正 Task 又發現相關問題時，在原 paths、責任與核准語意內繼續修正、保留失敗 evidence 並以新 action ID 重跑相關 checks，不重建 Task 或 lease。需補授權時先依[審查修正中的必要檔案補列](#審查修正中的必要檔案補列)辦理；超出原產品契約時才評估 RP，不能以「同一輪」放寬 API、資料或安全邊界。完成的 Task／Result 不重開或改寫；完成後又有新 finding，依正常複審進入下一輪修正。

Coordinator 撰寫本輪修正 Task 與 checks 的 Amendment，保存輸入：

```json
{
  "finding": { "event_sequence": 54, "event_hash": "<next 提供的 hash>" },
  "amendment": {
    "id": "TA-001", "reason": "補齊年度列表的快取設定",
    "added_tasks": [{
      "id": "T-005", "slice_id": "FS-043",
      "paths": ["src/routes/certificate.routes.ts"],
      "responsibility": "修正年度列表的快取回應",
      "check_ids": ["V-005"]
    }]
  }
}
```

以上為欄位示意；finding 使用 `next` 的原值，Task、Slice、paths 與 check IDs 依本次有效契約撰寫。使用 `review-fix-start --run-id <ID> --input <file> --action-id <ID>`。工具在登記前驗證 finding、修正責任、依賴、checks、checkout 及現有門檻，按 start → amendment 登記事件；不再要求 Agent 分開操作。若 finding 已被本輪通過結果取代、Amendment 非法或契約／內容改變，立即拒絕。

啟動成功後依[一般 Atomic Task 流程](execution-policy.md#atomic-task)實作、相關檢查、獨立 commit 與 `task-finish`；每項修正 commit 保留 `Cogito-Amendment: <ID>` trailer。修正 Tasks 完成後依 `next` 執行 `review-fix-complete`，再依[正式驗證](execution-policy.md#正式驗證)及[獨立審查](execution-policy.md#獨立審查)完成本輪；未受影響的原 approval 可依[採認程序](#保留未受影響審查)處理。正式審查仍在實作與驗證後進行，不與後續實作並行。

既有分開的 `review-fix-start` → `amend` 仍支援，包括非 Atomic 流程。新操作不得在 `reviewing` 先用 `amend` 加修正 Tasks；一般 check-only 等其他合法 Amendment 不受此限制。已被舊版接受的錯序恢復見 [Runtime Interface](runtime-interface.md#固定操作與歷史登記恢復)。

## 審查修正中的必要檔案補列

限同一 Atomic Development Run、整合前的 `review-fix`：本輪 finding 所需的檔案漏列，且 Acceptance、公開 API 語意、資料模型、安全邊界與 Slice 責任均不變。補正可授權本次新增的修正 Tasks，或本輪已新增且尚未完成的修正 Task，全部屬於該 finding 的 Slice；不更改已完成 Task 的 paths、checks、commit 或 Result。真正超出核准契約時使用 [Replanning](replanning.md)。

以下步驟用於首次建立修正 Task；已有本輪未完成 Task 時，直接依本節末段補列，不再次啟動 review-fix 或新增 Task。

1. Coordinator 或 Implementer 先說明原 finding、未超出範圍的理由、精確檔案及相關 checks。引用原規格與 finding，不重新撰寫完整 Package。以 `next` 提供的 `finding` 單獨作為 `review-fix-start --input` 的輸入，例如 `{"finding": {"event_sequence": 54, "event_hash": "<實值>"}}`，先進入既有修正階段；不要把尚未覆核的路徑補列放進合併啟動輸入。
2. 停妥受影響 Worker 與 controlled checks，保留原本已驗證的 checkout；尚未授權的檔案不可先改。依[路徑補列的共通程序](#路徑補列的共通程序)準備並 propose 以下形式：

   ```json
   {
     "author_id": "coordinator",
     "amendment": {
       "id": "TA-mapper", "reason": "修正本輪 finding：補齊原需求的年度欄位",
       "added_tasks": [{
         "id": "T-mapper", "slice_id": "FS-043",
         "paths": ["src/response_mapper.ts"],
         "responsibility": "回傳原規格要求的年度",
         "depends_on": ["T-query"], "check_ids": ["C-year"]
       }],
       "path_additions": [{
         "task_id": "T-mapper", "paths": ["src/response_mapper.ts"],
         "reason": "原核准欄位所需的 mapper 漏列", "check_ids": ["C-year"]
       }]
     }
   }
   ```

   IDs 使用實值。`added_tasks.paths` 是修正 Task 的完整範圍；`path_additions.paths` 只列需要補授權的精確檔案，且其 paths／checks 必須包含在對應新 Task。每個新 Task 都須有對應補列，不混入其他任務。必要時在同一 Amendment 增加 `added_checks`；原 required checks 仍保留。路徑須符合[共通限制](#路徑補列的共通程序)；跨 Slice 前置任務須已 integrated，不能改變原 Slice 相依。
3. **由原本的獨立 Reviewer 在既有審查中確認範圍即可**，不固定增加第三位 Agent 或使用者核准。Reviewer 不得是 proposal 作者或受影響 Implementer。依共通程序以 `amend-paths review` 保存具體範圍判斷與選測理由；通過後一筆 Amendment 同時登記檔案授權與新修正 Tasks。覆核前不建立可執行的新 Task。
4. 依[啟動審查修正](#啟動審查修正)完成修正 Task、相關檢查、commit、`task-finish` 與 `review-fix-complete`，再驗證目前內容並複審。原 Reviewer 聚焦確認原 finding、新增／受影響 Task 與連帶影響；符合[審查採認條件](#保留未受影響審查)的未受影響 approval 可採認。無法證明不受影響時擴大複審，不因補列檔案而自動重開 run。

本輪 Task 尚未完成時又發現漏列檔案，依[共通程序](#路徑補列的共通程序)執行 `amend-paths propose/review`，只提交指向該 Task 的 `path_additions` 與必要的 `added_checks`，省略 `added_tasks`。先停止受影響執行者，再提案；可保留 Task 原 paths 內未完成的修改，不得先改新檔案。Gate 保留 Task ID、lease base、分支及原修正 Amendment，追加授權後取得新 effective contract 的必要 evidence，再繼續同一 Task。`review-fix-complete` 仍引用建立該 Task 的 Amendment ID；後續純路徑補正另按 `proposal_hash` 記錄，不取代原修正完成紀錄。前一輪 Task 或已登記完成 Result 不適用。

此入口的 proposal 另綁定本次 review-fix finding。撤回不發布新 Task 或授權，仍留在原修正階段；修訂、撤回與中斷重送依共通程序，不重建修正 Task。

## 路徑補列的共通程序

本節供[執行中補列](#實作中補列必要路徑)與[審查修正補列](#審查修正中的必要檔案補列)共用；適用狀態、Task 是否新增及完成方式依各入口。補列只修正原規格所需的檔案授權，Acceptance、公開 API 語意、資料模型、安全邊界與 Slice 責任必須不變。不能只靠檔名判斷；超出契約時走 [Replanning](replanning.md)。

路徑必須是精確檔案，不得使用目錄、glob、symlink、控制文件、凍結來源、高風險 hotspot，或跨用其他 Task／Slice 的責任路徑。新檔案可尚不存在，但所屬 worktree 必須已建立；已完成 Task／Result 不改寫。Checks 只引用既有或本次新增的 required checks，新增檢查仍受凍結環境政策限制，不刪除原 required checks。

1. 停妥受影響 Slice 的實際 Worker 與所有 controlled checks，保留原授權範圍內未完成的內容；未授權檔案不可先改。使用[正常登錄](execution-policy.md#派發與隔離)與 [executor 停止憑據](replanning.md#停止與保存)的 `replan register-executor`／`replan executor-receipt`，不執行 `replan begin`。身分須對應 lease agent ID；receipt 來自真正 executor 回應，只更新 Task status 不代表已停。
2. 依原入口準備 proposal JSON，執行 `amend-paths propose --run-id <ID> --input <proposal.json> --action-id <ID>`。Gate 綁定 effective contract、受影響 Task、checkout 內容及 executor 身分，回傳 `proposal_hash`。等待覆核期間，受影響 Slice 與 controlled checks 不可繼續；其他 Slice 可繼續不受影響的 Task 操作。
3. 不同於 proposal 作者及受影響 Implementer 的 Reviewer 閱讀核准規格、必要依賴、目前 diff、完整 proposal 與檢查定義。Review JSON 包含 `proposal_hash`、`reviewer_id`、`decision: "within-approved-scope"`、`assessment` 與 `findings: []`；assessment 的 `requirements`、`api`、`data_model`、`security`、`slice`、`checks` 各用具體非空說明支持邊界不變與選測充分。存在問題時不提交通過判定；修訂 proposal 重新覆核，或撤回後走 RP。
4. 執行 `amend-paths review --run-id <ID> --input <review.json> --action-id <ID>`。通過即追加 Technical Amendment，擴充有效 Package／Worker／Task 路徑與 checks，並依入口登記適用的新修正 Tasks；不再請使用者核准。原 Package 與歷史紀錄不改寫。Gate 封存已停止 executor 的 registry 後，依原入口續接 Task；目前必要 checks 須取得新 effective contract 的 evidence，歷史通過不能代替目前驗證。

Proposal 或綁定內容改變時，重新 propose 並取得新的獨立覆核，不沿用舊 `proposal_hash`。撤回使用 `amend-paths withdraw --run-id <ID> --input <withdraw.json> --action-id <ID>`，輸入為 `{ "proposal_hash": "<hash>", "reason": "<撤回原因>" }`。撤回也封存已停止 executor，完成後可依原授權範圍重新登錄；改提另一 Slice 前先撤回目前提案。

部分失敗以相同輸入及 action ID 重送。Review 或 withdraw 事件已寫入但 executor 尚未封存時，`next` 回傳 `retry-path-amendment` 與原操作輸入、action ID；保持 Worker 停止並完成原操作，不另建 Amendment。

## 保留未受影響審查

這是可選捷徑，限同一 Atomic Development Run、整合前 `review-fix` 完成並重新 verification 的 `reviewing` 階段。首版要求所有 Task 在同一實作 checkout、修正提交區間無 merge；其他情況走正常本輪 review。已完成 Task 的 commit 與歷史測試原本就保留，不因未使用此捷徑重新實作或補空 commit。

1. Coordinator 先在修正 Plan 說明影響與選測理由；實作修正 Task、執行相關 controlled checks 並重新 verification。對原 finding 的 Task 及新增／受影響 Task，依[獨立審查](execution-policy.md#獨立審查)提交本輪正常 Reviewer Result。
2. Coordinator 準備 impact JSON，例如：

   ```json
   {
     "author_id": "coordinator",
     "retained": [{"task_id": "T-001", "reason": "試算不依賴此次顯示文字", "dependency_paths": ["src/rules"]}],
     "affected_task_ids": ["T-003", "T-004"],
     "check_ids": ["C-display"],
     "assessment": "追蹤共用 service、mapper、contract 與設定，修正僅影響 Reviewer 顯示；顯示及修正 Task 的必要 checks 已通過。"
   }
   ```

   IDs 與 paths 使用實際契約值；`dependency_paths` 列出 Task DAG／paths 未表達、但本次分析確認相關的依賴。Gate 不理解程式語意，不能用空清單代表已證明沒有依賴。`affected_task_ids` 必須涵蓋實際 touched 與新增 Task；工具自動加入這些 Task 的全部 targeted checks，`check_ids` 可補充其他相關檢查，不能用來刪除 required checks。
3. 執行 `review-retention --run-id <ID> --input <impact.json>`。工具只產生提案，沒有追加核准事件。保存輸出 `data`，包含原 review／verification 引用、原審查波次內容、當前 HEAD／tree、累積 touched paths、契約及證據 hash。`next.optional_operations` 的候選僅是提示，仍須通過此入口驗證。
4. 不同於提案者及本 Run Implementer 的 Reviewer 檢查實際差異、未受影響理由與選測充分性，在該 `data` object 加入 `reviewer_id` 與非空 `assessment`。不要改寫機器產生的 `impact`／`binding`／`binding_hash`；判斷需要修改 impact 時，重新產生提案。保存為 `{"retention": <覆核後的 object>}`。
5. 以 `transition --event review-approved --run-id <ID> --payload-json <approval.json> --action-id <ID>` 結束本輪審查。Gate 再次檢查目前內容與證據，在 executor 停止的同一鎖定區間內追加一筆 `review-approved`，內含採認依據。相同輸入／action ID 重送不重複寫入；不另造原 Reviewer Result。

原 approval 必須尚未被新結果取代；`needs-fix` 或本輪新結果不能被採認覆蓋。基準是原 review 當時的整個 verified wave，涵蓋其後每一筆提交的 touched paths；修改後還原也視為受影響，同檔不同區塊仍保守重審。Task／既有 targeted check 定義、已知祖先依賴、明示語意依賴及凍結產品邊界必須不受影響；共用設定、lockfile、工具鏈或執行流程變動不採認。原／新 verification 還須具有相同 executor/workflow 綁定；缺少此欄位的歷史記錄仍可讀取，但使用正常 review。

歷史 evidence 不改綁新的 tree 或契約；受影響檢查必須對應當前內容，較新失敗、未知或未完成 attempt 不能退回舊成功。無法證明安全、提案漂移或捷徑成本高於重審時，提交正常本輪 review 即可，不需另建 Run 或採認恢復流程。採認者及理由隨 [交付摘要](finalization.md#2-取得交付摘要) 保存，必要整合檢查照常執行。

## Maintenance 修正完成

Maintenance 修正使用未提交快照：`correction-complete`／`review-fix-complete` 的 `--commit-id` 指定 Start Gate HEAD，checkout 必須仍在原 delivery branch 與相同 HEAD。Gate 追加的 completion payload 包含 `completion_mode: working-tree`、`commit_id`（基線檢查點）與 `content_tree`。Result amendment 將後兩者記為 `base_commit`、`content_tree`，不含 `commit_id`；final commit 帶齊 trailers，結案報告再補實際 amendment commit ID。不可把此格式套用到其他 kind，或跳過修正後的正式 checks。

同樣適用 technical correction、review-fix 與 post-integration correction。新增任務仍須依[派工](execution-policy.md#派發與隔離)及[Agent Result](execution-policy.md#登錄-agent-result)規則完成登記；completion 快照不代表驗證通過，之後重跑 controlled checks 與適用的獨立審查。Result 的 amendment 欄位及唯一 final commit trailers 依 [Finalization](finalization.md)。其他 kind 仍依原流程先建立合法修正 commit。
