# RP Subtractive Redesign Implementation Plan

Status: implementation plan; this document is not an active runtime contract.

## 目前進度與本次確認範圍（2026-09-05）

本計畫最初僅更新文件；使用者後續已授權開始 Phase 2A，實作結果補記如下。Phase 2B 已於後續授權後完成入口整合；Phase 3／4 尚未開始。

| 階段 | 目前狀態 | 接下來的處理 |
|---|---|---|
| Phase 1：immutable-object Start | 已實作，legacy Start 入口已於 `caa6a30` 移除 | 保留現行入口；本次 focused 檢查不代表重新完成下方所有原始驗收項目 |
| Phase 1.5：RP／DP 快照共用 | 已實作至 `dca826f`，本次 48 項相關測試通過 | 以下記錄實作邊界與證據，不重新實作快照 |
| Phase 2A：共用工具審查機械層 | 已完成本次共用投影與提示修正，47 項相關測試通過 | 兩套現行入口保留，實作與驗證範圍見下方補記 |
| Phase 2B：統一工具更新入口 | 已實作，27 項相關測試通過 | 四個 toolchain 命令依階段及原提案綁定自動路由 |
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

### Phase 2A：整理共用工具審查步驟（已授權並完成本次實作）

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

#### Phase 2A 實作與驗證補記

- 在既有 `cogito_replan_toolchain_rules.py` 抽出兩個呼叫者共用的 `project_tool_review`，刪除 handoff 分派中的重複 proposed／reviewed／approved／rejected 投影。沒有新增檔案。
- 各入口仍先驗證所屬階段與 proposal；一般工具接軌的產品核准失效處理保留在原 wrapper，handoff 工具修正保留原產品核准。CLI 的不同建構與 live revalidation 步驟未硬合併；原本已共用的 reviewer 檢查、store replay／事件寫入也未再包一層。
- `next_action` 現在依目前階段的工具審查狀態提示獨立審查或精確 hash 核准。公開命令、事件格式與權限邊界不變。
- Production 修改僅涉及上述 rules 與 `cogito_replan_state.py`，共新增 56 行、刪除 57 行，淨減少 1 行。這次收益是移除一份重複狀態邏輯，並非大幅減少行數或公開流程分支。
- 自動化驗證：`test_replan_toolchain_rules` 18 項；`test_replan_toolchain`、`test_replan_handoff_tool_repair`、`test_replan_state` 合計 29 項；共 47 項通過。測試涵蓋兩種核准效果、過期 hash、自我審查、拒絕保留先前綁定、提示與 handoff guard 一致，以及同 action 重試。未執行完整 suite、DP 快照測試或新的人工旅程。
- 更新 `references/replan-toolchain.md` 的下一步說明，並移除已過時的「隔離 Start Gate」敘述。Phase 2B 尚未實作。

### Phase 2B：統一工具更新入口（已實作）

本節原先僅為計畫；後續已取得實作授權。目標是 Agent 不再自行選擇 `toolchain` 或 `handoff-tool`；由 Gate 根據已記錄的 RP 階段與提案綁定決定適用規則。Phase 2A 已共用內部審查投影，本階段移除重複的公開入口，不新增第三套流程。

#### 對外操作：8 個工具命令縮減為 4 個

唯一公開命令保留為 `replan toolchain-propose`、`toolchain-review`、`toolchain-approve`、`toolchain-reject`，沿用現有輸入參數。移除對外 `handoff-tool-*` 的四個命令及別名；Agent 不提供 mode、phase 或其他手選流程的參數。

這是工具更新子命令的 8→4，不是整個 RP 的命令總數。兩種必要的安全規則與既有事件家族仍保留，因此不能宣稱內部階段分支或事件也全部合併。

#### Gate 如何判斷

| 操作情境 | 判斷及行為 |
|---|---|
| 首次提案，RP 在 analyzing／reviewing／awaiting-approval／awaiting-decision | 使用現行規劃期間工具接軌規則；核准後回到 analyzing，原產品 proposal 的有效核准失效，須重新提案 |
| 首次提案，RP 在 handing-off | 使用現行交接工具修正规則；仍須確認 successor 在 start-gate、沒有 transfer plan／receipt、source 尚未 superseded，以及 Graph 等綁定符合條件 |
| 交接工具修正核准 | 保留原產品 proposal／review／approval；重試原 handoff，重新驗證 Start，successor 後續重跑必要 checks |
| 其他階段，或交接資格不符 | 拒絕，不改選其他規則，也不自動建立補救流程 |

審查、核准與拒絕必須跟隨已保存的 proposal hash 及所屬事件家族，並檢查當前階段是否仍合法；不能單憑最新階段，把同一份提案換成另一套核准規則。家族歸屬使用原有 proposed event 與 proposal schema／checkpoint 綁定，不追加新欄位改寫既有提案。

若沒有對應提案、hash 過期、出現無法唯一判斷的待處理提案或階段不符，直接拒絕並給出原因。提案修訂沿用現行修訂規則；不能跨家族悄悄替換未完成的提案。

#### 重試與歷史保護

