"""Net worth is a curve, and every point is honest about itself.

Net worth is always as-of a date, running from the earliest date available to
the latest. It is not a number that needs a date attached; it is a function of
date. So the properties worth asserting are less about arithmetic — that part
is a sum — and more about **what the product refuses to claim**:

  * an account contributes NOTHING before its first measurement, never zero
  * an earlier point never moves when a later document arrives
  * a liability we cannot value keeps the total INCOMPLETE and names the fix
  * "provable" is the existing grade, not a new badge
  * two currencies produce two subtotals and no grand total

Every one of those is a way of not bluffing a number.
"""

from decimal import Decimal

import pytest

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import CORROBORATED, VERIFIED, position_observed
from viva.ledger.networth import change_dates, net_worth, series


def _statement(ledger, raw, *, account, kind_doc, opening, closing,
               opening_date, closing_date, txns=None, number="000000001122",
               institution="Chase", captured="2026-04-01", blob=b"doc"):
    """A statement that RECONCILES, because the pipeline rightly refuses one
    that does not. When no transactions are given, one is invented for exactly
    the difference, so every fixture below is a document that could exist."""
    if txns is None:
        delta = Decimal(closing) - Decimal(opening)
        txns = ([(opening_date, "ACTIVITY", str(delta))] if delta else [])
    facts = StatementFacts(
        doc_id="", doc_type=kind_doc, doc_type_confidence=0.98,
        account_ref=account, currency="USD",
        opening_amount=Decimal(opening), opening_date=opening_date,
        closing_amount=Decimal(closing), closing_date=closing_date,
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number=number, institution=institution)

    def read(_data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    return capture_and_ingest(raw, ledger, blob, read, captured_at=captured)


@pytest.fixture
def vault(tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    return raw, Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))


def _checking(vault, **kw):
    raw, ledger = vault
    kw.setdefault("account", "Chase Total Checking")
    kw.setdefault("kind_doc", "checking_statement")
    _statement(ledger, raw, **kw)
    return ledger


# --- the curve ---------------------------------------------------------------

def test_one_statement_gives_one_point(vault):
    ledger = _checking(vault, opening="1000.00", closing="1500.00",
                       opening_date="2026-03-01", closing_date="2026-03-31",
                       txns=[("2026-03-05", "PAYCHECK", "500.00")])
    points = series(ledger.projection())
    assert [p.as_of for p in points] == ["2026-03-31"]
    assert points[0].by_currency()["USD"]["net"] == Decimal("1500.00")
    assert points[0].complete


def test_a_later_document_does_not_move_an_earlier_point(vault):
    """The property that makes the curve worth trusting. If last month's figure
    changed every time a new statement landed, no comparison across time would
    mean anything, and 'am I doing better than in March?' would be unanswerable."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31",
              txns=[("2026-03-05", "PAYCHECK", "500.00")], blob=b"march")
    march = net_worth(ledger.projection(), "2026-03-31")

    _checking(vault, opening="1500.00", closing="2200.00",
              opening_date="2026-04-01", closing_date="2026-04-30",
              txns=[("2026-04-05", "PAYCHECK", "700.00")], blob=b"april")
    proj = ledger.projection()
    assert net_worth(proj, "2026-03-31").by_currency() == march.by_currency()
    assert net_worth(proj, "2026-04-30").by_currency()["USD"]["net"] == Decimal("2200.00")


def test_an_account_contributes_nothing_before_its_first_measurement(vault):
    """Not zero. An account we had not yet seen is not an account worth nothing,
    and a zero would make the early curve confidently wrong."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31", blob=b"a")
    _statement(ledger, raw, account="Amex Gold", kind_doc="credit_card_statement",
               opening="0.00", closing="400.00", opening_date="2026-06-01",
               closing_date="2026-06-30", number="000000004321",
               institution="Amex", blob=b"b")
    proj = ledger.projection()
    march = net_worth(proj, "2026-03-31")
    # Accounts are identified by institution + number, not by the label printed
    # on the statement — two banks may both call it "Total Checking".
    assert len(march.lines) == 1 and "chase" in march.lines[0].account
    assert march.by_currency()["USD"]["net"] == Decimal("1500.00")
    assert len(net_worth(proj, "2026-06-30").lines) == 2


