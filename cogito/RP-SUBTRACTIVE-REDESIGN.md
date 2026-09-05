# RP Subtractive Redesign Implementation Plan

Status: implementation plan; this document is not an active runtime contract.

## 目前進度與本次確認範圍（2026-09-05）

本次只更新計畫，Phase 2 尚待使用者確認，不因本文件更新而開始實作。

| 階段 | 目前狀態 | 接下來的處理 |
|---|---|---|
| Phase 1：immutable-object Start | 已實作，legacy Start 入口已於 `caa6a30` 移除 | 保留現行入口；本次 focused 檢查不代表重新完成下方所有原始驗收項目 |
| Phase 1.5：RP／DP 快照共用 | 已實作至 `dca826f`，本次 48 項相關測試通過 | 以下記錄實作邊界與證據，不重新實作快照 |
| Phase 2A：共用工具審查機械層 | 下一個建議階段，待確認 | 整理兩套仍有用途的流程，修正下一步提示 |
| Phase 2B：統一工具接軌介面與驗證權限 | 設計候選，另行討論 | 不併入 2A；先釐清是否值得變更事件與命令 |
| Phase 3／4 | 延後 | Agent 範圍判斷與依賴修補授權不在下一次實作範圍 |

使用者已撤回需要舊 RP Start／快照相容的情境，因此不恢復這些舊入口，也不為缺少必要快照欄位的歷史資料補造核准證據。`handoff-tool-*` 則仍服務目前的新流程，不能因名稱或起源而視為已退役功能。

## Objective

Stop RP recovery branches from growing around validation-only operations. The first delivery replaces the disposable successor Start Gate checkout with immutable-object validation. Later deliveries may consolidate tool review mechanics and introduce a conservative Agent-impact routing model. Bounded remediation remains deferred until usage data proves that it is worth expanding the Package contract.

The governing architecture rules are:

1. Pure validation does not write external state or create workflow checkpoints.
2. A single authority object has one public lifecycle; its phase may change guards and invalidation, not event vocabulary.
3. Agent impact analysis is a rebuttable claim. The Gate derives the minimum route from actual deltas and frozen policy, and the user approves the exact proposal.
4. Only operations that perform durable external mutations receive intent, receipt, and recovery protocols.

## Delivery sequence

### Phase 0: supported-state baseline (revised after legacy retirement)

- Preserve fixtures for supported snapshots, ordinary toolchain adoption, pending tool proposals, approved handoff tool repair, successor Start success, partial transfer, and completed RP.
- Retired snapshot formats and detached Start checkpoints require no compatibility execution path. Preserve historical evidence without promising that unsupported journals can resume.
- Record projected state and `next_action` for each fixture before changing writers.
- Never rewrite an existing RP, source, or successor journal.

### Phase 1: immutable-object successor Start Gate

The following records the Phase 1 design. Its legacy Start entry cleanup is complete; it does not authorize further implementation in this document.

#### Hash dependency order

Use a directed, non-circular binding chain:

```text
StartArtifactManifest -> RP proposal -> independent review -> user approval -> start-gate-passed
```

`StartArtifactManifest` contains no proposal, review, or approval hash. The RP proposal binds `start_artifact_hash`; review binds `proposal_hash`; approval binds the exact proposal and artifact; `start-gate-passed` binds the artifact, proposal, approval event, and verifier.

#### StartArtifactManifest

The versioned manifest binds:

- source and successor run IDs and the source stop snapshot hash;
- repository object format;
- exact baseline commit and tree;
- exact resulting Start tree;
- Package, Project Graph, and effective-contract hashes;
- every control as repository-relative path, Git mode, object type, full object ID, and SHA-256 content digest;
- tool, workflow, policy, and verifier digests.

Objects must be durably reachable before proposal publication. Prefer an existing stage-artifact commit. If a dedicated artifact commit is necessary, use deterministic content and a content-addressed, create-only ref. An orphan object or ref has no authority and is never cleaned up by the RP lifecycle. The approval event is the only authorization commit point.

