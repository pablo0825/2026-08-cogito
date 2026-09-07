# 第二批：修正後保留有效成果

日期：2026-09-07。基準：Cogito 3.5.0，commit `651f6ad`。
狀態：計畫草案；尚未實作。此文件不是 Cogito Run 或 Package。

## 1. 目標與減法決策

同一 Run 內發生局部修正時，保留未受影響的 Task 成果與審查，只補做受影響的檢查及審查。Coordinator 提出影響分析，獨立 Reviewer 確認，Gate 驗證可機械檢查的綁定。

第二批不做並行正式審查；保留現有實作 → 驗證 → 審查順序。並行審查延到第三批評估，並非承諾一定實作。不新增 branch、worktree、Run、排程器、自動依賴分析器或通用證據快取。

## 2. 現況：已有的能力不重做

- `cogito/scripts/cogito_run_store.py` 的 `_validate_atomic_wave` 保留歷史 Task Result 與 evidence，不因後續 amendment 要求原 Task 重交；同時驗證當前 checkout。
- `cogito/scripts/cogito_gate_validation.py` 的 `verification_checks` 在 atomic implementation 階段不重跑全部 Task checks；post-integration 仍要求契約指定的整合檢查。
- `cogito/scripts/cogito_path_amendment_state.py` 禁止修改已完成 Task，路徑增補只針對未完成工作。
- `cogito/tests/test_path_amendment_flow.py` 與 `test_atomic_task_verification.py` 已有成果保留、相關整合檢查及 evidence 防竄改案例。這些是現有測試程式，本文撰寫時未重新執行。
- 真正需要調整的是 `RunStore.transition('review-approved')`：它先只取最新 `verification-passed` 之後的 Reviewer Result，再交由 `derive_review_decision` 判定，因此修正後不能直接沿用前輪 approval。

不能只讀 `derive_review_decision` 就斷言目前存在跨輪自動採認；必須連同呼叫入口的 cycle 過濾一起檢查。

本批不放寬 evidence 的 tree／contract hash 比對。不把舊測試標成「已在新版本跑過」；透過既有歷史 Task receipt 保留完成認定，受影響行為在修正後內容上取得新證據。

## 3. 最小適用範圍

首版限定同一 Run、Atomic Development、整合前的 `review-fix → verifying → reviewing`。

採認是可選捷徑；不提供採認資料時，照既有本輪逐 Task review 完成。跨 Run／RP successor、Maintenance、人工退回、整合後修正及工具鏈變動維持既有規則，避免同時改動多種恢復路徑。

已完成 Task 不重開、不重交 commit；有產品修正仍新增既有 Amendment Task。第一輪沒有舊 approval 的 Task，仍須完成正常獨立審查。`needs-fix` 不能採認為通過，也不能由新增修正 Task 的 approval 自動解除原 finding。

## 4. 操作方案

### 4.1 提出選測與審查保留理由

Coordinator 在既有修正 Amendment／Plan 中說明：

1. 修正行為與實際依賴：包含共用 service、mapper、contract、設定、測試工具及上下游行為。
2. 需重新檢查與審查的 Task／check IDs，以及理由。
3. 擬保留的既有 approval 及未受影響理由。

前期選測理由不等於最終採認。修正完成、相關 checks 通過、正式 verification 成功後，才對實際 diff 做採認；不在改碼前承諾舊成果必然有效。

### 4.2 工具產生事實，Agent 提供判斷

優先擴充既有 review 操作及 `next`，只新增必要的可選採認輸入，不建立第二套 approve 流程。具體 CLI 名稱於第一個實作 Task 確認；本文不將尚不存在的命令列作操作指引。

工具從帳本與 Git 產生原始 review 的 sequence/hash、Task/Implementer、原審查波次、目前 verification、原／新 checkout trees、有效契約、累積 diff、候選 check IDs。Agent 不手填可推導的 hash、commit 與狀態。

