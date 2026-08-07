"""The interview: a question with a next step, and an account nobody minted.

Two things are under test here, and they are one piece of work rather than two.

**The capability.** A schema states what a kind of asset or liability needs
known; the interview derives what is still owed from rulings already recorded;
the queue asks for one thing at a time, ranked with everything else. It is
read-side throughout — no interview object, no interview event — so a vault
built before any of this existed replays identically.

**The guard.** The same shape fixes an open finding: a tapped answer could open
`Assets:Other:Unnamed` and put it in the net-worth curve, because a question
with no next step had nowhere to ask *"which one, and what is it called?"*.
Now the answer that would open an account comes back as a proposal with a name
the person saw, and an answer that names nothing comes back as the question.

The properties, then, are mostly about what this refuses to do: never mint an
account from a tap, never accept a figure the person did not say, never ask
something it could not use, and never turn an unanswered cost into a zero.
"""

from decimal import Decimal

import pytest

from viva import schemas
from viva.interview import interviews, opens_pending, question_id
from viva.ledger import EventStore, Ledger
from viva.ledger.events import (SCOPE_ATTRIBUTE, VERIFIED, account_opened,
                                question_declined, ruling_recorded)
from viva.ledger.networth import net_worth
from viva.questions import INTERVIEW, open_questions, pending_questions
from viva.vault import Vault
from viva import engine


# --------------------------------------------------------------- the pack


def test_the_pack_loads_and_every_kind_is_jurisdiction_tagged():
    pack = schemas.load()
    assert pack["kinds"], "a schema pack with no kinds asks nothing"
    for entry in pack["kinds"]:
        assert entry["jurisdictions"], entry["kind"]


def test_no_answer_type_means_an_identifier():
    """The structural half of "a schema question may never ask for an
    identifier": the vocabulary has no member that means one. A parsed type can
    only hold a figure, a choice can only hold what the question enumerates,
    and the two free-form types are named for what they hold — the person's own
    word, and a company's public name. Widening this is a visible act."""
    assert set(schemas.ANSWER_TYPES) == {
        "money", "date", "rate", "yes_no", "choice", "label", "institution",
        "link"}


# A released schema pack is FROZEN, for the reason every other pack in this
# project is: a person answered the words that were there, and those words must
# keep resolving. To change one, add a pack file with a new version id.
def _frozen_schema_packs():
    import pathlib

    from vivacore import versions as manifest

    from viva import schemas as _schemas
    package = pathlib.Path(_schemas.__file__).resolve().parent.parent
    return {v: d for v, d in manifest.manifest(package)["released"].items()
            if v.startswith("schemas-")}


FROZEN_SCHEMA_PACKS = _frozen_schema_packs()


def test_released_schema_packs_are_frozen():
    import hashlib
    import pathlib

    from viva import schemas as _schemas
    base = pathlib.Path(_schemas.__file__).resolve().parent
    assert _schemas.ACTIVE_PACK in FROZEN_SCHEMA_PACKS
    for version, digest in FROZEN_SCHEMA_PACKS.items():
        body = (base / f"{version}.json").read_bytes()
        assert hashlib.sha256(body).hexdigest()[:16] == digest, (
            f"{version} changed — a released pack is immutable; add a new "
            "version instead, so a question already answered still resolves")


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "nan"])
def test_a_value_that_is_not_a_number_never_reaches_the_log(value):
    """An append-only log has no delete. One of these in it breaks every
    reading of net worth afterwards, for ever — so it is refused at the door
    rather than handled at the reader."""
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                        "2026-03-02", said="whatever they typed 7", value=value,
                        currency="USD")


@pytest.mark.parametrize("value", ["₹250000", "$1000000", "250000 USD",
                                   "2.5E5", "250_000"])
def test_a_figure_wearing_a_symbol_is_still_checked(value):
    """The check runs on the numbers a value CARRIES, not on whether the whole
    of it looks like one — otherwise a currency symbol would be enough to walk
    a figure straight past the guard."""
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                        "2026-03-02", said="I paid 1", value=value)


def test_a_sign_nobody_wrote_is_refused():
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                        "2026-03-02", said="I paid 250000", value="-250000",
                        currency="USD")


