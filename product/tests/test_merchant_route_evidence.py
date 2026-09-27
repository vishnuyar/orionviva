"""Typed identity, private scope and durable question parity."""
from types import SimpleNamespace

import pytest

from merchantcore import is_shareable, normalize_merchant
from viva.ledger import EventStore, Ledger, LedgerProjection, account_opened, simple_transaction
from viva.ledger.events import merchant_enriched
from viva.questions import _merchant_questions, _nature_questions
from viva.read_store import ReadStore


def events_for(descriptor, kind="", category=""):
    events = [account_opened("synthetic-cash", "depository", "Invented cash", "USD", "2026-01-01")]
    events += [simple_transaction("synthetic-cash", "-10", descriptor, day,
                                  kind="depository")
               for day in ("2026-01-02", "2026-01-03")]
    if kind:
        events.append(merchant_enriched(normalize_merchant(descriptor), category,
            occurred_at="2026-01-04", by="default" if not category else "human", attributes={"counterparty_kind": kind}))
    return events


@pytest.mark.parametrize("descriptor", ["VELVET TO ORBIT", "VELVET FROM ORBIT", "VÉLVET", "!!!"])
def test_privacy_refusal_does_not_assert_person_or_channel(descriptor):
    assert not is_shareable(descriptor)
    proj = LedgerProjection(events_for(descriptor))
    assert {proj.tier_of(m) for m in proj.movements()} == {"unknown"}
    merchants = _merchant_questions(proj)
    for question in merchants:
        assert "payment to a person" not in question.text
        assert question.scope == "one"
        assert len(question.refs["movements"]) == question.count == 2
    for question in _nature_questions(proj):
        assert "names how the money moved" not in question.why
        assert "don't yet know" in question.why


@pytest.mark.parametrize("kind", ["peer", "instrument"])
def test_shareable_typed_counterparty_never_offers_pattern(kind):
    proj = LedgerProjection(events_for("VELVET ORBIT", kind))
    question, = _merchant_questions(proj)
    assert question.scope == "one"
    assert len(question.refs["movements"]) == 2
    assert "2 transactions" in question.text
    for question in _nature_questions(proj):
        assert "names how the money moved" not in question.why


@pytest.mark.parametrize("descriptor,kind", [("VELVET TO ORBIT", ""), ("VELVET ORBIT", "peer"), ("VELVET ORBIT", "instrument"), ("VÉLVET", "business"), ("!!!", ""), ("VELVET ORBIT", "unrecognized")])
def test_question_evidence_survives_index_rebuild_and_reopen(tmp_path, descriptor, kind):
    events = events_for(descriptor, kind)
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    expected = {q.id: q.to_dict() for q in _merchant_questions(LedgerProjection(events)) + _nature_questions(LedgerProjection(events))}
    root = tmp_path / "read"
    with ReadStore.create(root, "synthetic-passphrase") as reads:
        reads.synchronize(source)
    with ReadStore.open(root, "synthetic-passphrase") as reads:
        with reads.open_reader() as revision:
            actual = {q["id"]: q for q in revision.open_questions(as_of="2026-02-01", limit=None)["questions"] if q["kind"] in ("merchant", "nature")}
    assert actual == expected
    assert all("names how the money moved" not in q["why"] for q in actual.values())


@pytest.mark.parametrize("descriptor,kind", [("VELVET TO ORBIT", ""), ("VELVET ORBIT", "peer"), ("VELVET ORBIT", "instrument")])
def test_merchant_answer_writes_only_displayed_population(tmp_path, descriptor, kind):
    from viva.engine import _write_answer
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events_for(descriptor, kind)))
    ledger = Ledger(source)
    question, = _merchant_questions(ledger.projection())
    assert question.scope == "one"
    displayed = set(question.refs["movements"])
    ledger.append(simple_transaction("synthetic-cash", "-10", descriptor,
                                    "2026-01-05", kind="depository"))
    result = _write_answer(SimpleNamespace(ledger=ledger), question,
                          SimpleNamespace(value=lambda _: "food"), "food")
    assert set(result["settled_movements"]) == displayed
    proj = ledger.projection()
    for movement in proj.movements():
        category = proj.derived_category(movement) or {}
        assert (category.get("category_by", category.get("by")) == "human") == (movement.key in displayed)
    assert (proj.merchant_categories().get(normalize_merchant(descriptor)) or {}).get("by") != "human"


