"""Viva asks you, at a terminal: the question queue, one question at a time.

The mirror of `viva.speak`, which is you asking Viva. Both are a person at a
terminal reaching the same engine — here the question direction's, so a question
is shown with what it wants back, a line is read, and the engine records what
the answer turns out to be.

Usage (from product/, auto-loads ./.env for VIVA_PASSPHRASE / VIVA_VAULT_DIR):

    PYTHONPATH=../core:../merchant:. python3 -m viva.ask           # answer them
    PYTHONPATH=../core:../merchant:. python3 -m viva.ask --list     # top 10
    PYTHONPATH=../core:../merchant:. python3 -m viva.ask --list 25  # top 25

A bare number sets how many questions are held in view at once. `--list` prints
the queue and writes nothing, which is what this module has always done; without
it each question is asked in turn and a blank line ends the sitting.

The queue is read again after every answer, so a ruling that settles a dozen
questions takes them all off the list before the next one is asked. A reply Viva
could not read leaves its question where it was and she asks it again; a
question that survives that is left for another sitting rather than standing
between a person and the rest of their list.

An answer that would bring an account into being does not write. It comes back
as a proposal — what Viva would record, said before anything is — and it waits
for an explicit yes. That yes is a question like any other: it declares the slot
it wants, and the reply travels the same path every other answer does. Nothing
is recorded unless a reply reads as a yes, so a no, an unreadable reply and a
person who walks away all leave the ledger exactly as it was.

Every sentence a person reads here comes from the persona pack, including what a
question wants back and what became of an answer. Nothing is written except
through the engine's one door.
"""

from __future__ import annotations

import os
import pathlib
import sys

from .env import load_dotenv, locale_from_env
from .logs import configure as configure_logging
from .persona import moment
from .render import money

# How many times one question is put to a person in a sitting: put once, and put
# once more. Viva's own answer to a reply she could not read is to ask again, so
# the question comes back — and then the queue moves on, because a question
# nothing can settle must not stand between a person and the rest of the list.
# It is one retry on the person's side of the door, the same shape of budget
# `reply.MAX_RETRIES` spends on the model before anyone is troubled at all. It
# bounds a confirmation the same way it bounds a question, because a
# confirmation is a question.
ASKED_AT_MOST = 2


def wants(slot: dict) -> str:
    """What one declared slot wants back, in Viva's words.

    The pack entry is keyed by the slot's own declared type, so a type that
    gains a parser gains its sentence in the pack rather than a branch here. A
    slot that holds several of something declares no scalar type and takes the
    compound line."""
    if slot.get("parts"):
        return moment("wants_several")
    return moment(f"wants_{slot['type']}",
                  alternatives=", ".join(str(c) for c in slot.get("choices", ())))


def print_question(q: dict, remaining: int, invite: str,
                   answered_by_document: str) -> None:
    """One question: what it moves, what it settles, what is being asked, the
    evidence under it, and what an answer to it is made of."""
    stake = money(q["amount"], q["currency"], locale=locale_from_env())
    scope = ("settles this one" if q["scope"] == "one"
             else f"settles all {q['count']} — and future ones")
    print()
    print(f"[{remaining} open]  {stake}   ({scope})")
    print(f"Viva: {q['text']}")
    print(f"  why: {q['why']}")
    if not q["slots"]:
        print(f"  {answered_by_document}")
        return
    for slot in q["slots"]:
        print(f"  {wants(slot)}")
    print(f"  {invite}")


def print_outcome(outcome: dict) -> None:
    """What became of one answer, in Viva's words.

    A refusal already carries the sentence she would say to the person; what is
    added here is what she says when something WAS recorded."""
    said = outcome.get("message") or (
        moment("reply_recorded") if outcome.get("ok") else moment("reply_ask_again"))
    print(f"Viva: {said}")


def confirm_text() -> str:
    """What Viva says while a proposal waits: that nothing is recorded yet, and
    what she is asking for. Two reviewed lines from the pack, placed side by
    side — neither of them written here."""
    return f"{moment('reply_needs_confirming')} {moment('reply_confirm_asks')}"


def print_proposal(proposal: dict, slot: dict, invite: str) -> None:
    """What Viva proposes: what would be recorded and what would come into
    being, that none of it has happened yet, and what an answer to it is made
    of — the same declaration the check behind the model reads."""
    print()
    print(f"Viva: {proposal.get('summary', '')}")
    print(f"Viva: {confirm_text()}")
    print(f"  {wants(slot)}")
    print(f"  {invite}")


