"""Current Conversation and Trust SQL read contracts."""

import pytest
from decimal import Decimal

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.demo import build_demo_vault
from viva.ledger.events import (conversation_proposal_recorded,
                                conversation_proposal_resolved,
                                conversation_turn_opened,
                                conversation_turn_settled,
                                read_recorded, statement_held)
from viva.ingest.statement import StatementFacts, TxnFact
from viva.questions import open_questions
from viva.read_store.conversation import MAX_CONVERSATION_EVENTS
from viva.read_store.store import ReadStoreError
from viva.read_store.trust import outbound_events
from viva.surface.conversation import timeline
from viva.surface.outbound import outbound
from viva.surface.review import question_review_binding
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.synchronize_read_store()
    return vault


def _expected_conversation(vault, *, as_of, locale=""):
    projection = vault.ledger.projection()
    queue = open_questions(projection, limit=100, as_of=as_of, locale=locale)
    queue = {**queue, "questions": [{**question, "review_binding":
             question_review_binding(projection, question, locale)}
             for question in queue["questions"]]}
    return timeline(projection, queue)


def test_current_conversation_matches_complete_payload_and_held_revision(tmp_path):
    vault = _vault(tmp_path)
    vault.ledger.append(conversation_turn_opened(
        "turn-1", "ask", "What changed?", "2026-08-29"))
    vault.ledger.append(conversation_proposal_recorded(
        "proposal-1", "turn-1", "q-1", "Fix this", {"kind": "correction"},
        {"version": 1}, "2026-08-29"))
    vault.ledger.append(conversation_turn_settled(
        "turn-1", "proposal", "Done", "2026-08-29", proposal_id="proposal-1"))
    as_of = "2026-08-29"
    expected = _expected_conversation(vault, as_of=as_of)
    provider = OpenedVaultSurfaceProvider(vault)
    actual = provider.read_surface("conversation", {"as_of": as_of})
    assert actual == expected
    held = vault.read_store.open_reader()
    old = timeline(held.conversation_projection(locale="en-US"),
                   held.open_questions(as_of=as_of, limit=100))
    vault.ledger.append(conversation_proposal_resolved(
        "proposal-1", "turn-1", "completed", "Done", "2026-08-29"))
    assert timeline(held.conversation_projection(locale="en-US"),
                    held.open_questions(as_of=as_of, limit=100)) == old
    new = provider.read_surface("conversation", {"as_of": as_of})
    assert new != actual
    assert new["turns"][0]["proposal"]["status"] == "resolved"
    held.close()


def test_trust_exchange_history_refuses_cap_plus_one_whole(tmp_path, monkeypatch):
    from viva.read_store import trust as sql_trust

    vault = _vault(tmp_path)
    for index in range(2):
        vault.ledger.append(read_recorded(
            f"doc-{index}", "route", "prompt", "text", "reply",
            0, 1, 1, True, None, "2026-08-29"))
    monkeypatch.setattr(sql_trust, "MAX_TRUST_EXCHANGES", 1)
    with vault.read_store.open_reader() as revision:
        assert revision.connection.execute(
            "SELECT COUNT(*) FROM document_reads").fetchone()[0] == 2
        with pytest.raises(ReadStoreError, match="exchange history exceeds"):
            outbound_events(revision)
    with pytest.raises(BridgeRequestError, match="could not answer Trust"):
        OpenedVaultSurfaceProvider(vault).read_surface("trust", {})


@pytest.mark.parametrize("parameters,environment_locale", [
    ({"as_of": "2026-08-29"}, "en-US"),
    ({"as_of": "2026-08-29", "locale": "en-IN"}, "en-US"),
    ({"as_of": "2026-08-29"}, "en-IN"),
])
def test_conversation_queue_and_review_binding_match_canonical_locale(
        tmp_path, monkeypatch, parameters, environment_locale):
    monkeypatch.setenv("VIVA_LOCALE", environment_locale)
    vault = build_demo_vault(tmp_path / "sample")
    expected = _expected_conversation(
        vault, as_of=parameters["as_of"], locale=parameters.get("locale", ""))
    actual = OpenedVaultSurfaceProvider(vault).read_surface(
        "conversation", parameters)
    assert actual == expected


