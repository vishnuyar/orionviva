"""The answer path: honest figures, honest refusals, coverage-aware totals."""

from decimal import Decimal

from viva.answer import answer_balance, answer_total, coverage_summary
from viva.ingest import RawStore, ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ledger import (EventStore, Ledger, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)


def _checking(account, ref, currency, opening, txns, closing,
              o_date="2026-01-01", c_date="2026-01-31", doc_id="d1",
              include_closing=True):
    evs = [account_opened(account, "depository", ref, currency, o_date,
                          provenance=Provenance(doc_id)),
           opening_balance_observed(account, opening, o_date, Provenance(doc_id, 1))]
    for d, desc, a in txns:
        evs.append(simple_transaction(account, a, desc, d,
                                      provenance=Provenance(doc_id, 2)))
    if include_closing:
        evs.append(closing_balance_observed(account, closing, c_date,
                                            Provenance(doc_id, 6)))
    return evs


# open 1000, +500, -42.42 => 1457.58
JAN = [("2026-01-10", "Pay", Decimal("500.00")),
       ("2026-01-15", "Coffee", Decimal("-42.42"))]


def test_answerable_balance_is_corroborated_with_source():
    evs = _checking("acct:chase", "Chase Checking", "USD", "1000.00", JAN, "1457.58")
    a = answer_balance(evs, "acct:chase")
    assert a.answered and a.amount == Decimal("1457.58")
    assert a.grade == "corroborated" and a.currency == "USD"
    assert a.as_of == "2026-01-31"
    assert a.provenance and a.provenance[0].doc_id == "d1"


def test_unknown_account_is_refused_not_faked():
    evs = _checking("acct:chase", "Chase Checking", "USD", "1000.00", JAN, "1457.58")
    a = answer_balance(evs, "acct:savings")
    assert not a.answered and a.reason == "unknown_account"
    assert a.amount is None and "Chase Checking" in a.coverage


def test_unverified_balance_is_given_but_flagged():
    evs = _checking("acct:chase", "Chase Checking", "USD", "1000.00", JAN,
                    "1457.58", include_closing=False)
    a = answer_balance(evs, "acct:chase")
    assert a.answered and a.grade == "unverified"
    assert a.caveats  # it says the figure isn't confirmed


def test_conflicted_balance_is_refused():
    evs = _checking("acct:chase", "Chase Checking", "USD", "1000.00", JAN, "1600.00")
    a = answer_balance(evs, "acct:chase")
    assert not a.answered and a.reason == "conflicted" and a.amount is None
    assert "reconcile" in a.text


def test_as_of_excludes_the_future():
    evs = _checking("acct:chase", "Chase Checking", "USD", "1000.00", JAN, "1457.58")
    evs += [simple_transaction("acct:chase", Decimal("100.00"), "Refund",
                               "2026-02-05", provenance=Provenance("d2", 2)),
            closing_balance_observed("acct:chase", "1557.58", "2026-02-28",
                                     Provenance("d2", 6))]
    assert answer_balance(evs, "acct:chase").amount == Decimal("1557.58")
    earlier = answer_balance(evs, "acct:chase", as_of="2026-02-01")
    assert earlier.amount == Decimal("1457.58")


def test_total_single_currency_sums():
    evs = _checking("acct:chase", "Chase", "USD", "1000.00", JAN, "1457.58",
                    doc_id="d1")
    evs += _checking("acct:bofa", "BofA", "USD", "200.00",
                     [("2026-01-12", "Dep", Decimal("50.00"))], "250.00",
                     doc_id="d2")
    a = answer_total(evs)
    assert a.answered and a.amount == Decimal("1707.58") and a.currency == "USD"


def test_total_across_currencies_is_not_faked():
    evs = _checking("acct:chase", "Chase", "USD", "1000.00", JAN, "1457.58", doc_id="d1")
    evs += _checking("acct:sbi", "SBI", "INR", "5000.00",
                     [("2026-01-12", "Dep", Decimal("1000.00"))], "6000.00",
                     doc_id="d2")
    a = answer_total(evs)
    assert a.answered and a.amount is None            # no cross-currency sum
    assert a.subtotals == {"USD": "1457.58", "INR": "6000.00"}


def test_total_excludes_an_untrustworthy_account():
    evs = _checking("acct:chase", "Chase", "USD", "1000.00", JAN, "1457.58", doc_id="d1")
    evs += _checking("acct:bad", "Bad", "USD", "200.00",
                     [("2026-01-12", "Dep", Decimal("50.00"))], "999.00",  # won't reconcile
                     doc_id="d2")
    a = answer_total(evs)
    assert a.amount == Decimal("1457.58")             # only Chase counted
    assert any("Bad" in c for c in a.caveats)


def test_coverage_summary_counts_posted_and_awaiting(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    store = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Checking", currency="USD",
        opening_amount=Decimal("1000.00"), opening_date="2026-01-01",
        closing_amount=Decimal("1457.58"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-10", "Pay", Decimal("500.00")),
                      TxnFact("2026-01-15", "Coffee", Decimal("-42.42"))])

    def reader(rr):
        def rf(data, doc_id):
            if rr.facts is not None:
                rr.facts.doc_id = doc_id
            return rr
        return rf

    capture_and_ingest(raw, store, b"stmt",
                       reader(ReadResult("checking_statement", 0.98, facts)),
                       captured_at="2026-02-01")
    capture_and_ingest(raw, store, b"paystub",
                       reader(ReadResult("pay_stub", 0.9, None, "no projector")),
                       captured_at="2026-02-01")

    cov = coverage_summary(store.events())
    assert cov.documents_held == 2 and cov.posted == 1 and cov.awaiting == 1
    assert cov.awaiting_types == {"pay_stub": 1}
