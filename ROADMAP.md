# Roadmap

Directional, not a promise. Built in public, so this will change as reality
grades the theory. Each phase maps to the four jobs in the vision:
organize → explain → act → peace of mind.

For what is actually built, in detail, see
[docs/implementation-roadmap.md](./docs/implementation-roadmap.md).

## Phase 0 — Foundations ✅
- [x] Unified data model: one clean internal representation of accounts, transactions, holdings, and net-worth snapshots, regardless of source.
- [x] Document ingestion: read an arbitrary statement (PDF/image) the way a person would — no per-institution parsers.
- [x] Confidence + provenance: every extracted figure carries a source and a "how sure" signal. This gates everything else.
- [x] Local-first storage, encrypted, keys held by the user.

## Phase 1 — Organize & consolidate (now)
- [ ] Account connection (aggregation) alongside manual upload.
- [x] Transfer-linking so a card payment isn't miscounted as new spending.
- [x] A net-worth curve current through the available evidence, carrying its coverage and stale inputs.
- [ ] Breadth of instruments: five document types are read today; a full financial life produces closer to forty.

## Phase 2 — Explain & advise
- [ ] Ask-anything over the full financial picture, in plain language.
- [x] Obligations and quiet findings: expected payments, recurring charges,
  fees, anomalies, and trends appear in the picture; Viva never initiates and
  the product never notifies.
- [x] Current-period control: a bounded known remainder over held funds,
  carrying its horizon, assumptions, coverage, and caveats.
- [x] Honest-uncertainty surfacing in the desktop: figures and answers carry
  their grades, dates, coverage, caveats, and evidence into the interface.

## Phase 3 — Take action
- [ ] Durable conversation and correction: corrections and preferences persist
  and update the picture across sessions.
- [ ] Goals and plans: draft targets, contributions, payoff paths, and progress
  from stated assumptions without changing the person's records.
- [ ] Deterministic scenarios: compare affordability, runway, compounding, and
  payoff choices without turning a hypothetical into a plan.
- [ ] Drafted actions: show the exact proposal and its consequences, re-check
  its basis, and require explicit confirmation before anything irreversible;
  routine low-stakes upkeep is still reported.

## Phase 4 — Trust agent (the longer arc)

This phase begins only after the single-user product has earned trust in use.

- [ ] Verifiable credentials: cryptographically attested source data.
- [ ] Selective, permissioned disclosure (prove a fact without revealing the raw number).
- [ ] Counterparty flow: your agent answers a lender's agent, on your consent — the credit-bureau alternative.

See the [build log](https://orionviva.com/writing.html#build-log) for what's actually happening week to week.
