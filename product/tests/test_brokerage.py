"""Brokerage holdings as dated measurements.

A brokerage statement reconciles on the snapshot identity (Σ market_value + cash =
total), its holdings are recorded as PositionObserved MEASUREMENTS (never posted),
the account value composes cash + positions, unrealized gain is a derived as-of
view, and a misread holding is held — never guessed."""

from decimal import Decimal

import pytest

from viva.ingest import (BrokerageActivity, BrokerageFacts, PositionFact,
                        ReadResult, RawStore, StatementFacts, TxnFact,
                        capture_and_ingest)
from viva.ledger import EventStore, Ledger, LedgerProjection


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.97, f)


def _brokerage(positions, cash, total, tmp_path, as_of="2026-03-31",
               number="000000003311"):
    """Ingest a brokerage statement through the real pipeline (facts injected)."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    facts = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of=as_of,
        cash=Decimal(cash), total=Decimal(total),
        positions=[PositionFact(instrument=i, units=Decimal(u),
                                market_value=Decimal(v),
                                cost_basis=(Decimal(c) if c is not None else None))
                   for i, u, v, c in positions],
        account_number=number, institution="Fidelity")
    res = capture_and_ingest(raw, ledger, b"brk-" + as_of.encode(),
                             lambda data, did: _stamp(facts, did),
                             captured_at="2026-04-02")
    return ledger, res


def test_brokerage_reconciles_and_records_positions_as_measurements(tmp_path):
    ledger, res = _brokerage(
        [("AAPL", "100", "18400.00", "12000.00"),
         ("VTSAX", "50", "6600.00", "5000.00")],
        cash="1000.00", total="26000.00", tmp_path=tmp_path)
    assert res.action == "posted" and res.grade == "corroborated"

    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos()]
    assert proj.account_info(acct).kind == "investment"
    # Holdings are measurements, not postings — no movements, no spending.
    assert proj.movements() == []
    assert proj.spending_by_category() in ({}, {})
    # Positions recorded, dated, class=measured.
    positions = proj.positions()
    assert {p.instrument for p in positions} == {"AAPL", "VTSAX"}
    aapl = next(p for p in positions if p.instrument == "AAPL")
    assert aapl.units == Decimal("100") and aapl.market_value == Decimal("18400.00")
    assert aapl.valuation_class == "measured" and aapl.as_of == "2026-03-31"
    # Account value composes cash + holdings.
    assert proj.account_value(acct) == Decimal("26000.00")
    # The measurements are self-contained on replay (no live objects needed).
    replayed = LedgerProjection(ledger.events())
    assert replayed.account_value(acct) == Decimal("26000.00")


def test_unrealized_gain_is_a_derived_as_of_view_not_a_ledger_fact(tmp_path):
    ledger, _ = _brokerage(
        [("AAPL", "100", "18400.00", "12000.00"),
         ("VTSAX", "50", "6600.00", "5000.00")],
        cash="1000.00", total="26000.00", tmp_path=tmp_path)
    proj = ledger.projection()
    # (18400-12000) + (6600-5000) = 6400 + 1600 = 8000, computed on demand.
    assert proj.unrealized_gain() == Decimal("8000.00")
    aapl = next(p for p in proj.positions() if p.instrument == "AAPL")
    assert aapl.unrealized_gain() == Decimal("6400.00")
    # It is NEVER an event in the ledger (cash-flow over accrual).
    types = {e.event_type for e in ledger.events()}
    assert "PositionObserved" in types
    assert not any("nrealized" in t or "Gain" in t for t in types)


def test_missing_cost_basis_is_absent_not_invented(tmp_path):
    ledger, _ = _brokerage([("BND", "20", "1600.00", None)],
                           cash="0.00", total="1600.00", tmp_path=tmp_path)
    proj = ledger.projection()
    bnd = proj.positions()[0]
    assert bnd.cost_basis is None
    assert bnd.unrealized_gain() is None          # nothing to compare → not zero
    assert proj.unrealized_gain() is None          # no basis anywhere


def test_a_misread_holding_fails_the_tally_and_is_held(tmp_path):
    # positions + cash = 25000, but the statement's stated total is 26000.
    ledger, res = _brokerage(
        [("AAPL", "100", "18400.00", "12000.00"),
         ("VTSAX", "50", "5600.00", "5000.00")],
        cash="1000.00", total="26000.00", tmp_path=tmp_path)
    assert res.action == "conflict" and res.grade == "conflicted"
    proj = ledger.projection()
    assert proj.positions() == []                  # nothing recorded on a bad tally
    assert len(proj.open_holds()) == 1


def test_a_later_statement_revalues_the_same_holding(tmp_path):
    ledger, _ = _brokerage([("AAPL", "100", "18400.00", "12000.00")],
                           cash="0.00", total="18400.00", tmp_path=tmp_path,
                           as_of="2026-03-31")
    # Q2: AAPL repriced up; same account (same number), later date.
    raw = None
    facts = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of="2026-06-30",
        cash=Decimal("0.00"), total=Decimal("20000.00"),
        positions=[PositionFact("AAPL", Decimal("100"), Decimal("20000.00"),
                                Decimal("12000.00"))],
        account_number="000000003311", institution="Fidelity")
    from viva.ingest import RawStore as _RS
    # reuse the same vault dir so it's the same account
    r2 = _RS.open(tmp_path / "raw", "pw")
    capture_and_ingest(r2, ledger, b"brk-q2",
                       lambda data, did: _stamp(facts, did), captured_at="2026-07-02")
    proj = ledger.projection()
    aapl = next(p for p in proj.positions() if p.instrument == "AAPL")
    assert aapl.market_value == Decimal("20000.00")   # latest measurement wins
    assert aapl.as_of == "2026-06-30"
    assert proj.unrealized_gain() == Decimal("8000.00")  # 20000 - 12000, derived


def test_a_cash_row_is_cash_not_a_holding(tmp_path):
    """A position row named CASH is the account's cash, not a holding. The tally
    passes either way, so no gate catches it."""
    ledger, res = _brokerage(
        [("CASH", "15507.13", "15507.13", None),
         ("AAPL", "10", "117.36", None)],
        cash="0.00", total="15624.49", tmp_path=tmp_path)
    assert res.action == "posted"
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos()]
    # CASH is not a holding...
    assert [p.instrument for p in proj.positions()] == ["AAPL"]
    # ...it's the account's cash, and the total is unchanged.
    assert proj.cash_value(acct) == Decimal("15507.13")
    assert proj.account_value(acct) == Decimal("15624.49")


def test_a_legacy_cash_position_self_corrects_on_read(tmp_path):
    """A vault holding PositionObserved(CASH) events has them reinterpreted as
    cash on the next query — no re-ingest, no model cost, nothing rewritten
    (the read-side payoff)."""
    from viva.ledger.events import position_observed
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    # Simulate the legacy shape directly: a cash row recorded as a holding.
    from viva.ledger.events import account_opened, closing_balance_observed
    ledger.append(account_opened("acct:x", "investment", "Broker X", "USD",
                                 "2026-03-31"))
    ledger.append(closing_balance_observed("acct:x", "0.00", "2026-03-31"))
    ledger.append(position_observed("acct:x", "CASH", "15507.13", "15507.13",
                                    "USD", "2026-03-31"))
    ledger.append(position_observed("acct:x", "SPAXX", "117.36", "117.36",
                                    "USD", "2026-03-31"))
    proj = ledger.projection()
    assert [p.instrument for p in proj.positions()] == ["SPAXX"]   # CASH isn't a holding
    assert proj.cash_value("acct:x") == Decimal("15507.13")        # it's cash
    assert proj.holdings_value("acct:x") == Decimal("117.36")
    assert proj.account_value("acct:x") == Decimal("15624.49")     # total unchanged


def test_a_composed_value_reports_its_oldest_as_of(tmp_path):
    """A value summed from measurements of different dates carries the oldest of
    them and reports that its parts differ.

    The cash here is attested in March and the securities measured in June, so
    the value is a March figure."""
    from viva.ledger.events import (account_opened, closing_balance_observed,
                                    position_observed)
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    ledger.append(account_opened("acct:mixed", "investment", "Broker", "USD",
                                 "2026-01-01"))
    ledger.append(closing_balance_observed("acct:mixed", "1000.00", "2026-03-31"))
    ledger.append(position_observed("acct:mixed", "VTSAX", "50", "20000.00",
                                    "USD", "2026-06-30"))
    proj = ledger.projection()
    as_of, mixed = proj.holdings_as_of("acct:mixed")
    assert mixed                                    # cash is March, VTSAX is June
    assert as_of == "2026-03-31"                    # dated by its oldest part
    (value,) = proj.composed_values("acct:mixed")
    assert value.amount == Decimal("21000.00")
    assert value.as_of == "2026-03-31" and value.mixed_vintage


def test_nothing_this_pipeline_records_leaves_a_value_ungraded(tmp_path):
    """A total with a term nothing attested carries no grade at all — a guard
    against a quantity nothing measured being added to one that was. This
    proves it is a guard rather than a live path: every measurement a statement
    ingested here leaves behind arrives graded, so no value composed out of
    them reaches it."""
    ledger, res = _brokerage(
        [("AAPL", "100", "18400.00", "12000.00"),
         ("VTSAX", "50", "6600.00", "5000.00")],
        cash="1000.00", total="26000.00", tmp_path=tmp_path)
    assert res.action == "posted"
    proj = ledger.projection()
    seen = 0
    for info in proj.account_infos():
        for value in proj.composed_values(info.account):
            seen += 1
            assert value.grade, (
                f"{info.account} composed a value out of a term nothing "
                "graded, which the ingest path is not supposed to produce")
    assert seen, "this vault composed no value, so it proves nothing"


def test_a_holding_no_longer_held_does_not_date_the_value(tmp_path):
    """The dates a value carries are the dates of what it is actually summed
    out of. A second statement replaces the first snapshot entirely, so the
    older holding is neither in the figure nor one of its vintages — and cash
    and securities read off one statement are one vintage, which is what the
    tally gate makes true."""
    ledger, _ = _brokerage([("AAPL", "100", "18400.00", None)],
                           cash="1000.00", total="19400.00", tmp_path=tmp_path,
                           as_of="2026-03-31")
    facts = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of="2026-06-30",
        cash=Decimal("1000.00"), total=Decimal("21000.00"),
        positions=[PositionFact("VTSAX", Decimal("50"), Decimal("20000.00"), None)],
        account_number="000000003311", institution="Fidelity")
    r2 = RawStore.open(tmp_path / "raw", "pw")
    capture_and_ingest(r2, ledger, b"brk-q2",
                       lambda data, did: _stamp(facts, did), captured_at="2026-07-02")
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos()]
    as_of, mixed = proj.holdings_as_of(acct)
    assert not mixed                                # AAPL is not held any more
    assert as_of == "2026-06-30"
    assert proj.account_value(acct) == Decimal("21000.00")   # the printed total


# --------------------------------------------------------------- the sweep ---

_SWEEP = "FIDELITY GOVERNMENT MONEY MARKET (SPAXX)"


def test_sweep_counted_once_when_the_cash_line_already_includes_it(tmp_path):
    """November's shape: cash printed as 139.77 AND the sweep listed at 139.77 —
    the same money. Adding both over-counts by exactly the sweep; the reading that
    reconciles is 'the cash line already includes it'."""
    ledger, res = _brokerage(
        [(_SWEEP, "139.770", "139.77", None),
         ("SPXS", "1500", "8760.00", "9323.49"),
         ("COST PUT", "10", "5650.00", "6256.77"),
         ("TSLA PUT SHT", "-1", "-1770.00", "-2788.24"),
         ("TSLA PUT", "1", "4790.00", "5964.68")],
        cash="139.77", total="17569.77", tmp_path=tmp_path)
    assert res.action == "posted"                      # the reading reconciles
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos()]
    assert _SWEEP not in [p.instrument for p in proj.positions()]
    assert proj.cash_value(acct) == Decimal("139.77")   # counted ONCE
    assert proj.account_value(acct) == Decimal("17569.77")
    assert "sweep" in res.message and "counted as cash" in res.message


def test_sweep_added_when_the_cash_line_excludes_it(tmp_path):
    """December's shape, same account: cash 20,998.11 EXCLUDES a separately listed
    sweep of 295.12. Here the sweep must be ADDED — the opposite of November."""
    ledger, res = _brokerage(
        [(_SWEEP, "295.120", "295.12", None),
         ("SPX CALL SHT", "-1", "-9955.00", "-9955.00"),
         ("SPX CALL", "1", "890.00", "1475.67"),
         ("SPXW PUT SHT", "-1", "-8920.00", "-8920.00"),
         ("SPXW PUT", "1", "16370.00", "16370.00"),
         ("NVDA PUT", "10", "8200.00", "5606.69")],
        cash="20998.11", total="27878.23", tmp_path=tmp_path)
    assert res.action == "posted"
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos()]
    # Normalized so cash means the same thing in both months: it includes the sweep.
    assert proj.cash_value(acct) == Decimal("21293.23")   # 20,998.11 + 295.12
    assert proj.account_value(acct) == Decimal("27878.23")


def test_a_sweep_that_reconciles_neither_way_is_still_held(tmp_path):
    """The rule only fires when a reading closes EXACTLY. A genuine misread has no
    reading that works, so it holds — decisive-or-hold, never a fitted answer."""
    ledger, res = _brokerage(
        [(_SWEEP, "100", "100.00", None), ("AAPL", "10", "5000.00", None)],
        cash="50.00", total="9999.99", tmp_path=tmp_path)
    assert res.action == "conflict"
    assert ledger.projection().positions() == []


# --------------------------------------------------------- Stage 2: cash flow

def _flow_facts(doc_id="", number="000000003311"):
    """A brokerage statement WITH opening cash + the period's activity."""
    return BrokerageFacts(
        doc_id=doc_id, doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of="2026-03-31",
        opening_cash=Decimal("1000.00"), cash=Decimal("5080.00"),
        total=Decimal("23480.00"),
        positions=[PositionFact("AAPL", Decimal("100"), Decimal("18400.00"),
                                Decimal("12000.00"))],
        activity=[
            BrokerageActivity("2026-03-02", "contribution", Decimal("5000.00")),
            BrokerageActivity("2026-03-10", "dividend", Decimal("100.00"), instrument="AAPL"),
            BrokerageActivity("2026-03-11", "fee", Decimal("20.00")),
            BrokerageActivity("2026-03-15", "buy", Decimal("3000.00"), instrument="AAPL"),
            BrokerageActivity("2026-03-20", "sell", Decimal("2000.00"),
                              instrument="VTSAX", realized_gain=Decimal("500.00")),
        ],
        account_number=number, institution="Fidelity")


