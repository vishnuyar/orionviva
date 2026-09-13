"""Optional event shapes crossing every converted desktop payload boundary."""

from contextlib import contextmanager

import pytest

from viva.demo import build_demo_vault
from viva.demo import DEMO_PASSPHRASE
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ingest.reader import live_reading_configured
from viva.ledger import Provenance
from viva.ledger.events import (account_alias_confirmed, account_identity_observed,
                                agent_acted, category_assigned,
                                conversation_proposal_recorded,
                                conversation_turn_opened,
                                conversation_turn_settled, finding_set_aside,
                                goal_proposal_recorded,
                                merchant_categorized, movement_tagged, read_recorded,
                                transfer_suggested)
from viva.questions import ACTIONABLE_QUESTION_WINDOW, open_questions
from viva.surface.account_ledger import account_ledger
from viva.surface.activity import activity
from viva.surface.conversation import timeline
from viva.surface.documents import documents
from viva.surface.outbound import outbound
from viva.surface.overview import overview
from viva.surface.plans import plans
from viva.surface.review import question_review_binding, review
from viva.surface.spending import spending_breakdown
from viva.persona import moment
from viva.vault import Vault
from product.tests.test_read_store_route_contract_register import OPTIONAL_SOURCE_FIELDS


READ_ON = "2026-08-29"
HISTORY = "2026-03-31"
QUESTION_AS_OF = "2026-09-30"
ACCOUNT = "acct:everyday-checking"


def _add_optional_events(vault):
    cited = Provenance("source-雪", 0, "line ☕", "0.0000")
    movement = vault.ledger.projection().movements()[0].key
    additions = (
        category_assigned(movement, "Synthetic", "Food", "verified",
                          "2026-03-01", subcategory="", provenance=cited),
        category_assigned(movement, "Synthetic", "Food", "verified",
                          "2026-03-01", subcategory="Coffee", provenance=cited),
        account_identity_observed(ACCOUNT, "2026-08-28", account_names=["雪", "雪"],
                                  provenance=cited),
        account_alias_confirmed("alias:optional", ACCOUNT, "optional-doc",
                                "2026-03-01", learn_signal=False,
                                match_names=["雪", "雪"], match_label="",
                                kind="depository", provenance=cited),
        movement_tagged(movement, ["旅", "旅", ""], "2026-03-02",
                        provenance=Provenance()),
        transfer_suggested(movement, [movement, movement],
                           {"empty": "", "null": None, "zero": 0,
                            "order": ["雪", "雪"]}, "2026-03-03", cited),
        goal_proposal_recorded(
            "optional-goal", "create", "", {"goal_id": "goal:optional",
            "title": "Optional", "currency": "USD", "target_amount": "0.0000",
            "order": ["雪", "雪"], "null": None},
            {"zero": 0, "empty": ""}, "2026-03-04", cited),
        conversation_turn_opened("optional-turn", "ask", "Why?",
                                 "2026-03-05", provenance=cited),
        conversation_turn_settled(
            "optional-turn", "completed", "", "2026-03-06",
            answer={"zero": 0, "null": None, "order": ["雪", "雪"]}),
        conversation_proposal_recorded(
            "optional-conversation", "optional-turn", "q:optional", "",
            {"kind": "correction", "order": ["雪", "雪"]},
            {"zero": 0, "null": None}, "2026-03-06", cited),
        finding_set_aside("finding:optional", "fee_observed",
                             {"zero": 0, "null": None}, "2026-03-06",
                             provenance=cited),
        read_recorded("optional-doc", "route", "v1", "text", "",
                      0.0, 0, 0, False, None, "2026-03-07",
                      provenance=cited, phase="extract", resolved_model=""),
        agent_acted("optional-rule", "induce", "optional-target", "refused",
                    "2026-03-08", calls=0,
                    stake={"zero": 0, "null": None, "order": ["雪", "雪"]},
                    provenance=cited),
    )
    vault.ledger.store.append_atomically(lambda _existing: additions)
    vault.synchronize_read_store()


