# Feature Slice Blueprint Template

建立 `docs/blueprint/feature-slice-blueprint.md`，不要在檔名加入版本。只在此文件保存目前 Status、Status Note 與 Active Feature Slice；詳細結構 lineage 放在相關 Slice Brief，內容歷史交由 Git 保存。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# Feature Slice Blueprint

## Document Information

- Schema Version: `1`
- Document Status: `active`
- Requirements Root: `docs/project/`
- Last Reconciled: `<YYYY-MM-DD>`
- Active Feature Slice: `<ID or none>`

## Purpose

<簡明說明目的、需求來源及使用方式>

## Requirement Sources

| Source | Relevant Sections | Notes |
|---|---|---|
| `docs/project/<file>` | <section> | <notes> |

## Open Questions

<跨 Slice 或整體規劃的未決問題；若沒有填寫 `None`>

## Feature Slice Index

| ID | Name | Type | Depends On | Revises | Corrects | Status | Status Note | Last Updated |
|---|---|---|---|---|---|---|---|---|
| FS-001 | `<english-name>` | feature | none | none | none | proposed | <note> | YYYY-MM-DD |

## Documents

| ID | Slice Brief | Spec | Plan | Verification |
|---|---|---|---|---|
| FS-001 | `docs/blueprint/slices/FS-001-<name>.md` | pending | pending | pending |
