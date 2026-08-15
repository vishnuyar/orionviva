# Honest Aggregates & the Learning Loop

**Status:** ✅ **BUILT** — derived nature + honest aggregates, the reset guard, and the question queue (see [the-question-queue.md](the-question-queue.md)) · **Last updated:** 2026-08-15 (the corollary this principle kept needing in practice is written down: route on the registry, not on the shape of the data). Before that, 2026-08-08: direction joins nature as a derived property, after a later reader got it wrong · **Origin:** the first full real-vault run after positions and investments. The reported "spending" figure was materially inflated by internal money movement, and the largest category decomposed into two *opposite* natures under one label. **Blocks seeded:** movement **nature** (derived) · the **question queue** (the learning loop's front door).

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
2. **`transfer` / `settlement` / `mixed` — a ruling.** A recorded ruling on this movement, or one on its *merchant* so one answer settles every transaction from that counterparty, or a `nature` carried on the category overlay or the merchant's attributes. A ruling whose legs disagree gives `mixed`: components known, proportions not.
3. **`transfer` — counterparty is an own account.** The movement names an account we hold, even if no link was formed — e.g. a card payment whose counterpart statement was never ingested. This is the rung that fixes the bulk of the error. It is a heuristic over description text, which is why a ruling outranks it: when the two disagree, the person decides.
4. **fallback — what the counterparty implies.** Not the category or subcategory label: an `implies` entry on the merchant's enrichment record, learned once at enrichment rather than matched against a word list we maintain, and filtered by *direction* — money out to a lender repays borrowing, money in from one is the borrowing. A `forced` implication decides; a `suggested` one decides and is marked provisional.
5. **`spending`** — the default when nothing above applies.

_**Rungs 2 and 3 were the other way round here until 2026-08-14, and the code has always been right.** The doc put own-account above the human ruling. That is not cosmetic: an issued card in the vault, a checking line reading `Payment To Northbank Card Ending IN 7799`, and the owner's ruling "I paid a friend's card, not mine" give `spending` under the code and `transfer` under the doc's order — a $400 swing, and an owner's explicit answer silently discarded. The own-account rung matches raw account tokens with no distinctiveness filter, so a bare institution name can fire it; a heuristic that loose must not outrank a person's answer. **Rung 4 never read the labels either** — the category-then-subcategory fallback described here exists nowhere in the code, and this document's own opening argument (same category, opposite natures) is why it should not._

`spending_by_category` and every downstream aggregate exclude anything not `spending`. Nature carries its **reason** (which rung decided it) so the surface can show why a figure is what it is (T1).

**A nature is never invented from a coincidence.** Where rungs 1–3 are silent and rung 4 only *suggests*, the movement takes the suggested nature and is marked **provisional**, and `provisional_spending` reports how much money is carried that way. The number is honest about its own uncertainty rather than quietly wrong in either direction (X2).

_**Corrected 2026-08-14, and it is a different number.** This paragraph said the movement "stays `spending`" — counted, with its uncertainty reported alongside. The code does the opposite: a `suggested` implication *changes* the nature away from spending and flags the change, so the doubtful money is **excluded** from the headline and flagged, not included and flagged. A $1,000 brokerage contribution on a suggested implication leaves `spending_by_category` empty and shows up in `provisional_spending`, which sums money that was **removed**. Two code comments repeat the old reading and should be corrected with it (`MovementInfo`'s `provisional` field comment and `decide_nature`'s docstring, both of which still say "counted")._

## Derive nature (this build)

Read-side only. No new event type, no change to the ingest path, nothing re-read:

- `MovementInfo` gains a derived `nature` + `nature_reason` computed in the projection.
- Aggregates (`spending_by_category`, `spending_by_subcategory`) exclude non-`spending` movements and report a provisional total alongside. `spending_by_currency` is the exception — see the as-built note below.
- The own-account rung reuses the transfer matcher's tokens — but **not** `_names_account`, and not the same token set: the projection tests raw `account_tokens`, while the link matcher first narrows them to *distinctive* ones, so this rung fires on a bare institution name that would never form a link. That is defensible on this document's own argument — a wrong nature is a weaker error than a wrong link — and it is the concrete reason a person's ruling must outrank it. There is deliberately **no loosening of the auto-link bar**: we get the honest number from nature, without gambling on speculative links (a wrong link is a wrong number; an unlinked-but-transfer-natured movement is merely a weaker explanation).

This is retroactive for free: aggregates re-derive from movements at query time, so an existing vault becomes honest on the next read, with no re-ingest and no model cost.

**A second derived property joined it, 2026-08-08: direction.** `nature` says whether money left your *life*; it does not say which *way* the money went, and a posting's sign does not either — a charge on a liability is recorded positive and the money is gone. Two later readers derived direction inline and one of them derived it wrong ([issue #1](https://github.com/vishnuyar/orionviva/issues/1)), which is the same shape as the failure this document was written about: one fact, two places deciding it, and the aggregate listening to the weaker one. It is now `money_effect(m)` in the same module as `is_expense` and `counts_as_spending` — positive in, negative out, the account's kind deciding. The split between what a merchant-scoped ruling *paid* and what *came back* reads it too, so a payment out of an investment account is a payment rather than money returning.

## The question queue (next, its own build)

The rulings we already write — `AccountAliasConfirmed`, `TransferLinked(by="human")`, `CategoryAssigned(by="human")`, `MerchantCategorized(by="human")` — are the same primitive implemented four times. The question queue does **not** refactor those writers. It adds one read-side projection, `open_questions()`, that gathers everything the system is genuinely unsure about into a single list, each entry carrying:

- **the question**, in Viva's voice;
- **its consequence** ("answering this moves X of your spending") — used to **rank by leverage**, so the highest-value question is asked first;
- **its scope** — does answering it settle one movement, or a whole pattern (the merchant-catalog lesson: one ruling should clear many);
- **a silence rule** — below a consequence threshold, take the conservative default and say so quietly rather than asking.

The principle: **abstract the read side early (cheap, reversible); abstract the write side late (expensive, one-way).** A generic `Ruling` event — the generic scoped ruling — waited on a fifth question type (Slice 8 or 11) to prove the shape, and has since arrived as `RulingRecorded` carrying `scope` + `same_as`.

**The corollary, added 2026-08-15: route on the registry, not on the shape of the data.** A read-side abstraction is only as reversible as its dispatch is explicit. Duck-typed checks — `"opening_amount" in facts`, an exact instrument-name match — silently did the wrong thing three times in one session where a route through the doc-type registry would have been correct. A missing route fails loudly; a route inferred from which fields happen to be present does the wrong thing quietly and keeps doing it, which is the expensive half of the trade this principle exists to avoid. So a projection asks the registry what a thing is, and never infers it from the shape of what it was handed.

## What we deliberately will NOT hardcode

These are the questions **Viva asks** — the learnings are the product (CLAUDE.md: *memory of the user is the moat*). Hardcoding an answer would be guessing on the owner's behalf, which is the thing this project refuses everywhere else:

- **Is a payment to this counterparty your own account, or someone else's?** (the mortgage-vs-own-card distinction)
- **Is a cash withdrawal spending, or money moved to cash in hand?** (defensible both ways; it is the owner's call, and the answer generalizes to every ATM line)
- **Is a large capital movement — a property closing, a vehicle purchase, a brokerage contribution — spending, or a change in what you own?**

Each is asked once, ruled once, and applied forever and retroactively. Until answered, the affected total is reported as **provisional**, never silently resolved either way.

## Protecting the asset — done

`viva.reset_categorization` once dropped **all** `CategoryAssigned` events, including `by="human"`. Under the original framing categories were cheap derived data; under the learning-loop framing those human rulings *are* the moat — the one thing a model call cannot regenerate. It now preserves a person's rulings by default; discarding them requires `--discard-my-rulings`.

## Done criteria / tests

- A card payment whose counterpart statement is **not** in the vault is nature `transfer` (own-account rung) and excluded from spending; the same payment when linked is excluded via rung 1 — both report their reason.
- A mortgage payment and an own-card payment carrying the **same category** land on **opposite** natures.
- `transfers` never appears as a line item inside a spending breakdown.
- A movement with no nature evidence stays `spending`, is marked provisional, and the aggregate reports the provisional total.
- Nature is derived (no new event type); an existing vault becomes honest with no re-ingest; a replay reproduces every nature.
- `reset_categorization` preserves human rulings by default and drops them only under the explicit flag.

## As-built (movement nature + the guard, 2026-07-25)

- **Nature lives on `MovementInfo`** (`nature`, `nature_reason`, `provisional`), decided in `LedgerProjection._decide_nature` on the rungs above. `counts_as_spending` (shape **and** nature) is the predicate the spending aggregates use — `spending_by_category`, `spending_by_subcategory`, `spending_by_category_then_subcategory`, and `uncategorized_expenses` (we never ask you to categorize money that didn't leave your life).

  _**One aggregate is not on it, and the consequence is live. Tracked as a defect, not fenced as prose.**_ `spending_by_currency` inlines its own test — depository outflows only — so it **omits every card purchase**, which is real spending under M1. It is marked superseded in code and it is still what three callers print as the headline: `debug.vault` and `rescan` both print it as *"external spending (transfers excluded)"* directly above a category breakdown computed on the correct population, and the synthetic bench uses it to pick a currency. It also omits provisional movements, which the paragraph above promises are included. This is the unresolved **R5** from the July repair list, where a real corpus run reported a headline and a category breakdown that did not agree and the difference was card charges; the partition test R5 asked for was never written, and `test_nature.py` currently asserts the divergence instead. Putting it on `counts_as_spending`, retiring it, or renaming it to what it measures is a ruling, because those assertions are deliberate.
- **Own-account tokens moved to `ledger/identity.py`** as `account_tokens`, so the transfer matcher and the projection share one implementation with no import cycle; `transfers.account_tokens_from` now delegates to it.
- **A human's nature ruling rides on the existing `CategoryAssigned` overlay** (`nature=` on `assign_category`) — no new event type, honouring "abstract the read side early, the write side late."
- **`provisional_spending()` and `excluded_from_spending()`** are surfaced in `debug.vault` (what was excluded, by which rung, and how much rests on weak evidence). _(The web overview went with the 2026-08-06 deletion.)_
- **Reset guard:** `reset_categorization` preserves `by="human"` rulings by default; `--discard-my-rulings` (or `keep_human=False`) is required to drop them, and the report says which was done.
- **Two defects in positions and investments found by the same real run, fixed here:** a statement's cash/sweep line read back as a position named `CASH` is folded into the cash balance (in `post_brokerage`, so every facts source is covered) rather than recorded as a holding; and `holdings_as_of()` reports the **oldest** measurement a composed account value rests on plus whether the parts were measured on different dates — summing different vintages must never read as "current."

Tests: `test_nature.py` (7) + 2 brokerage; full suite **279 green**.

## Deferred

The generic scoped ruling — **since arrived** (`RulingRecorded` with `scope` + `same_as`). Principal/interest splitting on a mortgage payment (Slice 11, where amortization data lives). Per-transaction custom categories for peer descriptors ([local-categorization-and-custom-categories.md](local-categorization-and-custom-categories.md)) — they compose over nature unchanged. Loosening the transfer auto-link bar (deliberately not done here).

## The doctrine reaches the answering path (2026-08-10)

This document's rule — *an unanswered question leaves a number incomplete,
never wrong*, and a total resting on something undecided is never silently
resolved either way — held everywhere beneath the voice and nowhere inside it.
The answer path had a word for how well evidence stands up and a word for
whether arithmetic terminated, and none for how much of the question an answer
covered. Asked what was owed, a run stated one liability of three and graded it
`corroborated`, which was true of that balance: a false sentence assembled
entirely out of true parts.

A figure now states the set it was taken over (see the tool registry's third
axis), and the run places that statement the way it places a caveat. An
incomplete total states the number **with** its gap rather than refusing until
the gap is filled — the owner's ruling, on the ground that a person asking what
they owe is better served by a figure and its hole than by silence.

The other half of the doctrine — that a gap becomes a question Viva asks — is
**not built**. The queue raises nothing that could answer this one: the drafted
ask wants an amount, the queue's question for the same account carries only a
yes/no about whether a document exists, and answering it writes nothing by
design. Closing that needs a question source that can record a balance, which
is its own cycle.
