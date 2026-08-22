"""The composer that turns one read into the picture a person is shown."""

from __future__ import annotations

from unittest import mock

import pytest

from viva import quantity, render
from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, networth,
                         opening_balance_observed, simple_transaction)
from viva.ledger.events import position_observed, statement_held
from viva import persona
from viva.persona import load, moment
from viva.surface import overview as overview_module
from viva.surface.models import FigureView, PanelState
from viva.surface.overview import (AS_OF, BALANCES, NET_WORTH, OLDEST,
                                   PICTURE, UNMEASURED, _picture_keys,
                                   _sentence, overview)
from viva.tools import default_registry
from viva.tools import envelope
from viva.tools.boundary import account_written, named_slice, statements
from viva.tools.envelope import (BY_ACCOUNT, BY_CURRENCY, GAP_REASONS,
                                 SELECTED_KINDS)


def _events(*extra):
    return [
        account_opened("acct:one", "depository", "Everyday Checking", "USD",
                       "2026-06-01"),
        opening_balance_observed("acct:one", "1000.00", "2026-06-01",
                                 Provenance("doc-one", 1, "", "opening balance")),
        simple_transaction("acct:one", "-40.00", "groceries", "2026-06-10"),
        closing_balance_observed("acct:one", "960.00", "2026-06-30",
                                 Provenance("doc-one", 4, "", "closing balance")),
        *extra,
    ]


def test_the_amount_is_written_under_the_locale_it_was_given():
    """The composer is a pure function of a projection and a locale, and the
    one writer of amounts is what writes them. Two locales, one value, two
    conventions, and no format string anywhere in the surface."""
    projection = LedgerProjection(_events())

    american = overview(projection, "en-US", "2026-09-30")["accounts"][0]["balance"]
    german = overview(projection, "de-DE", "2026-09-30")["accounts"][0]["balance"]

    assert american["exact_value"] == german["exact_value"] == "960.00"
    assert american["display"] == "USD 960.00"
    assert german["display"] == "USD 960,00"


def test_a_row_whose_figure_cannot_be_completed_is_withheld_and_the_panel_says_so():
    """An account opened and never measured has a number good as of no day.
    The row is still shown — it is an account the person holds — and the
    figure is kept back with a reason that names the account."""
    projection = LedgerProjection(_events(
        account_opened("acct:two", "depository", "Unmeasured Savings", "USD",
                       "2026-06-01")))

    picture = overview(projection, "en-US", "2026-09-30")
    withheld = [row for row in picture["accounts"] if row["balance"] is None]

    assert picture["state"] == PanelState.PARTIAL.value
    assert [row["account"] for row in withheld] == ["acct:two"]
    assert len(picture["issues"]) == 1
    assert "Unmeasured Savings" in picture["issues"][0]["message"]
    assert picture["issues"][0]["code"]


def test_a_panel_says_ready_only_when_every_row_carries_its_figure():
    projection = LedgerProjection(_events())

    picture = overview(projection, "en-US", "2026-09-30")

    assert picture["state"] == PanelState.READY.value
    assert picture["issues"] == []
    assert all(row["balance"] for row in picture["accounts"])


def test_a_ledger_bucket_is_not_an_account_on_the_picture():
    """The buckets a transaction posts against are in the projection and are
    not things a person holds. The read this surface asks is the one that
    already refuses them, so nothing here has to know their names."""
    projection = LedgerProjection(_events())

    shown = {row["account"] for row in overview(projection, "en-US", "2026-09-30")["accounts"]}

    assert shown == {"acct:one"}
    assert len(shown) < len(list(projection.account_infos()))


def test_an_empty_vault_shows_no_rows_and_withholds_nothing():
    picture = overview(LedgerProjection([]), "en-US", "2026-09-30")

    assert picture["accounts"] == []
    assert picture["state"] == PanelState.READY.value
    assert picture["issues"] == []


@pytest.mark.parametrize("locale", ["en-US", "en-IN"])
def test_every_figure_carries_a_citation_to_the_records_it_stands_on(locale):
    """The route is to the document the figure itself declares among its
    records, under the word the grade supports: a figure an issuer's own
    document states is attested by it."""
    picture = overview(LedgerProjection(_events()), locale, "2026-09-30")
    figure = picture["accounts"][0]["balance"]

    (citation,) = figure["citations"]
    assert citation["document_id"] == "doc-one"
    assert citation["document_id"] in figure["record_ids"]
    assert citation["relation"] == "attests"


def _investment_events():
    """An account whose worth is its cash summed with what it holds, each
    measured on its own page and its own day."""
    return [
        account_opened("acct:portfolio", "investment", "Growth Portfolio",
                       "USD", "2026-05-31"),
        closing_balance_observed(
            "acct:portfolio", "500.00", "2026-06-30",
            Provenance("doc-portfolio", 1, "", "closing balance")),
        position_observed(
            "acct:portfolio", "SAMPLE INDEX FUND", "100", "12000.00", "USD",
            "2026-05-31",
            provenance=Provenance("doc-portfolio", 2, "", "holdings table")),
    ]


def test_a_composed_figure_claims_no_page_of_the_part_it_was_summed_from():
    """The one shape where a figure and the account's balance are different
    numbers. The read records the page the cash was printed on and nothing
    about where the holdings were, so the citation names the document the
    figure declares it stands on and claims no page: a part's page offered as
    the page of the whole is a claim about evidence the record does not
    support, and it would sit under a grade that says the opposite."""
    projection = LedgerProjection(_investment_events())
    balance = projection.balance("acct:portfolio")

    figure = overview(projection, "en-US", "2026-09-30")["accounts"][0]["balance"]

    # The figure and the balance are two different numbers here.
    assert figure["exact_value"] == "12500.00"
    assert str(balance.amount) == "500.00"
    (citation,) = figure["citations"]
    assert citation["document_id"] == "doc-portfolio"
    assert citation["page"] == ""
    assert citation["label"] == ""


def test_a_figure_carries_no_sentence_written_about_a_different_number():
    """The balances view writes one sentence about an account's balance. A
    composed figure is not that balance, and the sentence would contradict the
    grade standing beside it, so it stays where it is true."""
    projection = LedgerProjection(_investment_events())
    explanation = projection.balance("acct:portfolio").explanation

    figure = overview(projection, "en-US", "2026-09-30")["accounts"][0]["balance"]

    assert explanation.strip()
    assert figure["provenance"] == ""
    assert explanation not in str(figure)