def _oracle(vault, provider, revision):
    projection = vault.ledger.projection()
    historical = vault.ledger.projection_as_of(HISTORY)
    source_head = revision.connection.execute(
        "SELECT source_head FROM projection_meta WHERE singleton=1").fetchone()[0]
    current_overview = overview(projection, "en-US", READ_ON)
    queue = open_questions(projection, limit=ACTIONABLE_QUESTION_WINDOW,
                           as_of=QUESTION_AS_OF, locale="en-US")
    queue = {**queue, "questions": [
        {**question, "review_binding": question_review_binding(
            projection, question, "en-US")}
        for question in queue["questions"]]}
    trust_events = vault.events()
    return {
        ("overview", "current"): current_overview,
        ("overview", "historical"): overview(historical, "en-US", READ_ON),
        ("overview_accounts", "current"): {
            "state": "ready", "freshness": "current",
            "lifecycle": vault.read_store_lifecycle,
            "revision": revision.generation, "overview": current_overview,
            "accounts": current_overview, "error": ""},
        ("spending", "current"): spending_breakdown(
            projection, "en-US", READ_ON),
        ("documents", "current"): documents(
            projection, frozenset(vault.raw.doc_ids()),
            live_reading_configured(), "en-US"),
        ("review", "current"): review(
            projection, "en-US", as_of=QUESTION_AS_OF),
        ("activity", "current"): activity(projection, "en-US", 100),
        ("activity", "historical"): activity(historical, "en-US", 100),
        ("plans", "current"): plans(projection, "en-US", READ_ON),
        ("conversation", "current"): timeline(projection, queue),
        ("trust", "current"): {
            "state": "ready", "outbound": outbound(trust_events, "en-US"),
            "absences": [{"id": "anchoring", "sentence": moment("trust_no_anchoring")}],
            "notes": []},
        ("account_ledger", "current"): account_ledger(
            projection, ACCOUNT, "en-US", source_head,
            cursor_secret=provider._cursor_secret, limit=10),
    }


def _parameters(route, variant):
    if route == "overview":
        return {"read_on": READ_ON, **({"as_of": HISTORY}
                                     if variant == "historical" else {})}
    if route == "overview_accounts":
        return {"read_on": READ_ON}
    if route == "spending":
        return {"read_on": READ_ON}
    if route == "review" or route == "conversation":
        return {"as_of": QUESTION_AS_OF}
    if route == "activity":
        return {"as_of": HISTORY} if variant == "historical" else {}
    if route == "plans":
        return {"read_on": READ_ON}
    if route == "account_ledger":
        return {"account_id": ACCOUNT, "limit": 10}
    return {}