def test_cash_flow_reconciles_and_recognizes_income_fees_gains(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    facts = _flow_facts()
    res = capture_and_ingest(raw, ledger, b"brk-flow",
                             lambda data, did: _stamp(facts, did),
                             captured_at="2026-04-02")
    assert res.action == "posted"
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos() if i.kind == "investment"]

    # Cash is a reconciled flow: 1000 opening + (5000+100-20-3000+2000) = 5080.
    ba = proj.balance(acct)
    assert ba.amount == Decimal("5080.00") and ba.grade == "corroborated"
    # Dividend + realized capital gain are recognized income (fee/buy are not).
    assert proj.income_by_currency() == {"USD": Decimal("600.00")}  # 100 + 500
    # Fee is an expense; buys/sells move cash to/from invested capital (not spend).
    assert proj.balance("Expenses:Fees").amount == Decimal("20.00")
    assert proj.balance("Assets:Investments").amount == Decimal("1500.00")  # 3000 - 1500
    # Total value still composes cash + holdings and equals the stated total.
    assert proj.account_value(acct) == Decimal("23480.00")
    # Self-contained on replay.
    assert LedgerProjection(ledger.events()).account_value(acct) == Decimal("23480.00")


def test_a_contribution_ties_to_the_funding_account(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    # A checking statement with a $5,000 transfer out to the brokerage.
    checking = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Checking", currency="USD",
        opening_amount=Decimal("10000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("5000.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-02", "Transfer to Fidelity", Decimal("-5000.00"))],
        account_number="000000001122", institution="Chase")
    capture_and_ingest(raw, ledger, b"chk",
                       lambda data, did: _stamp(checking, did), captured_at="2026-04-01")
    # A brokerage statement whose only activity is that $5,000 contribution.
    brk = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of="2026-03-31",
        opening_cash=Decimal("0.00"), cash=Decimal("5000.00"),
        total=Decimal("5000.00"), positions=[],
        activity=[BrokerageActivity("2026-03-02", "contribution", Decimal("5000.00"))],
        account_number="000000003311", institution="Fidelity")
    capture_and_ingest(raw, ledger, b"brk",
                       lambda data, did: _stamp(brk, did), captured_at="2026-04-02")

    proj = ledger.projection()
    # The transfer is recognized: the checking outflow and the brokerage inflow
    # are one movement, counted once.
    assert len(proj.transfer_links()) == 1
    linked = proj.linked_keys()
    checking_out = next(m for m in proj.movements()
                        if m.kind == "depository" and m.amount < 0)
    assert checking_out.key in linked
    # And so it is NOT spending — the $5,000 doesn't inflate checking outflow.
    assert proj.spending_by_category().get("Uncategorized", Decimal("0")) == Decimal("0")


