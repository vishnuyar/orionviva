"""A reply is read into the slots its question declared.

Two properties carry the whole weight, and they are the two halves of one
mechanism:

1. **A person's sentence, in real language, reaches the right typed structure.**
   The question says what an answer to it is made of; the model fills those
   slots from what was actually typed; the right writer runs. A sentence typed
   into a question about moving money is never read as a claim about what money
   became, because the question never asked for one.
2. **A value the model got wrong is refused by the deterministic check rather
   than written.** The parsers did not go away when the model moved in front of
   them — they stopped being the readers and became the checks behind. Nothing
   the model returns reaches the ledger on its own word.

Delete either half and this file goes red: without the first, real language is
refused; without the second, anything a model says is recorded.
"""

from decimal import Decimal

import pytest

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest, confirm_transfer)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import account_opened
from viva.listen import RULING_SLOTS
from viva.persona import moment
from viva.questions import INTERVIEW, MERCHANT, TRANSFER, open_questions
from viva.reply import Slot, answer, read_reply
from viva.schemas import ANSWER_CHOICE, ANSWER_MONEY
from viva.vault import Vault
from viva import engine


def _fills(payload):
    """A model that returns exactly this. What it returns is untrusted: every
    test here is about what happens to it next."""
    import json
    return lambda _prompt: json.dumps(payload)


def _reader(monkeypatch, payload):
    monkeypatch.setattr(engine, "_interpreter", lambda: _fills(payload))


def _facts(opening, txns, closing, ref, doc_type, number):
    return StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-01-01",
        closing_amount=Decimal(closing), closing_date="2026-01-31",
        transactions=[TxnFact(date=d, description=desc, amount=Decimal(a))
                      for d, desc, a in txns],
        account_number=number, institution="Northgate")


def _up(raw, ledger, data, facts):
    def _read(_data, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, 0.98, facts)
    capture_and_ingest(raw, ledger, data, _read, captured_at="2026-02-01")


class _Vault:
    """Only what the engine reaches for: a ledger."""

    def __init__(self, ledger):
        self.ledger = ledger


