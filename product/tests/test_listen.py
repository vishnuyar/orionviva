"""The six-step toolset, sentence to ledger.

The boundary these tests defend is the one the whole project rests on: **the
model reads meaning and nothing else.** It never sees the ledger, never picks an
account, never supplies a figure. Everything downstream of the parse is ordinary
deterministic code, so a model that is wrong, unavailable, or adversarial can
degrade the surface and never the ledger.

The fake `extract_fn` in these tests is deliberate — the pipeline must be fully
testable offline and for free, which is also why the queue keeps working with no
model configured at all.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import (ASSERTED, MAJOR_ASSET, MAJOR_EXPENSE,
                                SCOPE_MERCHANT, SCOPE_MOVEMENT)
from viva.ledger.projection import MIXED, SETTLEMENT, SPENDING, TRANSFER
from viva.listen import (IN_A_SENTENCE, PLAIN, RULING_SLOTS, apply_proposal,
                         listen, propose, resolve_account, ruling_context,
                         ruling_from)
from viva.reply import interpret as fill_slots
from viva.reply import read_reply


def _read(said, descriptor="", extract_fn=None):
    """The inbound path a nature question takes, in the order that matters: the
    model fills the slots the question declared, then the deterministic checks
    decide what survives. Nothing here reads the raw sentence."""
    filled = fill_slots(said, RULING_SLOTS, context=ruling_context(descriptor),
                        extract_fn=extract_fn)
    got = ruling_from(read_reply(RULING_SLOTS, filled.values), said)
    got.raw = filled.raw
    if filled.failure:
        got.failure, got.detail = filled.failure, filled.detail
    return got


def _enrich(ledger, merchant, category="other", kind="business", implies=(),
            subcategory=""):
    """Seed what the WORLD knows about a counterparty.

    Where the account belongs, which document proves it, and whether the
    descriptor even names a business are all learned once at enrichment — not
    read from tables in listen.py. Tests seed that knowledge instead of relying
    on keyword matching, because that is how the product gets it."""
    from viva.ledger.events import merchant_enriched
    ledger.append(merchant_enriched(
        merchant, category, subcategory=subcategory, grade="corroborated",
        occurred_at="2026-04-01", by="model",
        attributes={"counterparty_kind": kind, "implies": list(implies)}))


VEHICLE = [{"relationship": "a vehicle", "major": "asset", "on": "outflow",
            "account_group": "Vehicles", "compound": False,
            "confidence": "suggested", "documents": "invoice or bill of sale",
            "ask": "Shall I track it?"}]
MORTGAGE = [{"relationship": "a home loan", "major": "liability", "on": "outflow",
             "account_group": "Mortgage", "compound": True,
             "confidence": "suggested", "documents": "mortgage statement or 1098",
             "ask": "Shall I set up the loan?"}]


def _reply(payload):
    import json
    return lambda prompt: json.dumps(payload)


def _vault(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _checking(raw, ledger, txns, opening="100000.00"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")

    def read(data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    return capture_and_ingest(raw, ledger, b"chk", read, captured_at="2026-04-01")


# ------------------------------------------------------ the model's boundary


def test_the_model_never_supplies_a_figure(tmp_path):
    """The one place an invented figure could leak in: a model that names an
    amount in its reading. The amount is ignored — the posting uses the
    movement's own value — and the event builder refuses an amount outright, so
    this is closed twice."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    _enrich(ledger, "tesla motors", "transport", implies=VEHICLE)
    proj = ledger.projection()
    p = listen(proj, "i bought a car for ninety thousand dollars", "TESLA MOTORS",
               amount="42000.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Model 3",
                                            "amount": "90000.00"}],
                                  "kind": "vehicle"}))
    assert p.amount == "42000.00"                     # the movement's, not the model's
    assert all("amount" not in leg for leg in p.legs)
    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    assert proj.ruled_accounts()["Assets:Vehicles:Model 3"]["paid"] == Decimal("42000.00")


