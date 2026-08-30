# FS-012 — Personalized Greeting Spec

## Document Information

- Feature Slice: `FS-012`
- Change Type: `feature`
- Document Status: `draft`
- Feature Slice Status: See `docs/blueprint/feature-slice-blueprint.md`
- Created: `2026-08-29`
- Last Updated: `2026-08-29`
- Shared Understanding: `confirmed`
- Boundary Gate: `passed`
- Boundary Basis: `Confirmed single user-visible result in Slice Brief and Product Requirements before Draft commit`

## Change Information

- Revises Feature Slice: `none`
- Corrects Feature Slice: `none`
- Previous Spec: `none`
- Legacy Baseline: `none`
- Authoritative Spec: `this document`

## Source Reference

- `docs/project/product-requirements.md`, section `Personalized Greeting`

## User Story

```text
身為需要辨識回覆對象的使用者，
我希望問候訊息能包含我提供的名稱，
以便確認系統正確處理輸入。
```

## Behavior Change

### Current Behavior

- 系統只能回傳固定的一般問候。

### Target Behavior

- 非空白名稱產生個人化問候；空白名稱產生一般問候。

### Preserved Behavior

- `health_status()` 持續回傳 `ok`。

## Input / Output

### Input

- 任意字串名稱。

### Output

- 非空白名稱回傳 `Hello, <trimmed name>!`。
- 空字串或只有空白回傳 `Hello!`。

## Rules

1. 名稱輸出前移除頭尾空白。
2. 空白名稱不得產生多餘逗號或空格。
3. 既有 health check 行為不得改變。

## Included

- 純函式 greeting formatting。
- 空白輸入處理。

## Excluded

- UI、持久化與多語系。

## Preliminary Integration Contract

`format_greeting(name: str) -> str` 接受字串並同步回傳問候；不新增外部副作用。

## AI Acceptance

| ID | Criterion |
|---|---|
| AI-001 | 非空白名稱與空白名稱均產生符合 Rules 的結果，且既有 health check 測試通過。 |

## Human Acceptance

| ID | Criterion |
|---|---|
| HA-001 | 問候文案對使用者而言自然且清楚。 |

## Open Questions

None

## Approval

- Approved By: `pending`
- Approved At: `pending`
- Approval Note: `pending`