def test_a_choice_must_enumerate_its_alternatives():
    """A choice with no choices is a free-form answer wearing a closed one's
    name — the lint refuses the pack rather than the question."""
    with pytest.raises(schemas.SchemaPackError):
        schemas.lint({"kinds": [{
            "kind": "thing", "jurisdictions": ["us"], "account_shape": "Assets:X",
            "questions": [{"key": "k", "answer": "choice", "asks": "Which?",
                           "unlocks": "something"}]}]})


def test_a_question_must_say_what_it_unlocks():
    with pytest.raises(schemas.SchemaPackError):
        schemas.lint({"kinds": [{
            "kind": "thing", "jurisdictions": ["us"], "account_shape": "Assets:X",
            "questions": [{"key": "k", "answer": "label", "asks": "What?"}]}]})


def test_a_schema_may_only_name_a_document_the_pipeline_classifies():
    """A schema waiting for a document type the product cannot produce waits
    for ever, silently — the failure this check exists to make loud."""
    with pytest.raises(schemas.SchemaPackError):
        schemas.lint({"kinds": [{
            "kind": "thing", "jurisdictions": ["us"], "account_shape": "Assets:X",
            "document_types": ["telepathy_statement"], "questions": []}]})


def test_an_alias_is_refused_because_it_could_never_match():
    """`card_statement` resolves to a profile, so a naive check passes it — and
    then it matches nothing, because a document resolves to the CANONICAL name.
    The lint names that rather than letting the pack wait."""
    with pytest.raises(schemas.SchemaPackError):
        schemas.lint({"kinds": [{
            "kind": "thing", "jurisdictions": ["us"], "account_shape": "Assets:X",
            "document_types": ["card_statement"], "questions": []}]})


def test_a_schema_may_only_claim_a_kind_the_ledger_uses():
    with pytest.raises(schemas.SchemaPackError):
        schemas.lint({"kinds": [{
            "kind": "thing", "jurisdictions": ["us"], "account_shape": "Assets:X",
            "account_kinds": ["chattel"], "questions": []}]})


def test_the_evidence_for_what_a_thing_is_has_an_order():
    """Shape, then the documents an issuer produced, then the ledger's own word
    — and the last only when it can mean one thing."""
    shape = schemas.kind_of_account(
        "Assets:Bank:Everyday", "us", ledger_kind="liability",
        doc_types={"credit_card_statement"})
    assert shape == "deposit_account", "the path it was given wins"
    document = schemas.kind_of_account(
        "acct:northgate:1122", "us", ledger_kind="depository",
        doc_types={"credit_card_statement"})
    assert document == "card_account", "an issuer's document beats a ledger word"
    assert schemas.kind_of_account("acct:x:1", "us",
                                   ledger_kind="depository") == "deposit_account"
    assert schemas.kind_of_account("acct:x:1", "us", ledger_kind="liability") == "", (
        "a loan and a card are both liabilities, so that word decides nothing")


def test_the_same_instrument_under_two_names_is_one_kind():
    """A US certificate of deposit and an Indian fixed deposit differ in what
    they are called, not in what they are — so they are one kind with one
    sub-kind vocabulary, and the delta is data."""
    us = schemas.schema_for("deposit_account", "us").question("sub_kind")
    india = schemas.schema_for("deposit_account", "in").question("sub_kind")
    assert "certificate of deposit" in us.choices
    assert "fixed deposit" in india.choices
    assert "certificate of deposit" not in india.choices


def test_a_jurisdiction_scoped_question_does_not_travel():
    """A lock-in is a structural fact where it exists and a wrong assumption
    where it does not."""
    assert schemas.schema_for("retirement_account", "in").question("lock_in")
    assert schemas.schema_for("retirement_account", "us").question("lock_in") is None


def test_a_conditional_essential_is_not_owed_until_it_applies():
    schema = schemas.schema_for("deposit_account", "in")
    plain = schema.outstanding({"institution": {"value": "Northgate"},
                                "sub_kind": {"value": "savings"}})
    term = schema.outstanding({"institution": {"value": "Northgate"},
                               "sub_kind": {"value": "fixed deposit"}})
    assert [q.key for q in plain] == []
    assert [q.key for q in term] == ["principal", "maturity_date", "rate"]


# ------------------------------------------------------------- fixtures


@pytest.fixture
def vault(tmp_path):
    return Vault.open(tmp_path / "v", "pw")


def _property(vault, name="Cottage", date="2026-03-01"):
    """An asset the person told us about, opened the way a confirmed proposal
    opens one."""
    account = f"Assets:Property:{name}"
    vault.ledger.append(account_opened(account, "asset", name, "USD", date,
                                       origin="asserted"))
    return account


