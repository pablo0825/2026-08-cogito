# Batch 4：前向閱讀模擬

僅閱讀当前 Skill 與相關 reference；未執行 Gate、測試或實際流程，以下不是通過證明。

## A：同 Slice 相依 Atomic Tasks

T1 先建立非空、單一 parent（lease base）的獨立 commit；提交後完整內容須與提交前 evidence 相同。登錄 Implementer Result，evidence 精確涵蓋 T1 check_ids，再 task complete，之後才能 lease/running T2。T2 同樣實作、targeted checks、獨立 commit、Result、complete。波次 verify 使用 checkout 最新完整內容；T1 evidence 保留為歷史 Task 證據，不要求在 T2 HEAD 重跑，也不能代替最新內容的 verify。T2 相同內容提交前 evidence 可用於本輪 verify/review。獨立 Reviewer 逐 task 使用各自 Result base/head，當前內容仍須匹配本輪驗證；Gate 計算 closure。Coordinator 串行整合已審查 tip，正常 merge-tree 結果不得夾帶修改；跨 Slice 依賴至 integrated 才解鎖。最後在最新 delivery HEAD 執行 required integration checks，再依 Gate 進入 human/finalization。

## B：Maintenance 增量與最終範圍

假設 a 僅有 T1 已登錄修改且 T2 未再變更，T2 changed_paths 應為 b、c、d、e；staged b 與 untracked c 都要列，rename 列刪除 d、新增 e。比對 lease 的 working-tree 與 index 雙快照，因此 a 不屬 T2 增量；整體累積 a–e 仍須在 Package approved_paths。任務不建立產品 commit，保持 Start Gate HEAD；適用獨立 review 使用各 task 完成快照歸責，並確認當前內容等於本輪正式驗證。只有符合核准低風險條件且 Gate 接受才可豁免。最終一個 commit 保存全部已驗證產品、Result、Graph，唯一 parent 為 Start Gate HEAD；最終範圍檢查涵蓋累積交付。舊 lease 完全沒快照時採 baseline 全範圍保守驗證，不能補造快照或套用此增量規則；不完整／遺失物件則拒絕。

## C：未知 controlled attempt

不得刪除 marker，也不得同 ID 強制重跑。保留 attempt、原始指紋及現場，先確認程序狀態與可能外部副作用，再決定是否以新 action ID 執行。若其實已有完整發布 evidence 而只是事件追加失敗，才可用原 ID、相同輸入驗證並補登錄既有 evidence。無完整 evidence 的已開始 attempt 是未知結果，不能聲稱恢復成功；無法對帳時停止推進，若 Gate 可用則依 Runtime Interface 登錄 block，且 block 不會自行停止 subprocess。

## 閱讀順序與可讀性

1. `cogito/SKILL.md`：不變量 → 執行協定 → 操作路由 → 權威資料 → 文件與邊界 → 最終化。
2. `references/execution-policy.md`：完整依文件順序讀取；重點為派發與隔離 → Atomic Task → Maintenance 快照／舊 lease → 本波／整合後驗證 → Check 重送 → 獨立審查 → 串行整合。
3. `references/runtime-interface.md`：完整依順序讀取；儲存與復原明确解答 marker 禁令與新 action，停止規則補足未知結果處理。
4. `references/finalization.md`：完整依順序讀取；最後驗證內容與 kind 表明確區分 Maintenance 單一 commit、累積範圍與最終化例外。

無須回讀、查原始碼或歷史報告即可完成判斷。A 的一般 HEAD 綁定規則隨後有 Atomic 相同內容提交前 evidence 例外，讀到本波驗證與 review 即可解開，無實質歧義。B 舊版多 task run 的「另外處理」未具體指定恢復方案；只能判定不得自動套用增量規則，不能從本次閱讀推導可執行遷移步骤。C 在 execution 的簡述到 runtime 的儲存／復原節才明確出現禁止刪 marker；路由能導向答案。
