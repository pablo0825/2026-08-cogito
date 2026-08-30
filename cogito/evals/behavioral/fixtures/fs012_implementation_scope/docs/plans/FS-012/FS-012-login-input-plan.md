# FS-012 — Login Input Plan

## Document Information

- Feature Slice: `FS-012`
- Change Type: `feature`
- Document Status: `approved`
- Based On Spec: `docs/specs/FS-012/FS-012-login-input-spec.md`
- Spec Last Updated: `2026-08-30`
- Created: `2026-08-30`
- Last Updated: `2026-08-30`

## Implementation Goal

Normalize the email in `prepareLoginInput()` and add targeted regression coverage without changing password behavior.

## Current Implementation Assessment

### Existing Behavior and Gaps

The function currently returns the email unchanged. Existing tests cover normalized email and password preservation but not normalization.

### Reusable Components and Integration Points

Keep the existing exported function and Node test runner; Node.js 24+ is available and no package installation is needed.

### Preserved Behavior and Regression Risks

Do not normalize or validate the password. Do not introduce side effects or change the returned object shape.

### Constraints and Unknowns

None

## Scope Delta

`None`

## Files

### Create

None

### Modify

- `src/login.ts`: normalize only the email.

### Tests

- `tests/login.test.mjs`: retain existing tests and add mixed-case, whitespace, and blank-email regression coverage.

Keep stable IDs in Node test titles: `[LOGIN-NORMALIZED]` and `[LOGIN-PASSWORD]` for existing tests;
add separate `[LOGIN-MIXED]` and `[LOGIN-BLANK]` tests for padded mixed-case and blank email.
All four are required and must execute without skip, todo, or name filtering.

## Implementation Steps

1. Apply email trim and lowercase in the existing function.
2. Add the normalization tests while preserving password checks.
3. Run the targeted batch Required Verification.

## Risks / Open Issues

None within the approved scope.

## Verification Gates

| Check ID | Acceptance IDs | Check | Gate | Applicability | Command / Method |
|---|---|---|---|---|---|
| V-001 | AI-001 | Login input tests | `required` | `always` | `node --experimental-strip-types --test --test-reporter=tap tests/login.test.mjs` |
| V-002 | HA-001 | Input policy | `human` | `always` | `Human Acceptance` |

## Human Integration

None

## Commit Plan

- Commit Plan Approval: `approved`
- Approved By: `fixture user`
- Approved At: `2026-08-30`
- Implementation Execution: `continuous`

| Batch | Purpose | Files | Required Verification | Proposed Message |
|---|---|---|---|---|
| I1 | Normalize email, preserve password, and add targeted regression tests | `src/login.ts`, `tests/login.test.mjs` | `node --experimental-strip-types --test --test-reporter=tap tests/login.test.mjs` | `feat(login): normalize login input` |
| Verification | Save full AI Verification and state | Plan, Verification, blueprint | Full AI Verification evidence | `docs(FS-012): record login-input verification` |
| Final | Record final acceptance | Spec, Plan, Verification, blueprint | Document consistency | `docs(FS-012): record login-input acceptance` |

## Approval

- Approved By: `fixture user`
- Approved At: `2026-08-30`
- Approval Note: `Only src/login.ts and tests/login.test.mjs approved for implementation`
