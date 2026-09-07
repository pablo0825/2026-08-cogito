# 結案與交付回報

本流程只在 Gate 的 `next_action` 為 `write-result-and-finalize`、狀態為 `finalizing` 時使用。先前的驗證、審查及適用人工驗收必須已完成；產生摘要或建立 commit 本身都不代表結案。

順序是：確認最後驗證內容 → 取得交付摘要 → 準備 Result／Project Graph → 建立 final commit → 登記並確認 accepted → 回報結果。

## 1. 確認最後驗證內容

產品變更與必要且合法的 Spec／Plan 更新，必須在最後一次正式驗證前完成。Gate 將 final commit 與 evidence 的 `worktree_binding.content_tree` 比對；驗證後只有本 run 的 canonical Result 與 Project Graph 可以改變。缺少 `content_tree` 或對應 Git object 時，重新執行 controlled checks，不修改舊 evidence。

先確認本次 kind 的提交方式：

| `kind` | final commit 保存什麼 |
|---|---|
| `feature`、`change`、`correction` | 只保存本 run 的 Result 與 Project Graph；產品工作已由 Task／合法修正 commits 保存 |
| `maintenance` | 已驗證的工作樹產品內容、Result 與 Project Graph 一次提交；Start Gate HEAD 必須是唯一 parent，且從該 HEAD 起只有這一個新 commit |
| `documentation` | 可提交已驗證的工作樹內容及 Result／Project Graph；不能夾帶驗證後的新修改或漏交已驗證檔案 |

Maintenance 的任務與修正不提前建立產品 commit。Implementer Result 可使用相同 base/head，integration milestone 記錄 Start Gate HEAD 作為未提交成果的檢查點；最後才提交產品與結案紀錄。不要先提交產品，再補一個 metadata commit。

所有 kind 都會再次核對 Start Gate HEAD 到 final commit 的完整交付範圍。產品修改必須在 Package 或有效 Amendment 的核准路徑內；控制文件只接受既有精確例外，不能因位於 `docs/` 就取得豁免。凍結 Package 須內容相符，採納來源依凍結 bytes/hash 或已核准路徑處理，Spec／Plan 依既有政策且先於最後驗證更新。通過 integration 或 content-tree 比對都不能取代範圍檢查。

## 2. 取得交付摘要

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> delivery-summary --run-id <ID>
```

將輸出 JSON 的 `data` object 原樣放入 Result 的 `delivery_summary`，不要包含外層 `ok`／`data` 包裝。摘要從同一份事件快照產生，包含準備 checkpoints、各次實作與修正、實際整合版本、controlled checks、獨立審查及人工退回／修正／接受紀錄。查詢不建立 commit 或追加事件。

啟用 `stage_commits` 或曾採認舊審查的 run 必須提供摘要；其他舊 run 可省略，但若提供也必須與事件相符。缺項、過期、改動 commit 或使用不符的驗收摘要都會被拒絕。先前 blocked／失敗的 Agent Result 仍保留為歷史，不要求未採用的工作版本被整合。

審查採認放在 `delivery_summary.verification` 的 `review-approved` receipt 內，欄位為 `retention`；原本的 Reviewer Result 仍位於 `reviews`，實際執行的 checks 仍保留原事件。Result 頂層 `reviews` 須同時列出原 Reviewer 與採認 Reviewer。`report.review_retentions` 從這份摘要產生，可追溯原 review、本次採認者、選測理由及內容綁定，不代表舊測試在新版本重新跑過。完整採認條件與操作見 [Execution Policy](execution-policy.md#保留未受影響審查)。

## 3. 準備 Result 與 Project Graph

Result 保存 checks、reviews、已知 commit/amendment 摘要與剩餘風險；Project Graph 保存最終 disposition 並清除該 run 的 `active_run_id`。兩者由同一 final commit 原子保存。

歷史 Result metadata 的限縮更正另列於 delivery summary 的 corrections，精確引用原事件；它不是產品修正或 Amendment 完成，不新增產品 commit。原 implementation 記錄保留，Gate 投影採用已驗證的更正。

Result 不內嵌包含自身的 final commit ID。Maintenance 的 amendment 使用 `{id, base_commit, content_tree}`，必須符合 completion event；不填尚未存在的 final commit ID。經獨立覆核的路徑補正使用 `{id, proposal_hash}`，必須對應已生效的 proposal；它只追加授權，不填 `commit_id` 或要求獨立 amendment commit。實際產品內容仍由各 Atomic Task commit 交付。其他修正依其已登錄的合法修正 commits 記錄。

Git 保存交付摘要與證據引用；完整檢查資料與回饋原文仍在本地 `.cogito`，不提供從 Git 摘要還原完整事件的能力，也不另建 audit branch。

## 4. 建立並登記 final commit

建立符合第 1 節範圍的單一 final commit。Maintenance 必須帶齊所有適用的 `Cogito-Amendment: <ID>` trailers。Gate 也會確認準備 checkpoints 與已提交 amendments 的 commits 是 final commit 的祖先。

取得實際 commit ID，再登記：

```sh
python3 cogito/scripts/cogito_gate.py --repo <root> finalize \
  --run-id <ID> --result <Result-JSON-path> \
  --project-graph <Project-Graph-JSON-path> \
  --final-commit <actual-commit-id> --action-id <stable-action-id>
