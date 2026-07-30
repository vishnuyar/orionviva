"""The running-balance projection and its honest grade ladder."""

from decimal import Decimal

import pytest

from viva.ledger import (BalanceAnswer, LedgerProjection, Provenance,
                         UnknownAccountError, account_opened,
                         closing_balance_observed, opening_balance_observed,
                         simple_transaction, split_transaction)
from viva.ledger.events import (CONFLICTED, CORROBORATED, UNVERIFIED, VERIFIED)


def _statement(closing="1457.58", extra=None):
    """A tiny checking statement: open 1000, +500 pay, -42.42 coffee => 1457.58."""
    evs = [
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01"),
        opening_balance_observed("chk", "1000.00", "2026-01-01",
                                 Provenance("chase-jan", 1, "opening-box")),
        simple_transaction("chk", "500.00", "paycheck", "2026-01-10"),
        simple_transaction("chk", "-42.42", "coffee", "2026-01-15"),
    ]
    if extra:
        evs.extend(extra)
    if closing is not None:
        evs.append(closing_balance_observed(
            "chk", closing, "2026-01-31", Provenance("chase-jan", 6, "closing-box")))
    return evs


def test_running_balance_is_correct():
    proj = LedgerProjection(_statement())
    assert proj.balance("chk").amount == Decimal("1457.58")


def test_reconciled_statement_is_corroborated():
    ans = LedgerProjection(_statement()).balance("chk")
    assert ans.grade == CORROBORATED
    assert ans.reconciliation is not None and ans.reconciliation.passed
    assert ans.provenance.doc_id == "chase-jan" and ans.provenance.page == 6


def test_wrong_closing_is_conflicted_not_hidden():
    ans = LedgerProjection(_statement(closing="9999.99")).balance("chk")
    assert ans.grade == CONFLICTED
    assert not ans.reconciliation.passed
    # It still reports the attested figure and says the two disagree.
    assert ans.amount == Decimal("9999.99")
    assert "disagree" in ans.explanation


def test_no_closing_is_unverified():
    ans = LedgerProjection(_statement(closing=None)).balance("chk")
    assert ans.grade == UNVERIFIED
    assert ans.amount == Decimal("1457.58")   # still the replayed sum
    assert ans.reconciliation is None


def test_lone_snapshot_is_verified():
    evs = [
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01"),
        closing_balance_observed("chk", "1457.58", "2026-01-31",
                                 Provenance("chase-jan", 6, "closing-box")),
    ]
    ans = LedgerProjection(evs).balance("chk")
    assert ans.grade == VERIFIED and ans.amount == Decimal("1457.58")


def test_unknown_account_refuses():
    with pytest.raises(UnknownAccountError):
        LedgerProjection(_statement()).balance("savings")


def test_split_transaction_reflected_in_balance():
    extra = [split_transaction(
        "chk", "-100.00",
        [("Expenses:Groceries", "70.00"), ("Expenses:Gifts", "30.00")],
        "walmart", "2026-01-20")]
    # closing now 1000 + 500 - 42.42 - 100 = 1357.58
    ans = LedgerProjection(_statement(closing="1357.58", extra=extra)).balance("chk")
    assert ans.grade == CORROBORATED and ans.amount == Decimal("1357.58")


def test_as_of_excludes_future_events():
    # As of Jan 12, only the paycheck has landed: 1000 + 500 = 1500, no closing.
    proj = LedgerProjection(_statement(), as_of="2026-01-12")
    ans = proj.balance("chk")
    assert ans.amount == Decimal("1500.00")
    assert ans.grade == UNVERIFIED       # closing is in the excluded future


def test_accounts_listing():
    proj = LedgerProjection(_statement())
    assert "chk" in proj.accounts()


# --- identity: the number decides before the holder's name is consulted -----

def _known(tmp_path, *, account, name, number, holder="ROWAN E VANCE",
           institution="Northbank", kind="depository"):
    from viva.ledger import EventStore, Ledger
    from viva.ledger.events import account_opened
    ledger = Ledger(EventStore.open(tmp_path / "e.jsonl", "pw"))
    ledger.append(account_opened(account, kind, name, "USD", "2026-01-01",
                                 institution=institution, account_number=number,
                                 account_names=[holder]))
    return ledger.projection()


def test_a_savings_account_is_not_confused_with_the_checking_beside_it(tmp_path):
    """The commonest pairing a person has: two accounts at one bank, one holder,
    two different and perfectly readable numbers. A holder's name is on every
    account they own, so it cannot be what decides — and asking here asked about
    the most ordinary arrangement in personal finance."""
    proj = _known(tmp_path, account="acct:northbank:4417",
                  name="Everyday Checking", number="••••4417")
    r = proj.resolve("Northbank", "••••8802", "High-Yield Savings",
                     ["ROWAN E VANCE"], kind="depository")
    assert r.verdict == "new"


