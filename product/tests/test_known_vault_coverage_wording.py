"""Picture coverage describes recorded accounts, never an external inventory."""

import pytest

from viva.ledger import LedgerProjection, account_opened, closing_balance_observed
from viva.ledger.events import statement_held
from viva.surface.overview import overview

TODAY = "2026-09-30"
ALL = "Every account recorded in this vault is counted here."
INCOMPLETE = ("Every account recorded in this vault is counted here, "
              "though some information in the vault is not included.")
ONE = "Only one of the 2 accounts recorded in this vault is counted here."
SOME = "2 of the 3 accounts recorded in this vault are counted here."


def recorded_account(key, measured=True, currency="USD", day="2026-09-01"):
    rows = [account_opened(key, "depository", "Invented account", currency, day)]
    if measured:
        rows.append(closing_balance_observed(key, "123.45", day))
    return rows


def cases():
    from decimal import Decimal
    from viva.ingest import StatementFacts
    one = recorded_account("invented-one")
    held = StatementFacts(doc_id="invented-held", doc_type="checking_statement",
        doc_type_confidence=1, account_ref="Invented held account", currency="USD",
        opening_amount=Decimal("100"), opening_date="2026-09-01",
        closing_amount=Decimal("100"), closing_date="2026-09-12", transactions=[])
    return [
        (one, ALL),
        (one + [statement_held("invented-held", held.to_dict(), None, "gap", TODAY)], INCOMPLETE),
        (one + recorded_account("invented-two", measured=False), ONE),
        (one + recorded_account("invented-two", currency="EUR")
         + recorded_account("invented-three", measured=False), SOME),
    ]


@pytest.mark.parametrize("events,expected", cases())
def test_coverage_literal_is_bounded_to_recorded_accounts(events, expected):
    picture = overview(LedgerProjection(events), "en-US", TODAY)["picture"]
    assert picture["coverage"] == expected
    assert "you hold" not in picture["coverage"]


@pytest.mark.parametrize("events,expected", cases() + [([], None)])
def test_sql_and_event_coverage_match_without_inventory_assertion(tmp_path, events, expected):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore
    source = EventStore.open(tmp_path / "events", "synthetic-passphrase")
    source.append_atomically(lambda _: tuple(events))
    with ReadStore.create(tmp_path / "read", "synthetic-passphrase") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = overview(revision.overview_projection(today=TODAY), "en-US", TODAY)
    assert actual == overview(LedgerProjection(events), "en-US", TODAY)
    if expected:
        assert actual["picture"]["coverage"] == expected
    else:
        assert actual["picture"]["figures"] == []
        assert "Every account" not in actual["picture"]["coverage"]


@pytest.mark.parametrize("events", [row[0] for row in cases()] + [[],
    recorded_account("invented-one") + recorded_account("invented-two", day="2026-09-12")])
def test_other_payload_is_identical_to_previous_coverage_pack(monkeypatch, events):
    from viva.persona import moment
    from viva.surface import overview as module
    projection = LedgerProjection(events)
    current = overview(projection, "en-US", TODAY)
    monkeypatch.setattr(module, "moment", lambda key, **fields:
                        moment(key, version="pack-v46", **fields))
    previous = overview(projection, "en-US", TODAY)
    current["picture"].pop("coverage")
    previous["picture"].pop("coverage")
    assert current == previous


def test_withheld_currency_keeps_its_accounts_in_the_known_denominator(monkeypatch):
    from viva.surface import overview as module
    events = recorded_account("invented-one") + recorded_account("invented-two", currency="EUR")
    original = module._picture_figure

    def withhold(figure, *args, **kwargs):
        return None if figure["currency"] == "EUR" else original(figure, *args, **kwargs)

    monkeypatch.setattr(module, "_picture_figure", withhold)
    picture = overview(LedgerProjection(events), "en-US", TODAY)["picture"]
    assert picture["coverage"] == ONE
    assert [figure["currency"] for figure in picture["figures"]] == ["USD"]
    assert picture["withheld"]


def test_new_pack_changes_only_the_four_reviewed_coverage_moments():
    import json
    from pathlib import Path
    from viva import persona
    root = Path(persona.__file__).parent
    before = root / "pack-v46"
    after = root / "pack-v47"
    assert (before / "phrasings.json").read_bytes() == (after / "phrasings.json").read_bytes()
    assert (before / "tone.md").read_bytes() == (after / "tone.md").read_bytes()
    old = json.loads((before / "moments.json").read_text())
    new = json.loads((after / "moments.json").read_text())
    assert old.keys() == new.keys()
    assert {key for key in old if old[key] != new[key]} == {
        "picture_accounts_all", "picture_accounts_all_incomplete",
        "picture_accounts_one", "picture_accounts_some"}


def test_known_coverage_preserves_mixed_dates_and_unavailable_standing():
    from viva.persona import moment
    events = recorded_account("invented-one") + recorded_account("invented-two", day="2026-09-12")
    picture = overview(LedgerProjection(events), "en-US", TODAY)["picture"]
    assert picture["coverage"] == ALL
    figure, = picture["figures"]
    qualifications = figure["proof_presentation"]["qualifications"]
    assert any("records of more than one date" in line for line in qualifications)
    assert moment("proof_missing_evidence") in qualifications
    assert figure["as_of"] == TODAY
    assert figure["exact_value"] == "246.90"
