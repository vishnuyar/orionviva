# Net Worth — a curve, not a number

**State:** built
**Rules:** MON-85, MON-86, MON-87, MON-88, MON-89, MON-24, MON-25, MON-26, MON-27, MON-28

**Invariants touched:** **T1** · **T2** · **T4** · **M1** · **X2** · principle 2 · principle 7.

## Rules

### MON-85 — net worth is a curve, defined at every date in range
**State:** enforced
**Code:** product/viva/ledger/networth.py (`net_worth`, `change_dates`, `series`)
**Test:** product/tests/test_networth.py::test_one_statement_gives_one_point

1. `net_worth(D)` is defined for any `D` between the earliest and latest dated observation, and is evaluated at every date where something changed — a statement closed, a holding was measured, a ruling was made.
2. A depository or liability account contributes the observed closing balance the issuer attested, not a sum of the ledger's own postings.
3. An investment account contributes **one line per currency**: its cash plus the holdings carried on its latest statement at or before `D` — one snapshot, not each instrument's own latest measurement (product/viva/ledger/projection/positions.py:174, product/tests/test_networth.py::test_a_holding_the_newest_statement_no_longer_lists_is_no_longer_held).
4. An account a ruling brought into being contributes **cost at the ruling's date** for a purchased asset, or signed outstanding principal for a loan receivable—never an invented present-day market value.
5. An account with no measurement at or before `D` contributes nothing — no zero (product/tests/test_networth.py::test_an_account_contributes_nothing_before_its_first_measurement).
6. An earlier point never moves when a later document arrives (product/tests/test_networth.py::test_a_later_document_does_not_move_an_earlier_point).

### MON-24 — the side is decided by the account's kind, never by the sign of a balance
**State:** enforced
**Code:** product/viva/ledger/networth.py (`_side`)
**Test:** product/tests/test_networth.py::test_a_card_lands_on_the_liability_side

1. A liability's balance is money owed, stored as a positive magnitude, and its contribution is `-balance`.
2. It is negated, never absolute-valued, so an overpaid card is an asset (product/tests/test_networth.py::test_an_overpaid_card_is_an_asset_not_a_debt).

### MON-25 — a liability's own magnitude is emitted as `owed`, never as `balance`
**State:** enforced
**Code:** product/viva/tools/ledger_common.py:149 (`_measure_of`), product/viva/tools/ledger_aggregates.py:368 (`_PART_MEASURES`), :444 (`_line_word`), product/viva/quantity.py:46
**Test:** product/tests/test_tool_contract.py::test_no_read_states_what_is_owed_as_what_is_held, product/tests/test_shape_binding.py::test_what_is_owed_cannot_fill_a_hole_that_asked_for_what_is_held

1. Every read that emits a liability's own magnitude — the balances read, a net-worth line, the liabilities subtotal, the provenance read — names it `owed`.
2. A subtotal declares what its side measures however few accounts are in it: `assets` declares `balance` even in a vault whose only account is an overpaid card.
3. `owed` carries the convention the bill prints, so an overpaid card is emitted negative and means it, and one card is the same figure from every read.
4. A debt added to a deposit refuses, and a net worth assembled by hand out of the two sides refuses (product/tests/test_tool_compute.py::test_what_is_owed_does_not_add_to_what_is_held).
5. A clause asking about a balance cannot be filled with a debt; the binding refuses.

### MON-86 — trust the person; provable-versus-not is an audience question
**State:** enforced
**Code:** product/viva/ledger/networth.py (`NetWorthLine.provable`, `NetWorthPoint.by_currency`)
**Test:** product/tests/test_networth.py::test_both_figures_are_reported_the_whole_total_and_the_provable_part

1. The personal view includes everything the person stated, at their word, badged with its grade.
2. The provable subtotal is the sum of `corroborated` lines only, derived rather than stored.

### MON-87 — two different unknowns, and only one is a trust problem
**State:** enforced
**Code:** product/viva/ledger/networth.py (`_asserted_lines`, `_asserted_asset_lines`, `_gap_for`); product/viva/ledger/projection/rulings.py (`ruled_accounts.reliable_balance`)
**Test:** product/tests/test_networth.py::test_a_liability_from_cash_flow_alone_is_refused_and_named

