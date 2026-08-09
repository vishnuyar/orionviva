"""Viva asking, at a terminal.

An entry point with no test is a surface with no lint. What is pinned here is
what a person at a terminal actually meets: the queue is shown with what each
question wants back, a line typed lands in the engine and is recorded, a reply
that does not hold up comes back in Viva's words rather than as a machine
reason, and an empty queue says so.

And the other half of the loop, where the stakes are higher: an answer that
would bring an account into being is proposed rather than written, and only an
explicit yes applies it. The property those tests carry is that nothing reaches
the ledger without one — proved by counting events across a sitting where the
confirmation never comes.
"""

import json
from decimal import Decimal

from viva import ask, engine
from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest)
from viva.ledger import EventStore, Ledger
from viva.ledger.events import (SCOPE_ATTRIBUTE, VERIFIED, account_opened,
                                ruling_recorded)
from viva.persona import load as load_pack
from viva.persona import moment
from viva.vault import Vault


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _vault(tmp_path):
    return Vault(ledger=Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")),
                 raw=RawStore.open(tmp_path / "raw", "pw"), directory=tmp_path)


def _checking(vault, txns, opening="100000.00"):
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Everyday Account", currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-03-01",
        closing_amount=Decimal(opening) + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Riverbank")
    capture_and_ingest(vault.raw, vault.ledger, b"chk",
                       lambda d, i: _stamp(facts, i), captured_at="2026-04-01")
    return vault


def _one_merchant_question(tmp_path):
    return _checking(_vault(tmp_path), [
        ("2026-03-05", "ACME HARDWARE #12", "-100.00"),
        ("2026-03-09", "ACME HARDWARE #44", "-150.00"),
    ])


_HOUSE = "Assets:Property:Cottage"
_LOAN = "Liabilities:HomeLoan:Northgate Lending"

# Everything the schema asks about a property, answered — so the only thing left
# to ask is the one that follows from the yes: what the loan is called.
_ANSWERED = (("nickname", "Cottage"), ("purchase_price", "250000"),
             ("purchase_date", "2019-06-01"), ("use", "occupied"),
             ("financed", "yes"), ("ownership_share", "100"),
             ("improvements_since_purchase", "1000"))


def _a_loan_to_name(tmp_path):
    """A vault whose one open question is the one that would open an account.

    The person has said the property is financed, so a loan exists; nothing
    names it yet, and naming it is what produces a proposal."""
    vault = _vault(tmp_path)
    vault.ledger.append(account_opened(_HOUSE, "asset", "Cottage", "USD",
                                       "2026-03-01", origin="asserted"))
    for key, value in _ANSWERED:
        vault.ledger.append(ruling_recorded(
            SCOPE_ATTRIBUTE, f"{_HOUSE}:{key}", "2026-03-02", by="human",
            grade=VERIFIED, said=value, value=value))
    return vault


def _reader(monkeypatch, payload):
    """A model that returns this structure whatever was typed at it. What it
    returns is untrusted — the deterministic check behind it still decides."""
    monkeypatch.setattr(engine, "_interpreter",
                        lambda: lambda _prompt: json.dumps(payload))


def _no_model(monkeypatch):
    """No reader configured, so the filler is the identity and a plainly written
    reply is decided by the deterministic checks alone."""
    for var in ("VIVA_MODEL", "VIVA_INTERPRET_MODEL"):
        monkeypatch.delenv(var, raising=False)


def _fixed_part(key: str) -> str:
    """The part of a pack line that carries no slot — what a person reads
    whatever the alternatives turn out to be."""
    return load_pack()["moments"][key].split("{")[0]


def _typed(*lines):
    """A person at the keyboard, one line per prompt, then silence."""
    said = list(lines)

    def read_line(prompt=""):
        return said.pop(0) if said else ""

    return read_line


def test_an_empty_queue_says_so_in_vivas_words(tmp_path, capsys):
    ask.run(_vault(tmp_path), limit=10)
    out = capsys.readouterr().out
    assert out.strip() == moment("all_settled", name_part="")


