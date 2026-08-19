"""The financial picture, composed from the read the tool registry answers.

Asks the tool registry the same balances question a conversation turn asks, and
turns what comes back into figures a person can read: the amount under this
vault's own conventions, the reviewed sentence for its grade, one line saying
where the figure's claim ends, and a route back to the record it was read from.

Nothing here decides a financial fact. The value, its grade, its date, the
records behind it and its boundary are all the read's; this module chooses the
words each of them is shown in, and keeps back any row it cannot show whole.
"""

from __future__ import annotations

from typing import Any

from .. import render
from ..persona import STOOD_BEHIND_MOMENT, load, moment
from ..tools import default_registry
from ..tools.boundary import SELECTED_TERMS, named_slice, said, statements
from ..tools.envelope import BY_ACCOUNT
from .models import Citation, CitationRelation, FigureGrade, FigureView, PanelState

# The family of wordings a figure standing on its own is said in. The lines a
# run places after a clause open with a word pointing back at what was just
# said; a figure beside the account it is about is read under nothing.
CARD = "card_"

# The read this surface makes: one unnarrowed call, whose result decides which
# accounts the picture holds.
BALANCES = ("query_ledger", {"entity": "balances"})

# Why a row can be shown without its figure. Each names a way a figure fails to
# be whole, and each has one reviewed sentence naming the account it is about.
WITHHELD_INCOMPLETE = "incomplete_figure"
WITHHELD_IN_PARTS = "figure_in_parts"
WITHHELD_UNSAYABLE = "boundary_not_sayable"

_WITHHELD_MOMENTS = {
    WITHHELD_INCOMPLETE: CARD + "withheld_incomplete",
    WITHHELD_IN_PARTS: CARD + "withheld_in_parts",
    WITHHELD_UNSAYABLE: CARD + "withheld_unsayable",
}

# How a document stands to the figure that cites it, by the grade the figure
# carries. A grade on the ladder says whether an issuer's own figure was read:
# where one was, the document attests the number; where none was, the number
# was replayed and the document it points at is another record of the same
# account.
_CITED_AS = {
    FigureGrade.VERIFIED: CitationRelation.ATTESTS,
    FigureGrade.CORROBORATED: CitationRelation.ATTESTS,
    FigureGrade.CONFLICTED: CitationRelation.ATTESTS,
    FigureGrade.UNVERIFIED: CitationRelation.SAME_ACCOUNT,
}


def overview(projection, locale: str = "", today: str = "") -> dict[str, Any]:
    """The reviewed financial picture over one projection, ready to render.

    A pure function of a projection and a locale: it opens nothing, writes
    nothing and knows nothing about how the payload travels."""
    result = default_registry(projection, locale, today).call(*BALANCES)
    accounts, issues = [], []
    if result.ok:
        known = {item["account"]: item for item in result.identifiers
                 if item.get("account")}
        by_account = _figures_by_account(result.figures)
        for row in result.data["balances"]:
            account, issue = _account(row, by_account.get(row["record_id"], []),
                                      known, locale)
            accounts.append(account)
            if issue is not None:
                issues.append(issue)
    return {
        # Ready only where every row carries a figure; any withheld figure
        # makes the panel partial.
        "state": (PanelState.PARTIAL if issues else PanelState.READY).value,
        "issues": issues,
        # What the read said about the set of numbers it took, kept at the
        # read's own level rather than placed on any one figure in it.
        "caveats": [_sentence(item) for item in (result.caveats or [])],
        "as_of": projection.as_of,
        "accounts": accounts,
        "account_count": len(accounts),
        "spending_by_currency": {currency: str(amount) for currency, amount
                                 in projection.spending_by_currency().items()},
    }


def _figures_by_account(figures) -> dict:
    """Every figure the read emitted, keyed by the account it declares.

    A figure naming no single account belongs to no row and is dropped."""
    out: dict = {}
    for fig in figures:
        account = _account_named(fig)
        if account:
            out.setdefault(account, []).append(fig)
    return out


def _account_named(fig: dict) -> str:
    """The one account a figure declares it was taken over, or "".

    Read from the figure's own boundary. Empty where the boundary names no
    account or more than one."""
    bound = fig.get("boundary") or {}
    named = {item["value"] for item
             in (bound.get("cut") or []) + (bound.get("selected") or [])
             if item["kind"] == BY_ACCOUNT}
    return named.pop() if len(named) == 1 else ""