def test_a_broken_model_degrades_the_surface_never_the_ledger(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    proj = ledger.projection()
    for broken in (lambda p: "I think it's a car!", lambda p: '{"legs": "nope"}',
                   lambda p: '{"legs":[{"major":"equity"}]}'):
        assert listen(proj, "i bought a car", "TESLA MOTORS", extract_fn=broken) is None
    assert ledger.projection().rulings() == []       # nothing written, ever


def test_with_no_model_nothing_is_guessed():
    """With nothing configured to fill the slots, the honest result is no
    reading at all — never a leg assembled out of the sentence by something
    downstream."""
    assert _read("i bought a car", "TESLA").legs == []
    # And nobody is ever shown an accounting term.
    assert not any(m in PLAIN[m].lower() for m in PLAIN)


# ------------------------------------------------------- resolution and scope


def test_resolution_asks_only_when_ambiguous(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    _enrich(ledger, "tesla motors", "transport", implies=VEHICLE)
    proj = ledger.projection()
    assert resolve_account(proj, MAJOR_ASSET, "Model 3").verdict == "new"

    p = listen(proj, "i bought a car", "TESLA MOTORS", currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Model 3"}],
                                  "kind": "vehicle"}))
    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    # Exact match: silence. Near match: ask. Neither invents a second account.
    assert resolve_account(proj, MAJOR_ASSET, "Model 3").verdict == "same"
    assert resolve_account(proj, MAJOR_ASSET, "model  3").verdict == "same"
    near = resolve_account(proj, MAJOR_ASSET, "Model 3 Long Range")
    assert near.verdict == "ambiguous" and near.candidate == "Assets:Vehicles:Model 3"