def test_generic_historical_hold_excludes_future_but_conversation_uses_current(
        tmp_path):
    vault = _vault(tmp_path)
    facts = StatementFacts(
        "future-held", "checking_statement", 1, "Synthetic account", "USD",
        Decimal("100"), "2026-02-01", Decimal("125"), "2026-02-28",
        [TxnFact("2026-02-15", "Synthetic deposit", Decimal("25"))],
        account_number="••••1234", institution="Synthetic bank")
    vault.ledger.append(statement_held(
        facts.doc_id, facts.to_dict(), {"message": "Needs review."}, "gap",
        "2026-02-28"))
    with vault.read_store.open_reader() as revision:
        generic = revision.open_questions(as_of="2026-01-01", locale="en-US")
    conversation = OpenedVaultSurfaceProvider(vault).read_surface(
        "conversation", {"as_of": "2026-01-01", "locale": "en-US"})
    assert not any(question["id"].startswith("reconciliation:future-held")
                   for question in generic["questions"])
    assert any(question["id"].startswith("reconciliation:future-held")
               for question in conversation["questions"])


def test_trust_all_phases_and_decimal_match_canonical_and_refuse_stale(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    for index, phase in enumerate(("classify", "extract", "interpret", "speak", "future")):
        vault.ledger.append(read_recorded(
            f"call-{index}", "route", "prompt", "text", "reply",
            0.0001, 2, 3, True, None, "2026-08-29", phase=phase))
    expected = outbound(vault.events(), "en-US")
    provider = OpenedVaultSurfaceProvider(vault)
    actual = provider.read_surface("trust", {})
    assert actual["outbound"] == expected
    assert actual["absences"] and actual["notes"] == []
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: (_ for _ in ()).throw(AssertionError("projection")))
    monkeypatch.setattr(vault, "events",
                        lambda: (_ for _ in ()).throw(AssertionError("events")))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: (_ for _ in ()).throw(AssertionError("raw")))
    assert provider.read_surface("trust", {}) == actual
    vault.read_store_lifecycle = "degraded"
    with pytest.raises(BridgeRequestError, match="not caught up"):
        provider.read_surface("trust", {})


def test_conversation_refuses_stale_without_projection_fallback(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: (_ for _ in ()).throw(AssertionError("projection")))
    monkeypatch.setattr(vault, "events",
                        lambda: (_ for _ in ()).throw(AssertionError("events")))
    monkeypatch.setattr(vault.raw, "doc_ids",
                        lambda: (_ for _ in ()).throw(AssertionError("raw")))
    assert OpenedVaultSurfaceProvider(vault).read_surface(
        "conversation", {"as_of": "2026-08-29"})["state"] == "ready"
    vault.read_store_lifecycle = "degraded"
    with pytest.raises(BridgeRequestError, match="not caught up"):
        OpenedVaultSurfaceProvider(vault).read_surface("conversation", {})


def test_conversation_history_refuses_n_plus_one(tmp_path):
    vault = _vault(tmp_path)
    events = tuple(conversation_turn_opened(
        f"turn-{index}", "ask", "Question?", "2026-08-29")
        for index in range(MAX_CONVERSATION_EVENTS + 1))
    vault.ledger.store.append_atomically(lambda _existing: events)
    vault.synchronize_read_store()
    with vault.read_store.open_reader() as revision:
        with pytest.raises(ReadStoreError, match="history exceeds"):
            revision.conversation_projection(locale="en-US").conversation_turns()


def test_conversation_and_trust_use_source_order_without_temporary_sort(tmp_path):
    vault = _vault(tmp_path)
    with vault.read_store.open_reader() as revision:
        queries = (
            "SELECT h.event_type,h.occurred_at,CASE WHEN length(CAST(h.body_json AS BLOB))<=? "
            "THEN h.body_json END,a.event_id "
            "FROM conversation_turn_history h JOIN applied_events a "
            "ON a.sequence=h.source_sequence ORDER BY h.source_sequence LIMIT ?",
            "SELECT h.event_type,h.occurred_at,CASE WHEN length(CAST(h.body_json AS BLOB))<=? "
            "THEN h.body_json END,a.event_id "
            "FROM conversation_proposal_history h JOIN applied_events a "
            "ON a.sequence=h.source_sequence ORDER BY h.source_sequence LIMIT ?",
            "SELECT occurred_at,CASE WHEN length(CAST(body_json AS BLOB))<=? "
            "THEN body_json END FROM document_reads "
            "INDEXED BY document_reads_by_source ORDER BY source_sequence LIMIT ?",
        )
        plans = [" ".join(str(row[-1]) for row in revision.connection.execute(
            "EXPLAIN QUERY PLAN " + query, (1_000_000, 10_001)).fetchall())
            for query in queries]
    assert all("TEMP B-TREE" not in plan for plan in plans)
    assert all("SCAN" in plan for plan in plans)
    assert "document_reads_by_source" in plans[-1]
