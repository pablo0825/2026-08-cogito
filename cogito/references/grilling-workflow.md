# Requirement Grilling Workflow

在建立或實質修訂 Spec 前，釐清工程需求、產品邊界與驗收結果，取得足以建立準確 Spec 的共同理解；不問完所有可能問題。

## 進入條件與釐清範圍

下列情況在建立或實質修訂 Spec 前須完成對應釐清；純文字修正不需要 Grilling，不因使用者稱問題為 Bug 就判為 `correction`。

| 情況 | 釐清方式 |
|---|---|
| 建立新功能 Spec（`feature`） | 釐清使用者、目標、可見結果、Included／Excluded、錯誤行為與 Acceptance |
| 實質修改功能、產品行為、Scope、Integration Contract 或 Acceptance（`change`） | 釐清 Current／Target／Preserved Behavior、影響範圍、相容性與遷移風險 |
| Bug 的正確行為由有效 Spec 唯一決定 | 依 `correction` 調查根因並做最小共同理解確認，核對 Authoritative Spec、可重現差異與須恢復的 Acceptance；只問 AI 無法取得的必要重現資訊，不重問已核准需求 |
| Bug 的正確行為缺漏或有多個合理答案 | 進行聚焦的 Grilling，取得產品決策 |
| Bug 修復會改變需求、Acceptance、Integration Contract 或相容性 | 依 `change` 進行完整 Grilling |

## 調查與責任

提問前讀取適用需求來源、blueprint、Slice Brief 與有效 Spec，再調查實際程式、測試與必要 Git 歷史。區分目前核准、實際觀察、使用者目標、必須保留的行為，以及尚未決定的影響。

Rolling Adoption 初次收編可能缺少 canonical 文件，依 [rolling-adoption-workflow.md](rolling-adoption-workflow.md) 只讀本次能力相關的 Legacy Sources；Current、Target 與 Preserved Behavior 須由使用者確認，不盤問無關功能。

- `Verified Fact`：由需求文件、程式、測試、工具結果或使用者提供的外部事實支持。Legacy Source、程式與測試只提供現況、限制或差異證據，不自行升格為產品需求或決策。
- `Decision`：由使用者決定產品目標、範圍、取捨與風險接受；要求「自行決定」不授權 AI 決定高影響產品行為。
- `Assumption`：尚未驗證，不得改寫為 Fact 或 Decision。

AI 查找可取得的事實；只有外部資訊確實無法取得且影響決策時，才請使用者補充。必要查證移出提問清單後仍列為待查事項，保留對決策的影響，不以 `prune` 視為已解決。

## Readiness 的使用

首次判定前完整讀取 [shared-understanding-contract.md](shared-understanding-contract.md)（以下稱 contract），只依其判準決定狀態。同一未中斷階段沿用；依主 skill 明確恢復階段後重讀。無法讀取時揭露原因，不自行補出判準或狀態。

完成初步調查後首次評估；影響判定的回答、決策或證據更新後重新評估，再決定下一步。僅要求解釋且無新增資訊時不必重評，也不必每次宣告狀態。

## 決策樹與 Frontier

以目標使用者結果為根建立決策樹；前置決策確定後才進入 `frontier`，依賴本輪未決答案的問題留到後續輪次。
優先序：阻塞 Spec 的決策、Slice 邊界、使用者可見行為、Acceptance、保留行為、外部整合與重大風險。

1. 每輪選取最高價值的必要問題，最多五題、不設下限、不湊題數，先只列題目名稱。
2. 每次展開一題並等待回答，不合併獨立決策或要求填寫複合欄位。
3. 回答後更新決策樹，重排或移除剩餘題目，再問下一題；本輪 frontier 處理完才公布下一輪。

使用者直接回答、修正、反問或要求解釋目前題目時，不需要重複 `$cogito`；依主 skill 的續接閘門維持同一階段。

## 提問與建議

只問實質影響 Scope、行為、Acceptance、保留行為、外部整合、相容性或重大風險的決策。

