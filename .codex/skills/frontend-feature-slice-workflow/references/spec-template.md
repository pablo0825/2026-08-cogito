# Feature Slice Spec Template

建立 `docs/specs/<ID>/<ID>-<name>-spec.md`。Spec 只定義目前提出或核准的產品行為，不加入 implementation steps、從程式碼推論的需求、revision summary 或 commit record；修訂時直接取代失效內容。`feature` 以本文件為 Authoritative Spec；`change` 填寫 Previous Spec；`correction` 以舊 Spec 為 Authoritative Spec。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# <ID> — <Feature Name> Spec

## Document Information

- Feature Slice: `<ID>`
- Change Type: `feature | change | correction`
- Document Status: `draft`
- Feature Slice Status: See `docs/blueprint/feature-slice-blueprint.md`
- Created: `<YYYY-MM-DD>`
- Last Updated: `<YYYY-MM-DD>`

Document Status 使用 `draft`、`approved`、`completed`、`superseded`。

## Change Information

- Revises Feature Slice: `<ID or none>`
- Corrects Feature Slice: `<ID or none>`
- Previous Spec: `<path or none>`
- Authoritative Spec: `<path or this document>`

## Source Reference

- `docs/project/<file>`, section `<section>`

## User Story

```text
身為 <使用者角色>，
我希望 <完成的操作或目標>，
以便 <獲得的價值或結果>。
```

## Behavior Change

### Current Behavior

- <現有正式行為；新 feature 填寫 `not-applicable`>

### Target Behavior

- <完成後的目標行為>

### Preserved Behavior

- <不得改變的既有行為；不適用時填寫 `not-applicable`>

## Input / Output

### Input

- <輸入、前置資料或觸發條件>

### Output

- <畫面、狀態、資料或行為結果>

## Rules

1. <可驗收的功能規則>
2. <驗證規則>
3. <錯誤或邊界行為>

## Included

- <包含的產品行為>

## Excluded

- <明確不包含的產品行為>

## Preliminary Integration Contract

<必要輸入、預期輸出、錯誤類型與 loading／empty／success／failure 等可觀察狀態；不要指定不必要的檔案、函式或 library>

## AI Acceptance

- [ ] <可透過 build、test、lint、typecheck 或自動化操作驗證的條件>

## Human Acceptance

- [ ] <必須由使用者在實際瀏覽器或裝置確認的結果>

## Open Questions

- <影響需求的未決問題；若沒有填寫 `None`>

## Approval

- Approved By: `pending`
- Approved At: `pending`
- Approval Note: `pending`
