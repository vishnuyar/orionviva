"""Shared transfer admission keeps reference modes and caller failures distinct."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.ledger.transfer_admission import (
    account_reference_available, counterpart_reference_complete,
    recognized_link_origin, relationship_complete,
)


def movement(**changes):
    values = dict(key="movement", date="2024-02-17", description="synthetic transfer",
                  account="acct:synthetic", currency="USD", kind="depository",
                  amount=Decimal("10"))
    return SimpleNamespace(**(values | changes))


@pytest.mark.parametrize("origin, expected", [
    ({"by": "human", "grade": "verified", "decided_by": "  "}, "human"),
    ({"by": "human", "grade": "verified", "decided_by": "named_account"}, ""),
    ({"by": "auto", "grade": "corroborated", "decided_by": " named_account "}, "auto"),
    ({"by": "auto", "grade": "verified", "decided_by": "named_account"}, ""),
    ({"by": " auto", "grade": "corroborated", "decided_by": "named_account"}, ""),
    ({"by": "auto", "grade": "corroborated", "decided_by": "unsupported"}, ""),
])
def test_only_writer_provenance_is_recognized(origin, expected):
    assert recognized_link_origin(origin) == expected


@pytest.mark.parametrize("source", [movement(key=""), movement(currency=""),
                                    movement(date=None)])
def test_relationship_preserves_source_reference_asymmetry(source):
    counterpart = movement(key="other")
    assert relationship_complete(source, counterpart, True, True)
    assert counterpart_reference_complete(counterpart, True)


def test_counterpart_only_does_not_need_source_completeness():
    source = movement(date="", description="", account="")
    counterpart = movement(key="other")
    assert counterpart_reference_complete(counterpart, True)
    assert not relationship_complete(source, counterpart, False, True)
    assert not counterpart_reference_complete(movement(description="  "), True)
    assert not counterpart_reference_complete(movement(currency=""), True)
    assert not counterpart_reference_complete(movement(date=None), True)


@pytest.mark.parametrize("account,name,number,expected", [
    ("acct:tail", "", "", True), ("acct:", " ", "1234", True),
    ("acct:", "Label 12345678", "", True), ("acct: ", " ", " ", False),
])
def test_account_availability_preserves_fallbacks(account, name, number, expected):
    assert account_reference_available(account, name, number) is expected


def test_activity_withholds_lookup_failure_while_sql_propagates():
    from viva.surface.activity import _transfer_reference
    from viva.sql_authority.transfers import reference_complete

    class Unreadable:
        def account_info(self, _key):
            raise LookupError("synthetic account lookup failure")

        def _row(self, *_args):
            raise LookupError("synthetic database lookup failure")

    source, counterpart = movement(), movement(key="other")
    assert _transfer_reference(Unreadable(), source, counterpart, "") is None
    with pytest.raises(LookupError, match="synthetic database"):
        reference_complete(Unreadable(), source, counterpart)