def test_a_card_lands_on_the_liability_side(vault):
    """A card's stored balance is money OWED, positive — the figure on the bill
    (registry: "a card whose balance is money owed"). Net worth must subtract it.

    The fixture feeds a POSITIVE closing balance deliberately. A negative one
    would share the same mistaken assumption about the convention as the code
    under test, and confirm a bug instead of catching it."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31", blob=b"a")
    _statement(ledger, raw, account="Amex Gold", kind_doc="credit_card_statement",
               opening="0.00", closing="400.00", opening_date="2026-03-01",
               closing_date="2026-03-31", number="000000004321",
               institution="Amex", blob=b"b")
    point = net_worth(ledger.projection(), "2026-03-31")
    card = next(ln for ln in point.lines if "amex" in ln.account)
    assert card.amount == Decimal("-400.00"), "owed money is negative net worth"
    row = point.by_currency()["USD"]
    assert row["assets"] == Decimal("1500.00")
    assert row["liabilities"] == Decimal("400.00")
    assert row["net"] == Decimal("1100.00")


def test_an_overpaid_card_is_an_asset_not_a_debt(vault):
    """The reason net worth negates rather than takes an absolute value. If you
    overpay a card it owes YOU, its owed figure is negative, and abs() would
    book that credit as another debt — turning money you are owed into money you
    owe, which is the worst possible direction for this error."""
    raw, ledger = vault
    _statement(ledger, raw, account="Amex Gold", kind_doc="credit_card_statement",
               opening="0.00", closing="-50.00", opening_date="2026-03-01",
               closing_date="2026-03-31", number="000000004321",
               institution="Amex", blob=b"b")
    row = net_worth(ledger.projection(), "2026-03-31").by_currency()["USD"]
    assert row["assets"] == Decimal("50.00")
    assert row["liabilities"] == Decimal("0")


def test_every_point_names_its_stalest_input(vault):
    """A total resting on a four-month-old statement must say so. Without this
    the curve would present a stale figure as though it were current — the
    valuation-class invariant, applied to the headline number."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31", blob=b"a")
    _statement(ledger, raw, account="Amex Gold", kind_doc="credit_card_statement",
               opening="0.00", closing="400.00", opening_date="2026-07-01",
               closing_date="2026-07-31", number="000000004321",
               institution="Amex", blob=b"b")
    july = net_worth(ledger.projection(), "2026-07-31")
    assert july.oldest_input == "2026-03-31"
    dates = {ln.account.split(":")[1]: ln.as_of for ln in july.lines}
    assert dates == {"chase": "2026-03-31", "amex": "2026-07-31"}


# --- holdings ----------------------------------------------------------------

def test_holdings_use_the_measurement_current_at_that_date(vault):
    """A revaluation is a new observation, never a correction of the old one.
    So March's point keeps March's price."""
    raw, ledger = vault
    _statement(ledger, raw, account="Vanguard Brokerage",
               kind_doc="checking_statement", opening="0.00", closing="0.00",
               opening_date="2026-03-01", closing_date="2026-03-31",
               number="000000009911", institution="Vanguard", blob=b"bk")
    account = next(a for a in ledger.projection().accounts() if "9911" in a)
    for as_of, value in (("2026-03-31", "10000.00"), ("2026-06-30", "13000.00")):
        ledger.append(position_observed(
            account_id=account, instrument="VTSAX", units="100",
            market_value=value, currency="USD", occurred_at=as_of,
            grade=CORROBORATED))
    proj = ledger.projection()
    def holdings(date):
        return sum(ln.amount for ln in net_worth(proj, date).lines
                   if ln.kind == "holdings")
    assert holdings("2026-03-31") == Decimal("10000.00")
    assert holdings("2026-06-30") == Decimal("13000.00")