def test_optional_corpus_has_full_wire_parity_on_ten_routes_and_historical_branches(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_LOCALE", "en-US")
    vault = build_demo_vault(tmp_path / "sample")
    _add_optional_events(vault)
    observed = {(event.event_type, field) for event in vault.events()
                for field in event.body}
    missing = {(route, family, field) for route, fields in OPTIONAL_SOURCE_FIELDS.items()
               for family, field in fields.items()
               if (family, field) not in observed}
    assert not missing, missing
    source = tuple(vault.events())
    categories = [event.body for event in source
                  if event.event_type == "CategoryAssigned"
                  and event.body.get("category") == "Food"]
    assert any("subcategory" not in body for body in categories)
    assert any(body.get("subcategory") == "Coffee" for body in categories)
    assert any(event.body.get("stake") == {"zero": 0, "null": None}
               for event in source if event.event_type == "FindingSetAside")
    assert any(event.body.get("answer", {}).get("order") == ["雪", "雪"]
               for event in source if event.event_type == "ConversationTurnSettled")
    assert any(event.body.get("cost_usd") == 0.0 and
               event.body.get("parse_error") is None
               for event in source if event.event_type == "ReadRecorded")
    assert any(event.provenance == Provenance("source-雪", 0, "line ☕", "0.0000")
               for event in source)
    provider = OpenedVaultSurfaceProvider(vault)
    with vault.read_store.open_reader() as revision:
        overview(revision.overview_projection(today=READ_ON), "en-US", READ_ON)
        overview(revision.historical_overview_projection(
            as_of=HISTORY, today=READ_ON), "en-US", READ_ON)
        expected = _oracle(vault, provider, revision)
    assert {route for route, _variant in expected} == provider._READS - {"jobs"}
    monkeypatch.setattr(vault.ledger, "projection",
                        lambda: pytest.fail("canonical projection fallback"))
    monkeypatch.setattr(vault.ledger, "projection_as_of",
                        lambda *_args: pytest.fail("historical event replay"))
    monkeypatch.setattr(vault.ledger, "fresh_projection",
                        lambda: pytest.fail("fresh projection fallback"))
    monkeypatch.setattr(vault.ledger.store, "snapshot_events",
                        lambda: pytest.fail("event snapshot fallback"))
    for (route, variant), payload in expected.items():
        actual = provider.read_surface(route, _parameters(route, variant))
        assert actual == payload, (route, variant)


def test_movement_only_category_does_not_enter_merchant_choice_vocabulary(
        tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_LOCALE", "en-US")
    vault = build_demo_vault(tmp_path / "sample")
    movement = vault.ledger.projection().movements()[0].key
    vault.ledger.append(category_assigned(
        movement, "Synthetic", "Only-Movement-Choice", "verified",
        "2026-03-01"))
    provider = OpenedVaultSurfaceProvider(vault)
    def choices():
        questions = provider.read_surface(
            "conversation", {"as_of": QUESTION_AS_OF})["questions"]
        return next(question["refs"]["categories"] for question in questions
                    if question["kind"] == "merchant")
    assert "Only-Movement-Choice" not in choices()
    vault.ledger.append(merchant_categorized(
        "synthetic merchant", "Only-Movement-Choice", "verified",
        "2026-03-02"))
    assert "Only-Movement-Choice" in choices()


def test_identity_observation_before_future_open_does_not_ghost_historical_account(
        tmp_path, monkeypatch):
    from viva.ledger.events import account_opened

    monkeypatch.setenv("VIVA_LOCALE", "en-US")
    vault = build_demo_vault(tmp_path / "sample")
    vault.ledger.append(account_identity_observed(
        "later-account", "2026-01-01", account_names=["雪", "雪"]))
    vault.ledger.append(account_opened(
        "later-account", "depository", "Later", "USD", "2026-09-01"))
    expected = overview(vault.ledger.projection_as_of(HISTORY), "en-US", READ_ON)
    with vault.read_store.open_reader() as revision:
        historical = revision.historical_overview_projection(
            as_of=HISTORY, today=READ_ON)
        assert "later-account" not in historical.accounts()
        assert overview(historical, "en-US", READ_ON) == expected
    assert OpenedVaultSurfaceProvider(vault).read_surface(
        "overview", {"as_of": HISTORY, "read_on": READ_ON}) == expected


def test_optional_route_payloads_are_generation_held_after_suffix(tmp_path, monkeypatch):
    monkeypatch.setenv("VIVA_LOCALE", "en-US")
    vault = build_demo_vault(tmp_path / "sample")
    provider = OpenedVaultSurfaceProvider(vault)
    held = vault.read_store.open_reader()
    try:
        before = _oracle(vault, provider, held)
        _add_optional_events(vault)
        original = vault.read_store.open_reader

        @contextmanager
        def held_reader():
            yield held

        monkeypatch.setattr(vault.read_store, "open_reader", held_reader)
        for (route, variant), payload in before.items():
            actual = provider.read_surface(route, _parameters(route, variant))
            if route == "overview_accounts":
                assert actual["revision"] == held.generation
                assert actual["overview"] == payload["overview"]
                assert actual["accounts"] == payload["accounts"]
            else:
                assert actual == payload, (route, variant)
        monkeypatch.setattr(vault.read_store, "open_reader", original)
        with original() as revision:
            after = _oracle(vault, provider, revision)
        assert after[("conversation", "current")] != before[("conversation", "current")]
        assert after[("trust", "current")] != before[("trust", "current")]
    finally:
        held.close()


@pytest.mark.parametrize("reconstruct", [False, True])
def test_optional_route_full_payload_survives_restart_or_authenticated_rebuild(
        tmp_path, monkeypatch, reconstruct):
    monkeypatch.setenv("VIVA_LOCALE", "en-US")
    directory = tmp_path / "sample"
    vault = build_demo_vault(directory)
    _add_optional_events(vault)
    provider = OpenedVaultSurfaceProvider(vault)
    with vault.read_store.open_reader() as revision:
        before = _oracle(vault, provider, revision)
    secret = provider._cursor_secret
    vault.close()
    if reconstruct:
        (directory / "read-model").rename(tmp_path / "retained-read-model")
    reopened = Vault.open(directory, DEMO_PASSPHRASE, create=False)
    try:
        assert reopened.synchronize_read_store() in {"equal", "caught_up", "rebuilt"}
        fresh = OpenedVaultSurfaceProvider(reopened, cursor_secret=secret)
        with reopened.read_store.open_reader() as revision:
            after = _oracle(reopened, fresh, revision)
        for key in before:
            old, new = before[key], after[key]
            if key == ("overview_accounts", "current"):
                assert new["overview"] == old["overview"]
                assert new["accounts"] == old["accounts"]
                assert new["revision"]
            else:
                assert new == old, key
            assert fresh.read_surface(key[0], _parameters(*key)) == new
    finally:
        reopened.close()
