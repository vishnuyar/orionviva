"""SQL-native interview and complete question lookup parity."""
from pathlib import Path

import pytest

from viva.ingest import registry
from viva.ledger import (EventStore, LedgerProjection, Provenance,
                         account_opened, document_captured)
from viva.ledger.events import (SCOPE_ATTRIBUTE, VERIFIED, question_declined,
                                ruling_recorded)
from viva.questions import find_question, open_questions, pending_questions
from viva.read_store import ReadStore
from viva.read_store import questions as sql_questions
from viva.read_store.rhythm import RhythmReadError


PASSWORD = "correct horse battery staple"


def _events():
    account = "Assets:Property:Café Cottage"
    first = account_opened(account, "asset", "Café Cottage", "USD",
                           "2026-03-01", origin="asserted")
    nickname = ruling_recorded(
        SCOPE_ATTRIBUTE, f"{account}:nickname", "2026-03-02", by="human",
        grade=VERIFIED, said="Café", value="Café")
    projection = LedgerProjection([first, nickname])
    purchase = next(question for question in open_questions(
        projection, as_of="2026-03-03", jurisdiction="US", locale="en-US",
        limit=None)["questions"] if question["id"].endswith(":purchase_price"))
    declined = question_declined(
        purchase["id"], purchase["kind"], "2026-03-03", reason="not_now",
        amount=purchase["amount"], count=purchase["count"])
    return [first, nickname, declined], purchase["id"]


def _source(path: Path, events):
    source = EventStore.open(path / "events.jsonl", PASSWORD)
    source.append_atomically(lambda _existing: tuple(events))
    return source


def _attribute(account, key, value, day="2026-03-02"):
    return ruling_recorded(SCOPE_ATTRIBUTE, f"{account}:{key}", day,
                           by="human", grade=VERIFIED, said=str(value),
                           value=str(value))


def _assert_queue_parity(tmp_path, events):
    expected = open_questions(LedgerProjection(events), as_of="2026-03-03",
                              jurisdiction="US", locale="en-US", limit=None)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=None)
    assert actual == expected
    return actual


@pytest.mark.parametrize("jurisdiction", ["US", "CA"])
def test_interview_and_complete_queue_match_canonical(tmp_path, jurisdiction):
    events, _question_id = _events()
    expected = open_questions(LedgerProjection(events), as_of="2026-03-03",
        jurisdiction=jurisdiction, locale="en-US", limit=None)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-03",
                jurisdiction=jurisdiction, locale="en-US", limit=None)
    assert actual == expected


def test_find_and_pending_are_the_same_live_interview_payload(tmp_path):
    events, question_id = _events()
    projection = LedgerProjection(events)
    expected_question = find_question(projection, question_id,
        as_of="2026-03-03", jurisdiction="US", locale="en-US").to_dict()
    expected_pending = pending_questions(projection, as_of="2026-03-03",
        jurisdiction="US", locale="en-US")
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            assert revision.find_question(question_id, as_of="2026-03-03",
                jurisdiction="US", locale="en-US") == expected_question
            assert revision.pending_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US") == expected_pending
            assert revision.find_question("interview:not:live", as_of="2026-03-03",
                jurisdiction="US", locale="en-US") is None


def test_question_id_input_is_bounded_before_sql_work(tmp_path):
    events, _question_id = _events()
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            with pytest.raises(ValueError, match="bounded"):
                revision.find_question("x" * 513, as_of="2026-03-03",
                                       jurisdiction="US")


def _document_answer_events(doc_type: str):
    account = "Assets:Bank:Alias parity"
    doc_id = "doc-alias-parity"
    return [
        document_captured(doc_id, "statement.pdf", 20, doc_type, 0.91,
                          "2026-03-01"),
        account_opened(account, "depository", "Alias parity", "USD",
                       "2026-03-01", jurisdiction="US", institution="Bank",
                       provenance=Provenance(doc_id=doc_id)),
    ]


@pytest.mark.parametrize("profile", registry._SEED,
                         ids=lambda profile: profile.doc_type)
def test_every_registered_document_alias_has_canonical_interview_semantics(
        tmp_path, profile):
    """Stored classifier aliases resolve exactly as the canonical projection."""
    labels = (profile.doc_type, *sorted(profile.aliases))
    for index, label in enumerate(labels):
        events = _document_answer_events(label)
        expected = open_questions(LedgerProjection(events), as_of="2026-03-03",
                                  jurisdiction="US", locale="en-US", limit=None)
        root = tmp_path / str(index)
        with ReadStore.create(root / "read-model", PASSWORD) as reads:
            reads.synchronize(_source(root, events))
            with reads.open_reader() as revision:
                actual = revision.open_questions(as_of="2026-03-03",
                    jurisdiction="US", locale="en-US", limit=None)
        assert actual == expected, label


