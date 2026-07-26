"""Slice 9a — from your words to the ledger.

The failure these tests pin down came from the first real run of the question
queue: it asked about a mortgage payment and a car purchase, and its three
answers (spending / transfer / settlement) could hold neither. A mortgage is
three things at once; a car is something you now *own*, which the ledger had no
way to say. The fix is the four majors, reached by a sentence.

What each test is really defending:

* a ruling changes an aggregate *retroactively*, with no re-ingest (read side);
* a compound payment with unknown proportions is neither counted nor dropped —
  it gets its own honest line and names the document that would resolve it;
* an account nobody issued is marked `asserted` forever, because that is the
  difference between a ledger that can vouch for you and one that cannot (A3);
* a ruling can never smuggle in a figure (T2 / ADR-010).
"""

from decimal import Decimal

import pytest

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import (ASSERTED, ISSUED, MAJOR_ASSET, MAJOR_EXPENSE,
                                MAJOR_INCOME, MAJOR_LIABILITY, SCOPE_MERCHANT,
                                SCOPE_MOVEMENT, account_opened, ruling_recorded)
from viva.ledger.postings import account_path
from viva.ledger.projection import (BY_RULING, MIXED, SETTLEMENT, SPENDING,
                                    TRANSFER, nature_of_legs)


def _vault(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _checking(raw, ledger, txns, opening="100000.00"):
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

    return capture_and_ingest(raw, ledger, b"chk", read, captured_at="2026-04-01")


# --------------------------------------------------------------- the vocabulary


@pytest.mark.parametrize("majors,expected", [
    ([MAJOR_EXPENSE], SPENDING),
    ([MAJOR_ASSET], TRANSFER),
    ([MAJOR_LIABILITY], SETTLEMENT),
    ([MAJOR_EXPENSE, MAJOR_EXPENSE], SPENDING),      # several legs, one nature
    ([MAJOR_EXPENSE, MAJOR_LIABILITY, MAJOR_ASSET], MIXED),
])
def test_each_major_answers_did_the_money_leave_your_life(majors, expected):
    assert nature_of_legs([{"major": m} for m in majors]) == expected


def test_the_major_is_fixed_code_and_everything_below_it_is_data():
    assert account_path(MAJOR_ASSET, "Vehicles", "Model 3") == "Assets:Vehicles:Model 3"
    assert account_path(MAJOR_LIABILITY, "Mortgage", "Acme") == "Liabilities:Mortgage:Acme"
    # A counterparty name can never inject a fake level into the hierarchy.
    assert account_path(MAJOR_INCOME, "Rent:Evil") == "Income:Rent Evil"
    with pytest.raises(ValueError):
        account_path("equity", "NetWorth")     # equity is derived, never asserted


# ------------------------------------------------- a ruling moves the aggregate


def test_i_bought_a_car_stops_being_spending_with_no_reingest(tmp_path):
    """The car question the queue could not ask. One sentence, and a purchase
    the ledger called consumption becomes something you own — retroactively,
    because nature is derived on the read side."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00")),
                            ("2026-03-06", "WHOLE FOODS", Decimal("-180.00"))])
    proj = ledger.projection()
    assert sum(proj.spending_by_category("USD").values()) == Decimal("42180.00")

    car = account_path(MAJOR_ASSET, "Vehicles", "Model 3")
    ledger.append(ruling_recorded(
        SCOPE_MERCHANT, "tesla motors", "2026-07-25",
        legs=[{"major": MAJOR_ASSET, "account": car}],
        said="i bought a car", corroborates="invoice"))

    proj = ledger.projection()
    assert sum(proj.spending_by_category("USD").values()) == Decimal("180.00")
    moved = [m for m in proj.movements() if "TESLA" in m.description][0]
    assert (moved.nature, moved.nature_reason) == (TRANSFER, BY_RULING)
    assert moved.ruling_account == car
    # And the money is not lost — it is recorded as something you now hold.
    assert proj.ruled_accounts()[car]["paid"] == Decimal("42000.00")


def test_a_compound_payment_is_neither_counted_nor_dropped(tmp_path):
    """The mortgage. Interest is spending, principal is debt reduction, escrow is
    still yours — and the ratio is on a statement nobody has. Counting it all
    restates the overstatement Slice 6.5 fixed; dropping it understates. So it
    gets its own line, and names the document that would settle it."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-03-06", "WHOLE FOODS", Decimal("-180.00"))])
    loan = account_path(MAJOR_LIABILITY, "Mortgage", "Newco")
    ledger.append(ruling_recorded(
        SCOPE_MERCHANT, "newco mortgage servicing", "2026-07-25",
        legs=[{"major": MAJOR_EXPENSE, "account": "Expenses:Interest"},
              {"major": MAJOR_LIABILITY, "account": loan},
              {"major": MAJOR_ASSET, "account": account_path(MAJOR_ASSET, "Escrow", "Newco")}],
        said="this is my mortgage — principal, interest and escrow",
        corroborates="mortgage_statement"))

    proj = ledger.projection()
    m = [x for x in proj.movements() if "NEWCO" in x.description][0]
    assert m.nature == MIXED and m.provisional      # uncertainty reported, not hidden

    assert sum(proj.spending_by_category("USD").values()) == Decimal("180.00")   # not counted...
    gap = proj.undecomposed("USD")
    assert gap["total"] == Decimal("4400.00") and gap["count"] == 1   # ...nor dropped
    # The gap is actionable, not merely admitted.
    assert gap["corroborates"] == ["mortgage_statement"]
    assert loan in gap["accounts"]

    # And net worth must not read this as debt reduction: part of it was interest.
    assert proj.ruled_accounts()[loan]["reliable_balance"] is False


