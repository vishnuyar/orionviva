"""Slice 9a — the six-step toolset, sentence to ledger.

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
                                MAJOR_LIABILITY, SCOPE_MERCHANT, SCOPE_MOVEMENT)
from viva.ledger.projection import MIXED, SETTLEMENT, SPENDING, TRANSFER
from viva.listen import (PLAIN, apply_proposal, interpret, listen, propose,
                         resolve_account, suggest_answers)


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
    """The one place T2 could leak: a model that names an amount in its reading.
    The amount is ignored — the posting uses the movement's own value — and the
    event builder refuses an amount outright, so this is closed twice."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
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


def test_with_no_model_the_buttons_still_work():
    """Free text is an addition, never a dependency."""
    assert interpret("i bought a car", "TESLA").legs == []
    majors = [s["major"] for s in suggest_answers("loan_payments", "mortgage")]
    assert majors[0] == MAJOR_LIABILITY
    assert all(s["label"] == PLAIN[s["major"]] for s in suggest_answers())
    # And nobody is ever shown an accounting term (D1).
    assert not any(m in PLAIN[m].lower() for m in PLAIN)


# ------------------------------------------------------- resolution and scope


def test_resolution_asks_only_when_ambiguous(tmp_path):
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
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


# ---------------------------------------------------------- the proposal (X2)


def test_a_proposal_states_what_it_does_not_know(tmp_path):
    """X2. The mortgage: three legs, proportions unknown — and the summary has
    to say so plainly, because a proposal that hid it would be the confident
    wrong answer this project exists to refuse."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "NEWCO MORTGAGE SERVICING", Decimal("-4400.00"))])
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
    """X3, structurally: a Proposal is not applied until someone says so."""
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
    assert proj.rulings()[0]["said"] == "that paid off my car loan"   # T3


def test_the_corroboration_ask_is_the_path_from_asserted_to_issued(tmp_path):
    """Provenance is the product. A created account names the document that
    would prove it — and that document arriving is what upgrades its origin."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
    proj = ledger.projection()
    p = listen(proj, "i bought a car", "TESLA MOTORS", currency="USD",
               extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Model 3"}],
                                  "kind": "vehicle"}))
    assert p.corroborates == "invoice or bill of sale"
    apply_proposal(ledger, p, "2026-07-25")
    proj = ledger.projection()
    assert proj.account_info("Assets:Vehicles:Model 3").origin == ASSERTED
    assert proj.movements()[0].nature == TRANSFER


# --------------------------------------------------- the queue and the surface


def test_the_button_path_and_the_sentence_path_write_the_same_events(tmp_path):
    """Free text is an alternative channel, never a second mechanism. A tapped
    answer and a typed one must be indistinguishable in the ledger."""
    from viva.web import service

    def run(said):
        raw, ledger = _vault(tmp_path / said[:4])
        _checking(raw, ledger, [("2026-03-04", "TESLA MOTORS", Decimal("-42000.00"))])
        return ledger

    tapped = run("tap ")
    proj = tapped.projection()
    p = propose(proj, interpret("", extract_fn=None), "TESLA MOTORS")
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
    from viva.ingest import assign_merchant_category
    from viva.questions import NATURE, open_questions

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-06", "BIG MOTORS", Decimal("-30000.00"))])
    assign_merchant_category(ledger, "big motors", "transport", by="model")
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
    from viva.web import service

    for var in ("VIVA_MODEL", "VIVA_MODEL_ADAPTER", "VIVA_MODEL_BASE_URL",
                "VIVA_MODEL_KEY_ENV", "VIVA_INTERPRET_MODEL",
                "VIVA_INTERPRET_BASE_URL", "VIVA_INTERPRET_KEY_ENV"):
        monkeypatch.delenv(var, raising=False)
    assert service._interpreter() is None            # nothing configured: buttons only

    # A local, keyless server must build a spec without demanding an API key.
    monkeypatch.setenv("VIVA_INTERPRET_MODEL", "qwen3.6:4b")
    monkeypatch.setenv("VIVA_INTERPRET_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("VIVA_INTERPRET_KEY_ENV", "none")
    assert service._interpreter() is not None        # would raise if a key were required


# ------------------------------- reading a real model's reply (the second run)


def test_json_is_found_inside_whatever_the_model_wraps_it_in():
    """Requiring the WHOLE reply to be JSON was too brittle. Models fence their
    output, think out loud first, or add a cheerful sentence after — none of
    which is a failure of understanding, and all of which threw away a perfectly
    good reading."""
    from viva.listen import _first_json_object

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
    from viva.listen import _first_json_object

    cut = '{"legs": [{"major": "expense", "account_hint": "Newco inter'
    assert _first_json_object(cut) is None

    got = interpret("this is my mortgage", "LENDER", extract_fn=lambda p: cut)
    assert got.legs == []
    assert got.failure == "unparseable"
    assert got.raw == cut                  # kept, so it can be diagnosed offline


def test_interpretation_is_never_continued_across_truncation():
    """The bug the first live run produced: seven HTTP calls, then a stitched
    reply that wasn't valid JSON. Continuation is the right repair for a long
    transaction list and the WRONG one here — the answer is ~60 tokens, so
    hitting the limit means the model is rambling, and stitching six more chunks
    onto a runaway reply turns one cheap failure into garbage at 7x the cost."""
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
        assert out == '{"legs":[{"major":"expense"}]}'
    finally:
        models.adapter_for = real


# ------------------------------- the ATM answer (a real run, 2026-07-25)


def _atm(tmp_path):
    """The real shape: an ATM descriptor carrying its own date, place and card."""
    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [
        ("2026-03-29", "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
         Decimal("-500.00")),
        ("2026-03-29", "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
         Decimal("-500.00"))])
    return ledger