def confirm(vault, proposal: dict, invite: str, read_line) -> dict | None:
    """The second half of one answer: what Viva proposes, then the yes or no.

    An answer that would change which accounts a person holds comes back as a
    proposal rather than a write, and the proposal is transient — it lives for
    the length of this exchange and is never itself recorded. So a no, a reply
    that reads as neither, and a person who walks away all leave the ledger
    exactly as it was.

    The confirmation is a question like any other: it declares the slot it
    wants, and the reply goes through the same path every other answer takes.
    Nothing here reads the letters a person typed, so a yes written as a
    sentence lands where a bare word does. What reads as neither is put again,
    once, and then the sitting moves on.

    Returns what became of the proposal, or None when the person ended the
    sitting without answering."""
    from .engine import CONFIRM_SLOT, confirm_proposal
    asked = " ".join(part for part in (proposal.get("summary", ""),
                                       confirm_text()) if part)
    outcome: dict = {}
    for attempt in range(ASKED_AT_MOST):
        print_proposal(proposal, CONFIRM_SLOT.to_dict(), invite)
        try:
            said = read_line("you: ").strip()
        except EOFError:
            return None
        if not said:
            return None
        outcome = confirm_proposal(vault, proposal, said, asked=asked)
        if outcome.get("ok"):
            return outcome
        if attempt + 1 < ASKED_AT_MOST:
            print_outcome(outcome)
    return outcome


def main() -> None:
    load_dotenv()
    configure_logging()
    from .questions import DEFAULT_LIMIT
    from .vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    limit = next((int(a) for a in sys.argv[1:] if a.isdigit()), DEFAULT_LIMIT)

    vault = Vault.open(vault_dir, passphrase)
    run(vault, limit=limit, listing="--list" in sys.argv)


def run(vault, limit: int, listing: bool = False, read_line=input) -> None:
    """The sitting itself: show the top question, read a line, record it, and
    read the queue again. Ends when nothing is left, when nothing further can be
    asked, or on a blank line.

    A reply Viva could not read leaves the question where it was, so the one she
    just asked again is the one asked again — but only once, so a question
    nothing can settle cannot hold up the rest of the queue.

    An answer the engine hands back as a proposal is not the end of the turn:
    the exchange that confirms it runs here, and only what it returns is the
    outcome of the answer."""
    from .engine import answer_question
    from .questions import open_questions

    tries: dict = {}
    result = open_questions(vault.ledger, limit=limit)
    if not result["total"]:
        print(moment("all_settled", name_part=""))
        return
    print(f"{result['total']} thing(s) need you. The ones that move the most "
          "money first:")
    while True:
        result = open_questions(vault.ledger, limit=limit)
        left = [q for q in result["questions"]
                if tries.get(q["id"], 0) < ASKED_AT_MOST]
        if not left:
            break
        q = left[0]
        print_question(q, result["total"], result["invite"],
                       result["answered_by_document"])
        if listing or not q["slots"]:
            # A listing answers nothing, and a question only a document settles
            # has nothing to type at.
            tries[q["id"]] = ASKED_AT_MOST
            continue
        try:
            said = read_line("you: ").strip()
        except EOFError:
            break
        if not said:
            break
        outcome = answer_question(vault, q["id"], said)
        if outcome.get("confirm") and outcome.get("proposal"):
            # An answer that would bring an account into being waits for an
            # explicit yes, and the yes is asked for the way everything else is.
            settled = confirm(vault, outcome["proposal"], result["invite"],
                              read_line)
            if settled is None:
                break
            outcome = settled
        print_outcome(outcome)
        tries[q["id"]] = (ASKED_AT_MOST if outcome.get("ok")
                          else tries.get(q["id"], 0) + 1)

    tail = result["tail"]
    if tail["count"]:
        # No currency: the tail's total spans every question below the fold,
        # whatever each one is held in, so naming one would be inventing it.
        print(f"\n...plus {tail['count']} smaller item(s) worth "
              f"{money(tail['amount'], locale=locale_from_env())} in total. "
              "Run with a bigger number to see them.")


if __name__ == "__main__":
    main()