def test_opening_cash_carries_forward_when_the_statement_omits_it(tmp_path):
    """A statement printing no opening cash would otherwise have its whole
    activity list silently dropped. The ledger already knows the opening — it is
    the previous statement's closing cash, forward-stitched."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    # November: closes with 200.00 cash.
    nov = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity", currency="USD", as_of="2026-11-30",
        cash=Decimal("200.00"), total=Decimal("200.00"), positions=[],
        account_number="000000003311", institution="Fidelity")
    capture_and_ingest(raw, ledger, b"nov", lambda d, i: _stamp(nov, i),
                       captured_at="2026-12-01")
    # December: NO opening cash printed, but activity that reconciles from 200.
    dec = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity", currency="USD", as_of="2026-12-31",
        opening_cash=None, cash=Decimal("1650.00"), total=Decimal("1650.00"),
        positions=[],
        activity=[
            BrokerageActivity("2026-12-02", "contribution", Decimal("1500.00"),
                              description="Eft Funds Received"),
            BrokerageActivity("2026-12-31", "dividend", Decimal("10.00")),
            BrokerageActivity("2026-12-31", "fee", Decimal("60.00")),
            BrokerageActivity("2026-12-15", "sell", Decimal("1000.00")),
            BrokerageActivity("2026-12-16", "buy", Decimal("1000.00")),
        ],
        account_number="000000003311", institution="Fidelity")
    res = capture_and_ingest(raw, ledger, b"dec", lambda d, i: _stamp(dec, i),
                             captured_at="2027-01-02")
    assert res.action == "posted"
    assert "5 activity item(s) posted" in res.message     # nothing dropped
    proj = ledger.projection()
    (acct,) = [i.account for i in proj.account_infos() if i.kind == "investment"]
    assert proj.balance(acct).amount == Decimal("1650.00")   # 200 + 1500 + 10 - 60
    assert proj.income_by_currency() == {"USD": Decimal("10.00")}


def test_activity_is_never_dropped_in_silence(tmp_path):
    """If the flow still can't be reconciled, the result SAYS the activity is held
    back — an incomplete picture must be visibly incomplete, not quiet."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    facts = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity", currency="USD", as_of="2026-12-31",
        opening_cash=None, cash=Decimal("500.00"), total=Decimal("500.00"),
        positions=[],
        activity=[BrokerageActivity("2026-12-02", "contribution", Decimal("100.00"))],
        account_number="000000003311", institution="Fidelity")
    res = capture_and_ingest(raw, ledger, b"lone",
                             lambda d, i: _stamp(facts, i), captured_at="2027-01-02")
    assert res.action == "posted"
    assert "not posted" in res.message and "1 activity item" in res.message