#### Hardened Git object reader

Introduce a small read-only object adapter that:

- uses a minimal allowlisted environment;
- disables replace objects and lazy fetching;
- rejects unexpected alternates, promisor dependencies, hooks, filters, and external configuration;
- accepts only full object IDs for the repository object format;
- validates commit, tree, and blob types and recomputes object identity;
- compares raw tree entries as path bytes, mode, type, and object ID;
- rejects symlinks, gitlinks, malformed entries, file/directory prefix conflicts, reserved names, and configured platform case or Unicode collisions;
- never checks out a tree, reads the worktree or index as an authority source, or invokes the network.

#### Read-only projections

Add APIs that replay and validate event journals entirely in memory. The Phase 1 verifier must not call store loaders that refresh `state.json` caches.

#### Start verification

For new proposals, Start Gate:

1. reads the approved immutable manifest and objects;
2. validates the full Package, Graph, contract, policy, workflow, and tool semantics from those objects;
3. deterministically proves that baseline-to-Start-tree differences are exactly the approved controls;
4. read-only checks that the already-published live Package and Project Graph match their approved hashes;
5. rechecks source, RP, successor, and approval event anchors;
6. appends the existing successor `start-gate-passed` event using the previously observed successor event hash as CAS.

The Start request fingerprint and receipt bind the Start artifact hash, proposal hash, approval event hash, and verifier digest. A repeated action with the same binding replays the result; the same action with a different binding fails closed.

Keep existing receipt fields required by integration, finalization, and workflow guards, including `delivery_head`, `package_hash`, `baseline_valid`, `contract_valid`, and `worktrees_valid`. Add the Start artifact, resulting tree, proposal, approval, Graph, tool, and verifier bindings.

#### Removed active behavior

Successor Start verification for new-format proposals never:

- create or remove a Git worktree;
- create directories or copy, unlink, write, or chmod control files;
- emit intermediate Start materialization checkpoints;
- create Bundle preparation, anchoring, validation, cleanup, or repair events;
- add a Start recovery command.

Worker layout creation and validation move to the existing formal transfer/create mutation boundary. Package publication, Project Graph activation, `work-transfer-planned`, `work-transferred`, and their recovery remain because they represent real durable mutations.

#### Legacy retirement

- Every approvable proposal carries `start_artifact_hash` and uses immutable-object Start validation.
- Proposals without a Start artifact are unsupported and fail projection.
- Existing executing or completed successors are not re-gated.
- Old proposals and approvals are never supplemented with a generated artifact hash.
- The detached-worktree fallback and its Start checkpoint events are removed after the unfinished legacy handoffs are withdrawn.

#### Phase 1 tests

- full and abbreviated SHA-1/SHA-256 IDs, wrong object types, corrupt or missing objects, and GC retention;
- replace refs, polluted Git environments/configuration, alternates, promisor repositories, and proof that validation performs no fetch;
- symlink, gitlink, mode, prefix, duplicate, reserved-name, case-fold, and Unicode-normalization conflicts;
- extra add/delete/rename and exact entry mismatch;
- valid bytes with invalid Package run ID, Graph active run, DAG, contract, policy, workflow, or tool binding;
- live Package/Graph publication drift;
- same action/same artifact replay, same action/different artifact rejection, and event-tip CAS races;
- interruption at every object-validation point without new RP events;
- supported-state fixtures, rejection of unsupported proposals, integration base-head compatibility, and executing/completed successor behavior.

#### Phase 1 acceptance gates

- zero Start Gate checkout, control-file write, chmod, cleanup, fetch, hook, or filter behavior;
- zero new RP states, Start checkpoints, Bundle lifecycle events, or recovery commands;
- new proposals use only immutable artifact semantics plus read-only live publication checks;
- supported journals replay without rewriting evidence; unsupported legacy data receives no fabricated upgrade;
- run tests for changed files, related disposition flows and necessary RP integration cases; explain any proposed expansion first, and do not run all `test_replan*.py` or the full suite by default;
- security, legacy, and behavioral results are reported separately.

