# Verification and Acceptance Workflow

用於完整 AI Verification、Human Integration 與 Human Acceptance。

## AI Verification

完整讀取 [verification-template.md](verification-template.md)。以核准 Plan 定義完整驗證；batch checks 不取代 sequence 結束後的完整檢查。從 Plan 取得每個 `V-*` Check ID、mapped Acceptance IDs、Gate、Applicability 與 command／method：

- `required`：控制能否進入 `awaiting-human` 的必要 AI 檢查。
- `advisory`：不阻擋前進，但失敗或未執行時必須揭露風險的補充 AI 檢查。
- `human`：記錄於 Human Integration／Acceptance，不列入 AI Verification table。

既有 Plan 沒有 Gate 時，將 `AI Verification Requirements` 視為 `required`、Human Integration／Acceptance 視為 `human`，額外補充檢查視為 `advisory`；缺少 Applicability 時視為 `always`。專案指示明定的 release gate 仍為 `required`。Check、mapping、Gate、Applicability 與 command／method 在 Plan 核准後固定；任何新增、移除或改變都先提出 revision proposal，取得授權後才依 spec-plan workflow 修訂並重新核准 Plan。

依專案指示與 Slice 風險執行 typecheck、lint、unit、integration、build、相關 E2E、accessibility、browser smoke test 或 responsive inspection。使用：

- `passed`：本次實際執行並成功。
- `failed`：本次實際執行並失敗。
- `not-run`：因環境、權限、依賴或工具限制未執行。
- `not-applicable`：Plan 核准的 Applicability predicate 有客觀證據顯示為 false。

為每個 `V-*` 記錄 mapped Acceptance IDs、Gate、Applicability evaluation、最新 command／method、result、evidence 與必要 notes。同一 Check ID 重跑時取代舊結果；已解決的 failure、舊 evidence 與 revision summary 不移到其他章節。不要引用舊報告作為本次通過證據，也不要將 AI browser test 當成人類驗收。

`not-applicable` 只在 Plan 核准的 objective predicate 為 false 時使用，並記錄 exact predicate 與客觀證據。Predicate 部分成立、改變中、由 Agent 的實作選擇控制，或未在 Plan 中定義時，不得自行判定；停止並提出 revision proposal，取得授權後才修訂並重新核准 Plan。環境、權限、依賴、期限或工具限制屬於 `not-run`。在 Final Acceptance 前重新評估可能改變的 predicate。

Check 結果與 Acceptance closure 分開：每個 `AI-*` 只有在所有必要 mapped evidence 充分時標為 `satisfied`。一個 check 可支持多個 criteria，一個 criterion 可需要多個 checks；所有 mapped checks 為 `not-applicable` 不會讓無條件 criterion 自動完成。只有 advisory evidence 不足以完成原本需要 required coverage 的 Acceptance。

失敗後可以在現有授權下重跑 commands 與更新 evidence；任何程式碼修改都必須先提出 Plan revision proposal。只有使用者明確授權該 revision 後才能在 Plan 新增 fix batch，之後重新核准，並由使用者以新的 `$cogito` 訊息開始。產品語義 delta 回到 Grilling 與 Boundary Gate。完成所有可執行工作後：

1. 建立或更新 Verification；Plan 只保留驗證要求，不複製實際結果。只有所有 required checks 與所有 `AI-*` closure 完成時，才從 Plan 移除 Verification row。
2. 任一 `required` 為 `failed` 或 `not-run` 時不得進入 `awaiting-human`：現有授權只允許補跑與更新 evidence；需要程式修正時回到 `awaiting-approval` 並提出 fix batch revision proposal，不在取得 revision 授權前修改 Plan；受外部環境、權限或依賴阻礙且 AI 無法解除時設為 `blocked`，記錄阻礙前狀態與恢復條件。
3. 所有 `required` 均為 `passed` 或符合 approved-predicate 規則的 `not-applicable`，且所有 `AI-*` 均為 `satisfied` 時，可將 blueprint 設為 `awaiting-human`。`advisory` 的 `failed` 或 `not-run` 不阻擋前進，但必須在 Notes 與 Remaining Issues 記錄原因、風險與 release impact。
4. 建立 Verification Documentation commit；阻礙性結果可以保存目前證據與 blocked state，但不消耗 Verification checkpoint。任何結果都必須如實記錄。
5. 回報 Commit ID、未解決項目與 Human Integration／Acceptance 步驟，然後以明確 `$cogito` 續接句停止。

