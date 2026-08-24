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

from .. import quantity, render
from ..persona import STOOD_BEHIND_MOMENT, load, moment
from ..tools import default_registry
from ..tools.boundary import (SELECTED_TERMS, UNPOSTED, account_written,
                              named_slice, said, statements)
from ..ledger.projection.movements import leading_account
from ..tools.envelope import BY_ACCOUNT, BY_CURRENCY, GAP_REASONS
from .models import Citation, CitationRelation, FigureGrade, FigureView, PanelState
from .proof import freshness_confirmed_on, proof_presentation_from_evidence

# The family of wordings a figure standing on its own is said in. The lines a
# run places after a clause open with a word pointing back at what was just
# said; a figure beside the account it is about is read under nothing.
CARD = "card_"

# And the family a figure standing for the whole picture is said in. A total is
# read above the accounts it was taken over rather than beside any one of them,
# so it says how far it reaches as counts and names nothing — the names are
# already on the cards below it, and a list of them is the one thing on this
# screen a person cannot un-share.
PICTURE = "picture_"

# The two reads this surface makes, both through the registry a conversation
# asks. The first decides which accounts the picture holds; the second is the
# point a conversation would be told, so the number on the card and the number
# in an answer are one figure with one boundary rather than two.
#
# Which family a figure is said in is decided by which of these calls it came
# back from, never by what its boundary happens to name.
BALANCES = ("query_ledger", {"entity": "balances"})
NET_WORTH = ("query_ledger", {"entity": "aggregate", "metric": "net_worth"})

# The further things a read declares that the picture says in its own register.
# The accounts a read could not value come back from ``statements()`` apart from
# the rest, so a composer reading only what it returns first would leave out
# exactly the accounts these lines exist to disclose. The last two are the
# picture's own: the day the total is good for, and how old the oldest
# measurement under it is.
UNMEASURED = "boundary_unmeasured"

# How a gap is said, by where it landed. An account beneath a figure is named
# on that figure; an account beneath none is named at the panel, which is where
# beneath-nothing lands. Both are the same declaration said in the register of
# the place it is read.
BENEATH_A_FIGURE = "unmeasured_"
BENEATH_NOTHING = "unplaced_"
AS_OF = "as_of"
OLDEST = "oldest_input"

# Which of them the picture says as a number. Each has two whole reviewed
# sentences and the number chooses between them, because a single sentence with
# a count dropped into it is a frame rather than a line anybody reviewed.
_COUNTED = (UNMEASURED, UNPOSTED)

# The one order the picture says its lines in, whatever order a read declared
# them: what the total was cut to, what it could not value, what is not counted
# in it, the day it is good for, the oldest measurement beneath it. It is also
# the whole of what the picture can say, so a declaration with no place here is
# one the surface cannot say and the figure carrying it is kept back.
_PICTURE_ORDER = (SELECTED_TERMS[BY_CURRENCY][0], UNMEASURED, UNPOSTED,
                  AS_OF, OLDEST)

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


