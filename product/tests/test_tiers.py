"""Slice 9b — ask only where the counterparty cannot tell us.

The failure this replaces, in one sentence: the queue asked *"is this money spent,
or is it something you now own?"* about a counterparty already enriched as
`loan_payments / mortgage`. We knew, and we asked anyway (Vishnu, 2026-07-25).

So these tests are mostly about **silence** — the hardest thing to assert and the
whole point of the design. A product that asks about a supermarket is not being
careful, it is being useless.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import merchant_enriched
from viva.ledger.projection import (TIER_SETTLED, TIER_STRUCTURAL,
                                    TIER_UNENRICHED, TIER_UNKNOWN, TRANSFER)
from viva.questions import NATURE, open_questions


def _vault(tmp_path, txns, opening="100000.00"):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")

    def read(data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"chk", read, captured_at="2026-04-01")
    return ledger


def _enrich(ledger, merchant, category, implies=(), kind="business", sub=""):
    ledger.append(merchant_enriched(
        merchant, category, subcategory=sub, grade="corroborated",
        occurred_at="2026-04-01", by="model",
        attributes={"counterparty_kind": kind, "implies": list(implies)}))


LOAN_OUT = [{"relationship": "a home loan", "major": "liability", "on": "outflow",
             "account_group": "Mortgage", "compound": True,
             "confidence": "suggested", "documents": "mortgage statement or 1098",
             "ask": "Shall I set up the loan?"}]
BORROWED_IN = [{"relationship": "money you borrowed", "major": "liability",
                "on": "inflow", "account_group": "Loans", "compound": False,
                "confidence": "suggested", "documents": "loan agreement",
                "ask": "Was this a loan?"}]


def _tiers(ledger):
    proj = ledger.projection()
    return {m.description: proj.tier_of(m) for m in proj.movements()}


# ------------------------------------------------------------------- the tiers


def test_an_ordinary_counterparty_is_settled_and_silent(tmp_path):
    """The single largest change: we already knew, so we say nothing."""
    ledger = _vault(tmp_path, [("2026-03-06", "WHOLE FOODS MKT", "-180.00"),
                               ("2026-03-07", "NETFLIX.COM", "-15.00")])
    _enrich(ledger, "whole foods mkt", "food", sub="grocery")
    _enrich(ledger, "netflix com", "entertainment", sub="streaming")

    assert set(_tiers(ledger).values()) == {TIER_SETTLED}
    assert open_questions(ledger)["total"] == 0


def test_a_counterparty_that_implies_structure_is_proposed_not_asked(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-01", "LENDER ACH PMT", "-4400.00")])
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT, sub="mortgage")

    assert list(_tiers(ledger).values()) == [TIER_STRUCTURAL]
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    # A hypothesis with its grounds — not "what is this?"
    assert "normally mean a home loan" in q["text"]
    assert "several things at once" in q["text"]        # compound, stated up front
    assert "Shall I set up the loan?" in q["text"]
    assert "mortgage statement or 1098" in q["why"]
    assert q["options"][0]["args"]["major"] == "liability"
    assert q["options"][0]["args"]["group"] == "Mortgage"


def test_an_instrument_is_unknown_and_asked_one_at_a_time(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-04", "Check # 1201", "-20000.00"),
                               ("2026-03-11", "Check # 1202", "-500.00")])
    _enrich(ledger, "check", "other", kind="instrument")

    assert set(_tiers(ledger).values()) == {TIER_UNKNOWN}
    qs = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    assert len(qs) == 2 and all(q["scope"] == "one" for q in qs)


def test_an_unidentified_counterparty_waits_for_enrichment(tmp_path):
    """Not a nature question — we don't know who they are yet, and asking what
    the money BECAME before knowing who got it is the wrong order."""
    ledger = _vault(tmp_path, [("2026-03-04", "MYSTERY CO", "-100.00")])
    assert list(_tiers(ledger).values()) == [TIER_UNENRICHED]
    assert not [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]


# --------------------------------------------------------------- direction


def test_the_same_counterparty_means_opposite_things_by_direction(tmp_path):
    """Money OUT to a lender repays borrowing; money IN from one IS the
    borrowing. One counterparty, opposite signs, opposite meanings — carried as
    data on the implication rather than a branch in the queue."""
    ledger = _vault(tmp_path, [("2026-03-04", "ACME LENDING", "-500.00"),
                               ("2026-03-20", "ACME LENDING", "9000.00")])
    _enrich(ledger, "acme lending", "loan_payments",
            implies=list(LOAN_OUT) + list(BORROWED_IN))
    proj = ledger.projection()
    out = [m for m in proj.movements() if m.amount < 0][0]
    inn = [m for m in proj.movements() if m.amount > 0][0]
    assert proj.implication_of(out)["relationship"] == "a home loan"
    assert proj.implication_of(inn)["relationship"] == "money you borrowed"


def test_an_implication_that_does_not_apply_this_way_is_ignored(tmp_path):
    ledger = _vault(tmp_path, [("2026-03-20", "ACME LENDING", "9000.00")])
    _enrich(ledger, "acme lending", "loan_payments", implies=LOAN_OUT)  # outflow only
    proj = ledger.projection()
    assert proj.implication_of(proj.movements()[0]) is None


# ------------------------------------------------------- confidence, and doubt


def test_forced_is_decisive_and_suggested_says_it_is_not(tmp_path):
    """The forced / suggested ladder, reused from the verification findings
    rather than invented: acting confidently and admitting doubt are different
    behaviours and must not share a rung."""
    for confidence, provisional in (("forced", False), ("suggested", True)):
        ledger = _vault(tmp_path / confidence,
                        [("2026-03-08", "ACME BROKERAGE", "-1000.00")])
        _enrich(ledger, "acme brokerage", "investments", implies=[
            {"relationship": "a brokerage account", "major": "asset",
             "on": "outflow", "account_group": "Investments", "compound": False,
             "confidence": confidence, "documents": "", "ask": ""}])
        proj = ledger.projection()
        m = proj.movements()[0]
        assert m.nature == TRANSFER
        assert m.provisional is provisional, confidence


def test_no_implication_means_no_claim(tmp_path):
    """The safe default, and the one the eval guards hardest: a merchant that
    implies nothing must produce nothing. Inventing structure would create
    accounts nobody has, across a whole vault."""
    ledger = _vault(tmp_path, [("2026-03-06", "CORNER CAFE", "-8.00")])
    _enrich(ledger, "corner cafe", "dining", sub="coffee shop")
    proj = ledger.projection()
    assert proj.implication_of(proj.movements()[0]) is None
    assert proj.ruled_accounts() == {}
    assert sum(proj.spending_by_category().values()) == Decimal("8.00")


# ----------------------------------------------------------- the measurement


def test_the_tier_summary_is_the_before_and_after_number(tmp_path):
    from viva.debug_tiers import report

    ledger = _vault(tmp_path, [("2026-03-06", "WHOLE FOODS MKT", "-180.00"),
                               ("2026-03-07", "NETFLIX.COM", "-15.00"),
                               ("2026-03-01", "LENDER ACH PMT", "-4400.00"),
                               ("2026-03-04", "Check # 1201", "-20000.00")])
    _enrich(ledger, "whole foods mkt", "food", sub="grocery")
    _enrich(ledger, "netflix com", "entertainment", sub="streaming")
    _enrich(ledger, "lender ach pmt", "housing", implies=LOAN_OUT, sub="mortgage")
    _enrich(ledger, "check", "other", kind="instrument")

    proj = ledger.projection()
    summary = proj.tier_summary()
    assert summary[TIER_SETTLED]["count"] == 2
    assert summary[TIER_STRUCTURAL]["count"] == 1
    assert summary[TIER_UNKNOWN]["count"] == 1

    text = report(proj)
    assert "settled" in text and "50.0%" in text
    assert "questions the queue would ask: 2" in text     # not 4
    assert "handled without asking" in text
