# Skill 閱讀流程整理與驗證

本次依「重複內容、認知負荷、上下文完整性、單一責任」整理操作文件。採六個小包，每包先修改、執行相關檢查與獨立閱讀模擬，核對結果後才繼續。沒有修改 Python runtime、workflow、契約格式、Agent metadata 或版本；版本維持 3.3.0，因為本次重組與澄清既有規則，沒有新增功能或改變操作契約。

## 六個小包

| 包 | 單一問題 | 修改與核對結果 |
|---|---|---|
| 1 | Mini 適用條件出現太晚 | Package 類型移到準備前，區分一般／人工退回 review、Mini checkpoints、單一 commit 起算點；5 個閱讀情境、10 項相關測試符合預期 |
| 2 | 例外流程的前置條件後置 | RP 先分 Atomic／非 Atomic，工具接軌先分階段，DP 先保存／必要 release 再準備方案；3 個閱讀情境、10 項相關測試符合預期 |
| 3 | 結案流程散落四處 | 新增 `finalization.md` 統一最後內容核對、summary、Result／Graph、commit、登記、回報與 cleanup；3 個閱讀情境、5 項相關測試及 2 條實際 Gate 旅程符合預期 |
| 4 | 操作流程混入共通介面及實作細節 | Task、驗證、review、整合回到 Execution Policy；Runtime Interface 保留共通協定；runner 實作移到 `runtime-internals.md`；3 個閱讀情境與 8 項相關測試符合預期 |
| 5 | 正常流程被修訂與例外打斷 | Grilling 集中問答、摘要呈現／確認／修訂，摘要 contract 保留格式；人工修正以同一案例串起七個步驟，追加回饋與文件更新有獨立小節；3 個閱讀情境與 9 項相關測試符合預期 |
| 6 | 入口承擔過多責任 | SKILL 保留概念、共同限制及路由；詳細 Amendment／檔案／額度規則回到主責文件；AGENTS 保留維護政策；4 個閱讀情境與 5 項相關測試符合預期 |

最終獨立覆核發現驗證表失去 Atomic 適用標示，可能誤導目前的 Mini Package 使用跨狀態 evidence。已在表格前明示適用範圍，補清楚非 Atomic 的 required checks 與完成事件 freshness；追加 1 個獨立閱讀情境及 2 項對應測試通過，Reviewer 複核後沒有未解決項目。見 [規則保留覆核](final-preservation-review.md)。

第一包的模擬另指出 Mini 主路徑、commit 起算點與取消入口不夠醒目；同包補上並完成局部複核。第二包的模擬指出 Atomic 已整合 task 的 `omit` 容易回讀，已在入口表清楚區分「不移植 task」與「已在 delivery baseline 的內容仍保留」。

## 規則的主要說明位置

| 規則／問題 | 現在的完整說明位置 |
|---|---|
| 何時啟動、共通責任、目前讀什麼 | [SKILL.md](../../../SKILL.md) |
| Package／Mini 類型、政策、文件準備與核准 | [Package Authoring](../../../references/package-authoring.md) |
| 何時提問／保存、摘要版本與確認 | [Grilling Workflow](../../../references/grilling-workflow.md) |
| 摘要 readiness 與固定欄位 | [Shared Understanding Contract](../../../references/shared-understanding-contract.md) |
| 準備階段精確提交與登記 | [Stage Commits](../../../references/stage-commits.md) |
| Task、Maintenance 增量、check／review／integration、Amendment | [Execution Policy](../../../references/execution-policy.md) |
| CLI 輸入、action ID、事件、未知結果、停止與復原 | [Runtime Interface](../../../references/runtime-interface.md) |
| runner 程序、Git snapshot 與 evidence 發布實作 | [Runtime Internals](../../../references/runtime-internals.md) |
| 最後驗證內容、summary、Result、commit、自動清理 | [Finalization](../../../references/finalization.md) |
| 人工回饋分類、一輪修正、追加回饋、文件同步與升級 | [Human Acceptance](../../../references/human-acceptance.md) |
| 核准前候選變更 | [Planning Revisions](../../../references/planning-revisions.md) |
| RP 承接及適用範圍／Start artifact 模型 | [Replanning](../../../references/replanning.md)、[RP Snapshots](../../../references/replan-snapshots.md) |
| RP 途中工具更新 | [RP Toolchain](../../../references/replan-toolchain.md) |
| 取消後保存、release、移除／保留／恢復 | [Dispositions](../../../references/dispositions.md) |