### Phase 1.5：RP／DP 共用快照（已實作，補記）

#### 已完成什麼

- `cogito_product_snapshot.py` 共用 Git tree entries、排除已驗證路徑後推導產品樹，以及 journal 原始位元組前綴／事件游標的綁定和檢查。
- `cogito_replan_snapshot.py` 保留 RP 的分類：產品、凍結文件、來源證據、Worker、工具與允許更新的 runtime 各自驗證；不再接受缺少目前必要 runtime binding 的舊快照。
- `cogito_disposition_snapshot.py` 使用同一組底層原語，保留 DP 的 stop／pause、來源取消、RP 委派及封存控制文件規則。
- 產品比對只能排除已辨識且通過相應規則的 runtime 路徑；不全面忽略 `.cogito/`。Graph 的合法變更由對應流程邊界另外驗證。
- 原始 delivery／Worker trees、事件歷史與核准內容保留；產品樹投影不覆蓋原始證據。
- DP archive／release 驗證精確 refs、封存清單與恢復紀錄，保留真正修改工作內容所需的重試機制。

相關提交依序為 `941cd77`、`6961183`、`1f8e53d`、`0bb33b9`、`f037f75`、`dca826f`。這是共用底層機械操作，不是把 RP 與 DP 合併成同一個生命週期。

#### 寫入邊界：避免把「快照共用」誤解成完全零寫入

Phase 1 的 Start verifier 直接驗證已核准 immutable artifact。Phase 1.5 的產品樹投影目前仍用暫存 Git index 執行 `read-tree`／`update-index`／`write-tree`，會產生 Git objects；它不是 Phase 1 的 hardened object reader，也不能自動繼承其全部安全保證。

這些投影操作不建立驗證用 worktree、不複製產品檔案、不更新正式 index，也不新增流程事件。暫存 index 或無引用 tree 本身沒有核准權力。若未來要將投影改為完全唯讀的 entry 比對，應另行提出修改與收益，不在 Phase 2A 順帶重寫。

DP 的 pin／release 則確實需要保存 refs 或改動工作內容，應保留既有 intent、receipt 與 recovery。不能把驗證用暫存 worktree 的刪除原則套用到這些必要操作。

#### 本次檢查證據

2026-09-05，於 `dca826f` 執行以下 8 個測試模組，共 **48 項通過**：

```sh
PYTHONPATH=cogito/tests:cogito/scripts python3 -m unittest \
  test_replan_runtime_snapshot test_disposition_no_work \
  test_disposition_archive test_disposition_pause \
  test_disposition_recovery test_disposition_replan \
  test_disposition_flow test_replan_handoff_tool_repair -q
```

涵蓋未忽略 runtime 的正常流程、產品／Worker／凍結證據漂移、歷史前綴篡改、封存綁定、release、stop／pause 中斷重試，以及目前格式的 handoff 工具修正。首次執行受 sandbox 禁止 `ps` 影響；使用必要權限重跑相同範圍後通過。

本次沒有跑完整 suite、所有 `test_replan*.py`、mypy 或新的人工驗收旅程；也不宣稱涵蓋所有惡意檔案系統情境。檢查沒有發現阻擋下一階段的快照問題。

### Phase 2A：整理共用工具審查步驟（待使用者確認）

#### 要解決的問題

`toolchain-*` 處理規劃期間的工具接軌；`handoff-tool-*` 處理已進入 `handing-off`、但 successor 尚未 Start 且尚未移植工作時的工具修正。後者仍能使用目前 immutable Start artifact 完成交接，已有整合測試，不是可直接刪除的舊 Start fallback。

兩者都有「提案 → 獨立審查 → 精確 hash 核准／拒絕」，但部分程式碼各寫一份。已確認的具體問題是：`handoff_tool_status` 正在 `reviewing` 或 `awaiting-approval` 時，`next_action` 仍提示繼續交接，而 handoff Gate 正確拒絕交接。Agent 因此可能反覆嘗試被禁止的操作。