def test_the_arithmetic_of_a_failed_check_never_reaches_a_person():
    """A conflicted balance's explanation carries the identity check's own
    working — expected, got, delta, tolerance. It is written for whoever is
    fixing the ledger, and a person reading their accounts is not that."""
    events = _events()
    events[-1] = closing_balance_observed(
        "acct:one", "1500.00", "2026-06-30",
        Provenance("doc-one", 4, "", "closing balance"))
    projection = LedgerProjection(events)
    explanation = projection.balance("acct:one").explanation

    figure = overview(projection, "en-US", "2026-09-30")["accounts"][0]["balance"]

    assert figure["grade"] == "conflicted"
    assert "tolerance" in explanation
    assert "tolerance" not in str(figure)


# ------------------------------------------------------------- the picture


def _picture_events():
    """A vault the picture has something to say about: two currencies, an
    account no measurement covers, and a document read and not posted."""
    return _events(
        account_opened("acct:abroad", "depository", "Abroad Current", "EUR",
                       "2026-06-01"),
        closing_balance_observed("acct:abroad", "500.00", "2026-05-31",
                                 Provenance("doc-two", 1, "", "closing balance")),
        account_opened("acct:unmeasured", "depository", "Unmeasured Savings",
                       "USD", "2026-06-01"),
        statement_held("doc-held", {"account_ref": "acct:one"}, None, "gap",
                       "2026-07-02"),
    )


def _held(projection):
    """The accounts the balances read names, which is how an account the point
    could not value is still written as a person is shown it."""
    from viva.surface.overview import BALANCES, _known
    return _known(default_registry(projection, "en-US", "2026-09-30")
                  .call(*BALANCES))


def _picture(projection=None, today="2026-09-30"):
    return overview(projection or LedgerProjection(_picture_events()),
                    "en-US", today)["picture"]


def test_the_picture_carries_one_figure_for_each_currency_and_no_total_of_them():
    """Per-currency subtotals and no grand total: there is no rate with a
    source, a date and a grade of its own, so a number across currencies would
    be a figure no record attests. Nothing here adds them, including this
    assertion — what is checked is that each currency stands on its own."""
    picture = _picture()

    assert [figure["currency"] for figure in picture["figures"]] == ["EUR", "USD"]
    assert {figure["measure"] for figure in picture["figures"]} == {"net_worth"}
    for figure in picture["figures"]:
        assert figure["display"].strip()
        assert figure["exact_value"].strip()
        assert figure["grade_description"].strip()
        # One sentence to a line, so a surface that stacks them never has to
        # find the joins by looking for punctuation.
        assert figure["coverage"]
        assert all(line.strip() for line in figure["coverage"])


def test_the_picture_says_how_far_it_reaches_and_names_no_total_doing_it():
    """The panel's one sentence, counting and naming nothing — and saying
    nothing about a total.

    A person holding money in two currencies meets two totals and no third, so
    a sentence opening "this total" would name either a figure nothing may
    compose or one of the two, of which it is false. What the panel says is how
    much of what they hold is counted here, which is true at one currency and
    at four."""
    picture = _picture()

    assert picture["coverage"] == moment(
        "picture_accounts_some",
        counted=render.count(2), held=render.count(3))
    assert len(picture["figures"]) > 1


def test_how_far_the_picture_reaches_is_three_sentences_chosen_by_counting():
    """All, exactly one, and some are three whole reviewed lines. A verb
    agreeing with a count is a word dropped into a frame, which is the shape
    this project does not ship a person."""
    every = _picture(LedgerProjection(_events()))
    one = _picture(LedgerProjection(_events(
        account_opened("acct:two", "depository", "Second Savings", "USD",
                       "2026-06-01"))))
    some = _picture()

    assert every["coverage"] == moment("picture_accounts_all")
    assert one["coverage"] == moment("picture_accounts_one",
                                     held=render.count(2))
    assert some["coverage"] == moment("picture_accounts_some",
                                      counted=render.count(2),
                                      held=render.count(3))
    assert len({every["coverage"], one["coverage"], some["coverage"]}) == 3


def test_the_pictures_coverage_names_no_account_it_could_not_value():
    """The coverage sentence counts and never names. A list of account names
    is the one thing on this screen a person cannot un-share, and the names of
    the accounts a person holds are already on the cards below it."""
    projection = LedgerProjection(_picture_events())
    picture = _picture(projection)
    names = {info.name for info in projection.account_infos() if info.name}

    said = [picture["coverage"]] + [figure["coverage"]
                                    for figure in picture["figures"]]
    assert names
    for sentence in said:
        assert not [name for name in names if name in sentence], sentence
    for path in {info.account for info in projection.account_infos()}:
        assert not [sentence for sentence in said if path in sentence], path


def test_the_picture_discloses_every_account_the_point_could_not_value():
    """The accounts a read could not value come back from ``statements()``
    apart from everything else, so a composer reading only what it returns
    first would compose a coverage sentence that silently leaves out exactly
    the accounts these lines exist to disclose — and would pass every other
    check here."""
    projection = LedgerProjection(_picture_events())
    point = networth.net_worth(projection, "2026-09-30")

    picture = _picture(projection)

    assert point.skipped
    assert len(point.skipped) == 1
    # Disclosed on the figure it belongs to, and on no other: the account is
    # held in one currency and is missing from one total.
    said = [figure for figure in picture["figures"]
            if moment("picture_boundary_unmeasured_one") in figure["coverage"]]
    assert [figure["currency"] for figure in said] == ["USD"]


def test_a_second_account_the_point_cannot_value_is_said_as_a_number():
    """Singular and plural are two whole reviewed sentences chosen by counting,
    never one sentence with a word dropped into it."""
    picture = _picture(LedgerProjection(_picture_events() + [
        account_opened("acct:also-unmeasured", "depository", "Other Savings",
                       "USD", "2026-06-01")]))

    usd, = [figure for figure in picture["figures"]
            if figure["currency"] == "USD"]
    assert moment("picture_boundary_unmeasured_many",
                  count=render.count(2)) in usd["coverage"]
    assert moment("picture_boundary_unmeasured_one") not in usd["coverage"]


def test_the_picture_discloses_a_document_read_and_not_posted():
    """A gap no account can name: a document read and not posted may be about
    an account that does not exist yet, so it is said as a number."""
    picture = _picture()

    for figure in picture["figures"]:
        assert moment("picture_boundary_unposted_one") in figure["coverage"]


