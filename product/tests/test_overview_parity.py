"""The one artifact the backend and the interface are both held to.

Half of this contract lives here and half in `desktop/src/surface/adapters/
overview-parity.test.ts`, and both halves read the same committed bytes. The
bytes are produced by running the real provider through the real dispatch over
a vault built in code, so neither side can satisfy itself alone: a backend that
drops a field fails the comparison below, and a regenerated fixture then fails
the interface's half.

What is asserted here is not a shape. It is that a person opening a populated
vault sees a number on every account and a route from it to the record it was
read from.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from viva.quantity import MEASURES
from viva.surface import CURRENT_PROTOCOL
from viva.surface.models import CitationRelation, FigureGrade, PanelState

ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "scripts" / "generate_overview_parity_fixture.py"
FIXTURE = ROOT / "product" / "viva" / "surface" / "fixtures" / "overview-parity-v1.json"


def _generator():
    spec = importlib.util.spec_from_file_location("overview_parity", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(FIXTURE.read_bytes())


@pytest.fixture(scope="module")
def overview(committed) -> dict:
    return committed["reads"]["overview"]["result"]["data"]


def test_the_committed_fixture_is_what_the_product_produces():
    """The whole gate. A change to the provider, the composer, a grade, the
    pack's wording or the money renderer moves these bytes, and a fixture that
    was not regenerated with it says so with a diff a person can read."""
    assert FIXTURE.read_bytes() == _generator().encoded_artifact(), (
        "the committed overview parity fixture is not what the product "
        "returns; run scripts/generate_overview_parity_fixture.py --write and "
        "read the diff before accepting it"
    )


def test_the_fixture_is_generated_and_never_authored():
    """A fixture somebody wrote by hand is a description of the contract its
    author wished for. This one is what a shell would receive: a whole
    response frame per surface, protocol and all."""
    module = _generator()
    built = module.build_artifact()

    assert built["protocol"] == CURRENT_PROTOCOL.wire()
    for surface in module.SURFACES:
        frame = built["reads"][surface]
        assert frame["ok"] is True
        assert frame["protocol"] == CURRENT_PROTOCOL.wire()
        assert frame["result"]["surface"] == surface


def test_the_vault_behind_the_fixture_holds_every_shape_a_read_can_meet(committed, overview):
    """Eight shapes, because a fixture that meets only the easy ones proves
    the easy ones. What each shape is, is read off what the accounts declare
    rather than off their names."""
    figures = [account["balance"] for account in overview["accounts"]]

    assert len(figures) == 8
    assert {figure["grade"] for figure in figures} == {
        grade.value for grade in FigureGrade}
    assert {figure["measure"] for figure in figures} == {"balance", "owed"}
    assert len({figure["currency"] for figure in figures}) > 1
    # One owed on and in credit, one whose newest record is older than the day
    # the fixture is written as of.
    assert any(figure["measure"] == "owed"
               and figure["exact_value"].startswith("-") for figure in figures)
    assert any(figure["as_of"] < committed["today"][:4] + "-01-01"
               for figure in figures)


def test_no_ledger_bucket_is_shown_as_an_account(overview):
    """The read that answers a question refuses a bucket as an account, and
    this surface is that read. A spending category listed beside a person's
    accounts is the thing this proves cannot happen."""
    paths = [account["account"] for account in overview["accounts"]]

    assert paths
    assert not [path for path in paths
                if path.startswith(("Expenses:", "Income:", "Equity:",
                                    "Transfers:"))]


def test_every_account_carries_a_figure_a_person_can_read(overview):
    """The bug this cycle exists to fix, stated as an assertion: a populated
    vault renders a number, in a currency, measured on a day, under a word
    saying how well it is stood behind, and says what it covers."""
    for account in overview["accounts"]:
        figure = account["balance"]
        where = account["account"]

        assert figure is not None, where
        assert figure["display"].strip(), where
        assert figure["exact_value"].strip(), where
        assert figure["currency"], where
        assert figure["measure"] in MEASURES, where
        assert figure["as_of"].strip(), where
        assert figure["coverage"].strip(), where
        assert figure["exactness"].strip(), where
        assert figure["grade"] in {grade.value for grade in FigureGrade}, where
        assert figure["grade_label"] == figure["grade"], where
        assert figure["grade_description"].strip(), where
        assert figure["record_ids"], where


def test_every_figure_states_its_own_boundary_and_no_vault_wide_count(overview):
    """A card says what its own figure is over. How many accounts a person
    holds is true of the vault rather than of any figure, and a line repeated
    identically on every card is a line the eye learns to skip."""
    coverages = [account["balance"]["coverage"]
                 for account in overview["accounts"]]

    assert len(set(coverages)) == len(coverages)
    for account in overview["accounts"]:
        assert account["name"] in account["balance"]["coverage"]
        assert account["balance"]["as_of"] in account["balance"]["coverage"]


def test_every_figure_routes_to_the_records_it_stands_on(committed, overview):
    """A number with no route to its source is a number this product has no
    business showing. Every citation names a document the documents read holds,
    because a route to a row nobody can open is not a route — and it names one
    the figure itself declares it stands on, rather than one found beside it."""
    documents = {document["id"] for document
                 in committed["reads"]["documents"]["result"]["data"]["documents"]}
    relations = {relation.value for relation in CitationRelation}

    assert documents
    for account in overview["accounts"]:
        figure = account["balance"]
        assert figure["citations"], account["account"]
        for citation in figure["citations"]:
            assert citation["document_id"] in documents, account["account"]
            assert citation["document_id"] in figure["record_ids"], account["account"]
            assert citation["relation"] in relations, account["account"]


def test_no_figure_claims_where_in_a_document_it_was_printed(overview):
    """An account's worth can be its cash summed with the holdings measured
    beside it. The read records where one part was printed and nothing about
    where the others were, so no figure offers a part's page as the page of
    the whole. When the read can say where each part is, this is the gate that
    says so."""
    pages = {citation["page"] for account in overview["accounts"]
             for citation in account["balance"]["citations"]}

    assert pages == {""}


def test_no_figure_carries_prose_written_about_a_different_number(overview):
    """The sentence the balances view writes is about an account's balance,
    which a composed figure is only one part of, and it carries the arithmetic
    of a failed check. Neither belongs under a figure a person is reading."""
    assert not [account for account in overview["accounts"]
                if account["balance"]["provenance"]]


def test_a_figure_read_off_a_document_says_so_and_a_replayed_one_does_not(overview):
    """Corroboration is a second witness. A figure an issuer's own document
    states is attested by it; one replayed from what is on record was read off
    nothing, and calling that attestation is the small lie this product sells
    against."""
    for account in overview["accounts"]:
        figure = account["balance"]
        attested = figure["grade"] != FigureGrade.UNVERIFIED.value
        for citation in figure["citations"]:
            said = citation["relation"] == CitationRelation.ATTESTS.value
            assert said is attested, account["account"]


def test_the_panel_is_ready_only_when_no_row_withholds_its_figure(overview):
    """`ready` means this read succeeded and here is the answer. A panel
    reporting it over a row with no number says the read succeeded when it
    half did."""
    withheld = [account for account in overview["accounts"]
                if account["balance"] is None]

    assert overview["state"] == (PanelState.PARTIAL.value if withheld
                                 else PanelState.READY.value)
    assert len(overview["issues"]) == len(withheld)


def test_a_read_keeps_its_own_limits_and_puts_them_on_no_figure(overview):
    """A read writes one sentence about the set it took its numbers over. Put
    on a figure, it would say of one account what was true of another."""
    assert overview["caveats"]
    assert not [account for account in overview["accounts"]
                if account["balance"]["caveats"]]
