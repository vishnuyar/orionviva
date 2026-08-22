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
import shutil
import tempfile
from pathlib import Path

import pytest

from viva import render
from viva.ledger.projection.movements import leading_account
from viva.desktop_bridge import vault_surface
from viva.persona import moment
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


def test_the_writer_produces_the_same_bytes_on_any_machine(monkeypatch):
    """One writer means one writer, which a generator reading the machine it
    runs on is not.

    Every setting the product reads that would move these bytes is stated by
    the script and applied for the length of the run. A machine with reader
    keys exported would otherwise write a different sentence about reading into
    the same artifact, and the byte comparison above would fail for no drift.
    """
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "some-adapter")
    monkeypatch.setenv("VIVA_MODEL", "some-pinned-model")
    monkeypatch.setenv("VIVA_LOCALE", "de-DE")

    assert FIXTURE.read_bytes() == _generator().encoded_artifact()


def test_the_writer_produces_the_same_bytes_on_any_day(monkeypatch):
    """The clock is a setting like the others, and this varies it rather than
    hoping.

    A picture is good as of the day it was read on, so a generator that let the
    day default would write the day it ran into these bytes. Left to chance the
    check would pass merely because the stated day and the running day differ,
    and a machine whose calendar reached the stated day would find it green for
    a reason it never claimed — so one of the days below **is** the stated day,
    which is the case that hole hides in.
    """
    module = _generator()
    monkeypatch.setattr(vault_surface, "_now", lambda: "2027-03-01")
    far_off = module.encoded_artifact()
    monkeypatch.setattr(vault_surface, "_now", lambda: module.TODAY)
    on_the_day = module.encoded_artifact()

    assert far_off == on_the_day
    assert FIXTURE.read_bytes() == far_off


def test_no_document_is_settled_without_a_reading_behind_it():
    """A parity fixture may hold only combinations real ingest can reach.

    Nothing posts through this product without a model having been asked, so a
    row that is resolved and reads as never read is a state the ingest path
    cannot produce. Rendering it would prove the presentation of something that
    cannot happen, and teach the next reader a false thing about the words.
    """
    documents = None
    for surface, frame in json.loads(FIXTURE.read_bytes())["reads"].items():
        if surface == "documents":
            documents = frame["result"]["data"]

    assert documents["documents"]
    for row in documents["documents"]:
        if row["resolved"]:
            assert row["reading"] == "read", row["id"]
    # And the vault holds one nothing has read, because a fixture whose whole
    # value is parity has to carry the state this read exists to say out loud.
    unread = [row for row in documents["documents"]
              if row["reading"] == "never_read"]
    assert unread and not any(row["resolved"] for row in unread)
    assert documents["reading_sentence"]


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
    """A populated vault renders a number, in a currency, measured on a day,
    under a word saying how well it is stood behind, and says what it
    covers."""
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


def _built_and_read(module) -> tuple[set, dict]:
    """The accounts the fixture's vault was built with, read off the events
    that bring one into being rather than off any read of them, and the picture
    the product composes over that same vault.

    There are two such events, and counting only the first is a proxy rather
    than a measurement: a document opens an account, and a ruling brings one
    into being by naming it on a leg. A person holds both."""
    directory = Path(tempfile.mkdtemp(prefix="orionviva-parity-accounts-"))
    try:
        with module._stated_environment():
            vault = module.build_vault(directory / "vault")
            built = set()
            for event in vault.ledger.events():
                if event.event_type == "AccountOpened":
                    built.add(event.body["account_id"])
                # Which account a ruling brings into being is the ledger's own
                # question, answered by the ledger's own function: a ruling
                # whose legs name only a category brings no account into being,
                # and this measurement holds no second opinion about that.
                brought = leading_account(event.body.get("legs") or [])
                if brought:
                    built.add(brought)
            reads = module.read_surfaces(vault)
    finally:
        shutil.rmtree(directory, ignore_errors=True)
    return built, reads["overview"]["result"]["data"]["picture"]


def test_the_picture_reaches_the_screen_with_its_citation(committed, overview):
    """What this item exists for, stated as an assertion: a populated vault
    renders a total per currency, in a currency, good as of a stated day, under
    a word saying how well it is stood behind, saying what it covers and
    routing back to the records beneath it."""
    documents = {document["id"] for document
                 in committed["reads"]["documents"]["result"]["data"]["documents"]}
    picture = overview["picture"]

    assert documents
    assert picture["figures"]
    for figure in picture["figures"]:
        where = figure["currency"]
        assert figure["measure"] == "net_worth", where
        assert figure["display"].strip(), where
        assert figure["exact_value"].strip(), where
        assert figure["currency"], where
        assert figure["as_of"] == picture["read_on"], where
        # One sentence to a line: the interface stacks them without ever
        # looking for a join in the punctuation.
        assert figure["coverage"], where
        assert all(line.strip() for line in figure["coverage"]), where
        assert figure["grade"] in {grade.value for grade in FigureGrade}, where
        assert figure["grade_description"].strip(), where
        assert figure["citations"], where
        for citation in figure["citations"]:
            assert citation["document_id"] in documents, where
            assert citation["page"] == "", where