- 產品目標、偏好與取捨：先讓使用者作答，再提出 AI 觀點，避免錨定。
- 技術限制、有證據的重大風險或使用者主動要求：可直接提出建議與理由。
- 低風險、可逆且不影響產品邊界的細節：標為 `Recommended Default`，不占用逐題問答。

回答與需求來源、程式或測試證據衝突時，指出證據並追問，直到矛盾排除、修正或明確接受為風險；保持直接、尊重，不為延長 Grilling 重複提問。

回答「不知道」時，事實由 AI 查證，產品決策則說明選項與取捨；未解決事項保留未決，依 Readiness 與停止流程繼續處理。

## 剪枝與控制指令

每次回答後分類未決節點：

- `ask-now`：影響目前 Spec 或重大風險，且無安全預設。
- `default`：低風險、可逆，可採 AI 建議並在摘要揭露。
- `defer`：目前 Spec 不必決定，延後不造成歧義。
- `prune`：已回答、重複、超出 Scope 或前提不成立。

- 「只問關鍵問題」：只保留阻塞或高影響的 `ask-now`。
- 「其餘採用建議」：將有安全預設的未決節點轉為 `default`。
- 「先到這裡」：立即評估停止條件，只繼續詢問真正的阻塞問題。

「跳過這題」仍保留必要決策未決，不自動轉為 `defer`、`prune` 或接受預設；依下表安排回訪，不立即重問或為湊跳過次數而追問。

| 跳過情況 | 下一步 |
|---|---|
| 首次跳過（下列收尾情況除外） | 暫移出本輪提問，先完成其他可獨立回答的必要問題，再回訪；必要查證依停止流程處理 |
| 首次跳過當下，已無其他可有效進行的必要問答或查證 | 該題暫不追問，依停止條件產出 `blocked` 摘要，不等第二次跳過 |
| 回訪後再次跳過 | 該題暫不主動追問，保留阻塞；其他必要事項與摘要依停止條件處理 |

## 停止與摘要

依 contract 評估 Readiness；`blocked` 時先更新決策樹與待查事實，不因單一阻塞立即收尾：

- 繼續逐題釐清不依賴阻塞、目前可回答的必要決策；依賴阻塞的問題保留未決與依賴關係，不要求猜測，也不以 `defer`／`prune` 消除必要性。
- 可取得證據的必要事實繼續由 AI 查證，不轉交使用者或因暫無問題可問而收尾；查出新產品決策時回到同階段 frontier。
- 可取得來源已查完且使用者也無法補充時，保留阻塞，不重問同一事實；改處理其他獨立必要事項。被跳過問題的回訪與暫停追問依上表。

只有以下情況停止問答與目前可進行的查證；符合後不再為延長 Grilling 或解除暫時無法解除的阻塞尋找問題：

1. contract 判定 `ready`：產出 `ready` 摘要。
2. contract 判定 `blocked`，且已無可有效釐清的必要事項：產出 `blocked` 摘要；其他可獨立回答的必要問題及可取得的必要查證須先處理。

依 contract 的格式、確認方式與效力限制產出摘要，等待使用者明確確認。`blocked` 摘要在 `Blocking Questions` 保存阻塞原因、受影響及依賴阻塞的未決事項、缺少的證據或決策、對需求或驗收的影響與恢復條件。

## 摘要確認後

- `confirmed + ready`：確認後停止；Boundary Gate 是下一個新階段，要求使用者以新的 `$cogito` 訊息啟動，再完整讀取 [spec-plan-workflow.md](spec-plan-workflow.md) 執行。
- `confirmed + blocked`：摘要可以正確，但不得建立或修訂 Spec。

摘要確認不授權修改文件、實作或 commit。Boundary Gate 通過前不得提出或套用產品需求文件修改，也不得建立或修訂 Blueprint、Spec 或 Plan；Gate 未通過時先提出垂直拆分 Proposal。

若後續核准文件超出已確認摘要，原 Gate 結果失效；以新的 `$cogito` 訊息重新進入 Grilling，確認後停止，再以另一個新的 `$cogito` 訊息重跑 Boundary Gate。