@pytest.fixture
def transfer_question(tmp_path):
    """A vault holding one ambiguous transfer, and the question it raises.

    Two card paydowns of the same amount in the same window, and a payment out
    of checking with nothing naming which card it went to — so the pair cannot
    be settled without asking."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    _up(raw, ledger, b"chk", _facts(
        "5000.00", [("2026-01-10", "PAYMENT", "-500.00")], "4500.00",
        ref="Everyday Checking 1111", doc_type="checking_statement",
        number="10001111"))
    _up(raw, ledger, b"card-a", _facts(
        "500.00", [("2026-01-11", "PAYMENT", "-500.00")], "0.00",
        ref="Card A 2222", doc_type="credit_card_statement",
        number="10002222"))
    _up(raw, ledger, b"card-b", _facts(
        "500.00", [("2026-01-12", "PAYMENT", "-500.00")], "0.00",
        ref="Card B 3333", doc_type="credit_card_statement",
        number="10003333"))
    qs = open_questions(ledger, as_of="2026-02-01")["questions"]
    question = next(q for q in qs if q["kind"] == TRANSFER)
    return _Vault(ledger), question


# ------------------------------- half one: language reaches the right structure


def test_a_sentence_about_moving_money_settles_the_question_that_asked_it(
        transfer_question, monkeypatch):
    """A sentence answers the question that was asked, and only that one.

    The question's own slot is the target: a person writes a sentence; the model
    fills `same_money`; the deterministic check confirms it is one of the two
    words that slot accepts; and the transfer is linked. The words never reach a
    reader looking for expense/asset/liability/income, because nothing on this
    question declares one."""
    vault, question = transfer_question
    _reader(monkeypatch, {"same_money": "yes"})

    out = engine.answer_question(
        vault, question["id"], said="yes, that was moving money to my card")

    assert out["ok"] is True and out["linked"] is True
    assert vault.ledger.projection().linked_keys(), "the pair was settled"


def test_the_same_sentence_saying_no_records_the_other_ruling(
        transfer_question, monkeypatch):
    """A no is an answer too, and it goes to a different writer."""
    vault, question = transfer_question
    _reader(monkeypatch, {"same_money": "no"})

    out = engine.answer_question(vault, question["id"],
                                  said="no, that one really was spending")

    assert out["ok"] is True and out["linked"] is False
    assert not vault.ledger.projection().linked_keys()


def test_an_amount_no_parser_reads_is_accepted_once_the_model_shapes_it(
        interview, monkeypatch):
    """The difference the mechanism makes. No amount parser reads a sentence —
    under parser-selection, "$250,000 or thereabouts" was handed to `parse_amount`
    whole and refused. The model returns the amount and its currency; the amount
    parser then confirms that IS a real amount in a known currency; and it is
    recorded."""
    vault = interview
    _reader(monkeypatch, {"nickname": "Cottage"})
    engine.answer_question(vault, _next_interview(vault)["id"],
                            said="I just call it the cottage")

    asking = _next_interview(vault)
    assert asking["slots"][0]["type"] == ANSWER_MONEY
    _reader(monkeypatch, {"purchase_price": {"value": "250000",
                                             "currency": "USD"}})
    out = engine.answer_question(vault, asking["id"],
                                  said="we paid $250,000 or thereabouts")

    assert out["ok"] and out["value"] == "250000" and out["currency"] == "USD"


def test_a_figure_the_sentence_never_carried_is_refused_however_well_read(
        interview, monkeypatch):
    """And the limit of that, which is a rule older than this mechanism: an
    attribute value may carry no figure the person's own sentence did not.

    So a reading that expands "250k" into 250000 is well-formed, survives the
    amount check, and is still refused at the write — the digits are not in what
    they said. Nothing is recorded and the person is asked for the figure in
    their own words. Any change to this belongs to whoever owns the invariant,
    not to the reader in front of it."""
    vault = interview
    _reader(monkeypatch, {"nickname": "Cottage"})
    engine.answer_question(vault, _next_interview(vault)["id"], said="Cottage")

    asking = _next_interview(vault)
    before = len(list(vault.ledger.events()))
    _reader(monkeypatch, {"purchase_price": {"value": "250000",
                                             "currency": "USD"}})
    out = engine.answer_question(vault, asking["id"],
                                  said="about 250k, give or take")

    assert out["ok"] is False and out["why"] == "figure_not_said"
    assert len(list(vault.ledger.events())) == before, "nothing was recorded"


def test_a_currency_the_person_stated_is_never_swapped_for_the_accounts(
        interview, monkeypatch):
    """An amount is a value AND a currency, so the currency has to survive the
    whole way to the writer — and where it disagrees with what the account is
    held in, the answer is a question, not a conversion.

    The failure this guards is silent and permanent: the model splits the
    currency into its own field, so the amount parser never sees a conflict to
    refuse, and a writer handed the bare figure re-derives the currency from the
    account. The person said one thing; the ledger would record another, for
    ever. Nothing in this product converts between currencies — net worth is
    per-currency subtotals — so there is nothing to compute here and nothing to
    assume."""
    vault = interview
    _reader(monkeypatch, {"nickname": "Cottage"})
    engine.answer_question(vault, _next_interview(vault)["id"], said="Cottage")

    asking = _next_interview(vault)
    assert asking["currency"] == "USD", "the account is held in one currency"
    before = len(list(vault.ledger.events()))
    _reader(monkeypatch, {"purchase_price": {"value": "250000",
                                             "currency": "EUR"}})
    out = engine.answer_question(vault, asking["id"], said="we paid 250000 EUR")

    assert out["ok"] is False and out["why"] == "currency_conflict"
    assert "EUR" in out["message"] and "USD" in out["message"], (
        "the person is told which two currencies disagree")
    assert len(list(vault.ledger.events())) == before, "nothing was recorded"


def test_the_writer_is_handed_the_currency_that_was_validated_at_the_door(
        interview):
    """And the same rule one layer in, where the defect actually landed.

    The writer checks again — the check is idempotent and it must not trust
    what reached it — but it can only check what it is given. Handed a bare
    figure it would supply a currency from the account, which is the silent
    substitution wearing a second coat. So the currency is a parameter, and a
    conflicting one is refused here too."""
    account = "Assets:Property:Cottage"
    engine.answer_attribute(interview, account, "nickname", value="Cottage",
                             said="Cottage")
    before = len(list(interview.ledger.events()))

    refused = engine.answer_attribute(interview, account, "purchase_price",
                                       value="250000", currency="EUR",
                                       said="we paid 250000 EUR")
    assert refused["ok"] is False and refused["why"] == "currency_conflict"
    assert len(list(interview.ledger.events())) == before

    kept = engine.answer_attribute(interview, account, "purchase_price",
                                    value="250000", currency="USD",
                                    said="we paid 250000 USD")
    assert kept["ok"] and kept["currency"] == "USD"
    recorded = list(interview.ledger.events())[-1].body
    assert recorded["value"] == "250000" and recorded["currency"] == "USD"


# ------------------------------------- the model gets its chance, then the person


def _replies(*payloads):
    """A model that says each of these in turn, recording every prompt it got."""
    import json
    seen = []

    def extract(prompt):
        seen.append(prompt)
        said = payloads[min(len(seen) - 1, len(payloads) - 1)]
        return said if isinstance(said, str) else json.dumps(said)
    return extract, seen


def test_a_reply_that_does_not_fit_goes_back_to_the_model_before_the_person(
        transfer_question, monkeypatch):
    """It is the model that turns an answer into the declared shape, so when the
    shape does not come back, the model is what gets asked again — as a
    confirmation, naming what came back and what was wrong with it. The person
    is not troubled for a machine's mistake."""
    vault, question = transfer_question
    extract, seen = _replies("no JSON here at all", {"same_money": "yes"})
    monkeypatch.setattr(engine, "_interpreter", lambda: extract)

    out = engine.answer_question(vault, question["id"],
                                  said="yes, that was moving money to my card")

    assert len(seen) == 2, "the model was asked again"
    assert "no JSON here at all" in seen[1], "and shown what it had sent"
    assert "unparseable" in seen[1], "and told what was wrong with it"
    assert out["ok"] is True and out["linked"] is True, "the second attempt landed"