def test_the_picture_subtotals_per_currency_and_totals_none_of_them(overview):
    """Per-currency subtotals and no grand total anywhere. There is no rate
    with a source, a date and a grade of its own, so a number across currencies
    would be a figure no document attests — and nothing here adds two of them
    together in order to check that nothing else did."""
    currencies = [figure["currency"] for figure in overview["picture"]["figures"]]

    assert len(currencies) > 1
    assert len(set(currencies)) == len(currencies)
    assert {account["balance"]["currency"] for account in overview["accounts"]} \
        == set(currencies)


def test_the_pictures_denominator_is_every_account_the_vault_holds():
    """The tripwire under the one thing nobody could establish by reading: that
    the accounts a point ranges over are the accounts a person holds.

    The denominator is measured against the accounts the generator brought into
    being, which is what the vault holds, and not against the rows this surface
    happens to show. If this ever disagrees, the assumption is wrong and the
    number is not the thing to adjust.

    Asserted as sets and not merely as counts, because two sets of one size can
    still be two different sets, and it is the membership the assumption is
    about."""
    opened, picture = _built_and_read(_generator())
    stood_on = {account for figure in picture["figures"]
                for account in figure["record_ids"]}
    named = ({entry["account"] for entry in picture["unplaced"]}
             | {entry["account"] for figure in picture["figures"]
                for entry in figure["unmeasured"]})

    assert opened
    assert stood_on
    assert stood_on <= opened
    # Every account the vault holds is either counted in a total or said to be
    # out of one. Nothing a person holds goes unaccounted for either way.
    assert stood_on | named == opened, sorted(opened - (stood_on | named))
    if len(stood_on) == len(opened):
        expected = moment("picture_accounts_all")
    elif len(stood_on) == 1:
        expected = moment("picture_accounts_one", held=render.count(len(opened)))
    else:
        expected = moment("picture_accounts_some",
                          counted=render.count(len(stood_on)),
                          held=render.count(len(opened)))
    assert picture["coverage"] == expected


def test_the_fixture_carries_both_shapes_that_make_the_coverage_line_do_work(overview):
    """A document read and not posted, and an account no point can value. They
    are the two ways a total is less than the whole of what a person holds, and
    without them the coverage sentence is walked over an empty set.

    What is asserted is that the total is NOT withheld in their presence: a
    cycle that blanks the hero on the first vault that has either of them has
    shipped the failure this fixture exists to catch."""
    picture = overview["picture"]

    assert picture["figures"]
    assert picture["coverage"] != moment("picture_no_figure")
    # The unposted document belongs to no account, so it is said of every
    # total. The unvalued account belongs to one currency, so it is said of
    # the total that would otherwise have carried it and of no other.
    for figure in picture["figures"]:
        assert moment("picture_boundary_unposted_one") in figure["coverage"]
    said = [figure["currency"] for figure in picture["figures"]
            if moment("picture_boundary_unmeasured_one") in figure["coverage"]]
    assert len(said) == 1, said


def test_the_picture_states_the_day_it_was_read_on_and_no_second_date_beside_it(committed, overview):
    """The day the read was made, which the read was given and recorded, and
    which is not the projection horizon a letter away from it.

    How old the evidence beneath the picture is, is said on each figure and
    carried as no panel field: over the whole picture it would be a claim true
    of one currency's lines and false of another's, and nothing renders it.

    The oldest measurement is also the fact the mixed-vintage caveat carries in
    machine words, which is why that caveat is not rendered."""
    picture = overview["picture"]

    assert picture["read_on"] == committed["today"]
    assert set(picture) == {"coverage", "read_on", "figures", "withheld",
                            "unplaced"}
    for figure in picture["figures"]:
        assert moment("picture_oldest_input",
                      date=render.date(figure["as_of"])) not in figure["coverage"]
    assert overview["as_of"] is None


