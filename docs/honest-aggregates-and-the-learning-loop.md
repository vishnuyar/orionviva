# Honest Aggregates & the Learning Loop

**Status:** ✅ **BUILT** — derived nature + honest aggregates, the reset guard, and the question queue (see [the-question-queue.md](the-question-queue.md)) · **Last updated:** 2026-07-25 · **Origin:** the first full real-vault run after positions and investments. The reported "spending" figure was materially inflated by internal money movement, and the largest category decomposed into two *opposite* natures under one label. **Blocks seeded:** movement **nature** (derived) · the **question queue** (the learning loop's front door).

**Invariants touched:** T1 (a nature carries why it was decided) · T2 (nature is derived deterministically; a model may *suggest* a category, never certify a nature) · **T4 (a ruling is an append-only event; nature is a projection over events we already write)** · **M1 (cash-flow over accrual — "spending" must mean money that left your life, not money that left an account)** · X2 (an undecided nature is visible, never silently assumed) · principle 5 (serve, don't overwhelm — ask only where it pays) · principle 6 (you direct the pace — an unanswered question leaves the number *incomplete*, never wrong).

---

## The problem, from a real vault

Spending is computed as "money that left an account, excluding *linked* transfers." Two independent systems describe the same underlying fact — that money didn't leave your life — and the aggregate listens to only one of them:

- **The transfer link** records it as a `TransferLinked` overlay. Excluded from spending. ✅
- **The merchant catalog** records it as a *category* (`transfers`, `loan_payments`). **Still counted as spending.** ❌

So every internal movement that didn't auto-link — a card payment in a month whose card statement isn't ingested, a contribution to a brokerage, a cash withdrawal — is counted as consumption. On a real vault this was not a rounding issue; it was a large fraction of the headline number, and `transfers` appeared *as a line item inside spending*, which is self-evidently incoherent.

## Why the category can't decide it

The real run's decisive finding: the largest "spending" category, `loan_payments`, decomposed exactly into two subcategories — **mortgage payments** and **credit-card payments**. A mortgage payment is real cash leaving your life. A payment to your own card is not (the purchases it settles were already counted). **Same category, opposite natures.**

Therefore nature is not a property of the category. It is a property of **the counterparty**: is the other side of this movement an account *you hold*? That is knowable, and where it isn't, it is exactly the kind of question only the owner can answer.

## The model: movement nature

Every movement gets a derived `nature`, in this precedence:

1. **`transfer` — linked.** A live `TransferLinked` exists. Decisive, already built.
2. **`transfer` — counterparty is an own account.** The movement names an account we hold (the transfer-link token matcher already computes this), even if no link was formed — e.g. a card payment whose counterpart statement was never ingested. This is the rung that fixes the bulk of the error.
3. **`transfer` / `settlement` — a human ruling.** A recorded ruling on this movement or on a *pattern* it belongs to (see the learning loop).
4. **fallback — the category/subcategory signal**, used only to *suggest*, never to decide silently: subcategory first (it is the sharper signal — "credit card payment" vs "mortgage"), category second.
5. **`spending`** — the default when nothing above applies.

`spending_by_category` and every downstream aggregate exclude anything not `spending`. Nature carries its **reason** (which rung decided it) so the surface can show why a figure is what it is (T1).

**A nature is never invented from a coincidence.** Where rungs 1–3 are silent and rung 4 only *suggests*, the movement stays `spending` but is marked **provisional**, and the aggregate reports how much of it is provisional. The number is honest about its own uncertainty rather than quietly wrong in either direction (X2).

## Derive nature (this build)

Read-side only. No new event type, no change to the ingest path, nothing re-read:

- `MovementInfo` gains a derived `nature` + `nature_reason` computed in the projection.
- Aggregates (`spending_by_category`, `spending_by_subcategory`, `spending_by_currency`) exclude non-`spending` movements and report a provisional total alongside.
- The own-account rung reuses `account_tokens_from` / `_names_account` from `transfers.py` — no new matching logic, and deliberately **no loosening of the auto-link bar**: we get the honest number from nature, without gambling on speculative links (a wrong link is a wrong number; an unlinked-but-transfer-natured movement is merely a weaker explanation).

This is retroactive for free: aggregates re-derive from movements at query time, so an existing vault becomes honest on the next read, with no re-ingest and no model cost.

## The question queue (next, its own build)

The rulings we already write — `AccountAliasConfirmed`, `TransferLinked(by="human")`, `CategoryAssigned(by="human")`, `MerchantCategorized(by="human")` — are the same primitive implemented four times. The question queue does **not** refactor those writers. It adds one read-side projection, `open_questions()`, that gathers everything the system is genuinely unsure about into a single list, each entry carrying:

- **the question**, in Viva's voice;
- **its consequence** ("answering this moves X of your spending") — used to **rank by leverage**, so the highest-value question is asked first;
- **its scope** — does answering it settle one movement, or a whole pattern (the merchant-catalog lesson: one ruling should clear many);
- **a silence rule** — below a consequence threshold, take the conservative default and say so quietly rather than asking.

The principle: **abstract the read side early (cheap, reversible); abstract the write side late (expensive, one-way).** A generic `Ruling` event — the generic scoped ruling — waited on a fifth question type (Slice 8 or 11) to prove the shape, and has since arrived as `RulingRecorded` carrying `scope` + `same_as`.

## What we deliberately will NOT hardcode

These are the questions **Viva asks** — the learnings are the product (CLAUDE.md: *memory of the user is the moat*). Hardcoding an answer would be guessing on the owner's behalf, which is the thing this project refuses everywhere else:

- **Is a payment to this counterparty your own account, or someone else's?** (the mortgage-vs-own-card distinction)
- **Is a cash withdrawal spending, or money moved to cash in hand?** (defensible both ways; it is the owner's call, and the answer generalizes to every ATM line)
- **Is a large capital movement — a property closing, a vehicle purchase, a brokerage contribution — spending, or a change in what you own?**

Each is asked once, ruled once, and applied forever and retroactively. Until answered, the affected total is reported as **provisional**, never silently resolved either way.

## Protecting the asset (do first)

`viva.reset_categorization` currently drops **all** `CategoryAssigned` events, including `by="human"`. Under the original framing categories were cheap derived data; under the learning-loop framing those human rulings *are* the moat — the one thing a model call cannot regenerate. **Fix: preserve `by="human"` rulings by default; discarding them requires an explicit, loudly-named flag.**

## Done criteria / tests

- A card payment whose counterpart statement is **not** in the vault is nature `transfer` (own-account rung) and excluded from spending; the same payment when linked is excluded via rung 1 — both report their reason.
- A mortgage payment and an own-card payment carrying the **same category** land on **opposite** natures.
- `transfers` never appears as a line item inside a spending breakdown.
- A movement with no nature evidence stays `spending`, is marked provisional, and the aggregate reports the provisional total.
- Nature is derived (no new event type); an existing vault becomes honest with no re-ingest; a replay reproduces every nature.
- `reset_categorization` preserves human rulings by default and drops them only under the explicit flag.

## As-built (movement nature + the guard, 2026-07-25)

- **Nature lives on `MovementInfo`** (`nature`, `nature_reason`, `provisional`), decided in `LedgerProjection._decide_nature` on the rungs above. `_counts_as_spending` (shape **and** nature) is the single predicate every aggregate now uses — `spending_by_category`, `spending_by_subcategory`, `spending_by_currency`, and `uncategorized_expenses` (we never ask you to categorize money that didn't leave your life).
- **Own-account tokens moved to `ledger/identity.py`** as `account_tokens`, so the transfer matcher and the projection share one implementation with no import cycle; `transfers.account_tokens_from` now delegates to it.
- **A human's nature ruling rides on the existing `CategoryAssigned` overlay** (`nature=` on `assign_category`) — no new event type, honouring "abstract the read side early, the write side late."
- **`provisional_spending()` and `excluded_from_spending()`** are surfaced in the web overview and `debug.vault` (what was excluded, by which rung, and how much rests on weak evidence).
- **Reset guard:** `reset_categorization` preserves `by="human"` rulings by default; `--discard-my-rulings` (or `keep_human=False`) is required to drop them, and the report says which was done.
- **Two defects in positions and investments found by the same real run, fixed here:** a statement's cash/sweep line read back as a position named `CASH` is folded into the cash balance (in `post_brokerage`, so every facts source is covered) rather than recorded as a holding; and `holdings_as_of()` reports the **oldest** measurement a composed account value rests on plus whether the parts were measured on different dates — summing different vintages must never read as "current."

Tests: `test_nature.py` (7) + 2 brokerage; full suite **279 green**.

## Deferred

The generic scoped ruling — **since arrived** (`RulingRecorded` with `scope` + `same_as`). Principal/interest splitting on a mortgage payment (Slice 11, where amortization data lives). Per-transaction custom categories for peer descriptors ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)) — they compose over nature unchanged. Loosening the transfer auto-link bar (deliberately not done here).
