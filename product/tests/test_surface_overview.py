"""The composer that turns one read into the picture a person is shown."""

from __future__ import annotations

import pytest

from viva.ledger import (LedgerProjection, Provenance, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import position_observed
from viva.surface.models import PanelState
from viva.surface.overview import overview


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

    american = overview(projection, "en-US")["accounts"][0]["balance"]
    german = overview(projection, "de-DE")["accounts"][0]["balance"]

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

    picture = overview(projection, "en-US")
    withheld = [row for row in picture["accounts"] if row["balance"] is None]

    assert picture["state"] == PanelState.PARTIAL.value
    assert [row["account"] for row in withheld] == ["acct:two"]
    assert len(picture["issues"]) == 1
    assert "Unmeasured Savings" in picture["issues"][0]["message"]
    assert picture["issues"][0]["code"]


def test_a_panel_says_ready_only_when_every_row_carries_its_figure():
    projection = LedgerProjection(_events())

    picture = overview(projection, "en-US")

    assert picture["state"] == PanelState.READY.value
    assert picture["issues"] == []
    assert all(row["balance"] for row in picture["accounts"])


def test_a_ledger_bucket_is_not_an_account_on_the_picture():
    """The buckets a transaction posts against are in the projection and are
    not things a person holds. The read this surface asks is the one that
    already refuses them, so nothing here has to know their names."""
    projection = LedgerProjection(_events())

    shown = {row["account"] for row in overview(projection, "en-US")["accounts"]}

    assert shown == {"acct:one"}
    assert len(shown) < len(list(projection.account_infos()))


def test_an_empty_vault_shows_no_rows_and_withholds_nothing():
    picture = overview(LedgerProjection([]), "en-US")

    assert picture["accounts"] == []
    assert picture["state"] == PanelState.READY.value
    assert picture["issues"] == []


@pytest.mark.parametrize("locale", ["en-US", "en-IN"])
def test_every_figure_carries_a_citation_to_the_records_it_stands_on(locale):
    """The route is to the document the figure itself declares among its
    records, under the word the grade supports: a figure an issuer's own
    document states is attested by it."""
    picture = overview(LedgerProjection(_events()), locale)
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

    figure = overview(projection, "en-US")["accounts"][0]["balance"]

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

    figure = overview(projection, "en-US")["accounts"][0]["balance"]

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

    figure = overview(projection, "en-US")["accounts"][0]["balance"]

    assert figure["grade"] == "conflicted"
    assert "tolerance" in explanation
    assert "tolerance" not in str(figure)