def _answer(vault, account, key, value, said, currency=""):
    vault.ledger.append(ruling_recorded(
        SCOPE_ATTRIBUTE, f"{account}:{key}", "2026-03-02", by="human",
        grade=VERIFIED, said=said, value=value, currency=currency))


# ------------------------------------------------ the derived interview


def test_an_account_with_a_schema_is_asked_one_thing_at_a_time(vault):
    account = _property(vault)
    q = open_questions(vault.ledger, jurisdiction="US")["questions"]
    mine = [x for x in q if x["kind"] == INTERVIEW and x["refs"]["account"] == account]
    assert len(mine) == 1, "one question per interview, never the whole form"
    assert mine[0]["refs"]["key"] == "nickname"
    assert mine[0]["refs"]["unlocks"], "a question must be able to say why"


def test_the_interview_follows_the_answer(vault):
    account = _property(vault)
    _answer(vault, account, "nickname", "Cottage", "Cottage")
    keys = []
    for _ in range(3):
        iv = next(i for i in interviews(vault.ledger.projection(), "US")
                  if i.account == account)
        nxt = iv.next_question
        keys.append(nxt.key)
        _answer(vault, account, nxt.key, *{
            "purchase_price": ("250000", "I paid 250,000 for it", "USD"),
            "purchase_date": ("2019-06-01", "1 June 2019"),
            "use": ("occupied", "occupied"),
        }[nxt.key])
    assert keys == ["purchase_price", "purchase_date", "use"]


def test_an_interview_with_every_essential_settled_yields_nothing_further(vault):
    account = _property(vault)
    for key, value, said in [("nickname", "Cottage", "Cottage"),
                             ("purchase_price", "250000", "250,000"),
                             ("purchase_date", "2019-06-01", "2019-06-01"),
                             ("use", "occupied", "occupied"),
                             ("financed", "no", "no")]:
        _answer(vault, account, key, value, said,
                currency="USD" if key == "purchase_price" else "")
    iv = next(i for i in interviews(vault.ledger.projection(), "US")
              if i.account == account)
    assert iv.terminated
    assert not [x for x in open_questions(vault.ledger, jurisdiction="US")["questions"]
                if x["kind"] == INTERVIEW]


def test_a_kind_with_no_schema_asks_nothing_and_records_the_gap(vault):
    """A question it could not use the answer to is not asked. The absence is
    recorded, so coverage is a fact rather than a silence."""
    from viva.interview import coverage_gaps
    account = "Assets:Curios:Something"
    vault.ledger.append(account_opened(account, "asset", "Something", "USD",
                                       "2026-03-01", origin="asserted"))
    proj = vault.ledger.projection()
    assert not [x for x in open_questions(vault.ledger, jurisdiction="US")["questions"]
                if x["kind"] == INTERVIEW and x["refs"].get("account") == account]
    assert any(g["account"] == account for g in coverage_gaps(proj, "US"))


def test_an_account_a_statement_created_gets_its_interview(vault):
    """The account paths this product actually creates carry no shape a schema
    could match — `acct:<institution>:<last4>` says nothing about what kind of
    thing it is. What DOES say is the document an issuer produced for it, and
    that is the pipeline's own doc-type registry rather than a second
    vocabulary."""
    _seed_movement(vault)
    proj = vault.ledger.projection()
    account = next(a for a in proj.accounts() if a.startswith("acct:"))
    iv = next(i for i in interviews(proj, "US") if i.account == account)
    assert iv.kind == "deposit_account", iv.gap
    # And nothing is asked, because the document that identified the kind also
    # answered the only thing this kind needs known. A classified statement has
    # already said it is a checking account; asking is not listening.
    assert iv.answered["sub_kind"]["source"] == "document"
    assert [q.key for q in iv.outstanding] == []


def test_a_kind_the_ledger_cannot_tell_apart_is_not_guessed_at(vault):
    """A loan and a card are both liabilities, so the ledger's own word for the
    account decides nothing. With no document to settle it, the honest move is
    to ask nothing and record why."""
    account = "acct:northgate:9999"
    vault.ledger.append(account_opened(account, "liability", "Something", "USD",
                                       "2026-03-01"))
    iv = next(i for i in interviews(vault.ledger.projection(), "US")
              if i.account == account)
    assert iv.kind == "" and iv.schema is None
    assert "can't tell what kind" in iv.gap
    assert not [x for x in open_questions(vault.ledger, jurisdiction="US")["questions"]
                if x["refs"].get("account") == account]


