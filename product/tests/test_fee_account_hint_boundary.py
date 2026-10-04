"""Source instruments and expense components have different ledger roles."""

import json
from decimal import Decimal

import pytest

from viva import engine
from viva.ledger.events import (Posting, account_opened, ruling_recorded,
                                transaction_recorded)
from viva.listen import (Interpretation, MovementSelectionRequired, Proposal,
                         apply_proposal, listen, propose, resolve_account)
from viva.vault import Vault


def _vault(tmp_path, name="Harbor Checking", currency="USD"):
    vault = Vault.open(tmp_path / "vault", "pw")
    account = "Assets:Bank:synthetic-source"
    vault.ledger.append(account_opened(
        account, "depository", name, currency, "2026-05-01",
        institution="Harbor"))
    vault.ledger.append(transaction_recorded([
        Posting(account, Decimal("-12")),
        Posting("Expenses:Uncategorized", Decimal("12"))],
        "QUILLFEATHER SERVICES", "2026-05-02"))
    movement = vault.ledger.projection().movements()[0]
    return vault, movement


def _interpret(*hints, major="expense", said="A fee", category="fees"):
    return Interpretation(legs=[{"major": major, "account_hint": hint,
                                "share": "1" if len(hints) == 1 else ""}
                               for hint in hints], said=said, category=category)


def _proposal(vault, movement, interp):
    return propose(vault.ledger.projection(), interp, movement.description,
                   "12", movement.currency, movement.key)


@pytest.mark.parametrize("said", ["A fee", "Harbor Checking charged this fee",
                                  "Call the expense component Harbor Checking"])
def test_source_hint_defaults_without_registration(tmp_path, said):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret("Harbor Checking", said=said))
    assert proposal.legs == [{"major": "expense", "account": "Expenses:Uncategorized",
                              "share": "1"}]
    assert proposal.new_accounts == []
    assert proposal.category == "fees"
    assert proposal.scope == "movement" and proposal.subject == movement.key
    assert "no separate named component" in proposal.summary()
    assert "creates" not in proposal.summary()


def test_no_projected_movement_convenience_fee_is_safe(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    raw = json.dumps({"legs": [{"major": "expense", "account_hint": "Harbor Checking",
                                "share": "100"}], "category": "fees"})
    proposal = listen(vault.ledger.projection(), "A fee", "fee", "12", "USD",
                      "synthetic-movement", source="Harbor Checking",
                      extract_fn=lambda prompt: raw)
    assert proposal.legs[0]["account"] == "Expenses:Uncategorized"
    # The categorical fee meaning is usable; an unstated model percentage is not.
    assert proposal.legs[0]["share"] == ""
    assert proposal.new_accounts == []


def test_named_components_are_preserved_without_registration(tmp_path):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret("premium", "repair"))
    assert [leg["account"] for leg in proposal.legs] == [
        "Expenses:Other:premium", "Expenses:Other:repair"]
    assert proposal.new_accounts == []
    assert proposal.summary().index("premium") < proposal.summary().index("repair")
    assert "component" in proposal.summary()
    assert "creates" not in proposal.summary()
    assert proposal.unknown_split
    before = vault.ledger.projection().account_infos()
    apply_proposal(vault.ledger, proposal, "2026-05-03")
    assert vault.ledger.projection().account_infos() == before
    assert len([e for e in vault.events() if e.event_type == "AccountOpened"]) == 1


@pytest.mark.parametrize("invalid", ["Expenses:Other:fee", "Income:Other:bonus",
                                     "Assets:Other:", "Else:Other:name", "Assets:Other:!!!", None])
def test_registration_preflight_checks_all_entries_before_writing(tmp_path, invalid):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret(""))
    proposal.new_accounts = ["Assets:Other:New thing", invalid]
    before = list(vault.ledger.store.events())
    with pytest.raises(ValueError):
        apply_proposal(vault.ledger, proposal, "2026-05-03")
    assert list(vault.ledger.store.events()) == before


