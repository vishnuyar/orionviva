# Import performance and prepared sample plan

**State:** capture-performance repair stopped after three cycles; owner decision required; not ready to ship
**Rules:** none

## Owner direction

“go ahead and make each of those changes, prepare the plan, follow checklist and complete them, use multiple agents to orchestrate this”.

The outcome is responsive real-vault imports and immediate prepared-sample delivery. A prepared sample alone does not establish real-vault performance. Preserve exact arithmetic, reconciliation, provenance, encryption, capture-first, provider consent, permanent document identities and cross-writer correctness. Do not disturb the installed sample or existing vaults.

## Existing mechanisms and diagnosis

At the recorded baseline, encrypted content-addressed originals, three bounded extraction workers, one coordinator writer, durable generic job receipts and authenticated incremental SQLCipher read generations already existed. The implementation reuses them. Baseline interrupted unfinished jobs restored as failed, or cancelled if cancellation was requested; folder progress was session-only, and sample activation imported all originals before publishing SQL.

At baseline every ledger append decrypted prior events, copied the prefix, and reconstructed its projection. A synthetic first-twenty-document profile observed 271 cache installations and 318 projection constructions for 343 events. Projection reconstruction dominated; this profile is supporting evidence, and exact Vault.open measurements establish the composed baseline. Full physical chain authentication on canonical decisions is retained; removing repeat decryption, copying and projection folds must not weaken tamper detection.

## Architecture choice

Keep the encrypted hash-chained canonical event log and disposable immutable SQLCipher generations. Apply new events to owned state and catch SQL up to an authenticated committed revision. Canonical durability precedes SQL publication; a crash gap is repaired from the log. Publish only coherent revisions and never combine financial facts from different revisions.

Moving audit events and financial tables into one SQL transaction is an assessed alternative, not an implemented feature of this plan. It would reopen the append-only authority, backup, migration and keyless verification contracts. The prior recommendation explicitly allowed measuring an incremental repair before deciding on that migration. Mutable WAL storage is likewise unnecessary to achieve the outcome with existing immutable read generations.

## Implementation slices

1. Remove repeated ledger reconstruction and cache trusted type metadata. Own cached event bodies independently of callers; preserve projection revocation, external-write synchronization, uncertainty poisoning, same-size mutation detection and strict full-replay recovery. Batch only equivalent decision boundaries.
2. Retain encrypted per-document work checkpoints bound to content and extraction contract. Persist responses before completed extraction. Resume deterministic settlement without another model call; an uncertain external request requires explicit confirmation. Preserve duplicate/cancellation and active-vault-generation guards. Generic job receipts remain operational metadata, not financial authority.
3. Publish SQL at bounded document/chunk boundaries and refresh committed results while the folder continues. Keep processed coverage explicit, navigation usable, and pending documents excluded from claimed financial coverage. Do not broadly admit reentrant mutating handlers through the cancellation pump.
4. Build the synthetic sample using the verified production pipeline. Ship a separately packaged, versioned, hashed artifact with complete originals and financial source closure. Restore into a new private instance, verify compatibility and contents, regenerate runtime-bound receipts, and atomically activate only a validated instance. Never reuse public synthetic credentials for a personal vault.

## Checklist and acceptance

- [x] Independent factual check and scope ruling before product edits.
- [x] Retained synthetic baseline at the complete capture-and-ingest boundary with environment and inputs.
- [x] Incremental ledger updates; unchanged integrity tests plus external writers, caller mutation, legacy, crash and replay-equivalence cases. Supporting correctness verified; scaling remains open below.
- [x] Durable bounded import continuation with exact-once effects and no automatic uncertain paid retries.
- [x] Incremental coherent SQL publication and usable partial results.
- [ ] Complete prepared sample built, packaged, safely restored and reopened; tamper/version/path rejection.
- [ ] Full 794-document import and increasing-history measurements, including final cohort; independent full-replay agreement.
- [ ] Required package, architecture, style, privacy and independent acceptance checks.
- [ ] Fresh Verifier, Interface Designer and Steward; reconcile storage/jobs/sample docs and report unresolved evidence accurately.

No timing promise is established until measured. Required acceptance cases are not waived by supporting unit tests. No provider calls, existing-vault migration, installation replacement, push or release is part of this engineering run. Commit and merge remain the owner's separate gates.

## Current evidence and checkpoint

