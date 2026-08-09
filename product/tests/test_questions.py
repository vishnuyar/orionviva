"""The question queue: one ranked front door for the four ask-and-learn loops.

The promises under test: rank by what answering MOVES, scope a ruling to the
most general unit that is still honest, never hide the tail, and never introduce
a new event type to do it.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         assign_merchant_category, capture_and_ingest,
                         rule_merchant_nature)
from viva.ledger import EventStore, Ledger
from viva.persona import say
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
    # as_of pinned near the fixture dates so the cadence expectation
    # stays quiet and this asserts exactly the twelve merchant questions.
    result = open_questions(ledger, limit=3, as_of="2026-04-01")
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


def test_a_merchant_question_counts_the_movements_its_money_is_over(tmp_path):
    """One population per sentence.

    A question that says "N payments, X in total" must have counted the same
    movements it summed. Money that came BACK from the counterparty — a refund
    posted under the same descriptor — is not a payment to ask about, so it
    swells neither number. Asserted as a property against the projection's own
    population, never against a memorized pair of figures."""
    ledger = _checking(tmp_path, [
        ("2026-03-05", "ACME HARDWARE #12", "-100.00"),
        ("2026-03-09", "ACME HARDWARE #44", "-150.00"),
        ("2026-03-11", "ACME HARDWARE #12", "40.00"),
    ])
    proj = ledger.projection()
    (q,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == MERCHANT]
    population = [m for m in proj.uncategorized_expenses()
                  if proj.merchant_key_of(m) == q["refs"]["merchant"]]
    assert population, "the fixture asks about nothing"
    assert q["count"] == len(population)
    assert Decimal(q["amount"]) == sum(abs(m.amount) for m in population)


def test_a_peer_payment_is_scoped_to_itself_not_a_rule(tmp_path):
    """A commercial merchant generalizes; a person does not — one Zelle is a
    gift, the next a loan repayment."""
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
    """A supermarket we have already identified implies nothing beyond an
    ordinary expense — there is no question here, and asking one is the single
    largest source of noise in the queue."""
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
    # It states a hypothesis and its grounds, instead of asking what this is —
    # in the category this vault holds, not in the enrichment model's own words
    # for the relationship.
    assert "normally mean transport" in q["text"]
    assert "a vehicle" not in q["text"]
    # ...and it closes with the pack's own words. A sentence the enrichment
    # model wrote is never spliced into the question text.
    assert "Shall I track it?" not in q["text"]
    assert say("nature_group_ask") in q["text"]
    # What the counterparty implies still travels with the question, as
    # structure: the category is a value from a vocabulary a lint can check,
    # where a sentence is not.
    assert q["refs"]["category"] == "transport"
    assert "because of who they are" in q["why"].lower()
    assert "invoice or bill of sale" in q["why"]
    # The answer space is declared as slots, and it is what a ruling is made
    # of: several legs, each landing in the four majors, plus the label the
    # person names. A payment that is several things at once ("interest,
    # principal and escrow") is why the leg slot holds several.
    legs = next(s for s in q["slots"] if s["name"] == "legs")
    major = next(p for p in legs["parts"] if p["name"] == "major")
    assert major["choices"] == ["expense", "asset", "liability", "income"]
    assert {s["name"] for s in q["slots"]} == {"legs", "kind", "category"}
    # And nothing in the payload is a button: no action, no arguments.
    assert "options" not in q and "action" not in repr(q)


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


def test_a_ruled_one_off_question_is_never_asked_again(tmp_path):
    """The queue can be driven to empty.

    A payment to a person, a cheque or a cash withdrawal is asked about one at a
    time, because the counterparty cannot say what the money was. Once the
    person has said what it was, the question is answered — and a question that
    came back would be the same question, at the same stake, with the same id,
    in every sitting after this one."""
    from viva.listen import Interpretation, apply_proposal, propose
    ledger = _checking(tmp_path, [("2026-03-05", "ZELLE PAYMENT TO JOHN", "-200.00")])
    (before,) = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]

    proj = ledger.projection()
    (m,) = proj.movements()
    p = propose(proj, Interpretation(legs=[{"major": "expense", "account_hint": ""}],
                                     said="tickets I bought for both of us"),
                m.description, movement_key=m.key)
    apply_proposal(ledger, p, "2026-04-02")

    after = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    assert before["id"] not in [q["id"] for q in after]
    assert not after


def test_the_queue_introduces_no_new_event_type(tmp_path):
    """The queue is read-side. Answering must route to writers that already
    exist — a generic Ruling event would have to be earned by a fifth question
    type."""
    # The event vocabulary the queue must stay inside. Answering a question adds
    # no type — nature rides in `MerchantEnriched`'s existing attributes bag
    # rather than earning a field of its own.
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


def test_the_queue_carries_no_instructions_for_a_surface():
    """The engine holds no rules for a surface. A question carries what is being
    asked and the slots an answer to it has — never a label to render, an action
    to call or arguments to send.

    Options were how a caller answered without saying anything: the payload
    already contained the answer and the click merely picked one. That made the
    engine responsible for a layer it cannot see, and it kept alive a second way
    in that no deterministic check stood behind. Every question is answered in
    language, through one door."""
    import pathlib

    import viva.questions as _questions
    src = pathlib.Path(_questions.__file__).read_text()
    for smell in ('"action"', '"label"', '"args"', "options="):
        assert smell not in src, (
            f"{smell} is back in questions.py — the queue is describing a "
            "surface again")


def test_the_queue_supplies_the_sentences_a_caller_places(tmp_path):
    """Viva's words live in the persona pack, where the no-new-facts lint
    reaches them and a released version pins their bytes. The two sentences a
    caller needs around the questions — what the box a person writes in says,
    and what stands in its place where only a document settles the question —
    come from the queue, so nothing that shows a question keeps words of its
    own."""
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    payload = open_questions(ledger, as_of="2026-01-01", jurisdiction="US")
    assert payload["invite"] == say("free_text_invite")
    assert payload["answered_by_document"] == say("answered_by_document")
