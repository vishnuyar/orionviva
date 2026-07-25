# Positions & Investments (Slice 6)

**Status:** Design spec — approved architecture, pre-build · **Last updated:** 2026-07-24 · **Block seeded:** Asset (valuation class) / Position (instrument + units + cost basis, dated).

**Invariants touched:** T1 (every position value points to the statement region it was read from) · T2 (the reconciliation identity is deterministic `Decimal` arithmetic, never the model's mental math) · T3 (raw capture — the brokerage PDF is stored, so a richer position profile later re-reads it, no re-upload) · **T4 (a holding is an append-only *measurement* event; a revaluation is a new measurement, never an edit of the old one)** · **M1 (cash-flow over accrual — the ledger posts only realized cash events; unrealized gain is a derived presentation view, never a ledger fact)** · I5 (instrument and currency are data, no US-market assumptions) · **the valuation-class invariant (a measured value is always surfaced with its as-of date and class; a stale price is never dressed as "current" — the "never bluff a number" wall applied to prices) · X2 (unrealized gain is shown as an as-of-date estimate, its uncertainty visible)** · the grade ladder (a statement-attested position is `measured`+`verified`-of-source; a derived or stale figure is graded down, never silently).

---

## Open state (the capability is absent)

The pipeline reads *flow* documents only. A brokerage or retirement statement classifies but parks — or, at best, only its cash sweep reconciles as a depository balance, while the holdings that are the whole point of the account are invisible. Net worth cannot include investments, and "what do I hold, and what's it worth?" is unanswerable. *Proof (red test):* ingest a brokerage statement → parked (no projector for its identity); a positions query returns empty.

## The locked decision: holdings are dated measurements, not postings (Option A)

Every prior document reconciles a **flow** — money moved and a posting recorded it (`opening + Σ movements = closing`; `gross − deductions = net`). A brokerage statement breaks that: an account can go from \$100k to \$110k with no money moving, because the market repriced holdings already owned. That change is a **revaluation, not a transaction.**

So positions do **not** post to the double-entry money ledger. A holding is recorded as a **`PositionObserved`** event — a unit quantity of an instrument, *measured* at the statement date, exactly as `ClosingBalanceObserved` measures a balance rather than posting it. Only real cash flows (buys, sells, dividends, fees, sweeps) post. **Unrealized gain is never fabricated as a transaction** — it is simply the difference between two successive measurements, computed and surfaced at read time.

This is a thesis decision, not merely a modeling convenience. OrionViva's claim is that personal financial records are clean *because they are measurements, not generations*. Option B (posting each price change against an "unrealized gain" equity account) would manufacture money-movement events for changes that were never movements — the exact kind of generation the thesis rejects, and it would force a fabricated price onto every date. Option A keeps the money ledger pure cash flow and treats a holding honestly as a dated measurement carrying a valuation class.

## The two reconciliations: internal tally + cross-account flow

The brokerage account is a **reconciliation hub**, checked two independent ways (Vishnu, 2026-07-24). Both must hold; together they separate *contributed* growth from *market* growth — the honest heart of "how are my investments doing?"

**1 — Internal tally (within the uploaded statement), a hard gate.**
`Σ position market_value + cash = account total`, at the statement's close. Tight, deterministic (T2), model-free. A misread position or cash line fails it loudly and holds the statement.

**2 — Cross-account cash flow (over the period), all realized events.**
The ledger reconciles only *cash* — money that actually moved (M1: cash-flow over accrual). Each realized component maps to how Option A already records things:

- **contributions / withdrawals** tie to their source: a checking/savings → brokerage transfer is a **Slice-3 `TransferLinked`** between the source outflow and the brokerage cash inflow — counted once, a *contribution*, never spending. This is the "money moved to brokerage should tie to the brokerage account."
- **dividends / interest** → income postings (Slice 4 reuse); a cash dividend also visible in checking corroborates (Slice 3).
- **fees** → an expense posting (Slice 5 reuse).
- **realized gain** (a sell) → a real cash event: proceeds post to cash, the position's units drop, and `proceeds − cost basis of the units sold` is the booked gain/loss — a tax event (seeds cap-gains, S11).

**Unrealized gain is deliberately NOT here.** It is not cash and not a tax event, so it is never posted, never a reconciliation gate, never an event (M1). It lives in the **presentation layer** as a *derived, as-of-date* figure — `Σ market_value − Σ cost_basis` over held positions (or period market-change) — computed from the `PositionObserved` measurements on hand and labeled with that date under the valuation-class rule (X2). If a statement prints a "change in value" line, presentation may show our derived number beside it; the ledger never reconciles against it. This is what dissolves any "gate the market change" question — there is nothing to gate, because the paper change isn't a ledger fact.

The **internal tally (1)** remains the one hard gate — it is read-validation (the statement's own numbers are self-consistent), not accrual accounting.

## New primitives (each the smallest that works)

**`INVESTMENT` account kind.** A third kind beside `DEPOSITORY` and `LIABILITY`: an asset that holds *cash + positions*. Its account "value" is a **composition**, not a single posted balance — cash (from postings) plus the sum of its latest position measurements. Display is kind-aware, like the card's "owed."

**`PositionObserved` event.** The Position primitive as data:

```
PositionObserved(
  account_id,            # the investment account it belongs to
  instrument,            # ticker / name (the identity key — see below)
  units,                 # Decimal quantity held
  market_value,          # Decimal, the statement's value for the holding
  currency,              # per-currency, no FX faking (I5)
  as_of,                 # value time — the statement date (bitemporal)
  cost_basis="",         # optional Decimal, if the statement shows it (graded)
  valuation_class="measured",
  grade,                 # from the reconciliation, like every figure
  provenance)            # → the statement region (T1)
```

It is append-only: next quarter's statement emits a *new* `PositionObserved` for the same instrument; the projection reads the latest as-of. Nothing is edited (T4).

**Valuation class.** `measured` (a statement value at its date) · `valued` (mark-to-market from a live price feed — deferred) · `estimated` (a guess — deferred). **S6 emits only `measured`.** The invariant is the point: a position value is surfaced as "AAPL \$18,400 **as of Mar 31**," never "AAPL \$18,400" — a stale measured price must never read as current. Every future asset (property, vehicles, a price feed's `valued`, an `estimated` guess) inherits this discipline.

**`BROKERAGE_IDENTITY`.** A new identity row in the registry: `Σ(position market_value) + cash = account total`. Unlike the flow identities this is a **snapshot cross-check** — a point-in-time consistency test over many numbers the statement itself asserts, so a single misread position (wrong units or value) fails it loudly. Densest verification surface yet, and entirely model-free arithmetic (T2). It plugs into the *same* Finding contract (forced / suggested / held) as the balance family and pay stubs — a divergent profile, as data, exactly like Slice 4.

**`BrokerageFacts`.** The extraction shape the profile owns: account identity, statement date, cash balance, a list of positions (instrument, units, market value, optional cost basis), dividends, fees, and the stated account total.

## The projector (`post_brokerage`) — mostly reuse

1. **Internal tally (hard gate):** `Σ market_value + cash = total` deterministically → grade + Finding (reuse the forced/suggested/held contract verbatim).
2. **Positions →** emit a `PositionObserved` per holding (`measured`, graded, provenance to its row). Not posted.
3. **Cash →** post the cash sweep/balance as an ordinary depository-style leg on the investment account (real money).
4. **Contributions/withdrawals →** the brokerage cash inflow is a movement like any other; a checking/savings counter-leg auto-links (`TransferLinked`, Slice 3), so a contribution is counted once and excluded from spending. An unmatched inflow is a `suggested` transfer, asked, then learned.
5. **Dividends / interest →** income (reuse Slice 4 recognition); a cash dividend also in checking **corroborates** via the Slice 3 net↔deposit witness.
6. **Fees →** an expense leg (reuse Slice 5 categorization).
7. **Sells →** proceeds post to cash, units drop on the position; `proceeds − cost basis` is the booked realized gain/loss (a tax event; seeds cap-gains, S11). **Buys →** cash → position at cost, accumulating cost basis.
8. **Unrealized gain is not projected here at all** (M1) — it is a presentation-layer derivation over the `PositionObserved` measurements, computed as-of-date, never posted or reconciled.
9. **Heal / order-independence** (Slice 1) and **identity resolution** (Slice 1.5) apply unchanged.

## Decisions taken (open to veto before build)

- **Cost basis: a single figure per position now, per-lot detail deferred.** We store one `cost_basis` on the position when the statement shows it (graded like any attribute), enough to seed capital-gains and tax later (S11). Per-lot tranche tracking is a large extraction-and-reconciliation surface for the smallest seed; deferred, with the `lots` attribute slot reserved. _(Reconsider only if your real statements carry clean lot detail AND tax is near-term — then capture at read time to avoid a re-ingest.)_
- **Instrument identity is the ticker/name string for now.** No heavy instrument entity-resolution (the Slice-1.5 matcher for securities) yet — tickers are usually clean. Reserve the seam; don't build it.
- **Net-worth composition stays in Slice 7.** S6 makes positions queryable, dated, and classed; summing assets − liabilities into one figure is S7 (a pure projection over what S6 records — zero migration).

## Scope — staged, smallest seed first

The two reconciliations are built in order so each stage stands alone and green:

- **Stage 1 — the holdings snapshot.** Classify → brokerage profile → extract positions + cash + total → the **internal tally** hard gate → emit `PositionObserved` (`measured`, graded) + post cash → holdings queryable with units + value + `as_of` + `class=measured`. This is the minimum that proves the divergent profile and the measurement model.
- **Stage 2 — the cross-account cash flow.** Tie contributions/withdrawals to checking/savings via Slice-3 links (counted once); recognize dividends/interest as income and fees as expense from the statement lines; compute realized gain on sells (a cash/tax event). Unrealized gain stays out of the ledger — it's a presentation-layer as-of-date derivation over the position measurements (M1), landing with the presentation slice.

Cost basis: a single graded figure per position, captured when the statement shows it (per-lot deferred). Nothing beyond the two stages.

## Done criteria / tests

**Stage 1 (snapshot):**
- A real brokerage statement reconciles on `Σ market_value + cash = total` and posts; a misread position (units or value) fails the internal tally and is **held with a localized Finding**, never guessed.
- A `PositionObserved` carries units + market_value + currency + `as_of` + `class=measured` + grade + provenance; the answer/surface shows a holding as "as of {date}," never "current."
- Cost basis is stored when the statement shows it and absent (not invented) when it doesn't.
- The account's composed value = cash + Σ latest measured positions; registering a *synthetic* investment type via a profile row alone routes to the brokerage parser/identity (the divergent-profile proof holds).

**Stage 2 (flow):**
- A checking→brokerage contribution auto-links (Slice 3), is **counted once**, and is excluded from spending, in either ingest order; an unmatched inflow surfaces a `suggested` transfer.
- A cash dividend also present in checking is counted once; a fee lands as an expense; a sell posts proceeds to cash, drops the units, and books `proceeds − cost basis` as realized gain.
- **Unrealized gain is never posted or reconciled** (M1); it is computed on demand from the position measurements, as-of-date, and a stale figure is labeled as such (X2) — asserted by a projection/presentation test, not a ledger event.

Existing balance-family, pay-stub, transfer, and categorization tests stay green throughout.

## Deferred (explicitly not now)

Live price feeds (`valued`) and any "current" valuation; per-lot cost basis; instrument entity-resolution; options/derivatives and non-equity instruments beyond a priced line; FX on foreign holdings (S11); net-worth composition (S7); performance/return analytics.

## Why now + future use

The biggest missing net-worth component, and the first place the **valuation-class discipline** is set — a trust-critical invariant against dressing guesses (or stale prices) as facts, inherited by every future asset. It's the second real payoff of the divergent-profile architecture (its own schema + identity as *data*, proven by Slice 4), reuses Slice 3 corroboration for dividends and Slice 1/1.5 for order-independence and identity, and its cost-basis seed is the precursor to Tax (S11). Positions recorded honestly and dated are the direct precursor to net worth (S7) and, eventually, the provable claim bundle (S13).
