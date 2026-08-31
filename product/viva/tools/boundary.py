"""Where a figure's claim ends, and how that is said.

A figure declares what set it was taken over; this module turns that
declaration into statements, and each statement into the pack's words. Both
halves are pure functions of a figure and of the accounts a caller already
holds, so a run stating a number in a sentence and a surface rendering the same
number on a card say one thing about its boundary rather than two.

The accounts are handed in as a mapping from an account's ledger path to what
is known about it. It is what an account is written from, so an account named
in a boundary is named the way everything else names it, and the caller decides
where that knowledge comes from — the entities a run established, or the
identifiers a read returned.
"""

from __future__ import annotations

from .. import render
from ..persona import moment
from .envelope import (BY_ACCOUNT, BY_CATEGORY, BY_CURRENCY, BY_KIND, BY_MERCHANT,
                       BY_PERIOD, BY_SINCE, BY_SUBCATEGORY, BY_TAG, BY_UNTIL)

# How each way of narrowing a set is said: the pack's line for it, the name
# that line places it by, and how the thing becomes words. One entry per member
# of the vocabulary, so a way of narrowing with nowhere to say what it selected
# is a build failure rather than a figure that reaches a person looking like a
# total.
SELECTED_TERMS = {
    BY_ACCOUNT: ("boundary_selected_account", "account",
                 lambda item, accounts: account_written(item["value"],
                                                        accounts)),
    BY_CATEGORY: ("boundary_selected_category", "category",
                  lambda item, accounts: render.category(item["value"])),
    BY_MERCHANT: ("boundary_selected_merchant", "merchant",
                  lambda item, accounts: render.merchant({"key": item["value"]})),
    BY_PERIOD: ("boundary_selected_period", "period",
                lambda item, accounts: render.period(item["value"], item["to"])),
    BY_SINCE: ("boundary_selected_since", "day",
               lambda item, accounts: render.date(item["value"])),
    BY_UNTIL: ("boundary_selected_until", "day",
               lambda item, accounts: render.date(item["value"])),
    # The three the vault holds no thing for. Each is written as the label it is
    # held under, which says what a figure's scope is and offers nothing to ask
    # a follow-up with.
    BY_SUBCATEGORY: ("boundary_selected_subcategory", "subcategory",
                     lambda item, accounts: render.label(item["value"])),
    BY_TAG: ("boundary_selected_tag", "tag",
             lambda item, accounts: render.label(item["value"])),
    BY_CURRENCY: ("boundary_selected_currency", "currency",
                  lambda item, accounts: render.label(item["value"])),
    BY_KIND: ("boundary_selected_kind", "kind",
              lambda item, accounts: render.label(item["value"])),
}

# The statement a figure makes about documents read and not posted, which no
# account names.
UNPOSTED = "boundary_unposted"


def known_account(path: str, accounts) -> dict:
    """One account as the caller already holds it, or as its path alone gives
    it.

    An account something already spoke about carries the name a person is shown
    everywhere else, so the name in a boundary is the name in the sentence.

    The held entry itself is returned rather than a copy of it, because what
    tells one account apart from the others written beside it is that it is the
    same object as one of them.
    """
    known = accounts.get(path)
    return known if known is not None else {"account": path}


def account_written(path: str, accounts) -> render.Account:
    """One account, written among the others of its kind the caller holds, so
    two accounts are never written identically."""
    company = list(accounts.values())
    known = known_account(path, accounts)
    return render.account(known, among=company or [known])


def accounts_written(paths, accounts) -> render.Account:
    """Several accounts in one place, each told apart from the others beside
    it."""
    return render.accounts([known_account(path, accounts) for path in paths])


def named_slice(item: dict, accounts):
    """What one cut of a set is written as: the thing it was cut to, in
    whichever form that kind of thing is written in. The same writer the
    sentence about a boundary uses, so a slice named beside a number and a
    slice named in a scope clause are never written two ways."""
    return SELECTED_TERMS[item["kind"]][2](item, accounts)


def statements(fig: dict, *, cut: bool = True) -> tuple[list, list]:
    """Return ``(boundary statements, unmeasured account ids)`` for a figure.

    Whole figures omit selection and cut statements but retain evidence-gap
    disclosures. Set ``cut=False`` when a row already displays its own slice.
    """
    bound = fig.get("boundary") or {}
    whole = bound.get("whole", False)
    said = []

    def say(statement):
        # A figure's cuts include what narrowed its read, so the two halves
        # name some of the same slices. One slice is one sentence.
        if statement not in said:
            said.append(statement)

    if not whole:
        for item in bound.get("selected") or []:
            say((SELECTED_TERMS[item["kind"]][0], dict(item)))
        if cut:
            for item in bound.get("cut") or []:
                say((SELECTED_TERMS[item["kind"]][0], dict(item)))
    if bound.get("unposted"):
        # A gap no account names is still said. It is a number of documents,
        # because a document read and not posted may be about an account that
        # does not exist yet and there is nothing else to call it.
        say((UNPOSTED, {"count": bound["unposted"]}))
    return said, [item["account"] for item in bound.get("unmeasured") or []]


def said(statement, accounts, *, family: str = "") -> str:
    """One statement about how a set was narrowed, in the pack's words.

    ``family`` names which set of wordings says it. The empty family is the one
    a sentence following a clause is written in; a surface that places the same
    statement somewhere else asks for its own, and the two say one thing about
    the same declaration in the register each is read in."""
    key, fields = statement
    if key == UNPOSTED:
        return moment(family + key, count=render.count(fields["count"]))
    _key, name, written = SELECTED_TERMS[fields["kind"]]
    return moment(family + key, **{name: written(fields, accounts)})