def test_a_person_outranks_a_model_and_the_ruling_generalizes(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "ACME LENDING", Decimal("-500.00")),
                            ("2026-03-14", "ACME LENDING", Decimal("-500.00"))])
    loan = account_path(MAJOR_LIABILITY, "Auto", "Acme")
    ledger.append(ruling_recorded(SCOPE_MERCHANT, "acme lending", "2026-07-25",
                                  legs=[{"major": MAJOR_EXPENSE, "account": "Expenses:Other"}],
                                  by="model", grade="unverified"))
    ledger.append(ruling_recorded(SCOPE_MERCHANT, "acme lending", "2026-07-25",
                                  legs=[{"major": MAJOR_LIABILITY, "account": loan}],
                                  said="this paid my car loan"))
    proj = ledger.projection()
    # One answer settles BOTH payments — past and future — and the human wins.
    assert [m.nature for m in proj.movements() if "ACME" in m.description] == \
        [SETTLEMENT, SETTLEMENT]
    assert sum(proj.spending_by_category("USD").values()) == Decimal("0")
    # Payments known, outstanding unknown: an honest state, not a fabricated zero.
    assert proj.ruled_accounts()[loan]["paid"] == Decimal("1000.00")


def test_a_movement_ruling_beats_a_merchant_ruling(tmp_path):
    """One Zelle payment can be a gift and the next a loan repayment. The
    per-transaction answer must win over the counterparty-wide one."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "ZELLE TO SAM", Decimal("-300.00")),
                            ("2026-03-14", "ZELLE TO SAM", Decimal("-700.00"))])
    ledger.append(ruling_recorded(SCOPE_MERCHANT, "zelle to sam", "2026-07-25",
                                  legs=[{"major": MAJOR_EXPENSE, "account": "Expenses:Gifts"}],
                                  said="gifts to my brother"))
    proj = ledger.projection()
    second = [m for m in proj.movements() if m.amount == Decimal("-700.00")][0]
    ledger.append(ruling_recorded(SCOPE_MOVEMENT, second.key, "2026-07-25",
                                  legs=[{"major": MAJOR_ASSET, "account": "Assets:Loans:Sam"}],
                                  said="that one was a loan, he's paying it back"))
    proj = ledger.projection()
    by_amount = {m.amount: m.nature for m in proj.movements() if "ZELLE" in m.description}
    assert by_amount == {Decimal("-300.00"): SPENDING, Decimal("-700.00"): TRANSFER}
    assert sum(proj.spending_by_category("USD").values()) == Decimal("300.00")


# ------------------------------------------------------- the one-way doors (A3)


def test_an_account_records_who_says_it_exists(tmp_path):
    """A3. A statement-born account is `issued`; a sentence-born one is
    `asserted`. Only the first is evidence to a counterparty, and the
    distinction is capturable at write time or never."""
    _, ledger = _vault(tmp_path)
    ledger.append(account_opened("acct:chase:1122", "depository", "Checking",
                                 "USD", "2026-01-01", institution="Chase"))
    ledger.append(account_opened("Assets:Vehicles:Model 3", "asset", "Model 3",
                                 "USD", "2026-03-04", origin=ASSERTED))
    proj = ledger.projection()
    assert proj.account_info("acct:chase:1122").origin == ISSUED
    assert proj.account_info("Assets:Vehicles:Model 3").origin == ASSERTED


def test_an_older_vault_reads_as_issued():
    """Every account written before this slice came from a document. Absent must
    mean `issued`, so no existing vault's meaning shifts under it."""
    from viva.ledger.projection import LedgerProjection
    ev = account_opened("a", "depository", "n", "USD", "2026-01-01")
    ev.body.pop("origin")                      # a pre-9a event, replayed today
    assert LedgerProjection([ev]).account_info("a").origin == ISSUED


def test_a_ruling_can_never_carry_a_figure():
    """T2 / ADR-010's one plausible leak: a model interprets meaning, and the
    event it produces is the place an invented number could enter the ledger.
    Closed structurally, not by prompt."""
    with pytest.raises(ValueError, match="no amount"):
        ruling_recorded(SCOPE_MOVEMENT, "k", "2026-07-25",
                        legs=[{"major": MAJOR_ASSET, "amount": "42000.00"}])


def test_a_ruling_must_speak_the_closed_vocabulary():
    for legs in ([{"major": "equity"}], [{"major": ""}], [{"major": "spending"}]):
        with pytest.raises(ValueError):
            ruling_recorded(SCOPE_MOVEMENT, "k", "2026-07-25", legs=legs)
    with pytest.raises(ValueError):
        ruling_recorded("everything", "k", "2026-07-25")
