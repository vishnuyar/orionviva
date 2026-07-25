"""Slice 6.5 — movement nature: spending means money that left your LIFE (M1).

The real-vault finding this fixes: transfers were excluded only when a *link* was
formed, while a *category* saying "transfers" excluded nothing — and one category
(`loan_payments`) covered two opposite natures. Nature decides now, category only
suggests, and weak evidence is reported as provisional rather than hidden.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         assign_category, assign_merchant_category,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.projection import (BY_CATEGORY, BY_LINK, BY_OWN_ACCOUNT,
                                    SPENDING, TRANSFER)


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _vault(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _checking(raw, ledger, txns, opening="10000.00", number="000000001122",
              ref="Chase Total Checking", tag=b"chk"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number=number, institution="Chase")
    return capture_and_ingest(raw, ledger, tag,
                              lambda data, did: _stamp(facts, did),
                              captured_at="2026-04-01")


def test_payment_to_my_own_card_is_not_spending_even_unlinked(tmp_path):
    """The core real-vault bug: the card's statement isn't in the vault, so no
    link can form — but the money plainly went to an account I hold."""
    raw, ledger = _vault(tmp_path)
    # Open the card account (a statement of its own), then pay it from checking.
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Chase Freedom Rise", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=Decimal("500.00"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-05", "COSTCO WHSE", Decimal("500.00"))],
        account_number="000000007799", institution="Chase")
    capture_and_ingest(raw, ledger, b"card",
                       lambda data, did: _stamp(card, did), captured_at="2026-02-01")
    # A checking payment naming that card — in a period the card statement misses.
    _checking(raw, ledger,
              [("2026-03-10", "Payment To Chase Card Ending IN 7799", "-400.00"),
               ("2026-03-12", "WHOLE FOODS MKT", "-60.00")])

    proj = ledger.projection()
    payment = next(m for m in proj.movements() if "Payment To Chase" in m.description)
    assert not payment.linked                      # nothing to link to
    assert payment.nature == TRANSFER              # ...but it's still not spending
    assert payment.nature_reason == BY_OWN_ACCOUNT
    # The headline excludes it; only the real outflow counts.
    assert sum(proj.spending_by_category().values()) == Decimal("560.00")  # 500 card + 60
    assert proj.spending_by_currency() == {"USD": Decimal("60.00")}


def test_a_linked_transfer_reports_the_link_as_its_reason(tmp_path):
    raw, ledger = _vault(tmp_path)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Chase Freedom Rise", currency="USD",
        opening_amount=Decimal("400.00"), opening_date="2026-03-01",
        closing_amount=Decimal("0.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-10", "Payment Thank You-Mobile",
                              Decimal("-400.00"))],
        account_number="000000007799", institution="Chase")
    capture_and_ingest(raw, ledger, b"card",
                       lambda data, did: _stamp(card, did), captured_at="2026-04-01")
    _checking(raw, ledger,
              [("2026-03-10", "Payment To Chase Card Ending IN 7799", "-400.00")])
    proj = ledger.projection()
    payment = next(m for m in proj.movements()
                   if m.kind == "depository" and "Payment To Chase" in m.description)
    assert payment.linked and payment.nature == TRANSFER
    assert payment.nature_reason == BY_LINK        # rung 1 beats rung 2


def test_same_category_opposite_natures(tmp_path):
    """The finding that killed category-decides-nature: a mortgage payment and a
    payment to my own card can carry the SAME category and mean opposite things."""
    raw, ledger = _vault(tmp_path)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Imprint Card", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=Decimal("100.00"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-05", "SOME SHOP", Decimal("100.00"))],
        account_number="000000003344", institution="Imprint")
    capture_and_ingest(raw, ledger, b"card",
                       lambda data, did: _stamp(card, did), captured_at="2026-02-01")
    _checking(raw, ledger,
              [("2026-03-05", "ROCKET MORTGAGE PMT", "-2000.00"),
               ("2026-03-06", "IMPRINT ACH PMT", "-500.00")])
    ledger_proj = ledger.projection()
    # Both get the SAME category, as the real model did.
    for m in ledger_proj.movements():
        if m.amount == Decimal("-2000.00") or m.amount == Decimal("-500.00"):
            assign_category(ledger, m.key, "loan_payments", by="model")

    proj = ledger.projection()
    mortgage = next(m for m in proj.movements() if "MORTGAGE" in m.description)
    to_card = next(m for m in proj.movements() if "IMPRINT ACH" in m.description)
    assert mortgage.nature == SPENDING             # external lender: real outflow
    assert to_card.nature == TRANSFER              # my own card: not spending
    assert to_card.nature_reason == BY_OWN_ACCOUNT


def test_category_hint_alone_is_provisional_not_silent(tmp_path):
    """A category that merely SUGGESTS internal excludes the movement but says so
    — the number states its own uncertainty rather than hiding it (X2)."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-08", "ACME BROKERAGE DEPOSIT", "-1000.00")])
    m0 = next(m for m in ledger.projection().movements() if "ACME" in m.description)
    assign_merchant_category(ledger, "acme brokerage deposit", "transfers", by="model")

    proj = ledger.projection()
    m = next(m for m in proj.movements() if "ACME" in m.description)
    assert m.nature == TRANSFER and m.nature_reason == BY_CATEGORY
    assert m.provisional                            # weak evidence, flagged
    assert proj.provisional_spending() == Decimal("1000.00")
    # It IS excluded from the headline, but the doubt is reported alongside.
    assert proj.spending_by_category() == {}


def test_transfers_never_appear_as_a_spending_line_item(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-08", "MOVE TO SAVINGS", "-1000.00"),
                            ("2026-03-09", "WHOLE FOODS MKT", "-50.00")])
    m = next(m for m in ledger.projection().movements() if "SAVINGS" in m.description)
    assign_merchant_category(ledger, "move to savings", "transfers", by="model")
    by_cat = ledger.projection().spending_by_category()
    assert "transfers" not in by_cat                # the incoherence is gone
    assert by_cat == {"Uncategorized": Decimal("50.00")}


def test_a_human_ruling_beats_the_category_hint(tmp_path):
    """You say it's really spending; your ruling outranks the hint (rung 3)."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-08", "ATM WITHDRAWAL", "-200.00")])
    m0 = next(m for m in ledger.projection().movements() if "ATM" in m.description)
    assign_merchant_category(ledger, "atm withdrawal", "transfers",
                             by="model", subcategory="atm")
    assert ledger.projection().spending_by_category() == {}   # hint excludes it
    # Now rule that it IS spending — cash you consider spent.
    assign_category(ledger, m0.key, "personal_care", by="human", nature=SPENDING)
    proj = ledger.projection()
    m = next(m for m in proj.movements() if "ATM" in m.description)
    assert m.nature == SPENDING and not m.provisional
    assert proj.spending_by_category() == {"personal_care": Decimal("200.00")}


def test_excluded_movements_explain_themselves(tmp_path):
    raw, ledger = _vault(tmp_path)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Imprint Card", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=Decimal("100.00"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-05", "SOME SHOP", Decimal("100.00"))],
        account_number="000000003344", institution="Imprint")
    capture_and_ingest(raw, ledger, b"card",
                       lambda data, did: _stamp(card, did), captured_at="2026-02-01")
    _checking(raw, ledger, [("2026-03-06", "IMPRINT ACH PMT", "-500.00")])
    excluded = ledger.projection().excluded_from_spending()
    assert [m.nature_reason for m in excluded] == [BY_OWN_ACCOUNT]
    assert abs(excluded[0].amount) == Decimal("500.00")