```

Gate 驗證提交內容、範圍、Result、Graph 與事件。通過後才把 final commit ID 追加到事件歷史，轉為 `accepted`。不要為了在 Result 填入自身 commit 而 amend 或重寫 commit。

## 5. 回報與清理

以 `report --run-id <ID>` 取得結案結果。它讀取 final commit 內的摘要，另附實際 final commit ID；不從目前工作副本重建或改寫 Result。Maintenance amendments 的實際 final commit ID 只補在衍生報告。

向使用者回報：結果、實際 checks、獨立 review、commit IDs、amendments、是否經 human gate、剩餘風險及需要處理的清理保留原因。不要將本地測試通過當成 CI 通過。

### Worktree 清理

`finalize` 成功寫入 `accepted` 後，自動嘗試回收本次 Run 已不再使用的 Cogito worktree。只有核准 Package、Task lease（或 RP adoption）與 Git 登記一致、Task 已整合、HEAD 已完整包含於 final commit，且沒有執行中的 Worker／check、其他 Run 引用或進行中的 RP／DP，才會移除。只處理 `.cogito/worktrees/` 內的實際受管目錄；目前工作目錄、符號連結、locked worktree、未提交或未追蹤內容、隱藏修改的索引旗標都會使清理保留該目錄。

已忽略的 `node_modules`、`__pycache__`、`.pytest_cache`、`.mypy_cache` 可隨 worktree 移除；其他 ignored 資料（例如 `.env`、本地資料庫）會阻止清理。使用一般 `git worktree remove` 一併移除該 worktree 的 Git 登記，不使用 force 或全域 prune；branch 與 `.cogito/runs/<run-id>` 全部保留。清理前以 `refs/cogito/cleanup/<run-id>/` 保護事件與 evidence 引用的 Git 物件，避免後續 Git GC 破壞稽核內容。

`finalize` 回應的 `cleanup.removed`／`cleanup.retained` 列出移除項目與保留原因；清理故障不會撤回 `accepted`。排除保留原因後，重送原本相同參數與 `--action-id` 的 `finalize` 即可重試，不重做驗收或追加結案事件。已清理的 worktree 直接略過。Run 內的 `cleanup.json` 留存與 accepted 事件綁定的清理憑據，供中斷恢復及後續 RP／DP 辨識已清理的歷史 worktree；不改寫原事件、evidence、Result 或結案報告。沒有額外清理命令、branch 刪除或 runtime 到期刪除政策。

## 失敗時如何恢復

任一步失敗都先停止操作、查詢 Gate 與既有提交，確認事件是否已落盤。commit 已成功而事件尚未登記時，使用原 commit ID、相同參數與 action ID 重送 `finalize`，不再次 commit。已是 `accepted` 而清理保留時，同樣重送原請求只重試清理。

內容漂移、證據不足或結果無法核對時，不先報結案；依 [Runtime Interface 的停止與復原](runtime-interface.md#停止條件與狀態操作) 登錄阻塞或處理既有合法修正流程。不要直接改 state、events 或 evidence 使檢查通過。