@pytest.mark.parametrize("kind", ["peer", "instrument"])
def test_stale_pattern_answer_cannot_override_typed_scope(tmp_path, kind):
    from viva.engine import _write_answer
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events_for("VELVET ORBIT")))
    ledger = Ledger(source)
    question, = _merchant_questions(ledger.projection())
    assert question.scope == "pattern"
    ledger.append(events_for("VELVET ORBIT", kind)[-1])
    before = list(source.events())
    result = _write_answer(SimpleNamespace(ledger=ledger), question,
                           SimpleNamespace(value=lambda _: "food"), "food")
    from viva.desktop_bridge.conversation_actions import _outcome_of
    from viva.persona import moment
    outcome = _outcome_of(result)
    assert result["ok"] is False
    assert outcome.kind == "refused" and outcome.reason == "question_changed"
    assert outcome.message == moment("reply_question_changed")
    assert "No answer was applied" in outcome.message
    assert "reopen" in outcome.message
    assert list(source.events()) == before


@pytest.mark.parametrize("kind", ["peer", "instrument"])
def test_nature_answer_never_reaches_sibling(tmp_path, kind):
    from viva.listen import Interpretation, propose, apply_proposal
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events_for("VELVET ORBIT", kind)))
    ledger = Ledger(source)
    proj = ledger.projection()
    selected, sibling = proj.movements()
    interpretation = Interpretation(legs=[{"major": "expense", "category": "food"}])
    with pytest.raises(ValueError, match="specific transaction"):
        propose(proj, interpretation, selected.description)
    proposal = propose(proj, interpretation, selected.description, movement_key=selected.key)
    assert proposal.scope == "movement" and proposal.subject == selected.key
    apply_proposal(ledger, proposal, "2026-01-06")
    by_key = {m.key: m for m in ledger.projection().movements()}
    assert by_key[selected.key].nature_reason == "ruling"
    assert by_key[sibling.key].nature_reason != "ruling"


@pytest.mark.parametrize("kind", ["", "unrecognized", "business"])
def test_abstention_and_private_business_preserve_tiers(kind):
    descriptor = "VELVET TO ORBIT"
    proj = LedgerProjection(events_for(descriptor, kind, "food" if kind else ""))
    assert {proj.tier_of(m) for m in proj.movements()} == {"unknown"}
    assert all("person" not in q.why and "names how" not in q.why for q in _nature_questions(proj))
    ordinary = LedgerProjection(events_for("VELVET ORBIT", kind))
    question, = _merchant_questions(ordinary)
    assert question.scope == "pattern"
    assert "person" not in question.text


def test_mixed_group_does_not_inherit_first_members_claim():
    proj = LedgerProjection(events_for("VELVET ORBIT"))
    first = proj.movements()[0].key
    proj.counterparty_kind = lambda m: "peer" if m.key == first else "business"
    question, = _merchant_questions(proj)
    assert question.scope == "one" and question.count == 2
    assert "person" not in question.text
    assert len(question.refs["movements"]) == 2


def test_mixed_privacy_group_checks_every_member_on_both_reads(tmp_path):
    events = events_for("VELVET ORBIT")
    events[2] = simple_transaction("synthetic-cash", "-10", "VELVET ORBIT Ω",
                                   "2026-01-03", kind="depository")
    proj = LedgerProjection(events)
    question, = _merchant_questions(proj)
    assert question.count == 2 and question.scope == "one"
    assert "person" not in question.text
    assert len(question.refs["movements"]) == 2
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            indexed, = [q for q in revision.open_questions(as_of="2026-02-01", limit=None)["questions"] if q["kind"] == "merchant"]
    assert indexed == question.to_dict()


@pytest.mark.parametrize("canonical_grade,legacy_grade,expected_kind", [
    ("unverified", "verified", "peer"),
    ("verified", "unverified", "business"),
    ("verified", "verified", "business"),
    ("corroborated", "unverified", "business"),
    ("unverified", "corroborated", "peer"),
])
def test_alias_legacy_grade_evidence_matches_after_rebuild_and_reopen(
        tmp_path, canonical_grade, legacy_grade, expected_kind):
    from viva.ledger.merchant_keys import resolve_keys
    events = events_for("VELVET ORBIT") + [
        merchant_enriched("canonical", "", by="default", aliases=["velvet orbit"],
            grade=canonical_grade, attributes={"counterparty_kind": "business"}),
        merchant_enriched("velvet orbit", "", by="default", grade=legacy_grade,
            attributes={"counterparty_kind": "peer"}),
    ]
    proj = LedgerProjection(events, resolve_keys=resolve_keys)
    assert {proj.counterparty_kind(m) for m in proj.movements()} == {expected_kind}
    expected = {q.id: q.to_dict() for q in _merchant_questions(proj) + _nature_questions(proj)}
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    root = tmp_path / "read"
    with ReadStore.create(root, "synthetic-passphrase") as reads:
        reads.synchronize(source)
    with ReadStore.open(root, "synthetic-passphrase") as reads:
        with reads.open_reader() as revision:
            actual = {q["id"]: q for q in revision.open_questions(as_of="2026-02-01", limit=None)["questions"] if q["kind"] in ("merchant", "nature")}
    assert actual == expected


