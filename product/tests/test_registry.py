"""The doc-type registry: a new statement type is DATA (a row), not code."""

from viva.ingest import (BALANCE_IDENTITY, DEPOSITORY, LIABILITY, DocProfile,
                         account_kind_for, can_project, profile_for, register)


def test_canonical_and_alias_resolve_to_same_profile():
    p = profile_for("checking_statement")
    assert p is not None and p.account_kind == DEPOSITORY
    # A label variant the model might emit resolves to the same profile.
    assert profile_for("bank_statement") is p
    assert profile_for("CHECKING") is p             # case/space forgiving


def test_card_is_a_liability_savings_is_depository():
    assert profile_for("credit_card_statement").account_kind == LIABILITY
    assert profile_for("credit_card_statement").is_liability
    assert profile_for("savings_statement").account_kind == DEPOSITORY
    assert account_kind_for("credit_card") == LIABILITY
    assert account_kind_for("savings") == DEPOSITORY


def test_whole_balance_family_shares_one_identity():
    for dt in ("checking_statement", "savings_statement", "credit_card_statement"):
        assert profile_for(dt).identity == BALANCE_IDENTITY
        assert can_project(dt)


def test_unknown_type_has_no_projector():
    assert profile_for("pay_stub") is None
    assert not can_project("pay_stub")
    assert account_kind_for("pay_stub") == DEPOSITORY   # safe default


def test_registering_a_new_balance_type_is_data_only():
    # The claim the architecture rests on: adding a balance-shaped type is a
    # registry row — no change to the reconciliation gate — and it projects.
    assert not can_project("gift_card_statement")
    register(DocProfile("gift_card_statement", LIABILITY,
                        aliases=frozenset({"gift_card"})))
    assert can_project("gift_card_statement")
    assert profile_for("gift_card").account_kind == LIABILITY