Coordinator 提供保留對象與影響理由；Reviewer 確認選測充分性與未受影響判斷。Reviewer 必須獨立於提案者與被採認／受影響的 Implementer；可由既有合格 Reviewer 處理，不另要求新角色。

### 4.3 採認與正常審查共用 closure

新增最小 append-only 採認紀錄，綁定原 approval、目前 verification 與被覆核的完整提案。原 Reviewer Result、事件、evidence 不改寫；不偽造一份新的原 Reviewer Result。

本輪 closure 要求每個適用 Task 都有「本輪有效 approval」或「本輪有效採認」。新增 Task、受影響 Task、原有未解除 finding 的 Task，必須走正常本輪 review。

原 Task 即使 commit 未變，其行為也可能被後續共用邏輯改變，因此機器篩選只產生候選，不自動批准。Gate 的機械輸入限於 frozen Task paths、check 定義、DAG、本輪明示的影響分析及 Git 差異，不承諾自動理解 service／mapper 語意依賴；Reviewer 負責檢查這些語意依賴與分析是否完整。

本批不擴張整合或結案豁免：當前內容 verification、必要整合 checks、獨立審查與 Result 可追溯性全部保留。報告區分「歷史測試」「本次重跑」「本輪重新審查」「本輪採認」。

## 5. 保守的採認條件

全部成立才可採認：

- 同 Run、允許的 correction cycle，沒有未完成 Worker/check 或其他既有阻塞；採認仍在現有 reviewing 階段。
- 原 approval 真實存在、完整性可驗證且未被後續 needs-fix／新結果取代；精確綁定原 Task Result 與獨立 Reviewer。
- 原實作 commit 仍在目前提交鏈；Task 責任、Acceptance、required checks 與產品／安全邊界未被修改。
- 對比基準是原 approval 當時所審查的整個 wave 內容，不只是原 Task commit，也不只是最近一次修正。多輪修正累積比較，首版不建立採認接採認的遞迴鏈。
- 首版同時檢查原／新內容差異及這段提交歷史中曾變動的 paths，涵蓋 rename/delete；途中修改後還原仍保守視為曾受影響。無法可靠取得區間（含複雜 merge）時不採認。代價是部分最終內容相同的工作仍需重審，換取較小的判定複雜度。
- 實際 diff 不觸及候選 Task 路徑、已知相關依賴或共用測試／設定；同檔即使不同行，首版仍保守要求重審。DAG 沒有邊不代表無依賴。
- 共用規則、資料模型、權限、公開契約、lockfile、測試執行環境或 executor/workflow 變動，不能只憑檔案不重疊採認；不在首版可證明範圍者走正常重驗／重審。
- 受影響 checks 已有當前內容的有效 controlled evidence；不得用舊成功遮蔽較新失敗、執行中或未知結果。已核准 required checks 不因選測理由被靜默刪除。
- 提案、當前內容或 verification 變動後，原採認不能套到新波次；相同 action 重送不重複追加，資料不同拒絕。未知或不完整歷史可讀取，但不新授予採認資格。

任何條件無法證明，就使用既有重驗／重審途徑，不另開恢復流程。正常授權內的保留不增加使用者核准；產品／安全邊界變動依原規則處理。

## 6. 具體例子

T-001 試算、T-002 送件、T-003 Reviewer 顯示在第一輪接受審查；T-001、T-002 已通過，T-003 被指出顯示文字錯誤。

新增 T-004 修正顯示文字，跑顯示相關 checks 並 commit。重新 verification 後，工具列出 T-001、T-002 的原 approval 與本次實際差異；Coordinator 說明無依賴影響，Reviewer 確認後採認。T-003 的 finding 及 T-004 修正內容仍須本輪審查。T-001、T-002 不重做、不新增 commit，也不補跑未受影響的 Task checks。

若 T-004 實際改了共用 cohort resolver，則試算與送件可能受影響，不採認兩者的舊 approval，補足相關檢查並重審；仍不要求重做原實作或製造空 commit。

## 7. 分包實作與驗收

先固定資料模型與以下各包精確 allowed paths；不以本表作任意擴張範圍授權。每包由主代理實作，相關 checks 通過後獨立 commit，子代理做獨立測試／模擬／審查。