@pytest.mark.parametrize("major,root", [("expense", "Expenses"), ("income", "Income")])
@pytest.mark.parametrize("name,currency", [("Plum-Current", "EUR"), ("雪 Orbit", "JPY")])
def test_arbitrary_source_names_and_currencies_keep_own_major(tmp_path, major, root, name, currency):
    vault, movement = _vault(tmp_path, name, currency)
    proposal = _proposal(vault, movement, _interpret(name.upper().replace("-", "  "), major=major))
    assert proposal.legs[0]["account"] == root + ":Uncategorized"
    assert proposal.currency == currency
    assert proposal.new_accounts == []


@pytest.mark.parametrize("hint", ["Harbor", "Harbor depository", "Harbor depository account",
                                  "synthetic-source", "Assets:Bank:synthetic-source"])
def test_source_record_identity_aliases_are_guarded(tmp_path, hint):
    vault, movement = _vault(tmp_path)
    assert _proposal(vault, movement, _interpret(hint)).legs[0]["account"] == "Expenses:Uncategorized"


def test_compound_collision_clears_only_the_matching_leg(tmp_path):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret("premium", "Harbor Checking", "repair"))
    assert [l["account"] for l in proposal.legs] == ["Expenses:Other:premium",
        "Expenses:Uncategorized", "Expenses:Other:repair"]
    assert all(l["share"] == "" for l in proposal.legs)
    summary = proposal.summary()
    assert summary.index("premium") < summary.index("no separate named component") < summary.index("repair")
    assert "won't guess" in summary
    assert not proposal.new_accounts


@pytest.mark.parametrize("major,wrong_root", [("expense", "Assets"), ("income", "Assets")])
def test_ruled_candidate_matching_stays_under_its_own_major(tmp_path, major, wrong_root):
    vault, movement = _vault(tmp_path)
    vault.ledger.append(ruling_recorded("movement", movement.key, "2026-05-03",
        legs=[{"major": "asset" if wrong_root == "Assets" else "expense",
               "account": wrong_root + ":Other:premium", "share": "1"}]))
    match = resolve_account(vault.ledger.projection(), major, "premium")
    assert match.verdict == "new"
    assert match.account.startswith("Expenses:" if major == "expense" else "Income:")


def test_existing_named_component_and_context_prefixed_interest_survive(tmp_path):
    vault, movement = _vault(tmp_path)
    vault.ledger.append(ruling_recorded("movement", "another-movement", "2026-05-03",
        legs=[{"major": "expense", "account": "Expenses:Mortgage:Newco interest", "share": "1"}]))
    proposal = _proposal(vault, movement, _interpret("Newco interest", said="That part was interest"))
    assert proposal.legs[0]["account"] == "Expenses:Mortgage:Newco interest"
    assert not proposal.new_accounts


@pytest.mark.parametrize("hints", [("premium", "repair"), ("Harbor Checking", "")])
def test_missing_source_compound_requires_selection_without_model_retry(tmp_path, hints, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "pw")
    interp = _interpret(*hints)
    with pytest.raises(MovementSelectionRequired):
        propose(vault.ledger.projection(), interp, "fee", movement_key="missing")
    result = engine.record_ruling(vault, interp, "fee", movement_key="missing")
    assert result["ok"] is False and result["why"] == "movement_required"
    calls = []
    def fake(prompt):
        calls.append(prompt)
        return json.dumps({"legs": interp.legs})
    with pytest.raises(MovementSelectionRequired):
        listen(vault.ledger.projection(), "Components", "fee", movement_key="missing", extract_fn=fake)
    assert len(calls) == 1
    assert not list(vault.events())


