"""Slice 3 — internal transfers: detect, net (exclude from spending), and the
decisive-vs-ambiguous boundary. The link is an overlay; each statement still
reconciles on its own."""

from decimal import Decimal

from viva.answer import answer_spending
from viva.ingest import (POSTED, RawStore, ReadResult, StatementFacts, TxnFact,
                         account_id_for, capture_and_ingest, confirm_transfer,
                         link_transfers, reject_transfer)
from viva.ledger import EventStore, Ledger, LedgerProjection


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _facts(opening, txns, closing, ref, doc_type, o="2026-01-01", c="2026-01-31",
           number="", inst="Acme"):
    f = StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date=o,
        closing_amount=Decimal(closing), closing_date=c,
        transactions=[TxnFact(date=d, description=desc, amount=Decimal(a))
                      for d, desc, a in txns],
        opening_page=1, closing_page=2, account_number=number, institution=inst)
    return f


def _up(raw, ledger, data, facts):
    return capture_and_ingest(
        raw, ledger, data, lambda d, did: _stamp(facts, did, facts.doc_type),
        captured_at="2026-02-01")


def _stamp(facts, doc_id, doc_type):
    facts.doc_id = doc_id
    return ReadResult(doc_type, 0.98, facts)


# Checking pays the card: -2400 out of checking, -2400 off the card's owed.
def _checking_paying_card(number_card_hint="9876"):
    chk = _facts("5000.00", [("2026-01-05", "Groceries", "-100.00"),
                             ("2026-01-10", f"ONLINE PAYMENT TO CARD {number_card_hint}", "-2400.00")],
                 "2500.00", ref="Everyday Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    card = _facts("2400.00", [("2026-01-12", "PAYMENT THANK YOU", "-2400.00")],
                  "0.00", ref="Rewards Card 9876", doc_type="credit_card_statement",
                  number="000000009876")
    return chk, card


def test_internal_transfer_auto_links_and_excludes_from_spending(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk, card = _checking_paying_card()
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)          # posting the card triggers detection

    proj = ledger.projection()
    # Both statements still reconcile on their own (overlay, not re-post).
    assert proj.balance(account_id_for(chk)).grade == "corroborated"
    assert proj.balance(account_id_for(card)).grade == "corroborated"
    # The transfer is recognized and netted: only the $100 groceries is spending,
    # not the $2400 that moved to the user's own card.
    assert proj.spending_by_currency() == {"USD": Decimal("100.00")}
    assert len([m for m in proj.movements() if m.linked]) == 2


def test_spending_double_counts_until_linked(tmp_path):
    # The once-red proof: before the link exists, the transfer inflates spending.
    raw, ledger = _stores(tmp_path)
    chk, card = _checking_paying_card()
    _up(raw, ledger, b"chk", chk)            # card not yet ingested → no partner
    proj = ledger.projection()
    assert proj.spending_by_currency() == {"USD": Decimal("2500.00")}  # 100 + 2400


def test_ambiguous_amount_is_suggested_not_auto_linked(tmp_path):
    raw, ledger = _stores(tmp_path)
    # Two card paydowns of the same amount, same window, and a checking payment
    # with NO own-account hint → cannot force a unique decisive pair.
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT", "-500.00")], "4500.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card1 = _facts("500.00", [("2026-01-11", "PAYMENT", "-500.00")], "0.00",
                   ref="Card A 2222", doc_type="credit_card_statement", number="000000002222")
    card2 = _facts("500.00", [("2026-01-12", "PAYMENT", "-500.00")], "0.00",
                   ref="Card B 3333", doc_type="credit_card_statement", number="000000003333")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card1", card1)
    _up(raw, ledger, b"card2", card2)
    proj = ledger.projection()
    assert proj.transfer_suggestions()                      # surfaced, not silent
    assert not any(m.linked for m in proj.movements())      # nothing auto-netted
    assert proj.spending_by_currency() == {"USD": Decimal("500.00")}  # still counted