def test_the_picture_is_not_withheld_where_a_document_is_unposted_and_an_account_unvalued():
    """The shape most likely to blank a real vault. Both of the things that
    make a total less than whole are present, and the total still reaches the
    screen — with what it leaves out said beside it, which is the whole point
    of saying it."""
    projection = LedgerProjection(_picture_events())
    point = networth.net_worth(projection, "2026-09-30")

    picture = _picture(projection)

    assert point.skipped and point.held
    assert picture["figures"]
    assert picture["coverage"] != moment("picture_no_figure")


def test_the_picture_prepends_no_account_term_to_a_figure_over_no_account():
    """A total composes account lines whose boundaries differ from each other,
    so it is over none of those sets and may inherit none of their boundaries.
    The card composer puts the account term first and always; the picture puts
    nothing in front of what the read itself declared."""
    projection = LedgerProjection(_picture_events())
    picture = _picture(projection)
    known = {}

    for figure in picture["figures"]:
        assert figure["coverage"][0] == moment(
            "picture_boundary_selected_currency",
            currency=render.label(figure["currency"]))
        assert moment("card_boundary_selected_account",
                      account=named_slice({"kind": BY_ACCOUNT,
                                           "value": "acct:one"},
                                          known)) not in figure["coverage"]


def test_no_picture_figure_declares_a_way_of_narrowing_with_an_empty_value():
    """Walked over the closed vocabulary of ways a set can be narrowed, so a
    kind added later is walked too. A term declared with nothing in it renders
    a sentence with a hole where a fact should be."""
    result = default_registry(LedgerProjection(_picture_events()), "en-US",
                              "2026-09-30").call(*NET_WORTH)
    figures = [fig for fig in result.figures
               if fig["quantity"] == quantity.NET_WORTH]
    terms = [item for fig in figures
             for item in (fig["boundary"].get("cut") or [])
             + (fig["boundary"].get("selected") or [])]

    assert figures
    assert terms
    for item in terms:
        assert item["kind"] in SELECTED_KINDS, item
        assert str(item.get("value", "")).strip(), item


def test_every_way_a_picture_figure_can_fall_short_has_a_reviewed_line():
    """A figure whose boundary this surface has no reviewed line for is
    withheld rather than shown, and the picture is not exempt from that. What
    this asserts is that nothing on the fixture's own shapes has to be
    withheld: every declaration the read makes has a line in the pack that
    ships, both of them where a count chooses between two sentences."""
    result = default_registry(LedgerProjection(_picture_events()), "en-US",
                              "2026-09-30").call(*NET_WORTH)
    moments = load()["moments"]
    declared = set()
    for fig in result.figures:
        if fig["quantity"] != quantity.NET_WORTH:
            continue
        said, unmeasured = statements(fig)
        declared |= {term for term, _fields in said}
        if unmeasured:
            declared.add(UNMEASURED)
    declared |= {AS_OF, OLDEST}

    assert declared
    for term in declared:
        keys = _picture_keys(term)
        assert keys
        for key in keys:
            assert key in moments, key


def test_a_picture_figure_whose_scope_has_no_reviewed_line_is_kept_back():
    """Withholding stays reachable, because a refusal beats a wrong number. A
    declaration the picture family has no words for keeps its figure off the
    screen rather than putting a number there with no scope."""
    projection = LedgerProjection(_picture_events())

    assert _picture(projection)["figures"]
    with mock.patch.object(overview_module, "_PICTURE_ORDER", ()):
        assert _picture(projection)["figures"] == []


def test_the_picture_says_what_day_it_was_read_on_and_how_old_its_evidence_is():
    """Two dates, because the gap between them is the whole of what "how
    current is this picture" means. A balance carries forward, so the total is
    good on the day it was asked for; the oldest measurement under it is a
    different fact, said in words on the figure it is actually under.

    The day the read was made is carried as a field because it was given to
    the read and recorded. The panel carries no second date beside it: a date
    over the whole picture would be a claim at a level where it is not true of
    every figure under it, and nothing would render it."""
    picture = _picture()

    assert picture["read_on"] == "2026-09-30"
    assert set(picture) == {"coverage", "read_on", "figures", "withheld",
                            "unplaced"}
    for figure in picture["figures"]:
        assert figure["as_of"] == "2026-09-30"
        assert moment("picture_as_of",
                      date=render.date("2026-09-30")) in figure["coverage"]


def test_a_currencys_oldest_measurement_is_read_off_its_own_lines():
    """The oldest measurement behind a figure is behind THAT figure. A date
    carried by a line held in another currency is not under this number, and
    saying it would be a false claim about this one."""
    picture = _picture()
    oldest = {figure["currency"]:
              moment("picture_oldest_input", date=render.date(day))
              for figure, day in zip(picture["figures"],
                                     ("2026-05-31", "2026-06-30"))}

    for figure in picture["figures"]:
        assert oldest[figure["currency"]] in figure["coverage"]
    assert len(set(oldest.values())) == len(oldest)


def test_a_picture_with_nothing_to_stand_behind_says_so_rather_than_going_blank():
    """Silence is not a refusal. A person who saw a total yesterday and sees
    nothing today learns that the product is broken, which is a worse and less
    true thing than what actually happened."""
    picture = _picture(LedgerProjection([]))

    assert picture["figures"] == []
    assert picture["coverage"] == moment("picture_no_figure")
    assert picture["read_on"] == "2026-09-30"


def test_the_picture_routes_back_to_the_records_beneath_it():
    """A number with no route to its source is a number this product has no
    business showing — and a composed figure names no page, because the read
    records the page of one part only."""
    picture = _picture()

    for figure in picture["figures"]:
        assert figure["citations"]
        for citation in figure["citations"]:
            assert citation["document_id"]
            assert citation["page"] == ""


def test_a_picture_citation_names_a_document_beneath_its_own_currency():
    """A route to a record that is not under this number is not a route to
    this number's evidence. There is no rate with a source, a date and a grade
    of its own, so two currencies are two figures nothing may relate — and a
    citation reaching across them relates them at the one place a person goes
    looking for proof. No page is claimed either: the read records the page of
    one part, and a part's page offered as the page of a whole is a claim the
    record does not support."""
    projection = LedgerProjection(_picture_events())
    point = networth.net_worth(projection, "2026-09-30")
    beneath = {}
    for line in point.lines:
        beneath.setdefault(line.currency, set()).add(line.proves)

    picture = _picture(projection)

    assert len(beneath) > 1
    assert picture["figures"]
    for figure in picture["figures"]:
        named = {citation["document_id"] for citation in figure["citations"]}
        assert named
        assert named <= beneath[figure["currency"]], figure["currency"]
        for other, documents in beneath.items():
            if other != figure["currency"]:
                assert not named & (documents - beneath[figure["currency"]])
        assert {citation["page"] for citation in figure["citations"]} == {""}


