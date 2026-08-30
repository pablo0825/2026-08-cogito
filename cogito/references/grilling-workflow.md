# Requirement Grilling Workflow

用於在建立或實質修訂 Spec 前，以需求拷問（Grilling）釐清工程需求、產品邊界與驗收結果。目標是取得足以建立準確 Spec 的共同理解，不是問完所有可能問題。

## 進入條件

下列情況必須先完成 Grilling：

- 建立新功能的 Spec。
- 實質修改既有功能、產品行為、Scope、Integration Contract 或 Acceptance。
- Bug 的正確行為未由有效 Spec 明確定義，或修復可能改變產品規則、相容性或外部契約。

純文字修正不需要 Grilling。有效 Spec 已明確定義正確行為的 `correction` 只執行 Bug Triage 與最小共同理解確認，不重新詢問已核准需求。

## 事實與決策責任

提問前先讀取適用的需求來源、blueprint、Slice Brief 與有效 Spec。Rolling Adoption 第一次收編時這些 canonical 文件可能不存在；依 [rolling-adoption-workflow.md](rolling-adoption-workflow.md) 只讀取本次能力相關的 Legacy Sources，再調查實際程式、測試與必要的 Git 歷史，建立下列基準：

- 目前核准行為。
- 實際觀察行為。
- 使用者要求的目標行為。
- 必須保留的行為。
- 尚未決定的影響。

Rolling Adoption 必須由使用者確認 Current、Target 與 Preserved Behavior；不要為了補完整產品地圖詢問無關功能。Legacy Source 或 observed behavior 只能成為 `Verified Fact`，不能自行升格為產品決策。

將程式碼與測試只視為現況、限制或差異證據，不用它們發明產品需求。AI 負責查找可取得的事實；只有外部資訊確實無法取得且會影響決策時，才請使用者補充。清楚區分：

- `Verified Fact`：有需求文件、程式、測試、工具結果或使用者提供的外部事實支持。
- `Decision`：必須由使用者決定的產品目標、範圍、取捨或風險接受。
- `Assumption`：尚未驗證；不得改寫成 Fact 或 Decision。

## 工作類型與 Bug Triage

| 類型 | Grilling 重點 |
|---|---|
| `feature` | 使用者、目標、可見結果、Included／Excluded、錯誤行為與 Acceptance |
| `change` | Current／Target／Preserved Behavior、影響範圍、相容性與遷移風險 |
| `correction` | Authoritative Spec、可重現差異與必須恢復的 Acceptance |

收到 Bug 時先分流：

1. 有效 Spec 已唯一決定正確行為：依 `correction` 進行根因調查，只詢問 AI 無法取得的必要重現資訊。
2. 正確行為缺漏或有多個合理答案：執行聚焦的 Grilling，取得產品決策。
3. 修復會改變需求、Acceptance、Integration Contract 或相容性：依 `change` 執行完整 Grilling。

不要因使用者稱問題為 Bug 就推論它是 `correction`，也不要因使用者要求「自行決定」就替使用者決定高影響產品行為。

## 決策樹與 Frontier

以目標使用者結果為根節點建立決策樹。每個決策只在其前置決策已確定時進入 `frontier`；答案依賴本輪尚未解決問題的節點留到後續輪次。

每輪：

1. 從 frontier 選出最高價值的 3–5 題，先只列出題目名稱作為本輪範圍。
2. 每次只展開一題並等待回答，不把多個獨立決策塞入同一題或要求使用者填寫複合欄位。
3. 收到回答後更新決策樹，重新排序或移除剩餘題目，再展開下一題。
4. 本輪 frontier 處理完畢後，才公布下一輪題目。

使用者直接回答、修正、反問或要求解釋目前題目時，不需要重複 `$cogito`；依主 skill 的續接閘門維持同一 Grilling 階段。

問題優先級依序為：阻塞 Spec 的決策、Slice 邊界、使用者可見行為、Acceptance、必須保留的行為、外部整合與重大風險。

## 提問、建議與挑戰

只詢問會實質影響 Scope、行為、Acceptance、保留行為、外部整合、相容性或重大風險的決策。

- 產品目標、偏好與取捨：先讓使用者形成答案，再提出 AI 觀點，避免建議造成錨定。
- 技術限制、有證據的重大風險，或使用者主動要求：可以在問題中直接提出建議與理由。
- 低風險、可逆且不影響產品邊界的細節：標為 `Recommended Default`，不占用逐題問答。