入口保留必要的安全提醒，各操作文件承擔完整步驟。沒有以刪除 guards、恢復舊協定或放寬核准來縮短內容。`spec-template.md`、`plan-template.md` 的責任原本已清楚，未修改。

## 實際驗證

**自動化：49 項不同的相關 unittest 通過。** 使用既有測試，不新增以標題或文字比對代替行為驗證的 regression。精確命令、每包文件 hashes、情境輸入與輸出索引保存在 [results.json](results.json)。各包 log 保留實際執行結果。

第二包首次執行為 8 項通過、2 項環境錯誤：沙盒拒絕 controlled runner 的 `ps` 程序查詢。只重跑這兩項，使用允許程序檢查的暫存測試環境，結果通過。原失敗紀錄見 [首次執行](batch2-tests.log)，成功重跑見 [重跑結果](batch2-retry-tests.log)。其他需 controlled runner 的後續測試直接使用適當環境。

**Gate 端到端模擬：Feature、Maintenance 各 1 條通過。** 使用既有 `simulate.py`，建立暫存 Git repositories、真實 commits，實際呼叫 public RunStore Gates 及 controlled runner。兩條都走過階段提交、人工退回、局部修正、重新檢查、獨立 reviewer 身分、明確接受、finalization。輸入中的人類／reviewer 決策為合成資料。

```sh
python3 cogito/evals/reports/2026-09-03-stage-delivery/simulate.py \
  --output /tmp/cogito-skill-readability-simulation.json
```

此命令需要允許 `ps` 程序查詢，指定新輸出路徑以保留歷史報告。實際結果：[runtime simulation](batch3-runtime-simulation.json)、[執行輸出](batch3-runtime.log)。Git IDs 來自已清除的暫存 repositories，不是本專案的 commits。

**獨立閱讀模擬：22 個情境完成並由主代理核對。** 每次用沒有父任務歷史的新子代理，只提供合成情境、目前 SKILL 與必要 reference 入口；不提供預期答案、改法、舊報告或程式碼。各報告列出實際閱讀順序、決策與回讀點：

- [Package 選擇](batch1-agent.md)
- [RP／工具接軌／DP 入口](batch2-agent.md)
- [結案](batch3-agent.md)
- [Task 與 evidence](batch4-agent.md)
- [問答與人工退回](batch5-agent.md)
- [最終入口路由](batch6-agent.md)
- [Atomic／Mini evidence 適用範圍追加模擬](batch6-scope-agent.md)

這些是閱讀決策推演，不是真實 Gate 操作、使用者核准、正式 evidence 或自然語言準確率基準。它們補足文件理解檢查；實際 Gate 模擬則驗證 runtime 路徑，兩者不能互相取代。

**格式與連結：** skill-creator 的 `quick_validate.py` 通過；本次操作文件的相對 Markdown 連結與 anchors 已核對；`git diff --check` 通過。格式工具的 PyYAML 僅安裝於暫存目錄，沒有改動專案依賴。

未執行完整 regression、CI 或 mypy：變更限文件與驗證紀錄，沒有修改執行程式或型別。既有 runtime tests 通過不證明任意 Agent 都會正確遵循文件，真實使用仍需觀察。

## 閱讀負擔的變化

SKILL 從 8,211 降到 4,549 字元；共通 Runtime Interface 從 12,212 降到 5,906 字元。Execution Policy 因吸收散落的任務規則而較長，但讀者能依 Task → 驗證 → review → 整合順序閱讀，不再到「儲存與復原」找正常任務步驟。

這是文字量與責任位置的觀察，不是模型 token 消耗、執行時間或錯誤率的實測。保留了必要的例外與相容性資訊，沒有以總字數最少為唯一目標。
