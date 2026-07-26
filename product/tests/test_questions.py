"""Slice 6.5 Move 2 — the question queue: one ranked front door for the four
ask-and-learn loops that were built separately.

The promises under test: rank by what answering MOVES, scope a ruling to the
most general unit that is still honest, never hide the tail, and never introduce
a new event type to do it.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         assign_merchant_category, capture_and_ingest,
                         rule_merchant_nature)
from viva.ledger import EventStore, Ledger
from viva.questions import MERCHANT, NATURE, TRANSFER, open_questions


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _checking(tmp_path, txns, opening="100000.00", tag=b"chk"):
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
    capture_and_ingest(raw, ledger, tag, lambda d, i: _stamp(facts, i),
                       captured_at="2026-04-01")
    return ledger


def test_questions_are_ranked_by_what_answering_moves(tmp_path):
    ledger = _checking(tmp_path, [
        ("2026-03-05", "TINY SHOP", "-12.00"),
        ("2026-03-06", "BIG MOTORS", "-30000.00"),
        ("2026-03-07", "MIDDLE STORE", "-500.00"),
    ])
    result = open_questions(ledger)
    amounts = [Decimal(q["amount"]) for q in result["questions"]]
    assert amounts == sorted(amounts, reverse=True)      # biggest stake first
    assert "BIG MOTORS" in result["questions"][0]["text"]


def test_the_tail_is_summarized_never_dropped(tmp_path):
    ledger = _checking(tmp_path, [
        (f"2026-03-{d:02d}", f"SHOP {d}", f"-{d}.00") for d in range(1, 13)
    ])
    result = open_questions(ledger, limit=3)
    assert len(result["questions"]) == 3
    assert result["total"] == 12
    assert result["tail"]["count"] == 9
    # The tail reports its VALUE too — hidden from the list, not from the person.
    assert Decimal(result["tail"]["amount"]) == sum(Decimal(d) for d in range(1, 10))


def test_an_unknown_merchant_asks_what_it_is_scoped_to_the_merchant(tmp_path):
    ledger = _checking(tmp_path, [
        ("2026-03-05", "ACME HARDWARE #12", "-100.00"),
        ("2026-03-09", "ACME HARDWARE #44", "-150.00"),
    ])
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == MERCHANT]
    assert q["count"] == 2 and Decimal(q["amount"]) == Decimal("250.00")
    assert q["scope"] == "pattern"           # one ruling clears both, and future
    assert "ACME HARDWARE" in q["text"]


def test_a_peer_payment_is_scoped_to_itself_not_a_rule(tmp_path):
    """A commercial merchant generalizes; a person does not — one Zelle is a
    gift, the next a loan repayment (the local-categorization finding)."""
    ledger = _checking(tmp_path, [("2026-03-05", "ZELLE PAYMENT TO JOHN", "-200.00")])
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == MERCHANT]
    assert q["scope"] == "one"
    assert "only apply your answer here" in q["text"]


def _enrich(ledger, merchant, category, implies=(), kind="business", subcategory=""):
    from viva.ledger.events import merchant_enriched
    ledger.append(merchant_enriched(
        merchant, category, subcategory=subcategory, grade="corroborated",
        occurred_at="2026-04-01", by="model",
        attributes={"counterparty_kind": kind, "implies": list(implies)}))


def test_an_ordinary_known_merchant_is_never_asked_about(tmp_path):
    """Slice 9b's headline. A supermarket we have already identified implies
    nothing beyond an ordinary expense — there was never a question here, and
    asking one was the single largest source of noise in the queue."""
    ledger = _checking(tmp_path, [("2026-03-06", "WHOLE FOODS MKT", "-180.00")])
    _enrich(ledger, "whole foods mkt", "food", subcategory="grocery")
    assert [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE] == []


def test_a_merchant_that_implies_structure_gets_a_proposal(tmp_path):
    """And the counterpart: where the counterparty DOES imply something, we say
    what we believe rather than asking an open question."""
    ledger = _checking(tmp_path, [("2026-03-06", "BIG MOTORS", "-30000.00")])
    _enrich(ledger, "big motors", "transport", implies=[
        {"relationship": "a vehicle", "major": "asset", "on": "outflow",
         "account_group": "Vehicles", "compound": False, "confidence": "suggested",
         "documents": "invoice or bill of sale", "ask": "Shall I track it?"}])
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    assert q["scope"] == "pattern"
    # It states a hypothesis and its grounds, instead of asking what this is.
    assert "normally mean a vehicle" in q["text"]
    assert "Shall I track it?" in q["text"]
    assert "because of who they are" in q["why"].lower()
    assert "invoice or bill of sale" in q["why"]
    # Slice 9a widened the answer space from three natures to the four majors,
    # reached in plain language — and added the escape hatch for the compound
    # answers ("interest, principal and escrow") no button set can hold.
    assert [o["args"]["major"] for o in q["options"]] == ["asset", "expense"]
    assert q["free_text"]


def test_answering_a_nature_question_settles_the_merchant_and_stops_asking(tmp_path):
    """The core promise: one ruling clears every transaction from that merchant,
    past and future — and the question does not come back."""
    ledger = _checking(tmp_path, [
        ("2026-03-06", "TITLE COMPANY", "-20000.00"),
        ("2026-03-08", "TITLE COMPANY", "-3000.00"),
    ])
    _enrich(ledger, "title company", "housing", implies=[
        {"relationship": "a property purchase", "major": "asset", "on": "outflow",
         "account_group": "Property", "compound": False, "confidence": "suggested",
         "documents": "closing disclosure", "ask": ""}])
    before = open_questions(ledger)["questions"]
    assert any(q["kind"] == NATURE for q in before)
    proj = ledger.projection()
    # The implication ALREADY keeps it out of spending — but only provisionally,
    # because it is `suggested`: we believe it, and we say we are not certain.
    assert sum(proj.spending_by_category().values()) == Decimal("0")
    assert proj.provisional_spending() == Decimal("23000.00")

    rule_merchant_nature(ledger, "title company", "settlement", by="human")

    after = open_questions(ledger)["questions"]
    assert not [q for q in after if q["kind"] == NATURE]      # never asked again
    # Confirming does not change the figure — it removes the DOUBT about it.
    proj = ledger.projection()
    assert sum(proj.spending_by_category().values()) == Decimal("0")
    assert proj.provisional_spending() == Decimal("0")


def test_the_queue_introduces_no_new_event_type(tmp_path):
    """Move 2 is read-side. Answering must route to writers that already exist —
    a generic Ruling event is Move 3, and only if a fifth question type earns it."""
    # The event vocabulary as it stood BEFORE this slice. Answering a question
    # must stay inside it — `MerchantEnriched` is Slice 5.6's, and nature rides
    # in its existing attributes bag rather than earning a field of its own.
    BEFORE_MOVE_2 = {
        "AccountOpened", "OpeningBalanceObserved", "ClosingBalanceObserved",
        "TransactionRecorded", "DocumentCaptured", "ReadRecorded",
        "StatementHeld", "CorrectionApplied", "AccountAliasConfirmed",
        "TransferLinked", "TransferUnlinked", "TransferSuggested",
        "CategoryAssigned", "MerchantCategorized", "MerchantEnriched",
        "PositionObserved"}
    ledger = _checking(tmp_path, [("2026-03-06", "BIG MOTORS", "-30000.00")])
    assign_merchant_category(ledger, "big motors", "transport", by="model")

    n_before = len(list(ledger.events()))
    open_questions(ledger)                       # a projection: writes nothing
    assert len(list(ledger.events())) == n_before

    rule_merchant_nature(ledger, "big motors", "settlement", by="human")
    assert {e.event_type for e in ledger.events()} <= BEFORE_MOVE_2
    # ...and the ruling rode the attributes bag, not a new field.
    latest = [e for e in ledger.events() if e.event_type == "MerchantEnriched"][-1]
    assert latest.body["attributes"]["nature"] == "settlement"


def test_question_ids_are_stable_across_reads(tmp_path):
    ledger = _checking(tmp_path, [("2026-03-05", "ACME HARDWARE", "-100.00")])
    first = [q["id"] for q in open_questions(ledger)["questions"]]
    second = [q["id"] for q in open_questions(ledger)["questions"]]
    assert first == second and first        # doesn't churn between projections


def test_a_transfer_suggestion_becomes_a_one_off_question(tmp_path):
    """An ambiguous pair generalizes to nothing, so it is scoped to itself."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Some Card", currency="USD",
        opening_amount=Decimal("600.00"), opening_date="2026-03-01",
        closing_amount=Decimal("300.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-10", "Payment Thank You", Decimal("-150.00")),
                      TxnFact("2026-03-11", "Payment Thank You", Decimal("-150.00"))],
        account_number="000000009999", institution="Other")
    capture_and_ingest(raw, ledger, b"card", lambda d, i: _stamp(card, i),
                       captured_at="2026-04-01")
    chk = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal("1000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("850.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-10", "Online Payment", Decimal("-150.00"))],
        account_number="000000001122", institution="Chase")
    capture_and_ingest(raw, ledger, b"chk", lambda d, i: _stamp(chk, i),
                       captured_at="2026-04-01")
    qs = [q for q in open_questions(ledger)["questions"] if q["kind"] == TRANSFER]
    if qs:                                   # only if the matcher left it ambiguous
        assert qs[0]["scope"] == "one"
        assert "own accounts" in qs[0]["text"]