#### 預計修改順序

1. **固定現有行為與差異。** 列出兩個流程的允許階段、核准綁定、失效效果、pending guard、replay 與事件寫入邊界；以既有測試為基礎，只補缺少的相關案例。
2. **先修正下一步提示。** 等審查就提示審查；等精確 hash 核准就提示核准；只有完成或拒絕後才按當前狀態提示交接。測試需同時核對提示與實際 Gate 行為。
3. **抽出確實相同的機械步驟，並同步刪除重複實作。** 候選包括 proposal hash 核對、reviewer 與作者分離、review binding、核准／拒絕的狀態檢查、pending 判斷與提示選擇。對 replay、CAS、鎖與事件追加優先沿用現有 store／event 基礎設施，不另建第二套。
4. **讓兩個現有入口使用共用步驟。** 僅用固定的兩種流程設定表達欄位或名稱差異；保留各自必要的商業與安全判斷。如果某一步語義不同，保留在原流程，不以大量 callback 或新例外硬塞進共用核心。
5. **清除被替代的程式碼並更新對應說明。** 檢查 imports、委派方法及事件分派；只有已無呼叫者或已被完整替代的部分才刪除。新的共用檔案若有必要，必須同時指出它替代了哪些舊實作。

#### 預計影響檔案

| 檔案 | 預計處理 |
|---|---|
| `scripts/cogito_replan_state.py` | 共用審查狀態處理與正確的 `next_action` |
| `scripts/cogito_replan_toolchain_rules.py` | 抽出實際相同的純驗證；保留工具接軌特有規則 |
| `scripts/cogito_replan_toolchain.py` | 呼叫共用步驟；保留 proposal 建構、scope、compatibility 與 revalidation |
| `scripts/cogito_replan_handoff_tool.py` | 呼叫共用步驟；保留交接 checkpoint、階段資格與核准效果 |
| `scripts/cogito_replan_store.py` | 僅在接線或共用 guard 確實需要時修改 |
| 以上檔案對應 tests／references | 驗證行為一致、提示修正與操作說明 |

以上是預期範圍，不要求每個檔案都修改。若需要修改 snapshot、Start verifier、DP lifecycle 或其他授權規則，先說明具體原因並回到計畫討論。

#### 保留與不擴張的邊界

- 保留兩個現有流程的資格限制、產品／工具範圍檢查、相容性判斷及不同的核准失效效果。
- 保留 `toolchain-*` 與 `handoff-tool-*` 的事件格式、proposal hash、CLI 與現行歷史投影；這些仍是目前有效格式，不是恢復已退役的 Start／snapshot 相容層。
- 不新增 `tool-migration-*` 事件、命令、狀態或恢復流程；不做可動態擴充的通用 workflow engine。
- 不讓 Agent 自行核准、不放寬工具目錄或產品路徑、不改成只看檔名就豁免安全檢查。
- 不把 Phase 3 的 Agent 範圍判斷、Phase 4 的依賴修補授權或新的 bootstrap verifier 併入本階段。

#### 相關測試與驗收

優先選擇 `test_replan_toolchain_rules.py`、`test_replan_toolchain.py`、`test_replan_handoff_tool_repair.py` 中直接受影響的測試。若修改共用 RP projector，補跑其對應 state 測試；只有涉及 handoff 接線才追加必要的 RP handoff integration。Phase 1.5 的 48 項不需要因純文件或無關提示修改全部重跑。

必須確認：審查／核准提示與 guard 一致；自我審查、錯誤或過期 hash、未核准接續仍被拒絕；相同 action 重試不重複寫事件，不同輸入不能冒用 action；兩個流程原有核准效果及正常交接保持一致。若變更碰到 CAS 或鎖，才補跑其對應競爭／中斷案例。

驗收要求是：共用步驟已有兩個真實呼叫者、被替代的重複程式碼已刪除、沒有新增公開流程分支、既有事件／核准證據不被改寫。回報修改前後的 production 行數與重複實作，測試與文件另計；不能只新增共用層卻留下兩套原實作。若 production 程式碼淨增加，先說明必要性，再決定是否調整設計。