def test_a_held_brokerage_statement_does_not_break_the_sweep(tmp_path):
    """Holds are polymorphic: a held brokerage statement has no opening_amount,
    so a consumer that rebuilds every conflict-hold as a StatementFacts dies on
    it. Consumers must route on the registry, not on the shape of the dict."""
    from viva.ingest import held_items, other_holds, sweep
    # A brokerage statement whose tally fails -> held as a conflict.
    ledger, res = _brokerage([("AAPL", "10", "100.00", None)],
                             cash="0.00", total="999.99", tmp_path=tmp_path)
    assert res.action == "conflict"
    swept = sweep(ledger)                       # must not raise
    assert swept["gaps"] == 0
    proj = ledger.projection()
    assert held_items(proj) == []               # not a balance-family item...
    others = other_holds(proj)                  # ...but visible, never invisible
    assert len(others) == 1
    assert others[0]["doc_type"] == "brokerage_statement"
    assert others[0]["reason"] == "conflict"


def test_cash_flow_mismatch_is_held(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    # Snapshot is consistent (18400 + 5000 = 23400), but the activity only explains
    # 1000 + 4080 = 5080, not the stated 5000 ending cash → cash-flow gate fails.
    facts = BrokerageFacts(
        doc_id="", doc_type="brokerage_statement", doc_type_confidence=0.97,
        account_ref="Fidelity Roth", currency="USD", as_of="2026-03-31",
        opening_cash=Decimal("1000.00"), cash=Decimal("5000.00"),
        total=Decimal("23400.00"),
        positions=[PositionFact("AAPL", Decimal("100"), Decimal("18400.00"), None)],
        activity=[
            BrokerageActivity("2026-03-02", "contribution", Decimal("5000.00")),
            BrokerageActivity("2026-03-10", "dividend", Decimal("100.00")),
            BrokerageActivity("2026-03-11", "fee", Decimal("20.00")),
            BrokerageActivity("2026-03-15", "buy", Decimal("3000.00")),
            BrokerageActivity("2026-03-20", "sell", Decimal("2000.00")),
        ],
        account_number="000000003311", institution="Fidelity")
    res = capture_and_ingest(raw, ledger, b"brk-bad",
                             lambda data, did: _stamp(facts, did), captured_at="2026-04-02")
    assert res.action == "conflict"
    proj = ledger.projection()
    assert proj.positions() == []                  # nothing recorded on a bad flow
    assert len(proj.open_holds()) == 1