def test_each_picture_figure_announces_itself_and_no_two_announce_the_same():
    """One total per currency is one control per currency, and the words a
    control announces are how a person who cannot see which card it sits on
    tells them apart. Two controls announcing the same words conflate two
    figures nothing may relate, at the moment somebody acts on one of them.

    Both come from the pack that ships them: an announcement composed here
    would be a sentence a person reads that nobody reviewed.

    What this holds on its own is equality — it would stay green against a
    composer that reproduced today's copy some other way. What makes it
    provenance is the pack moving underneath it: change the shipped line and
    the composer follows while anything else does not. The gate that holds
    that alone is the parity one, which compares committed bytes against a
    live render of the pack."""
    figures = _picture()["figures"]

    assert len(figures) > 1
    for figure in figures:
        currency = render.label(figure["currency"])
        assert figure["evidence_label"] == moment("picture_evidence_label",
                                                  currency=currency)
        assert figure["evidence_heading"] == moment("picture_evidence_heading",
                                                    currency=currency)
    assert len({figure["evidence_label"] for figure in figures}) == len(figures)
    assert len({figure["evidence_heading"] for figure in figures}) == len(figures)


def test_the_announcements_are_emitted_beside_a_figure_and_not_declared_on_it():
    """The surface contract artifact is built from the figure model's own field
    names, so a field added there moves an artifact no writer here owns. These
    are the words of one surface's control rather than a property of the
    figure, and they are merged onto what it emits."""
    from dataclasses import fields

    declared = {field.name for field in fields(FigureView)}
    figure = _picture()["figures"][0]

    assert declared
    beside = {"evidence_label", "evidence_heading", "boundary", "unmeasured"}
    for added in beside:
        assert added not in declared, added
    assert set(figure) - declared == beside


def test_a_currency_whose_total_is_kept_back_is_said_and_not_left_blank():
    """Silence is not a refusal at the figure any more than at the panel. A
    person holding money in two currencies and shown one number, with nothing
    beside it, is not told a second total was withheld — they learn there was
    never one, which is the thing that did not happen."""
    projection = LedgerProjection(_picture_events())
    whole = _picture(projection)

    with mock.patch.object(overview_module, "_PICTURE_ORDER", ()):
        kept_back = _picture(projection)

    assert len(whole["figures"]) > 1
    assert whole["withheld"] == []
    assert kept_back["figures"] == []
    assert kept_back["withheld"] == [
        {"currency": currency,
         "sentence": moment("picture_withheld_unsayable",
                            currency=render.label(currency))}
        for currency in ("EUR", "USD")]


def test_what_is_shown_and_what_is_kept_back_are_both_in_currency_order():
    """The read emits one figure per currency in currency order, and a person
    reading a stack of totals against a stack of refusals reads them in one
    order or reads two lists that do not line up."""
    projection = LedgerProjection(_picture_events())
    shown = [figure["currency"] for figure in _picture(projection)["figures"]]

    with mock.patch.object(overview_module, "_PICTURE_ORDER", ()):
        kept_back = [entry["currency"]
                     for entry in _picture(projection)["withheld"]]

    assert shown == sorted(shown)
    assert kept_back == sorted(kept_back)
    assert shown == kept_back


def test_a_picture_figure_carries_the_boundary_the_read_declared_unaltered():
    """The panel counts the accounts a total could not value and never names
    them, and that is only honest because the figure carries the declaration
    that does name them, with the reason, where a person can go and read it.

    The point names and the sentence counts. Drop this half and the counting
    stands on nothing — so what is asserted is that the boundary arrives, that
    it is the read's own object rather than a version of it, and that the
    unvalued accounts are in it by name."""
    projection = LedgerProjection(_picture_events())
    result = default_registry(projection, "en-US", "2026-09-30").call(*NET_WORTH)
    declared = {fig["currency"]: fig["boundary"] for fig in result.figures
                if fig["quantity"] == quantity.NET_WORTH}

    figures = _picture(projection)["figures"]

    assert declared
    for figure in figures:
        assert figure["boundary"] == declared[figure["currency"]]
        named = {row["account"] for row in figure["boundary"]["unmeasured"]}
        assert named == {"acct:unmeasured"}
        assert all(row["reason"] for row in figure["boundary"]["unmeasured"])


def test_a_picture_figure_names_no_record_from_another_currency():
    """Everything a figure points at is scoped to the lines it was composed
    from. A figure listing identities from the other currency discloses, in the
    one place a person goes for proof, exactly the identities the panel
    sentence counts rather than names in order to keep back."""
    projection = LedgerProjection(_picture_events())
    point = networth.net_worth(projection, "2026-09-30")
    beneath = {}
    for line in point.lines:
        beneath.setdefault(line.currency, set()).add(line.account)

    figures = _picture(projection)["figures"]

    assert len(beneath) > 1
    for figure in figures:
        records = set(figure["record_ids"])
        assert records
        assert records == beneath[figure["currency"]], figure["currency"]
        for other, accounts in beneath.items():
            if other != figure["currency"]:
                assert not records & (accounts - beneath[figure["currency"]])


def test_the_composer_cannot_be_called_without_being_told_the_day():
    """The composer takes the day as a required argument.

    A composer with a default day does not read a clock itself — it hands an
    empty day to a read that does, one call further down, where nothing on this
    side would notice. A function that cannot be called without the day is not
    one line away from a function that reads the machine it ran on."""
    import inspect

    day = inspect.signature(overview).parameters["today"]

    assert day.default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        overview(LedgerProjection(_events()), "en-US")


def test_the_day_the_picture_records_is_the_day_it_was_handed():
    """`read_on` records the value this read was given, carried through
    unchanged. Read back off the point it would be a derivation, and a
    derivation can drift from what was asked for while still looking like a
    record of it."""
    projection = LedgerProjection(_picture_events())

    for day in ("2026-09-30", "2027-03-01"):
        picture = _picture(projection, today=day)
        assert picture["read_on"] == day
        for figure in picture["figures"]:
            assert figure["as_of"] == day