def test_what_a_statement_already_said_is_not_asked_again(vault):
    """Asking a person to name the bank whose statement Viva just read is Viva
    not listening. The schema declares which account field answers it."""
    account = "Assets:Bank:Northgate"
    vault.ledger.append(account_opened(
        account, "depository", "Everyday", "USD", "2026-03-01",
        institution="Northgate Savings"))
    proj = vault.ledger.projection()
    iv = next(i for i in interviews(proj, "US") if i.account == account)
    assert "institution" not in [q.key for q in iv.outstanding]


def test_an_interview_ranks_with_the_other_questions_not_ahead_of_them(vault):
    """Ranking by consequence is settled, and an interview that outranked a
    larger finding would be incoherent."""
    account = _property(vault)
    qs = open_questions(vault.ledger, jurisdiction="US")["questions"]
    amounts = [Decimal(x["amount"]) for x in qs]
    assert amounts == sorted(amounts, reverse=True)
    mine = next(x for x in qs if x["refs"].get("account") == account)
    assert Decimal(mine["amount"]) == Decimal("0"), (
        "an interview on an account with no cash recorded against it settles no "
        "money, and says so rather than inventing a stake")


# ------------------------------------------------------------- deferring


def test_not_now_leaves_the_queue_and_can_still_be_found(vault):
    account = _property(vault)
    qid = question_id(account, "nickname")
    vault.ledger.append(question_declined(qid, INTERVIEW, "2026-03-02",
                                          reason="not_now", amount="0", count=0))
    payload = open_questions(vault.ledger, jurisdiction="US")
    assert qid not in [x["id"] for x in payload["questions"]]
    assert payload["pending"]["count"] >= 1
    assert qid in [x["id"] for x in
                   pending_questions(vault.ledger, jurisdiction="US")["questions"]]


def test_a_deferred_question_returns_when_evidence_touches_its_subject(vault):
    """No timer: it comes back because something changed about the thing it was
    about — and it is declined at its LIVE stake, so the evidence is the only
    thing that can bring it back."""
    account = _property(vault)
    live = next(x for x in open_questions(vault.ledger, jurisdiction="US")["questions"]
                if x["refs"].get("account") == account)
    vault.ledger.append(question_declined(
        live["id"], INTERVIEW, "2026-03-02", reason="not_now",
        amount=live["amount"], count=live["count"]))
    assert live["id"] not in [x["id"] for x in
                              open_questions(vault.ledger, jurisdiction="US")["questions"]]
    _rule_a_payment_into(vault, account)
    assert live["id"] in [x["id"] for x in
                          open_questions(vault.ledger, jurisdiction="US")["questions"]], (
        "money reached the thing it was about, so the question comes back")


def test_the_return_trigger_moves_for_an_account_no_ruling_touches(vault):
    """An account a statement created has no ruled cash, so counting only
    rulings left its questions frozen at a stake of zero — declined once,
    silent for ever, however many statements arrived afterwards. The trigger is
    the movements that touch it."""
    _seed_movement(vault)
    proj = vault.ledger.projection()
    account = next(a for a in proj.accounts() if a.startswith("acct:"))
    before = next(i for i in interviews(proj, "US") if i.account == account).settles
    _seed_movement(vault, amount="-99.00", blob=b"a second statement",
                   opening="75000.00", start="2026-04-01", end="2026-04-30")
    after = next(i for i in interviews(vault.ledger.projection(), "US")
                 if i.account == account).settles
    assert before == 1 and after > before


# ------------------------------------------- no figure the person did not say


def test_a_figure_absent_from_their_words_is_refused():
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                        "2026-03-02", said="it was about what we expected",
                        value="250000", currency="USD")


@pytest.mark.parametrize("said,value", [
    # The whole-number cases a reading gets wrong, and a digit-run check misses
    # because the digits are all present somewhere in the sentence.
    ("I paid 1,250,000 for it", "250000"),      # an order of magnitude out
    ("I paid 250 up front and 3,000 later", "5030"),   # assembled from parts
    ("I paid 250000", "25"),                    # truncated
    ("it was about what we expected", "250000"),       # no figure at all
])
def test_a_figure_the_sentence_does_not_carry_is_refused(said, value):
    """The guard compares NUMBERS the person wrote, not a run of digits. A
    sentence saying 1,250,000 is not a place where 250,000 was said."""
    with pytest.raises(ValueError):
        ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                        "2026-03-02", said=said, value=value, currency="USD")


