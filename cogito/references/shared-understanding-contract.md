# Shared Understanding Contract

定義 Grilling 的共同理解摘要格式、Readiness 判準、確認方式與確認效力；何時停止問答、產出摘要及確認後的階段流程由 [grilling-workflow.md](grilling-workflow.md) 管理。

## Readiness 判準

Readiness 判斷目前需求是否足以建立準確 Spec；Shared Understanding 只記錄使用者是否確認摘要正確，兩者分開判定。

- `ready`：目前 Spec 所需的產品決策與關鍵事實已釐清，沒有阻塞需求成立或驗收的未決事項。
- `blocked`：仍有必要產品決策未定，或支撐目前需求的關鍵事實尚未確認。摘要可以被確認為正確，但確認本身不解除阻塞。

關鍵事實是查證結果可能迫使目前 Spec 的 Scope、使用者可見行為、Acceptance、必要相容性或可行性改變的事實。這些事實必須有證據支持；尚未驗證的關鍵假設，即使使用者表示願意承擔風險，也不能據此標為 `ready`，或以 `default`、`defer`、`prune` 的分類解除阻塞。

已查明的風險，若產品應對行為與驗收條件明確，且經使用者明確接受，不阻擋 `ready`。風險接受不等於將未知的關鍵能力視為已驗證，也不保證外部系統每次都成功。

不影響目前 Spec 的內部實作安排，可留到 Plan 或實作階段；不阻塞目前 Spec 的其他未知事項可揭露並延後，不要求所有工程細節都已決定。

## 摘要格式與確認

共同理解摘要保留七個欄位，標題使用 Markdown 粗體，與正文之間留一個空行。實際摘要正常渲染，不將整份摘要包在程式碼區塊內；下列區塊只示範 Markdown 結構：

```markdown
**Confirmed Decisions**

〈本欄內容〉

**Verified Facts**

〈本欄內容〉

**Recommended Defaults**

〈本欄內容〉

**Deferred Decisions**

〈本欄內容〉

**Explicitly Excluded**

〈本欄內容〉

**Remaining Risks**

〈本欄內容〉

**Blocking Questions**

〈本欄內容〉

Shared Understanding: awaiting-confirmation | confirmed
Readiness: ready | blocked
```

每個欄位只有一項簡短內容時可用短句；有多個彼此獨立的事項時使用列點。同一事項的理由、限制或證據跟隨該事項，不另拆成獨立列點。沒有內容的欄位仍保留標題並寫「無」；尚未釐清不能冒充「無」。狀態行沿用上述名稱和值，只輸出當下有效的狀態。

七個欄位的用途與內容邊界如下，不另外建立文件：

- `Confirmed Decisions`：使用者已明確確認的產品目標、範圍、行為、取捨或風險接受決策。只記錄有效的使用者決策，不將 AI 建議、未驗證假設或觀察到的現況改寫為使用者決策。
- `Verified Facts`：已確認的事實及其證據來源；未驗證假設不得列為事實。程式或測試呈現的現況，不自動成為產品應有的行為。
- `Recommended Defaults`：AI 提出的低風險、可逆且不影響產品邊界的預設及其理由，明確保留 AI 建議的來源。整份摘要被確認，不會自動將這些預設移入 `Confirmed Decisions`；只有使用者明確選定該項預設時，才將該項移入 `Confirmed Decisions`，不在兩欄重複列為目前結論。這是來源分類，不改變摘要確認的既有效力，也不以預設取代必要產品決策或關鍵事實查證。
- `Deferred Decisions`：不阻塞目前 Spec 的延後事項，說明為何不影響目前需求與驗收；待查事實仍標明未驗證。
- `Explicitly Excluded`：使用者或適用需求文件已明確界定為本次不包含的範圍，附上排除依據；未提及不等於排除。必要的範圍歧義依 Grilling 流程先行釐清，不在產出摘要時自行補出排除結論，也不為列滿此欄而詢問所有可想像的功能。
- `Remaining Risks`：已查明風險、產品應對行為、驗收條件與使用者接受情況。
- `Blocking Questions`：必要未決事項、對 Spec 的影響與解除阻塞的條件；註明是由 AI 查證或由使用者決策。AI 查證受阻時列出缺少的證據或存取條件，不把事實調查改成要求使用者猜答案。

等待使用者明確確認摘要。摘要確認屬於同一 Grilling 階段，不需要重複 `$cogito`；修正摘要時直接取代失效結論，不累積 revision history。

## 確認效力與保存

摘要確認只表示內容正確，不授權修改 `docs/project/`、Blueprint、Spec 或 Plan，不核准實作，也不授權 commit。

完整問答留在對話中。Canonical 文件只在取得適用授權後保存目前有效的結論，不建立 Requirement Interview history 文件。
