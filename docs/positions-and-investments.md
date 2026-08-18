# Positions & Investments

**State:** built
**Rules:** MON-29, MON-30, MON-31, MON-32, MON-33, MON-34, MON-35, MON-36

**Invariants touched:** T1 · T2 · T3 · **T4** · **M1** · I5 · **the valuation-class invariant** · **X2** · the grade ladder.

## Rules

### MON-29 — a holding is a dated measurement, never a posting
**State:** enforced
**Code:** product/viva/ledger/events.py:659 (`position_observed`); product/viva/ingest/pipeline.py:616 (`post_brokerage`)
**Test:** product/tests/test_brokerage.py::test_brokerage_reconciles_and_records_positions_as_measurements

1. A holding is recorded as `PositionObserved` — instrument, units, market value, currency, `as_of`, grade, provenance — and is not posted to the money ledger.
2. Only realized cash events post: buys, sells, dividends, interest, fees, sweeps, contributions and withdrawals.
3. Unrealized gain is never posted, never reconciled and never an event; it is derived at read time from the measurements on hand (product/viva/ledger/projection/positions.py:257, product/tests/test_brokerage.py::test_unrealized_gain_is_a_derived_as_of_view_not_a_ledger_fact).
4. Measurements are append-only: a later statement emits a new observation for the same instrument and edits nothing (product/tests/test_brokerage.py::test_a_later_statement_revalues_the_same_holding).
5. Positions emit only the `measured` valuation class, and a position value is surfaced with its as-of date, never as "current".
6. If a statement prints a "change in value" line, presentation may show our derived number beside it; the ledger never reconciles against it (product/viva/ingest/brokerage.py:90 — the read carries positions, cash and the stated total, and no such figure; the two identities are product/viva/ingest/pipeline.py:644 and :681).

### MON-30 — the internal tally is a hard gate
**State:** enforced
**Code:** product/viva/ingest/pipeline.py:644 (`check_brokerage_identity` in `post_brokerage`); product/viva/ingest/registry.py:30 (`BROKERAGE_IDENTITY`)
**Test:** product/tests/test_brokerage.py::test_a_misread_holding_fails_the_tally_and_is_held

1. `Σ position market_value + cash = stated total`, deterministic `Decimal` arithmetic, no model.
2. A failure holds the statement with a localized finding through the same forced/suggested/held contract as every other identity; nothing is guessed.
3. A different-shaped investment type registered by a profile row alone routes to this parser and this identity.

### MON-31 — the cash flow reconciles when the statement reports it
**State:** enforced
**Code:** product/viva/ingest/pipeline.py:681 (`check_balance_identity` over the activity)
**Test:** product/tests/test_brokerage.py::test_cash_flow_reconciles_and_recognizes_income_fees_gains

1. The flow path runs when a statement carries both an opening cash figure and an activity list: the opening is booked once, each activity item posts, and the closing is observed.
2. Where the statement omits the opening, the previous statement's closing cash carries forward rather than the activity being discarded (product/tests/test_brokerage.py::test_opening_cash_carries_forward_when_the_statement_omits_it).
3. A cash flow that does not reconcile holds the statement and says the activity is held back (product/tests/test_brokerage.py::test_cash_flow_mismatch_is_held).
4. A holdings-only statement falls back to the snapshot path, with cash observed as a lone attested balance.

### MON-32 — activity counter-legs, and a contribution counted once
**State:** enforced
**Code:** product/viva/ledger/postings.py:94 (the counter-leg map), :121 (`brokerage_activity_transaction`)
**Test:** product/tests/test_brokerage.py::test_a_contribution_ties_to_the_funding_account

1. Contribution and withdrawal post to `Transfers:Uncategorized` and tie to the funding account by a cross-document transfer link, so the money is counted once and excluded from spending.
2. Dividend and interest post to income; a fee posts to an expense; a buy and a sell move cash to and from invested capital, and a statement-reported realized gain posts as income.
3. Realized gain is taken from the statement's reported figure, not computed from lot basis.

### MON-33 — a holdings figure is one snapshot, not a composition across statements
**State:** enforced
**Code:** product/viva/ledger/projection/positions.py:45 (`snapshot_positions`)
**Test:** product/tests/test_networth.py::test_a_holding_the_newest_statement_no_longer_lists_is_no_longer_held

1. A holdings figure sums the measurements carried on the newest statement date at or before the date asked about.
2. An instrument the newest statement does not list is not held, and does not contribute.
3. The projection keeps a latest-per-instrument view beside the full history; no holdings figure and no net-worth point reads it.

### MON-34 — one composition, dated by the oldest and graded by the weakest
**State:** enforced
**Code:** product/viva/ledger/projection/positions.py:174 (`composed_values`), :110 (`_composed_grade`)
**Test:** product/tests/test_networth.py::test_one_account_reads_the_same_from_every_read_that_states_it

1. An account's value is computed in one function, and every read that states an account's value calls it.
2. The value is dated by the oldest measurement it rests on, graded by the weakest of them with cash included, and says when the parts were not measured on one day.
3. A term nothing graded leaves the value with no grade at all rather than a weak one (product/tests/test_networth.py::test_a_value_with_a_term_nothing_graded_carries_no_grade).
4. Holdings in a currency the cash is not in are a second value, not a bigger number.

