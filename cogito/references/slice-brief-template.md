# Feature Slice Brief Template

建立 `docs/blueprint/slices/<ID>-<name>.md`。Brief 只保存 Slice 的使用者結果、高階邊界、來源與 lineage；詳細行為與 Acceptance 留給 Spec，實作與驗證責任留給 Plan。只引用主 blueprint 的目前狀態。沒有拆分、合併或撤回時省略 Blueprint Revision。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# <ID> — <Feature Name>

## Slice Information

- ID: `<ID>`
- Name: `<English Name>`
- Type: `feature | change | correction`
- Depends On: `<ID or none>`
- Revises: `<ID or none>`
- Corrects: `<ID or none>`
- Feature Slice Status: See `docs/blueprint/feature-slice-blueprint.md`

## User-Visible Result

<用一句話描述使用者可以觀察、獨立驗收且本身有價值的完成結果>

## Source Reference

- `docs/project/<file>`, section `<section>`

## Legacy Baseline

只在第一次收編既有行為的 `change` 使用；其他 Slice 省略本節。此時 `Revises` 必須為 `none`。

- Legacy Sources: `<legacy document sections or none>`
- Observed Evidence: `<code, tests, reproducible behavior, Git history, or none>`
- Confirmed Current Behavior: `<concise baseline>`
- Confirmed By: `<user>`
- Confirmed At: `<YYYY-MM-DD>`

## Included

- <本 Slice 包含的需求>

## Excluded

- <本 Slice 明確不包含的需求>

## Blueprint Revision

- Action: `split | merge | withdraw`
- Derived From: `<IDs or none>`
- Replaced By: `<IDs or none>`
- Merged Into: `<ID or none>`
- Reason: <原因>
- Revised At: `<YYYY-MM-DD>`