def test_a_commercial_merchant_generalizes_and_a_person_does_not(tmp_path):
    """One answer settles every payment to a lender. It must NOT do that for a
    friend: one Zelle can be a gift and the next a loan."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-03-31", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-03-14", "ZELLE TO SAM", Decimal("-700.00"))])
    proj = ledger.projection()
    lender = listen(proj, "this is my mortgage", "NEWCO MORTGAGE SERVICING",
                    extract_fn=_reply({"legs": [{"major": "liability",
                                                 "account_hint": "Newco"}],
                                       "kind": "mortgage"}))
    assert lender.scope == SCOPE_MERCHANT and lender.settles == 2

    key = [m for m in proj.movements() if "ZELLE" in m.description][0].key
    friend = listen(proj, "a loan to my brother", "ZELLE TO SAM", movement_key=key,
                    extract_fn=_reply({"legs": [{"major": "asset",
                                                 "account_hint": "Sam"}], "kind": "loan"}))
    assert friend.scope == SCOPE_MOVEMENT and friend.settles == 1


def test_a_proposal_counts_the_payments_it_is_answering_about(tmp_path):
    """One population per sentence.

    The confirmation says an amount and a number of payments in one breath, so
    both must describe one set of movements: the payments to this counterparty
    whose meaning is still open. A refund that came back from it is not a
    payment, and a payment whose nature the person already ruled is not one this
    answer settles. Asserted against the projection's own population rather than
    against a remembered number."""
    from viva.ingest import assign_category
    from viva.questions import MERCHANT, open_questions
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-03-31", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-04-02", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00")),
                            ("2026-04-05", "NEWCO MORTGAGE SERVICING", Decimal("120.00"))])
    ruled = next(m for m in ledger.projection().movements() if m.date == "2026-04-02")
    assign_category(ledger, ruled.key, "housing", nature="settlement", by="human")
    proj = ledger.projection()

    (q,) = [x for x in open_questions(ledger, as_of="2026-05-01")["questions"]
            if x["kind"] == MERCHANT]
    p = listen(proj, "this is my mortgage", "NEWCO MORTGAGE SERVICING",
               amount=q["amount"], currency=q["currency"],
               extract_fn=_reply({"legs": [{"major": "liability",
                                            "account_hint": "Newco"}],
                                  "kind": "mortgage"}))
    assert p.scope == SCOPE_MERCHANT
    # What the question counted is what the confirmation counts back.
    assert p.settles == q["count"] > 1
    assert f"across {q['count']} payments" in p.summary()


def _branded(tmp_path, lines):
    """A vault whose card lines resolve to a brand.

    A card line carries the brand, the store, the city and the posting date, so
    two visits to one restaurant are two descriptors and one counterparty. The
    grammar is what tells them apart, and it is the shape every real vault
    reads under."""
    from merchantcore.profile import Profile, Template
    from viva.ledger import account_opened, simple_transaction
    from viva.ledger.merchant_keys import resolve_keys
    from viva.vault import Vault
    grammar = Profile("northbank", "depository", "v1", [
        Template("CARD PURCHASE {date} {brand} {city} {region} CARD {account_ref}")])
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"),
                    resolve_keys=lambda rows: resolve_keys(
                        rows, profile_for=lambda i, k: grammar))
    ledger.append(account_opened("chk", "depository", "Checking", "USD",
                                 "2026-01-01", institution="northbank"))
    for date, description, amount in lines:
        ledger.append(simple_transaction("chk", amount, description, date))
    return Vault(ledger=ledger, raw=RawStore.open(tmp_path / "raw", "pw"),
                 directory=tmp_path)


BISTRO = "golden fork bistro"
PLANO_JUNE = "CARD PURCHASE 06/12 GOLDEN FORK BISTRO PLANO TX CARD 0000"
AUSTIN_JULY = "CARD PURCHASE 07/03 GOLDEN FORK BISTRO AUSTIN TX CARD 0000"
PLANO_JULY = "CARD PURCHASE 07/19 GOLDEN FORK BISTRO PLANO TX CARD 0000"
THREE_VISITS = [("2026-06-12", PLANO_JUNE, "-42.10"),
                ("2026-07-03", AUSTIN_JULY, "-18.00"),
                ("2026-07-19", PLANO_JULY, "-66.20")]


def _implies_a_membership(vault, grade="corroborated"):
    """What the world knows about the brand: paying it implies a thing you then
    own, and an invoice would prove it."""
    from viva.ledger.events import merchant_enriched
    vault.ledger.append(merchant_enriched(
        BISTRO, "dining", grade=grade, by="model", occurred_at="2026-07-20",
        attributes={"counterparty_kind": "business",
                    "implies": [{"relationship": "a supper club",
                                 "major": "asset", "on": "outflow",
                                 "account_group": "Memberships",
                                 "compound": False, "confidence": "suggested",
                                 "documents": "invoice", "ask": ""}]}))


def _answers(monkeypatch):
    """A reading of the person's sentence. What it returns is untrusted; the
    deterministic checks behind it still decide."""
    import json

    from viva import engine
    monkeypatch.setattr(engine, "_interpreter", lambda: lambda _prompt: json.dumps(
        {"legs": [{"major": "asset", "account_hint": "Supper Club"}]}))


def _nature_questions(vault):
    from viva.questions import NATURE, open_questions
    return [q for q in open_questions(vault.ledger)["questions"]
            if q["kind"] == NATURE]


def test_an_answer_settles_the_payments_its_question_counted(tmp_path, monkeypatch):
    """The number a person is shown and the number their answer settles are one
    number, and the answer reaches every payment it named.

    A question is asked about a counterparty; an answer to it must be about the
    same counterparty. Where a grammar names the brand behind two different card
    lines, re-deriving the identity from one of those lines names something
    narrower than the question did — and a person reads one count, confirms
    another, and the payments outside the narrower name go on being asked
    about."""
    from viva import engine

    vault = _branded(tmp_path, THREE_VISITS)
    _implies_a_membership(vault)
    _answers(monkeypatch)

    (q,) = _nature_questions(vault)
    outcome = engine.answer_question(vault, q["id"], "that's the club membership")
    proposal = outcome["proposal"]
    assert proposal["settles"] == q["count"] > 1
    assert f"across {q['count']} payments" in proposal["summary"]

    applied = engine.apply_ruling(vault, proposal)
    # Filed under the identity the question was asked under, so one answer
    # reaches every payment the question counted and none is left asking.
    assert applied["subject"] == q["refs"]["merchant"]
    assert not _nature_questions(vault)


def test_a_proposal_states_the_payments_it_settles_that_nobody_asked_about(
        tmp_path, monkeypatch):
    """Two true numbers, each over the set it is true of.

    A question is raised only where the counterparty cannot say what the money
    was. Here one of three visits to one restaurant is already explained by an
    answer given before a grammar could name the brand, so the question is over
    two payments — and the ruling, which outranks what a category merely
    implied, will decide all three. The confirmation states both, because the
    sentence before an irreversible write is the wrong place to learn that it
    did more than it said."""
    from decimal import Decimal as D

    from viva import engine
    from viva.ledger import merchant_categorized
    from viva.ledger.events import VERIFIED
    from viva.ledger.projection import BY_RULING
    from viva.render import money

    vault = _branded(tmp_path, THREE_VISITS)
    _implies_a_membership(vault)
    # The person's own older answer about one of the lines, filed under the
    # descriptor because that is the only name the vault had at the time. It
    # explains that visit, so nothing needs to ask about it.
    vault.ledger.append(merchant_categorized(
        "card purchase golden fork bistro austin tx card", "dining", VERIFIED,
        "2026-05-01"))
    _answers(monkeypatch)

    (q,) = _nature_questions(vault)
    asked = set(q["refs"]["movements"])
    rest = [m for m in vault.ledger.projection().movements()
            if m.key not in asked]
    assert len(asked) == q["count"] and rest, "the fixture asks about everything"

    proposal = engine.answer_question(
        vault, q["id"], "that's the club membership")["proposal"]
    summary = proposal["summary"]
    # The set the question was over — its own count, and its own total.
    assert proposal["settles"] == q["count"]
    assert f"across {q['count']} payments" in summary
    assert str(money(q["amount"], q["currency"])) in summary
    # And the set it reaches beyond it, named rather than folded in.
    assert proposal["also_settles"] == len(rest)
    assert D(proposal["also_amount"]) == sum(abs(m.amount) for m in rest)
    assert str(proposal["also_settles"]) in summary
    assert str(money(proposal["also_amount"], q["currency"])) in summary

    # ...and the second sentence was true: applying it does settle them.
    engine.apply_ruling(vault, proposal)
    settled = {m.key for m in vault.ledger.projection().movements()
               if m.nature_reason == BY_RULING}
    assert settled == asked | {m.key for m in rest}


def test_a_new_account_opens_in_the_fallback_group(tmp_path, monkeypatch):
    """What kind of thing an account holds is not a level in its path. Until it
    is a thing known about the account, a counterparty named by a carried key
    opens its accounts in the one fallback group — and the document that would
    prove the account still comes from what the counterparty implies, because
    the question already told the person it would."""
    from viva import engine

    vault = _branded(tmp_path, THREE_VISITS)
    _implies_a_membership(vault)
    _answers(monkeypatch)

    (q,) = _nature_questions(vault)
    proposal = engine.answer_question(
        vault, q["id"], "that's the club membership")["proposal"]
    assert proposal["new_accounts"] == ["Assets:Other:Supper Club"]
    assert proposal["corroborates"] == "invoice"
    assert "invoice" in q["why"], "the question already named the document"


# --------------------------------------------------------------- the proposal


def test_a_proposal_states_what_it_does_not_know(tmp_path):
    """The mortgage: three legs, proportions unknown — and the summary has to
    say so plainly, because a proposal that hid it would be the confident wrong
    answer this project exists to refuse."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00"))])
    _enrich(ledger, "newco mortgage servicing", "housing", implies=MORTGAGE)
    proj = ledger.projection()
    p = listen(proj, "principal, interest and escrow on my house",
               "NEWCO MORTGAGE SERVICING", amount="4400.00", currency="USD",
               extract_fn=_reply({"legs": [
                   {"major": "expense", "account_hint": "Newco interest"},
                   {"major": "liability", "account_hint": "Newco"},
                   {"major": "asset", "account_hint": "Newco escrow"}],
                   "kind": "mortgage"}))
    assert p.unknown_split
    summary = p.summary()
    assert "won't" in summary and "guess" in summary
    assert "mortgage statement or 1098" in summary
    # The document is offered as proof, not demanded as a gate.
    assert "isn't needed" in summary

    applied = apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    m = proj.movements()[0]
    assert m.nature == MIXED and m.provisional
    # The account exists NOW — a missing document never blocked it.
    assert "Liabilities:Mortgage:Newco" in applied["accounts_opened"]
    assert proj.account_info("Liabilities:Mortgage:Newco").origin == ASSERTED
    # ...but its balance is not to be trusted as debt reduction: part was interest.
    assert proj.ruled_accounts()["Liabilities:Mortgage:Newco"]["reliable_balance"] is False


