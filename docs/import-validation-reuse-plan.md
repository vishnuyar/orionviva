# Exact validation reuse during import and SQL publication

**State:** private staged basis and bounded publication memo implemented; historical cursor deferred; complete sample acceptance pending
**Rules:** none

## Outcome and current evidence

The owner requested completion of every change in the [import performance plan](import-performance-plan.md), with agents coordinating implementation and verification. Responsive real imports and complete prepared-sample delivery remain the outcome. Neither amendment below is authorized by the preceding [bank witness repair](import-bank-witness-plan.md); each requires its own explicit scope ruling before product edits.

The completed bank-witness candidate imports one hundred documents in 195.556 seconds, with capture and ingestion accounting for 194.050 seconds. Twenty-document cohorts take 3.671, 20.875, 30.365, 65.071 and 74.069 seconds; the resulting log has 1,889 events. This improves the earlier hundred-document observations but retains growing cost. A separate profiled SQL publication takes 147.676 seconds, including 63 complete `LedgerProjection` constructions accounting for 124.511 cumulative seconds. Nine `_records_from_owned_prefix` calls reach 63 `_net_event` calls; mortgage binding accounts for approximately 113.96 cumulative seconds. Nested cumulative times overlap and must not be summed.

Retained evidence is under ignored `runs/incremental-import/`, including `candidate-bank-witness-vault100.json`, `candidate-bank-witness-sql100-profile.txt` and `bank-witness-timing-identity.json`. The measured environment uses strict isolated source execution, blank provider environment and network denial. Profiled duration is diagnostic evidence, not an uncontended performance comparison. The full 794-document import and actual complete prepared artifact remain unbuilt; no completion or readiness is claimed.

## Slice one: private staged basis and exact healing no-op planning

`Ledger.stage_atomically` already encloses deterministic settlement in the canonical writer decision. However, `_StagedLedger.projection()` currently lends its mutable fold, and nested root decisions copy projections and rebuild source indexes. Detaching an already exposed fold cannot establish canonical ownership: it can copy an earlier caller mutation. Establish private ownership from stage creation instead.

Keep one staged basis never lent to callers. Lazily return a deeply detached public projection view. Successful additions apply independently owned events to the private basis and discard that view. Nested decision callbacks receive detached snapshots; their chosen events are independently owned before application. `events()` derives from the private basis. Retaining or mutating a public view, its nested bodies, source events or read caches cannot affect the private basis, later events snapshots or later decisions. Caught fold failure still poisons the stage and closure disables it. Public view mutation remains local mutation; only append operations change financial state. This is a bounded staged ownership prerequisite, not a general copy-on-write framework.

Within this exact active stage, issue one private healing planning basis containing independently owned events, resolver, validated source index, activity selection, funding context and event map. Bind it to the genuine owner stage, operation, thread and mutation generation. It must never accept a caller-supplied projection, event tuple, index or freshness claim. Keep its internals away from callbacks that can retain or mutate them.

Evaluate the same existing root selection, row binding and validation algorithm against this basis. A proven no-op need not enter another nested projection-copy and full-index construction boundary. An actual proposed change still takes the existing strict `append_from_source` path against the private current frontier. Every addition by any helper, failed fold or stage closure invalidates the planning basis; rebuild before the next root. Preserve target order and bounded copy-healing passes. Public or legacy calls without the exact private stage capability retain fresh per-root decisions, because another writer can advance between discovery and decision. Event count, last identifier, accepted status or filesystem metadata cannot alone establish freshness.

Independent alternatives are deferred: filtering account-reference triggers requires a complete dependency-resolution change proof, and a second canonical staged event spine adds synchronization and recovery burden. Neither is included. This slice changes no target set, evidence meaning, source policy or financial result.

## Slice two: scoped historical validation reuse in SQL publication

