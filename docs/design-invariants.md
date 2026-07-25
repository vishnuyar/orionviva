# Design Invariants — the checklist every decision answers to

**Status:** Living · **Last updated:** 2026-07-20

## Why this doc

Some requirements are cross-cutting: they belong to no single feature, so they're exactly the ones forgotten when deep inside one. This is the standing checklist. **Every new design doc, ADR, or feature spec states — explicitly — which of these it touches and how it honors them.** Silence about a relevant invariant is a review failure, not an oversight. New invariants are added by deliberate decision, with a dated entry.

## Trust invariants (from ADRs 001–010)

- **T1 — Provenance + confidence on every figure.** No number without a source pointer and a verification grade. (ADR-008 promise 1–2)
- **T2 — Arithmetic is deterministic; models never certify.** (ADR-010)
- **T3 — Capture-first.** Originals and model I/O written before anything parses them; nothing trust-relevant is ever discarded. (ADR-003)
- **T4 — Everything is an event.** State is a projection of the append-only, anchored log; the log assumes multiple writers (devices). (ADR-004, multi-device doc)
- **T5 — No plaintext phase, anywhere, ever** — including tests, fixtures, debug output. (ADR-005)
- **T6 — Nothing leaves silently.** New outbound bytes of any kind are a *decision* (ADR + promise check), never an implementation detail. (ADR-006)
- **T7 — IDs are permanent; fingerprints are versioned.** (ADR-007)
- **T8 — Models are pinned, provider-swappable, and never trusted** — access modes: bundled local, OAuth-brokered, BYOK, future attested-cloud. (ADR-001, model trust policy, adoption doc)
- **T9 — The personal/impersonal boundary is drawn at package edges (added 2026-07-24).** Shared-knowledge packages (e.g. `merchantcore`, the format commons) may hold and share only *impersonal* data — merchant knowledge, format knowledge — never personal financial data. What crosses the product → such a package must be impersonal by construction (a normalized merchant key + a privacy-linted example; a format profile) — never amounts, dates, accounts, or PII descriptors. The unencrypted-safety of a shared catalog is a *consequence* of this boundary, not an exception to T5. (merchantcore-package.md, format-commons.md)

## Internationalization invariants (added 2026-07-20, standing directive: never lose these while deep in other features)

- **I1 — Currency is first-class.** An amount is always (value, currency) — never a bare number. No field, schema, computation, or display assumes USD.
- **I2 — Normalization is locale-aware and versioned.** Number formats (1.234,56 · 1,23,456 lakh grouping · 万 units), date formats (the 03/04/2025 trap), negative conventions (parentheses, DR/CR) are handled by explicit, versioned, deterministic rules — and when locale can't be determined from context, the figure grades `conflicted`, never guessed (T1 applied to locale).
- **I3 — Trust is earned per locale.** Model autonomy scorecards are keyed (model, document type, **locale**). Proven-in-US says nothing about Germany. Viva's capability honesty extends to regions: "I haven't been proven on documents from this country yet."
- **I4 — Ground truth carries locale metadata from day one.** Every answer-key figure stores raw-as-printed form + normalized value + locale + currency. (Raw-capture doctrine applied to benchmarks — cannot be retrofitted.)
- **I5 — No US-shaped taxonomy.** Account types, tax concepts, and document categories in the data model must be extensible to non-US instruments (ISAs, provident funds, passbooks) without migration pain.
- **I6 — The admission exam is pack-extensible.** Regional benchmark packs run through identical machinery; real statements are never committed (synthetic packs, or contributors verify locally and share scorecards only). International expansion is evidence-gated, not promised.

## Accounting-model invariants

- **M1 — Cash-flow over accrual, when in doubt (added 2026-07-24).** The ledger records *realized* cash events — money that moved, which is what is tax-relevant and independently verifiable. Accrual/paper figures (unrealized gains, mark-to-market revaluation) are **never posted, never reconciled as ledger facts, never events**; they are *derived, as-of-date presentation views* computed from the measurements on hand, always carrying their date and valuation class (X2). Rationale: the thesis (clean data is *measurements, not generations*) — posting a price change that wasn't a cash movement fabricates an event that never happened; keeping the ledger cash-flow keeps it aligned with reality and with tax. When a modeling choice is ambiguous, prefer the cash-flow reading. (positions-and-investments.md)

## Experience invariants

- **X1 — Target user skill: "can install an app."** No feature may require self-hosting, terminals, or knowing what an API key is on the default path. (Adoption doc)
- **X2 — Uncertainty is visible, never decorative.** Confidence language in any surface maps 1:1 to verification grades. (Extraction doc)
- **X3 — Irreversible actions wait for an explicit yes**, enforced in code, not prompts. (Promise 8)

## How to use this doc

At the top of every future ADR and design doc: an "Invariants touched" line (e.g., *"Invariants: T1, T4, I1–I2, X2"*). During review, ask of each proposal: which invariant does this strain? A proposal straining none is either trivial or under-examined.