@pytest.mark.parametrize("label", ["unknown_statement", "账单_未知", "  账单  "])
def test_unknown_and_unicode_document_labels_keep_canonical_unknown_behavior(
        tmp_path, label):
    events = _document_answer_events(label)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-03",
                              jurisdiction="US", locale="en-US", limit=None)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=None)
    assert actual == expected


def test_dense_interview_queue_shows_two_hundred_and_reports_exact_tail(tmp_path):
    events = []
    for index in range(205):
        account = f"Liabilities:Cards:Interview {index:03d}"
        events.append(account_opened(account, "liability", f"Card {index:03d}",
            "USD", "2026-03-01", jurisdiction="US", origin="asserted"))
    # Include the ordinary declined interview fixture so the dense-interview
    # result is composed with another live/pending decision, not in isolation.
    fixture, _question_id = _events()
    events.extend(fixture)
    expected = open_questions(LedgerProjection(events), as_of="2026-03-03",
                              jurisdiction="US", locale="en-US", limit=200)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=200)
    assert actual == expected
    assert len(actual["questions"]) == 200
    assert actual["tail"]["count"] == actual["total"] - 200


def test_interview_history_and_identity_bounds_refuse_independently(
        tmp_path, monkeypatch):
    fixture, _question_id = _events()
    events = fixture + _document_answer_events("checking_statement")
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            connection = revision.connection
            for constant, message, call in (
                ("MAX_INTERVIEW_ACCOUNT_ROWS", "account history",
                 lambda: sql_questions._interview_accounts(connection)),
                ("MAX_INTERVIEW_DOCUMENT_ROWS", "captured-document history",
                 lambda: sql_questions._interview_document_types(connection)),
                ("MAX_ATTRIBUTE_HISTORY_ROWS", "attribute answer history",
                 lambda: sql_questions.attribute_answers(
                     connection, as_of="9999-12-31")),
                ("MAX_QUESTION_CANDIDATES", "identity bound",
                 lambda: sql_questions._bounded_candidate_identities(
                     (), sql_questions._interview_possible_ids(connection, "US"))),
            ):
                monkeypatch.setattr(sql_questions, constant, 0)
                with pytest.raises(RhythmReadError, match=message):
                    call()
                monkeypatch.undo()


def _property_candidate_events(count):
    events = []
    for index in range(count):
        account = f"Assets:Property:Candidate {index:03d}"
        events.extend((
            account_opened(account, "asset", f"Candidate {index:03d}", "USD",
                           "2026-03-01", jurisdiction="US", origin="asserted"),
            _attribute(account, "financed", "yes"),
        ))
    return events


def test_all_question_reads_refuse_complete_post_compose_candidate_overflow(
        tmp_path):
    # The production US property schema has seven ordinary identities and one
    # synthetic home-loan opening identity per account: 571 * 7 = 3,997 schema
    # ids, plus 571 opens ids.  Declines/live filtering cannot bypass this cap.
    events = _property_candidate_events(571)
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            calls = (
                lambda: revision.open_questions(as_of="2026-03-03",
                    jurisdiction="US", locale="en-US", limit=1),
                lambda: revision.find_question(
                    "interview:Assets:Property:Candidate 000:nickname",
                    as_of="2026-03-03", jurisdiction="US", locale="en-US"),
                lambda: revision.pending_questions(as_of="2026-03-03",
                    jurisdiction="US", locale="en-US"),
            )
            for call in calls:
                with pytest.raises(RhythmReadError, match="identity bound"):
                    call()


def test_exact_four_thousand_question_candidate_boundary_is_deterministic(
        tmp_path):
    # 500 property accounts * (seven schema ids + one opens id) = exactly 4,000.
    events = _property_candidate_events(500)
    target = "interview:Assets:Property:Candidate 000:nickname"
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            first = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=1)
            second = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=1)
            assert first == second
            assert revision.find_question(target, as_of="2026-03-03",
                jurisdiction="US", locale="en-US") == first["questions"][0]
            assert revision.pending_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US") == {
                    "questions": [], "total": 0}