def overview(projection, locale: str, today: str) -> dict[str, Any]:
    """The reviewed financial picture over one projection, ready to render.

    A pure function of a projection, a locale and a day: it opens nothing,
    writes nothing, reads no clock and knows nothing about how the payload
    travels.

    ``today`` is the day the picture is read on, and it has no default. A
    balance carries forward, so a total is good on the day it was asked for and
    says so — and a day nobody stated would be read off whichever machine ran
    the composer, one call further down, where nothing would notice. The day is
    given once, at the boundary that has a clock, and is never derived again.
    An empty day is a day nobody stated, and is refused the same way a missing
    one is: a signature that cannot be called without an argument and a body
    that accepts any argument are one hole with two names."""
    if not today:
        raise ValueError(
            "a picture is good as of the day it was read on, and no day was "
            "stated; the day is given where a clock is, and a read told none "
            "would date its figures by whichever machine composed them")
    registry = default_registry(projection, locale, today)
    # Both reads are made here, so what the panel says about the set of numbers
    # it took can be said over every read it took them from. A caveat gathered
    # from one of two reads is not this read's caveats; it is that read's, under
    # a name claiming both.
    result = registry.call(*BALANCES)
    aggregate = registry.call(*NET_WORTH)
    accounts, issues = [], []
    known = _known(result) if result.ok else {}
    if result.ok:
        by_account = _figures_by_account(result.figures)
        for row in result.data["balances"]:
            account, issue = _account(
                row, by_account.get(row["record_id"], []), known, locale,
                today, tuple(result.caveats or ()),
                _account_mixed_vintage(projection, row["record_id"]))
            accounts.append(account)
            if issue is not None:
                issues.append(issue)
    # Include every real account in the picture. An account with no observed
    # stock value carries its identity with no monetary figure, including when
    # every account is unmeasured.
    shown = {row["account"] for row in accounts}
    for info in projection.account_infos():
        if info.kind not in ("depository", "liability", "investment"):
            continue
        if info.account in shown:
            continue
        known[info.account] = {
            "account": info.account,
            "currency": info.currency,
            "number_masked": "",
        }
        account, issue = _account(
            {"record_id": info.account, "kind": info.kind,
             "name": info.name}, [], known, locale, today,
            tuple(result.caveats or ()), None)
        accounts.append(account)
        if issue is not None:
            issues.append(issue)
    return {
        # Ready only where every row carries a figure; any withheld figure
        # makes the panel partial.
        "state": (PanelState.PARTIAL if issues else PanelState.READY).value,
        "issues": issues,
        # What the reads said about the sets of numbers they took, kept at the
        # reads' own level rather than placed on any one figure in them. Every
        # read this composer made is gathered, in the order it was made: a
        # machine that holds a caveat and does not place it has kept back a
        # property of a figure it was handed.
        #
        # Nothing merges two of them. Two reads declaring the same words say it
        # of two different sets, and folding them into one line would assert
        # they are one claim.
        "caveats": [_sentence(item) for read in (result, aggregate)
                    for item in (read.caveats or [])],
        "as_of": projection.as_of,
        "accounts": accounts,
        "account_count": len(accounts),
        "spending_by_currency": {currency: str(amount) for currency, amount
                                 in projection.spending_by_currency().items()},
        # And the picture as one thing: what it covers, what day it is good
        # for, and one figure per currency. Nothing adds them together — there
        # is no rate with a source, a date and a grade of its own, so a total
        # across currencies would be a figure no record attests.
        # The accounts the balances read named travel with it: an account the
        # point could not value is named in the picture and is, by definition,
        # not among the accounts that read named, so without them it would be
        # written from its ledger path rather than from what it is called.
        "picture": _picture(aggregate, locale, today, _known(result),
                            _vault_accounts(projection, _known(result))),
    }


def _vault_accounts(projection, named: dict) -> set:
    """Every account this vault holds, from both places one can be declared.

    A read names the accounts it could take a figure over. A ruling brings an
    account into being by naming it on a leg — and one nothing has yet been
    posted to reaches no read at all, because every read that would find it
    finds it through the movements it has none of.

    Which account a ruling brings into being is the ledger's own question and
    is answered by the ledger's own function, so this holds no second opinion
    about which legs name a thing a person holds."""
    ruled = {leading_account(ruling.get("legs") or [])
             for ruling in projection.rulings()}
    return set(named) | (ruled - {""})


def _known(result) -> dict:
    """The accounts a read named, keyed by the path everything else holds them
    under. An account written from what a read knows about it is written the
    way a person is shown it everywhere else."""
    return {item["account"]: item for item in result.identifiers
            if item.get("account")}


def _figures_by_account(figures) -> dict:
    """Every figure the read emitted, keyed by the account it declares.

    A figure naming no single account belongs to no row and is dropped."""
    out: dict = {}
    for fig in figures:
        account = _account_named(fig)
        if account:
            out.setdefault(account, []).append(fig)
    return out


def _account_mixed_vintage(projection, account: str) -> bool | None:
    """The projection's structured vintage fact for one account figure."""
    values = tuple(projection.composed_values(account))
    if not values:
        return None
    return any(value.mixed_vintage for value in values)


def _account_named(fig: dict) -> str:
    """The one account a figure declares it was taken over, or "".

    Read from the figure's own boundary. Empty where the boundary names no
    account or more than one."""
    bound = fig.get("boundary") or {}
    named = {item["value"] for item
             in (bound.get("cut") or []) + (bound.get("selected") or [])
             if item["kind"] == BY_ACCOUNT}
    return named.pop() if len(named) == 1 else ""


