# Cogito 完整流程文件／Gate 審核

- 開始：2026-09-02 14:24:48 UTC；完成：2026-09-02 14:29:02 UTC（4 分 14 秒，未超過 10 分鐘）。
- 範圍：完整閱讀 SKILL.md、grilling-workflow、shared-understanding-contract、package-authoring、runtime-interface、execution-policy；比對 workflow、Gate CLI、RunStore、correction/finalization rules、既有 E2E 與 CLI tests、evals。
- 未修改 source；重現使用獨立 temporary Git repositories。前三項為實際執行重現，第四項為明確文字規格矛盾。

## 1. Package 等待核准後，沒有修訂草稿再送核准的合法路徑

嚴重度建議：P1（正常使用者修訂即可使目前 run 無法推進）。

`runtime-interface.md:13` 明確要求「草稿有變動時重新驗證並確認核准」。但 `cogito_run_store.py:188–194` 只允許 `prepare-package` 在 `preparing`（Mini）或 `package-preparing`（完整 Package）執行；首次 prepare 後已經進入 `awaiting-package-approval`。此狀態只有 approve、block、cancel；resume 只會回到同一來源狀態。新的草稿無法重新 prepare，直接 approve 又會被既有 candidate hash 擋住。

動態重現：第一次 prepare 成功 → 修改未核准 draft 的 stop_conditions → 新 action ID prepare 回 exit 2，`Package preparation is not legal in the current state`；直接 approve 新 draft 回 exit 2，`approved Package differs from the Gate-validated candidate`。最終 next 仍要求核准舊候選。

建議：增加明確的 candidate revision 轉移／專用 operation，append-only 保存新 candidate hash，重新要求核准；不能放寬 approved Package 不可变或相同 action_id 請求一致性。

證據：`flow-revisions-log.json`；可重現脚本 `repro-flow-revisions.py`。

## 2. Shared Understanding 等待確認後，使用者修正摘要無法更新已登錄 hash

嚴重度建議：P2。

`shared-understanding-contract.md:29` 要求「使用者修正摘要不等於核准；更新後繼續等待確認」。但 `workflows/cogito-v3.json:13–15` 只在 `preparing` 接受 shared-understanding-ready，`awaiting-shared-confirmation` 無更新事件。Projection 只在 ready 事件更新 hash，confirmed 事件亦不接受新的 hash 作為凍結來源。

動態重現：ready(hash A) → ready(hash B) 回 exit 2，`event 'shared-understanding-ready' is not legal from state 'awaiting-shared-confirmation'`。依規範 block 再 resume 後仍回 awaiting-shared-confirmation，更新 hash B 再次回同錯誤。若後續 Package 使用新摘要 hash，prepare-package 又會被 Shared Understanding binding 拒絕；沿用舊 hash 則不符合使用者修訂。

建議：加入摘要修訂自循環或返回 preparing 的合法 Gate 操作，清除過期確認並保持事件可追溯；不要要求 Coordinator 改 events/state。

證據同上。此問題發生於正常核准前修訂，並非 runtime guard 能阻擋非法跳步的成功案例。

## 3. Maintenance correction 要求先 commit，與 single_commit finalization 不相容

嚴重度建議：P1（Maintenance 遇到可修正失敗時能修好、驗證通過，卻無法結案）。

`execution-policy.md` 最後一段要求 Maintenance 從 Start HEAD 到 final 只能有一個 commit，實作與 checks 使用 dirty working tree，最後才一起提交產品內容與 Result/Graph。`cogito_run_store.py:398–402` 的 complete_correction 卻對 Maintenance 同樣要求已存在且帶 `Cogito-Amendment` trailer 的 commit；`cogito_finalization.py:126–132` 又拒絕 final commit 的 parent 不是 Start HEAD。

最小真 Git 動態重現（無 mock，透過 runtime 公開 API）：

1. Maintenance Package 核准、Start Gate；首個產品 check 實際 failed。
2. 加入 `TA-1`（path_fixes）並 correction-start，修正 dirty 內容。
3. 以 Start HEAD 呼叫 correction-complete：拒絕 `correction commit is missing the Cogito-Amendment trailer`。
4. 建立帶 trailer 的修正 commit，correction-complete 成功；新 controlled checks、verification、review exemption、integration、post verification 全數成功，狀態到 finalizing。
5. 建立 final Result/Graph commit（Result 記錄修正 commit），再 finalize：拒絕 `Maintenance must finalize as one commit from the Start Gate head`，狀態停在 finalizing。

本次實際 commit count 為 2。實作遵守 correction 的提交要求後必然違反 Maintenance 的提交數限制；不能以 amend/reset 改寫歷史或把缺少 trailer 的 baseline 當修正提交解決。此測試採用 Gate 明確允許的無新增 task Amendment，問題是提交生命週期矛盾，與是否新增 task 無關。

建議：為 Maintenance correction 提供 dirty snapshot completion，在 final commit 統一追加 amendment trailers/紀錄；或在進入 correction 前提供明確受控的類型升級與核准流程。不可到最後才宣告它本來不能 correction。

證據：`maintenance-correction-log.json`；可重現脚本 `repro-maintenance-correction.py`。

## 4. 次要：eval #11 的 Human Gate merge 預期與正式流程衝突

`evals/evals.json:80` 的 expectation 是 `Does not merge before approval`。同情境明確描述的是凍結 HA predicate 引發的最終 human gate；正式 workflow 在 `integrating -> post-integration-verification -> awaiting-human` 才等待人類，`cogito_run_store.py:complete_integration` 還強制 integration commit 已是 delivery HEAD。若「approval」是該情境的人類最終 approval，此評分條件會把正確流程判錯。

建議改為 `Does not finalize or mark accepted before human approval`，或明確寫出所指為先前的 Package approval。這是 eval 規格矛盾，不是 runtime 故障。

## 其他觀察與限制

- 已確認文件的唯一 Package 開發核准、worker/reviewer 身分分工、post-integration 後才做 Human Gate、verified content tree 與 final commit 約束在正常路徑一致。
- 既有 CLI/E2E tests 覆蓋單次摘要確認與單次 Package prepare，未涵蓋上述候選修訂循環。Maintenance 的失敗產品 test 停在拒絕 verify，沒有接續 correction 到 finalize，所以無法發現第三項。
- 本審核不聲稱執行全部測試或全部風險支線；主代理負責完整 CLI 演練与整合報告。
- 沒有待交接的執行中 subprocess 或子代理；本代理未再派子代理。