def test_the_listing_shows_the_question_and_what_it_wants_and_writes_nothing(
        tmp_path, capsys):
    vault = _one_merchant_question(tmp_path)
    before = len(list(vault.ledger.store.events()))

    ask.run(vault, limit=10, listing=True)

    out = capsys.readouterr().out
    assert "ACME HARDWARE" in out                 # the question Viva would ask
    assert "why:" in out                          # the evidence under it
    # What an answer to it is made of: one of a closed list, named in the pack's
    # words rather than as a type from the code.
    assert _fixed_part("wants_choice") in out
    assert "groceries" in out
    assert len(list(vault.ledger.store.events())) == before, \
        "a listing writes nothing"


def test_an_answer_typed_at_the_terminal_reaches_the_ledger(tmp_path, capsys,
                                                            monkeypatch):
    _no_model(monkeypatch)
    vault = _one_merchant_question(tmp_path)

    ask.run(vault, limit=10, read_line=_typed("groceries"))

    proj = vault.ledger.projection()
    assert not proj.uncategorized_merchants(), "the ruling settled the merchant"
    assert moment("reply_recorded") in capsys.readouterr().out


def test_a_reply_that_does_not_hold_up_comes_back_in_vivas_words(tmp_path, capsys,
                                                                 monkeypatch):
    """Never a machine reason: the person is told what would have been accepted,
    in the words the pack holds, and nothing is recorded."""
    _no_model(monkeypatch)
    vault = _one_merchant_question(tmp_path)

    ask.run(vault, limit=10, read_line=_typed("oh, odds and ends"))

    out = capsys.readouterr().out
    assert _fixed_part("reply_not_in_vocabulary") in out
    assert "not_in_vocabulary" not in out
    assert vault.ledger.projection().uncategorized_merchants(), "nothing recorded"


def test_a_blank_line_ends_the_sitting(tmp_path, capsys, monkeypatch):
    _no_model(monkeypatch)
    vault = _one_merchant_question(tmp_path)

    ask.run(vault, limit=10, read_line=_typed(""))

    assert vault.ledger.projection().uncategorized_merchants()
    assert moment("reply_recorded") not in capsys.readouterr().out


def test_a_question_asks_for_each_thing_once(capsys):
    """What a person is being asked for is the line, not the slot.

    A ruling is made of several slots and two of them want the same kind of
    answer — a label, in the person's own words — so printed one per slot the
    question ends in the same line twice, which reads as a second thing to
    type."""
    from viva.listen import RULING_SLOTS
    question = {"amount": "100.00", "currency": "USD", "scope": "one",
                "count": 1, "text": "What was this?", "why": "because",
                "slots": [s.to_dict() for s in RULING_SLOTS]}
    ask.print_question(question, 1, "type away", "a document answers this")
    lines = [line for line in capsys.readouterr().out.splitlines()
             if line.startswith("  ")]
    assert len(lines) == len(set(lines)), lines
    assert len(lines) > 1, "the fixture asks for only one thing"


def test_every_kind_of_slot_has_words_for_what_it_wants():
    """A person can see what a question is asking for. A slot type with no
    sentence in the pack would print nothing, or a code word — both leave
    someone guessing at what to type."""
    from viva.schemas import ANSWER_CHOICE, ANSWER_TYPES

    for slot_type in ANSWER_TYPES:
        slot = {"name": "x", "type": slot_type}
        if slot_type == ANSWER_CHOICE:
            slot["choices"] = ["one", "two"]
        assert ask.wants(slot).strip(), f"{slot_type} says nothing about itself"
    assert ask.wants({"name": "legs", "type": "", "parts": [{"name": "major"}]}) \
        == moment("wants_several")


def test_a_reply_she_could_not_read_leaves_the_question_where_it_was(tmp_path,
                                                                     capsys,
                                                                     monkeypatch):
    """Viva's answer to an unreadable reply is to ask again, so the question is
    put again rather than the sitting moving past it — and the second answer
    lands on the question the first one was about."""
    _no_model(monkeypatch)
    vault = _one_merchant_question(tmp_path)

    ask.run(vault, limit=10, read_line=_typed("odds and ends", "groceries"))

    out = capsys.readouterr().out
    assert out.count("May I ask what ACME HARDWARE") == 2
    assert not vault.ledger.projection().uncategorized_merchants()