def _account(row: dict, figures: list, known: dict, locale: str,
             read_on: str, read_caveats: tuple,
             mixed_vintage: bool | None) -> tuple[dict, dict | None]:
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
            figure = _figure(row, figures[0], known, locale, read_on,
                             read_caveats, mixed_vintage)
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


def _figure(row: dict, fig: dict, known: dict, locale: str, read_on: str,
            read_caveats: tuple, mixed_vintage: bool | None) -> FigureView:
    """One account's worth, as a figure already interpreted for a reader.

    Every fact in it is the read's; what is decided here is the words. The
    amount goes through the one writer of amounts under this vault's own
    conventions, and the grade's sentence is the whole reviewed line for the
    word the read chose. Raises where the read supplied too little to build a
    figure."""
    grade = FigureGrade(fig["grade"])
    written = render.money(fig["value"], fig["currency"], locale=locale)
    grade_description = moment(STOOD_BEHIND_MOMENT + grade.value)
    coverage = _coverage(fig, known)
    return FigureView(
        id=row["record_id"],
        exact_value=str(fig["value"]),
        display=str(written),
        currency=fig["currency"] or None,
        measure=fig["quantity"],
        grade=grade,
        grade_label=grade.value,
        grade_description=grade_description,
        exactness=fig["exactness"],
        as_of=fig["dated"],
        coverage=coverage,
        proof_presentation=proof_presentation_from_evidence(
            grade=grade,
            exactness=fig.get("exactness"),
            boundary=fig.get("boundary"),
            record_ids=fig.get("record_ids"),
            caveats=read_caveats,
            freshness_confirmed=freshness_confirmed_on(
                (str(fig.get("dated", "")),), read_on),
            mixed_vintage=mixed_vintage,
            grade_qualification=grade_description,
            inexact_qualification=moment("proof_inexact"),
            missing_evidence_qualification=moment("proof_missing_evidence"),
            stale_qualification=moment("proof_stale_boundary"),
            mixed_vintage_qualification=moment("proof_mixed_vintage"),
            boundary_qualifications=(coverage,)),
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


# ------------------------------------------------------------- the picture


def _picture(result, locale: str, today: str, held: dict,
             vault_accounts: set) -> dict[str, Any]:
    """The whole picture over one read of the net-worth point.

    The coverage sentence is composed whether or not a figure could be stood
    behind, because it is a sentence about the picture rather than about any
    figure in it. A screen that has gone blank says nothing at all, which a
    person reads as the product being broken — a worse and less true thing
    than saying there is nothing to stand behind today.

    Every figure here is said in the picture's own family because it came back
    from this call, and for no other reason."""
    if not result.ok:
        # A read this call cannot make fail, kept honest rather than kept
        # explained. What a refusal carries is the tool's own machinery words,
        # and there is no reviewed sentence for a branch nothing can enter —
        # so the panel says the one thing it can stand behind, which is that
        # there is no total today, and says nothing it did not review.
        return {"coverage": moment(PICTURE + "no_figure"), "read_on": today,
                "figures": [], "withheld": [], "unplaced": []}

    point = result.data["point"]
    known = {**held, **_known(result)}
    held_in = _held_in(point, known)
    # Every gap the read declared, once. The same account is declared on every
    # currency's figure, so it is gathered by account rather than by figure or
    # it would be named as many times as a person holds currencies.
    declared_gaps: dict = {}
    figures, withheld = [], []
    for fig in result.figures:
        if fig["quantity"] == quantity.NET_WORTH:
            for row in (fig.get("boundary") or {}).get("unmeasured") or []:
                declared_gaps.setdefault(str(row["account"]), row)
    for fig in result.figures:
        # One figure per currency, and only what the picture is: what is held
        # and what is owed are two further parts of the same point, and neither
        # has a screen. The read emits them in currency order and both lists
        # below keep it.
        if fig["quantity"] != quantity.NET_WORTH:
            continue
        view = _picture_figure(fig, point, held_in, known, locale, today,
                               tuple(result.caveats or ()))
        if view is None:
            # A currency whose total was kept back is said. A person shown
            # fewer totals than they hold currencies, with nothing beside them,
            # is not told that one was withheld — they learn there was never
            # one, which is the thing that did not happen.
            if fig["currency"]:
                withheld.append({
                    # The currency rides beside the sentence it was written
                    # from. The composer already holds it — that is how the
                    # sentence got written — and carrying it closes the one
                    # door by which a surface could come to learn which
                    # currency was kept back: reading the words back.
                    "currency": fig["currency"],
                    "sentence": moment(PICTURE + "withheld_unsayable",
                                       currency=render.label(fig["currency"])),
                })
            continue
        figures.append(view)
    return {
        # Composed last, over the figures above, because what the panel says is
        # counted has to be counted off what the panel shows.
        "coverage": _covers(point, figures, vault_accounts),
        # The day the read was made, which is what the total is good for. It
        # is not the horizon the projection was cut at, and the two are not one
        # field wearing two meanings. It is the value this read was given,
        # carried through unchanged — reading it back off the point would make
        # it a derivation, and a derivation can drift from what was asked for
        # while still looking like a record of it.
        #
        # How old the evidence beneath the picture is rides on each figure, in
        # words, because it is true of one currency's part of a point and not
        # of the point as a whole.
        "read_on": today,
        "figures": figures,
        "withheld": withheld,
        # And the accounts beneath no figure, named here because there is
        # nowhere else they appear. Nothing is taken off any figure's boundary
        # to put them here: these are the ones no figure could carry.
        "unplaced": _unmeasured(_unplaced(list(declared_gaps.values()), held_in),
                                known, BENEATH_NOTHING),
    }


def _announced(currency: str) -> dict[str, str]:
    """What the control that opens this figure's evidence is called, and what
    the panel it opens is headed.

    One total per currency is one control per currency. Two controls announcing
    the same words conflate two figures nothing may relate — at the moment a
    person acts on one of them, and only for the person who cannot see which
    card it sits on. The slice the figure was cut to is the whole of what tells
    them apart, and it is written by the one writer of that kind of thing.

    Merged onto the emitted figure rather than declared on the model behind it.
    A figure's fields are what the surface contract is built from, and these are
    the words of one surface's control rather than a property of the figure.
    """
    slice_of = render.label(currency)
    return {
        "evidence_label": moment(PICTURE + "evidence_label",
                                 currency=slice_of),
        "evidence_heading": moment(PICTURE + "evidence_heading",
                                   currency=slice_of),
    }


def _covers(point: dict, figures: list, vault_accounts: set) -> str:
    """The one sentence the panel says about how far the picture reaches.

    It is said of the picture and never of a total. Where a person holds money
    in two currencies they meet two totals and no third, so a line opening
    "this total" would name either a figure nothing may compose or one of the
    two, of which it is false. What is true at one currency and at four is how
    much of what they hold is counted here.

    Counts, and names nothing. The claim belongs here, over every figure the
    picture stated, because a count said once about one figure reads as being
    about the whole of it.

    **What is counted is counted off the figures this panel renders**, never
    off the read behind them. A total that was kept back is not on the screen,
    and a sentence computed over the read would say a person's accounts were
    all counted here while the currency holding some of them is absent — true
    of the read, false of the thing a person is looking at. What they are held
    against is every account the read ranged over, which is what a person
    holds; neither number is a tally this surface made and neither comes from
    the balances read.

    Whole reviewed sentences, chosen by comparing two numbers and by the
    boolean the read declares about itself: a verb agreeing with a count would
    otherwise be a word dropped into a frame. Saying nothing where every
    account is counted would leave silence standing for completeness, which is
    the one thing silence never means.

    **And where every account is counted, the sentence still says whether
    anything else is missing.** This sentence answers how many accounts; a
    person reads it as whether this is everything. Standing "every account you
    hold is counted here" over a read that declares itself short of something —
    a document read and not posted, a side it could not place — is false in the
    way the sentence is actually read, whatever it is true of.

    It resolves itself rather than handing off. What else is short of whole is
    said on a figure, and a figure is a different card and may be one of
    several, so a sentence relying on the line after it relies on a layout it
    cannot see."""
    if not figures:
        return moment(PICTURE + "no_figure")
    counted, held = _reach(point, figures, vault_accounts)
    if counted == held:
        # The read's own declared boolean, never anything read off a sentence.
        # Absent, it is not a claim of completeness: silence is not wholeness
        # here any more than anywhere else on this surface.
        return moment(PICTURE + ("accounts_all"
                                 if point.get("complete") is True
                                 else "accounts_all_incomplete"))
    if counted == 1:
        return moment(PICTURE + "accounts_one", held=render.count(held))
    return moment(PICTURE + "accounts_some",
                  counted=render.count(counted), held=render.count(held))


def _reach(point: dict, figures: list,
           vault_accounts: set) -> tuple[int, int]:
    """How many accounts the panel counts, against how many a person holds.

    The numerator is read off the figures the panel renders — the accounts
    those figures declare they stand on — so it cannot say more than what is
    on the screen. A figure kept back takes its accounts out of the count by
    not being there, which is the only way a count and a screen stay in step
    without either being told about the other.

    The denominator is the union of two declared sets: every account the read
    ranged over — those that contributed a line, those it refused a figure for,
    and those it has never seen a balance of — and every account the vault
    holds. Neither alone is authority for this claim. **The point is
    authoritative about what it valued and is not authoritative about what is
    held:** an account a ruling brought into being that nothing has yet been
    posted to is in no line, no refusal and no skip, so a denominator taking
    the point's word for it would report a person's whole picture as covered
    while something they hold sat outside it, with nothing red.

    One account counted once however many of the two sets hold it, and the
    number does not shrink because a figure could not be shown."""
    counted = {str(account) for figure in figures
               for account in figure["record_ids"] if account}
    held = {str(line.get("account", ""))
            for line in (point.get("lines") or []) if line.get("account")}
    held |= {str(row.get("account", "")) for row
             in (point.get("missing") or []) + (point.get("skipped") or [])
             if row.get("account")}
    held |= {str(account) for account in vault_accounts if account}
    return len(counted), len(held)


def _picture_figure(fig: dict, point: dict, held_in: dict, known: dict,
                    locale: str, read_on: str,
                    result_caveats: tuple) -> dict | None:
    """One currency's part of the picture, ready to render, or None.

    None is where it is kept back: a figure whose boundary this surface has no
    reviewed line for is withheld rather than shown, because a number whose
    scope nothing states reads as a claim about everything and a refusal beats
    a wrong number.

    Everything the emitted figure carries is assembled here, where what is
    beneath it has been decided once."""
    declared, _left_out = statements(fig)
    # What this figure could not value, decided once and used everywhere it is
    # spoken of: the sentence that counts them, the entries that name them, and
    # the check that would keep the figure back if either could not be said.
    # Two places deciding it is how a card came to count one and list another.
    unmeasured = _beneath((fig.get("boundary") or {}).get("unmeasured") or [],
                          fig["currency"], held_in)
    if any(not _picture_sayable(term) for term, _fields in declared):
        return None
    if unmeasured and not _picture_sayable(UNMEASURED):
        return None
    grade = FigureGrade(fig["grade"])
    beneath = _beneath(point.get("lines") or [], fig["currency"], held_in)
    lines = _picture_coverage(fig, declared, unmeasured, beneath, known)
    written = render.money(fig["value"], fig["currency"], locale=locale)
    grade_description = moment(STOOD_BEHIND_MOMENT + grade.value)
    try:
        view = FigureView(
            # One figure per currency, so the currency is what tells them
            # apart on this surface.
            id=fig["currency"],
            exact_value=str(fig["value"]),
            display=str(written),
            currency=fig["currency"] or None,
            measure=fig["quantity"],
            grade=grade,
            grade_label=grade.value,
            grade_description=grade_description,
            exactness=fig["exactness"],
            as_of=fig["dated"],
            # The model holds one sentence; what is emitted is the ordered
            # list below. Joining here is what keeps the model's own refusal to
            # be built without a coverage line doing its work.
            coverage=" ".join(lines),
            proof_presentation=proof_presentation_from_evidence(
                grade=grade,
                exactness=fig.get("exactness"),
                boundary=fig.get("boundary"),
                record_ids=fig.get("record_ids"),
                caveats=tuple(result_caveats),
                freshness_confirmed=freshness_confirmed_on(
                    tuple(str(row.get("as_of", "")) for row in beneath),
                    read_on),
                mixed_vintage=_picture_mixed_vintage(beneath),
                grade_qualification=grade_description,
                inexact_qualification=moment("proof_inexact"),
                missing_evidence_qualification=moment(
                    "proof_missing_evidence"),
                stale_qualification=moment("proof_stale_boundary"),
                mixed_vintage_qualification=moment("proof_mixed_vintage"),
                boundary_qualifications=tuple(lines)),
            record_ids=tuple(sorted({row["account"] for row in beneath})),
            citations=_picture_citations(beneath, grade),
            # A caveat is about the set the read took, not about this
            # currency's part of it.
            caveats=(),
        )
    except (ValueError, TypeError):
        # FigureView refuses to be built without identity, measure, date and
        # coverage; what it refuses is kept back rather than checked twice.
        return None
    return {
        **view.as_dict(),
        # Laid out one sentence to a line rather than one paragraph, so a
        # surface that wants them stacked never has to find the joins by
        # looking for punctuation.
        "coverage": lines,
        # The boundary the read declared, carried through unaltered. It is what
        # names the accounts this total could not value, and the panel sentence
        # counts them precisely because this says who they are: the point names
        # and the sentence counts, and dropping this half would leave the
        # counting with nothing to stand on.
        "boundary": fig["boundary"],
        # Naming them is half of what is owed. A person looking at a card with
        # a number on it that this total does not include needs to know whether
        # anything is theirs to do, and only the reason says.
        "unmeasured": _unmeasured(unmeasured, known),
        **_announced(fig["currency"]),
    }


def _picture_mixed_vintage(beneath: list[dict]) -> bool | None:
    """Read the net-worth point's closed per-line vintage flags."""
    flags = tuple(row.get("mixed_vintage") for row in beneath)
    if not flags or any(not isinstance(flag, bool) for flag in flags):
        return None
    return any(flags)


def _picture_coverage(fig: dict, declared: list, unmeasured: list,
                      beneath: list, known: dict) -> list:
    """What this part of the picture is over, what day it is good for, and how
    old the evidence beneath it is.

    Composed from the boundary the read declared and from nothing else: no
    account term is put in front of it, because a total composed of account
    lines whose boundaries differ is over none of those sets and may inherit
    none of their boundaries.

    Both halves of what the read declared are used. The accounts it could not
    value come back apart from the rest, and a line composed from the first
    half alone would leave out exactly them."""
    lines = {}
    for term, fields in declared:
        lines[term] = (_by_the_number(term, int(fields["count"]))
                       if term in _COUNTED
                       else said((term, fields), known, family=PICTURE))
    if unmeasured:
        lines[UNMEASURED] = _by_the_number(UNMEASURED, len(unmeasured))
    lines[AS_OF] = moment(PICTURE + AS_OF, date=render.date(fig["dated"]))
    oldest = _oldest_under(beneath)
    if oldest:
        lines[OLDEST] = moment(PICTURE + OLDEST, date=render.date(oldest))
    return [lines[term] for term in _PICTURE_ORDER if term in lines]


def _by_the_number(term: str, count: int) -> str:
    """One of two whole reviewed sentences, chosen by comparing a count to one.

    A single sentence with the number dropped into it would be a frame nobody
    read in the form a person meets it."""
    if count == 1:
        return moment(PICTURE + term + "_one")
    return moment(PICTURE + term + "_many", count=render.count(count))


def _picture_sayable(term: str) -> bool:
    """Whether the picture family has a reviewed line for this declaration.

    A way of falling short said as a number needs both of its sentences: one of
    them missing is a count that could reach a person as a frame."""
    moments = load()["moments"]
    return term in _PICTURE_ORDER and all(key in moments
                                          for key in _picture_keys(term))


def _picture_keys(term: str) -> tuple[str, ...]:
    """The pack keys the picture says one declaration in."""
    if term in _COUNTED:
        return (PICTURE + term + "_one", PICTURE + term + "_many")
    return (PICTURE + term,)


def _oldest_under(beneath: list) -> str:
    """The stalest measurement beneath one figure, or "".

    Read off the lines the figure was composed from rather than off the point
    as a whole: a date carried by a line held in another currency is not
    behind this number."""
    return min((str(row["as_of"]) for row in beneath if row.get("as_of")),
               default="")


def _unmeasured(rows: list, known: dict,
                family: str = BENEATH_A_FIGURE) -> list:
    """Why each account THIS figure could not value is not in it.

    ``rows`` are already kept to the figure's own currency by the one helper
    that decides what is beneath a figure. An account held in another currency
    is not missing from this total — it was never a term of it — and naming it
    here would put one gap on two figures, so a person counting what they read
    against what the panel says would find two where the panel says one.

    Each entry carries the account, the name it is written under, and one whole
    reviewed sentence chosen by the token the read declared it under. The name
    travels with it because the account is written once, by the one writer of
    accounts: two sides each resolving a path is two systems describing one
    fact, and they disagree first on exactly the accounts a name cannot tell
    apart.

    The reason token does its work here and does not travel, wherever the entry
    is read. Choosing which reviewed line to compose is the whole of its job,
    and a token crossing beside the sentence it chose is a field nothing reads
    — and worse than unread, it is a standing invitation for a surface to
    branch on a machine's word instead of rendering what it was handed.

    A token with no reviewed line raises rather than rendering. There is no
    generic line to fall through to and no way to say the token itself: a
    person reading a machine's word for why their money is missing has been
    told nothing, and a fallback is what makes that look like it worked."""
    return [{"account": row["account"],
             "name": str(account_written(row["account"], known)),
             "sentence": moment(PICTURE + family + row["reason"],
                                account=account_written(row["account"], known))}
            for row in rows]


def _held_in(point: dict, known: dict) -> dict:
    """What currency each account the picture might name is held in.

    One answer to one question, asked once. Everything a figure points at —
    the records beneath it, the documents it cites, the accounts it could not
    value — is kept to the figure's own currency, and a second way of deciding
    which currency an account belongs to is a second system describing one
    fact.

    A line states its own currency. An account the read could not value has no
    line, so it is read from what the accounts read knew about it. An account
    neither can place is in neither answer, and belongs to no figure: an
    account attributed to every currency would be disclosed once per figure as
    though a person held that many of it."""
    placed = {str(line["account"]): str(line.get("currency", ""))
              for line in (point.get("lines") or []) if line.get("account")}
    for path, entity in known.items():
        placed.setdefault(str(path), str(entity.get("currency", "")))
    return {path: currency for path, currency in placed.items() if currency}


def _unplaced(rows, held_in: dict) -> list:
    """The rows naming an account no currency could be found for.

    The mirror of the rule ``_beneath`` states. A figure declaring no currency
    is beneath nothing; an account no currency can be found for is beneath no
    figure — it is on no card, in no line and in no drawer, so there is nowhere
    else it could be said.

    Counting such an account and naming it nowhere is not privacy. The panel
    counts rather than names where the names are already on the screen, and
    this one is on no screen: a person holding something the product recorded,
    that sits in no total and is called nothing, cannot verify it, act on it,
    or discover that it exists."""
    return [row for row in rows
            if str(row.get("account", "")) not in held_in]


def _beneath(rows, currency: str, held_in: dict) -> list:
    """The rows naming an account held in one currency, in their own order.

    The one place a figure decides what is beneath it. There is no rate with a
    source, a date and a grade of its own, so two currencies are two figures
    nothing may relate — and anything a figure carries from the other one
    discloses, wherever it is read, exactly what the panel sentence counts
    rather than names in order to keep back."""
    if not currency:
        # A figure declaring no currency is beneath nothing. Matching on a
        # missing answer would sweep up every account nothing could place,
        # which is the opposite of what not being able to place one means.
        return []
    return [row for row in rows
            if str(row.get("account", "")) in held_in
            and held_in[str(row["account"])] == currency]


def _picture_citations(beneath: list,
                       grade: FigureGrade) -> tuple[Citation, ...]:
    """The route from the picture back to the records beneath it.

    One citation per document the lines beneath this figure stand on. No page
    is claimed and nothing says which part came from where: the read records
    the page of one part, and a part's page offered as the page of a whole is
    a claim about evidence the record does not support."""
    return tuple(Citation(document_id=document, relation=_CITED_AS[grade])
                 for document in sorted({str(row["proves"]) for row in beneath
                                         if row.get("proves")}))


def _sentence(caveat) -> str:
    """One caveat as its words, whether it arrived as a sentence or as a
    mapping carrying that sentence under an identity."""
    return str(caveat.get("text", "") if isinstance(caveat, dict) else caveat)