def test_human_can_confirm_a_suggested_transfer(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT", "-500.00")], "4500.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card1 = _facts("500.00", [("2026-01-11", "PAYMENT", "-500.00")], "0.00",
                   ref="Card A 2222", doc_type="credit_card_statement", number="000000002222")
    card2 = _facts("500.00", [("2026-01-12", "PAYMENT", "-500.00")], "0.00",
                   ref="Card B 3333", doc_type="credit_card_statement", number="000000003333")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card1", card1)
    _up(raw, ledger, b"card2", card2)
    proj = ledger.projection()
    sug = proj.transfer_suggestions()[0]
    confirm_transfer(ledger, sug["a"], sug["candidates"][0])
    proj2 = ledger.projection()
    assert proj2.spending_by_currency() == {}               # confirmed → netted
    assert not proj2.transfer_suggestions()                 # suggestion resolved


def _card_missing_its_payment():
    """A card whose read DROPPED the $2400 payment, so it is off by 2400. The
    checking statement plainly shows the payment 'to card'."""
    chk = _facts("5000.00", [("2026-01-05", "Groceries", "-100.00"),
                             ("2026-01-10", "ONLINE PAYMENT TO CARD 9876", "-2400.00")],
                 "2500.00", ref="Everyday Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    # Card: opening owed 2400, one $500 charge, closing 500 — but the -2400 payment
    # was missed, so opening+Σ = 2900 ≠ closing 500 (off by -2400).
    card = _facts("2400.00", [("2026-01-08", "Dyson", "500.00")], "500.00",
                  ref="Rewards Card 9876", doc_type="credit_card_statement",
                  number="000000009876")
    return chk, card


def test_cross_document_corroboration_closes_the_gap(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk, card = _card_missing_its_payment()
    _up(raw, ledger, b"chk", chk)            # checking present first
    res = _up(raw, ledger, b"card", card)    # card is off by 2400 → corroborated
    assert res.action == POSTED
    proj = ledger.projection()
    # The card now reconciles and posts, owed 500.
    assert proj.balance(account_id_for(card)).amount == Decimal("500.00")
    # The supplied leg cites the CHECKING document, not the card, graded corroborated.
    supplied = [ln for ln in proj.transactions(account_id_for(card))
                if ln.provenance.doc_id != account_id_for(card)
                and "corrobor" in (ln.provenance.note or "")]
    assert supplied and supplied[0].grade == "corroborated"
    assert supplied[0].provenance.doc_id != ""      # points at the counterparty doc
    # And the pair is netted: the $2400 is not spending, only the $100 groceries.
    assert proj.spending_by_currency() == {"USD": Decimal("100.00")}


def test_corroboration_heals_in_either_order(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk, card = _card_missing_its_payment()
    res = _up(raw, ledger, b"card", card)    # card first → off by 2400, no partner yet
    assert res.action != POSTED              # held (no counterparty present yet)
    _up(raw, ledger, b"chk", chk)            # checking arrives → heal closes the card
    proj = ledger.projection()
    assert proj.balance(account_id_for(card)).amount == Decimal("500.00")
    assert proj.balance(account_id_for(card)).grade == "corroborated"
    assert proj.spending_by_currency() == {"USD": Decimal("100.00")}   # netted


def test_a_real_misread_is_not_falsely_corroborated(tmp_path):
    # A card off by an amount with NO matching counterparty movement must NOT be
    # rescued — it holds for review. Corroboration never invents a leg.
    raw, ledger = _stores(tmp_path)
    lone = _facts("0.00", [("2026-01-08", "Dyson", "500.00")], "480.00",  # off by -20
                  ref="Rewards Card 9876", doc_type="credit_card_statement",
                  number="000000009876")
    res = _up(raw, ledger, b"card", lone)
    assert res.action != POSTED                       # held, not silently closed


def test_reject_dismisses_the_suggestion(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT", "-500.00")], "4500.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card1 = _facts("500.00", [("2026-01-11", "PAYMENT", "-500.00")], "0.00",
                   ref="Card A 2222", doc_type="credit_card_statement", number="000000002222")
    card2 = _facts("500.00", [("2026-01-12", "PAYMENT", "-500.00")], "0.00",
                   ref="Card B 3333", doc_type="credit_card_statement", number="000000003333")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card1", card1)
    _up(raw, ledger, b"card2", card2)
    sug = ledger.projection().transfer_suggestions()[0]
    reject_transfer(ledger, sug["a"])
    assert not ledger.projection().transfer_suggestions()   # dismissed, append-only


def test_auto_link_is_corroborated_and_survives_a_replay(tmp_path):
    # A link references movements by a CONTENT key, so replaying the log (as a
    # reingest does) re-derives the same keys and the link still holds.
    raw, ledger = _stores(tmp_path)
    chk, card = _checking_paying_card()
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    assert ledger.projection().transfer_links()[0]["grade"] == "corroborated"
    replayed = LedgerProjection(ledger.events())         # fresh projection from events
    assert replayed.spending_by_currency() == {"USD": Decimal("100.00")}
    assert len([m for m in replayed.movements() if m.linked]) == 2


def test_answer_spending_excludes_transfers(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk, card = _checking_paying_card()
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    ans = answer_spending(ledger.projection())
    assert ans.answered and ans.amount == Decimal("100.00")
    assert "transfer" in ans.text.lower()