def test_the_model_gets_one_chance_and_only_then_is_the_person_asked(
        transfer_question, monkeypatch):
    """One retry, never a loop — the same budget the answer path keeps in the
    other direction. And what the person finally sees asks them for something,
    rather than describing the machinery that failed."""
    vault, question = transfer_question
    extract, seen = _replies("still not JSON")
    monkeypatch.setattr(engine, "_interpreter", lambda: extract)
    before = len(list(vault.ledger.events()))

    out = engine.answer_question(vault, question["id"], said="yes, same money")

    assert len(seen) == 2, "exactly one retry, then it stops"
    assert out["ok"] is False
    assert out["message"] == moment("reply_ask_again")
    assert len(list(vault.ledger.events())) == before


def test_a_stated_currency_is_never_handed_back_for_a_second_opinion(
        interview, monkeypatch):
    """The one refusal that must not be retried. Asking the model again about a
    currency the person plainly stated invites it to drop the currency to make
    the reply fit — which is exactly the silent substitution being refused. A
    disagreement between what was said and what the vault holds is not something
    a second reading can honestly change."""
    vault = interview
    _reader(monkeypatch, {"nickname": "Cottage"})
    engine.answer_question(vault, _next_interview(vault)["id"], said="Cottage")

    asking = _next_interview(vault)
    extract, seen = _replies({"purchase_price": {"value": "250000",
                                                 "currency": "EUR"}})
    monkeypatch.setattr(engine, "_interpreter", lambda: extract)
    out = engine.answer_question(vault, asking["id"], said="we paid 250000 EUR")

    assert out["why"] == "currency_conflict"
    assert len(seen) == 1, "asked once, and not asked to try again"


def test_a_retried_reading_records_both_texts_that_produced_it(
        transfer_question, monkeypatch):
    """A recorded prompt_version must resolve to the exact text that produced
    the reading, forever. A reading the second attempt produced stood on the
    instructions AND the complaint, so it is stamped with both."""
    from viva.ingest.prompt_library import resolve
    from viva.reply import INTERPRET_RETRY_VERSION, INTERPRET_VERSION, answer

    extract, seen = _replies("not JSON", {"same_money": "yes"})
    got = answer("yes", (Slot(name="same_money", type="yes_no", required=True),),
                 asked="Was it the same money?", extract_fn=extract)

    assert got.ok and got.version == f"{INTERPRET_VERSION}+{INTERPRET_RETRY_VERSION}"
    text = resolve(got.version)
    assert resolve(INTERPRET_VERSION) in text
    assert resolve(INTERPRET_RETRY_VERSION) in text


