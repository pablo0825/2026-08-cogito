# Feature Slice Brief Template

建立 `docs/blueprint/slices/<ID>-<name>.md`。保持 Brief 簡短；詳細 Rules、Input／Output 與 Integration Contract 留給 Spec。只引用主 blueprint 的目前狀態。沒有拆分、合併或撤回時省略 Blueprint Revision。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# <ID> — <Feature Name>

## Slice Information

- ID: `<ID>`
- Name: `<English Name>`
- Type: `feature | change | correction`
- Depends On: `<ID or none>`
- Revises: `<ID or none>`
- Corrects: `<ID or none>`
- Feature Slice Status: See `docs/blueprint/feature-slice-blueprint.md`

## Goal

<功能目標>

## User-Visible Result

<使用者可以觀察或完成的結果>

## Source Reference

- `docs/project/<file>`, section `<section>`

## Included

- <本 Slice 包含的需求>

## Excluded

- <本 Slice 明確不包含的需求>

## AI Responsibility

- <AI 負責的實作、測試及文件工作>

## Human Integration

- <人工外部設定，或 `not-applicable`>

## AI Acceptance

- <可由 AI 取得證據的結果>

## Human Acceptance

- <必須由使用者確認的結果>

## Blueprint Revision

- Action: `split | merge | withdraw`
- Derived From: `<IDs or none>`
- Replaced By: `<IDs or none>`
- Merged Into: `<ID or none>`
- Reason: <原因>
- Revised At: `<YYYY-MM-DD>`