| Task | 單一責任／預計範圍 | 驗收與 targeted checks |
| --- | --- | --- |
| T-001 | 採認契約與純判定：contract、rules、對應 tests | AC-01：合法與不合法候選明確區分；覆蓋共用依賴、原 finding、契約漂移及多輪累積差異 |
| T-002 | 本輪採認登記與 review closure：run store、projection、事件及相關 tests | AC-02：只審受影響 Task 也能合法閉合；AC-03：無採認仍按舊流程；重送／中斷不偽造核准 |
| T-003 | next／report／finalization 與操作文件 | AC-04：機器生成事實欄位；AC-05：原審查及採認者均可追溯，真實 Git 流程能走到 accepted |

跨多個 core module 的變更需先核對影響，單包過大再拆，不為測試或審查製造產品空 commit。Python executable contracts 維持唯一驗證來源，不新增平行 JSON schema。

必要情境：局部文字修正成功採認、共用邏輯拒絕、無原 approval、舊 needs-fix、證據竄改／較新失敗、同檔改動、rename/delete、修改後還原、多輪修正、契約及環境變動、相同 action 重送／不同輸入拒絕、登記後回應遺失、舊帳本重播、完整 accepted 與 report。保留原始事件 hashes；新事件與 Result 擴充方式需驗證舊記錄相容性，不在 load 時補造採認。

執行受影響的 atomic verification/correction、review decision、event repository、finalization／report 與新增測試，以及設定範圍 mypy。文件操作變動做 focused reading simulation。自動測試、文件模擬與真實 Gate 執行分開報告；完整 regression 留給 CI，不宣稱未執行的 CI 通過。

## 8. 風險與停止條件

| 潛在問題 | 處理方式／剩餘限制 |
| --- | --- |
| 檔案未變但行為受共用依賴影響 | 既有依賴＋實際 diff＋獨立 Reviewer；無法保證 Agent 能找出所有語意依賴，疑慮時重驗 |
| 把舊 evidence 換 hash 當新測試 | 禁止重綁；保留歷史 receipt，當前修正使用新 evidence |
| 混淆原 Task commit 與原審查內容 | 綁原 wave verification，所有後續差異都納入 |
| 舊 approval 覆蓋新 finding | 精確事件引用與替代關係檢查；needs-fix 必須正常解除 |
| 採認本身比重審更麻煩 | 可選捷徑，機器產生事實，單次覆核合併既有 review；小修改可直接走正常審查 |
| 加入新事件卻漏改結案或重播 | T-003 必須驗證 accepted/report，不以局部 validator 通過宣稱交付 |
| 一次擴張所有 correction 類型 | 首版只做整合前 review-fix；其餘維持現況 |

若發現必須放寬當前 evidence 驗證、改寫舊核准、重做跨 Run 採認、增加並行狀態或通用依賴引擎才能完成，停止實作並回報重新評估。版本只在行為完整交付並驗證後更新；計畫本身不更新 VERSION。

## 9. 計畫審核紀錄

主代理已核對現有 receipts、path amendment、review cycle、verification、integration 與 finalization 入口。調整後重點是選擇性審查採認，而非重新建立已存在的 Task／測試保留。

獨立子代理已檢查現有實作，確認本批缺口位於 review closure 的本輪過濾，並要求精確原事件引用、當前內容綁定、保留 finding 與 required checks、完整結案測試。上述要求已納入第 4–8 節。曾提出的隱性跨輪 reuse 疑慮，經主代理指出入口 cycle 過濾、子代理複核後撤回，不列為缺陷。

本次僅撰寫計畫，未執行新功能測試或修改 backend 的 Run。

子代理再讀計畫後未發現阻塞，提出兩項必要澄清：限制機械依賴分析的資料來源、明定 touch 後 revert 的處理。主代理已分別補入第 4.3 與第 5 節；採保守拒絕採認，避免默認新增語意依賴引擎或省略中途變動。
