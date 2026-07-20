# Discovery Plan

**Status:** Draft · **Last updated:** 2026-07-19

## Purpose

We are deliberately in a discovery/research phase before writing product code. The goal is to make the expensive decisions (data model, extraction architecture, storage, stack) with evidence rather than momentum. Speed is not the constraint; being right about the load-bearing choices is.

## Phases

**Discovery (now).** Map the landscape: agent frameworks, model capabilities, competitive products, storage/crypto options. Output: the research docs, each with findings and open questions.

**De-risking experiments (next).** The questions that can't be settled by reading get settled by small, throwaway experiments before any product code:

1. **Extraction benchmark** — take 10–20 real statements (author's own, per "first user is the author"), run cloud frontier models vs. the best local VLMs, measure per-figure accuracy and whether stated confidence correlates with correctness. This is the single most important experiment: it grades the hybrid model strategy (ADR-001) and tells us whether local-only is viable sooner than assumed.
2. **Data model spike** — attempt to represent the author's real accounts (bank, cards, brokerage, retirement, loans, property) in one schema; find where the abstraction leaks.
3. **Provenance round-trip** — extract a figure, store it with source + confidence, answer a question citing it, and click through back to the exact source region of the document. If this loop works end-to-end for one number, the architecture is sound.

**Architecture & build plan.** Only after the experiments: pick stack and form factor (the form-factor doc graduates to an ADR), write the v0 architecture doc, start Phase 0 of ROADMAP.md.

## Decisions made so far

- **ADR-001 — Hybrid model strategy** (amended with the domain-model doc specialization flywheel).
- **ADR-002–010 — the one-way doors** (the discovery map): MIT license, raw capture doctrine, append-only anchored event log, encryption from commit one, zero exfiltration, hybrid record identity, promise inventory, DCO, verification-never-in-weights. Full index: [decisions/](decisions/README.md).

## Open questions register

| # | Question | Where it's being worked | Settles when |
|---|---|---|---|
| Q1 | Can any model give *calibrated* per-figure confidence on messy statements, and by what mechanism? | the extraction doc | Extraction benchmark |
| Q2 | Form factor: CLI, local web, or native desktop for v0? | the form-factor doc | After experiments (informed by stack choice) |
| Q3 | Language/stack: Python vs TypeScript (vs Rust core)? | the form-factor doc | After experiments |
| Q4 | Agent harness: Claude Agent SDK vs direct API loop vs framework? | the agent-landscape doc | Architecture phase |
| Q5 | Storage: SQLCipher vs SQLite + file-level encryption; key custody UX | the storage doc | Architecture phase |
| Q6 | How do Era/OpenBudget-style MCP aggregators change positioning — threat, complement, or distribution channel? | the competitive-landscape doc | Ongoing; revisit quarterly |
| Q7 | Account aggregation (Plaid/MX/SimpleFIN) vs document-only for Phase 1 — privacy cost vs coverage | the competitive-landscape doc, future doc | Before Phase 1 |
| Q8 | Local model floor: at what point do on-device VLMs make local-only extraction honest to offer? | agent-landscape + extraction docs | Extraction benchmark, re-run periodically |
| Q9 | Specialization flywheel: how many verified extraction pairs before a personal LoRA beats frontier on the user's own formats? | the domain-model doc | Extraction benchmark baseline, then accumulation |
| Q10 | River AI trajectory: does auditable parametric personalization become viable? | the domain-model doc | Ongoing watch |

## Scope note

This plan covers the *current* discovery tracks. The full-scope inventory — every domain needing discovery, and the classification of decisions by reversibility (one-way / sticky / two-way doors) — lives in [the discovery map](discovery-map-and-reversibility.md), which is the master map. The discovery map's sequencing section supersedes the phase list above where they differ.

## Cadence

Landscape docs (01, 04) get refreshed when something material changes — new model generations, new entrants — not on a schedule. The register above is the heartbeat: a question leaves it only via an ADR or an experiment result.