def _account(row: dict, figures: list, known: dict,
             locale: str) -> tuple[dict, dict | None]:
    """One account row, with its figure where the figure can be shown whole.

    Returns ``(row, issue)``. The row is always returned; only the figure is
    withheld, and then the issue names the account and says why. ``issue`` is
    None where the figure was shown."""
    # Identity as the read established it: the account's names and the masked
    # form of its number, never the digits.
    entity = known.get(row["record_id"]) or {}
    identity = {
        "account": row["record_id"],
        "kind": row["kind"],
        "name": row["name"],
        "currency": entity.get("currency", ""),
        "number": entity.get("number_masked", ""),
    }
    code = _withheld(figures)
    if code is None:
        try:
            figure = _figure(row, figures[0], known, locale)
        except (ValueError, TypeError):
            # FigureView refuses to be built without identity, measure, date
            # and coverage; what it refuses is withheld rather than checked a
            # second time here.
            code = WITHHELD_INCOMPLETE
        else:
            return {**identity, "balance": figure.as_dict()}, None
    return {**identity, "balance": None}, {
        "code": code,
        "message": moment(_WITHHELD_MOMENTS[code],
                          account=named_slice({"kind": BY_ACCOUNT,
                                               "value": row["record_id"]},
                                              known)),
    }


def _withheld(figures: list) -> str | None:
    """One of the ``WITHHELD_*`` codes, or None where the figure can be shown.

    No figure and several figures are both rows with no single number, and are
    told apart: several is an account whose worth came back in parts."""
    if not figures:
        return WITHHELD_INCOMPLETE
    if len(figures) > 1:
        return WITHHELD_IN_PARTS
    if any(not _sayable(statement) for statement in _boundary(figures[0])):
        return WITHHELD_UNSAYABLE
    return None


def _figure(row: dict, fig: dict, known: dict, locale: str) -> FigureView:
    """One account's worth, as a figure already interpreted for a reader.

    Every fact in it is the read's; what is decided here is the words. The
    amount goes through the one writer of amounts under this vault's own
    conventions, and the grade's sentence is the whole reviewed line for the
    word the read chose. Raises where the read supplied too little to build a
    figure."""
    grade = FigureGrade(fig["grade"])
    return FigureView(
        id=row["record_id"],
        exact_value=str(fig["value"]),
        display=str(render.money(fig["value"], fig["currency"], locale=locale)),
        currency=fig["currency"] or None,
        measure=fig["quantity"],
        grade=grade,
        grade_label=grade.value,
        grade_description=moment(STOOD_BEHIND_MOMENT + grade.value),
        exactness=fig["exactness"],
        as_of=fig["dated"],
        coverage=_coverage(fig, known),
        record_ids=tuple(fig["record_ids"]),
        # Where the figure came from is said by the citation. The balances
        # view's own prose is not carried: it describes an account's balance,
        # not a figure composed of that balance and the holdings beside it.
        citations=_citations(row["record_id"], fig, grade),
        # No read-level caveat is placed on a single figure: what the read
        # wrote is about the set it took, not about this account.
        caveats=(),
    )


def _boundary(fig: dict) -> list:
    """Where this figure's claim ends, as the statements a card says it in.

    The account the figure is over is stated first and always, whether or not
    the read declared a shortfall. Anything further the read declared follows
    it, once each."""
    declared, _left_out = statements(fig)
    account = (SELECTED_TERMS[BY_ACCOUNT][0],
               {"kind": BY_ACCOUNT, "value": _account_named(fig)})
    return [account] + [item for item in declared if item != account]


def _sayable(statement) -> bool:
    """Whether the card family has a reviewed line for this statement."""
    return CARD + statement[0] in load()["moments"]


def _coverage(fig: dict, known: dict) -> str:
    """What this figure is over, and what day it is good for.

    Composed from the boundary the read declared and the figure's own date. It
    says nothing about how many other accounts a person holds, which is a fact
    about the vault rather than about this number."""
    lines = [said(statement, known, family=CARD)
             for statement in _boundary(fig)]
    lines.append(moment(CARD + "boundary_as_of",
                        day=render.date(fig["dated"])))
    return " ".join(lines)


def _citations(account: str, fig: dict, grade: FigureGrade) -> tuple[Citation, ...]:
    """The route from this figure back to the records it stands on.

    One citation per document the figure declares, the account's own record id
    excluded. No page is claimed: a composed figure stands on parts and the
    read records the page of one part only. A figure whose read recorded no
    document gets no citations rather than one that would not open."""
    return tuple(Citation(document_id=document, relation=_CITED_AS[grade])
                 for document in fig["record_ids"]
                 if document and document != account)


def _sentence(caveat) -> str:
    """One caveat as its words, whether it arrived as a sentence or as a
    mapping carrying that sentence under an identity."""
    return str(caveat.get("text", "") if isinstance(caveat, dict) else caveat)