def test_missing_source_empty_hint_compound_can_proceed(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    proposal = propose(vault.ledger.projection(), _interpret("", ""), "fee", movement_key="missing")
    assert [l["account"] for l in proposal.legs] == ["Expenses:Uncategorized"] * 2
    assert not proposal.new_accounts


def test_grouped_population_requires_every_source_and_guards_the_union(tmp_path):
    vault, first = _vault(tmp_path)
    vault.ledger.append(account_opened("Assets:Bank:second", "investment", "Orchid Reserve", "USD", "2026-05-01"))
    vault.ledger.append(transaction_recorded([Posting("Assets:Bank:second", "-8"),
        Posting("Expenses:Uncategorized", "8")], first.description, "2026-05-04"))
    proj = vault.ledger.projection()
    keys = [m.key for m in proj.movements()]
    proposal = propose(proj, _interpret("Harbor Checking", "Orchid Reserve"), first.description,
                       movement_key=first.key, movements=keys)
    assert [l["account"] for l in proposal.legs] == ["Expenses:Uncategorized"] * 2
    with pytest.raises(MovementSelectionRequired):
        propose(proj, _interpret("premium", "repair"), first.description,
                movement_key=first.key, movements=keys + ["missing"])
    partial = propose(proj, _interpret("premium"), first.description,
                      movement_key=first.key, movements=keys + ["missing"])
    assert partial.legs[0]["account"] == "Expenses:Uncategorized"


@pytest.mark.parametrize("major,hint,expected", [("asset", "Harbor Checking", "Assets:Bank:synthetic-source"),
    ("asset", "Orchid violin", "Assets:Other:Orchid violin"),
    ("liability", "Orchid loan", "Liabilities:Other:Orchid loan")])
def test_asset_and_debt_resolution_remains_compatible(tmp_path, major, hint, expected):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret(hint, major=major, category=""))
    assert proposal.legs[0]["account"] == expected
    assert bool(proposal.new_accounts) == (hint != "Harbor Checking")
    apply_proposal(vault.ledger, proposal, "2026-05-03")
    assert vault.ledger.projection().seen_account(expected)


def test_empty_hint_ordinary_answer_still_applies_immediately(tmp_path):
    vault, movement = _vault(tmp_path)
    result = engine.record_ruling(vault, _interpret(""), movement.description, movement.key)
    assert result["ok"] and result["confirm"] is False
    assert any(e.event_type == "RulingRecorded" for e in vault.events())


@pytest.mark.parametrize("hints", [("Harbor Checking",), ("premium", "repair")])
def test_named_fee_correction_applies_immediately_and_survives_reload(tmp_path, monkeypatch, hints):
    from types import SimpleNamespace
    from viva.desktop_bridge.conversation_actions import ConversationActions
    from viva.listen import category_vocabulary, ruling_slots
    from viva.questions import Question
    from viva.reply import INTERPRET_VERSION

    vault, movement = _vault(tmp_path)
    question = Question(id="synthetic-nature", kind="nature", text="Explain this movement", why="Explicitly requested editor",
        amount=Decimal("12"), currency="USD", count=1, scope="one",
        slots=ruling_slots(category_vocabulary(vault.ledger.projection())),
        refs={"movement": movement.key, "descriptor": movement.description})
    monkeypatch.setattr("viva.questions.find_question", lambda *a, **k: question)
    raw = json.dumps({"legs": [{"major": "expense", "account_hint": h,
                               "share": "100" if len(hints) == 1 else ""} for h in hints],
                      "category": "fees"})
    def extractor(prompt):
        extractor.exchanges.append({"prompt": prompt, "result": SimpleNamespace(text=raw)})
        return raw
    extractor.exchanges = []
    monkeypatch.setattr(engine, "_interpreter", lambda: extractor)
    before_accounts = vault.ledger.projection().account_infos()
    outcome = ConversationActions(vault).answer({"question_id": question.id, "said": "That was a fee"})
    assert outcome["kind"] == "completed"
    after = list(vault.events())
    captured = next(e for e in after if e.event_type == "ReadRecorded")
    assert json.loads(captured.body["response_text"])["text"] == raw
    assert captured.body["prompt_version"] == INTERPRET_VERSION
    assert not [e for e in after if e.event_type == "ConversationProposalRecorded"]
    assert [e for e in after if e.event_type == "RulingRecorded"]
    assert [e for e in after if e.event_type == "CategoryAssigned"]
    reopened = Vault.open(tmp_path / "vault", "pw")
    assert reopened.ledger.projection().account_infos() == before_accounts
    assert reopened.ledger.projection().movements()[0].account == movement.account
    ruling = reopened.ledger.projection().rulings()[0]
    expected = ["Expenses:Other:premium", "Expenses:Other:repair"] if len(hints) == 2 else ["Expenses:Uncategorized"]
    assert [leg["account"] for leg in ruling["legs"]] == expected


