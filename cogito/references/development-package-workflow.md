# Development Package Workflow

完整適用於 blueprint 明確設定 `Execution Mode: sequential-package`、已有 canonical source 的單一 active Feature Slice。`controlled-parallel` 重用本文件的 Development Package、Preparation Authority、Autonomy Budget、review–fix 與 Final Approval 邊界，但候選數量、Wave Approval、worktree、Worker 與 integration 只依 [controlled-parallel-workflow.md](controlled-parallel-workflow.md)。缺少欄位或使用 `legacy-staged` 時不得套用本文件。Rolling Adoption 與 Maintenance 仍走既有 staged workflow。

## 授權模型

本模式區分三種權限，不能以其中一種推論另一種：

### Preparation Authority

專案經使用者核准採用 `sequential-package` 或 `controlled-parallel` 後即建立 standing Preparation Authority；`confirmed + ready` 的 Shared Understanding 只是啟動條件，不是新的授權。AI 可進行可逆的開發包準備：執行 Boundary Gate、分析程式、配置候選 ID、建立或修訂 blueprint／Brief／Spec／Plan draft，並產出 Development Package 摘要。Preparation Authority 不授權 commit、worktree／branch 建立、Worker、實作、AI Verification、Review Fix 或 Final Approval。

所有準備內容必須留在 working tree 且不 stage；開始前仍依 commit workflow 記錄並保留使用者既有變更。若準備內容與既有 staged changes 或目標檔案修改無法安全分離，停止，不以 package mode 繞過 working-tree 邊界。

### Package Approval

使用者明確核准目前 Development Package 時，核准對象是摘要指向的 exact drafts、核准 baseline、Commit Plan、Autonomy Budget、Review-Fix Budget、Verification Gates 與停止條件。這一次核准授權：

1. 沒有拆分時建立 Approval Documentation commit；有拆分時先建立核准的 Blueprint Revision commit，再建立唯一 Execution Candidate 的 Approval Documentation commit。兩者都必須檢查 exact files 與完整核准 metadata。
2. 依唯一 Execution Candidate 的 Plan 連續執行所有尚未完成的 implementation batches。
3. 自動執行完整 AI Verification。
4. 由獨立 Review Agent 進行 code review。
5. 在核准的 Autonomy Budget 內執行 review–fix loop，再重跑受影響 checks 與獨立 review。
6. 保存 Verification 與 review report，將 Slice 推進至 `awaiting-human` 後停止。

Package Approval 不授權 Final Approval、Human Integration、Human Acceptance、push、改寫 Git history 或下列停止條件中的變更。`sequential-package` 仍沿用目前 checked-out branch 的 commit model，不提供 worktree isolation 或 merge queue；`controlled-parallel` 只有額外取得未到期 Wave Approval 後，才依其 workflow 建立隔離環境與序列 integration。

### Final Approval

只有使用者檢視最終摘要、必要的 Risk Hotspots 與 Human Acceptance 結果後，才能確認 Final Approval 並將 Slice 設為 `accepted`。低風險不代表自動接受；未收到回覆時保持 `awaiting-human`。

## Grilling 後自動準備

Shared Understanding 成為 `confirmed + ready` 後，不再要求新的 `$cogito` Boundary Gate 或 Spec／Plan invocation；完整讀取 spec-plan workflow 並在同一 sequence 進行下列準備。

### Boundary Gate 通過

1. 依 confirmed summary 與 canonical sources 執行 Boundary Gate。
2. 建立或修訂本 Slice 的 Brief、Spec／Plan draft 與必要 blueprint 欄位。
3. 完成實作調查、Verification mappings、Development Package、Commit Plan 與風險分析。
4. 不 stage、不 commit、不開始實作；向使用者呈現摘要並等待 Package Approval。

### Boundary Gate 要求拆分

1. 依 blueprint workflow 的垂直結果規則產生拆分候選，不建立技術層 Slice。
2. 為拆分候選配置 provisional ID，準備 blueprint／Brief 與各候選的 Spec／Plan draft；在結構未核准前不得把候選表示為 approved。provisional ID 在 Package Approval commit 前不是穩定 ID；核准寫入 Git 後才適用永不重用規則。
3. Development Package 必須呈現修改前後結構、每個結果、Included／Excluded、依賴、執行順序、可平行性、ID 影響、時程與整合風險。
4. package 必須指定恰好一個 `Execution Candidate`，通常是共同前置 Slice 或最接近原 Goal 的候選。其他候選即使已有 Spec／Plan draft，仍保持 `proposed` 與 pending approvals。
5. 所有拆分候選等待 Package Approval；不得開始實作，不啟動任何候選 Slice，也不 commit。
6. Package Approval 只核准結構與 `Execution Candidate` 的執行 package；其他候選只在 blueprint／Brief 保存為 `proposed`，不取得 Spec／Plan approval 或實作授權。它們的 Spec／Plan preparation 可供本次審查，但不持久化為 active drafts，以免占用 active slot。
7. 建立 split commits 前，只清理本次 package 自己建立、且未被使用者修改的非 Execution Candidate Spec／Plan drafts；先核對內容與路徑，不刪除或覆蓋使用者檔案。使用者拒絕或要求修改時保留 working-tree drafts 並再次呈現 package。

新增前置 Slice、改變切割、依賴或執行順序即使不改產品結果，也屬 orchestration change，必須列入 package 並等待核准。

## Development Package

Plan 的 `Development Package` 與對話摘要共同提供核准基礎。摘要預設只呈現下列內容，完整文件可展開：