# --- the honesty properties --------------------------------------------------

def test_a_liability_from_cash_flow_alone_is_refused_and_named(vault):
    """Money reaching a lender says nothing about the balance owed — part of it
    was interest — and trusting the person does not fix that, because they do
    not know either. Only the statement does.

    So the total stays INCOMPLETE, the account is named, and the product says
    both what it would ask and what document would settle it."""
    from viva.ledger.events import ruling_recorded
    ledger = _checking(vault, opening="10000.00", closing="8000.00",
                       opening_date="2026-03-01", closing_date="2026-03-31",
                       txns=[("2026-03-10", "ACME MORTGAGE", "-2000.00")])
    ledger.append(ruling_recorded(
        scope="merchant", subject="acme mortgage",
        legs=[{"major": "liability", "account": "Liabilities:Mortgage:Acme"}],
        occurred_at="2026-04-01", by="human"))
    point = net_worth(ledger.projection(), "2026-03-31")
    assert not point.complete
    missing = {m["account"] for m in point.missing}
    assert "Liabilities:Mortgage:Acme" in missing
    entry = next(m for m in point.missing
                 if m["account"] == "Liabilities:Mortgage:Acme")
    assert entry["ask"] and entry["would_fix"], "say what would settle it"
    assert not any(ln.account.startswith("Liabilities:") for ln in point.lines), \
        "cash paid must never be summed as a debt balance"


def test_provable_is_the_existing_grade_not_a_new_badge(vault):
    """`corroborated` already means "we hold the document and the arithmetic
    checks", which is exactly what provable means. A figure a person asserted is
    `verified` — a human attested it, nothing checked it — so it counts toward
    net worth (we trust the user) and NOT toward the provable subtotal."""
    from viva.ledger.events import ruling_recorded
    ledger = _checking(vault, opening="30000.00", closing="10000.00",
                       opening_date="2026-03-01", closing_date="2026-03-31",
                       txns=[("2026-03-10", "BIG MOTORS", "-20000.00")])
    ledger.append(ruling_recorded(
        scope="merchant", subject="big motors",
        legs=[{"major": "asset", "account": "Assets:Vehicles:Car"}],
        occurred_at="2026-04-01", by="human"))
    point = net_worth(ledger.projection(), "2026-03-31")
    car = next(ln for ln in point.lines if ln.account.startswith("Assets:"))
    assert car.amount == Decimal("20000.00"), "an asset is recorded at COST"
    assert car.grade == VERIFIED and not car.provable
    row = point.by_currency()["USD"]
    assert row["net"] == Decimal("30000.00"), "trust the user: the car counts"
    assert row["provable"] == Decimal("10000.00"), "only the statement is provable"


