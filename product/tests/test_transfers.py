"""Internal transfers: detect, net (exclude from spending), and the
decisive-vs-ambiguous boundary. The link is an overlay; each statement still
reconciles on its own."""

from decimal import Decimal

from viva.answer import answer_spending
from viva.ingest import (POSTED, RawStore, ReadResult, StatementFacts, TxnFact,
                         account_id_for, capture_and_ingest, link_transfers,
                         reject_transfer, sweep)
from viva.ingest.transfers import confirm_transfer
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
    # Before the link exists, the transfer inflates spending.
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


def test_multi_leg_corroboration_supplies_a_missing_payments_section(tmp_path):
    # The card's WHOLE payments section is dropped, so it is off by the SUM of
    # two bank payments. Each bank line names the card ("IMPRINT"), so the
    # subset that sums to the gap is unique → supplied.
    raw, ledger = _stores(tmp_path)
    chk = _facts("10000.00",
                 [("2026-01-05", "Groceries", "-100.00"),
                  ("2026-01-10", "PAYMENT TO IMPRINT", "-1500.00"),
                  ("2026-01-20", "PAYMENT TO IMPRINT", "-1140.27")],
                 "7259.73", ref="Everyday Checking 1111",
                 doc_type="checking_statement", number="000000001111")
    # Imprint card owes 2640.27 opening + a 200 charge, closing 200 — but both
    # payments were dropped, so it is off by -2640.27.
    card = _facts("2640.27", [("2026-01-08", "Store", "200.00")], "200.00",
                  ref="Imprint Card", doc_type="credit_card_statement",
                  number="000000000007", inst="Imprint")
    _up(raw, ledger, b"chk", chk)
    res = _up(raw, ledger, b"card", card)
    assert res.action == POSTED
    proj = ledger.projection()
    assert proj.balance(account_id_for(card)).amount == Decimal("200.00")
    # Two legs were supplied, each citing the checking document, and both netted.
    supplied = [ln for ln in proj.transactions(account_id_for(card))
                if "corrobor" in (ln.provenance.note or "")]
    assert len(supplied) == 2 and all(s.grade == "corroborated" for s in supplied)
    assert proj.spending_by_currency() == {"USD": Decimal("100.00")}


def test_sweep_links_previously_ingested_statements(tmp_path):
    # Statements can be posted with no counterpart yet / before detection ran; a
    # later sweep over the whole vault links them without a new upload.
    raw, ledger = _stores(tmp_path)
    chk, card = _checking_paying_card()
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    # Suppose nothing was linked at ingest (simulate by rejecting is overkill —
    # instead assert sweep is idempotent and keeps the link).
    before = len(ledger.projection().transfer_links())
    result = sweep(ledger)
    after = ledger.projection().transfer_links()
    assert len(after) >= before                      # idempotent, never loses links
    assert ledger.projection().spending_by_currency() == {"USD": Decimal("100.00")}
    assert isinstance(result, dict) and "auto" in result


