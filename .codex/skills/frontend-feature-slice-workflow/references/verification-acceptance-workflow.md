# Verification and Acceptance Workflow

用於完整 AI Verification、Human Integration 與 Human Acceptance。

## AI Verification

完整讀取 [verification-template.md](verification-template.md)。以核准 Plan 定義完整驗證；batch checks 不取代 sequence 結束後的完整檢查。從 Plan 取得每項 Gate：

- `required`：控制能否進入 `awaiting-human` 的必要 AI 檢查。
- `advisory`：不阻擋前進，但失敗或未執行時必須揭露風險的補充 AI 檢查。
- `human`：記錄於 Human Integration／Acceptance，不列入 AI Verification table。

既有 Plan 沒有 Gate 時，將 `AI Verification Requirements` 視為 `required`、Human Integration／Acceptance 視為 `human`，額外補充檢查視為 `advisory`；專案指示明定的 release gate 仍為 `required`。Gate 在 Plan 核准後固定，不得因檢查結果、期限或 release 壓力自行降級。新增、移除或改變 check、Gate、command／method 時先依 spec-plan workflow 修訂並重新核准 Plan。

依專案指示與 Slice 風險執行 typecheck、lint、unit、integration、build、相關 E2E、accessibility、browser smoke test 或 responsive inspection。使用：

- `passed`：本次實際執行並成功。
- `failed`：本次實際執行並失敗。
- `not-run`：因環境、權限、依賴或工具限制未執行。
- `not-applicable`：此 Slice 不適用。

為每項 AI 檢查記錄 Gate、最新的 command／method、result、evidence 與必要 notes。同一 check 重跑時取代舊結果；已解決的 failure、舊 evidence 與 revision summary 不移到 Batch Exceptions、Implementation Summary 或其他章節。不要引用舊報告作為本次通過證據，也不要將 AI browser test 當成人類驗收。

`not-applicable` 只用於檢查確實不適用，並記錄理由；環境、權限、依賴或工具限制屬於 `not-run`。`required` 只有 `passed` 或有理由的 `not-applicable` 才算通過。

範圍內失敗可修正並重跑；超出核准 Scope 時停止並要求重新核准。完成所有可執行工作後：

1. 建立或更新 Verification；Plan 只保留驗證要求，不複製實際結果。完成 Verification checkpoint 時從 Plan 移除該 row。
2. 任一 `required` 為 `failed` 或 `not-run` 時不得進入 `awaiting-human`：可在核准 Scope 內修正或補跑時維持 `in-progress`；受外部環境、權限或依賴阻礙且 AI 無法解除時設為 `blocked`，記錄阻礙前狀態與恢復條件；Scope 改變時回到 `awaiting-approval`。
3. 所有 `required` 均為 `passed` 或有理由的 `not-applicable` 時，可將 blueprint 設為 `awaiting-human`。`advisory` 的 `failed` 或 `not-run` 不阻擋前進，但必須在 Notes 與 Remaining Issues 記錄原因、風險與 release impact。
4. 建立 Verification Documentation commit；任何結果都必須如實記錄，不得誤標通過。
5. 回報 Commit ID、未解決項目與 Human Integration／Acceptance 步驟，然後停止。

不要將任何 AI check 的 `not-run` 自動改寫成人工步驟；只有 Plan 已核准為 `human` 的項目由人類確認。

## Human Integration

記錄 credentials、secrets、environment variables、OAuth、webhook、真實環境、部署平台、第三方服務或特定權限等人工工作；不需要時使用 `not-applicable`。只有使用者明確確認後才能更新結果。

## Human Acceptance

Human Acceptance 只評估自動化無法可靠判斷的產品結果：

- 真實環境、真實資料或外部服務的使用者旅程。
- 視覺、文案、資訊層級與互動感受。
- 代表性真實裝置上的實際體驗。
- 需要人類語意、信任或整體品質判斷的情境。
- 產品是否符合使用者期待。

從上述類型選擇原則上 3–5 個最高價值場景；只有較少獨立人類判斷時可以少於 3 個，不為達到數量拆分同一旅程。Human Acceptance Instructions 必須使用 verification template 的單一 `High-Value Scenarios` 三欄表；每個場景只描述一個使用者目標與一個人類判斷，不改成逐場景章節、操作步驟、Expected Results 清單或時間規劃。

不要重跑 AI Verification、逐項映射所有 Spec criteria，或展開 browser／viewport／state matrix。自動化 `not-run` 不自動成為 Human Acceptance；只有本質上需要人類判斷或使用者明確要求人工補驗時才加入，且人工結果不改寫 AI Verification status。

只有使用者能回報 `passed`、`failed` 或 `changes-requested`；含糊回覆必須先詢問。

### Passed

進入 `accepted` 前再次確認所有 `required` 仍為 `passed` 或有理由的 `not-applicable`、Human Integration 為 `passed` 或 `not-applicable`，且 Human Acceptance 為使用者確認的 `passed`。任何條件未滿足時維持目前狀態並回報未解決項目。

1. 在 Verification 記錄 Integration 與 Acceptance 證據。
2. 將 Spec／Plan 設為 `completed`，目前 Slice 設為 `accepted`。
3. `change` 將舊 Spec 設為 `superseded` 並加入 replacement link；`correction` 保持 Authoritative Spec 有效。
4. 建立 Final Documentation commit。
5. 回報 Commit ID、AI Verification、Human Acceptance 與未執行檢查，然後停止。

### Failed or changes-requested

- `failed`：如實記錄並建立 Acceptance Feedback commit；範圍內修正可將 Slice 設回 `in-progress`，但只在使用者要求時繼續。
- `changes-requested`：將 Spec／Plan 改為 `draft`、Slice 設為 `awaiting-approval`，同步核准內容並建立 Acceptance Feedback commit。
- 需要改變 Spec、Plan 或 Scope 時重新核准；已提交實作使用新的 `fix` batch，不改寫歷史。

活文件只保存目前有效狀態與證據。Verification 只保留每項檢查的最新結果、目前 Human Integration／Acceptance 與未解決問題；已被後續結果取代的 failure、已解決問題、Commit Batch Verification 與 revision summary 全部由 Git 保存。
