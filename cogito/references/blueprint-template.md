# Feature Slice Blueprint Template

建立 `docs/blueprint/feature-slice-blueprint.md`，不要在檔名加入版本。只在此文件保存目前 Status、Status Note 與 Active Feature Slice；詳細結構 lineage 放在相關 Slice Brief，內容歷史交由 Git 保存。只輸出下列第二個 H1 起的文件內容，並將 placeholder 換成實際值。

# Feature Slice Blueprint

## Document Information

- Schema Version: `4`
- Document Status: `active`
- Requirements Root: `docs/project/`
- Adoption Mode: `complete | rolling`
- Coverage: `complete | partial`
- Execution Mode: `legacy-staged | sequential-package | controlled-parallel`
- Last Reconciled: `<YYYY-MM-DD>`
- Active Feature Slice: `<ID or none>`
- Active Feature Slices: `<comma-separated IDs or none>`
- Integration Candidate: `<ID or none>`

## Purpose

<簡明說明目的、需求來源及使用方式>

Rolling Adoption 且 Coverage 為 `partial` 時，明確寫出：Feature Slice Index 只列已收編或正在收編的能力；未列出不代表產品不存在該功能。完整模式省略此警示。

`Execution Mode` 缺少時依相容性規則視為 `legacy-staged`。`legacy-staged`／`sequential-package` 使用 `Active Feature Slice`，並將 `Active Feature Slices` 與 `Integration Candidate` 填為 `none`；`controlled-parallel` 將前者填為 `none`，使用最多三個 ID 的 `Active Feature Slices` 與最多一個 ID 的 `Integration Candidate`。切換 mode 前必須讓使用者核准授權、active-slot、隔離與回復影響；mode 變更不修改 accepted snapshots。

## Requirement Sources

| Source | Relevant Sections | Notes |
|---|---|---|
| `docs/project/<file>` | <section> | <notes> |

## Adoption Coverage

完整模式只填寫 `Complete` 並省略下表。Rolling Adoption 使用下表，只列目前已收編或正在收編的能力，不建立未收編功能清單。

| Capability | Canonical Source | First Adopted By |
|---|---|---|
| `<capability>` | `docs/project/<file>#<section>` | `<FS-ID>` |

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
