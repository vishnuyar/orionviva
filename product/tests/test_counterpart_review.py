"""Debt evidence preserves movements while both default readers stay quiet."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.ledger import (EventStore, LedgerProjection, Posting, Provenance,
                         account_opened, transaction_recorded)
from viva.ledger.events import merchant_enriched
from viva.questions import open_questions
from viva.read_store import ReadStore

OPTIONS = dict(as_of="2026-03-01", jurisdiction="US", locale="en-US")
IMPLIED = {"major": "liability", "compound": False, "on": "outflow",
           "documents": "debt statement", "account_group": "Debt"}


def events_for(implied=IMPLIED):
    events = [account_opened("cash", "depository", "Everyday", "USD", "2026-01-01")]
    for day, amount in (("2026-01-10", "-71"), ("2026-01-20", "-83")):
        events.append(transaction_recorded(
            [Posting("cash", amount), Posting("Expenses:Unclassified", str(-Decimal(amount)))],
            "Fable Lending", day, provenance=Provenance(doc_id="bank-statement")))
    events.append(merchant_enriched("fable lending", "financial", occurred_at="2026-02-01",
        attributes={"counterparty_kind": "business", "implies": [implied] if implied else []}))
    return events


def paired(tmp_path, events):
    expected = open_questions(LedgerProjection(events), limit=None, **OPTIONS)
    source = EventStore.open(tmp_path / "events", "pw")
    source.append_atomically(lambda _: tuple(events))
    with ReadStore.create(tmp_path / "reads", "pw") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = revision.open_questions(limit=None, **OPTIONS)
    assert actual == expected
    return expected


def waits(payload):
    return [q for q in payload["questions"] if q["id"].startswith("expectation:counterpart:")]


def test_each_payment_waits_for_its_statement_without_account_hints(tmp_path):
    events = events_for()
    payload = paired(tmp_path, events)
    assert waits(payload) == []
    assert payload["total"] == 0
    assert len(LedgerProjection(events).movements()) == 2


@pytest.fixture(autouse=True)
def no_real_profiles(monkeypatch):
    from viva.ingest import transfers
    monkeypatch.setattr(transfers, "default_profile_for", lambda _proj: lambda _m: None)


def add_card(events, amount="-71", date="2026-01-11", name="Fable Lending", currency="USD", institution=""):
    events += [account_opened("card", "liability", name, currency, "2026-01-01", institution=institution),
        transaction_recorded([Posting("card", amount),
            Posting("Equity:Counterpart", str(-Decimal(amount)))],
            "Payment received", date, provenance=Provenance(doc_id="card-statement"))]
    return next(m.key for m in LedgerProjection(events).movements() if m.account == "card")


def test_own_account_without_posted_counterpart_still_waits(tmp_path):
    events = events_for()
    events.append(account_opened("card", "liability", "Fable Lending", "USD", "2026-01-01", institution="Fable Lending"))
    assert {m.nature_reason for m in LedgerProjection(events).movements()} == {"own_account"}
    assert len(waits(paired(tmp_path, events))) == 0


@pytest.mark.parametrize("candidate_state", ["live", "taken", "missing", "source_linked"])
def test_transfer_precedence_requires_current_source_and_candidate(tmp_path, candidate_state):
    from viva.ledger.events import transfer_suggested, transfer_linked
    events = events_for()
    source, other = [m.key for m in LedgerProjection(events).movements()]
    candidate = add_card(events)
    events.append(transfer_suggested(source, [candidate if candidate_state != "missing" else "missing"], {}, "2026-02-01"))
    if candidate_state in ("taken", "source_linked"):
        linked_source = other if candidate_state == "taken" else source
        events.append(transfer_linked(linked_source, candidate, "corroborated", {}, "2026-02-02"))
    payload = paired(tmp_path, events)
    transfer = [q for q in payload["questions"] if q["kind"] == "transfer"]
    assert len(transfer) == 0
    waiting_keys = {q["refs"]["movement"] for q in waits(payload)}
    assert waiting_keys == set()
    assert not [q for q in payload["questions"] if q["kind"] == "nature"]


@pytest.mark.parametrize("implied", [None, {**IMPLIED, "compound": True},
    {**IMPLIED, "major": "asset"}, {**IMPLIED, "documents": ""},
    {k: v for k, v in IMPLIED.items() if k != "compound"},
    {**IMPLIED, "on": "inflow"}])
@pytest.mark.parametrize("suggested", [False, True])
def test_ineligible_metadata_keeps_existing_review(tmp_path, implied, suggested):
    from viva.ledger.events import transfer_suggested
    events = events_for(implied)
    source = LedgerProjection(events).movements()[0].key
    if suggested:
        candidate = add_card(events, name="Other Debt")
        events.append(transfer_suggested(source, [candidate], {}, "2026-02-01"))
    payload = paired(tmp_path, events)
    assert waits(payload) == []
    assert not [q for q in payload["questions"] if q["kind"] == "nature"]


@pytest.mark.parametrize("settlement", ["link", "ruling"])
def test_declined_wait_is_findable_until_settled_then_stale_everywhere(tmp_path, settlement):
    from viva import engine
    from viva.ledger import Ledger
    from viva.ledger.events import question_declined, ruling_recorded, transfer_linked
    from viva.questions import find_question, open_question_counts, pending_questions
    events = events_for()
    from viva.questions import _nature_questions
    question = next(q.to_dict() for q in _nature_questions(LedgerProjection(events), "en-US")
                    if q.id.startswith("expectation:counterpart:"))
    events.append(question_declined(question["id"], "expectation", "2026-02-01",
                                   amount=question["amount"], count=1))
    source = EventStore.open(tmp_path / "events", "pw")
    source.append_atomically(lambda _: tuple(events))
    ledger = Ledger(source)
    with ReadStore.create(tmp_path / "reads", "pw") as reads:
        for settled in (False, True):
            if settled:
                if settlement == "ruling":
                    event = ruling_recorded("movement", question["refs"]["movement"], "2026-02-02",
                        legs=[{"major": "expense", "account": "Expenses:Other", "share": ""}])
                else:
                    extra = []
                    candidate = add_card(extra)
                    for event in extra: ledger.append(event)
                    event = transfer_linked(question["refs"]["movement"], candidate,
                                            "corroborated", {}, "2026-02-02")
                ledger.append(event)
            reads.synchronize(source)
            projection = ledger.projection()
            canonical = open_questions(projection, limit=None, **OPTIONS)
            counts = open_question_counts(projection, **OPTIONS)
            pending = pending_questions(projection, **OPTIONS)
            found = find_question(projection, question["id"], **OPTIONS)
            assert bool(found) is not settled
            assert pending["total"] == 0
            assert counts["total"] == canonical["total"]
            assert counts["pending"] == canonical["pending"]["count"]
            with reads.open_reader() as revision:
                assert revision.open_questions(limit=None, **OPTIONS) == canonical
                assert revision.pending_questions(**OPTIONS) == pending
                indexed = revision.find_question(question["id"], **OPTIONS)
                assert indexed is None, "retired corroboration questions do not enter the SQL default queue"
            if settled:
                assert engine.answer_question(SimpleNamespace(ledger=ledger), question["id"], "yes")["why"] == "not_open"


def test_document_answers_cannot_create_accounts(tmp_path):
    from viva import engine
    from viva.ledger import Ledger
    from viva.questions import find_question
    source = EventStore.open(tmp_path / "events", "pw")
    source.append_atomically(lambda _: tuple(events_for()))
    ledger = Ledger(source)
    vault = SimpleNamespace(ledger=ledger)
    from viva.questions import _nature_questions
    q = next(q.to_dict() for q in _nature_questions(ledger.projection(), "en-US")
             if q.kind == "expectation")
    question = find_question(ledger, q["id"], **OPTIONS)
    before = list(ledger.events())
    accounts_before = ledger.projection().accounts()
    response = engine._write_answer(vault, question, SimpleNamespace(value=lambda _: "yes"), "yes")
    assert response["ok"] and response["recorded"] is False
    assert list(ledger.events()) == before
    response = engine._write_answer(vault, question, SimpleNamespace(value=lambda _: "no"), "not now")
    assert response["ok"]
    assert [event.event_type for event in list(ledger.events())[len(before):]] == ["QuestionDeclined"]
    assert ledger.projection().accounts() == accounts_before


@pytest.mark.parametrize("state", ["captured", "held", "unrelated"])
def test_an_existing_statement_does_not_satisfy_a_payment(tmp_path, state):
    from viva.ingest import StatementFacts
    from viva.ledger import document_captured
    from viva.ledger.events import statement_held
    events = events_for()
    events.append(document_captured("other", "synthetic.pdf", 12,
        "credit_card_statement", 1, "2026-02-01"))
    if state == "held":
        facts = StatementFacts(doc_id="other", doc_type="credit_card_statement",
            doc_type_confidence=1, account_ref="Other Card", currency="USD",
            opening_amount=Decimal("100"), opening_date="2026-01-01",
            closing_amount=Decimal("20"), closing_date="2026-01-31", transactions=[])
        events.append(statement_held("other", facts.to_dict(), {}, "reconciliation",
                                     "2026-02-01"))
    elif state == "unrelated":
        add_card(events, amount="-23")
    assert len(waits(paired(tmp_path, events))) == 0


@pytest.mark.parametrize("card_first", [False, True])
@pytest.mark.parametrize("repeated", [False, True])
def test_two_payment_imports_link_separately_preserving_original_records(tmp_path, card_first, repeated):
    from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                             capture_and_ingest, link_transfers, sweep)
    from viva.ledger import Ledger
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events", "pw"))
    amounts = ("-71", "-71" if repeated else "-83")
    def facts(card):
        rows = [("2026-01-10", "Payment received", amounts[0]),
                ("2026-01-12", "Payment received", amounts[1])] if card else [
                ("2026-01-13", "01/10 Payment to Lumen 2222", amounts[0]),
                ("2026-01-14", "01/12 Payment to Lumen 2222", amounts[1])]
        return StatementFacts(doc_id="", doc_type="credit_card_statement" if card else "checking_statement",
            doc_type_confidence=1, account_ref="Card 2222" if card else "Cash 1111",
            account_number="2222" if card else "1111", institution="Lumen" if card else "Vale",
            currency="USD", opening_amount=Decimal("900"), opening_date="2026-01-01",
            closing_amount=Decimal("900") + sum(map(Decimal, amounts)), closing_date="2026-01-31",
            transactions=[TxnFact(day, description, Decimal(amount)) for day, description, amount in rows])
    bank, card = facts(False), facts(True)
    retained = {}
    for is_card in (card_first, not card_first):
        statement = card if is_card else bank
        def read(_data, identity):
            statement.doc_id = identity
            return ReadResult(statement.doc_type, 1, statement)
        capture_and_ingest(raw, ledger, b"card" if is_card else b"bank", read,
                           captured_at="2026-02-01")
        for m in ledger.projection().movements():
            snapshot = (m.account, m.amount, m.currency, m.date)
            assert retained.get(m.key, snapshot) == snapshot
            retained[m.key] = snapshot
    projection = ledger.projection()
    assert len(retained) == 4
    links = projection.transfer_links()
    assert len(links) == 2
    by_key = {m.key: m for m in projection.movements()}
    for link in links:
        a, b = by_key[link["a"]], by_key[link["b"]]
        source, destination = (a, b) if a.kind == "depository" else (b, a)
        assert source.description[:5].replace("/", "-") == destination.date[5:]
        assert source.date != destination.date
        assert source.amount == destination.amount
    before = list(ledger.events())
    assert sum(e.event_type == "TransactionRecorded" for e in before) == 4
    assert sum(e.event_type == "AccountOpened" for e in before) == 2
    for _ in range(2):
        link_transfers(ledger, profile_for=lambda _m: None)
        sweep(ledger)
    assert list(ledger.events()) == before
    replay = LedgerProjection(before)
    assert replay.transfer_links() == links
    assert {(m.key, m.account, m.amount, m.currency, m.date) for m in replay.movements()} == {
        (key, *values) for key, values in retained.items()}


@pytest.mark.parametrize("case", ["no_account_evidence", "two_cards", "wrong_currency", "outside_window"])
def test_conservative_matcher_never_closes_unsupported_waits(tmp_path, case):
    from viva.ingest import link_transfers
    from viva.ledger import Ledger
    events = events_for()
    currency = "EUR" if case == "wrong_currency" else "USD"
    date = "2026-02-20" if case == "outside_window" else "2026-01-10"
    candidate = add_card(events, currency=currency, date=date, name="Other Card",
                         institution="Fable Lending" if case == "two_cards" else "")
    if case == "two_cards":
        events.append(account_opened("card2", "liability", "Second Card", "USD", "2026-01-01",
                                     institution="Fable Lending"))
        events.append(transaction_recorded([Posting("card2", "-71"), Posting("Equity:Other", "71")],
            "Payment received", date, provenance=Provenance(doc_id="other-card")))
    store = EventStore.open(tmp_path / "match-events", "pw")
    store.append_atomically(lambda _: tuple(events))
    ledger = Ledger(store)
    link_transfers(ledger, profile_for=lambda _m: None)
    assert ledger.projection().transfer_links() == []
    payload = paired(tmp_path, list(ledger.events()))
    assert not waits(payload)
    assert not [q for q in payload["questions"] if q["kind"] == "transfer"]


@pytest.mark.parametrize("change", ["currency", "amount", "date", "direction"])
def test_stale_suggestion_must_still_pass_current_candidate_gate(tmp_path, change):
    from viva.ledger.events import transfer_suggested
    events = events_for()
    source = LedgerProjection(events).movements()[0].key
    candidate = add_card(events, currency="EUR" if change == "currency" else "USD",
        amount="-72" if change == "amount" else "71" if change == "direction" else "-71",
        date="2026-02-20" if change == "date" else "2026-01-11")
    events.append(transfer_suggested(source, [candidate], {}, "2026-02-01"))
    payload = paired(tmp_path, events)
    assert not waits(payload)
    assert not [q for q in payload["questions"] if q["kind"] == "transfer"]
