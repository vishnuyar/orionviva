# Data Model Considerations — what the unified model must account for

**Status:** Draft — the thinking that guides experiment 2 (data model spike); the spike's findings graduate this into the architecture-phase data model ADR · **Last updated:** 2026-07-20
**Invariants touched:** T1, T3, T4, T7 (the trust spine below is their schema form), I1 (currency on every amount), I2 (locale-driven normalization feeds the claims layer), I5 (no US-shaped taxonomy — jurisdiction as attribute, never as table), X2

## The pipeline, refined

The working pipeline sketch — classify → extract → verify (per type) → data layer → queried by tools; document retained for provenance — is correct with two refinements:

1. **Classification is a claim, not a fact.** Document type comes from a model, carries confidence, and can be wrong. Misclassification must degrade to *visible conflict* (wrong checks fail loudly), never silent corruption. `unknown` is a first-class type: generic claim extraction still runs, fewer checks apply, and answers standing on such documents say so (X2). Which checks run per type is a **registry (data/config), not code** — new document types and new regional variants are additions to a table, not releases.
2. **Three layers, not one data layer:**
   - **Claims layer** — what models asserted, verbatim, per run (model version, prompt version, source regions). Immutable, append-only. This is also the flywheel's training-pair mine.
   - **Facts layer** — what survived verification: canonical, typed records carrying grade (`verified` / `corroborated` / `unverified` / `conflicted`), the verification trail (which checks, what results), and provenance pointers (document → page → region).
   - **Projection layer** — query-shaped views (`query_ledger`'s world): accounts, transactions, positions, net-worth series, spending by tag. **Rebuildable at any time from the event log.** This is what dissolves the "comprehensive from day one" pressure: comprehensiveness lives in what events *capture* (raw capture doctrine); projections expose what we've so far chosen to model, and can be re-derived richer later.

## The core ontology — small, closed, universal

Finance everywhere reduces to ~10 primitives. Regional variety is **attributes on primitives, never new primitives** (I5):

| Primitive | Covers | Regional note |
|---|---|---|
| **Party** | user, household members, institutions, merchants, employers | Unicode names, script-aware matching |
| **Account** | any value-holding or obligation relationship: depository, credit, investment, retirement, loan/mortgage, insurance policy | 401(k)/EPF/ISA/superannuation = retirement-kind + jurisdiction tag; kind+subtype registry is data |
| **Asset** | securities, property, vehicles | valuation source matters (see measurements vs valuations) |
| **Transaction** | money moved: amount **(value, currency)**, date(s), direction, counterparty, description raw+normalized, tags | multi-currency transactions carry both legs |
| **Position** | holding of an asset at a moment | units + instrument identity |
| **BalanceSnapshot** | account value at a moment, as attested | always dated; never silently "current" |
| **Obligation** | recurring/scheduled promises: bills, premiums, EMIs, minimums | cadence + due rules; feeds `list_obligations` and completeness |
| **Provision** | non-numeric attested facts: coverage terms, loan conditions, plan rules | feeds `search_documents`; insurance is why this is core, not an afterthought |
| **Document / Claim / Fact** | the trust spine (below) | locale + currency on Document from ingestion (I4) |
| **Tag/Category** | the personal taxonomy: learned, corrected, hierarchical ("son" tag) | seeded minimal; grown from corrections (the moat) |

## The trust spine (what no PFM schema has, and we exist for)

- **Observations accumulate; they don't just dedup.** The same real transaction seen on an overlapping statement, a re-upload, or two document types (card statement + bank autopay) merges by fingerprint (ADR-007) into one fact with *multiple observations* — and corroboration raises the grade. Conflicting observations → `conflicted`, surfaced, never averaged.
- **Corrections are events on facts.** A fact's full history — model asserted, checks passed, user overruled — is replayable. Current value is a projection; nothing is overwritten (T4).
- **Transfer links are graded facts.** Checking→card payment is one economic non-event; the link entity carries its own confidence and its own evidence (amount/date proximity, description hints, eventually learned patterns). Wrong links double-count spending — this is load-bearing for job 1.
- **Completeness is data.** Accounts carry expected cadence ("monthly statement, ~5th"); gaps become one query (`check_completeness`), and every aggregate answer can state its coverage honestly ("Jan–Jun, May missing").
- **Bitemporality.** Two timelines per fact: when it happened vs when we learned it (event time — free from ADR-004 if respected from the start). Enables "what did I know on March 3rd, provably" — the trust trial needs it; Phase 4's vouching *requires* it.
- **Measurements vs valuations vs estimates.** A statement *measures* (attested by issuer, dated). A market price *values* (changes without documents). A property guess *estimates*. Three provenance classes; answers must never dress one as another. v0 is measurements-only: net worth is "as of your latest statements," honestly dated. Live valuations, if ever, enter as the labeled lower-trust feed (Q7 territory).

## Regional versatility, concretely (beyond I1–I6 restated)

- **Amounts:** (value, currency) always; account-level default currency but per-transaction override (foreign transactions on a US card). FX conversion happens at *answer time*, computed deterministically from a rate the answer must cite and date — converted totals are estimates by provenance class, and say so.
- **Jurisdiction on accounts** (not just locale on documents): tax treatment, retirement semantics, insurance conventions hang off it. US-only v0 populates it with "US" — the field existing is the point (I4 logic applied to accounts).
- **Calendars:** fiscal years differ (India: Apr–Mar; Japan: Apr–Mar); "this year" in a question is locale/jurisdiction-sensitive — an *answer-time* concern, but the schema must not bake calendar-year assumptions into stored aggregates (store atoms, aggregate at query time).
- **Statement conventions:** passbooks (running-balance lines, no period totals), DR/CR columns, combined multi-account statements — all handled by the claims layer being shape-agnostic (claims are claims) plus type-registry checks; no per-region schema.

## What experiment 2 (the spike) must stress with the author's real accounts

The known leak candidates — where clean ontologies meet messy reality:

1. **Escrow inside a mortgage payment** — one transaction, three economic destinations (principal, interest, escrow). Split-transaction support: one movement, multiple classified parts.
2. **Pay stub** — gross→net with deductions that are *also* other facts (401(k) contribution appears here AND on the 401(k) statement: two observations, one fact — the cross-document merge test).
3. **401(k) vesting** — owned vs vested: a position attribute or a provision? Spike decides.
4. **Joint accounts / household** — Party exists from day one so "wife's card" is representable; but v0 stays single-*user* (one human, one key) with multi-*party* data. The shared/household product is a later door the schema deliberately doesn't close.
5. **Insurance** — mostly Provisions + Obligations (premiums), almost no transactions: the test that the model isn't secretly transaction-shaped.
6. **Brokerage statements** — positions + transactions + income (dividends) + fees in one document; the densest cross-check surface and the best verification showcase.

## Consequences

- The type registry (document types → expected claims → applicable checks) is a first-class design artifact of the architecture phase, versioned like the normalization rules.
- `query_ledger`'s query language is the projection layer's contract — designed together with it (as the toolset doc noted).
- The claims layer's schema is already half-built: it is viva-bench's claim format, deliberately (the benchmark rehearses the product again).
- Event schema design (ADR-004's sticky consequence) now has its requirements list: multi-writer, bitemporal, observation-merging, correction-carrying.

## Open questions

- Whether Provision needs structure beyond (topic, text, source, grade) — or whether structured coverage modeling (deductibles, limits as typed amounts) earns its complexity. Spike + real policies decide.
- Category taxonomy seed: ship a minimal neutral seed vs start empty and learn everything. Leaning: minimal seed, aggressively overridable (the moat is the corrections, not the seed).
- Rate sources for FX at answer time (deferred until a non-USD account exists; the schema slot is what matters now).
