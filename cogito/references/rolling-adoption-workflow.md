# Rolling Adoption Workflow

用於已上線但缺少完整 `docs/project/`、blueprint 或 Cogito lineage 的專案。只在某項使用者結果第一次需要修改時收編相關規則；不要為了開始工作先掃描、拆分或補造整個既有產品。

## 進入條件

下列條件成立時使用 Rolling Adoption：

- 系統已有可觀察的已上線行為。
- 目標是產品行為變更，而不是不改行為的 Maintenance。
- `docs/project/`、blueprint 或目標能力的 accepted Slice／Spec 不存在或覆蓋不完整。

若只是新專案缺少需求來源，停止並詢問位置。若目標行為已有 accepted Slice／Spec，改走一般 `change` 或 `correction`。Rolling Adoption 不是略過 Grilling、Boundary Gate、文件授權或 Human Acceptance 的捷徑。

## 局部 Legacy Baseline

只調查本次使用者結果需要的範圍：相關舊文件、實際程式、測試與必要 Git history。不要盤點無關功能，也不要把整份舊文件直接搬入 `docs/project/`。

將證據分類為：

- Legacy Source：`docs/project/` 之外的既有文件，只是待確認材料。
- Observed Behavior：程式、測試或可重現結果證明的現況。
- User Decision：使用者確認的 Current、Target 與 Preserved Behavior。

Legacy Source、Observed Behavior 互相衝突，或無法唯一決定應保留的行為時，提出一個聚焦問題。不得自行選擇較方便的版本，也不得將現況改寫成需求。

## 決策與邊界

1. 完整執行 [grilling-workflow.md](grilling-workflow.md)，只詢問本次 change 的必要產品決策。
2. 使用者確認共同理解且 Readiness 為 `ready` 後，依 [spec-plan-workflow.md](spec-plan-workflow.md) 執行 Boundary Gate。第一次收編尚無 Slice Brief／canonical Source Reference 時，以 confirmed summary、Legacy Sources 與目標使用者結果判斷。
3. Gate 未通過時只提出垂直拆分 Proposal；不建立 `docs/project/`、blueprint、Spec 或 Plan。
4. Gate 通過後提出 Rolling Adoption Proposal，等待明確核准。

## Rolling Adoption Proposal

```text
Rolling Adoption Proposal

Capability:
- <本次收編的使用者結果或規則範圍>

Legacy Baseline:
- Legacy Sources: <legacy documents and sections>
- Observed Evidence: <code, tests, reproducible behavior, or Git history>
- Current Behavior: <confirmed baseline>
- Confirmed By: <user>

Canonicalization:
- Target: docs/project/<file>#<section>
- Effective Content: <current target and preserved rules>

Legacy Retirement:
- <old section -> canonical link | delete | unchanged because not adopted>

Blueprint:
- Adoption Mode: rolling
- Coverage: partial
- Slice: <ID, name, type, lineage, initial status>

Documentation Batch:
- Files: <exact files>
- Message: docs(<ID>): adopt <capability> requirements
```

第一次修改已上線行為使用 `Type: change`、`Revises: none` 與 `Legacy Baseline`；不要改成 `feature`、補造 accepted Slice 或建立虛構 Previous Spec。若是全新使用者結果，使用 `feature`，Legacy Baseline 只記錄必要的既有相鄰限制，不代替 feature semantics。沒有 Cogito Authoritative Spec 的舊問題不能使用 `correction`。

核准 Proposal 只授權列出的 Documentation Batch，不授權建立 Spec 或實作。

## 文件收編與退役

在同一 Adoption Documentation commit：

1. 將使用者已確認且目前有效的規則寫入 `docs/project/`；不搬入討論歷史、舊方案或未確認推論。
2. 舊文件仍有未收編內容時保留該內容，並將已收編章節替換為 canonical link；不得為「保險」保留重複全文。
3. 舊文件只剩已收編或失效內容時，更新所有可控 reference 後刪除；若穩定外部連結確實需要舊路徑，只保留最小 redirect。
4. 產品行為進 `docs/project/`；API／架構／部署說明留在適當技術文件；失效內容刪除，歷史由 Git 保存。
5. 不修改 Proposal 未列出的未收編章節。

## Blueprint 與停止點

blueprint 不存在時，以 [blueprint-template.md](blueprint-template.md) 建立 `Adoption Mode: rolling`、`Coverage: partial` 的最小入口；存在時只新增本次能力。Feature Slice Index 不是完整產品清單，未列出不代表功能不存在。

建立本次 `proposed` Slice 與 Brief；Brief 的 Legacy Baseline 記錄 sources 與使用者確認，不重建歷史 Spec／Plan／Verification。依 [commit-workflow.md](commit-workflow.md) 建立 Adoption Documentation commit，回報後提供建立 Spec／Plan 的精確 `$cogito` 指令並停止。只有使用者以包含 `$cogito` 的後續訊息明確要求時，才進入一般 workflow。

本次 Slice accepted 後，相同行為的後續 change 使用正常 `Revises`，不再使用新的 Legacy Baseline。blueprint Coverage 只有在所有產品能力確實完成收編並經使用者確認後才能改為 `complete`。