`materialize_authenticated_snapshot` in `product/viva/investment/authenticated.py` receives an authenticated committed snapshot from the read-store publication path and constructs detached events before calling the investment materializer. `ReadStore._apply_owned_events` verifies snapshot identity before this call. The source marker is written in the same generation transaction. Preserve that authenticated boundary and all publication checks.

Activate the existing bounded `ValidationMemo` for one authenticated materialization when no memo is active. Enclose the complete investment materializer and its payroll work, not each helper separately. If the canonical operation already has a memo, inherit it without replacing, clearing or extending its established lifetime. A newly created publication memo retains the existing 512-entry bound and is released and its context reset on success or exception. No process-global financial memo, persisted memo or cross-publication reuse is introduced.

Inside `_records_from_owned_prefix`, a cold historical payroll lookup currently calls `_net_event` with an earlier event prefix, which builds a complete projection. That loop already owns its events through `PrefixProofIndex` and requires each payroll observation's recorded count to equal its ordinal, with an exact prefix proof. Use a private monotonic projection cursor over that same owned event sequence. Advance in event order to the requested count; resolve the same `_enumerated` movement key and currency, depository kind, unique candidate, transaction event and line as the fresh projection. Never substitute the final projection for an earlier prefix.

The cursor never escapes the owning records loop or accepts an arbitrary supplied projection. Its event inputs are independently owned. Memo hits continue to use the existing complete prefix proof, movement key and currency and retain only the existing immutable transaction identifier and `TxnLine` field tuple. Validate the referenced transaction is present at that exact prefix. Do not store a mutable projection, resolver or cursor in the memo. Ordinary public `_decomposition` and `_net_event` caller-input paths retain their current complete hashing and fresh-replay behavior; current-source append validation is unchanged.

Cursor application must equal `LedgerProjection(events[:count])` at every queried prefix, including aliases, corrections, retroactive instrument visibility, mortgage observations and source lifecycle changes. Existing `LedgerProjection.apply` can itself rebuild when earlier instrument visibility changes; retain that behavior rather than bypassing it with a lower-level core fold. If exact prefix ownership, monotonicity or equivalence cannot be established, use the fresh full-prefix path. Expected reductions such as fewer cold lookups or one growing fold per loop are hypotheses to measure, not acceptance claims.

## Common fence and acceptance checklist

These slices are independent and may be verified separately. Preserve canonical JSONL authority, strict physical chain authentication, encrypted state, exact arithmetic, grades, provenance, retraction, supersession, cross-writer correctness, provider consent and existing deadlines. No SQL-authority migration, relaxed validation, arbitrary projection injection, global cache, public-sample bypass, private-vault access, paid call, installation replacement, commit or release belongs to this brief.

- [x] Independently fact-check each boundary and obtain separate Director scope rulings before its product edits.
- [ ] Reproduce repeated unchanged-root planning and repeated cold historical projection construction before changing them.
- [ ] Prove staged public-view and nested-callback mutations cannot contaminate canonical events, later decisions or healing proofs, including retained aliases before and after append, equal-count body mutation, failure and closure.
- [ ] Compare shared no-op and actual-change healing decisions with the fresh algorithm; cover intervening additions, stale or forged capability, public concurrent writers, funding conflicts, missing evidence, copies and lifecycle changes.
- [ ] Differentially compare cold cursor results and failures against complete replay at every historical query prefix, including aliases, currency, duplicate candidate, missing transaction, corrections, retroactive mortgage visibility and source revisions.
- [ ] Prove complete proof keys reject changed bodies or order despite identical identifiers; no cursor or mutable value escapes; bounded memo eviction, nested active memo, exception cleanup and independent publications preserve correctness.
- [ ] Retain affected suites and independent review, then run uncontended paired hundred-document capture plus SQL publication measurements with fixed candidate, inputs and environment; profile separately.
- [ ] Complete the full 794-document pipeline, final cohorts, source checks, replay agreement, packaged artifact restore and reopening. Record residual costs and unresolved acceptance instead of declaring early completion.

## Director ruling — Checkpoint 1: separate bounded approvals for validation reuse

