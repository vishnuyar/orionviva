# Personal beta readiness

The first release is a personal financial vault: bring statements together,
understand the recorded money, and inspect the sources behind an answer.
Institution-facing credentials, credit checks, issuer signatures and shared
proof infrastructure remain future work.

A private beta is ready when a new person can install the intended artifact,
create a vault, import a statement, understand its reading/review result, ask a
supported question, inspect its evidence, and recover an encrypted backup
without developer assistance. A source build or a green unit suite alone does
not establish that result.

## Recovery improvements

Welcome now offers **Restore a backup** without requiring another open vault.
Restore uses the existing encrypted archive format and verifies its ciphertext,
event chain and original documents in private staging before publishing the
recovered folder. Verification failure leaves the intended destination
retryable. Occupied destinations and concurrently arriving files are refused.
The submitted phrase is cleared; opening the recovered vault is a separate,
explicit action that asks for the phrase again.

Browser vault transitions drain already-sent bridge work and reject new bridge
requests while the transition is pending. Rejected work is never replayed
against the next vault. The host distinguishes current-vault contention from
a stale vault identity; stale requests and ended browser access remain fenced.

## Evidence still required before inviting users

| Journey | Required evidence |
| --- | --- |
| Installation | Signed intended artifact; clean supported-machine launch, update, rollback and uninstall with vault preserved. App-only bundling does not prove installer delivery. |
| First use | A representative person completes the sample, setup and first-statement journey without coaching; keyboard and assistive-technology checks remain part of acceptance. |
| Statement import | Current-candidate browser verification against independent source records, including held/refused/duplicate outcomes and review persistence. Preserve the existing campaign's unresolved dispositions. |
| Answers | Exact-candidate model qualification, truthful source/coverage/refusal behavior and the retained-vault financial-question campaign. Deterministic calculations alone do not qualify a live model. |
| Recovery | The synthetic production-browser roundtrip exercises wrong-phrase retry and explicit restored-vault opening; backend tests check occupied destinations and original integrity. Save-file, open-file and folder choosers are implemented, including cancellation without submission. Installed-artifact dialog behavior still requires its own evidence. |

## Current verification

The save-file chooser is available in the native and browser hosts. Trust offers
backup destination, archive and restore-folder selection. Selecting a path only
fills its field; cancellation submits nothing and writes nothing. Focused chooser
and recovery checks passed 138 tests; native checks passed 27 tests and the
synthetic production-host suite passed 19 checks. The shared interface passed
1,086 tests, its production build, 155 architecture checks and 66 style checks.
These measurements cover the tested implementation; later documentation edits
require a fresh candidate identity for whole-product acceptance.

The frontend dependency repair pins Vite 8.2.4 and Vitest 4.1.12. The measured
npm audit findings fell from five to zero. This is dependency-audit evidence,
not proof of signed delivery or an end-to-end financial answer.

## Independent evaluator boundaries

The independent evaluator lives outside this product repository. Its welcome
journeys have been updated for the dedicated welcome screen. The default
complete command is provider-free and does not run model quality. Live model
execution requires explicit opt-in and explicit settings/environment paths;
ambient private configuration is not permission to call a provider. A failed
child with no retained meter still cannot prove that it made no calls.

The preserved qualification corpus contains 123 independent financial oracles
and 93 expected figures. Its current-schema offline port passed all 123 cases
and twelve controls. Those checks exercise deterministic downstream behavior;
they do not establish live model interpretation, exact hosted-runtime admission
or completion of the seventeen financial browser cases. Those remain unverified.
The serial provider-free browser run passed five journeys: first open, sample
financial integrity, current period, keyboard navigation and privacy. Its seven
oracle checks passed on the frozen runtime/dependency identity
`e05d3a3+worktree.25cc65f90d6a`. This does not execute the seventeen additional
financial browser cases. The complete evaluator result is recorded below. Independent budget-gate
regressions pass, including invalid ceilings and invalid provider cost receipts;
the complete run still reports insufficient release evidence.

The original campaign budget and spending/hold records remain in force. The
reviewed retained-document campaign runner is missing and must be restored and
authenticated before resumption. No paid model call was made in this cycle.
Provider/data authority, existing spending and holds must be reconciled before
any separately authorized live run. Preserve failed and incomplete evidence;
missing reports are never passes.

Use [the acceptance policy](../acceptance/README.md),
[the retained-document continuation](../acceptance/real-document-test.md) and
[the release procedure](../RELEASING.md) for their respective gates. This page
changes neither the model-admission rules nor release/publication authority.

## Complete local acceptance result

The provider-free complete run on `e05d3a3+worktree.b859fe7983ae` reports
**nine passes, zero failures and nineteen gaps** across 28 declarations. The gaps
are seventeen unmapped financial browser cases, live model quality and signed
clean-machine compatibility. Zero model calls were made. Catalog, performance,
stateful learning and all five browser journeys pass. This result remains an
acceptance gap, with insufficient evidence for invitations. The local report is
`runs/user-readiness-2026-10-24/complete/trace.report.md`. Later status-prose edits
leave the tested executable/dependency/source contract unchanged and do not
rewrite the report identity.
