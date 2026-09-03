# Cogito a056941 修正流程重新模擬

本段從 2026-09-02 15:16:04 UTC 開始，核心驗收完成於 15:18:45 UTC，耗時 2 分 41 秒；未超過 8 分鐘目標或 10 分鐘硬上限。受測 Git HEAD 為 a056941，完整 hash 保存在 summary.json。沒有修改或提交 Cogito source；既有 untracked eval reports 保留。所有演練使用全新隔離 Git repository，沒有覆寫上一輪證據。

結果：指定場景全部符合預期，未重現上一輪 staged P1，沒有發現新的流程 bug。

## 完整 Maintenance 三段修正鏈

`run-chain.py` 透過真正的 CLI、controlled runner 與 Git 完成：

- T-1 執行後第一次產品 check 實際失敗；TA-pre technical correction 使用 Start HEAD 與 working-tree snapshot，重驗通過。
- Reviewer needs-fix → review-fix-start → TA-review 新增 T-2 → lease／Implementer Result → working-tree completion → 重驗通過。T-1、T-2 逐項登錄不同於 worker ID 的 Reviewer 通過結果。
- 整合一次後注入缺陷，post check 實際失敗；TA-post 修正後直接回 post-integration-verification，重驗通過。
- 三次 completion 都保持 Start HEAD 不变；Result 記錄 base_commit/content_tree，final commit 才一次保存所有變更與結案紀錄，帶齊三個 Cogito-Amendment trailers。
- finalize/report 到 accepted；report 將三個 amendment 的 commit_id 指向唯一 final commit。

final commit：`ea0fef7638e547ba483a2b341ddde443fd1fc4b5`。新 commit 數為 1，integration 事件數為 1，verification_corrections = 2，review_fix_cycles = 1。保留 `chain-repo`、`cli-transcript.jsonl`、`chain-summary.json`、`report.json`。

## Documentation 完整獨立審查流程

`run-additional.py` 的 documentation 場景以 Mini Package 整理既有文件空白，完成 implementation commit、controlled verification、不同 agent_id 的 Reviewer Result、review-approved、integration、post verification、final commit、accepted/report；沒有套用 Maintenance review exemption。

final commit：`5860ceae5821d241364ebfa8c65b06faca978346`。新 commit 數為 2（文件變更 + 結案紀錄），integration 一次。Documentation 不受 Maintenance 單 commit 約束，此結果符合目前規則。場景檢驗的是 Gate 對實作者與 Reviewer ID／結果的獨立性契約，沒有宣稱做過外部身分認證。證據位於 `documentation/`。

## Staged 路徑問題修復驗收

三組全新 repository 的真 CLI 現場均保留：

| 場景 | 實際結果 | 判定 |
|---|---|---|
| staged-good | 合法 staged-only note.txt 可以登錄 Agent Result，完整流程 accepted，僅一個新 commit | 原先合法 staged 誤拒已修復 |
| staged-before | note.txt 之外另 staged unrelated.txt，Agent Result 未申報該檔，Gate 拒絕 changed_paths 不符 | 合理 guard，events/index 不變 |
| staged-after | Agent Result 通過後注入並 staged unrelated.txt，post check 通過且 snapshot 包含該檔，finalize 仍拒絕 exceeds approved paths | 原先越界 accepted 已修復，events/index 不變 |

staged-good final commit：`3cfcd080cb1fbcacf53236c02dd5e5ffff2cb2bd`。兩組拒絕分別保留 executing／finalizing 狀態，沒有誤稱命令錯誤會自動把 run 轉為 blocked，也沒有繞過 guard 讓這些負面案例結案。

## 精準測試與 next/event 核對

命令：`python3 -B -m unittest -v test_staged_maintenance test_maintenance_delivery_scope`，在 cogito/tests 執行，11/11 通過，程序耗時 7.342 秒（unittest 自報 7.281 秒）。覆蓋 staged-only 合法路徑、申報／省略越界、刪除、rename 的舊路徑、非 ASCII／換行檔名、index/worktree 抵銷變更、finalization 再檢查 scope、Package 合法保存及最後驗證後才新增追蹤 Package 的拒絕。

本段保存 199 次 CLI 呼叫及逐次耗時，對 97 次成功狀態操作後的 next 回傳逐項確認 state 一致。Runner 正式 evidence、append-only events、Git commit count、integration count、三個 amendment trailers 亦已核對。命令與耗時明細在 summary.json、targeted-tests-command.json 及各 cli-transcript.jsonl；測試輸出在 targeted-tests.log。

## 交接

指定工作完成，無待驗證項目、執行中 subprocess 或子代理。可使用本目錄的 REPORT.md、summary.json、兩份重現腳本，以及各場景 repository/log 進行封存。合理的產品 guard 拒絕已與真 bug 分開列明；此輪沒有發現真 bug。