- 路由前先核對 action ID 的既有成功紀錄及原請求。已成功的相同操作／相同輸入走原家族 replay，即使核准後 RP 階段已變，仍不得被重新當作另一種提案。
- 相同 action ID 搭配不同操作或輸入必須拒絕。首次嘗試未成功寫入事件時，依當前資格與既有提案重新驗證，不補造成功紀錄。
- 沿用既有 `toolchain-*`、`handoff-tool-*` event bytes、request fingerprint 及投影規則；統一的是命令路由，不是把歷史事件重新命名。現有已保存的待審提案可由統一入口指向原 hash 繼續處理，仍受原有資格限制。
- 不新增 `tool-migration-*`、事件轉換、snapshot 相容分支或 recovery command；舊 Start／快照格式仍維持退役。

#### 具體修改與刪除清單

| 檔案／範圍 | 預計修改 |
|---|---|
| `scripts/cogito_replan_cli.py` | 刪除四個 handoff-tool 子命令、專用參數集合及四條 dispatch；保留 toolchain 命令 |
| `scripts/cogito_replan_store.py` | 四個 toolchain 方法成為統一路由邊界；移除四個對外 handoff_tool 委派方法，沿用現有 mutation 鎖與 replay 設施 |
| `scripts/cogito_replan_toolchain.py`／`cogito_replan_handoff_tool.py` | 保留兩種必要的 proposal 建構、資格、scope、compatibility、live revalidation 與核准效果；只在路由／重試接線需要時調整，不整套搬進新引擎 |
| 直接相關 tests | 改用統一入口；增加路由與跨階段 replay 的缺口測試，保留現有安全案例 |
| `references/replan-toolchain.md`、`references/runtime-interface.md` 及實際引用舊命令的說明 | 改為同一套操作說明，解釋 Gate 自動選擇的階段規則；先搜尋確認引用再修改 |

不因移除公開命令而直接刪除 `cogito_replan_handoff_tool.py`：其中仍有交接專用安全判斷。只有已被取代或沒有呼叫者的接線才刪除。若必須改動 `SKILL.md`，只更新實際存在的舊命令指引，不擴大 Agent 授權。

#### 測試範圍與驗收

先跑變更直接對應的 CLI／路由測試，以及 `test_replan_toolchain`、`test_replan_handoff_tool_repair` 中的相關案例。若改到共用投影或規則，再跑對應 state／rules 測試。不預設重跑 Phase 1.5 的 48 項、所有 `test_replan*.py` 或完整 suite；擴大前須說明原因。

必要驗證包括：

- 同一個 toolchain-propose 命令，在兩個合法階段產生各自原格式的提案；不合法階段不寫事件。
- review／approve／reject 精確指向已保存的家族與 hash；階段或資格變動時不切換規則。
- 一般工具核准仍使產品提案失效；交接工具核准仍保留產品核准，正常 handoff 可完成。
- 過期 hash、自我審查、未提交交接工具修正、混入產品變更，以及待審時嘗試交接仍被拒絕。
- 相同 action 重試不重複產生事件；特別驗證核准改變階段後的 replay、handoff 完成後的 replay，以及 action ID 在兩個家族之間不能被冒用。
- 舊 handoff-tool 命令不再是可用入口；CLI help 與操作文件只呈現四個工具更新命令。

完成後列出刪除的命令、路由、委派方法，並分別報告 production、測試及文件的增刪。若只是新增統一包裝、原本公開入口卻全部保留，則不算完成；若 production 淨增加，須先說明必要性與是否值得繼續。

事件家族整合、新的 bootstrap verifier、Agent 自由判定修改範圍、依賴修補授權都不在本次範圍。Phase 3／4 繼續延後。舊計畫的整體「23→17 事件、17→13 命令」目標不套用於此次入口縮減。

#### Phase 2B 實作與驗證補記

- CLI 工具更新命令由 8 個減為 4 個，刪除 handoff-tool 的四個子命令與 dispatch。Store 刪除四個 handoff_tool 委派方法，四個 toolchain 方法經固定路由選擇原有規則。
- 路由先查同 action 的原事件操作及家族，由原處理函式驗證 request fingerprint；新操作依當前階段及原提案 hash 選路。非法階段、錯誤 hash、跨家族待審及 action 換操作均拒絕。沿用原有 mutation 鎖。
- 保留兩個內部事件家族、proposal 格式、專用資格／相容性檢查及核准效果。沒有新增檔案、命令別名、狀態、事件或恢復分支。
- Production 僅修改 `cogito_replan_cli.py` 與 `cogito_replan_store.py`，新增 34 行、刪除 38 行，淨減少 4 行。更新兩份對應 references 及現有測試。
- 直接相關驗證：`test_replan_toolchain` 原有案例與 `test_replan_handoff_tool_repair` 合計 22 項通過；新增的 `ToolchainEntryRoutingTests` 5 項通過，共 27 項。包括交接完成後原 action 重試不追加事件，以及變更輸入的同 action 被拒絕。CLI 測試初版誤用外層 parser，改為直接測試 replan parser 後通過；無 production 測試失敗。
- 未執行完整 suite、所有 replan 測試、DP 快照測試或新人工旅程。Phase 3／4 仍延後。

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