def test_the_same_number_is_still_the_same_account(tmp_path):
    proj = _known(tmp_path, account="acct:northbank:4417",
                  name="Everyday Checking", number="••••4417")
    assert proj.resolve("Northbank", "4417", "Checking",
                        ["ROWAN E VANCE"], kind="depository").verdict == "same"


def test_with_no_numbers_two_different_products_are_two_accounts(tmp_path):
    proj = _known(tmp_path, account="acct:everyday-checking",
                  name="Everyday Checking", number="")
    assert proj.resolve("Northbank", "", "High-Yield Savings",
                        ["ROWAN E VANCE"], kind="depository").verdict == "new"


def test_with_nothing_stronger_than_a_name_it_still_asks(tmp_path):
    """The ask is not removed, it is scoped. When no number is readable and the
    labels agree, a holder name really is all there is, and that is exactly the
    case worth one question."""
    proj = _known(tmp_path, account="acct:northbank:4417",
                  name="Everyday Checking", number="••••4417")
    r = proj.resolve("Northbank", "", "Statement of Account",
                     ["ROWAN E VANCE"], kind="depository")
    assert r.verdict == "ambiguous" and r.candidate == "acct:northbank:4417"


def test_a_card_and_a_checking_account_are_still_two_accounts(tmp_path):
    proj = _known(tmp_path, account="acct:northbank:4417",
                  name="Everyday Checking", number="••••4417")
    assert proj.resolve("Meridian", "••••2291", "Signature Card",
                        ["ROWAN E VANCE"], kind="liability").verdict == "new"


# --- what a closing figure is, and what an opening one seeds ----------------

def test_a_closing_balance_is_observed_not_posted():
    """A closing figure is a reconciliation target, not a leg: it never enters
    the replayed sum, so observing the same one twice changes no balance."""
    base = _statement(closing=None)
    replayed = LedgerProjection(base).balance("chk").amount
    proj = LedgerProjection(base + [
        closing_balance_observed("chk", "1457.58", "2026-01-31"),
        closing_balance_observed("chk", "1457.58", "2026-01-31")])
    assert proj.running_balance("chk") == replayed
    assert proj.balance("chk").amount == replayed


def test_a_backfilled_opening_reseats_the_earliest_rather_than_accumulating():
    """Opening Balance Equity is injected once, from the earliest known opening.
    A statement backfilled in front of the chain re-seats it; it does not add a
    second seed."""
    proj = LedgerProjection(_statement(closing=None) + [
        opening_balance_observed("chk", "250.00", "2025-12-01")])
    assert proj.earliest_opening("chk") == Decimal("250.00")
    assert proj.running_balance("chk") == Decimal("707.58")   # 250 + 500 - 42.42


def test_the_uncategorized_inflow_bucket_is_never_reported_as_income():
    """`income_by_currency` reports attributed income only. The paycheck's
    counter-leg sits in `Income:Uncategorized`, which is excluded."""
    proj = LedgerProjection(_statement())
    assert "Income:Uncategorized" in proj.accounts()
    assert proj.income_by_currency() == {}


def test_the_enrichment_example_is_linted_never_the_raw_descriptor():
    """`uncategorized_merchants` offers a linted example, so store numbers and
    order ids in a raw descriptor never reach a model provider."""
    raw_line = "COFFEE HOUSE #1234 SEATTLE WA 0123456"
    proj = LedgerProjection([
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01"),
        simple_transaction("chk", "-8.50", raw_line, "2026-01-15"),
    ])
    row = proj.uncategorized_merchants()["coffee house seattle wa"]
    assert row["example"] == "COFFEE HOUSE SEATTLE WA"
    assert "1234" not in row["example"] and "0123456" not in row["example"]


def test_the_cached_projection_matches_a_full_replay(tmp_path):
    """`Ledger` folds each append into one live projection instead of replaying.
    The cached answer is the same one a cold replay of the log gives."""
    from viva.ledger import EventStore, Ledger

    ledger = Ledger(EventStore.open(tmp_path / "e.jsonl", "pw"))
    for event in _statement():
        ledger.append(event)
    cached = ledger.projection().balance("chk")
    replayed = LedgerProjection(ledger.store.events()).balance("chk")
    assert (cached.amount, cached.grade) == (replayed.amount, replayed.grade)
    assert cached.amount == Decimal("1457.58") and cached.grade == CORROBORATED