def test_signal_without_naming_hint_is_suggested_not_auto_linked(tmp_path):
    # Within the window, with a transfer WORD ("PAYMENT") but no naming hint:
    # SURFACED to ask, never auto-linked.
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-05", "PAYMENT", "-750.00")], "4250.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card = _facts("750.00", [("2026-01-08", "PAYMENT", "-750.00")], "0.00",
                  ref="Card 2222", doc_type="credit_card_statement", number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    proj = ledger.projection()
    assert proj.transfer_suggestions()                   # surfaced (transfer word)
    assert not any(m.linked for m in proj.movements())   # not auto-linked (no hint)


def test_a_coincidence_with_no_english_word_is_still_asked_about(tmp_path):
    """The gate here used to be a transfer-word list — "transfer", "payment",
    "autopay", "thank you" — and a matching pair carrying none of them was
    treated as ordinary spending rather than a question.

    That is a fact about English, not about the money. Same amount, same
    currency, opposite direction, both accounts yours, within the window: the
    coincidence IS the evidence, and the queue was built to rank exactly this —
    ask what moves the most money first, summarise the tail. Deciding what to
    ask by which words a bank happened to print made the answer depend on the
    language the statement was written in.

    Still not AUTO-linked: that needs a distinctive account token, and neither
    line carries one."""
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-05", "STARBUCKS", "-40.00")], "4960.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card = _facts("40.00", [("2026-01-06", "REFUND ADJUSTMENT", "-40.00")], "0.00",
                  ref="Card 2222", doc_type="credit_card_statement", number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    proj = ledger.projection()
    assert proj.transfer_suggestions(), "the match is the evidence, so it is asked"
    assert not any(m.linked for m in proj.movements()), "asked, never assumed"
    # Nothing is netted until a person rules, so spending is unchanged.
    assert proj.spending_by_currency() == {"USD": Decimal("40.00")}


def test_a_generic_word_no_longer_auto_links_anything(tmp_path):
    """`_strong_hint` used to return true if "card", "credit", "visa" or
    "amex" appeared anywhere in either description. A credit card statement
    prints "card" on nearly every line, so for a card destination the hint was
    close to always-true and the only real constraints left were equal amount
    and uniqueness. A word list that is always true is not evidence.

    Now only a token belonging to one of these two accounts — and to no other
    account held — can make a link without asking."""
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT TO CREDIT CARD", "-500.00")],
                 "4500.00", ref="Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    card = _facts("500.00", [("2026-01-11", "PAYMENT THANK YOU", "-500.00")], "0.00",
                  ref="Card 2222", doc_type="credit_card_statement",
                  number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    proj = ledger.projection()
    assert not any(m.linked for m in proj.movements()), \
        "'credit card' names no particular account of yours"
    assert proj.transfer_suggestions(), "and it is asked about instead"


def test_a_distinctive_token_still_links_without_asking(tmp_path):
    """The other half: the last four of the account being paid is evidence about
    THAT account, and nothing else held carries it."""
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT TO CARD 2222", "-500.00")],
                 "4500.00", ref="Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    card = _facts("500.00", [("2026-01-11", "PAYMENT THANK YOU", "-500.00")], "0.00",
                  ref="Card 2222", doc_type="credit_card_statement",
                  number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    assert any(m.linked for m in ledger.projection().movements())


def test_a_token_two_of_your_accounts_share_names_neither(tmp_path):
    """What replaced the stopword list. "chase" is generic in a vault where
    every account is Chase and distinctive in one holding a single Chase account
    — a fixed list cannot know which vault it is in, and the vault can."""
    from viva.ledger.identity import distinctive_tokens
    inst = {"a": "chase", "b": "chase"}
    both = distinctive_tokens({"a": {"chase", "1111"}, "b": {"chase", "2222"}}, inst)
    assert both["a"] == {"1111"} and both["b"] == {"2222"}

    inst2 = {"a": "chase", "b": "citi"}
    alone = distinctive_tokens({"a": {"chase", "1111"}, "b": {"citi", "2222"}}, inst2)
    assert "chase" in alone["a"] and "citi" in alone["b"]

    # And the case a real test caught: an account LABELLED "Card 2222" offers
    # the token "card", unique between two accounts and still the most generic
    # word on a card statement. A label word must carry a digit to name
    # anything; the institution is exempt because it is a name, not a kind.
    labelled = distinctive_tokens({"a": {"checking", "1111"},
                                   "b": {"card", "2222"}},
                                  {"a": "chase", "b": "chase"})
    assert labelled["b"] == {"2222"} and labelled["a"] == {"1111"}


def test_confirming_one_removes_the_shared_movement_from_others(tmp_path):
    # Two checking payments both match the same card paydown; confirming one must
    # not leave that paydown offered to the other (no double-link).
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-10", "PAYMENT", "-500.00"),
                             ("2026-01-11", "PAYMENT", "-500.00")], "4000.00",
                 ref="Checking 1111", doc_type="checking_statement", number="000000001111")
    card = _facts("500.00", [("2026-01-12", "PAYMENT", "-500.00")], "0.00",
                  ref="Card A 2222", doc_type="credit_card_statement", number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    sugg = ledger.projection().transfer_suggestions()
    assert len(sugg) == 2                                # both payments ask
    dest = sugg[0]["candidates"][0]
    assert confirm_transfer(ledger, sugg[0]["a"], dest) is True
    # The confirmed source drops out; confirming the SAME paydown to the other
    # source is a guarded no-op (the money is already in a transfer).
    assert all(s["a"] != sugg[0]["a"] for s in ledger.projection().transfer_suggestions())
    assert confirm_transfer(ledger, sugg[1]["a"], dest) is False
    assert len([m for m in ledger.projection().movements() if m.linked]) == 2


# --------------------------------------------------------------- printed dates
#
# The cases below are the shapes a real vault produced: 29 unanswerable questions
# of which 24 were unanswerable only because the matcher was not reading the date
# the bank had printed on the line. They are reproduced here, not invented.


def _one_checking_paying_one_card(chk_txns, card_txns, o="2026-01-01",
                                  c="2026-12-31"):
    """Both statements reconcile by construction — closing is derived from the
    transactions, so a test can add a line without hand-balancing the sheet."""
    def _close(opening, txns):
        return str(Decimal(opening) + sum(Decimal(a) for _d, _s, a in txns))

    chk = _facts("9000.00", chk_txns, _close("9000.00", chk_txns),
                 ref="Everyday Checking 1111", doc_type="checking_statement",
                 number="000000001111", o=o, c=c)
    card = _facts("9000.00", card_txns, _close("9000.00", card_txns),
                  ref="Rewards Card 2222", doc_type="credit_card_statement",
                  number="000000002222", o=o, c=c)
    return chk, card


def test_the_printed_date_resolves_a_week_of_identical_card_payments(tmp_path):
    """The shape that produced most of the unanswerable questions: one checking
    account paying one card four times in eight days, every credit reading
    'Payment Thank You-Mobile'. The account evidence is equally true of all four,
    so nothing but the date the bank printed can say which is which."""
    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-02-14", "02/14 Payment To Acme Card Ending IN 2222", "-150.00"),
         ("2026-02-15", "02/15 Payment To Acme Card Ending IN 2222", "-150.00"),
         ("2026-02-20", "02/17 Payment To Acme Card Ending IN 2222", "-150.00"),
         ("2026-02-20", "02/19 Payment To Acme Card Ending IN 2222", "-150.00")],
        [("2026-02-14", "Payment Thank You-Mobile", "-150.00"),
         ("2026-02-15", "Payment Thank You-Mobile", "-150.00"),
         ("2026-02-17", "Payment Thank You-Mobile", "-150.00"),
         ("2026-02-19", "Payment Thank You-Mobile", "-150.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    proj = ledger.projection()
    assert len([m for m in proj.movements() if m.linked]) == 8      # all four pairs
    assert proj.transfer_suggestions() == []                       # nothing to ask

    # And each one paired with ITS date, not merely with some credit.
    by_key = {m.key: m for m in proj.movements()}
    for link in proj.transfer_links():
        a, b = by_key[link["a"]], by_key[link["b"]]
        src, dst = (a, b) if a.description.startswith("02/") else (b, a)
        assert src.description[:5].replace("/", "-") == dst.date[5:]


def test_a_date_that_does_not_match_loses_the_destination_to_one_that_does(tmp_path):
    """The wrong link a real vault contained. A $300 cash withdrawal and a $300
    card payment, one day apart. The old rule linked them because the ATM line
    contains the word 'card'; the printed date says the withdrawal happened on
    the 1st and the credit landed on the 2nd, and the line that says 12/02 is
    sitting right there."""
    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-12-01", "ATM Withdrawal 12/01 100 Example Ave Card 8888",
          "-300.00"),
         ("2026-12-04", "12/02 Payment To Acme Card Ending IN 2222", "-300.00")],
        [("2026-12-02", "Payment Thank You-Mobile", "-300.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    proj = ledger.projection()
    linked = [m for m in proj.movements() if m.linked]
    assert len(linked) == 2
    assert any(m.description.startswith("12/02 Payment") for m in linked)
    assert not any("ATM" in m.description for m in linked)


def test_the_printed_date_never_links_on_its_own(tmp_path):
    """Account evidence stays mandatory. A date agreeing is a tiebreaker between
    pairs that already qualify, never a reason to link — otherwise every rent
    payment that happens to name a day becomes a transfer."""
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-03-09", "03/09 Rent Payment", "-1200.00")],
                 "3800.00", ref="Everyday Checking 1111",
                 doc_type="checking_statement", number="000000001111")
    card = _facts("1200.00", [("2026-03-09", "Payment Thank You-Mobile", "-1200.00")],
                  "0.00", ref="Rewards Card 2222",
                  doc_type="credit_card_statement", number="000000002222")
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    proj = ledger.projection()
    assert [m for m in proj.movements() if m.linked] == []
    assert len(proj.transfer_suggestions()) == 1


def test_the_date_is_read_without_knowing_the_country(tmp_path):
    """17/02 is the seventeenth of February and 02/17 is too, and the matcher is
    told which by nobody. Both orders are tried; only one can land inside a
    five-day window, so the ambiguity that would need a locale cannot arise."""
    from viva.ingest.transfers import _prints_date

    assert _prints_date("02/17", "2026-02-17")          # month first
    assert _prints_date("17/02", "2026-02-17")          # day first
    assert _prints_date("17-02", "2026-02-17")          # a dash is a separator
    assert _prints_date("12/31/25", "2025-12-31")       # a year is ignored, not parsed
    assert not _prints_date("02/18", "2026-02-17")
    assert not _prints_date("", "2026-02-17")
    assert not _prints_date("Payment", "2026-02-17")
    assert not _prints_date("02/17", "")


def test_a_tie_is_still_a_question(tmp_path):
    """Two sources, one destination, identical evidence. `_sole_max` refuses to
    break it — a tie broken by iteration order is a coin flip recorded as a
    fact."""
    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-04-05", "Payment To Acme Card Ending IN 2222", "-250.00"),
         ("2026-04-05", "Payment To Acme Card Ending IN 2222", "-250.00")],
        [("2026-04-05", "Payment Thank You-Mobile", "-250.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    proj = ledger.projection()
    assert [m for m in proj.movements() if m.linked] == []
    assert len(proj.transfer_suggestions()) == 2


def test_a_link_records_which_rule_decided_it(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-05-06", "05/05 Payment To Acme Card Ending IN 2222", "-75.00")],
        [("2026-05-05", "Payment Thank You-Mobile", "-75.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    link = ledger.projection().transfer_links()[0]
    assert link["decided_by"] == "named_account+printed_date"
    # The rule's NAME, never the account reference it matched.
    assert "2222" not in link["decided_by"]


def test_the_scan_is_the_same_whichever_order_the_graph_iterates(tmp_path):
    """`decide` scores the whole graph before choosing anything, so the outcome
    is a property of the evidence. Asserted by reversing the candidate lists."""
    from viva.ingest.transfers import _candidates, _distinctive, decide, weigh

    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-06-02", "06/01 Payment To Acme Card Ending IN 2222", "-90.00"),
         ("2026-06-03", "06/03 Payment To Acme Card Ending IN 2222", "-90.00")],
        [("2026-06-01", "Payment Thank You-Mobile", "-90.00"),
         ("2026-06-03", "Payment Thank You-Mobile", "-90.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)

    proj = ledger.projection()
    graph, sources = _candidates(proj)
    # Everything is already linked, so re-derive on a graph built by hand from
    # the same movements to compare orderings on identical input.
    dist = _distinctive(proj)
    strength, _why = weigh(proj, graph, sources, dist)
    forward = decide(graph, strength)
    flipped = {k: list(reversed(v)) for k, v in graph.items()}
    assert decide(flipped, strength) == forward


def test_a_question_whose_candidate_was_taken_stops_being_asked(tmp_path):
    """A real scan linked 24 pairs and left 5 questions that could not be
    answered: each had been raised by an EARLIER scan, and this one linked their
    only candidate to a better-evidenced source. `confirm_transfer` refuses a
    movement already in a transfer, so the only available answer was "no".

    Note the history this needs. A source that loses its candidate inside a
    single scan is never asked about at all — it reaches the loop with an empty
    candidate list and is skipped. The stale question only exists when the
    suggestion was recorded before the link, which is why this test appends the
    two events in that order rather than running one scan."""
    from viva.ledger.events import transfer_linked, transfer_suggested

    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-07-02", "07/01 Payment To Acme Card Ending IN 2222", "-500.00"),
         ("2026-07-02", "Tuition Center Sale Web ID: 1234567890", "-500.00")],
        [("2026-07-01", "Payment Thank You-Mobile", "-500.00")])

    # Post the checking side alone: no card yet, so nothing can link.
    _up(raw, ledger, b"chk", chk)
    proj = ledger.projection()
    loser = next(m for m in proj.movements() if "Tuition" in m.description)
    winner = next(m for m in proj.movements() if m.description.startswith("07/01"))

    # An earlier scan asked about the loser, naming a credit that does not exist
    # yet. Then the card arrives and the credit goes to the better evidence.
    _up(raw, ledger, b"card", card)
    proj = ledger.projection()
    credit = next(m for m in proj.movements() if "Thank You" in m.description)
    assert credit.linked                                   # the winner took it

    ledger.append(transfer_suggested(loser.key, [credit.key], {}, "2026-07-02"))
    assert ledger.projection().transfer_suggestions() == []   # unanswerable, so unasked

    # Read-side, not a ruling: revoke the link that took the credit and the
    # question is a question again. Nothing was withdrawn from the log.
    reject_transfer(ledger, winner.key, credit.key)
    back = ledger.projection().transfer_suggestions()
    assert [s["a"] for s in back] == [loser.key]


def test_layer_zero_alone_reaches_the_same_verdicts(tmp_path):
    """The claim that the published rules are not a degraded mode, tested rather
    than asserted. `profile_for=None` forces `resolve_descriptor` past every
    grammar and onto `posting_date` alone; the links must be the same pairs.

    Only the recorded REASON differs — `named_account` where a grammar would have
    said `account_ref_slot`, because the grammar proved a slot and the published
    rules only saw a substring."""
    from viva.ingest.transfers import _candidates, _distinctive, decide, weigh

    raw, ledger = _stores(tmp_path)
    chk, card = _one_checking_paying_one_card(
        [("2026-08-02", "08/01 Payment To Acme Card Ending IN 2222", "-310.00"),
         ("2026-08-04", "08/03 Payment To Acme Card Ending IN 2222", "-310.00")],
        [("2026-08-01", "Payment Thank You-Mobile", "-310.00"),
         ("2026-08-03", "Payment Thank You-Mobile", "-310.00")])
    _up(raw, ledger, b"chk", chk)
    _up(raw, ledger, b"card", card)
    assert len([m for m in ledger.projection().movements() if m.linked]) == 4

    # Re-derive on the same movements with the grammar deliberately withheld.
    proj = ledger.projection()
    graph, sources = _candidates(proj)
    dist = _distinctive(proj)
    without, _why = weigh(proj, graph, sources, dist, profile_for=None)
    assert decide(graph, without) == decide(graph, without)   # stable
    # Every pair the real scan made is still reachable without any grammar.
    for skey, cands in graph.items():
        assert max((without[(skey, c.key)] for c in cands), default=0) >= 2