def test_invalid_old_proposal_is_a_recoverable_refusal(tmp_path):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret(""))
    proposal.new_accounts = ["Assets:Other:New thing", "Expenses:Other:fee"]
    before = list(vault.events())
    result = engine.apply_ruling(vault, proposal.to_dict())
    assert result["ok"] is False and result["why"] == "invalid_proposal"
    assert result["message"]
    assert list(vault.events()) == before


def test_nonidentical_source_label_is_not_fuzzily_discarded(tmp_path):
    vault, movement = _vault(tmp_path)
    proposal = _proposal(vault, movement, _interpret("Harbor Checking maintenance"))
    assert proposal.legs[0]["account"] == "Expenses:Other:Harbor Checking maintenance"
    assert proposal.new_accounts == []


def test_old_invalid_held_registration_is_refused_after_reload(tmp_path, monkeypatch):
    from viva.desktop_bridge.conversation_actions import ConversationActions, _question_stake
    from viva.ledger.events import conversation_proposal_recorded, conversation_turn_opened
    from viva.listen import ruling_slots
    from viva.questions import Question

    vault, movement = _vault(tmp_path)
    question = Question("legacy-nature", "nature", "What was this?", "Unresolved synthetic movement",
        Decimal("12"), currency="USD", slots=ruling_slots(()),
        refs={"movement": movement.key, "descriptor": movement.description})
    proposal = _proposal(vault, movement, _interpret(""))
    proposal.new_accounts = ["Assets:Other:New thing", "Expenses:Other:fee"]
    vault.ledger.append(conversation_turn_opened("old-turn", "answer", question.text,
        "2026-05-03", said="A fee", question_id=question.id))
    vault.ledger.append(conversation_proposal_recorded("old-proposal", "old-turn", question.id,
        proposal.summary(), proposal.to_dict(), _question_stake(question), "2026-05-03"))
    reopened = Vault.open(tmp_path / "vault", "pw")
    before = list(reopened.events())
    monkeypatch.setattr("viva.questions.find_question", lambda *a, **k: question)
    monkeypatch.setattr(engine, "_interpreter", lambda: None)
    outcome = ConversationActions(reopened).confirm({"proposal_id": "old-proposal", "said": "yes"})
    assert outcome["kind"] == "refused" and outcome["reason"] == "invalid_proposal"
    assert "again" in outcome["message"]
    assert all(e.event_type in {"ConversationTurnOpened", "ConversationTurnSettled"}
               for e in list(reopened.events())[len(before):])
    persisted = reopened.ledger.projection().conversation_proposal("old-proposal")
    assert persisted["status"] == "open"
    assert persisted["proposal"] == proposal.to_dict()


def test_recovery_pack_adds_only_the_reviewed_refusal():
    from pathlib import Path
    from viva import persona
    from vivacore import versions

    root = Path(persona.__file__).parent
    old = root / "pack-v47"
    new = root / "pack-v48"
    assert versions.fingerprint(old) == "78b2937f9fc156f1"
    for name in ("phrasings.json", "tone.md"):
        assert (old / name).read_bytes() == (new / name).read_bytes()
    prior = json.loads((old / "moments.json").read_text())
    current = json.loads((new / "moments.json").read_text())
    assert current.pop("reply_invalid_proposal") == (
        "I can't apply this proposal as shown. This attempt made no changes to your financial records. "
        "Please answer the original question again so I can prepare a fresh proposal.")
    assert current == prior
    assert versions.fingerprint(new) == "e77e781b89b0c766"