### MON-35 — the sweep is cash, decided by which reading closes the tally
**State:** enforced
**Code:** product/viva/ingest/brokerage.py:169 (`resolve_sweep_cash`)
**Test:** product/tests/test_brokerage.py::test_sweep_counted_once_when_the_cash_line_already_includes_it

1. Both readings are tried — the cash line includes the sweep, or excludes it — and the one whose tally closes exactly is taken.
2. Neither reading closing means nothing is decided and the ordinary gate holds the statement (product/tests/test_brokerage.py::test_a_sweep_that_reconciles_neither_way_is_still_held).
3. The result is normalized so cash always includes the sweep, and the projector and the claims diagnostic share the one implementation.
4. A cash row recorded as a holding is folded into the account's cash on read (product/tests/test_brokerage.py::test_a_legacy_cash_position_self_corrects_on_read).

### MON-36 — an optional field that cannot be read is unknown, never fatal
**State:** enforced
**Code:** product/viva/ingest/brokerage.py:234 (`from_brokerage_json`)
**Test:** product/tests/test_brokerage.py::test_missing_cost_basis_is_absent_not_invented

1. Cost basis and realized gain degrade to unknown when a statement prints something unparseable.
2. Units, market value, cash and the stated total do not degrade, because the reconciliation identity rests on them.
3. Cost basis is stored when the statement shows it and absent, never invented, when it does not.

## Why

Every other document reconciles a **flow** — money moved and a posting recorded it. A brokerage statement breaks that: an account can go from one figure to a larger one with no money moving, because the market repriced holdings already owned. That change is a **revaluation, not a transaction**.

So a holding is recorded the way a closing balance is recorded — measured, not posted — and only real cash flows post. This is a thesis decision rather than a modeling convenience. The claim is that personal financial records are clean *because they are measurements, not generations*. Posting each price change against an unrealized-gain account would manufacture money-movement events for changes that were never movements, and would force a fabricated price onto every date. Keeping the money ledger pure cash flow keeps it aligned with reality and with tax (M1).

The brokerage account is a reconciliation hub checked two independent ways, and together they separate *contributed* growth from *market* growth — the honest heart of "how are my investments doing?". The internal tally is a **snapshot cross-check** over many numbers the statement itself asserts, which makes it the densest verification surface in the system and entirely model-free; a single misread position fails it loudly. The cross-account cash flow ties each realized component to how it is already recorded: a contribution links to its funding account so it is counted once and never spending, a dividend visible in checking corroborates across issuers, a fee is an expense, a sell books proceeds and a realized gain.

Unrealized gain is deliberately absent from both. It is not cash and not a tax event, so it is never posted, never a gate, never an event; it lives as a derived as-of-date figure labelled with its date under the valuation-class rule. That is what dissolves any "should we gate the market change?" question — there is nothing to gate, because the paper change is not a ledger fact.

The valuation class is the invariant, not the field: a position value is surfaced as a figure *as of a date*, never bare, and every future asset — property, vehicles, a price feed's `valued`, an `estimated` guess — inherits that discipline.

Composing per-instrument latest values is the mistake the snapshot rule exists to prevent: an instrument that appeared on an older statement and is absent from the newer one would keep contributing its old value forever, and one instrument written two ways would count twice. A brokerage statement states everything the account holds on its date, so one snapshot answers both halves at once.

Three things real statements taught, kept because they were not obvious. A brokerage account's "cash" is usually a money-market fund, and the *same* account printed it two ways in consecutive months — one where the cash line **was** the sweep, one where it excluded a separately-listed sweep. Treating it as a holding double-counts in the first case; treating it as cash under-counts in the second, so the tally decides, decisive-or-hold, and the figure is normalized so it means the same thing across statements, which is what lets the cash flow stitch month to month. A real December statement printed no opening cash, which would have silently discarded two dozen activity items including a contribution from the person's own checking account — the ledger already knew the opening, because it is the previous statement's closing, which is the heal cascade's forward-stitching rule applied to brokerage cash. And options needed no work at all: real holdings included short puts and calls with negative units and negative market values, and the measurement model absorbed them unchanged, so the caution about derivatives was more than was needed.

Refusing a figure means declining to *use* it, not discarding the document that carried it. A real statement printed a cost basis of "not applicable", and strict parsing threw away the whole statement — every position, the cash line, the tally — over one field nothing depends on. That is why an optional field degrades and a load-bearing one does not.

Instrument identity is the ticker or name string, with no entity resolution behind it; the seam is reserved rather than built, because tickers are usually clean. Cost basis is one figure per position, enough to seed capital gains later, because per-lot tranche tracking is a large extraction-and-reconciliation surface for the smallest seed.

Summing assets minus liabilities into one figure is not this document's job — that is [net-worth.md](net-worth.md), a pure projection over what positions record.

## Open

- An investment **fee** lands in the `Expenses:Fees` account balance but not in the movement-based spending view, which is scoped to depository and liability legs. Consumer spending stays clean; investment costs are visible in the account.
- Full gap and heal hardening for brokerage cash across many statements is deferred; multi-period stitching is handled lightly by the shared balance identity.
- Live price feeds and any `valued` or "current" valuation are unbuilt.
- Per-lot cost basis is unbuilt; the `lots` attribute slot is reserved. Reconsider only if real statements carry clean lot detail and tax is near-term, then capture at read time to avoid a re-ingest.
- Instrument entity resolution is unbuilt.
- FX on foreign holdings and performance or return analytics are unbuilt.