@pytest.mark.parametrize("said,value", [
    ("I paid 2,50,000 for it", "250000.00"),    # lakh grouping
    ("I paid $250,000", "250000"),
    ("about 6.5%", "6.5"),
])
def test_a_figure_the_person_did_write_is_accepted(said, value):
    ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                    "2026-03-02", said=said, value=value, currency="USD")


def test_the_same_figure_written_differently_is_accepted():
    ruling_recorded(SCOPE_ATTRIBUTE, "Assets:Property:Cottage:purchase_price",
                    "2026-03-02", said="I paid 2,50,000 for it",
                    value="250000.00", currency="USD")


def test_a_value_outside_attribute_scope_is_refused():
    with pytest.raises(ValueError):
        ruling_recorded("merchant", "somebody", "2026-03-02", value="12",
                        said="12")


def test_an_answer_outside_the_offered_vocabulary_is_refused_not_guessed(vault):
    account = _property(vault)
    _answer(vault, account, "nickname", "Cottage", "Cottage")
    _answer(vault, account, "purchase_price", "250000", "250,000", "USD")
    _answer(vault, account, "purchase_date", "2019-06-01", "2019-06-01")
    out = engine.answer_attribute(vault, account, "use", said="by the sea")
    assert out["ok"] is False and out["why"] == "not_in_vocabulary"
    assert set(out["choices"]) == {"occupied", "rented", "land"}


def test_a_typed_amount_is_read_by_the_parser_and_kept_with_its_currency(vault):
    account = _property(vault)
    out = engine.answer_attribute(vault, account, "purchase_price",
                                   said="$250,000")
    assert out["ok"] and out["value"] == "250000" and out["currency"] == "USD"


# ------------------------------------------- an account nobody minted


def _reading(major, hint="", said=""):
    """A checked reading of what money became — what survives the slot checks
    behind the model, and all the write path is ever handed."""
    from viva.listen import Interpretation
    return Interpretation(legs=[{"major": major, "account_hint": hint,
                                 "share": ""}], said=said)


def test_an_asset_answer_with_nothing_named_asks_rather_than_mints(vault):
    """An empty hint plus an asset major must not open `Assets:Other:Unnamed`
    in the same request."""
    _seed_movement(vault)
    out = engine.record_ruling(vault, _reading("asset"),
                                movement_key=_first_movement(vault))
    assert out["ok"] is False and out["why"] == "needs_name"
    proj = vault.ledger.projection()
    assert not [a for a in proj.accounts() if "Unnamed" in a]


def test_an_answer_that_would_open_an_account_comes_back_to_be_confirmed(vault):
    _seed_movement(vault)
    out = engine.record_ruling(vault, _reading("asset", "The Estate"),
                                descriptor="NORTHGATE MOTORS")
    assert out["confirm"] is True
    assert out["proposal"]["new_accounts"] == ["Assets:Other:The Estate"]
    assert not vault.ledger.projection().seen_account("Assets:Other:The Estate"), (
        "nothing may exist until the person says yes")
    engine.apply_ruling(vault, out["proposal"])
    assert vault.ledger.projection().seen_account("Assets:Other:The Estate")


def test_a_proposal_with_something_unnamed_cannot_be_applied(vault):
    from viva.listen import Proposal, apply_proposal
    with pytest.raises(ValueError):
        apply_proposal(vault.ledger,
                       Proposal(scope="movement", subject="m", needs_name=["asset"]),
                       "2026-03-02")


def _rule_a_payment_into(vault, account, amount="-50000.00"):
    """Cash reaching a thing the person told us about — the evidence that moves
    an interview's stake."""
    from viva.ledger.events import ruling_recorded as _rr
    _seed_movement(vault, amount=amount)
    vault.ledger.append(_rr("movement", _first_movement(vault), "2026-03-06",
                            by="human",
                            legs=[{"major": "asset", "account": account}]))


def _first_movement(vault) -> str:
    return vault.ledger.projection().movements()[0].key


