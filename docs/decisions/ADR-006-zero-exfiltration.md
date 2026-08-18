# ADR-006 · Zero Exfiltration by Default; Diagnostics by Manual Export Only

_This records reasoning, not current behaviour._

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu (diagnostics posture) · **Door type:** one-way in trust (the first silent byte breaks the promise permanently)

**State:** partial
**Rules:** ADR-006
**Invariants touched:** T6

## Rules

### ADR-006 — Nothing transmits itself, and diagnostics leave only by the person's own hand
**State:** by-review-with-exception
**Code:** core/vivacore/models/openai_compat.py:76 · core/vivacore/models/anthropic_adapter.py:64
**Test:** none

1. There is no telemetry, no analytics, no update ping carrying an identifier and no crash-reporting endpoint; the receiving infrastructure is not built, so the temptation has no object.
2. Errors log locally. A person wanting help generates a diagnostics bundle, can read exactly what it contains, and sends it themselves.
3. The product can always display a complete, plain-language account of everything that has ever left the machine and to whom.
4. Update checks, when packaging exists, are designed identifier-free.

**Exception:** assertions 2 and 3 have no implementation. Nothing in the tree generates a diagnostics bundle, and no surface enumerates what has left the machine; `product/viva/surface/capabilities.py` registers developer diagnostic reports, which are engine tooling rather than the person-facing outbound record.

## Why

There is no hosted backend: OrionViva is an app each person runs on their own machine, and the project hosts only the website and the code. The only data that ever leaves is user-initiated model traffic under ADR-001. The open question was diagnostics — the traditional first crack through which "just telemetry" grows.

**Opt-in automatic crash reporting** is conventional and eases remote support at scale. It was rejected by decision because it creates the project's first user-data-receiving infrastructure, and off-by-default settings have a documented tendency to creep toward on-by-default. This decision exists to prevent that ratchet.

**Privacy-preserving aggregate telemetry** is sophisticated and is still a stream of bytes leaving machines by default. The promise "nothing leaves" is legible to a non-technical person in a way that a differential-privacy guarantee never will be, and trust must be verifiable by the person extending it.

**No diagnostics at all** is purist and self-defeating: unsupportable software gets abandoned, and abandonment is also a trust failure.

The cost is accepted knowingly. Remote debugging of future non-author users is deliberately harder, and the eval harness plus reproducible local logs are what must compensate. The "what has ever left this machine" ledger is a product requirement rather than a policy page.

## Would reverse this

Nothing reverses the default. A future user-initiated, per-incident transmission convenience could be added if it remains explicit-action-only.

## Open

- No diagnostics bundle exists, so a person needing help has no supported way to produce one.
- No surface shows what has ever left the machine, so promise 4 rests on the absence of code rather than on something a person can read.