def test_two_currencies_give_two_subtotals_and_no_grand_total(vault):
    """We have no FX source with a date, a provenance and a grade, so a
    converted total would be a figure no document attests."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31", blob=b"a")
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="HDFC Savings", currency="INR",
        opening_amount=Decimal("50000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("60000.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-10", "SALARY", Decimal("10000.00"))],
        account_number="000000007788", institution="HDFC")

    def read(_data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"inr", read, captured_at="2026-04-01")
    by_currency = net_worth(ledger.projection(), "2026-03-31").by_currency()
    assert set(by_currency) == {"USD", "INR"}
    assert by_currency["INR"]["net"] == Decimal("60000.00")
    assert by_currency["USD"]["net"] == Decimal("1500.00")


def test_an_empty_vault_says_nothing_rather_than_zero(vault):
    _raw, ledger = vault
    point = net_worth(ledger.projection())
    assert point.as_of == "" and point.lines == [] and point.by_currency() == {}
    assert change_dates(ledger.projection()) == []


def test_the_debug_report_names_what_it_will_not_count(vault):
    """An instrument that prints a confident total while silently omitting a
    mortgage is the failure the instrument exists to prevent. The report must
    say what is missing, in words, on the page."""
    from viva.debug.networth import report_point, report_series
    from viva.ledger.events import ruling_recorded

    ledger = _checking(vault, opening="10000.00", closing="8000.00",
                       opening_date="2026-03-01", closing_date="2026-03-31",
                       txns=[("2026-03-10", "ACME MORTGAGE", "-2000.00")])
    ledger.append(ruling_recorded(
        scope="merchant", subject="acme mortgage",
        legs=[{"major": "liability", "account": "Liabilities:Mortgage:Acme"}],
        occurred_at="2026-04-01", by="human"))
    proj = ledger.projection()
    text = report_point(net_worth(proj, "2026-03-31"))
    assert "INCOMPLETE" in text
    assert "NOT COUNTED" in text and "LOWER" in text
    assert "Liabilities:Mortgage:Acme" in text
    assert report_series(series(proj))


def test_an_empty_vault_reports_absence_not_zero(vault):
    """A vault with nothing in it must not print a confident 0.00 net worth."""
    from viva.debug.networth import report_point
    _raw, ledger = vault
    text = report_point(net_worth(ledger.projection()))
    assert "Nothing to value yet" in text
    assert "not zero" in text


def test_an_account_it_cannot_value_is_named_not_dropped(vault):
    """Silently omitting an account is the same failure as silently omitting a
    mortgage: whole accounts go missing while the report still looks complete.
    An account we hold but cannot value at this date must be NAMED."""
    raw, ledger = vault
    _checking(vault, opening="1000.00", closing="1500.00",
              opening_date="2026-03-01", closing_date="2026-03-31", blob=b"a")
    _statement(ledger, raw, account="Amex Gold", kind_doc="credit_card_statement",
               opening="0.00", closing="400.00", opening_date="2026-07-01",
               closing_date="2026-07-31", number="000000004321",
               institution="Amex", blob=b"b")
    march = net_worth(ledger.projection(), "2026-03-31")
    assert len(march.lines) == 1
    skipped = {row["account"].split(":")[1] for row in march.skipped}
    assert "amex" in skipped, "an account with no statement yet must be named"
    assert "2026-07-31" in march.skipped[0]["why"], "say when its first one is"

    from viva.debug.networth import report_point
    assert "DOES NOT INCLUDE" in report_point(march)


# --- the grade is a measurement, not a constant -----------------------------

def test_a_closing_grades_corroborated_and_a_confirmed_one_grades_verified(tmp_path):
    """The grade a net-worth line carries has to come from somewhere. It used to
    come from a body key nothing wrote, so every line read `corroborated`
    whatever the evidence was, and the provable subtotal equalled the total."""
    from viva.ledger.events import closing_balance_observed, account_opened

    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    ledger.append(account_opened("acct:a:1", "depository", "A", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("acct:a:1", Decimal("100"), "2026-01-31"))
    ledger.append(account_opened("acct:b:2", "depository", "B", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("acct:b:2", Decimal("50"), "2026-01-31",
                                           confirmed_by="human"))
    point = net_worth(ledger.projection())
    grades = {ln.account: ln.grade for ln in point.lines}
    assert grades["acct:a:1"] == CORROBORATED
    assert grades["acct:b:2"] == VERIFIED


def test_both_figures_are_reported_the_whole_total_and_the_provable_part(tmp_path):
    """Provable means issuer-attested arithmetic, so a figure a person attested
    is in the total and not in the provable part. Reporting only one of the two
    would make the person choose between being informed and being honest."""
    from viva.ledger.events import closing_balance_observed, account_opened

    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    ledger.append(account_opened("acct:a:1", "depository", "A", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("acct:a:1", Decimal("100"), "2026-01-31"))
    ledger.append(account_opened("acct:b:2", "depository", "B", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("acct:b:2", Decimal("50"), "2026-01-31",
                                           confirmed_by="human"))
    row = net_worth(ledger.projection()).by_currency()["USD"]
    assert row["net"] == Decimal("150")
    assert row["provable"] == Decimal("100")


# --- a held document is a known hole ----------------------------------------

def test_a_point_is_not_complete_while_a_document_sits_held(tmp_path):
    """A statement read and not posted names money the figure does not include.
    It may name an account that does not exist yet, so it cannot appear in
    `skipped` — which is how a point once called itself complete with two
    statements parked in review."""
    from viva.ledger.events import (account_opened, closing_balance_observed,
                                    statement_held)

    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    ledger.append(account_opened("acct:a:1", "depository", "A", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("acct:a:1", Decimal("100"), "2026-01-31"))
    before = net_worth(ledger.projection())
    assert before.complete is True

    ledger.append(statement_held("doc-9", {"account_ref": "elsewhere"}, None,
                                 "identity", "2026-02-01"))
    after = net_worth(ledger.projection())
    assert after.complete is False
    assert after.held and after.held[0]["reason"] == "identity"
    assert after.to_dict()["held"]


# --- holdings are one snapshot, not a composition ---------------------------

def _investment(ledger, *, account="acct:v:7734"):
    from viva.ledger.events import account_opened, closing_balance_observed
    ledger.append(account_opened(account, "investment", "Broker", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed(account, Decimal("1000"), "2026-03-31"))
    return account


def test_one_instrument_written_two_ways_is_not_held_twice(tmp_path):
    """The defect a real model run produced: a statement named a holding
    `BND VANGUARD TOTAL BOND MKT ETF` in January and `BND - VANGUARD TOTAL BOND
    MKT ETF` in March. Keyed by that string they are two instruments, and a
    total composed instrument-by-instrument counted an entire stale snapshot a
    second time — twenty thousand dollars, graded corroborated.

    Reading the newest statement as ONE snapshot removes the whole class: the
    older reading is not the latest measurement of anything, it is last
    statement's, and last statement is not what the account holds now."""
    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    acct = _investment(ledger)
    ledger.append(position_observed(acct, "BND VANGUARD TOTAL BOND MKT ETF",
                                    "55.000", "3993.00", "USD", "2026-01-31"))
    ledger.append(position_observed(acct, "BND - VANGUARD TOTAL BOND MKT ETF",
                                    "61.000", "4462.15", "USD", "2026-03-31"))
    proj = ledger.projection()
    holdings = [ln for ln in net_worth(proj).lines if ln.kind == "holdings"]
    assert sum(ln.amount for ln in holdings) == Decimal("4462.15")
    assert len(proj.positions(acct)) == 1


