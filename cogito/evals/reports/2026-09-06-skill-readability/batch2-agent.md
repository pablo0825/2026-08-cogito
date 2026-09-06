# 合成文件模擬：例外入口

僅依當前 Skill 與相關 reference 推理；未讀程式碼、Git 歷史或舊報告，未操作真實 run。以下不是實際授權、Gate verdict 或檢查證據。

## A：Atomic successor 與證據

**首讀順序：** `SKILL.md`「執行協定：核准契約變更」→ `replanning.md`「先確認承接方式」→「停止與保存」→「重新釐清與提案」→「獨立覆核與使用者核准」→「承接與中斷恢復」。

API 變更超出 Technical Amendment，建立 RP，先停止並保存 source。每筆 source task 恰好列一次；atomic proposal 使用 `omit`、`target_task_id: null`，不採用舊 evidence（選 `rerun`）。已整合 task 的內容自然存在保存的 delivery baseline，不因 `omit` 移除，也無須盲目重做；依 API 影響重驗。未整合但已完成的 task 留在 source 快照，在 successor 規劃新的 atomic Task，重新 lease、實作、檢查及交付，不能預先移植 commit 假充新 Task 交付。successor 保留 `task_delivery: "atomic"`，新 Slice ID 以 lineage 指向原 Slice。精確提案須獨立覆核及使用者核准，再完成 handoff；使用者說要帶成果不是承接授權。

**回讀點：** 表格只說「未整合來源」，後文要求每筆 source task 且「Atomic 提案…使用 omit」，需合讀以理解 integrated task 仍列 omit，但其內容已在 baseline；這是措辭需回讀處，不是 reuse 例外。

## B：一般工具接軌與 handoff 修復

**首讀順序：** `SKILL.md`「操作路由：RP 途中更新工具」→ `replan-toolchain.md`「先確認目前階段」→「支援範圍」→「提案與覆核」→兩個續接小節。

兩者均由 Gate 選規則，先工具提案、真正獨立覆核、精確 hash 的人工核准。

`analyzing` 的未提交 tool-only 更新可先接軌並繼續規劃；核准回到 `analyzing`，清除有效產品 RP proposal/review/approval 引用，保留歷史。RP Package 核准前工具 HEAD/index/content 必須一致：先提交，再對新 HEAD 重新工具接軌；候選 baseline 改變則 `planning begin` 修訂、prepare-package、獨立 planning review，再新 RP propose/review/approve。一般接軌要求 `rerun`。

題定 `handing-off` 邊界與完整提交符合修復入口，仍須通過 tool-root、線性 tool-only 提交鏈等檢查。工具核准僅追加 `runtime_toolchain` binding，保留原產品提案、覆核、核准與 intent，維持 `handing-off`；以原 handoff action ID 重送，重驗 immutable Start artifact，後續重跑必要 checks。pending repair 期間不得啟動 successor、移植或完成交接。

**回讀點：** 無需推翻階段表；一般接軌「清除引用」不可套用修復；未提交接軌也不是 dirty checkout 的永久豁免。

## C：取消 Maintenance 後準備移除方案

**首讀順序：** `SKILL.md`「取消／成果處置」→ `dispositions.md`「已確認的決策」→「狀態與權責／停止與保存」→「準備方案前：確認是否需要釋放 checkout」→「選擇處置並提出方案」。

先 DP begin 限制派工，真正停止 executors，DP stop 保存 HEAD/index/content 並完成取消、Graph 釋放；題定已 archived 時先確認這些既有結果，不重做外部操作。分析產品及語意相依，暫停受影響任務。

在準備 follow-up 前，必要時 `disposition release`，只將已保存、屬 DP 範圍的 dirty 路徑還原到保存 HEAD；保留 archive refs/manifest、原 worker worktrees、Graph 更新、範圍外使用者修改，不移動 HEAD。未知漂移拒絕覆寫；同一路徑混有未能分離的使用者修改也不能宣稱可安全釋放。已整合內容留在 HEAD。

然後正常 preparation Gates 準備新正式 run，DP remove 提案綁其候選 hash、impact、acceptance，獨立覆核後交使用者審核。DP 核准之外，還須正常 approve 同份 follow-up Package；正式執行、驗證、覆核並強制人工驗收。follow-up accepted 後才能 DP complete 解除範圍。

**回讀點：** 無；「準備方案前」清楚把 release 放在 preparation 前。取消或要求移除提案均不等於批准移除已整合內容。