1. An asserted purchased asset whose cost the person stated is a line at cost; an asserted loan receivable is a line at signed outstanding principal. Both are graded `verified`, origin `asserted`.
2. An asserted asset nobody has priced is neither counted nor hidden: it appears in `missing` with the question that closes it, and the point reads incomplete.
3. Where the schema pack cannot yet ask about the kind at all, that is said plainly rather than the asset being omitted.
4. A liability is never valued from cash flow alone — money reaching a lender says nothing about the balance owed — so it goes to `missing` with the ask and the document that would answer it.
5. A movement ruled `mixed` makes its account's figure unreliable, and an unreliable figure never enters a sum.
6. A stated cost **replaces** the cash-derived line for that account rather than adding to it.

### MON-88 — reuse the grade ladder; do not invent an issued/asserted badge
**State:** enforced
**Code:** product/viva/ledger/networth.py (`NetWorthLine.provable` reads `grade == corroborated`)
**Test:** product/tests/test_networth.py::test_provable_is_the_existing_grade_not_a_new_badge

1. "Provable" is the existing grade `corroborated`: the attesting document is held and the arithmetic checks.
2. `origin` stays on the account and answers who says the account exists; the grade answers whether a figure can be proved.

### MON-89 — subtotal per currency; never convert
**State:** enforced
**Code:** product/viva/ledger/networth.py (`NetWorthPoint.by_currency`)
**Test:** product/tests/test_networth.py::test_two_currencies_give_two_subtotals_and_no_grand_total, product/tests/test_tool_contract.py::test_net_worth_currency_view_keeps_only_the_direct_net_figures, product/tests/test_shape_rows.py::test_net_worth_by_currency_is_one_homogeneous_block

1. Net worth reports per-currency subtotals and no grand total.
2. No conversion happens anywhere until a rate has a source, a date and a grade of its own.
3. The currency-row read emits only those net-worth subtotals, not the asset, liability or per-account audit figures the ordinary read retains, and it still names every account it could not measure by its visible name.

### MON-26 — every point names its stalest input, and a composed line says when its parts differ
**State:** enforced
**Code:** product/viva/ledger/networth.py (`NetWorthPoint.oldest_input`); product/viva/ledger/projection/positions.py (`as_of`, `mixed_vintage`)
**Test:** product/tests/test_networth.py::test_every_point_names_its_stalest_input

1. A point carries the as-of of the stalest measurement in it.
2. A line composed of several measurements is dated by the oldest of them, graded by the weakest of them, and says when they were not all measured on one day (product/tests/test_networth.py::test_a_value_of_several_days_says_so_wherever_it_is_stated).

### MON-27 — incompleteness is stated, never absorbed
**State:** enforced
**Code:** product/viva/ledger/networth.py (`NetWorthPoint.complete`, `net_worth` missing/skipped/held)
**Test:** product/tests/test_networth.py::test_a_point_is_not_complete_while_a_document_sits_held

1. A point is incomplete while anything known to be owed has no usable figure, or while a read document sits unposted.
2. An account the point cannot value is named with the reason, never dropped (product/tests/test_networth.py::test_an_account_it_cannot_value_is_named_not_dropped).
3. An empty vault reports absence rather than zero (product/tests/test_networth.py::test_an_empty_vault_reports_absence_not_zero).

### MON-28 — cost is never presented as value, and no model is involved
**State:** by-review
**Code:** product/viva/ledger/networth.py (`_asserted_lines`, `_stated_cost`, `_gap_for`); product/viva/ledger/projection/rulings.py (`ruled_accounts`)
**Test:** none

1. An asserted purchased asset holds what was paid; a loan receivable holds signed outstanding principal. Any present-day market worth would be an `estimated` layer on top and is not built.
2. The gap a point discloses is about what a thing cost, never about what it is worth today.
3. Net worth is arithmetic over recorded measurements end to end.

## Why

