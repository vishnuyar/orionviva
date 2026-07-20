# ADR-006 · Zero Exfiltration by Default; Diagnostics by Manual Export Only

**Status:** Accepted · **Date:** 2026-07-19 · **Decided by:** Vishnu (diagnostics posture) · **Door type:** one-way in trust (the first silent byte breaks the promise permanently)

## Context

There is no hosted backend: OrionViva is an app each person runs on their own machine; the project hosts only the website and the code. The only data that ever leaves a user's machine is the user-initiated model traffic under ADR-001. The open question was diagnostics — the traditional first crack through which "just telemetry" grows.

## Decision

Nothing transmits itself, ever. No telemetry, no analytics, no update pings carrying identifiers, no crash reporting endpoint — the receiving infrastructure is not built, so the temptation has no object. Diagnostics: errors log locally; a user wanting help generates a diagnostics bundle, can read exactly what it contains, and sends it themselves (email, GitHub issue). The product can always display a complete, plain-language account of everything that has ever left the machine, and to whom (in practice: model API calls under the user's key, and 32-byte anchor hashes per ADR-004).

## Alternatives considered

**Opt-in automatic crash reporting** — conventional, eases remote support at scale. Rejected by decision: it creates the project's first user-data-receiving infrastructure, and off-by-default settings have a documented tendency to creep toward on-by-default; D4 exists to prevent exactly that ratchet.

**Privacy-preserving aggregate telemetry** (differential privacy etc.) — sophisticated, and still a stream of bytes leaving machines by default; the promise "nothing leaves" is legible to a non-technical user in a way "ε-differentially-private aggregates leave" never will be. Trust must be *verifiable by the person extending it*.

**No diagnostics at all** — purist but self-defeating; unsupportable software gets abandoned, and abandonment is also a trust failure.

## Consequences

Remote debugging of future non-author users is deliberately harder; the eval harness (the discovery map, A8) and reproducible local logs must compensate. The "what has ever left this machine" ledger is a UI requirement, not a policy page. Update checks (when packaging exists) must be designed identifier-free.

## Would reverse this

Nothing reverses the default. A future *user-initiated, per-incident* transmission convenience could be added if it remains explicit-action-only.