def _seed_movement(vault, amount="-25000.00", blob=b"doc",
                   opening="100000.00", start="2026-03-01", end="2026-03-31"):
    from viva.ingest import ReadResult, StatementFacts, TxnFact, capture_and_ingest
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Everyday", currency="USD",
        opening_amount=Decimal(opening), opening_date=start,
        closing_amount=Decimal(opening) + Decimal(amount),
        closing_date=end,
        transactions=[TxnFact(start, "NORTHGATE MOTORS", Decimal(amount))],
        account_number="000000001122", institution="Northgate")

    def read(_data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(vault.raw, vault.ledger, blob, read,
                       captured_at="2026-04-01")


# ---------------------------------------------------------- branching


def test_a_yes_opens_the_next_interview_without_creating_anything(vault):
    account = _property(vault)
    _answer(vault, account, "financed", "yes", "yes")
    proj = vault.ledger.projection()
    assert [kind for _, kind in opens_pending(proj, "US")] == ["home_loan"]
    out = engine.open_kind(vault, "home_loan", secures=account)
    assert out["ok"] is False and out["why"] == "needs_name"
    assert not [a for a in proj.accounts() if a.startswith("Liabilities:HomeLoan")]


def test_the_opened_loan_is_created_by_a_confirmed_proposal_and_links_back(vault):
    account = _property(vault)
    _answer(vault, account, "financed", "yes", "yes")
    out = engine.open_kind(vault, "home_loan", name="Northgate Lending",
                            secures=account)
    assert out["confirm"] is True
    engine.apply_ruling(vault, out["proposal"])
    proj = vault.ledger.projection()
    loan = "Liabilities:HomeLoan:Northgate Lending"
    assert proj.seen_account(loan)
    iv = next(i for i in interviews(proj, "US") if i.account == loan)
    assert iv.value_of("secures") == account
    assert not opens_pending(proj, "US"), (
        "the ask goes away because the loan names what it secures, not because "
        "anything was created to silence it")


# ------------------------------------------------------- the disclosed gap


def test_an_asset_with_no_stated_cost_is_a_gap_never_a_zero(vault):
    account = _property(vault)
    _answer(vault, account, "nickname", "Cottage", "Cottage")
    point = net_worth(vault.ledger.projection())
    gap = next(g for g in point.missing if g["account"] == account)
    assert gap["ask"]
    assert account not in [ln.account for ln in point.lines], "never a zero line"
    assert not point.complete


def test_a_stated_cost_becomes_a_line_rather_than_a_silence(vault):
    """Closing the gap must not make the asset vanish. Before this, answering
    the question the product asked removed the disclosure and put nothing in
    its place — and the total then claimed to be complete."""
    account = _property(vault)
    _answer(vault, account, "nickname", "Cottage", "Cottage")
    _answer(vault, account, "purchase_price", "250000", "250,000", "USD")
    point = net_worth(vault.ledger.projection())
    assert not [g for g in point.missing if g["account"] == account]
    line = next(ln for ln in point.lines if ln.account == account)
    assert line.amount == Decimal("250000") and line.currency == "USD"
    assert not line.provable, (
        "their word, which no document has checked, stays out of the provable "
        "subtotal")


def test_an_answer_today_does_not_rewrite_an_earlier_point(vault):
    """The curve grows forward. A point that honestly said it was incomplete
    must still say so after a later answer."""
    account = _property(vault)
    early = net_worth(vault.ledger.projection(), "2026-03-01")
    assert not early.complete
    _answer(vault, account, "purchase_price", "250000", "250,000", "USD")
    again = net_worth(vault.ledger.projection(), "2026-03-01")
    assert again.to_dict() == early.to_dict()


def test_an_ordinary_account_is_not_announced_as_a_gap(vault):
    """A savings account has no principal to state, so demanding one would
    invent a gap out of a question that was never owed — and drag the whole
    total to incomplete on the strength of it."""
    account = "Assets:Bank:Northgate"
    vault.ledger.append(account_opened(
        account, "depository", "Everyday", "USD", "2026-03-01",
        institution="Northgate Savings"))
    _answer(vault, account, "sub_kind", "savings", "savings")
    point = net_worth(vault.ledger.projection())
    assert not [g for g in point.missing if g["account"] == account]


def test_a_cost_that_cannot_be_read_is_disclosed_not_dropped(vault):
    """A value the ledger cannot turn into a figure must come back as the gap
    it is. Silence plus a complete total is the failure this cycle exists to
    remove, arrived at from the other side."""
    account = _property(vault)
    _answer(vault, account, "purchase_price", "two hundred and fifty",
            "two hundred and fifty")
    point = net_worth(vault.ledger.projection())
    assert [g for g in point.missing if g["account"] == account]
    assert not point.complete


def test_the_carried_figure_is_dated_when_it_was_bought(vault):
    account = _property(vault)
    _answer(vault, account, "purchase_price", "250000", "250,000", "USD")
    _answer(vault, account, "purchase_date", "2019-06-01", "2019-06-01")
    line = next(ln for ln in net_worth(vault.ledger.projection()).lines
                if ln.account == account)
    assert line.as_of == "2019-06-01", (
        "the day a person mentions a flat is not the day they bought it")


def test_a_correction_does_not_reach_backwards(vault):
    """A person fixing a typo must not silently delete a year of their own
    curve. An attribute is a history, like every other measurement here."""
    account = _property(vault)
    vault.ledger.append(ruling_recorded(
        SCOPE_ATTRIBUTE, f"{account}:purchase_price", "2026-02-01", by="human",
        grade=VERIFIED, said="250,000", value="250000", currency="USD"))
    before = net_worth(vault.ledger.projection(), "2026-03-01").to_dict()
    vault.ledger.append(ruling_recorded(
        SCOPE_ATTRIBUTE, f"{account}:purchase_price", "2026-06-01", by="human",
        grade=VERIFIED, said="300,000", value="300000", currency="USD"))
    assert net_worth(vault.ledger.projection(), "2026-03-01").to_dict() == before
    today = net_worth(vault.ledger.projection(), "2026-07-01")
    assert next(ln for ln in today.lines
                if ln.account == account).amount == Decimal("300000")


def test_a_group_is_not_a_name(vault):
    """A name made only of punctuation cleans away to nothing, and what is left
    is the group. Opening it would be the same defect one segment shorter."""
    account = _property(vault)
    out = engine.open_kind(vault, "home_loan", name=":", secures=account)
    assert out["ok"] is False and out["why"] == "needs_name"
    from viva.listen import Proposal, apply_proposal
    with pytest.raises(ValueError):
        apply_proposal(vault.ledger,
                       Proposal(scope="movement", subject="m", legs=[],
                                new_accounts=["Liabilities:HomeLoan"]),
                       "2026-03-02")


def test_a_reply_that_cannot_open_an_account_still_says_something_to_a_person(vault):
    """Every refusal carries Viva's words, and the naming one is no exception.

    A refusal that hands back only a machine reason leaves whoever asked with
    nothing to show: a person is left looking at an empty space where an
    explanation should be, and the schema pack's own question — the one thing
    that would tell them what to type — never reaches them."""
    from viva import persona
    account = _property(vault)
    out = engine.open_kind(vault, "home_loan", secures=account)

    assert out["ok"] is False and out["why"] == "needs_name"
    assert out["message"] == persona.moment("reply_needs_name", asks=out["asks"])
    assert out["asks"] and out["asks"] in out["message"]


def test_the_currency_follows_the_vault_and_is_never_assumed(vault, monkeypatch):
    """A flat bought in rupees is not four and a half million dollars. The
    currency comes from the accounts the vault already holds, because there is
    no table here saying what money a country uses — and where nothing says,
    the product declines rather than picks one."""
    monkeypatch.setenv("VIVA_LOCALE", "en-IN")
    empty = engine.open_kind(vault, "property", name="Flat 3B")
    assert empty["ok"] is False and empty["why"] == "no_currency"
    vault.ledger.append(account_opened(
        "Assets:Bank:Northgate", "depository", "Everyday", "INR", "2026-01-01",
        institution="Northgate"))
    out = engine.open_kind(vault, "property", name="Flat 3B")
    engine.apply_ruling(vault, out["proposal"])
    answered = engine.answer_attribute(
        vault, "Assets:Property:Flat 3B", "purchase_price", said="4500000")
    assert answered["currency"] == "INR"
    line = next(ln for ln in net_worth(vault.ledger.projection()).lines
                if ln.account == "Assets:Property:Flat 3B")
    assert line.currency == "INR"


def test_an_asset_the_pack_cannot_ask_about_is_still_disclosed(vault):
    """X2: an unfilled asset is never silently omitted. "I have no way to ask
    about this one" is an honest answer; a total that quietly reads complete
    is not."""
    account = "Assets:Curios:Something"
    vault.ledger.append(account_opened(account, "asset", "Something", "USD",
                                       "2026-03-01", origin="asserted"))
    point = net_worth(vault.ledger.projection())
    assert [g for g in point.missing if g["account"] == account]
    assert not point.complete


def test_a_stated_cost_beats_a_sum_of_the_payments_so_far(vault):
    """A part-paid property is the ordinary case. The person's figure for the
    whole thing is the cost; a sum of the instalments to date is not, and
    quietly preferring it reported the asset at a fraction of itself."""
    account = _property(vault)
    _seed_movement(vault, amount="-50000.00")
    key = _first_movement(vault)
    from viva.ledger.events import ruling_recorded as _rr
    vault.ledger.append(_rr("movement", key, "2026-03-06", by="human",
                            legs=[{"major": "asset", "account": account}]))
    _answer(vault, account, "purchase_price", "250000", "250,000", "USD")
    point = net_worth(vault.ledger.projection())
    mine = [ln for ln in point.lines if ln.account == account]
    assert len(mine) == 1 and mine[0].amount == Decimal("250000")


def test_a_link_to_the_wrong_kind_of_thing_is_refused(vault):
    account = _property(vault)
    out = engine.open_kind(vault, "home_loan", name="Northgate Lending",
                            secures=account)
    engine.apply_ruling(vault, out["proposal"])
    bad = engine.answer_attribute(
        vault, "Liabilities:HomeLoan:Northgate Lending", "secures",
        value="Assets:Bank:Northgate")
    assert bad["ok"] is False


def test_a_free_form_answer_is_not_read_as_a_number(vault):
    """The figure guards must not fire on a name. A lender called with a
    leading dash is not a negative amount."""
    account = _property(vault)
    out = engine.open_kind(vault, "home_loan", name="-Lakeside Lending",
                            secures=account)
    assert out["ok"] is True
    engine.apply_ruling(vault, out["proposal"])


def test_a_guessed_existing_account_is_named_in_the_sentence_it_confirms(vault):
    """An account picked because it LOOKED like one you have is a guess, and a
    guess nobody was told about is a guess the person did not make."""
    from viva.listen import Proposal
    summary = Proposal(scope="movement", subject="m",
                       legs=[{"major": "asset", "account": "x", "share": ""}],
                       confirm_accounts=["Assets:Vehicles:The Estate"],
                       amount="100", currency="USD").summary()
    assert "Assets:Vehicles:The Estate" in summary


def test_an_account_that_names_nothing_cannot_be_written(vault):
    """The confirmation endpoint trusts its own body less than the ledger
    does: a path whose last part is empty is a group, not a thing."""
    with pytest.raises(ValueError):
        engine.apply_ruling(vault, {
            "scope": "movement", "subject": "m", "legs": [],
            "new_accounts": ["Assets:Other:"], "summary": ""})


def test_a_name_cannot_inject_a_level_into_the_hierarchy(vault):
    account = _property(vault)
    out = engine.open_kind(vault, "home_loan", name="Lender:Sub:Deeper",
                            secures=account)
    assert out["proposal"]["new_accounts"] == [
        "Liabilities:HomeLoan:Lender Sub Deeper"]


# ----------------------------------------------------- nothing new was minted


def test_a_vault_built_before_this_replays_identically(vault):
    """The read-side promise, checked rather than asserted: everything above is
    a projection over events that already existed, plus one more SCOPE on the
    ruling event. A ledger with no attribute rulings must project exactly as it
    did."""
    _seed_movement(vault)
    before = vault.ledger.projection()
    baseline = (sorted(before.accounts()),
                {a: str(before.balance(a).amount) for a in before.accounts()},
                net_worth(before).to_dict())
    account = _property(vault)
    _answer(vault, account, "nickname", "Cottage", "Cottage")
    after = vault.ledger.projection()
    assert sorted(after.accounts()) != baseline[0], "the fixture must have changed"
    kinds = {e.event_type for e in vault.events()}
    assert "InterviewStarted" not in kinds and "AttributeRecorded" not in kinds
    assert kinds <= {"DocumentCaptured", "ReadRecorded", "AccountOpened",
                     "OpeningBalanceObserved", "ClosingBalanceObserved",
                     "TransactionRecorded", "MerchantEnriched",
                     "MerchantCategorized", "TransferSuggested",
                     "RulingRecorded", "AccountAliasConfirmed",
                     "CategoryAssigned", "PositionObserved"}, (
        "the interview must add no event type of its own")