def test_a_proposal_names_each_meaning_once_and_in_the_middle_of_a_sentence(
        tmp_path):
    """What a person reads back before anything is written.

    One payment can be two things at once — and it can be two of the same
    thing, an insurance premium and a repair on one bill, both money spent. The
    summary says what the money became, once per meaning; and it says it as a
    clause, because the four majors' other form is a whole sentence in the
    person's own voice and setting one down inside another sentence reads as a
    fragment."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NORTHGATE SERVICES", Decimal("-900.00"))])
    proj = ledger.projection()
    p = listen(proj, "part was the premium, part was the repair",
               "NORTHGATE SERVICES", amount="900.00", currency="USD",
               extract_fn=_reply({"legs": [
                   {"major": "expense", "account_hint": "premium"},
                   {"major": "expense", "account_hint": "repair"}]}))
    summary = p.summary()
    assert summary.count(IN_A_SENTENCE[MAJOR_EXPENSE]) == 1
    # Not the standalone form, spliced into the middle of another sentence.
    assert PLAIN[MAJOR_EXPENSE].lower() not in summary
    # And neither form ever shows a person an accounting term.
    assert not any(m in IN_A_SENTENCE[m].lower() for m in IN_A_SENTENCE)
    assert set(IN_A_SENTENCE) == set(PLAIN)


def test_a_stated_split_is_kept_and_an_invented_one_is_not(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00"))])
    proj = ledger.projection()
    told = listen(proj, "half interest, half principal", "NEWCO MORTGAGE SERVICING",
                  extract_fn=_reply({"legs": [
                      {"major": "expense", "account_hint": "i", "share": "0.5"},
                      {"major": "liability", "account_hint": "Newco", "share": "0.5"}],
                      "kind": "mortgage"}))
    assert not told.unknown_split
    guessed = listen(proj, "this is my mortgage", "NEWCO MORTGAGE SERVICING",
                     extract_fn=_reply({"legs": [
                         {"major": "expense", "account_hint": "i"},
                         {"major": "liability", "account_hint": "Newco"}],
                         "kind": "mortgage"}))
    assert guessed.unknown_split


def test_applying_is_a_separate_explicit_act(tmp_path):
    """A Proposal is not applied until someone says so."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "ACME LENDING", Decimal("-500.00"))])
    proj = ledger.projection()
    p = listen(proj, "that paid off my car loan", "ACME LENDING", currency="USD",
               extract_fn=_reply({"legs": [{"major": "liability", "account_hint": "Acme"}],
                                  "kind": "loan"}))
    assert ledger.projection().rulings() == []       # proposing wrote nothing
    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    assert len(proj.rulings()) == 1
    assert proj.movements()[0].nature == SETTLEMENT
    assert proj.rulings()[0]["said"] == "that paid off my car loan"