def test_interview_production_selects_are_bounded_and_planned(tmp_path):
    events, _question_id = _events()
    with ReadStore.create(tmp_path / "read-model", PASSWORD) as reads:
        reads.synchronize(_source(tmp_path, events))
        with reads.open_reader() as revision:
            traced = []
            revision.connection.set_trace_callback(traced.append)
            try:
                sql_questions._interview_questions(
                    revision.connection, jurisdiction="US", locale="en-US")
            finally:
                revision.connection.set_trace_callback(None)
            selects = [statement for statement in traced
                       if statement.lstrip().upper().startswith("SELECT")]
            assert len(selects) == 6
            assert all("LIMIT" in statement.upper() for statement in selects)
            assert all(" OFFSET " not in statement.upper() for statement in selects)
            plans = [row[3] for statement in selects for row in
                     revision.connection.execute(
                         "EXPLAIN QUERY PLAN " + statement).fetchall()]
            assert not any("USE TEMP B-TREE" in plan.upper() for plan in plans)
            rendered = " ".join(plans)
            assert "accounts_by_source_date" in rendered
            assert "documents_by_source" in rendered
            assert "attributes_by_eligible_time" in rendered


def test_alias_semantics_survive_suffix_restart_and_held_revision(tmp_path):
    first = _document_answer_events("checking_statement")
    source = _source(tmp_path, first)
    model = tmp_path / "read-model"
    with ReadStore.create(model, PASSWORD) as reads:
        reads.synchronize(source)
        held = reads.open_reader()
        before = held.open_questions(as_of="2026-03-03", jurisdiction="US",
                                     locale="en-US", limit=None)
        second_account = "Assets:Bank:Second alias"
        source.append_atomically(lambda _events: (
            document_captured("doc-second", "second.pdf", 20,
                              "bank_statement", 0.91, "2026-03-02"),
            account_opened(second_account, "depository", "Second alias", "USD",
                           "2026-03-02", jurisdiction="US", institution="Bank",
                           provenance=Provenance(doc_id="doc-second")),
        ))
        reads.synchronize(source)
        assert held.open_questions(as_of="2026-03-03", jurisdiction="US",
                                   locale="en-US", limit=None) == before
        held.close()
    with ReadStore.open(model, PASSWORD) as reopened:
        with reopened.open_reader() as revision:
            actual = revision.open_questions(as_of="2026-03-03",
                jurisdiction="US", locale="en-US", limit=None)
    expected = open_questions(LedgerProjection(source.snapshot_events()),
        as_of="2026-03-03", jurisdiction="US", locale="en-US", limit=None)
    assert actual == expected


def test_conditional_deposit_essentials_unlock_and_suppress_in_pack_order(
        tmp_path):
    account = "Assets:Bank:Term deposit"
    base = [account_opened(account, "depository", "Term deposit", "USD",
                           "2026-03-01", jurisdiction="US",
                           institution="Example Bank")]
    first = _assert_queue_parity(tmp_path / "first", base)
    assert first["questions"][0]["id"].endswith(":sub_kind")

    fixed = base + [_attribute(account, "sub_kind", "certificate of deposit")]
    second = _assert_queue_parity(tmp_path / "second", fixed)
    assert second["questions"][0]["id"].endswith(":principal")

    with_principal = fixed + [_attribute(account, "principal", "1000")]
    third = _assert_queue_parity(tmp_path / "third", with_principal)
    ids = [question["id"] for question in third["questions"]]
    assert not any(identity.endswith(":principal") for identity in ids)
    assert ids[0].endswith(":maturity_date")


def test_open_and_link_questions_resolve_against_existing_accounts(tmp_path):
    prop = "Assets:Property:Home"
    loan = "Liabilities:HomeLoan:Mortgage"
    property_events = [
        account_opened(prop, "asset", "Home", "USD", "2026-03-01",
                       jurisdiction="US", origin="asserted"),
        _attribute(prop, "nickname", "Home"),
        _attribute(prop, "purchase_price", "250000"),
        _attribute(prop, "purchase_date", "2020-01-01"),
        _attribute(prop, "use", "occupied"),
        _attribute(prop, "financed", "yes"),
    ]
    unresolved = _assert_queue_parity(tmp_path / "unresolved", property_events)
    assert any(question["id"].endswith(":opens:home_loan")
               for question in unresolved["questions"])

    loan_events = property_events + [
        account_opened(loan, "liability", "Mortgage", "USD", "2026-03-01",
                       jurisdiction="US", origin="asserted"),
        _attribute(loan, "lender", "Example Lender"),
        _attribute(loan, "original_amount", "200000"),
        _attribute(loan, "start_date", "2020-01-01"),
    ]
    link_open = _assert_queue_parity(tmp_path / "link", loan_events)
    link = next(question for question in link_open["questions"]
                if question["id"].endswith(":secures"))
    assert link["slots"][0]["choices"] == [prop]

    resolved_events = loan_events + [_attribute(loan, "secures", prop)]
    resolved = _assert_queue_parity(tmp_path / "resolved", resolved_events)
    ids = [question["id"] for question in resolved["questions"]]
    assert not any(identity.endswith(":secures") or
                   identity.endswith(":opens:home_loan") for identity in ids)