def test_every_reason_an_account_can_be_left_out_for_has_a_reviewed_line():
    """The build gate on the reason vocabulary.

    A reason is a machine's token, and a person reading a machine's word for
    why their own money is missing from a total has been told nothing. So there
    is no generic line to fall through to and no way to render the token: a
    token with no reviewed sentence fails here, at build time, rather than
    there.

    Walked over the closed vocabulary the module that owns it declares, so a
    token added later is walked too rather than remembered about."""
    moments = load()["moments"]
    families = (overview_module.BENEATH_A_FIGURE, overview_module.BENEATH_NOTHING)

    assert GAP_REASONS
    assert families
    for family in families:
        for reason in GAP_REASONS:
            key = PICTURE + family + reason
            assert key in moments, (
                f"the read can leave an account out of a total for {reason!r} "
                f"and this surface has no reviewed line for it: add {key} to "
                "the pack")
            assert persona.MOMENT_FIELDS[key] == {"account"}


def test_a_reason_with_no_reviewed_line_renders_nothing_at_all():
    """Not a bare token, not a blank, not a generic sentence — nothing. A
    fallback here is what would make a person reading a machine's word look
    like a working screen."""
    projection = LedgerProjection(_picture_events())

    assert _picture(projection)["figures"]
    with mock.patch.object(overview_module, "PICTURE", "no_such_family_"):
        with pytest.raises(KeyError):
            _picture(projection)


def test_each_account_left_out_of_a_total_is_named_with_its_reason():
    """MON-27, on the screen rather than in the payload alone. Naming the
    account says which card to look at; the reason is what tells a person
    whether anything is theirs to do, and it is the half that is load-bearing
    when they are looking at a card carrying a number the total does not
    include."""
    projection = LedgerProjection(_picture_events())
    named = {info.account: info.name for info in projection.account_infos()}

    figures = _picture(projection)["figures"]

    usd, = [figure for figure in figures if figure["currency"] == "USD"]
    declared = usd["boundary"]["unmeasured"]

    assert declared
    assert len(usd["unmeasured"]) == len(declared)
    for said, row in zip(usd["unmeasured"], declared):
        assert said["account"] == row["account"]
        assert said["sentence"] == moment(
            PICTURE + "unmeasured_" + row["reason"],
            account=account_written(row["account"], _held(projection)))
        # Written as the person is shown it, never as a ledger path — and the
        # written name travels beside it, so nothing on the other side of the
        # bridge resolves a path a second way.
        assert said["name"] == named[row["account"]]
        assert named[row["account"]] in said["sentence"]
        assert row["account"] not in said["sentence"]


def test_a_withheld_currency_is_carried_as_the_currency_and_its_sentence():
    """The interface is never left to work out which currency was kept back by
    reading the words. The composer already holds it — that is how the sentence
    was written — so carrying it closes the door rather than trusting nobody
    opens it."""
    projection = LedgerProjection(_picture_events())

    with mock.patch.object(overview_module, "_PICTURE_ORDER", ()):
        withheld = _picture(projection)["withheld"]

    assert withheld
    assert [entry["currency"] for entry in withheld] == ["EUR", "USD"]
    for entry in withheld:
        assert set(entry) == {"currency", "sentence"}
        assert entry["sentence"] == moment(
            "picture_withheld_unsayable",
            currency=render.label(entry["currency"]))


def _entity(account: str, name: str) -> dict:
    """One account as a read hands it over — what an account is written from."""
    return {"id": "", "kind": "account", "account": account, "name": name,
            "account_kind": "depository", "currency": "USD"}


def test_a_gap_that_something_would_settle_reads_differently_from_one_nothing_can():
    """The arm no vault in this repository composes.

    A parity fixture teaches only the shapes it happens to hold, and it holds
    one of the two reasons a read can leave an account out of a total. A
    sentence nothing has ever composed is a sentence nobody has seen, so this
    drives the other arm directly against a boundary built here, and drives
    both in one figure so the two are shown to be different things to be told.

    The account is written by the one writer of accounts, from what a read
    knows about it — a display name, never a ledger path. The first working
    version of this composer put a path fragment where a name belongs, and
    nothing was watching that arm."""
    from viva.tools.envelope import GAP_REFUSED, GAP_UNOBSERVED, bounded

    known = {"acct:refused": _entity("acct:refused", "Sample Home Loan"),
             "acct:never-seen": _entity("acct:never-seen", "Sample Old Passbook")}
    boundary = bounded(
        whole=False,
        cut=[{"kind": BY_CURRENCY, "value": "USD"}],
        unmeasured=[{"account": "acct:refused", "reason": GAP_REFUSED,
                     "settled_by": "a statement for it"},
                    {"account": "acct:never-seen", "reason": GAP_UNOBSERVED,
                     "settled_by": ""}])
    held_in = overview_module._held_in({}, known)
    rows = overview_module._beneath(boundary["unmeasured"], "USD", held_in)

    refused, never_seen = overview_module._unmeasured(rows, known)

    assert refused["account"] == "acct:refused"
    assert refused["sentence"] == moment(
        "picture_unmeasured_refused",
        account=account_written("acct:refused", known))
    assert never_seen["sentence"] == moment(
        "picture_unmeasured_unobserved",
        account=account_written("acct:never-seen", known))
    assert refused["sentence"] != never_seen["sentence"]
    # Written as a person is shown it, and never as the path underneath it.
    for said, name in ((refused, "Sample Home Loan"),
                       (never_seen, "Sample Old Passbook")):
        assert name in said["sentence"]
        assert said["account"] not in said["sentence"]
    # And what would settle the gap reaches no sentence, on either arm.
    assert "a statement for it" not in refused["sentence"]


def test_a_refused_gap_that_names_no_remedy_cannot_be_built_at_all():
    """Why the refused sentence may assert that something would settle it.

    It is not a promise the sentence keeps by being careful — a boundary
    refuses to be built where a refused gap names nothing that would close it,
    so the clause is true of every figure that exists."""
    from viva.tools.envelope import GAP_REFUSED, GAP_UNOBSERVED, bounded

    with pytest.raises(ValueError, match="names what would close it"):
        bounded(whole=False, unmeasured=[{"account": "acct:x",
                                          "reason": GAP_REFUSED,
                                          "settled_by": ""}])
    with pytest.raises(ValueError, match="has nothing to name"):
        bounded(whole=False, unmeasured=[{"account": "acct:x",
                                          "reason": GAP_UNOBSERVED,
                                          "settled_by": "something"}])


