# Net Worth — a curve, not a number

**Status:** ✅ **BUILT 2026-07-26** — and hardened the same day by its first real-vault run: the liability-sign defect (two cards booked as assets; see D1's postscript) and unvalued accounts silently dropped from the total, both fixed · **Created:** 2026-07-26 · **Origin:** Vishnu, on being asked what date a net-worth figure carries: *"net worth is always as-of date, it should be from the earliest date available to latest date."* · **Blocks seeded:** the **net-worth projection** · the **provable subtotal** (Slice 13's first primitive, derived for free).

**Invariants touched:** **T1** (every line names the document behind it) · **T2** (arithmetic is deterministic; no model anywhere near this) · **T4** (pure projection over events already written — no new event type, retroactive, no re-ingest) · **M1** (cash-flow over accrual: a holding is a dated *measurement*, unrealized change is a presentation view) · **X2** (a figure carries its as-of date and its grade, always) · principle 2 (never bluff a number) · principle 7 (deferential where it counts).

---

## The one sentence

**Net worth is a function of date**, `net_worth(D)`, defined at every date between your earliest document and your latest — each point built from every account's last-known measurement at or before `D`, each line carrying its own as-of date and grade.

---

## Why this shape, and why it is not the shape I proposed

I offered three options for the as-of problem: one coherent date (pure but stale), latest-known-per-account (current but never true at any instant), or both. All three assume net worth is **a number that needs a date attached**.

It isn't. It is **a curve**, and asking "what is my net worth?" is asking for a point on it.

That dissolves the problem rather than answering it. There is no *the* net worth to be wrong about; there is `net_worth(D)` for any `D`, and each point is honestly constructed from what was known at that date. It also falls straight out of what the ledger already is — an append-only log of dated observations — so it needs **no new event type and no new machinery**, and it hands us trends for free, which the roadmap had waiting on this slice.

**The residue, named rather than hidden.** At any point on the curve, some accounts' last measurement may be months older than the point itself. That is a real limitation, not a rounding error, so **every point carries the age of its oldest input**. The curve visibly firms up as documents arrive — which is the product telling the truth about its own coverage, and the same honesty the `provisional` aggregate established with movement nature.

---

## The four decisions

### D1 · Net worth is a curve, defined at every date in range

`net_worth(D)` for any `D` between the earliest and latest dated observation. The series is evaluated at every date where *anything changed* — a statement closing, a position measurement, a ruling — because those are the only dates where the answer can move.

**What a point is made of.** For each account, the most recent measurement at or before `D`:

| account kind | the measurement | why this and not something else |
|---|---|---|
| depository, liability (card) | the **observed closing balance** | the issuer attests it; summing our own postings would be *our* arithmetic over a possibly incomplete run |
| investment | `Σ(market_value)` over **one snapshot** — the holdings measured on the latest statement at or before `D` — plus the account's cash | a holding is a dated measurement (positions and investments, M1) |
| asserted (`Assets:` / `Liabilities:` from a ruling) | **cost at the ruling's date** | what you paid, never what it is now worth |

_**Corrected 2026-08-15.** The investment row said `Σ(market_value)` of **each
holding's** latest observation ≤ `D`, which is a composition across instruments,
and the code deliberately does not do that. It takes the newest observation date
at or before `D` and sums only the measurements carried on it. The difference is
not academic: composing per-instrument latest values double-counts a stale
snapshot, because an instrument that appeared on an older statement and is
absent from the newer one keeps contributing its old value forever. One snapshot
answers both halves at once — an earlier point on the curve still uses the
statement that was current then, and a holding the newest statement no longer
lists is no longer held._

**The side is decided by the account's KIND, never by the sign of its balance.** The registry is explicit: a `liability` account's balance is *money owed*, stored as a **positive** magnitude, because that is the figure printed on the bill. So a liability's contribution is `-balance` — negated rather than absolute-valued, which keeps the real edge case honest: an overpaid card owes *you*, its owed figure is negative, and `abs()` would book that credit as another debt.