@pytest.mark.parametrize("canonical_kind,legacy_kind,canonical_grade,legacy_grade", [
    ("peer", "business", "verified", "unverified"),
    ("business", "peer", "unverified", "verified"),
    ("instrument", "business", "verified", "verified"),
])
def test_proposal_uses_grade_selected_evidence_and_writes_one_movement(
        tmp_path, canonical_kind, legacy_kind, canonical_grade, legacy_grade):
    from viva.ledger.merchant_keys import resolve_keys
    from viva.listen import Interpretation, propose, apply_proposal
    events = events_for("VELVET ORBIT") + [
        merchant_enriched("canonical", "", by="default", aliases=["velvet orbit"],
            grade=canonical_grade, attributes={"counterparty_kind": canonical_kind}),
        merchant_enriched("velvet orbit", "", by="default", grade=legacy_grade,
            attributes={"counterparty_kind": legacy_kind}),
    ]
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    ledger = Ledger(source)
    proj = LedgerProjection(events, resolve_keys=resolve_keys)
    selected, sibling = proj.movements()
    interpretation = Interpretation(legs=[{"major": "expense", "category": "food"}])
    with pytest.raises(ValueError, match="specific transaction"):
        propose(proj, interpretation, selected.description)
    proposal = propose(proj, interpretation, selected.description, movement_key=selected.key)
    assert proposal.scope == "movement" and proposal.subject == selected.key
    apply_proposal(ledger, proposal, "2026-01-06")
    after = LedgerProjection(list(source.events()), resolve_keys=resolve_keys)
    by_key = {m.key: m for m in after.movements()}
    assert by_key[selected.key].nature_reason == "ruling"
    assert by_key[sibling.key].nature_reason != "ruling"


def test_mixed_alias_evidence_scopes_indexed_answer_to_displayed_members(tmp_path):
    from viva.ledger.merchant_keys import resolve_keys
    from viva.engine import _write_answer
    events = events_for("VELVET ORBIT")
    events[2] = simple_transaction("synthetic-cash", "-10", "SILKEN COMET",
                                   "2026-01-03", kind="depository")
    events += [
        merchant_enriched("canonical", "", by="default", grade="unverified",
            aliases=["velvet orbit", "silken comet"],
            attributes={"counterparty_kind": "business"}),
        merchant_enriched("velvet orbit", "", by="default", grade="verified",
            attributes={"counterparty_kind": "peer"}),
        merchant_enriched("silken comet", "", by="default", grade="verified",
            attributes={"counterparty_kind": "business"}),
    ]
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    ledger = Ledger(source, resolve_keys=resolve_keys)
    question, = _merchant_questions(ledger.projection())
    assert question.scope == "one" and question.count == 2
    assert "person" not in question.text
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as reads:
        reads.synchronize(source)
    with ReadStore.open(tmp_path / "read", "synthetic-passphrase") as reads:
        with reads.open_reader() as revision:
            indexed, = [q for q in revision.open_questions(as_of="2026-02-01", limit=None)["questions"] if q["kind"] == "merchant"]
    assert indexed == question.to_dict()
    displayed = set(indexed["refs"]["movements"])
    ledger.append(simple_transaction("synthetic-cash", "-10", "VELVET ORBIT",
                                    "2026-01-05", kind="depository"))
    _write_answer(SimpleNamespace(ledger=ledger), SimpleNamespace(**indexed),
                  SimpleNamespace(value=lambda _: "food"), "food")
    projection = ledger.projection()
    for movement in projection.movements():
        category = projection.derived_category(movement) or {}
        assert (category.get("category_by", category.get("by")) == "human") == (movement.key in displayed)


@pytest.mark.parametrize("bound", ["MAX_RHYTHM_ACCOUNTS", "MAX_RESOLVER_PROFILES", "MAX_RHYTHM_JSON_BYTES"])
def test_indexed_question_evidence_refuses_oversized_inputs(monkeypatch, bound):
    import json
    import sqlite3
    from merchantcore.profile import Profile, Template
    from viva.read_store import question_evidence
    from viva.read_store.rhythm import RhythmReadError
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE accounts(source_sequence INTEGER,event_type TEXT,"
                       "account_id TEXT,kind TEXT,institution TEXT)")
    connection.execute("CREATE TABLE resolver_profiles(institution TEXT,account_kind TEXT,profile_json TEXT)")
    connection.execute("INSERT INTO accounts VALUES(1,'AccountOpened','cash','depository','Invented')")
    profile = Profile("Invented", "depository", "v1", templates=[Template("PAY {brand}")])
    connection.execute("INSERT INTO resolver_profiles VALUES(?,?,?)",
                       ("Invented", "depository", json.dumps(profile.to_dict())))
    monkeypatch.setattr(question_evidence, bound, 0)
    try:
        with pytest.raises(RhythmReadError, match="question evidence"):
            question_evidence.movement_records(connection, [], {})
    finally:
        connection.close()