def _two_currencies():
    """A vault where every account a person holds is valued, in two
    currencies — so the panel's own sentence is the all-accounts one."""
    return [
        account_opened("acct:home", "depository", "Everyday Checking", "USD",
                       "2026-06-01"),
        closing_balance_observed("acct:home", "960.00", "2026-06-30",
                                 Provenance("doc-h", 1, "", "closing balance")),
        account_opened("acct:away", "depository", "Abroad Current", "EUR",
                       "2026-06-01"),
        closing_balance_observed("acct:away", "500.00", "2026-06-30",
                                 Provenance("doc-a", 1, "", "closing balance")),
    ]


def test_the_panel_counts_what_it_shows_and_not_what_the_read_returned():
    """The claim is about the thing a person is looking at.

    Every account here is valued, so the read would say all of them are
    counted — and it would be right about the read. Keep one currency's total
    back and that sentence becomes false about the screen: one number is
    showing, the other is not, and the accounts behind the missing one are not
    counted anywhere a person can see.

    So the numerator is read off the figures the panel renders. A figure that
    is not there takes its accounts out of the count by not being there, which
    is the only way the two stay in step without either being told about the
    other."""
    projection = LedgerProjection(_two_currencies())
    whole = _picture(projection)

    kept_back = _without_a_currency(projection, "EUR")

    assert whole["coverage"] == moment("picture_accounts_all")
    assert [figure["currency"] for figure in kept_back["figures"]] == ["USD"]
    assert kept_back["coverage"] == moment("picture_accounts_one",
                                           held=render.count(2))


def _without_a_currency(projection, currency: str):
    """The same picture with one currency's total kept back, so what the panel
    says can be read against what the panel shows."""
    composed = overview_module._picture_figure

    def keeping_back(fig, *rest):
        return None if fig["currency"] == currency else composed(fig, *rest)

    with mock.patch.object(overview_module, "_picture_figure", keeping_back):
        return _picture(projection)


def test_what_a_figure_carries_is_kept_to_its_own_currency_by_one_decision():
    """Records, citations, the sentence that counts what could not be valued,
    and the entries that name them — all four are one question asked once.

    Two places deciding which accounts belong to a figure is how a card came to
    count one gap and list another, and how a total in one currency came to
    name an account held in the other."""
    projection = LedgerProjection(_picture_events())
    point = networth.net_worth(projection, "2026-09-30")
    currencies = {line.account: line.currency for line in point.lines}

    figures = _picture(projection)["figures"]

    assert len(figures) > 1
    for figure in figures:
        currency = figure["currency"]
        for account in figure["record_ids"]:
            assert currencies[account] == currency
        for said in figure["unmeasured"]:
            assert _held(projection)[said["account"]]["currency"] == currency
        # The sentence and the entries are one count, because they are one
        # decision.
        counted = [line for line in figure["coverage"]
                   if line in (moment("picture_boundary_unmeasured_one"),
                               moment("picture_boundary_unmeasured_many",
                                      count=render.count(
                                          len(figure["unmeasured"]))))]
        assert len(counted) == (1 if figure["unmeasured"] else 0), currency


def test_an_account_no_currency_can_be_found_for_is_named_by_no_figure():
    """A gap the read declares and neither the point nor the accounts read can
    place. It belongs to no figure and is attributed to none: put on all of
    them, one account a person holds would be disclosed once per currency, as
    though they held that many of it.

    It is still counted among what a person holds, so the panel does not
    quietly shrink. What it does not get is a name on a card, which is a
    disclosure gap the panel's own sentence stands in for."""
    from viva.tools.envelope import GAP_REFUSED, bounded

    known = {"acct:placed": _entity("acct:placed", "Sample Checking")}
    held_in = overview_module._held_in(
        {"lines": [{"account": "acct:placed", "currency": "USD"}]}, known)
    rows = bounded(whole=False,
                   unmeasured=[{"account": "Liabilities:Loan:Sample",
                                "reason": GAP_REFUSED,
                                "settled_by": "the loan statement"}])["unmeasured"]

    assert "Liabilities:Loan:Sample" not in held_in
    assert overview_module._beneath(rows, "USD", held_in) == []
    assert overview_module._beneath(rows, "", held_in) == []


def test_a_day_stated_as_nothing_is_refused_like_a_day_not_stated_at_all():
    """A signature that cannot be called without an argument, and a body that
    accepts any argument, are one hole with two names. The empty string is what
    a caller passes when it has no day, and it reached the machine's clock one
    call down."""
    projection = LedgerProjection(_events())

    with pytest.raises(TypeError):
        overview(projection, "en-US")
    with pytest.raises(ValueError, match="no day was stated"):
        overview(projection, "en-US", "")
    with pytest.raises(ValueError, match="no day was stated"):
        overview(projection, "", "")


def _unplaceable():
    """A vault holding a liability a ruling brought into being. It is on no
    card, in no line and in no drawer: the accounts read never names it,
    because nothing opened it, and no line carries it, because the point
    refuses a debt figure from cash flow alone."""
    from viva.ledger.events import ruling_recorded
    return [
        account_opened("acct:home", "depository", "Everyday Checking", "USD",
                       "2026-03-01"),
        opening_balance_observed("acct:home", "10000.00", "2026-03-01",
                                 Provenance("doc-h", 1, "", "opening balance")),
        simple_transaction("acct:home", "-2000.00", "SAMPLE LENDER",
                           "2026-03-10"),
        closing_balance_observed("acct:home", "8000.00", "2026-03-31",
                                 Provenance("doc-h", 2, "", "closing balance")),
        ruling_recorded(scope="merchant", subject="sample lender",
                        legs=[{"major": "liability",
                               "account": "Liabilities:Loan:Sample"}],
                        occurred_at="2026-04-01", by="human"),
    ]