def test_the_label_a_person_names_is_not_dropped(tmp_path):
    """The defect: answering "spent on playing poker, add it to poker category"
    recorded only the major. Half the sentence reached the ledger and nothing
    said so — the worst kind of silence, because it looks like it worked."""
    ledger = _atm(tmp_path)
    p = listen(ledger.projection(), "spent on playing poker, add it to poker category",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               amount="1000.00", currency="USD",
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
    """v1 asked for "corroborates" with no guidance; a model answered "no", and
    the surface said "Your no would let me prove this — it isn't needed to save
    it." Nonsense reaching a person is a trust failure even when the ledger is
    fine. Code maps kind -> document now; the model has no say."""
    ledger = _atm(tmp_path)
    p = listen(ledger.projection(), "spent on playing poker",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               amount="1000.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "expense"}],
                                  "corroborates": "no", "kind": ""}))
    assert p.corroborates == ""
    assert "prove" not in p.summary()
    assert "no would" not in p.summary()

    # And where a document genuinely applies, it is OUR wording, not the model's.
    car = listen(ledger.projection(), "i bought a car", "NORTHSIDE MOTORS",
                 extract_fn=_reply({"legs": [{"major": "asset", "account_hint": "Truck"}],
                                    "kind": "vehicle", "corroborates": "whatever"}))
    assert car.corroborates == "invoice or bill of sale"


def test_ordinary_spending_creates_no_account(tmp_path):
    """Not every answer brings a thing into being. Cash spent on an evening out
    is an expense, not an asset with a name — and an account per answer is how
    the sprawl this slice worries about would actually start."""
    ledger = _atm(tmp_path)
    p = listen(ledger.projection(), "spent on playing poker",
               "ATM Withdrawal 03/29 100 Example Rd Anytown Card 0000",
               amount="1000.00", currency="USD",
               extract_fn=_reply({"legs": [{"major": "expense", "account_hint": ""}],
                                  "category": "poker"}))
    applied = apply_proposal(ledger, p, "2026-07-25")
    assert applied["accounts_opened"] == []
    assert ledger.projection().ruled_accounts() == {}


def test_a_nested_reply_is_still_read(tmp_path):
    """"mortgage payments" came back "I couldn't read that one". Some providers
    and json_mode wrappers nest the answer — {"response": {"legs": [...]}} — and
    taking the OUTER object found no legs. Search for the object that carries
    them, not merely the first one."""
    from viva.listen import _first_json_object

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
    """One sentence for four failures meant neither the person nor the log could
    tell a model that was DOWN from one that was rambling from one that simply
    didn't understand. Saying which is the difference between a product that
    admits a limit and one that just seems broken."""
    from viva.web import service

    raw, ledger = _vault(tmp_path)
    _checking(raw, ledger, [("2026-03-01", "LENDER ACH PMT", Decimal("-4400.00"))])

    class FakeVault:
        pass
    v = FakeVault()
    v.ledger = ledger

    cases = {
        "unreachable": lambda p: (_ for _ in ()).throw(ConnectionError("down")),
        "unparseable": lambda p: "sure, it's a mortgage!",
        "empty": lambda p: '{"legs": []}',
    }
    seen = set()
    for expected, fn in cases.items():
        service._interpreter = lambda _fn=fn: _fn
        out = service.listen_to(v, "mortgage payments", "LENDER ACH PMT")
        assert out["understood"] is False
        assert out["why"] == expected
        seen.add(out["message"])
    assert len(seen) == 3, "each failure needs its own honest sentence"