不要將任何 AI check 的 `not-run` 自動改寫成人工步驟；只有 Plan 已核准為 `human` 的項目由人類確認。

## Human Integration

依 Plan 的 `HI-*` 記錄 credentials、secrets、environment variables、OAuth、webhook、真實環境、部署平台、第三方服務或特定權限等人工工作。`not-applicable` 只在 Plan 核准的 HI applicability predicate 為 false 時使用。只有使用者明確確認後才能更新結果。

## Human Acceptance

Human Acceptance 只評估自動化無法可靠判斷的產品結果：

- 真實環境、真實資料或外部服務的使用者旅程。
- 視覺、文案、資訊層級與互動感受。
- 代表性真實裝置上的實際體驗。
- 需要人類語意、信任或整體品質判斷的情境。
- 產品是否符合使用者期待。

從上述類型選擇原則上 3–5 個最高價值場景；只有較少獨立人類判斷時可以少於 3 個，不為達到數量拆分同一旅程。Human Acceptance Instructions 使用 verification template 的單一 `High-Value Scenarios` 四欄表；每個場景列出涵蓋的 `HA-*`，只描述一個使用者目標與一個人類判斷。一個場景可涵蓋多個 `HA-*`，但每個 `HA-*` 都必須被至少一個場景涵蓋。

不要求人類重跑 `AI-*`、技術 checks 或 browser／viewport／state matrix。自動化 `not-run` 不成為 Human Acceptance；只有 Spec 定義的 `HA-*` 由人類確認，且人工結果不改寫 AI Verification status。

只有使用者能回報 `passed`、`failed` 或 `changes-requested`；含糊回覆必須先詢問。等待時提示：`請以 $cogito 回報 <ID> Human Acceptance 結果`。

### Passed

進入 `accepted` 前重新評估 Applicability，確認所有 `required` 仍為 `passed` 或符合 approved-predicate 規則的 `not-applicable`、所有 `AI-*` 均為 `satisfied`、每個 `HI-*` 為 `passed` 或合法 `not-applicable`，且所有 `HA-*` 為使用者確認的 `passed`。任何條件未滿足時維持目前狀態並回報未解決項目。

1. 在 Verification 依 `HI-*` 與 `HA-*` 記錄 Integration 與 Acceptance 證據。
2. 將 Spec／Plan 設為 `completed`，目前 Slice 設為 `accepted`。
3. `change` 以新 Slice、blueprint 與新 Spec 的 lineage 表示取代關係；`correction` 保持 Authoritative Spec 有效。不要修改舊 accepted Spec 或在其中加入 replacement metadata。
4. 建立 Final Documentation commit。
5. 回報 Commit ID、AI Verification、Human Acceptance 與未執行檢查，然後停止。

### Failed or changes-requested

- `failed`：如實記錄並建立 Acceptance Feedback commit。需要程式修正時將 Slice 設為 `awaiting-approval`，提出 fix batch revision proposal；取得 revision 授權後才修改 Plan，重新核准且使用者以 `$cogito` 明確開始後才進入 `in-progress`。
- `changes-requested`：先保存實際 feedback。若改變產品行為、Scope、Acceptance 或 Integration Contract，停止並提示下一輪以 `$cogito` 回到 Grilling 與 Boundary Gate；不直接修改 Spec。
- 只有技術 Plan 修正時依 spec-plan workflow 重新核准 Plan；已提交實作使用新的 `fix` batch，不改寫歷史。

活文件只保存目前有效狀態與證據。Verification 只保留每項檢查的最新結果、目前 Human Integration／Acceptance 與未解決問題；已被後續結果取代的 failure、已解決問題、Commit Batch Verification 與 revision summary 全部由 Git 保存。
