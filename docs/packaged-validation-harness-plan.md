# Current sample protocol in packaged validation

**State:** controller repair implemented with supporting tests; frozen packaged-artifact qualification pending
**Rules:** none

## Goal and classification

Restore the product-owned packaged validation journeys to the current sample protocol while preserving their acceptance strength. This is a qualification-tooling failure: it does not authorize a product workaround, a changed financial oracle or weaker deadlines. The [import plan](import-performance-plan.md) still requires a complete 794-document build, artifact restoration and independent acceptance. This document establishes none of those passes.

The affected tools are `scripts/validate_packaged_artifact.py` and `scripts/validate_sidecar_lifecycle.py`. Changes to independent evaluator code, assertions, evidence requirements or qualification contracts are excluded.

## Source reproduction and stale assumptions

The packaged validator's top-level `validate` calls `bridge.open_demo_vault` before preparing a sample. The lifecycle tool's `probe(create=True)` does the same. Current `viva.demo.open_demo_vault` delegates to `sample.activation.open_ready`, which rejects a sample that has not completed preparation. Current activation requires `bridge.sample.prepare`, bounded `bridge.sample.status` polling, then open. This mismatch is reproducible from the call paths without treating an unprepared-open refusal as evidence that the prepared snapshot is defective.

Both tools already isolate a disposable home and omit configured model credentials. Keep those protections. Preparation must consume the packaged artifact through the packaged process; importing product code into the controller or substituting a source worker would not prove delivery.

The lifecycle tool sets `VIVA_DEMO_HOME` to `home/vault`, then snapshots and reopens that directory as if it directly contained canonical files. Current activation instead stores its active pointer under `home/vault/versioned` and selects `sample-vaults/<version>/<instance>/vault` beneath it. Resolve the fresh pointer once after first preparation and retain that exact canonical root for all candidate, rollback and reinstall probes. Preparing a fresh sample for each executable would invalidate the existing unchanged-vault proof.

The packaged validator hardcodes `acct:everyday-checking` for its account-ledger read. That identifier belongs to the older tiny sample and is not a public account-identity contract. Select a nonempty opaque identity from an authenticated, current packaged account surface and require the account-ledger response to belong to that selected identity. Do not invent an identifier, import the source projection to choose one or silently skip this surface.

The validator additionally requires the sample to supply an actionable Review question. A financial sample is not contractually required to contain unresolved work. Retain `_review_conversation_ids` and all of its shape, ordering, semantic binding and count assertions when comparing sample surfaces, allowing a genuinely empty but internally consistent pair. Keep the separate eleven-document synthetic pagination fixture and its exact eleven identities, beyond-ten action, refreshed ten identities and order unchanged. This fixture already owns the nonempty actionable/pagination oracle independently of incidental sample contents.

The fixed Spending read date lies after the current source interval. This can validly produce empty or unavailable coverage, both already handled by `_spending_contract`; it is not grounds to weaken coverage assertions. Retain the entire closed Spending contract, chart invariants, exact authored controls and count/coverage consistency checks. If an in-range scenario is added, its date and expectation must be tied to the declared synthetic source contract, not selected because the current result passes. Do not invent expected spending totals, category composition, Review counts or account names.

Other existing top-level checks remain meaningful: protocol identity, meaningful revision, packaged origin, sample flag and fictional frame, all declared surface responses, synthetic pagination actions, undeclared-operation refusal, executable hashes, distinct-artifact versus same-artifact labeling, clean shutdown, canonical-byte preservation, application removal and baseline rollback/reinstall. Preserve them. A sidecar check is still not installation, signing, native UI or independent browser evidence.

## Recommended minimal repair

Update only these product-owned controllers and narrowly affected controller tests. Reuse the real stdio request/reply protocol, request correlation and progress handling. Prepare only the initial disposable sample, poll the closed status until ready or failed, then open it. Treat failed, malformed or timed-out status as failure and retain that disposition; do not retry preparation to select a passing result.

For lifecycle validation, validate the controller-owned pointer's exact closed fields, version, bounded instance identifier, containment and ordinary nonlinked path before locating canonical files. Do not ask the source package where the artifact stored them. Bind the selected root before taking the initial canonical snapshot and retain it across all binary replacements. Reopen that root through ordinary `bridge.open_vault(create=False)` for candidate, rollback and reinstall. A missing pointer/root or byte change is failure; never silently create or choose another instance.