The Director reviewed this brief at SHA-256 `9d81358f40f7cacb5b62f4325dfa720c25ad92bb47c7780e59a1016a63753fc2` and the independent factual report retained at `runs/incremental-import/validation-reuse-factcheck/report.md`. Seven factual claims were verified; two proposed correctness properties remain unverified. No material factual refutation was found.

**Slice one — approve private staged ownership and exact active-stage healing reuse.**

The Fact-checker demonstrated that mutation through the current public staged projection contaminates later event snapshots and nested decisions. Establish an unexposed private basis from stage creation before introducing reuse. Independently own appended events and callback inputs; public views and retained aliases must never influence the basis.

A healing planning basis may be reused only within its genuine active stage, operation, thread and unchanged mutation generation. No caller-supplied projection, index, tuple or freshness assertion establishes that authority. Any addition, failed fold or closure invalidates reuse. Preserve root ordering, target selection, bounded copy passes, validation outcomes **and errors**. An actual change must return to the existing strict append path at the current private frontier. Public and legacy calls retain fresh decisions.

Acceptance must demonstrate mutation isolation, stale/forged capability rejection, failure and closure behavior, and differential parity with fresh healing for no-op and actual-change cases. Missing evidence, conflicts, copies, source lifecycle and concurrent public writers remain required cases. This approval introduces no general ownership framework or broader target filtering.

**Slice two — approve publication-scoped memo reuse; conditionally approve a private historical cursor.**

The existing authenticated snapshot, exact historical proof keys, immutable memo payloads and 512-entry bound support reusing `ValidationMemo` across one authenticated investment publication. A new memo must reset and release on success or exception. An inherited canonical memo must retain its existing identity and lifetime; do not replace or clear it. No cross-publication or process-global financial cache is approved.

The memo change may proceed and be measured independently of the cursor.

The cursor is approved only where its behavior is demonstrated equivalent to constructing `LedgerProjection(events[:count])` at the exact queried prefix. Constructor prescanning of instrument history and visibility means incremental `apply` alone is **not** proof. Establish parity for returned values and failures across relevant aliases, corrections, source lifecycle and retroactive instrument/mortgage visibility. Retain fresh replay for any relevant class whose equivalence is not established. Never substitute the final projection for historical state, expose the cursor, or bypass constructor semantics through lower-level folding.

Memo hits must retain complete prefix/body/order proofs and verify the referenced transaction exists at that prefix. Mutable projections and resolver state must not enter memo values. Public `_net_event` and `_decomposition` trust boundaries remain unchanged.

Both approvals preserve strict physical authentication, canonical JSONL authority, immutable coherent SQL generations, exact financial semantics and existing deadlines. They authorize bounded implementation and independent review, **not acceptance**. Require paired uncontended hundred-document capture-plus-SQL measurements, separately collected profiles, and the parent checklist’s full 794-document import, replay agreement, source closure, prepared-artifact restoration and reopening before completion claims.

No commit, installation replacement, release, push or merge is authorized. This ruling is persisted by the parent; the Director remained read-only. Issued in the Director’s name.

## Slice two implementation disposition

Authenticated native and scratch investment publication now share the existing bounded validation memo for the complete materializer. An enclosing memo retains its identity and lifetime; a publication-owned memo is cleared and its context reset on success or exception. The focused actual SQL operation gate reduces three repeated historical net projection constructions to one, with unchanged SQL rows, source identity and financial error behavior in the synthetic fixture. These checks establish neither composed timing nor full-sample acceptance.

The conditional historical cursor is deferred and is not implemented. Constructor prescanning and retroactive instrument visibility have not been proved equivalent to a growing apply cursor for values and failures. A conservative whitelist would fall back after the sample's first instrument and leave the measured workload unchanged. Every historical memo miss therefore retains the existing complete fresh-prefix replay. Public payroll validation remains unchanged; no cursor parity or constant-time claim is made.
