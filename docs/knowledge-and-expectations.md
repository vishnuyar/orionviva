# Knowledge & Expectations — where the domain rules live

**Status:** Draft · **Last updated:** 2026-07-20 · **Origin question:** how does OrionViva *know* to ask for 401(k) statements after seeing a pay-stub contribution, or an escrow analysis after a mortgage statement? Where do such rules sit?
**Invariants touched:** T1 (inferred accounts/expectations are graded, cited claims), T2 (expectation evaluation is deterministic), I5/I6 (knowledge is jurisdiction-tagged data, community-extensible packs), X2 (unmet expectations are visible quiet state, honestly labeled inferences)

## The reframe

These "rules" are not instructions for reading documents (parsers — banned, models read). They are **expectations about what exists in the world and how it relates** — completeness knowledge. And expectations are just another kind of claim, so they flow through the trust machinery already built: proposed → graded → confirmed by evidence or the user → enforced deterministically.

## Three tiers

### Tier 1 — Mechanisms (code, verify/-grade, ~5 total, universal)

The gears, true everywhere forever, knowing nothing about any document type:

- Every account carries an expected document cadence; gaps are computable (`check_completeness`).
- Every recurring flow to/from an external destination implies a counterpart account exists.
- Every inferred entity carries a grade and a source, like any fact.
- Expectations have states: `unmet` → `satisfied` (document arrived and linked) / `dismissed` (user said no) / `expired` — all as events.
- Satisfaction is deterministic matching (the arriving document links by account/fingerprint), never model opinion.

### Tier 2 — The knowledge registry (data: versioned, shipped, extensible)

Declarative, jurisdiction-tagged entries — a table, not a codebase:

```yaml
- given: {doc_type: mortgage_statement, jurisdiction: US, has: escrow_line}
  expect:
    - {doc_type: escrow_analysis, cadence: annual}
    - {doc_type: form_1098, cadence: annual, season: tax}
- given: {doc_type: pay_stub, has: retirement_deduction}
  expect:
    - {account_kind: retirement, evidence: deduction_line}
    - {doc_type: retirement_statement, cadence: quarterly}
- given: {account_kind: brokerage, jurisdiction: US}
  expect:
    - {doc_type: brokerage_statement, cadence: monthly_or_quarterly}
    - {doc_type: form_1099, cadence: annual, season: tax}
```

Properties that keep it on the right side of the anti-goal line: entries state what exists and relates — never how to parse anything; they're versioned like normalization rules; jurisdiction tags make a German or Indian entry set a **knowledge pack** (the I6 pattern for the third time — benchmark packs, taxonomy, now knowledge); and the registry ships small, growing from tier 3 confirmations and community contributions rather than from anyone's attempt to foresee finance.

### Tier 3 — Model world knowledge (runtime suggestions, never silent facts)

At ingestion, the understanding model may propose expectations beyond the registry ("solar loans typically issue annual interest statements"). These enter as *expectation claims*: low-grade, cited to what prompted them, surfaced quietly. Confirmation — by the user, or by the predicted document arriving and linking — promotes them into **personal knowledge** (memory events, the moat). Personally-confirmed patterns that are plausibly universal become upstream candidates for the shared registry (a community contribution, reviewed like any PR). The model proposes; the registry remembers; tier 1 enforces.

## The flow, concretely (the two motivating examples)

**Pay stub → 401(k):** extraction finds deduction "401K FIDELITY $750" → tier 1: recurring external flow ⇒ counterpart account → tier 2: retirement deduction ⇒ retirement account + quarterly statements → ledger gains an **inferred account** (grade `unverified`, source: pay stub line, cited) + an unmet expectation → dashboard coverage map, quietly: "401(k) at Fidelity — inferred from your pay stub; no statements yet" (no ping; speak-only-when-spoken-to) → statement uploaded later links, inference graduates, expectation becomes cadence.

**Mortgage → escrow analysis:** mortgage statement shows escrow line → registry ⇒ expect annual escrow analysis + 1098 → coverage map carries both with due windows → tax season's "mortgage interest?" answer can honestly say "…and your 1098 hasn't been seen yet."

**The pattern: documents are evidence that other documents exist.** The knowledge layer turns every arrival into a checklist for the rest of the financial life — job 1 (organize & consolidate) becomes *pursued*, not passively received, without nagging.

## Where it sits in the product

A component between the pipeline and the ledger — the **expectations engine**: consumes newly verified facts, consults registry + personal knowledge + tier-3 suggestions, emits expectation events. `check_completeness` (toolset) reads expectation state; the dashboard coverage map renders it; Viva mentions it only when spoken to. No new agent tool needed — the twelve-verb surface holds (the scaling law survives its first test: a whole new subsystem, zero new tools).

## Boundaries (what this layer must never become)

- Never a parser: no entry may describe how to read a document.
- Never a nag: unmet expectations are dashboard state, period (the no-interruption rule).
- Never silent: an inferred account is always visibly labeled as inferred with its evidence; it never quietly becomes real without linkage or confirmation.
- Never load-bearing for money math: expectations affect completeness honesty, not balances.

## Open questions

- Registry seed size for v0: just the document types in the v1 corpus (~7 types' worth of entries) — resist encyclopedism; the tiers grow it.
- Upstreaming mechanics: how a personally-confirmed tier-3 pattern becomes a registry PR without leaking personal detail (entries must be generic by construction).
- Dismissal semantics: "I don't have a 401(k) anymore" — expectation dismissed *and* remembered so it doesn't resurrect from the next pay stub (memory interplay).