# -------------------------------- half two: the check behind refuses the model


def test_a_value_the_model_invented_for_an_amount_is_refused_not_written(
        interview, monkeypatch):
    """The model proposes; the code disposes. A money slot filled with something
    that is not an amount is refused by the same parser that has always refused
    it, and nothing is recorded — the model's word is not evidence."""
    vault = interview
    _reader(monkeypatch, {"nickname": "Cottage"})
    engine.answer_question(vault, _next_interview(vault)["id"], said="Cottage")

    asking = _next_interview(vault)
    before = len(list(vault.ledger.events()))
    _reader(monkeypatch, {"purchase_price": {"value": "quite a lot",
                                             "currency": "USD"}})
    out = engine.answer_question(vault, asking["id"], said="it was a fair bit")

    assert out["ok"] is False and out["why"] == "unreadable_money"
    assert len(list(vault.ledger.events())) == before, "nothing was recorded"
    assert _next_interview(vault)["id"] == asking["id"], "it is asked again"


def test_a_word_outside_the_declared_vocabulary_is_refused_with_it_named(
        transfer_question, monkeypatch):
    """A yes/no slot takes two words. A model that hedges is refused, the
    alternatives are named, and the ledger is untouched."""
    vault, question = transfer_question
    before = len(list(vault.ledger.events()))
    _reader(monkeypatch, {"same_money": "probably, yes"})

    out = engine.answer_question(vault, question["id"],
                                  said="I think so, probably")

    assert out["ok"] is False and out["why"] == "not_in_vocabulary"
    assert set(out["choices"]) == {"yes", "no"}
    assert len(list(vault.ledger.events())) == before
    assert not vault.ledger.projection().linked_keys()


def test_a_category_the_model_may_not_be_told_is_still_one_you_can_answer_with(
        tmp_path, monkeypatch):
    """What crosses to a model and what a person may say are two lists.

    A category the person coined can carry another person's name, so it is held
    back from the prompt (T9). It is still theirs: the slot validates against
    the whole vocabulary, so answering with it settles the question rather than
    being read back a list of alternatives that omits their own word."""
    from viva.listen import shareable_categories
    from viva.reply import _render_slots

    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    _up(raw, ledger, b"chk", _facts(
        "5000.00", [("2026-01-10", "SOMEWHERE LTD", "-40.00")], "4960.00",
        ref="Everyday Checking 1111", doc_type="checking_statement",
        number="10001111"))
    vault = _Vault(ledger)
    q = next(x for x in open_questions(ledger, as_of="2026-02-01")["questions"]
             if x["kind"] == MERCHANT)

    coined = "Money to family"
    assert coined not in shareable_categories([coined]), (
        "this test needs a category the gate actually withholds")

    # Through the real question builder, with the vault's vocabulary holding a
    # name the gate refuses — this is the wiring, not a hand-built slot.
    import viva.listen as listen_module
    import viva.questions as questions_module
    whole = tuple(q["slots"][0]["choices"]) + (coined,)
    monkeypatch.setattr(questions_module, "category_vocabulary",
                        lambda _proj: whole)
    monkeypatch.setattr(listen_module, "category_vocabulary",
                        lambda _proj: whole)

    built = questions_module._merchant_questions(ledger.projection())
    assert built, "no merchant question to check the wiring on"
    slot = built[0].slots[0]
    assert coined in slot.choices, (
        "the fence dropped the person's own word — they cannot answer with it")
    assert coined not in (slot.offered or ()), "the gate let the name cross"
    assert coined not in _render_slots((slot,)), "the model was told it anyway"

    # And a reply naming it settles rather than being read back a list.
    from viva.reply import answer as read_answer
    read = read_answer(coined, (slot,))
    assert read.ok, f"{read.why}: {read.message}"
    assert read.values["category"] == coined

    # The same holds for the ruling path's category slot.
    ruling = next(s for s in listen_module.ruling_slots(whole)
                  if s.name == "category")
    assert coined in ruling.choices and coined not in (ruling.offered or ())