def test_an_account_beneath_no_figure_is_named_at_the_panel():
    """The panel counts rather than names where the names are already on the
    screen. This one is on no screen: no card, no line, no drawer.

    So counting it and naming it nowhere is not privacy but concealment — a
    person holding something the product recorded, that sits in no total and is
    called nothing, cannot verify it, act on it, or find out it exists."""
    projection = LedgerProjection(_unplaceable())
    point = networth.net_worth(projection, "2026-09-30")

    picture = _picture(projection)
    said, = picture["unplaced"]

    assert [row["account"] for row in point.missing] == ["Liabilities:Loan:Sample"]
    assert said["account"] == "Liabilities:Loan:Sample"
    assert said["sentence"] == moment(
        "picture_unplaced_refused",
        account=account_written("Liabilities:Loan:Sample", _held(projection)))
    assert said["name"] == str(
        account_written("Liabilities:Loan:Sample", _held(projection)))
    # A ledger path is never what a person reads, and the one writer of
    # accounts is what keeps that true here as everywhere else.
    assert said["account"] not in said["sentence"]
    # It is named because no figure could carry it, and nothing was taken off
    # any figure to put it here.
    assert all(figure["unmeasured"] == [] for figure in picture["figures"])
    assert any(row["account"] == said["account"]
               for figure in picture["figures"]
               for row in figure["boundary"]["unmeasured"])


def test_an_account_named_at_the_panel_is_still_counted_among_what_is_held():
    """Dropping it from the denominator would make the panel quietly shrink,
    which is the worse failure: a person would be told a smaller thing was
    covered whole rather than a larger thing was covered in part."""
    projection = LedgerProjection(_unplaceable())

    picture = _picture(projection)

    assert picture["unplaced"]
    assert picture["coverage"] == moment(
        "picture_accounts_one", held=render.count(2))


def test_an_account_a_figure_can_carry_is_not_also_named_at_the_panel():
    """Named where it is beneath, and once. An account a figure carries is
    already disclosed on that figure and on its own card, so naming it again at
    the panel is the list of names the panel exists not to print."""
    projection = LedgerProjection(_picture_events())

    picture = _picture(projection)

    assert picture["unplaced"] == []
    assert [said["account"] for figure in picture["figures"]
            for said in figure["unmeasured"]] == ["acct:unmeasured"]


def test_one_unplaced_account_is_named_once_however_many_currencies_are_held():
    """The read declares the same gap on every currency's figure, so gathering
    them by figure would name one account as many times as a person holds
    currencies."""
    projection = LedgerProjection(_unplaceable() + [
        account_opened("acct:away", "depository", "Abroad Current", "EUR",
                       "2026-03-01"),
        closing_balance_observed("acct:away", "500.00", "2026-03-31",
                                 Provenance("doc-a", 1, "", "closing balance")),
    ])

    picture = _picture(projection)

    assert len(picture["figures"]) > 1
    assert len(picture["unplaced"]) == 1
    assert len({said["account"] for said in picture["unplaced"]}) == 1


def test_the_reason_token_chooses_a_sentence_and_only_travels_where_it_is_read():
    """A token is a machine's word. Its job is choosing which reviewed line to
    compose, and by the time the sentence exists that job is finished — so a
    token crossing beside the sentence it chose is a field nothing reads, and
    worse, a standing invitation for a surface to branch on a machine's word
    instead of rendering what it was handed.

    Both sites, the same answer, and asserted from both ends: a key missing
    here and a key added there are the same drift and neither passes."""
    beneath = _picture(LedgerProjection(_picture_events()))
    panel = _picture(LedgerProjection(_unplaceable()))

    said = [entry for figure in beneath["figures"]
            for entry in figure["unmeasured"]]
    assert said
    for entry in said:
        assert set(entry) == {"account", "name", "sentence"}

    assert panel["unplaced"]
    for entry in panel["unplaced"]:
        assert set(entry) == {"account", "name", "sentence"}


def test_every_caveat_every_read_declared_is_carried():
    """A machine that holds a caveat and does not place it has kept back a
    property of a figure it was handed.

    This surface makes two reads. Gathering from one of them leaves a field
    named for the reads carrying one read's caveats, which is not a decision
    not to render — it is a disclosure lost in transport, and the field would
    say the reads had nothing to add when one of them did."""
    projection = LedgerProjection(_picture_events())
    registry = default_registry(projection, "en-US", "2026-09-30")
    declared = [_sentence(item)
                for read in (registry.call(*BALANCES), registry.call(*NET_WORTH))
                for item in (read.caveats or [])]

    carried = overview(projection, "en-US", "2026-09-30")["caveats"]

    assert declared, "neither read declared a caveat; this walks nothing"
    assert carried == declared


def test_a_caveat_only_the_net_worth_read_declares_still_reaches_the_payload():
    """The defect exactly: the balances read declares nothing, the net-worth
    read declares something, and the payload showed an empty list."""
    projection = LedgerProjection(_picture_events())
    registry = default_registry(projection, "en-US", "2026-09-30")
    balances = registry.call(*BALANCES)
    aggregate = registry.call(*NET_WORTH)

    carried = overview(projection, "en-US", "2026-09-30")["caveats"]

    assert aggregate.caveats
    for item in aggregate.caveats:
        assert _sentence(item) in carried
    assert len(carried) == len(balances.caveats or []) + len(aggregate.caveats)


def test_every_account_counted_still_says_whether_anything_else_is_missing():
    """The sentence answers how many accounts; a person reads it as whether
    this is everything.

    So where every account is counted and the read still declares itself short
    of something — a document read and not posted, a side it could not place —
    the completeness claim is false in the way the sentence is actually read.
    Chosen by the boolean the read declares about itself, never by anything
    read off a string."""
    whole = LedgerProjection(_two_currencies())
    short = LedgerProjection(_two_currencies() + [
        statement_held("doc-held", {"account_ref": "acct:home"}, None, "gap",
                       "2026-07-02")])

    complete = networth.net_worth(whole, "2026-09-30")
    incomplete = networth.net_worth(short, "2026-09-30")

    assert complete.complete is True
    assert incomplete.complete is False
    assert _picture(whole)["coverage"] == moment("picture_accounts_all")
    assert _picture(short)["coverage"] == moment(
        "picture_accounts_all_incomplete")


def test_the_panel_sentence_resolves_itself_and_the_figure_still_discloses():
    """The panel's sentence and the figure's disclosure are two things.

    The panel's sentence carries its own resolution, because what else is short
    of whole is said on a figure — a different card, and possibly one of
    several — so a line relying on what follows it relies on a layout it cannot
    see. And the figure still says it, because the panel resolving itself is
    not a reason for the detail to stop being disclosed where it belongs."""
    short = LedgerProjection(_two_currencies() + [
        statement_held("doc-held", {"account_ref": "acct:home"}, None, "gap",
                       "2026-07-02")])

    picture = _picture(short)

    assert picture["coverage"] == moment("picture_accounts_all_incomplete")
    for figure in picture["figures"]:
        assert moment("picture_boundary_unposted_one") in figure["coverage"]


