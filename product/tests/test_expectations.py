"""The expectations engine: documents pursue documents.

The registry is data; the mechanisms are universal; the whole thing is
read-side — derived on every projection, satisfied deterministically by the
expected document's arrival, silenced by the decline event. No new event type
anywhere, which is the read-early/write-late principle doing its job.
"""

from decimal import Decimal

from viva.ingest import (Deduction, PayStubFacts, RawStore, ReadResult,
                         StatementFacts, TxnFact, capture_and_ingest)
from viva.knowledge import evaluate
from viva.ledger import EventStore, Ledger, Provenance
from viva.questions import EXPECTATION, open_questions
from viva.vault import Vault
from viva.web import service

AS_OF = "2026-04-01"      # pinned: cadence math must be reproducible


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _vault(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    return Vault(ledger=ledger, raw=raw, directory=tmp_path)


def _funded_paystub(vault, retirement="750.00", stub=b"stub1",
                    pay_date="2026-03-15", dates=("2026-03-01", "2026-03-31"),
                    opening="10000.00", tag=b"chk"):
    """A pay stub only POSTS once its matching net deposit is on the books,
    because posting decomposes that deposit — so the fixture ingests the
    checking statement carrying the deposit first, then the stub."""
    net = Decimal("5000.00") - Decimal(retirement) - Decimal("1000.00")
    _checking(vault, [(pay_date, "DIRECT DEP ACME PAYROLL", str(net))],
              opening=opening, dates=dates, tag=tag)
    return _paystub(vault, retirement=retirement, doc_id=stub, pay_date=pay_date)


def _paystub(vault, retirement="750.00", doc_id=b"stub1", pay_date="2026-03-15"):
    facts = PayStubFacts(
        doc_id="", doc_type="pay_stub", doc_type_confidence=0.99,
        employer="Acme", currency="USD", pay_date=pay_date,
        period_start=pay_date[:8] + "01", period_end=pay_date,
        gross=Decimal("5000.00"),
        net=Decimal("5000.00") - Decimal(retirement) - Decimal("1000.00"),
        deductions=[Deduction("401K PLAN", Decimal(retirement), "retirement"),
                    Deduction("FED TAX", Decimal("1000.00"), "tax")])
    return capture_and_ingest(vault.raw, vault.ledger, doc_id,
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-03-16")


def _checking(vault, txns, opening="10000.00", dates=("2026-03-01", "2026-03-31"),
              tag=b"chk"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date=dates[0],
        closing_amount=Decimal(opening) + total, closing_date=dates[1],
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")
    return capture_and_ingest(vault.raw, vault.ledger, tag,
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-04-01")


def test_retirement_flow_raises_an_expectation(tmp_path):
    """Money leaves every pay stub for retirement and no statement has ever
    shown where it lands — the pay stub is evidence the 401(k) statement
    exists."""
    vault = _vault(tmp_path)
    _funded_paystub(vault)
    exps = evaluate(vault.ledger.projection(), AS_OF, "US")
    ret = [e for e in exps if e.entry_id == "retirement-statements"]
    assert len(ret) == 1
    assert ret[0].amount == Decimal("750.00"), "the stake is the money flowing"

    qs = open_questions(vault.ledger, as_of=AS_OF, jurisdiction="US")
    q = next(x for x in qs["questions"] if x["kind"] == EXPECTATION
             and x["refs"]["registry_entry"] == "retirement-statements")
    assert "USD 750.00" in q["text"], "the phrasing carries the stake"
    labels = [o["label"] for o in q["options"]]
    assert labels == ["I have it", "Not right now"]


def test_the_stake_grows_with_each_pay_stub_and_a_decline_respects_that(tmp_path):
    """Declining the ask silences it, and the NEXT pay stub changes the stake,
    which brings it back — no timer anywhere."""
    vault = _vault(tmp_path)
    _funded_paystub(vault)
    qs = open_questions(vault.ledger, as_of=AS_OF, jurisdiction="US")
    q = next(x for x in qs["questions"] if x["kind"] == EXPECTATION)
    service.decline_question(vault, q["id"], "not_now")
    qs = open_questions(vault.ledger, as_of=AS_OF, jurisdiction="US")
    assert not [x for x in qs["questions"] if x["kind"] == EXPECTATION]

    _funded_paystub(vault, stub=b"stub2", pay_date="2026-04-15",
                    dates=("2026-04-01", "2026-04-30"), opening="13250.00",
                    tag=b"chk2")
    qs = open_questions(vault.ledger, as_of=AS_OF, jurisdiction="US")
    back = [x for x in qs["questions"] if x["kind"] == EXPECTATION]
    assert back and Decimal(back[0]["amount"]) == Decimal("1500.00")


def test_jurisdiction_filters_the_registry(tmp_path):
    """A 1099 is a US fact. An Indian vault must not be asked for one — the
    entry is jurisdiction-tagged data, not code."""
    vault = _vault(tmp_path)
    _funded_paystub(vault)
    us = {e.entry_id for e in evaluate(vault.ledger.projection(), AS_OF, "US")}
    india = {e.entry_id for e in evaluate(vault.ledger.projection(), AS_OF, "IN")}
    assert "retirement-statements" in india, "universal entries hold everywhere"
    assert "investment-1099" not in india


def test_cadence_expectation_ranks_below_money_and_names_the_edge(tmp_path):
    """A stale account raises a quiet ask with stake 0: it settles no money, it
    improves currency — so every money question outranks it, honestly."""
    vault = _vault(tmp_path)
    _checking(vault, [("2026-03-05", "SOME NEW SHOP", "-120.00")])
    qs = open_questions(vault.ledger, limit=100, as_of="2026-07-27",
                        jurisdiction="US")
    cadence = [x for x in qs["questions"]
               if x["refs"].get("registry_entry") == "statement-currency"]
    assert len(cadence) == 1
    assert "2026-03-31" in cadence[0]["text"], "the edge date is named"
    money = [x for x in qs["questions"] if Decimal(x["amount"]) > 0]
    positions = [i for i, x in enumerate(qs["questions"]) if x["id"] == cadence[0]["id"]]
    assert all(qs["questions"].index(m) < positions[0] for m in money), (
        "every question that settles money outranks it")
    # …and within the cadence window, silence.
    fresh = open_questions(vault.ledger, limit=100, as_of=AS_OF,
                           jurisdiction="US")
    assert not [x for x in fresh["questions"]
                if x["refs"].get("registry_entry") == "statement-currency"]


def test_satisfaction_is_the_documents_arrival(tmp_path):
    """Deterministic satisfaction: the expected doc_type present among captured
    documents closes the expectation. No model opinion anywhere."""
    vault = _vault(tmp_path)
    _funded_paystub(vault)
    proj = vault.ledger.projection()
    assert any(e.entry_id == "retirement-statements"
               for e in evaluate(proj, AS_OF, "US"))
    # A retirement statement arrives (classified retirement_statement — an
    # alias of the brokerage profile). Its captured doc_type is what
    # satisfies the expectation: the ask was for the document, and it is here.
    from viva.ingest import BrokerageFacts
    facts = BrokerageFacts(
        doc_id="", doc_type="retirement_statement", doc_type_confidence=0.97,
        account_ref="Fido 401k", currency="USD", as_of="2026-03-31",
        cash=Decimal("0.00"), total=Decimal("0.00"), positions=[],
        account_number="000000009900", institution="Fido")
    capture_and_ingest(vault.raw, vault.ledger, b"ret1",
                       lambda data, did: _stamp(facts, did),
                       captured_at="2026-04-01")
    proj = vault.ledger.projection()
    assert not any(e.entry_id == "retirement-statements"
                   for e in evaluate(proj, AS_OF, "US"))


def test_an_unknown_mechanism_in_the_registry_fails_loudly(tmp_path):
    """A registry row naming a mechanism that doesn't exist is a data error —
    surfaced, never silently skipped, or the registry rots invisibly."""
    import json
    import pathlib

    import pytest

    import viva.knowledge as knowledge
    bad = {"version": "x", "entries": [{"id": "bad", "given": "no_such_thing"}]}
    tmp = tmp_path / "bad.json"
    tmp.write_text(json.dumps(bad))
    original = knowledge._DIR
    try:
        knowledge._DIR = pathlib.Path(tmp_path)
        knowledge.load.cache_clear()
        vault = _vault(tmp_path / "v")
        with pytest.raises(ValueError, match="no_such_thing"):
            knowledge.evaluate(vault.ledger.projection(), AS_OF, "US",
                               version="bad")
    finally:
        knowledge._DIR = original
        knowledge.load.cache_clear()