- 本次交付與明確不做的事項。
- 與 Shared Understanding 的差異；沒有差異時明記 `None`。
- Boundary Gate 結果、Slice 結構、依賴、執行順序與唯一 Execution Candidate。
- 主要實作方式、共用區域與整合策略。
- Acceptance、Verification Gates 與 Human Integration／Acceptance。
- 風險分類、緩解方式與需要使用者查看的內容。
- Autonomy Budget、Review-Fix Budget 與停止條件。
- 核准後會自動執行到哪裡。

任何 Agent 新增的產品假設、未驗證的重要事實、Scope Delta、拆分、前置依賴或高風險區域都必須出現在摘要，不能只藏在完整 Spec／Plan。

Package Approval 只接受 immediately preceding unresolved package 的 exact drafts。對話中斷、canonical／Brief 漂移、target files 改變或無法證明內容相同時，重新檢查並呈現更新摘要；不把舊的「核准」套用到新內容。

## Autonomy Budget

核准後可以在 Plan 明列的 Files／Internal Areas 內修改內部實作與測試，並處理不改變產品語義的低風險整合問題。不得自行改變：

- 已核准的產品行為或 Acceptance。
- 公開契約、事件格式、CLI 或持久化格式。
- 資料模型、migration 或資料轉換規則。
- 認證、授權、秘密資訊或其他安全邊界。
- Slice 責任範圍、切割、依賴或執行順序。
- Plan 未授權的主要實作方式、核心檔案或 Verification Gate。

觸及任一邊界時停止受影響工作，保存現有證據並產生單一決策卡；不得用新增測試或 Review Fix 將未核准變更合理化。

## Verification 與獨立 Review

最後一個 implementation batch 完成後，在同一 package sequence 自動執行完整 AI Verification，不要求新的 `$cogito`。所有 required checks 通過且 Acceptance closure 完整後，必須取得獨立 Review Agent；實作 Agent 不得審核自己的結果並宣稱獨立。

獨立 Reviewer 只取得核准 Spec／Plan、核准 baseline、實際 diff、Verification evidence 與必要專案指示。它必須檢查：

- 是否符合核准的產品 contract、Scope、Files 與停止條件。
- 是否存在未揭露的行為、契約、資料、安全或跨 Slice 影響。
- 測試是否真正覆蓋 Acceptance，而非只對實作細節自我驗證。
- 高風險程式碼位置、最壞影響、證據缺口與回滾方式。
- 建議 `approve`、`fix` 或 `block`，以及理由。

無法取得獨立 Reviewer 時將 Slice 設為 `blocked`，保存 `Previous state: in-progress`、`Reason: review-pending` 與可觀察的恢復條件；不得退化成實作 Agent 自我 review，也不得進入 `awaiting-human`。

## Review–Fix Loop

Plan 為每個 Slice 設定 1–3 輪的 Review-Fix Budget，並可設定較小的時間或成本上限；全域硬上限是最多 3 輪。每一輪：

1. Reviewer 產出具體 finding 與風險。
2. 只有完全落在 Autonomy Budget 內的 finding 才交回 Implementer 修正。
3. 修正使用獨立 `fix` commit，保留 `Feature-Slice` trailer，不改寫既有 commit。
4. 重跑受影響 batch checks、完整 required checks，再交由獨立 Reviewer 重審。

下列任一情況立即停止，不消耗剩餘輪次來嘗試改變邊界：

- 同一類問題連續兩輪仍出現，或已使用核准輪數。
- 風險升級、修正超出 Autonomy Budget 或需要 Plan／Spec revision。
- Implementer 與 Reviewer 對正確性或風險有實質分歧。
- required evidence 仍不足，或達到核准的時間／成本上限。

停止時產生決策卡，摘要已嘗試方案、剩餘風險、Agent 分歧、建議、替代方案、影響與需要使用者做的單一決定。一般 finding 與已解決的中間輪次只留在 Git history；不逐輪打擾使用者。

## 風險分類與最終報告

下列項目預設為高風險：安全與權限、schema／migration／資料刪除、公開契約、不可逆外部操作、concurrency／transaction／cache consistency、高扇出共享模組、部署／依賴／build pipeline、難以回滾的變更、無法以測試證明的安全性，以及 Agent 風險分級分歧。

Verification 的 Independent Code Review 區段記錄整體 Risk Classification、Review-Fix rounds、所有未解決 finding、Risk Hotspots 的精確檔案與行號、最壞影響、evidence、rollback 與 Recommendation。

- 低風險：使用者可依摘要與獨立 Reviewer 報告核准，不預設要求閱讀完整 diff。
- 高風險：報告必須指出需要使用者親自檢查的程式碼段落；其餘低風險 diff 仍由 Reviewer 負責。
- 任一 required check 未通過、Acceptance 未 closure 或 blocking finding 未解決時，不得推薦 Final Approval。

## Attention 與通知

package sequence 預設安靜：一般 batch 完成、低風險 finding 與已解決修正只更新證據，不要求核准。只有安全／資料／不可逆風險、超出核准邊界、修正未收斂或所有可執行工作均 blocked 時，才以單一決策卡打斷使用者。若 host 沒有背景通知能力，只在目前對話回報，不宣稱已發送通知。

## 相容性

`legacy-staged` 完整保留原有 stage-scoped invocation、單獨 Spec／Plan approval、Implementation、AI Verification 與 Human Acceptance handoff。只有 blueprint 明確採用 `sequential-package` 或 `controlled-parallel` 時，本文件的共用 package 邊界才覆蓋其他 reference 的適用停止點；parallel orchestration 仍只由 controlled parallel reference 定義。