實作經確認後，建議把「提示修正與相關測試」和「共用機械層與舊碼刪除」分成可獨立閱讀的提交；本次文件更新不執行這些修改。

### Phase 2B：是否統一工具接軌的公開介面（延後另議）

原計畫的 `tool-migration-*` 家族、bootstrap verifier 與命令縮減目標移到此處作為候選，並非既定實作要求。Phase 2A 只減少內部重複，**不等於已減少公開 RP 事件或命令**。

完成 2A 後，再確認能否把兩個現行工具接軌生命週期整合為一個、以階段區分資格與失效效果。任何新事件家族都必須有取代舊家族的明確收益與退役安排，不能累加第三套流程。歷史讀取需求、pending proposal 的處置及獨立驗證工具權限都要在那次設計中明確決定；不能靜默改寫既有 hashes，也不能讓候選工具成為自己升級的唯一驗證者。

原先「23→17 事件、17→13 命令」屬於舊基線目標；經 Phase 1／1.5 刪除後須重新盤點，不能直接當作目前數量或 2A 驗收數字。

### Phase 3: Agent impact claims and Gate-derived route

Introduce a versioned `ChangeEnvelope` as an Agent claim, not an authorization object. The Gate independently computes every changed path, mode, type, object ID, authority overlap, contract/policy/tool change, and evidence binding. Every changed object must be covered by a claim.

Use a closed impact vocabulary and a monotonic route lattice:

```text
continue < in-contract amendment < bounded remediation < replan < blocked/clarify
```

The route is the join of mechanical signals, Agent claims, unresolved historical findings, reviewer additions, and unknowns. Missing evidence, unclassified or conflicting changes, authority self-change, and semantic uncertainty raise the route. Proposal revisions retain stable finding IDs and evidence-backed dispositions so a later proposal cannot silently erase known risk.

Run the new route engine in shadow mode until it has not produced an unexplained downgrade against existing behavior. `SKILL.md` then retains Agent responsibilities and fail-closed guidance, while executable versioned policy owns the minimum route.

### Phase 4: optional bounded remediation

Do not implement bounded remediation until measurements show repeated, mechanically bounded RP cases. Project Policy may define only a capability ceiling. Each Package must explicitly opt in during its original approval and freeze exact conditional paths, trigger check and classifier digests, parser/package-manager configuration, permitted semantic delta, forbidden effects, required revalidation, and activation budget. Existing Packages receive no retrospective grant.

Activation reuses the existing Technical Amendment event family. No remediation lifecycle, state, or CLI is added. Failed evidence must be current controlled-runner evidence bound to the same tree, check, contract, policy, and tool. Unsupported formats, ambiguous failures, direct dependency or manifest changes, registry/protocol/integrity changes, lifecycle scripts, native binaries, unknown impacts, or cumulative budget excess route to RP.

## Stop rules

Stop implementation and revisit the design if any phase requires:

- a Bundle preparation, anchoring, cleanup, migration, or repair lifecycle;
- a validation-only workflow checkpoint;
- Start Gate filesystem materialization or worktree cleanup;
- reconstruction of missing approved objects from live files;
- a new event family for a circumstance expressible as existing phase data or impact policy;
- Agent authority to lower the Gate-derived route;
- retrospective Project Policy expansion of an approved Package;
- candidate-tool self-approval;
- silent conversion or rewriting of legacy proposal or approval hashes;
- a dynamically extensible generic workflow engine;
- more active states, events, commands, or recovery code than the phase removes.

## Scope and trust boundary

Phase 1 protects against hostile or malformed repository content, unauthorized deltas, Git configuration ambiguity, accidental drift, crashes, replay, and cooperating concurrent writers. It does not protect an environment where the operating system, approval identity channel, selected Git executable, bootstrap verifier, or same-UID actor capable of replacing the Gate and complete journal history is compromised. That stronger threat model requires signed or externally anchored approvals.