回答若與需求來源、程式或測試證據衝突，指出具體證據並繼續追問，直到矛盾被排除、修正或明確接受為風險。保持直接、尊重；不得為了延長 Grilling 重複詢問。

## 剪枝與控制指令

每次回答後將未決節點分類：

- `ask-now`：會影響目前 Spec 或重大風險，且沒有安全預設。
- `default`：低風險、可逆，可採 AI 建議並在摘要揭露。
- `defer`：目前 Spec 不需要決定，延後不會造成歧義。
- `prune`：已回答、重複、可由 AI 查證、超出 Scope，或其前提已不成立。

支援以下使用者控制：

- 「只問關鍵問題」：只保留阻塞或高影響的 `ask-now`。
- 「其餘採用建議」：將有安全預設的未決節點轉為 `default`。
- 「跳過這題」：轉為 `defer`；若該題阻塞 Spec，揭露阻塞而不假裝完成。
- 「先到這裡」：立即評估停止條件；只繼續詢問真正的阻塞問題。

使用者回答「不知道」時，若是事實則由 AI 查證；若是產品決策則說明選項與取捨；若是無安全預設的必要邊界，將 Readiness 標為 `blocked`。

## 停止條件

每次回答或取得查證結果後，更新決策樹與待查事實，再判斷是否仍有可有效釐清的必要事項。`Readiness: blocked` 不代表立即停止問答或產出共同理解摘要：

- 遇到單一阻塞時，其他不依賴該阻塞、目前仍可回答的必要產品決策，繼續依 frontier 逐題釐清，不因部分受阻而一併停止。
- 依賴阻塞答案的必要問題保留為未決，記錄依賴關係；不提前要求使用者猜測，也不以 `defer` 或 `prune` 假裝它們不再必要。
- AI 仍能取得證據的必要事實，由 AI 在目前 Grilling 階段繼續查證；不轉成使用者必須回答的問題，也不因暫無產品問題可問就提前產出摘要。查證若揭露新的必要產品決策，回到同一階段的 frontier。
- 必要事實的可取得來源已查完，且使用者也無法提供缺少的資訊時，保留阻塞，不反覆追問同一事實；改為處理其他可獨立釐清的必要事項。

只有以下兩種情況停止問答與目前可進行的查證，產出共同理解摘要：

1. **`ready` 摘要**：目前 Spec 所需的必要產品決策與關鍵事實都已釐清。問題、使用者、預期結果、Included／Excluded、可驗收的完成條件、必須保留的行為，以及適用限制、整合與重大風險均已明確，符合共同理解 contract 的 Readiness 判準。
2. **`blocked` 摘要**：仍有必要產品決策或關鍵事實未釐清，但目前已沒有可繼續有效釐清的必要事項；其他可獨立回答的必要問題與可取得的必要查證均已處理。摘要保存已取得的共同理解，列出剩餘阻塞原因、受影響的未決事項與恢復條件，不要求所有必要產品決策先有答案才允許產出受阻摘要。

不要在符合上述停止條件後，為了延長 Grilling 或消除暫時無法解除的阻塞繼續尋找問題。

## 共同理解摘要

符合上述任一摘要產出條件時，完整讀取 [shared-understanding-contract.md](shared-understanding-contract.md)，依其 Readiness 判準、摘要格式、確認方式與效力限制，在對話中產出目前有效的摘要並等待使用者明確確認。`blocked` 摘要在 `Blocking Questions` 列出阻塞原因、依賴該阻塞的必要未決事項、缺少的證據或決策，以及恢復釐清所需的條件；即使使用者確認摘要，也不自動變成 `ready`。

## 摘要確認後的流程

- `confirmed + ready`：確認摘要後停止；Boundary Gate 是新階段，要求使用者以新的 `$cogito` 訊息啟動，再完整讀取 [spec-plan-workflow.md](spec-plan-workflow.md) 並執行 Gate。Gate 是產品需求文件 Proposal、Blueprint、Spec 與 Plan 前的下一個步驟。
- `confirmed + blocked`：共同理解可以正確，但不得建立或修訂 Spec。

Boundary Gate 通過前不得提出或套用產品需求文件修改，也不得建立或修訂 Blueprint、Spec 或 Plan。Gate 未通過時先提出垂直拆分 Proposal。若後續核准的文件內容超出已確認摘要，原 Gate 結果失效；要求使用者以新的 `$cogito` 訊息重新進入 Grilling，確認後停止，再以另一個新的 `$cogito` 訊息重跑 Boundary Gate。
