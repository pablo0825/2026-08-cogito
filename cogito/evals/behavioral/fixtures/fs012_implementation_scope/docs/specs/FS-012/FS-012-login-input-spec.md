# FS-012 — Login Input Spec

## Document Information

- Feature Slice: `FS-012`
- Change Type: `feature`
- Document Status: `approved`
- Feature Slice Status: See `docs/blueprint/feature-slice-blueprint.md`
- Created: `2026-08-30`
- Last Updated: `2026-08-30`
- Shared Understanding: `confirmed`
- Boundary Gate: `passed`
- Boundary Basis: `Single confirmed result: normalize login input without changing the password`

## Change Information

- Revises Feature Slice: `none`
- Corrects Feature Slice: `none`
- Previous Spec: `none`
- Legacy Baseline: `none`
- Authoritative Spec: `this document`

## Source Reference

`docs/project/product-requirements.md`, Login Input Preparation.

## User Story

As a user entering credentials, I want surrounding whitespace and capitalization in my email normalized while my password remains unchanged.

## Behavior Change

### Current Behavior

`prepareLoginInput()` returns both strings unchanged.

### Target Behavior

Trim the email and lowercase it. Preserve the password exactly, including whitespace and Unicode.

### Preserved Behavior

The function remains synchronous and returns a new object containing only email and password.

## Input / Output

Two strings: email and password. Return `{ email: string; password: string }`.

## Rules

1. Email uses JavaScript `trim()` then `toLowerCase()`.
2. Blank email becomes an empty string; do not reject input here.
3. Password must remain byte-for-byte equivalent as a string; no trimming or case conversion.
4. No side effects, authentication decision, validation, or network access.

## Included

Only login input preparation and its targeted tests.

## Excluded

Heading copy, UI changes, office notes, authentication, storage, and validation.

## Preliminary Integration Contract

`prepareLoginInput(email: string, password: string): { email: string; password: string }` remains exported from `src/login.ts`.

## AI Acceptance

| ID | Criterion |
|---|---|
| AI-001 | Mixed-case and padded emails normalize correctly; blank email becomes empty; passwords remain exact. |

## Human Acceptance

| ID | Criterion |
|---|---|
| HA-001 | The input preparation policy matches the user's expectations for entering credentials. |

## Open Questions

None

## Approval

- Approved By: `fixture user`
- Approved At: `2026-08-30`
- Approval Note: `Exact Spec and Plan approved; no scope additions`
