# RP Subtractive Redesign and Phase 1 Implementation Plan

Status: implementation plan; this document is not an active runtime contract.

## Objective

Stop RP recovery branches from growing around validation-only operations. The first delivery replaces the disposable successor Start Gate checkout with immutable-object validation. Later deliveries may consolidate tool review mechanics and introduce a conservative Agent-impact routing model. Bounded remediation remains deferred until usage data proves that it is worth expanding the Package contract.

The governing architecture rules are:

1. Pure validation does not write external state or create workflow checkpoints.
2. A single authority object has one public lifecycle; its phase may change guards and invalidation, not event vocabulary.
3. Agent impact analysis is a rebuttable claim. The Gate derives the minimum route from actual deltas and frozen policy, and the user approves the exact proposal.
4. Only operations that perform durable external mutations receive intent, receipt, and recovery protocols.

## Delivery sequence

### Phase 0: compatibility baseline

- Preserve fixtures for legacy snapshots, ordinary toolchain adoption, pending tool proposals, both handoff Start checkpoints, approved handoff tool repair, successor Start success, partial transfer, and completed RP.
- Record projected state and `next_action` for each fixture before changing writers.
- Never rewrite an existing RP, source, or successor journal.

### Phase 1: immutable-object successor Start Gate

Phase 1 is the only immediately authorized implementation phase.

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

New-format proposals never:

- create or remove a Git worktree;
- create directories or copy, unlink, write, or chmod control files;
- emit `handoff-start-isolated` or `handoff-start-validated`;
- create Bundle preparation, anchoring, validation, cleanup, or repair events;
- add a Start recovery command.

Worker layout creation and validation move to the existing formal transfer/create mutation boundary. Package publication, Project Graph activation, `work-transfer-planned`, `work-transferred`, and their recovery remain because they represent real durable mutations.

#### Legacy compatibility

- New proposals carrying `start_artifact_hash` use immutable-object Start validation.
- Old proposals continue through the legacy handoff path.
- Legacy readers continue to accept both handoff Start checkpoints and old `start-gate-passed` payloads.
- Existing executing or completed successors are not re-gated.
- Old proposals and approvals are never supplemented with a generated artifact hash.
- Legacy recovery remains until inventory proves there are no unfinished legacy handoffs.

#### Phase 1 tests

- full and abbreviated SHA-1/SHA-256 IDs, wrong object types, corrupt or missing objects, and GC retention;
- replace refs, polluted Git environments/configuration, alternates, promisor repositories, and proof that validation performs no fetch;
- symlink, gitlink, mode, prefix, duplicate, reserved-name, case-fold, and Unicode-normalization conflicts;
- extra add/delete/rename and exact entry mismatch;
- valid bytes with invalid Package run ID, Graph active run, DAG, contract, policy, workflow, or tool binding;
- live Package/Graph publication drift;
- same action/same artifact replay, same action/different artifact rejection, and event-tip CAS races;
- interruption at every object-validation point without new RP events;
- every legacy state fixture, integration base-head compatibility, and executing/completed successor behavior.

#### Phase 1 acceptance gates

- zero Start Gate checkout, control-file write, chmod, cleanup, fetch, hook, or filter behavior;
- zero new RP states, Start checkpoints, Bundle lifecycle events, or recovery commands;
- new proposals use only immutable artifact semantics plus read-only live publication checks;
- all legacy journals replay without rewriting evidence;
- full regression and configured mypy pass;
- security, legacy, and behavioral results are reported separately.

### Phase 2: reviewed-change core and tool migration

After Phase 1 acceptance, extract only the common proposed/reviewed/approved/rejected mechanics: canonical hashes, author/reviewer separation, findings, exact approval, action replay, CAS, pending guards, and `next_action`. Keep eligibility, proposal construction, compatibility validation, and phase-specific approval effects separate.

Initially retain legacy `toolchain-*` and `handoff-tool-*` event bytes while both use the same internal core. Publish readers for a fixed `tool-migration-*` family before any writer emits it. Pending legacy proposals must complete or be rejected under their original schema and hash. A small bootstrap verifier outside the ordinary candidate-tool authority range validates tool-only history, authority manifests, review, approval, and minimum invalidation; a candidate tool cannot be its sole verifier.

Long-term targets are 23 to at most 17 active RP event kinds and 17 to at most 13 public RP lifecycle commands. Compatibility readers remain even after old writers stop.

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