def test_a_category_the_vault_does_not_know_is_refused_rather_than_minted(
        tmp_path, monkeypatch):
    """A merchant question's categories are a closed vocabulary — validation,
    not buttons. The model is told what it is and must return a member; a word
    of its own is refused rather than becoming a new category nobody chose."""
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    _up(raw, ledger, b"chk", _facts(
        "5000.00", [("2026-01-10", "SOMEWHERE LTD", "-40.00")], "4960.00",
        ref="Everyday Checking 1111", doc_type="checking_statement",
        number="10001111"))
    vault = _Vault(ledger)
    q = next(x for x in open_questions(ledger, as_of="2026-02-01")["questions"]
             if x["kind"] == MERCHANT)
    allowed = q["slots"][0]["choices"]
    assert allowed, "an enumerated slot with no vocabulary can only be refused"

    _reader(monkeypatch, {"category": "sundries and bits"})
    refused = engine.answer_question(vault, q["id"], said="oh, odds and ends")
    assert refused["ok"] is False and refused["why"] == "not_in_vocabulary"

    _reader(monkeypatch, {"category": allowed[0]})
    out = engine.answer_question(vault, q["id"], said="oh, odds and ends")
    assert out["ok"] and out["category"] == allowed[0]


def test_a_leg_outside_the_ledgers_own_vocabulary_never_reaches_a_ruling():
    """The closed-vocabulary discipline, now running as a check behind the
    model rather than inside it. A leg whose major is not one of the four is
    dropped; a reading left with none is unanswered, and a refusal is what the
    person gets."""
    good = read_reply(RULING_SLOTS, {"legs": [{"major": "expense"},
                                              {"major": "equity"}]})
    assert good.ok and [leg["major"] for leg in good.values["legs"]] == ["expense"]

    none_left = read_reply(RULING_SLOTS, {"legs": [{"major": "equity"}]})
    assert none_left.ok is False and none_left.why == "unanswered"


def test_a_share_the_model_made_up_is_still_only_a_number_it_must_prove():
    """A proportion is checked like every other value. What stops an invented
    split is the instruction not to invent one, but what stops a malformed one
    reaching a posting is this."""
    got = read_reply(RULING_SLOTS, {"legs": [{"major": "expense",
                                              "share": "most of it"}]})
    assert got.ok, "an unreadable share must not throw away the answer"
    assert got.values["legs"] == [{"major": "expense", "account_hint": "",
                                   "share": ""}], (
        "a proportion nothing can read is a proportion nobody stated")


# ----------------------------------------------- what a question declares now


def test_every_question_declares_the_structure_of_its_answer(transfer_question):
    """Not a type to route on, and not a payload to click: the slots an answer
    is made of. A question with none says nothing spoken settles it."""
    vault, _question = transfer_question
    questions = open_questions(vault.ledger, as_of="2026-02-01")["questions"]
    assert {q["kind"] for q in questions} >= {TRANSFER}, "the fixture went quiet"
    for q in questions:
        for key in ("options", "free_text", "reply", "choices"):
            assert key not in q, f"{key} is back in the payload"
        for slot in q["slots"]:
            assert slot["name"] and (slot["type"] or slot.get("parts"))


def test_a_slot_nothing_can_check_is_a_build_error_not_a_persons_mistake():
    with pytest.raises(ValueError):
        Slot(name="mood", type="vibes")
    with pytest.raises(ValueError):
        Slot(name="which", type=ANSWER_CHOICE)      # one of nothing
    with pytest.raises(ValueError):
        Slot(name="legs", type=ANSWER_CHOICE, parts=(Slot("a", ANSWER_MONEY),))


def test_a_pair_settled_while_the_question_was_open_is_told_so_in_words(
        transfer_question):
    """A movement belongs to at most one transfer, so a yes about a pair that
    was settled between the question being read and the answer arriving records
    nothing at all.

    Recording nothing is honest; going quiet about it is not. The reply carries
    Viva's own words for what happened, so no surface has to invent a sentence —
    and the words it does carry do not claim the answer was unreadable, because
    it was read perfectly."""
    from viva.questions import find_question
    from viva.reply import Reply

    vault, question = transfer_question
    q = find_question(vault.ledger, question["id"], as_of="2026-02-01")
    confirm_transfer(vault.ledger, q.refs["movement"], q.refs["candidates"][0])
    before = len(list(vault.ledger.events()))

    out = engine._write_answer(
        vault, q, Reply(True, values={"same_money": "yes"}), "yes, same money")

    assert out["ok"] is False and out["why"] == "already_linked"
    assert out["message"] == moment("reply_already_linked")
    assert len(list(vault.ledger.events())) == before, "nothing further recorded"


