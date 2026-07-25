"""Slice 6 Stage 1 — brokerage holdings as dated measurements (Option A).

A brokerage statement reconciles on the snapshot identity (Σ market_value + cash =
total), its holdings are recorded as PositionObserved MEASUREMENTS (never posted),
the account value composes cash + positions, unrealized gain is a derived as-of
view, and a misread holding is held — never guessed."""

from decimal import Decimal

import pytest

from viva.ingest import (BrokerageFacts, PositionFact, ReadResult, RawStore,
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
    # It is NEVER an event in the ledger (M1: cash-flow over accrual).
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