def test_the_corroboration_ask_is_the_path_from_asserted_to_issued(tmp_path):
    """Provenance is the product. A created account names the document that
    would prove it — and that document arriving is what upgrades its origin."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    _enrich(ledger, "tesla motors", "transport", implies=VEHICLE)
    proj = ledger.projection()
    p = listen(proj, "i bought a car", "TESLA MOTORS", currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Model 3"}],
                                  "kind": "vehicle"}))
    # The document comes from what the WORLD knows about this counterparty.
    assert p.corroborates == "invoice or bill of sale"
    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    assert proj.account_info("Assets:Vehicles:Model 3").origin == ASSERTED
    assert proj.movements()[0].nature == TRANSFER


# --------------------------------------------------- the queue and the surface


def test_the_button_path_and_the_sentence_path_write_the_same_events(tmp_path):
    """Free text is an alternative channel, never a second mechanism. A tapped
    answer and a typed one must be indistinguishable in the ledger."""

    def run(said):
        raw, ledger = _vault(tmp_path / said[:4])
        _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
        return ledger

    tapped = run("tap ")
    proj = tapped.projection()
    p = propose(proj, _read(""), "TESLA MOTORS")
    p.legs = [{"major": MAJOR_ASSET, "account": "Assets:Other:TESLA MOTORS", "share": ""}]
    p.new_accounts = ["Assets:Other:TESLA MOTORS"]
    apply_proposal(tapped, p, "2026-07-25")

    typed = run("type")
    q = listen(typed.projection(), "i bought a car", "TESLA MOTORS",
               extract_fn=_reply({"legs": [{"major": "asset",
                                            "account_hint": "TESLA MOTORS"}]}))
    apply_proposal(typed, q, "2026-07-25")

    a = tapped.projection().rulings()[0]
    b = typed.projection().rulings()[0]
    assert a["scope"] == b["scope"] and a["legs"] == b["legs"] and a["grade"] == b["grade"]
    assert b["said"] == "i bought a car" and a["said"] == ""   # only the words differ


def test_an_asserted_account_asks_for_the_document_that_would_prove_it(tmp_path):
    """The ask is ranked with everything else and is never a gate — the account
    and the money are already recorded before it is raised."""
    from viva.questions import CORROBORATION, open_questions

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    _enrich(ledger, "tesla motors", "transport", implies=VEHICLE)
    p = listen(ledger.projection(), "i bought a car", "TESLA MOTORS",
               currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Model 3"}],
                                  "kind": "vehicle"}))
    apply_proposal(ledger, p, "2026-07-25")

    asks = [q for q in open_questions(ledger)["questions"] if q["kind"] == CORROBORATION]
    assert len(asks) == 1
    assert "invoice or bill of sale" in asks[0]["text"]
    assert "prove" in asks[0]["text"]
    assert asks[0]["refs"]["account"] == "Assets:Vehicles:Model 3"
    # An issued account never generates one — only what you asserted does.
    assert all("chase" not in q["refs"].get("account", "").lower() for q in asks)


def test_a_ruling_retires_the_question_that_prompted_it(tmp_path):
    """Idempotent by construction: state changed, so the queue stops asking."""
    from viva.questions import NATURE, open_questions

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-06", "BIG MOTORS", Decimal("-30000.00"))])
    _enrich(ledger, "big motors", "transport", implies=VEHICLE)
    assert [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]

    p = listen(ledger.projection(), "i bought a car", "BIG MOTORS", currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Truck"}],
                                  "kind": "vehicle"}))
    apply_proposal(ledger, p, "2026-07-25")
    assert not [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]


def test_the_interpreter_is_configured_separately_and_can_be_local(monkeypatch):
    """Reading a statement is a hard vision task; reading a sentence is a tiny
    text task. One setting for both would overpay on every sentence or under-read
    every statement — and a local model is only reachable if it can be keyless."""
    from viva import engine

    for var in ("VIVA_MODEL", "VIVA_MODEL_ADAPTER", "VIVA_MODEL_BASE_URL",
                "VIVA_MODEL_KEY_ENV", "VIVA_INTERPRET_MODEL",
                "VIVA_INTERPRET_BASE_URL", "VIVA_INTERPRET_KEY_ENV"):
        monkeypatch.delenv(var, raising=False)
    assert engine._interpreter() is None      # nothing configured: no reader

    # A local, keyless server must build a spec without demanding an API key.
    monkeypatch.setenv("VIVA_INTERPRET_MODEL", "qwen3.6:4b")
    monkeypatch.setenv("VIVA_INTERPRET_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("VIVA_INTERPRET_KEY_ENV", "none")
    assert engine._interpreter() is not None        # would raise if a key were required


# ------------------------------------------------- reading the model's reply


def test_json_is_found_inside_whatever_the_model_wraps_it_in():
    """Models fence their output, think out loud first, or add a cheerful
    sentence after — none of which is a failure of understanding, so requiring
    the WHOLE reply to be JSON throws away a perfectly good reading."""
    from viva.reply import _first_json_object

    obj = {"legs": [{"major": "liability"}]}
    for wrapper in (
        '```json\n{"legs":[{"major":"liability"}]}\n```',
        'Let me think about this.\n{"legs":[{"major":"liability"}]}\nHope that helps!',
        '<think>the user said mortgage</think>{"legs":[{"major":"liability"}]}',
        '{"legs":[{"major":"liability"}]}',
    ):
        assert _first_json_object(wrapper) == obj, wrapper[:30]

    assert _first_json_object("no json here at all") is None
    # A brace inside a string must not be mistaken for structure.
    assert _first_json_object('{"a": "} not really"}') == {"a": "} not really"}


def test_a_truncated_reply_is_refused_not_half_read():
    """The important half of the leniency. A cut-off reading is not a partial
    reading, it is an UNKNOWN one — guessing the rest is how a wrong ruling gets
    written and then generalized."""
    from viva.reply import _first_json_object

    cut = '{"legs": [{"major": "expense", "account_hint": "Newco inter'
    assert _first_json_object(cut) is None

    got = _read("this is my mortgage", "LENDER", extract_fn=lambda p: cut)
    assert got.legs == []
    assert got.failure == "unparseable"
    assert got.raw == cut                  # kept, so it can be diagnosed offline


def test_interpretation_is_never_continued_across_truncation():
    """Continuation is the right repair for a long transaction list and the
    WRONG one here — the answer is ~60 tokens, so hitting the limit means the
    model is rambling, and stitching six more chunks onto a runaway reply turns
    one cheap failure into garbage at 7x the cost."""
    from dataclasses import replace as _replace

    from viva.listen import one_shot_extractor

    seen = {}

    class FakeAdapter:
        def __init__(self, spec):
            seen["max_continuations"] = spec.max_continuations

        def extract(self, pages, prompt):
            class R:
                text = '{"legs":[{"major":"expense"}]}'
                finish_reason = "length"
                output_tokens = 1024
            return R()

    import vivacore.models as models
    real = models.adapter_for
    models.adapter_for = FakeAdapter
    try:
        from vivacore.models import ModelSpec
        spec = ModelSpec(name="t", adapter="openai-compatible", model="m",
                         base_url="http://x/v1", api_key_env=None)
        assert spec.max_continuations is None          # the document-reading default
        out = one_shot_extractor(spec)("prompt")
        assert seen["max_continuations"] == 0          # ...overridden to one shot
        # Truncation is marked, not stitched: the caller reports it as its own
        # failure rather than guessing at the missing tail.
        from viva.listen import TRUNCATED_MARK
        assert out == TRUNCATED_MARK + '{"legs":[{"major":"expense"}]}'
    finally:
        models.adapter_for = real


# ------------------------------------------------------- the ATM answer


def _atm(tmp_path):
    """An ATM descriptor carrying its own date, place and card.

    Two withdrawals sharing a descriptor — which is a CONDUIT, so each is
    answered separately. The tests pass a movement key for exactly that reason."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [
        ("2026-03-29", "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
         Decimal("-500.00")),
        ("2026-03-29", "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
         Decimal("-500.00"))])
    _enrich(ledger, "atm withdrawal 03 29 example rd anytown card", "transfers",
            kind="instrument", subcategory="atm")
    return ledger