Retain the existing 90-second lifecycle reply and SQL-readiness limits and the required 90-second prepared readiness/open/reopen boundary. A polling phase has one monotonic deadline; repeated polls must not restart its budget. Bound each blocking reply by the smaller applicable remaining budget so one reply cannot overrun the enclosing deadline. The packaged validator's current `Sidecar.ask` blocks on `readline` without a reply deadline; adding a real bounded reader is necessary to enforce the existing campaign boundary, not permission to lengthen it. Preserve request correlation and ignore only valid progress frames.

The alternative is a separate retained protocol controller leaving the old validators explicitly unqualified. It could establish a narrow restore/open result but would duplicate long-lived tooling and would not make legacy validator claims true. Prefer repairing the two owned journeys under this reviewed fence.

## Checklist and evidence

- [x] Independently confirm every stale assumption and the current product contract; obtain Director scope ruling before controller source edits.
- [ ] Retain the original source-path mismatch and a deterministic failing controller reproduction, using a bounded fake sidecar if the complete artifact is not yet built. Preserve any actual packaged failure separately; never relabel it as a product pass.
- [ ] Prove prepare/status/open order, failure propagation, immutable overall deadlines, progress correlation and shutdown without changing the packaged product to satisfy the harness.
- [ ] Prove current account selection still exercises account-ledger and empty Review remains fully cross-checked; retain all Spending and eleven-document pagination assertions.
- [ ] Prove pointer traversal/link/malformed-root rejection and that candidate/rollback/reinstall reuse one exact root. Simulated or actual canonical-byte mutation must fail the unchanged-bytes gate.
- [ ] Run the repaired controllers on exact frozen artifact bytes after the complete sample build. Record executable identities, original and repaired failure dispositions, prepare-to-usable and reopen timings, canonical source hashes before/after and mode distinctions.
- [ ] Obtain independent review of changed tools and tests. Full sample, packaging, browser acceptance and owner ship gates remain separate and open until established.

No product sources, independent evaluator assertions, financial source data, security controls, deadlines or evidence requirements may change under this amendment. Passing a controller simulation does not establish a packaged-artifact pass.

## Director ruling — Checkpoint 1

The Director approved the bounded packaged-validation tooling repair after reviewing this brief at SHA-256 `e786265fd4f139fee01cbf38a18b5c05709b4e5269dd314178ad46725eefcbb3` and the independent factual report at `runs/incremental-import/packaged-harness-factcheck/report.md`. Controlled reproductions establish stale operation ordering and canonical-root assumptions, not an actual packaged-artifact result.

Approved changes are limited to `scripts/validate_packaged_artifact.py`, `scripts/validate_sidecar_lifecycle.py`, and narrowly affected controller tests. Prepare the first disposable sample through the packaged process, poll with one enclosing deadline, then open. Failed, malformed or timed-out status fails without outcome-selecting retries. Resolve and validate the closed versioned pointer once and bind its exact ordinary contained canonical root before snapshotting. Candidate, rollback and reinstall must reopen it with `create=False`; never select or prepare replacements.

Discover a nonempty opaque identity through the current packaged account surface and require account-ledger `scope.account_id` to match. Missing identity fails without skipping. Allow a genuinely empty sample Review pair only with complete consistency checks. Preserve the eleven-identity pagination fixture, beyond-ten action and exact remaining-ten ordering, and all Spending, protocol, identity, packaged-origin, fictional-frame, surface, refusal, hash, shutdown, lifecycle-mode and canonical-byte assertions.

Enforce existing lifecycle reply/readiness limits and the required **90-second** prepared-ready/open/reopen boundary. Polls cannot restart it and blocking replies respect remaining time. Demonstrate baseline failures, corrected sequencing, timeout/malformed-frame handling, request correlation, pointer/link/traversal rejection, exact-root retention and canonical-byte mutation failure. Simulations are supporting evidence; frozen qualification after the full sample build remains required.

No product sources, independent evaluators, financial oracles, private vaults, deadlines or acceptance requirements may change under this ruling. Browser, native installation/signing, full-sample and owner gates remain separate. Public runtime-path sanitization is outside this fence and requires a separate bounded proposal. No commit, installation replacement, release, push or merge is authorized. Persisted by the parent in the Director's name; the Director remained read-only.