The as-of problem looked like a choice between one coherent date (pure but stale), latest-known-per-account (current but never true at any instant), or both. All three assume net worth is a number that needs a date attached. It is not: it is a **curve**, and asking "what is my net worth?" is asking for a point on it. That dissolves the problem rather than answering it — there is no *the* net worth to be wrong about — and it falls straight out of what the ledger already is, an append-only log of dated observations, so it needs no event type and no new machinery, and hands over trends for free.

The residue is named rather than hidden. At any point, some accounts' last measurement may be months older than the point itself. That is a real limitation, so every point carries the age of its oldest input, and the curve visibly firms up as documents arrive — the product telling the truth about its own coverage.

One account is one line because a person owns one account, and its value is its cash plus what it holds. An earlier shape gave a brokerage two or more lines, one of them under a sub-account path that exists nowhere else, so a point cited an identifier the same read could not resolve. Composing per-instrument latest values is worse than a cosmetic error: an instrument that appeared on an older statement and is absent from the newer one would keep contributing its old value forever. A brokerage statement states everything the account holds on its date, so one snapshot answers both halves at once — an earlier point still uses the statement that was current then, and a holding the newest statement no longer lists is no longer held. Holdings in a currency the cash is not in still keep a line of their own, because nothing here converts.

The side rule is written down because the first implementation got it backwards, from a docstring that asserted liabilities were "already negative" — inferred from defensive `abs()` calls in the answer path instead of read from the one comment stating the convention. On a real vault two cards were added to **assets**, and the report printed `liabilities 0.00` directly beneath two lines labelled `[liability]`. The test agreed with the code because the fixture fed a negative closing balance: one wrong assumption held in both places, so the suite confirmed the bug rather than catching it. The transferable half is not about liabilities — **`abs()` erases the one bit that matters**, and it has now done so twice in unrelated code: here, turning two debts into assets, and in the merchant view, where wrapping every amount before summing added both directions of a transfer together. Reach for `abs()` and the question is what direction is being discarded, and who was relying on it.

How a figure is stored is half of it; the other half is what travels beside it when it leaves. Naming a liability's magnitude `owed` in the closed vocabulary means two things follow without anyone remembering them: a debt added to a deposit refuses, and a net worth assembled by hand out of the two sides refuses, which leaves the read that is complete on its own and knows what it left out.

*"Trust the user, he has no incentive to lie. But in the future when a credit agent asks, we state what is provable and what is not."* Two views over one set of data — the personal one now, the disclosure one later — is the decision that makes the honesty machinery cost nothing today, because the grade is already recorded and the disclosure view is a one-line filter.

The two unknowns are genuinely different. **Asserted**: you told us the car cost X, nobody issued a document — trust it, include it, badge it. **Undecomposable**: cash reached the mortgage servicer, and how much of it reduced the debt rather than paying interest is unknown — trusting you produces no number here, because you do not know either; only the statement does. So: ask, record the answer as `asserted` with its own as-of date, and let the 1098 or the mortgage statement later *upgrade* it to `corroborated` rather than unlock it. Until then the liability appears with its amount unknown and the total is marked incomplete — knowingly too favourable, and saying so. A missing document must never block an answer, and must never be silently absorbed either. A stated cost replaces the cash-derived line because the sum of the instalments paid so far is not what the thing cost.

Adding a parallel `issued`/`asserted` vocabulary for net worth would be two systems describing one fact — precisely the bug that inflated the spending figure before honest aggregates, where a transfer link and a category both described one movement and the aggregate listened to only one.

One financial life can hold several currencies (I1), and there is no FX source with provenance, so a converted total would be a figure no document attests: a bluff by construction.

## Open

- The **disclosure view** — the corroborated subset only, the figure a counterparty could be shown — is unbuilt. It is this projection with one filter, which is the whole point of settling MON-86 and MON-88 early: the endgame primitive, proving a claim to a counterparty without revealing more than the claim, arrives as a filter over a projection rather than as a subsystem.
- Market valuation of asserted assets needs a price source with provenance and is unbuilt.
- FX conversion is unbuilt (MON-89).
- Per-lot cost basis is unbuilt.
- The curve ends at the last document and does not extrapolate; nothing projects forward in time.
- Charts belong to a real presentation layer, not the debug one.