def test_the_committed_picture_announces_every_figure_it_carries(overview):
    """The half of the announcement contract that lives on this side. The
    interface reads these words out of the bytes below rather than composing
    names of its own, so a figure arriving without them is an interface falling
    back to something nobody reviewed — and a fallback nothing notices is the
    defect the announcement exists to prevent."""
    figures = overview["picture"]["figures"]

    assert len(figures) > 1
    for figure in figures:
        currency = render.label(figure["currency"])
        assert figure["evidence_label"] == moment("picture_evidence_label",
                                                  currency=currency)
        assert figure["evidence_heading"] == moment("picture_evidence_heading",
                                                    currency=currency)
    assert len({figure["evidence_label"] for figure in figures}) == len(figures)
    assert len({figure["evidence_heading"] for figure in figures}) == len(figures)


def test_the_committed_picture_says_why_each_account_is_left_out(overview):
    """MON-27 reaching a person on the one artifact both sides read. The panel
    counts the accounts a total could not value and never names them, and that
    is only honest because the figure beside it names each one and says why —
    which is the half that tells a person whether anything is theirs to do."""
    figures = overview["picture"]["figures"]
    said = [entry for figure in figures for entry in figure["unmeasured"]]

    assert figures
    assert said, "the fixture holds an account no point can value; it is said"
    for figure in figures:
        # Scoped to the figure's own currency: the accounts the read declared
        # are the accounts the read declared for every currency at once, and a
        # figure naming one held elsewhere makes a person count two gaps where
        # the panel says one.
        assert len(figure["unmeasured"]) <= len(figure["boundary"]["unmeasured"])
        for entry in figure["unmeasured"]:
            # The sentence is what crosses. The token that chose it did its
            # work backend-side and is not carried beside its own output.
            assert set(entry) == {"account", "name", "sentence"}
            assert entry["sentence"].strip()
            assert entry["name"].strip()
            # The written name travels with the account, so nothing on the
            # other side of the bridge resolves a path a second way.
            assert entry["name"] in entry["sentence"]
            assert entry["account"] not in entry["sentence"]
            reason, = [row["reason"] for row in figure["boundary"]["unmeasured"]
                       if row["account"] == entry["account"]]
            # The token is a machine's word and never reaches a person.
            assert reason not in entry["sentence"]
    # And one gap is said once across the whole picture, not once per currency.
    assert len(said) == len({entry["account"] for entry in said})


def test_the_committed_picture_leaves_no_account_named_nowhere(overview):
    """Condition 25 on the artifact both sides read. Every account the read
    could not value is named somewhere a person can reach — on the figure that
    would otherwise have carried it, or, where no figure could, at the panel.

    The fixture holds no unplaceable account today, so what this asserts on
    these bytes is the invariant rather than the case: the set of gaps the
    read declared is exactly the set said somewhere."""
    picture = overview["picture"]
    declared = {row["account"] for figure in picture["figures"]
                for row in figure["boundary"]["unmeasured"]}
    said = {entry["account"] for figure in picture["figures"]
            for entry in figure["unmeasured"]}
    said |= {entry["account"] for entry in picture["unplaced"]}

    assert declared, "the fixture holds an account no point can value"
    assert declared == said, sorted(declared - said)
    for entry in picture["unplaced"]:
        # An account the picture could not place is the one thing here a
        # person may be told about and find nowhere else, so what the read
        # said about it crosses with it.
        assert set(entry) == {"account", "name", "sentence"}
        assert entry["sentence"].strip()
        assert entry["name"].strip()
        assert entry["account"] not in entry["sentence"]


def test_the_committed_picture_names_an_account_beneath_no_figure(overview):
    """The shape the parity fixture can carry, carried.

    A debt a ruling brought into being: the point refuses it a figure, nothing
    opened it so no accounts read names it, and no currency can be found for
    it. It is on no card and in no total, so the panel is the only place it can
    be said — and an assertion over an empty list would have passed without
    ever checking that it is."""
    unplaced = overview["picture"]["unplaced"]

    assert unplaced, "the fixture no longer carries an account beneath no figure"
    for entry in unplaced:
        assert set(entry) == {"account", "name", "sentence"}
        assert entry["sentence"].strip()
        assert entry["account"] not in entry["sentence"]
    # And it is not on any card, which is what makes naming it here the only
    # way a person can reach it at all.
    shown = {account["account"] for account in overview["accounts"]}
    assert not {entry["account"] for entry in unplaced} & shown


def test_the_committed_caveats_carry_what_every_read_declared(overview):
    """Both reads this composer makes reach the caveat field, so a caveat the
    net-worth read declares and the balances read does not survives transport
    rather than being dropped in it."""
    assert len(overview["caveats"]) > 1
    for said in overview["caveats"]:
        assert said.strip()