def test_the_label_a_person_names_is_not_dropped(tmp_path):
    """Answering "spent on playing poker, add it to poker category" records the
    category as well as the major. Half a sentence reaching the ledger with
    nothing said about it is the worst kind of silence, because it looks like it
    worked."""
    ledger = _atm(tmp_path)
    key = ledger.projection().movements()[0].key
    p = listen(ledger.projection(), "spent on playing poker, add it to poker category",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               movement_key=key, amount="500.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "expense", "account_hint": ""}],
                                  "category": "poker"}))
    assert p.category == "poker"
    assert "poker" in p.summary()

    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    assert proj.movements()[0].nature == SPENDING
    # Both halves landed, through the writers that already existed.
    assert (proj.derived_category(proj.movements()[0]) or {}).get("category") == "poker"


def test_the_document_line_is_never_the_models_free_text(tmp_path):
    """Code maps kind -> document; the model has no say. An unguided
    "corroborates" field puts the model's free text in front of a person, and
    nonsense reaching a person is a trust failure even when the ledger is
    fine."""
    ledger = _atm(tmp_path)
    key = ledger.projection().movements()[0].key
    p = listen(ledger.projection(), "spent on playing poker",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               movement_key=key, amount="500.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "expense"}],
                                  "corroborates": "no", "kind": ""}))
    assert p.corroborates == ""                  # an instrument proves nothing
    assert "prove" not in p.summary()
    assert "no would" not in p.summary()

    # And where a document genuinely applies, it is OUR wording, not the model's.
    _enrich(ledger, "northside motors", "transport", implies=VEHICLE)
    car = listen(ledger.projection(), "i bought a car", "NORTHSIDE MOTORS",
                 extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Truck"}],
                                    "kind": "vehicle", "corroborates": "whatever"}))
    assert car.corroborates == "invoice or bill of sale"