def test_a_question_no_longer_being_asked_records_nothing(interview):
    """The queue is read live, so an answer to a question it no longer holds
    writes nothing and says so."""
    out = engine.answer_question(interview, "interview:nothing:at:all",
                                  said="yes")
    assert out["ok"] is False and out["why"] == "not_open"


# ------------------------------------------------------ with nothing configured


def test_with_no_reader_a_plain_answer_still_lands_and_a_loose_one_does_not(
        interview, monkeypatch):
    """Local-first: the machine with nothing configured is not a machine that
    cannot answer anything. The filler degrades to the identity — the sentence
    is offered to the slot as typed — and the same deterministic checks decide.
    So plain words land, and everything else is refused rather than guessed."""
    vault = interview
    monkeypatch.setattr(engine, "_interpreter", lambda: None)

    named = engine.answer_question(vault, _next_interview(vault)["id"],
                                    said="Cottage")
    assert named["ok"]

    asking = _next_interview(vault)
    loose = engine.answer_question(vault, asking["id"], said="about 250k")
    assert loose["ok"] is False and loose["why"] == "unreadable_money"

    plain = engine.answer_question(vault, asking["id"], said="$250,000")
    assert plain["ok"] and plain["value"] == "250000"


def test_a_reader_that_cannot_be_reached_says_so_and_is_not_asked_again(
        transfer_question, monkeypatch):
    """A reader that is DOWN is a different thing from one that answered with
    something unusable. Nothing a second attempt could carry reaches a reader
    that is not there, so the retry is spent only where it can honestly change
    the answer — and the person is told the truth about what happened rather
    than asked to say it again."""
    tries = []

    def _down(_prompt):
        tries.append(_prompt)
        raise ConnectionError("nothing listening")

    vault, question = transfer_question
    monkeypatch.setattr(engine, "_interpreter", lambda: _down)
    before = len(list(vault.ledger.events()))

    out = engine.answer_question(vault, question["id"], said="yes, same money")

    assert out["ok"] is False and out["why"] == "unreachable"
    assert len(tries) == 1, "asked once, and not asked to try again"
    assert out["message"] == moment("reply_unreachable")
    assert len(list(vault.ledger.events())) == before


# ------------------------------------------------------------- the interview


@pytest.fixture
def interview(tmp_path):
    """An asset the person told us about, and the interview it opens."""
    vault = Vault.open(tmp_path / "v", "pw")
    vault.ledger.append(account_opened(
        "Assets:Property:Cottage", "asset", "Cottage", "USD", "2026-03-01",
        origin="asserted"))
    return vault


def _next_interview(vault) -> dict:
    qs = open_questions(vault.ledger, as_of="2026-03-02",
                        jurisdiction="US")["questions"]
    return next(q for q in qs if q["kind"] == INTERVIEW)


def test_a_schema_question_declares_its_slot_where_every_question_does(interview):
    """A schema question's answer type is a slot on the question, in the field
    every other question uses, rather than buried among its references — and it
    carries the schema's own words for what is being asked."""
    q = _next_interview(interview)
    (slot,) = q["slots"]
    assert slot["name"] == "nickname" and slot["type"] == "label"
    assert "answer" not in q["refs"], "a declaration, not something to dig for"


def test_the_two_halves_run_in_that_order_and_only_that_order():
    """`answer` is fill-then-check. A check that ran first would be reading the
    raw sentence, which is the mechanism this replaced; a fill with no check
    behind it would put a model's word in a ledger."""
    seen = []

    def _fill(prompt):
        seen.append(prompt)
        return '{"same_money": "maybe"}'

    got = answer("I suppose so", (Slot(name="same_money", type="yes_no",
                                       required=True),),
                 asked="Were these the same money?", extract_fn=_fill)
    assert seen, "the model is asked first"
    assert "Were these the same money?" in seen[0], "and asked what was asked"
    assert "same_money" in seen[0], "and told the structure to fill"
    assert got.ok is False and got.why == "not_in_vocabulary"