def test_an_answer_that_would_open_an_account_is_proposed_before_it_is_written(
        tmp_path, capsys, monkeypatch):
    """The proposal is shown before anything happens: what would be recorded,
    that none of it has yet, and that a yes or a no settles it."""
    _no_model(monkeypatch)
    vault = _a_loan_to_name(tmp_path)

    ask.run(vault, limit=10, read_line=_typed("Northgate Lending"))

    out = capsys.readouterr().out
    assert _LOAN.rsplit(":", 1)[-1] in out, "what would come into being is named"
    assert moment("reply_needs_confirming") in out
    assert moment("reply_confirm_asks") in out
    assert moment("wants_yes_no") in out


def test_a_yes_at_the_terminal_records_the_proposal(tmp_path, capsys,
                                                    monkeypatch):
    _no_model(monkeypatch)
    vault = _a_loan_to_name(tmp_path)

    ask.run(vault, limit=10, read_line=_typed("Northgate Lending", "yes"))

    assert vault.ledger.projection().seen_account(_LOAN)
    assert moment("reply_recorded") in capsys.readouterr().out


def test_a_no_records_nothing_and_says_so(tmp_path, capsys, monkeypatch):
    _no_model(monkeypatch)
    vault = _a_loan_to_name(tmp_path)
    before = len(list(vault.ledger.store.events()))

    ask.run(vault, limit=10, read_line=_typed("Northgate Lending", "no"))

    assert not vault.ledger.projection().seen_account(_LOAN)
    assert len(list(vault.ledger.store.events())) == before
    assert moment("reply_not_confirmed") in capsys.readouterr().out


def test_a_confirmation_is_read_as_language_not_as_a_word(tmp_path, monkeypatch):
    """The whole reason a confirmation is not a button: a person answers in
    their own words. Nothing here compares what was typed against "yes" — the
    model fills the declared slot and the check behind it decides — so a yes
    inside a sentence lands where a bare one does."""
    _reader(monkeypatch, {"name": "Northgate Lending", "confirm": "yes"})
    vault = _a_loan_to_name(tmp_path)

    ask.run(vault, limit=10,
            read_line=_typed("it's with Northgate Lending", "yes, that's right"))

    assert vault.ledger.projection().seen_account(_LOAN)


def test_a_confirmation_that_reads_as_neither_is_asked_again_and_then_moves_on(
        tmp_path, capsys, monkeypatch):
    _no_model(monkeypatch)
    vault = _a_loan_to_name(tmp_path)

    ask.run(vault, limit=10,
            read_line=_typed("Northgate Lending", "hmm", "let me think"))

    out = capsys.readouterr().out
    assert out.count(moment("reply_confirm_asks")) == ask.ASKED_AT_MOST
    assert out.count(_fixed_part("reply_not_in_vocabulary")) == ask.ASKED_AT_MOST
    assert not vault.ledger.projection().seen_account(_LOAN)


def test_a_proposal_that_is_never_confirmed_leaves_the_ledger_untouched(
        tmp_path, monkeypatch):
    """The property the whole confirmation exists for. A sitting that proposes
    twice and confirms nothing — once talked past, once walked away from —
    writes not one event."""
    _no_model(monkeypatch)
    vault = _a_loan_to_name(tmp_path)
    before = len(list(vault.ledger.store.events()))

    ask.run(vault, limit=10,
            read_line=_typed("Northgate Lending", "hmm", "let me think",
                             "Northgate Lending", ""))

    assert len(list(vault.ledger.store.events())) == before
    assert not vault.ledger.projection().seen_account(_LOAN)


def test_a_question_nothing_settles_does_not_hold_up_the_queue(tmp_path, capsys,
                                                               monkeypatch):
    """The other half: asked again is asked ONCE again. A person who cannot
    answer one thing must still reach the rest of their list."""
    _no_model(monkeypatch)
    vault = _one_merchant_question(tmp_path)

    ask.run(vault, limit=10,
            read_line=_typed("odds and ends", "still odds and ends", "no"))

    out = capsys.readouterr().out
    assert out.count("May I ask what ACME HARDWARE") == ask.ASKED_AT_MOST
    assert "Everyday Account" in out, "the next question was reached"
