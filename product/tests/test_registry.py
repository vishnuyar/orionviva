"""The doc-type registry: a new statement type is DATA (a row), not code."""

from viva.ingest import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, DEPOSITORY,
                         INVESTMENT, LIABILITY, DocProfile, account_kind_for,
                         can_project, profile_for, register)


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
    assert profile_for("loan_statement") is None
    assert not can_project("loan_statement")
    assert account_kind_for("loan_statement") == DEPOSITORY        # safe default


def test_pay_stub_is_a_divergent_projectable_profile():
    p = profile_for("pay_stub")
    assert p is not None and p.identity == "paystub"    # not the balance family
    assert can_project("pay_stub")                       # it has a projector
    assert profile_for("payslip") is p                   # alias resolves


def test_brokerage_is_a_divergent_investment_profile():
    p = profile_for("brokerage_statement")
    assert p is not None and p.identity == BROKERAGE_IDENTITY   # its own identity
    assert p.account_kind == INVESTMENT                          # a third kind
    assert can_project("brokerage_statement")                    # has a projector
    assert profile_for("ira_statement") is p                     # alias resolves
    assert account_kind_for("401k_statement") == INVESTMENT


def test_registering_a_new_balance_type_is_data_only():
    # The claim the architecture rests on: adding a balance-shaped type is a
    # registry row — no change to the reconciliation gate — and it projects.
    assert not can_project("gift_card_statement")
    register(DocProfile("gift_card_statement", LIABILITY,
                        aliases=frozenset({"gift_card"})))
    assert can_project("gift_card_statement")
    assert profile_for("gift_card").account_kind == LIABILITY


def test_a_read_names_its_own_type_through_its_prompt_version():
    """T8 required the extract version to be self-describing —
    `extract:<base>+<fragment>` — and a fragment belongs to exactly one profile.
    So a claim that lost its classify phase can still say what it is.

    This is not a convenience. A real vault held 40 documents whose claims had an
    EXTRACT phase and no CLASSIFY phase; the balance family's extract JSON does
    not name its own type, so every one replayed as `unknown`, found no
    projector, and parked. A rebuild produced an EMPTY vault out of forty
    perfectly good stored reads — while the answer sat one field away, written
    down at ingest time by a rule adopted for a completely different reason.

    Reading it back is recovering a recorded fact, not inferring one."""
    from viva.ingest.registry import doc_type_for_prompt_version

    assert doc_type_for_prompt_version("extract:base-v1+card-v1") == \
        "credit_card_statement"
    assert doc_type_for_prompt_version("extract:base-v1+checking-v1") == \
        "checking_statement"
    # An unknown fragment must return "" so the caller parks honestly rather
    # than defaulting to a plausible type — a wrong projector is worse than none.
    assert doc_type_for_prompt_version("extract:base-v1+not-a-real-fragment") == ""
    assert doc_type_for_prompt_version("classify-v1") == ""
    assert doc_type_for_prompt_version("") == ""