@pytest.mark.parametrize("choose_movement", [False, True])
def test_insufficient_descriptor_proposal_cannot_write_to_sufficient_sibling(tmp_path, choose_movement):
    from viva.ledger.merchant_keys import resolve_keys
    from viva.listen import Interpretation, propose, apply_proposal
    raw = "AB *CEDARFURNITURE123, 555-010-0200"
    events = events_for(raw)
    events[2] = simple_transaction("synthetic-cash", "-10", "AB", "2026-01-03", kind="depository")
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    ledger = Ledger(source, resolve_keys=resolve_keys)
    proj = ledger.projection()
    target = next(m for m in proj.movements() if m.description == raw)
    sibling = next(m for m in proj.movements() if m.description == "AB")
    assert proj.merchant_keys_of(target) == ("",)
    assert proj.merchant_keys_of(sibling) == ("ab",)
    interpretation = Interpretation(legs=[{"major": "expense", "category": "food"}])
    if not choose_movement:
        before = list(source.events())
        with pytest.raises(ValueError, match="specific transaction"):
            propose(proj, interpretation, raw)
        assert list(source.events()) == before
        return
    proposal = propose(proj, interpretation, raw, movement_key=target.key)
    apply_proposal(ledger, proposal, "2026-01-06")
    after = {m.key: m for m in ledger.projection().movements()}
    assert after[target.key].nature_reason == "ruling"
    assert after[sibling.key].nature_reason != "ruling"
    assert proposal.scope == "movement" and proposal.subject == target.key


def test_repeated_insufficient_descriptor_requires_explicit_movement():
    from viva.ledger.merchant_keys import resolve_keys
    from viva.listen import Interpretation, propose
    raw = "AB *CEDARFURNITURE123, 555-010-0200"
    proj = LedgerProjection(events_for(raw), resolve_keys=resolve_keys)
    interpretation = Interpretation(legs=[{"major": "expense", "category": "food"}])
    with pytest.raises(ValueError, match="specific transaction"):
        propose(proj, interpretation, raw)
    target = proj.movements()[0]
    proposal = propose(proj, interpretation, raw, movement_key=target.key)
    assert proposal.scope == "movement" and proposal.subject == target.key


@pytest.mark.parametrize("grammar_supported", [False, True])
def test_ordinary_and_grammar_supported_identity_still_generalize(grammar_supported):
    from merchantcore.profile import Profile, Template
    from viva.ledger.merchant_keys import resolve_keys
    from viva.listen import Interpretation, propose
    raw = "XY*CEDARFURNITURE123" if grammar_supported else "VELVET ORBIT"
    grammar = Profile("Invented", "depository", "v1", templates=[Template("{brand}*{reference}")])
    resolver = (lambda rows: resolve_keys(rows, profile_for=lambda *_: grammar)) if grammar_supported else resolve_keys
    proj = LedgerProjection(events_for(raw), resolve_keys=resolver)
    assert all(proj.merchant_key_of(m) for m in proj.movements())
    proposal = propose(proj, Interpretation(legs=[{"major": "expense", "category": "food"}]), raw)
    assert proposal.scope == "merchant" and proposal.settles == 2


def test_insufficient_target_engine_response_is_an_ordinary_no_write_refusal(tmp_path):
    from viva.engine import record_ruling
    from viva.listen import Interpretation
    from viva.ledger.merchant_keys import resolve_keys
    from viva.desktop_bridge.conversation_actions import _outcome_of
    from viva.persona import moment
    raw = "AB *CEDARFURNITURE123, 555-010-0200"
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events_for(raw)))
    ledger = Ledger(source, resolve_keys=resolve_keys)
    before = list(source.events())
    result = record_ruling(SimpleNamespace(ledger=ledger),
        Interpretation(legs=[{"major": "expense", "category": "food"}]), descriptor=raw)
    outcome = _outcome_of(result)
    assert result["ok"] is False
    assert outcome.kind == "refused" and outcome.reason == "movement_required"
    assert outcome.message == moment("reply_select_transaction")
    assert "No answer was applied" in outcome.message
    assert list(source.events()) == before