def test_a_holding_the_newest_statement_no_longer_lists_is_no_longer_held(tmp_path):
    """Sold, or misread. Either way the issuer has stopped attesting it, and
    carrying it forward adds something no document says you own."""
    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    acct = _investment(ledger)
    ledger.append(position_observed(acct, "VTI", "10.000", "2000.00", "USD", "2026-01-31"))
    ledger.append(position_observed(acct, "SOLD-CO", "5.000", "500.00", "USD", "2026-01-31"))
    ledger.append(position_observed(acct, "VTI", "10.000", "2100.00", "USD", "2026-03-31"))
    proj = ledger.projection()
    assert proj.holdings_value(acct) == Decimal("2100.00")
    assert [p.instrument for p in proj.positions(acct)] == ["VTI"]


def test_an_earlier_point_still_uses_the_statement_current_then(tmp_path):
    """Snapshot semantics must not cost the curve its stability: at a January
    date the January statement is the newest one there was, so that point keeps
    reporting what was true then."""
    store = EventStore.open(tmp_path / "e.jsonl", "pw")
    ledger = Ledger(store)
    acct = _investment(ledger)
    ledger.append(position_observed(acct, "VTI", "10.000", "2000.00", "USD", "2026-01-31"))
    ledger.append(position_observed(acct, "SOLD-CO", "5.000", "500.00", "USD", "2026-01-31"))
    ledger.append(position_observed(acct, "VTI", "10.000", "2100.00", "USD", "2026-03-31"))
    proj = ledger.projection()
    january = [ln for ln in net_worth(proj, "2026-02-15").lines if ln.kind == "holdings"]
    assert sum(ln.amount for ln in january) == Decimal("2500.00")
