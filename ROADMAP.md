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
- [x] Always-current net worth and history.
- [ ] Breadth of instruments: five document types are read today; a full financial life produces closer to forty.

## Phase 2 — Explain & advise
- [ ] Ask-anything over the full financial picture, in plain language.
- [ ] Volunteered insight: recurring charges, fees, anomalies, trends.
- [ ] Honest-uncertainty surfacing in answers, not just internally. _(The answer path does this; the net-worth surface does not yet — its grade is currently a constant.)_

## Phase 3 — Take action
- [ ] Drafts budgets and payoff plans; keeps things categorized.
- [ ] Autonomous on routine, low-stakes upkeep; asks first on anything irreversible.

## Phase 4 — Trust agent (the longer arc)
- [ ] Verifiable credentials: cryptographically attested source data.
- [ ] Selective, permissioned disclosure (prove a fact without revealing the raw number).
- [ ] Counterparty flow: your agent answers a lender's agent, on your consent — the credit-bureau alternative.

See the [build log](https://orionviva.com/writing.html#build-log) for what's actually happening week to week.