The [packaged validation harness proposal](packaged-validation-harness-plan.md) classifies stale tiny-sample controller assumptions as tooling defects. Independent factual check and the Director approved the bounded repair without changing product contracts, independent evaluator assertions or readiness bounds. Fresh independent checks passed 141 cases; actual prepared-artifact execution remains open.

The [exact validation reuse proposal](import-validation-reuse-plan.md) records two independent bounded next slices: private staged healing decisions and scoped historical validation reuse during SQL publication. Independent factual check and separate Director Checkpoint 1 rulings approved bounded implementation, with historical cursor use conditional on demonstrated equivalence or fresh replay fallback; complete sample acceptance remains open.

Increasing-history performance remains blocked. The [stable bank funding provenance amendment](import-bank-witness-plan.md) records a reproduced unnecessary revision cascade, independent factual review and the Director's bounded Checkpoint 1 approval. Its supporting reproduction does not establish full 794-document completion or readiness.

Checkpoint 1 approved the bounded incremental implementation, durable recovery, coherent partial results and a separately validated prepared sample. JSONL remains canonical authority; SQL-authority migration was assessed and deferred. The Fact-checker found six baseline claims verified, full-sample completion unverified, and no material falsehood. These are scope rulings, not acceptance passes.

Supporting implementation checks cover ownership and tamper handling, crash recovery, queue continuation, SQL publication and UI state. Independent review caught and reproduced stale projection aliasing, current-projection poisoning and a lock-order deadlock; the repaired reproductions pass. Browser checks exposed exclusive-channel status loading, selection/inspection association and unavailable first-chunk Stop controls. These were repaired and rechecked in synthetic vaults. The final delayed-chunk browser run showed immediate Stop, draining to a paused selection with two originals remaining. Frontend checks passed 1,463 tests. This verifies local intake behavior, not financial model quality or installed delivery.

An earlier first-100-document measurement took 376.645 seconds through the vault/import boundary. Its first twenty took 3.626 seconds versus 21.287 seconds at baseline. After measured private validation repairs, the production sample worker reached 100 documents at 275.634 seconds elapsed, including 267.002 seconds inside `capture_and_ingest`; successive twenty-document capture cohorts took 3.483, 23.005, 36.614, 94.232 and 109.667 seconds. Worker setup and progress publication are separately timed, so these totals are not identical benchmark boundaries. The full attempt was stopped for the remaining scaling defect after 103 completed documents and 104 captures; its fixture and failure record remain retained. No full-794 or final-cohort performance claim is made.

The isolated profile showed repeated whole-history copies and checks during historical healing. Independent reproduction then established that an equivalent bank-reference arrival emitted four successor events while the original witness still validated and transaction count stayed unchanged. The approved amendment repairs that churn. The subsequent isolated hundred-document run completed capture and ingestion in 195.556 seconds, with twenty-document cohorts of 3.671, 20.875, 30.365, 65.071 and 74.069 seconds and 1,889 events. A separate profiled SQL publication took 147.676 seconds and constructed 63 complete historical projections; profiled duration is diagnostic and is not a plain latency comparison. These measurements still show growing cost and do not establish full-sample completion. The complete changed/new-path and tracked-tree denylist scans passed against the owner's existing twelve-pattern local file; the file and patterns were not copied into the candidate.

Retained supporting evidence is under ignored `runs/incremental-import/`. The initial independent evaluator result was `invalid_report`: all 28 declared cases were incomplete and revision/qualification evidence was missing. It establishes neither a product pass nor a deterministic product failure. Final whole-suite verification, actual full prepared artifact build, restoration/package proof, fresh final reviews and owner acceptance remain open.

## Matched validation-reuse result and repair stop

The uncontended matched hundred-document run retained exact package, input and isolated environment identities and checked source stability. Baseline capture/ingestion took 194.297 seconds, SQL publication 48.917 seconds and the combined boundary 243.214 seconds. The candidate took 188.643 seconds, 11.671 seconds and 200.315 seconds respectively. Candidate twenty-document capture cohorts took 4.199, 21.655, 30.613, 61.107 and 69.559 seconds. Both logs contained 1,889 events. These are plain timings, separate from profiler evidence. SQL improved substantially; increasing-history capture remains a blocker.

