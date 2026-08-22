"""Which way the money went comes from the account's kind, in every place.

M2's exception named one site: a counterparty's implication was picked from the
posted sign, so on a liability a purchase read as money arriving. The guard here
is structural — the function that decides direction raises when it is handed no
kind — so the site cannot reopen by somebody adding a branch that reads a sign.
"""

from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path

import pytest

from viva.ledger.projection.merchants import implication_in, implication_of
from viva.ledger.streams import money_effect

SITE = Path(__file__).resolve().parents[1] / "viva/ledger/projection/merchants.py"

BORROWING = {"on": "inflow", "what": "this is the borrowing"}
REPAYMENT = {"on": "outflow", "what": "this repays the borrowing"}
RECORD = {"attributes": {"implies": [BORROWING, REPAYMENT]}}


class _Movement:
    """One movement, with the two things direction is decided from."""

    def __init__(self, kind: str, amount: str) -> None:
        self.kind = kind
        self.amount = Decimal(amount)
        self.description = "acme lending"
        self.account = "acct:one"


class _Core:
    """A catalog that answers for one counterparty, whatever it is asked."""

    _merchant_categories = {"acme lending": RECORD}

    def __init__(self) -> None:
        self._merchant_keys = None


def _implication(kind: str, amount: str) -> dict | None:
    import viva.ledger.projection.merchants as merchants

    core = _Core()
    original = merchants.merchant_record
    try:
        merchants.merchant_record = lambda _core, _m: RECORD
        return implication_of(core, _Movement(kind, amount))
    finally:
        merchants.merchant_record = original


def test_a_purchase_on_a_liability_is_money_leaving_not_money_arriving():
    """The defect M2 named. A charge on a card posts positive — what is owed
    grew — and a sign alone reads that as the borrowing itself."""
    assert _implication("liability", "120.00") == REPAYMENT


def test_a_drawdown_on_a_liability_is_the_borrowing():
    assert _implication("liability", "-500.00") == BORROWING


def test_an_asset_reads_as_recorded():
    assert _implication("asset", "500.00") == BORROWING
    assert _implication("asset", "-120.00") == REPAYMENT


def test_a_movement_with_no_account_kind_raises_rather_than_guessing():
    """There is no fallback to the posted amount. A movement that cannot say
    what kind of account it is on cannot be described in a direction at all."""
    with pytest.raises(ValueError, match="decided by its account's kind"):
        _implication("", "120.00")


def test_the_site_reads_no_posted_sign_at_all():
    """The guard is the call rather than a comment beside one. Nothing in this
    function compares a movement's amount to anything, so the branch M2's
    exception named cannot come back by somebody editing around a note."""
    tree = ast.parse(SITE.read_text(encoding="utf-8"), filename=str(SITE))
    site = next(node for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef) and node.name == "implication_of")

    compared = [node for node in ast.walk(site) if isinstance(node, ast.Compare)]
    reads_amount = [node for node in ast.walk(site)
                    if isinstance(node, ast.Attribute) and node.attr == "amount"]

    # One comparison, and it is of what `money_effect` returned. The amount is
    # read once, and only to hand it to the function that knows the kind.
    assert len(compared) == 1
    assert len(reads_amount) == 1
    assert isinstance(compared[0].left, ast.Call)
    assert compared[0].left.func.id == "money_effect"


def test_direction_is_decided_by_the_one_function_that_knows():
    """Not a second copy of the rule: the same function every other read uses,
    so a change to what a kind means moves every direction at once."""
    assert money_effect("liability", Decimal("120.00")) == Decimal("-120.00")
    assert money_effect("asset", Decimal("120.00")) == Decimal("120.00")


def test_a_catalog_with_no_implication_in_that_direction_answers_nothing():
    """Closing the site changes which implication is chosen, never whether one
    is invented when the catalog holds none."""
    outflow_only = {"attributes": {"implies": [REPAYMENT]}}

    assert implication_in(outflow_only, inflow=True) is None
    assert implication_in(outflow_only, inflow=False) == REPAYMENT