def test_ordinary_spending_creates_no_account(tmp_path):
    """Not every answer brings a thing into being. Cash spent on an evening out
    is an expense, not an asset with a name — and an account per answer is how
    account sprawl would actually start."""
    ledger = _atm(tmp_path)
    key = ledger.projection().movements()[0].key
    p = listen(ledger.projection(), "spent on playing poker",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               movement_key=key, amount="500.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "expense", "account_hint": ""}],
                                  "category": "poker"}))
    applied = apply_proposal(ledger, p, "2026-07-25")
    assert applied["accounts_opened"] == []
    assert ledger.projection().ruled_accounts() == {}


def test_a_nested_reply_is_still_read(tmp_path):
    """Some providers and json_mode wrappers nest the answer —
    {"response": {"legs": [...]}} — so taking the OUTER object finds no legs.
    Search for the object that carries them, not merely the first one."""
    from viva.reply import _first_json_object

    inner = {"legs": [{"major": "liability", "account_hint": "Lender"}],
             "kind": "mortgage"}
    for wrapper in (
        '{"response": {"legs":[{"major":"liability","account_hint":"Lender"}],'
        '"kind":"mortgage"}}',
        '{"result": {"data": {"legs":[{"major":"liability","account_hint":"Lender"}],'
        '"kind":"mortgage"}}}',
        'here you go: {"legs":[{"major":"liability","account_hint":"Lender"}],'
        '"kind":"mortgage"}',
    ):
        assert _first_json_object(wrapper, require_key="legs") == inner, wrapper[:40]

    # A leading object WITHOUT legs must not win over a later one that has them.
    two = '{"note":"thinking"} {"legs":[{"major":"expense"}]}'
    assert _first_json_object(two, require_key="legs") == {"legs": [{"major": "expense"}]}


def test_each_failure_says_something_different_and_true(tmp_path):
    """A model that is DOWN, one that is rambling, and one that simply didn't
    understand each need their own sentence — with one sentence for all of them
    neither the person nor the log can tell them apart. Saying which is the
    difference between a product that admits a limit and one that just seems
    broken."""
    from viva.reply import answer

    cases = {
        "unreachable": lambda p: (_ for _ in ()).throw(ConnectionError("down")),
        "unparseable": lambda p: "sure, it's a mortgage!",
        # Well-formed, and filling nothing: the reader answered, and what it
        # returned does not settle the question.
        "unanswered": lambda p: '{"legs": []}',
    }
    seen = set()
    for expected, fn in cases.items():
        out = answer("mortgage payments", RULING_SLOTS,
                     context=ruling_context("LENDER ACH PMT"), extract_fn=fn)
        assert out.ok is False
        assert out.why == expected
        seen.add(out.message)
    assert len(seen) == 3, "each failure needs its own honest sentence"


