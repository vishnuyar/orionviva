# Categorization & Spending — where your money went, and the moat that learns it

**Status:** Implemented (Slice 5, core) · **Last updated:** 2026-07-24 · **Origin:** Every non-account leg today lands in `Uncategorized`, so "where did my money go?" is unanswerable — and a Slice-4 real-vault run showed the `Uncategorized` buckets are worse than empty: their sign is asset-centric, so a card *purchase* files as income. This slice makes the counter-leg honest, then turns each movement into a categorized, graded fact, and makes spending answerable. It is the first real *advice* (job 2), and the categorization stream is the moat — the same correction events that categorize your money are, later and for free, the training data that learns what a merchant is.

**Invariants touched:** T1 (a category carries provenance — the source line — and a grade), T2 (the counter-leg fix and any amount-split are deterministic and still balance), T4 (a categorization is an append-only correction event, movement-keyed, reversible — nothing overwritten, survives a reingest), I1 (amounts are `(value, currency)`), I5 (the category taxonomy is minimal, overridable **data**, never a US-shaped tree — jurisdiction is an attribute), X2 (a model-proposed category is a graded, visibly-unconfirmed claim). Principle 2 (a category we can't stand behind is shown as an unconfirmed suggestion, never asserted) and principle 7 (Core *suggests and asks*; it does not auto-apply) are load-bearing.

## The architecture (decisions locked with Vishnu, 2026-07-24)

**1. First job: make the counter-leg *kind-aware* (the Slice-4 real-data fix).** The `Uncategorized` counter-leg is currently chosen by the sign of the account leg, which is right for an asset and inverted for a liability. It becomes a function of `(kind, direction)`:

| account kind | direction | counter-leg |
|---|---|---|
| depository (asset) | money in (+) | `Income:Uncategorized` |
| depository (asset) | money out (−) | `Expenses:Uncategorized` |
| liability (card) | charge, owed ↑ (+) | `Expenses:Uncategorized` — a purchase **is** spending |
| liability (card) | payment, owed ↓ (−) | `Transfers:Uncategorized` — a debt reduction, funded by a transfer, **not** an expense |

This alone makes a real spending number possible (card purchases finally count; card payments correctly don't), and it's the prerequisite everything else sits on.

**2. A category is a *graded overlay* via correction-as-event — not a re-post.** `CategoryAssigned(movement_key, descriptor, category, grade, by)` is an append-only, reversible event keyed to the same stable movement key transfers use. The projection reads it and moves that movement's counter-leg out of `Uncategorized` into the category. Model-proposed = `unverified`; you confirm = `verified`; (later) a learned rule applied it = `corroborated`. It survives a reingest (content-keyed), never mutates the read, and reuses the correction spine and the overlay pattern from Slice 3 wholesale.

**3. Core is single-category, suggest-and-confirm.** One category per movement (the common case). The model proposes a generic bucket from its world knowledge (it already knows KROGER is groceries, SPECTRUM is utilities), graded `unverified` so spending is populated immediately but honestly; you confirm or override, which upgrades it to `verified`. Nothing is auto-applied in Core (principle 7). Amount-splits, the tags overlay, and learned auto-apply are deferred (see notes).

**4. The category taxonomy is data, and two-level (I5).** The **primary** set is **16 controlled buckets** (`merchantcore.taxonomy.PRIMARY_CATEGORIES` — the single source of truth, informed by an industry scan of Plaid's 16-primary PFC taxonomy), and a **subcategory** the model fills with value ("streaming", "warehouse club") for finer slicing (see [merchantcore-package.md](merchantcore-package.md)). Jurisdiction-neutral, overridable; a person may still assign anything. `spending_by_category` groups by primary; `spending_by_subcategory` is the finer slice — the first two of several slice-and-dice axes (tags and recurrence follow).

**5. The one thing Core must do for the future: capture the merchant descriptor.** Every `CategoryAssigned` event records the movement's raw descriptor (the merchant string, e.g. "AMZN MKTP US*RA30Z3BP0") alongside the category. This costs nothing now and buys the entire merchant layer later: merchant learning becomes a **projection over categorization events we already have** — no re-reading a document, no re-doing a categorization (see notes). The categorizing you do by using the product *is* the training signal.

## The spending projection

With counter-legs kind-aware and categories overlaid, `spending_by_category` (and by time, and eventually by merchant) is the sum of `Expenses:*` postings grouped by category, **excluding transfer-linked movements** (Slice 3 composes in). This is real spending — card purchases included — replacing the Slice-4 stopgap ("outflow from deposit accounts"). "Groceries in March" answers with a grade (how much of it is confirmed vs model-suggested) and provenance (the source lines). The honest envelope stays: a total made of `unverified` guesses says so.

## Autonomy — suggest, don't assert

The model's category is a claim, graded `unverified`, shown as a suggestion against the source — never asserted as fact. Your confirmation is the authoritative, `verified` event and the moat. This is the same forced/suggested discipline as reconciliation and transfers: the system proposes where it's useful, and the human ruling is what enters the trusted layer. In Core there is no auto-apply; a movement is either your confirmed category or a clearly-marked model suggestion.

## Implementation status (as built, 2026-07-24) — audit vs the invariants

- ✅ **Kind-aware counter-leg (the first job).** `ledger.postings.counter_account(kind, amount)`: a card purchase → `Expenses:Uncategorized`, a card payment → `Transfers:Uncategorized`, never income. Threaded through the pipeline's postings. Fixes the Slice-4 sign inversion. _Retroactive for free: the user-facing aggregates (`spending_by_category`, `income_by_currency`) re-derive from the immutable **movement** legs kind-aware at query time, so every already-ingested statement reports correctly with **no reingest**. Only the raw `*:Uncategorized` account balances (a pre-fix card purchase still physically sits in `Income:Uncategorized`) stay in the old bucket — cosmetic (debug view), read by no answer. Reingest is optional cleanup, not a correctness requirement._
- ✅ **T4 — category as a graded overlay.** `CategoryAssigned(movement_key, descriptor, category, grade, by)` (append-only, reversible, movement-keyed → survives a reingest — tested). The projection tracks the overlay; a `verified` human ruling supersedes an `unverified` model suggestion.
- ✅ **X2 / P7 — suggest and confirm.** `suggest_categories(ledger, suggest_fn)` records model suggestions `unverified` (the live model edge is injected, offline-testable); `assign_category(..., by='human')` records `verified`. Nothing auto-applies in Core.
- ✅ **The spending projection.** `spending_by_category` sums expense movements — card purchases included, transfers excluded (S3) — grouped by the overlay category, from movements (not the sign-mixed Uncategorized account balances, which are internal bookkeeping). `answer_spending` reports it with the uncategorized share shown honestly. Replaces the Slice-4 deposit-outflow stopgap.
- ✅ **I5 — taxonomy as data.** A minimal seed set (`ingest/categorize.SEED_CATEGORIES`); any string is a valid category; no US-shaped table.
- ✅ **T1 / the seam.** Every `CategoryAssigned` captures the descriptor — the merchant-learning seam — and provenance rides on the movement. Surface: a categorization queue (`/api/categorize`, one-tap assign) + a spending-by-category breakdown; `debug_vault` shows spending by category.

Honest edges (deferred by scope, noted): merchant normalization + the merchant→category commons + learned auto-apply; amount-splits + the tags overlay; external Party. A live *model* categorizer is injected (`suggest_fn`) but not yet wired to a real model call — like the reader was at first, the deterministic mechanism ships and the network edge is a thin follow-on. Tests: `test_categorize.py` (7); full suite 227 green.

## Notes for future slices (read these when you build them)

- **Merchant normalization + the merchant→category commons (later).** "AMZN MKTP US*…", "AMAZON.CO", "AMZN Digital" are one **Amazon** — the entity-resolution block (Slice 1.5) applied to merchants. On top sits a *merchant → category prior* ("Amazon → shopping"), which is **format-knowledge, shareable** (impersonal — about the merchant, not your money), so it follows the [format-commons](format-commons.md) pattern. Three refinements make it different from the format commons: it is a **prior, not truth** (a merchant's category is subjective; your override always wins locally), it is **lazy and locale-sharded** (merchants are millions, long-tail, country-specific — the model bootstraps every novel merchant on first sight; the commons is a *cache* of prior rulings, fetched by region, contributed opt-in and privacy-linted), and it has **two layers** (normalization vs the category prior). Crucially, because Core captured the descriptor on every categorization, this whole layer is a **projection over the existing correction events** — it mines "descriptors containing 'AMZN MKTP' were categorized shopping N times" to learn both the normalization and the prior, with **zero re-ingestion and nothing wasted**, and it only changes *future* suggestions (past confirmed categories stand).
- **Learned auto-apply (with merchant learning).** Once a merchant's category is confirmed, future matches auto-categorize at `corroborated`; new/ambiguous merchants still ask. The ask-once-then-learn autonomy we used for identity and transfers, turned on for categories — the thing that makes categorization stop being tedious after the first pass. Depends on merchant normalization.
- **The second mechanism: amount-splits + tags (later).** A movement split across categories by amount (double-entry: $100 Walmart → $70 groceries + $30 household, still balances) via a split-as-overlay; and a many-to-many `tags` overlay (free labels that never balance — "reimbursable", "vacation"). The `tags` field has been on the transaction event since v0 for exactly this. Both are overlays keyed to the movement, so they compose with the single-category work without redoing it.
- **The external Party (deferred from Slice 3).** A merchant, an employer, a landlord are all **Party**; the same descriptor-capturing correction events seed the Party graph. External counterparty attribution (a payment to a real person or biller is a real outflow, not a transfer) is the categorization-side of transfer-linking.

---

## Slice 5 — Categorization & spending (core)

**Block(s) seeded:** the **kind-aware counter-leg** (correct P&L buckets for assets and liabilities), **Category** (a graded, descriptor-carrying overlay via correction-as-event), a minimal **seed taxonomy** (data), and the **spending projection** (by category and time). Reuses movement keys, correction-as-event, grade + provenance, the overlay pattern, and transfer-exclusion — genuinely new is the counter-leg fix, the category overlay event, the taxonomy, and the spending projection.

**Open state:** every non-account leg is `Uncategorized`, and worse, the bucket's sign is inverted for liabilities (a card purchase files as income), so "where did my money go?" has no answer and any income/spending total is polluted. *Proofs (red tests):* a card purchase lands in `Income:Uncategorized`; spending-by-category returns everything under `Uncategorized`; a $100 card charge is invisible to any spending figure.

**Implementation:**
- Make the counter-leg a function of `(account kind, direction)` — card purchase → expense, card payment → transfers.
- `CategoryAssigned(movement_key, descriptor, category, grade, by)` overlay event; the projection reassigns the movement's counter-leg to the category. Model proposes (`unverified`, descriptor captured); a human confirms (`verified`).
- A minimal, overridable, jurisdiction-neutral seed taxonomy (data).
- `spending_by_category` / by-time projection, excluding transfer-linked movements; the spending answer carries a grade (confirmed vs suggested) and provenance. Replaces the Slice-4 "deposit-outflow" stopgap.
- Surface: a categorization view (uncategorized movements with the model's suggested bucket; one tap to confirm or override) and a spending breakdown.

**Final state:** movements carry categories with grade + provenance; a card purchase is spending, a card payment is not; "spending on groceries in March" answers honestly; a confirmed category is `verified` and survives a reingest; every categorization has quietly recorded the merchant descriptor, so merchant learning is a later projection, not a redo.

> _Amended 2026-07-25 (Slice 6.5): "spending-by-category excludes transfers" held only for **linked** transfers. A real-vault run showed the category and the transfer link are two independent descriptions of the same fact, and the aggregate listened to only one — so a movement *categorized* `transfers` or `loan_payments` was still counted as spending, and one category (`loan_payments`) covered two opposite natures (mortgage vs own-card payment). Exclusion is now decided by derived **movement nature**, with category/subcategory demoted to a *suggestion* rung: [honest-aggregates-and-the-learning-loop.md](honest-aggregates-and-the-learning-loop.md)._

**Done criteria / tests:** a card purchase now posts to `Expenses:Uncategorized` (not income) and a card payment to `Transfers:Uncategorized`; assigning a category moves the movement out of `Uncategorized` in the spending projection; a model suggestion is `unverified` and a human confirmation is `verified`; spending-by-category excludes transfers (S3) and includes card purchases; a categorization survives a reingest (content-keyed); each `CategoryAssigned` event carries the raw descriptor (the merchant-learning seam); existing balance/transfer/pay-stub tests stay green.

**Why now + future use:** it turns the ledger into answers ("where did my money go") — the first real advice, and the thing that makes a dashboard worth building (unblocking the presentation-layer decision). It fixes the counter-leg so income and spending are finally trustworthy. And it starts the moat that compounds: the correction stream is simultaneously your private categorization and — because Core captured the descriptor — the training data for merchant learning and a shareable merchant→category commons, built later as a projection with nothing wasted.
