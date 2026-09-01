# Shared Understanding Contract

定義 Grilling 的共同理解摘要格式、Readiness 判準、確認方式與確認效力；何時停止問答、產出摘要及確認後的階段流程由 [grilling-workflow.md](grilling-workflow.md) 管理。

## Readiness 判準

本文件是 Readiness 判準的唯一來源，用來判斷目前需求是否足以建立準確 Spec；其他 workflow 只使用判定結果，不另行定義 `ready`／`blocked`。Shared Understanding 是否經使用者確認應分開判定。

- `ready`：目前 Spec 所需的產品決策與關鍵事實已釐清，沒有阻塞需求成立或驗收的未決事項。
- `blocked`：仍有必要產品決策未定，或支撐目前需求的關鍵事實尚未確認。摘要可以被確認為正確，但確認本身不解除阻塞。

判定時檢查目前 Spec 所需的下列資訊：

- 問題、使用者與預期結果。
- Included／Excluded。
- 可驗收的完成條件。
- 必須保留的既有行為。
- 適用的限制、整合與重大風險。

關鍵事實是查證結果可能迫使目前 Spec 的 Scope、使用者可見行為、Acceptance、必要相容性或可行性改變的事實。這些事實必須有證據支持；尚未驗證的關鍵假設，即使使用者表示願意承擔風險，也不能據此標為 `ready`，或以 `default`、`defer`、`prune` 的分類解除阻塞。

已查明的風險，若產品應對行為與驗收條件明確，且經使用者明確接受，不阻擋 `ready`。風險接受不等於將未知的關鍵能力視為已驗證，也不保證外部系統每次都成功。

不影響目前 Spec 的內部實作安排，可留到 Plan 或實作階段；不阻塞目前 Spec 的其他未知事項可揭露並延後，不要求所有工程細節都已決定。

## 摘要格式

共同理解摘要最上方使用 Markdown 一級標題。已有明確 Slice ID 時使用 `# FS-NNN Shared Understanding`，以目前 Slice ID 取代 `FS-NNN`；尚未建立 Slice 或沒有可確認的 Slice ID 時使用 `# Shared Understanding`。不得猜測、預留或為摘要建立 Slice ID。

摘要保留七個欄位，標題使用 Markdown 二級標題加粗體（`## **標題**`），與正文之間留一個空行。實際摘要正常渲染，不將整份摘要包在程式碼區塊內；下列區塊只示範已有 Slice ID 時的 Markdown 結構：

```markdown
# FS-NNN Shared Understanding

## **Confirmed Decisions**

〈本欄內容〉

## **Verified Facts**

〈本欄內容〉

## **Recommended Defaults**

〈本欄內容〉

## **Deferred Decisions**

〈本欄內容〉

## **Explicitly Excluded**

〈本欄內容〉

## **Remaining Risks**

〈本欄內容〉

## **Blocking Questions**

〈本欄內容〉

Shared Understanding: awaiting-confirmation | confirmed
Readiness: ready | blocked
```

- **呈現方式**：單一簡短結論使用短句；多個獨立且沒有共同比較欄位的事項使用列點；多個事項具有相同屬性，且表格能讓對應或比較更清楚時，可使用 Markdown 表格，例如「情況／回應」或「阻塞事項／影響／解除條件」。同一欄位可混用格式，不要求每份摘要都有表格。
- **分類與證據**：七個欄位各自保留，不因表格而合併或改變分類。理由、限制或證據跟隨對應事項；表格無法容納時，在表外明確指出對應事項。不得拆成無關項目或為填滿表格補出未確認內容。
- **空值與狀態**：沒有內容的欄位保留標題並寫「無」，尚未釐清不能冒充「無」。狀態行沿用上述名稱和值，只輸出當下有效狀態。

七個欄位的用途與內容邊界如下：

- `Confirmed Decisions`：使用者已明確確認的產品目標、範圍、行為、取捨或風險接受決策。只記錄有效的使用者決策，不將 AI 建議、未驗證假設或觀察到的現況改寫為使用者決策。
- `Verified Facts`：已確認的事實及其證據來源；未驗證假設不得列為事實。程式或測試呈現的現況，不自動成為產品應有的行為。
- `Recommended Defaults`：AI 提出的低風險、可逆且不影響產品邊界的預設，附理由並保留 AI 建議來源。摘要確認不會使其成為 `Confirmed Decisions`；使用者明確選定後才移入，且不在兩欄重複。此分類不改變摘要確認效力，也不能取代必要產品決策或關鍵事實查證。
- `Deferred Decisions`：不阻塞目前 Spec 的延後事項，說明為何不影響目前需求與驗收；待查事實仍標明未驗證。
- `Explicitly Excluded`：使用者或適用需求文件明確界定為本次不包含的範圍，附排除依據；未提及不等於排除。必要的範圍歧義先依 Grilling 流程釐清，不得在摘要中自行補列，也不為填滿此欄而詢問所有可想像的功能。
- `Remaining Risks`：已查明風險、產品應對行為、驗收條件與使用者接受情況。
- `Blocking Questions`：必要未決事項、對 Spec 的影響與解除條件，並標明由 AI 查證或使用者決策。AI 查證受阻時列出缺少的證據或存取條件，不要求使用者猜測事實。

## 確認效力與保存

摘要確認只建立內容基線，不構成任何後續工作的授權。確認後的摘要持續有效，直到使用者明確修改或撤回。

完整問答留在對話中；Canonical 文件只在取得適用授權後保存目前有效的結論，不建立 Requirement Interview history 文件。

## 確認流程與固定提示

等待使用者明確確認摘要；摘要確認仍屬於同一 Grilling 階段，不需要重複 `$cogito`。

`Shared Understanding: awaiting-confirmation` 的摘要在狀態行後輸出以下固定結尾，不得省略、改寫或擴張。確認提示與引導句使用一般段落，不加引號、列點或引用格式；`同意` 使用標示為 `text` 的程式碼區塊：

請確認這份 Shared Understanding 是否正確。確認只表示摘要內容正確，不授權進入後續階段、修改文件、建立 Slice、實作或 commit。

若摘要正確，可直接回覆：

```text
同意
```

程式碼區塊只提供方便複製的回覆，不代表 AI 自行確認摘要。使用者指出修正內容時，直接取代失效結論，不累積 revision history；修正不等於同意，狀態維持 `awaiting-confirmation`。`Shared Understanding: confirmed` 的摘要不再次輸出確認提示、引導句或程式碼區塊。
