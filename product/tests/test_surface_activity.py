"""What moved, and which way it went.

Direction is the whole of why this read could not ship before: on a card a
purchase posts positive, and a read that took the sign would have told a person
money arrived. Every test here is about that, or about a row that is not plain
spending saying what it is.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger.projection.movements import (BY_CATEGORY, BY_LINK, MIXED,
                                              SPENDING, TRANSFER)
from viva.persona import moment
from viva.surface.activity import activity
from viva.vault import Vault


class _Movement:
    def __init__(self, *, key="m1", kind="asset", amount="10.00",
                 date="2026-07-01", description="a shop", account="acct:one",
                 currency="USD", nature=SPENDING, reason="default",
                 provisional=False, linked=False, ruling_account=""):
        self.key = key
        self.kind = kind
        self.amount = Decimal(amount)
        self.date = date
        self.description = description
        self.account = account
        self.currency = currency
        self.nature = nature
        self.nature_reason = reason
        self.provisional = provisional
        self.linked = linked
        self.ruling_account = ruling_account


class _Projection:
    def __init__(self, movements) -> None:
        self._movements = list(movements)

    def movements(self):
        return list(self._movements)


def _read(movements, **kwargs) -> dict:
    return activity(_Projection(movements), "en-US", **kwargs)


def test_a_purchase_on_a_card_is_money_leaving():
    """The defect the direction site carried. A charge posts positive — what is
    owed grew — and a sign alone reads that as money arriving."""
    read = _read([_Movement(kind="liability", amount="120.00")])

    assert read["items"][0]["direction"] == "out"
    assert read["items"][0]["exact_value"] == "120.00"


def test_a_purchase_on_a_current_account_is_money_leaving_too():
    read = _read([_Movement(kind="asset", amount="-120.00")])

    assert read["items"][0]["direction"] == "out"


def test_money_arriving_is_money_arriving_on_either_kind():
    on_asset = _read([_Movement(kind="asset", amount="500.00")])
    on_card = _read([_Movement(kind="liability", amount="-500.00")])

    assert on_asset["items"][0]["direction"] == "in"
    assert on_asset["items"][0]["treatment"] == {
        "kind": "not_spending", "name": ""}
    assert on_card["items"][0]["direction"] == "in"


def test_a_named_loan_keeps_its_direction_and_name_in_the_read():
    lent = _read([_Movement(
        amount="-100.00", nature=TRANSFER,
        ruling_account="Assets:Loans:Sam")])
    repaid = _read([_Movement(
        amount="30.00", nature=TRANSFER,
        ruling_account="Assets:Loans:Sam")])

    assert lent["items"][0]["treatment"] == {"kind": "loan", "name": "Sam"}
    assert repaid["items"][0]["treatment"] == {
        "kind": "loan_repayment", "name": "Sam"}


def test_a_movement_with_no_account_kind_stops_the_read_rather_than_guessing():
    with pytest.raises(ValueError, match="decided by its account's kind"):
        _read([_Movement(kind="")])


def test_the_amount_travels_unsigned_beside_the_word():
    """A sign and a word saying the same thing are two chances to disagree."""
    read = _read([_Movement(kind="liability", amount="120.00")])

    assert read["items"][0]["exact_value"] == "120.00"
    assert "-" not in read["items"][0]["display"]


def test_a_focused_row_stays_on_the_bounded_page_after_review():
    movements = [
        _Movement(key=f"movement:{index:02d}", date=f"2026-07-{index + 1:02d}")
        for index in range(31)
    ]

    read = _read(movements, limit=10, focus="movement:00")

    assert len(read["items"]) == 10
    assert "movement:00" in {item["id"] for item in read["items"]}
    assert read["beyond"] == {"count": 21}


# ------------------------------------------------ what a row is, beyond spending


def test_a_row_that_is_plain_spending_says_nothing_extra():
    """A line saying "this is spending" on every spending row is a line that
    stops being read."""
    read = _read([_Movement()])

    assert read["items"][0]["sentence"] == ""


def test_money_between_a_persons_own_pockets_says_it_is_not_spending():
    read = _read([_Movement(nature=TRANSFER, reason=BY_LINK, linked=True)])

    assert read["items"][0]["sentence"] == moment("activity_transfer")
    assert read["items"][0]["linked"] is True


def test_a_row_held_out_of_spending_on_weak_evidence_says_which_it_is():
    """That it rests on a hint is the more important fact, and the one that
    explains why a total moved."""
    read = _read([_Movement(nature=TRANSFER, reason=BY_CATEGORY,
                            provisional=True)])

    assert read["items"][0]["sentence"] == moment("activity_provisional")
    assert read["items"][0]["provisional"] is True


def test_a_movement_whose_proportions_are_unknown_gets_its_own_line():
    read = _read([_Movement(nature=MIXED)])

    assert read["items"][0]["sentence"] == moment("activity_unsettled")


def test_the_reason_the_projection_recorded_is_carried_rather_than_re_derived():
    read = _read([_Movement(nature=TRANSFER, reason=BY_LINK)])

    assert read["items"][0]["decided_by"] == BY_LINK


# ----------------------------------------------------------- what the panel says


def test_a_vault_that_knows_of_nothing_moving_says_so_rather_than_rendering_empty():
    """Not the same as nothing having moved."""
    read = _read([])

    assert read["state"] == "absent"
    assert read["sentence"] == moment("activity_empty")


def test_the_panel_says_where_direction_is_read_from():
    read = _read([_Movement()])

    assert read["sentence"] == moment("activity_scope")


def test_what_was_left_out_is_counted_rather_than_dropped():
    """A list that silently stops is a list a person reads as the whole of what
    happened."""
    read = _read([_Movement(key=f"m{n}", date=f"2026-07-{n:02d}")
                  for n in range(1, 11)], limit=4)

    assert len(read["items"]) == 4
    assert read["beyond"]["count"] == 6


def test_what_was_left_out_carries_no_amount():
    """The rows beyond are in whatever currencies they are in, and one number
    over them would be a total of unlike things."""
    read = _read([_Movement(key=f"m{n}") for n in range(6)], limit=2)

    assert set(read["beyond"]) == {"count"}


def test_newest_first_and_stable_between_reads():
    read = _read([_Movement(key="a", date="2026-07-01"),
                  _Movement(key="b", date="2026-08-01"),
                  _Movement(key="c", date="2026-08-01")])

    assert [item["id"] for item in read["items"]] == ["c", "b", "a"]


def test_nothing_here_is_a_total():
    """The picture is where a figure lives. A second place computing one would
    be a second answer."""
    read = _read([_Movement(amount="10.00"), _Movement(key="m2", amount="20.00")])

    assert "total" not in read
    assert all("total" not in item for item in read["items"])


def test_the_whole_read_is_json_safe():
    json.dumps(_read([_Movement(nature=MIXED)]), allow_nan=False)


def test_the_surface_reads_activity_from_a_real_vault(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", "pw")

    read = OpenedVaultSurfaceProvider(vault).read_surface("activity", {})

    assert read["state"] == "absent"
    json.dumps(read, allow_nan=False)