The Director ruled that the three-unsuccessful-cycle stop applies to the same capture-performance outcome: initial incremental repair, bank-witness repair and staged/healing reuse were distinct implemented hypotheses. Different amendment names and missing final qualification do not reset the limit. The acceptance-repair skill says, “Stop after three unsuccessful repair cycles.” No further product repair edits or unchanged full-794 attempt are authorized by the Director. One bounded read-only warm document-91 profile is allowed to establish the dominant remaining operation and concrete owner proposal. It is diagnostic evidence, not a new repair or acceptance pass. Unaffected validation continues.

The owner subsequently approved exactly one additional cycle of the concrete proposal below; the earlier stop and attempts remain recorded. Full 794-document import, final cohorts, prepared artifact build/restoration and final acceptance remain incomplete. No commit, installation replacement, release, push or merge is authorized. This ruling is persisted by the parent in the Director's name; it is not an owner approval.

The allowed warm document-91 diagnostic completed with unchanged source identity. It took 59.507 profiled seconds; direct `deepcopy` callers identify repeated prefix ownership in `PrefixProofIndex.events` (15.961 seconds), `PrefixProofIndex.__init__` (12.392 seconds) and `SourceIndex.__init__` (6.750 seconds). Whole-projection copying in nested staged callbacks accounted for only 1.822 seconds directly, so a source-only atomic API is not the recommended next repair. Profiler costs are diagnostic, not plain-time predictions.

The [one-cycle owned-evidence proposal](owned-evidence-repair-proposal.md) was independently fact-checked and explicitly owner-authorized for one additional cycle. It preserves public detached APIs and physical authentication, targets only redundant ownership acquisition inside sealed validators, and predeclares a 30% capture/final-cohort experiment threshold before one full build. The cycle has now completed and failed that timing gate; it is not an acceptance pass. Surface-contract, declared surface-impact, whitespace and 98 changed/new-path privacy checks passed before timing.

The first stabilized complete Python run finished with 39 failed, 7,086 passed and 92 skipped. Ten socket failures were classified as sandbox restrictions by a separate unchanged 42-pass elevated local-mock diagnostic. The [coverage repair](import-validation-coverage-plan.md) independently reviewed and repaired contract omissions, obsolete fixture boundaries and the current stale exact-source schema exception, preserving original failure evidence. Fresh affected verification passed 247 cases. The second unfiltered complete Python run passed 7,145 tests with 92 skipped and one expected duplicate-archive warning in 952.33 seconds. It used sibling private HOME/TMPDIR roots and valid local-socket permissions. Fresh independent review confirmed identical before/after source identities and zero changed files during the run. Evidence is retained in `runs/incremental-import/independent-review/coverage-python-{before,after,result}.json` and `coverage-python-final.log`. This prior-candidate Python gate pass does not verify the subsequent performance implementation or establish full sample, artifact or independent acceptance readiness.

## Additional owner-authorized cycle: failed timing gate

The owner directly selected “Authorize one additional cycle” for the sealed-evidence proposal; the Director fenced implementation before edits. The Builder stayed within five investment modules and two focused tests. Builder affected checks passed 483 cases. Fresh independent review passed 61 focused tests and 42 copied-loop/owned result-and-exception comparisons. The unfiltered product run retained one documentation-date failure, 6,870 passes and 92 skips with unchanged source. A date-only correction and fresh complete 23-test documentation closure left every product/test/script identity unchanged. The Director admitted the single measurement on that evidence continuity; no newly executed full-suite pass is claimed.

The uncontended candidate capture took **143.413591917 seconds** versus 188.642926750; the final twenty took **54.119981790 seconds** versus 69.559439251. Capture improved 23.976% and the last cohort 22.196%, below the required 30%. SQL took 10.563550417 seconds and combined capture/publication 153.977572750 seconds. Twenty-document capture cohorts were 3.200, 15.908, 23.018, 45.669 and 54.120 seconds, with the same 1,889 events and stable package identity. Evidence is retained in `runs/incremental-import/owned-evidence100-v1*` and `owned-evidence-cycle/timing-gate.json`.

**Earlier capture-repair checkpoint: stopped and incomplete.** Both capture thresholds failed, although total time improved. The one additional cycle is consumed. That campaign admits no further repair, profile, repeated measurement or full-794 build. The actual prepared artifact remains absent and its pin remains `unbuilt`; frozen restore/open/reopen and final acceptance remain unproved. Existing user vaults and installed application are untouched. No commit or merge had occurred at that checkpoint. The owner subsequently authorized publication of the accumulated source changes; that authorization does not reopen the stopped campaign or establish responsive real-vault scaling.