def test_the_four_ways_of_saying_how_far_the_picture_reaches_are_all_distinct():
    """Every arm is a whole reviewed line and no two are the same words. Two
    arms sharing a sentence is two states a person cannot tell apart."""
    said = {moment("picture_accounts_all"),
            moment("picture_accounts_all_incomplete"),
            moment("picture_accounts_one", held=render.count(2)),
            moment("picture_accounts_some", counted=render.count(2),
                   held=render.count(3))}

    assert len(said) == 4


def test_the_shapes_no_vault_reaches_are_each_exercised_somewhere():
    """A key assertion over an empty list passes without checking anything.

    Both of these are absent from the one real vault, and one is absent from
    the parity fixture by construction: a withheld currency needs a boundary
    term the shipped pack has no reviewed line for, which a shipped pack cannot
    have. So each is driven here, non-empty, and this names where — a list of
    ruled behaviours nothing anywhere demonstrates is a different claim from
    one verified against a fixture."""
    projection = LedgerProjection(_picture_events())

    unplaced = _picture(LedgerProjection(_unplaceable()))["unplaced"]
    withheld = _without_a_currency(projection, "EUR")["withheld"]

    assert unplaced, "nothing exercises an account beneath no figure"
    assert withheld, "nothing exercises a currency whose total is kept back"
    for entry in unplaced + withheld:
        assert entry["sentence"].strip()


def test_the_denominator_sees_an_account_no_read_has_ever_met():
    """The point is authoritative about what it valued. It is not authoritative
    about what is held.

    A ruling brings an account into being by naming it on a leg. One nothing
    has yet been posted to reaches no read at all — every read that would find
    it finds it through movements it has none of — so it is in no line, no
    refusal and no skip. A denominator taking the point's word for what a
    person holds would report their whole picture as covered while something
    they hold sat outside it, and nothing would go red.

    Two declared sets, compared as data: neither can shrink the count on its
    own."""
    from viva.ledger.events import ruling_recorded

    held = _events()
    silent = ruling_recorded(
        scope="merchant", subject="nobody at all",
        legs=[{"major": "liability", "account": "Liabilities:Loan:Silent"}],
        occurred_at="2026-07-01", by="human")
    without = LedgerProjection(held)
    with_it = LedgerProjection(held + [silent])

    # No read meets it: not the point, and not the accounts read.
    point = networth.net_worth(with_it, "2026-09-30")
    ranged = ({line.account for line in point.lines}
              | {row["account"] for row in point.missing}
              | {row["account"] for row in point.skipped})
    assert "Liabilities:Loan:Silent" not in ranged
    assert "Liabilities:Loan:Silent" not in _held(with_it)

    assert _picture(without)["coverage"] == moment("picture_accounts_all")
    assert _picture(with_it)["coverage"] == moment("picture_accounts_one",
                                                   held=render.count(2))


def test_neither_declared_set_can_shrink_the_denominator_on_its_own():
    """Held by both sources, so removing either one is caught. A denominator
    from a single source can omit an account without anything going red, which
    is the property the amendment is about rather than any one number."""
    from viva.ledger.events import ruling_recorded

    projection = LedgerProjection(_events() + [ruling_recorded(
        scope="merchant", subject="nobody at all",
        legs=[{"major": "liability", "account": "Liabilities:Loan:Silent"}],
        occurred_at="2026-07-01", by="human")])
    point = networth.net_worth(projection, "2026-09-30")
    ranged = ({line.account for line in point.lines}
              | {row["account"] for row in point.missing}
              | {row["account"] for row in point.skipped})
    vault = overview_module._vault_accounts(projection, _held(projection))

    assert ranged, "the point ranged over nothing; this walks an empty set"
    assert vault, "the vault declared no accounts; this walks an empty set"
    # Each set holds something the other does not, so neither is sufficient.
    # The vault knows an account the point never met, so the point alone is
    # not sufficient — which is the whole of what the amendment says.
    assert vault - ranged == {"Liabilities:Loan:Silent"}
    assert len(ranged | vault) > len(ranged)


def test_the_pictures_read_is_pinned_to_the_arguments_that_cannot_refuse():
    """What stops the one who does not read the comment.

    The picture's call takes no filters, no `as_of`, no `matching` and no
    `group_by`, and with those arguments every refusal `query_ledger` can
    construct sits behind a branch it cannot enter — `_aggregate_net_worth`
    constructs none at all. That is a fact about these arguments and not a
    property of the read, so it is pinned here rather than trusted.

    A comment saying so would be read by whoever already agreed with it. This
    goes red."""
    widening = ("filters", "as_of", "matching", "group_by")
    tool, arguments = NET_WORTH
    why = ("widening this call opens refusal tags with no reviewed sentence, "
           "and that is a Checkpoint 1 decision before it is a diff")

    assert tool == "query_ledger", why
    assert arguments == {"entity": "aggregate", "metric": "net_worth"}, why
    for narrowing in widening:
        assert narrowing not in arguments, f"{narrowing}: {why}"


def test_a_read_that_fails_leaves_the_picture_saying_something_it_reviewed():
    """A read this call cannot make fail, handled anyway — and handled by
    saying less rather than by saying something nobody reviewed.

    What a refusal carries is the tool's own machinery words. There is no
    reviewed sentence for a branch nothing can enter, and a pack line that
    cannot be said devalues the ones that can, so the panel says the one thing
    it can stand behind. What it does not do is render empty: a blank where a
    figure was is read as the product being broken."""
    turned_down = envelope.refusal("query_ledger", "as_of_in_the_future",
                                   "I cannot answer for a day that has not "
                                   "happened yet; entity, metric, read.")

    picture = overview_module._picture(turned_down, "en-US", "2026-09-30", {},
                                       set())

    assert picture["figures"] == []
    assert picture["coverage"] == moment("picture_no_figure")
    assert picture["read_on"] == "2026-09-30"
    # Nothing the tool wrote crosses, and no field carries it.
    assert turned_down.text not in str(picture)
    assert turned_down.refusal not in str(picture)
    assert set(picture) == {"coverage", "read_on", "figures", "withheld",
                            "unplaced"}