**And what a read of one says it measured.** How a figure is stored is half of it; the other half is what travels beside it when it leaves. Every read that emits a liability's **own** magnitude emits it as **`owed`** — its own name in the closed vocabulary of what a figure can measure — and none of them emits it as `balance`: the balances read, the per-account line and the liabilities subtotal of a net-worth point, and the provenance read. A subtotal is a figure about a *side* rather than about an account, and it declares what that side measures however few accounts are in it: in a vault whose only account is an overpaid card, `assets` still declares `balance`, because money a card holds on your behalf is money held. `owed` carries the same convention the bill prints, so an overpaid card is emitted negative and means it, and the same card comes back as the same figure from every read rather than positive in one and negative in another. The point's internal line keeps the signed contribution every subtotal is built from, so nothing about how the total is computed changes — only what the figure handed to a model says it is. Two things then follow from the vocabulary rather than from anyone remembering: a debt added to a deposit refuses, and a net worth assembled by hand out of the two sides refuses, which leaves the read that is complete on its own and knows what it left out.

This is written down because the first implementation got it backwards, from a docstring that asserted liabilities were "already negative" — inferred from defensive `abs()` calls in the answer path instead of read from the one comment that states the convention. On a real vault two cards were added to **assets**, and the report printed `liabilities 0.00` directly beneath two lines labelled `[liability]`. The test agreed with the code because the fixture fed a negative closing balance: **one wrong assumption, held in both places, so the suite confirmed the bug rather than catching it.**

The transferable half is not about liabilities. **`abs()` erases the one bit that matters**, and it has now done so twice in unrelated code: here, where it turned two debts into assets; and in the merchant view, where wrapping every amount in `abs()` before summing added both directions of a transfer together, so every row read positive and a total combined money going out with money coming in. Reach for `abs()` and the question to ask is what direction is being discarded, and who was relying on it.

An account with no measurement at or before `D` **does not contribute** to that point. It did not exist to us then, and inventing a zero would be a claim.

### D2 · Trust the user; the provable/unprovable line is an *audience* question

> *"Trust the user, he has no incentive to lie. But in the future when a credit agent asks, we state what is provable and what is not."* — Vishnu, 2026-07-26

Two views over one set of data:

- **The personal view (built now):** one number. Everything you told us is included, at your word, badged with its grade.
- **The disclosure view (Slice 13):** the corroborated subset only — the figure a counterparty could be shown.

This is the decision that makes the honesty machinery *cost nothing today*. We record the grade because we already do; the disclosure view is later a one-line filter.

### D3 · Two different unknowns, and only one is a trust problem

**Kind A — asserted.** You told us the car cost X. Nobody issued a document. **Trust it, include it, badge it `asserted`.**

**And when you have not told us yet — the disclosed gap (2026-08-01).** An asserted asset whose cost nobody has stated is neither counted nor hidden. It is reported in `missing` with the question that closes it, so the point reads **incomplete** rather than quietly complete: a zero would be a number nobody stated, and silence would let a total claim to include something it does not. The same applies when the schema pack cannot yet ask about the kind at all — *I have no way to ask what this cost* is an answer; omitting it is not. Which essential closes the gap is `gates_net_worth` in the schema pack, and the date the figure belongs to is `dates_net_worth`, so a flat bought years ago is not a step on the day it was mentioned. A stated cost **replaces** the cash-derived line for that account rather than adding to it: the sum of the instalments paid so far is not what the thing cost.

**Kind B — undecomposable.** Cash reached the mortgage servicer; how much of it reduced the debt rather than paying interest is unknown. **Trusting you produces no number here, because you do not know either** — only the statement does. This is `reliable_balance = False`, already tracked by `ruled_accounts`.

**The ruling:** *ask, record it, and correct it when the document arrives.* The queue asks what you roughly owe; your answer is recorded as `asserted` with its own as-of date, exactly like the car; the 1098 or the mortgage statement later **upgrades** it to `corroborated` rather than unlocking it. Until you answer, the liability appears in the list with its amount unknown and the total is marked **incomplete** — knowingly too favourable, and saying so.

A missing document must never block an answer (the ruling from Viva listens), and it must never be silently absorbed either.