def test_a_conduit_is_answered_one_transaction_at_a_time(tmp_path):
    """Every check in a vault normalizes to the single token "check". Grouping
    them as a merchant would allow one answer for all of them, when one check
    may be an earnest-money deposit and the next an initial deposit to open an
    account. A check says HOW the money moved, not who got it."""
    from viva.ledger.merchants import normalize_merchant
    from viva.questions import NATURE, open_questions

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "Check # 1201", Decimal("-20000.00")),
                            ("2026-03-11", "Check # 1202", Decimal("-500.00"))])
    # Enrichment is what tells us "check" names an instrument, not a business.
    _enrich(ledger, "check", "other", kind="instrument")

    assert normalize_merchant("Check # 1201") == normalize_merchant("Check # 1202")

    qs = [q for q in open_questions(ledger)["questions"] if q["kind"] == NATURE]
    assert len(qs) == 2, "one question per check, not one for the bucket"
    assert all(q["scope"] == "one" and q["count"] == 1 for q in qs)
    assert all(q["refs"]["movement"] for q in qs)
    assert "not who received it" in qs[0]["why"]
    # Ranked by consequence, so the earnest money surfaces above the small one.
    assert Decimal(qs[0]["amount"]) > Decimal(qs[1]["amount"])

    # Two different answers, each landing on its own transaction.
    proj = ledger.projection()
    big = [m for m in proj.movements() if m.amount == Decimal("-20000.00")][0]
    small = [m for m in proj.movements() if m.amount == Decimal("-500.00")][0]
    earnest = listen(proj, "earnest money that went to the house down payment",
                     big.description, movement_key=big.key, currency="USD",
                     extract_fn=_reply({"legs": [{"major": "asset",
                                                  "account_hint": "House"}],
                                        "kind": "property"}))
    apply_proposal(ledger, earnest, "2026-07-25")
    proj = ledger.projection()
    opening = listen(proj, "initial deposit to open a new bank account",
                     small.description, movement_key=small.key, currency="USD",
                     extract_fn=_reply({"legs": [{"major": "asset",
                                                  "account_hint": "New account"}]}))
    apply_proposal(ledger, opening, "2026-07-25")

    proj = ledger.projection()
    by_amount = {m.amount: m.ruling_account for m in proj.movements()}
    # An instrument implies nothing, so the account is named from the person's
    # own words and lands in the dull fallback group. That is correct: we know
    # nothing about a check beyond what they just told us.
    assert by_amount[Decimal("-20000.00")] == "Assets:Other:House"
    assert by_amount[Decimal("-500.00")] == "Assets:Other:New account"
    assert sum(proj.spending_by_category("USD").values()) == Decimal("0")


def test_a_conduit_answer_refuses_to_settle_the_whole_bucket(tmp_path):
    """The guard behind it: asked to rule on a conduit without naming which
    transaction, refuse loudly rather than quietly settle them all."""
    import pytest

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "Check # 1201", Decimal("-20000.00")),
                            ("2026-03-11", "Check # 1202", Decimal("-500.00"))])
    _enrich(ledger, "check", "other", kind="instrument")
    with pytest.raises(ValueError, match="needs a specific transaction"):
        listen(ledger.projection(), "earnest money", "Check # 1201",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "House"}]}))


def test_running_past_the_token_limit_is_its_own_failure(tmp_path):
    """"Couldn't make sense of it" and "ran on and never finished" have
    different causes and different fixes — a clearer sentence versus a less
    chatty model. Telling a person the first when it was the second sends them
    to rewrite a sentence that was never the problem."""
    from viva.listen import TRUNCATED_MARK

    got = _read("mortgage payments", "LENDER",
                extract_fn=lambda p: TRUNCATED_MARK +
                '{"legs": [{"major": "liabil')
    assert got.failure == "too_long"
    assert got.legs == []
    assert "token limit" in got.detail
    assert got.raw.startswith("{")          # the partial reply is kept, unmarked

    # A truncated reply that nonetheless CONTAINS a complete object is fine —
    # the model rambled after answering, which costs tokens, not correctness.
    ok = _read("mortgage payments", "LENDER",
               extract_fn=lambda p: TRUNCATED_MARK +
               '{"legs":[{"major":"liability"}]} and furthermore I should')
    assert ok.legs and ok.failure == ""