### D4 · Reuse the grade ladder; do not invent an issued/asserted badge

"Provable" is not a new property. It is `corroborated`: **we hold the document that attests the figure, and the arithmetic checks.** Every figure in this ledger already carries a grade.

Adding a parallel `issued`/`asserted` vocabulary for net worth would mean two systems describing one fact — which is precisely the bug that inflated the spending figure before honest aggregates, where a transfer *link* and a category saying `transfers` described the same movement and the aggregate listened to only one. `origin` stays on the account, where it answers *"who says this account exists?"*; the **grade** answers *"can this figure be proved?"*, and that is the one net worth reads.

The provable subtotal is therefore `Σ(lines where grade == corroborated)` — derived, not stored, and built when Slice 13 has a counterparty to show it to.

### D5 · Currency: subtotal, never convert *(recommendation, not a fork)*

One financial life can hold several currencies (I1). We have **no FX source with provenance**, and a converted total would be a figure no document attests — a bluff by construction. So net worth reports **per-currency subtotals** and no grand total until a rate has a source, a date and a grade of its own.

---

## What it computes

```
NetWorthPoint
  as_of          the date this point is true of
  assets         Decimal, per currency
  liabilities    Decimal, per currency
  net            assets − liabilities, per currency
  oldest_input   the as_of of the stalest measurement in this point
  complete       False when any known obligation has no usable amount
  missing        what is excluded, and what would fix it — a document, or
                 the question nobody has answered yet
  lines[]        account · amount · as_of · grade · origin · what proves it
```

`net_worth(proj)` returns the latest point there is evidence for; `net_worth(proj, D)` returns the point at any date. `series(proj)` returns the whole curve.

---

## Honesty properties (the point of the slice)

1. **Every line carries its own as-of date and grade.** No figure is ever dressed as "current" (the valuation-class invariant, inherited from positions and investments).
2. **Every point names its stalest input.** A total resting on a four-month-old brokerage statement says so.
3. **Incompleteness is stated, never absorbed.** An obligation we cannot value keeps the total marked incomplete and names the document that would fix it. An asset nobody has priced does the same, and what it names is the **question** that closes it rather than a document — including the case where the schema pack cannot yet ask about the kind at all.
4. **Cost is never presented as value.** A car holds its purchase price. Any present-day worth is an `estimated` layer on top, and is not built in this slice.
5. **`reliable_balance = False` never enters a sum.** Cash reaching a mortgage account is a fact; treating all of it as debt reduction is not.
6. **No model is involved.** This is arithmetic over recorded measurements, end to end.

---

## What this slice does NOT do

Market **valuation** of asserted assets (a car's worth today — needs a source with provenance). FX conversion (D5). Per-lot cost basis (Slice 11). Projections forward in time — this curve ends at the last document and does not extrapolate. Charts (the surface renders the series; the visual design belongs to the real presentation layer, not the debug one).

---

## Done-tests

- A vault with one checking statement returns a curve with one point, `complete = True`.
- Adding a card statement dated later adds a point; the earlier point is **unchanged**.
- An investment account contributes `Σ(market_value)` over the holdings of the latest statement at or before `D`, and a *later* observation does not alter an earlier point. _(Corrected 2026-08-15: this read "at the latest observation ≤ `D`" per instrument — see the note under the table above. The snapshot is the unit, not the instrument.)_
- An account whose first statement is after `D` contributes nothing to that point — no zero, no guess.
- An asserted car appears at cost, badged `asserted`, from its ruling date onward.
- A `reliable_balance = False` liability keeps `complete = False` and appears in `missing` with its corroborating document named.
- Answering the "roughly what do you owe?" question flips `complete` to `True` and badges the line `asserted`; a later mortgage statement upgrades it to `corroborated` **without** changing the earlier points.
- Two currencies produce two subtotals and no grand total.
- The provable subtotal equals the sum of `corroborated` lines only.

---

## Later

The **disclosure view** (Slice 13) is this projection with one filter. That is the whole point of settling D2 and D4 now: the endgame primitive — *proving a claim to a counterparty without revealing more than the claim* — arrives as a filter over a projection rather than as a subsystem.
