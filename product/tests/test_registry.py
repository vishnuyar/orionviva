import pytest

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
    """The extract version is self-describing — `extract:<base>+<fragment>` —
    and a fragment belongs to exactly one profile. So a claim that lost its
    classify phase can still say what it is.

    This is not a convenience. The balance family's extract JSON does not name
    its own type, so without it a stored claim with no CLASSIFY phase replays as
    `unknown`, finds no projector, and parks — an empty vault out of perfectly
    good stored reads, while the answer sits one field away.

    Reading it back is recovering a recorded fact, not inferring one."""
    from viva.ingest.registry import doc_type_for_prompt_version

    assert doc_type_for_prompt_version("extract:base-v1+card-v1") == \
        "credit_card_statement"
    assert doc_type_for_prompt_version("extract:base-v1+checking-v1") == \
        "checking_statement"
    # An unknown fragment must return "" so the caller parks honestly rather
    # than defaulting to a plausible type — a wrong projector is worse than none.
    # A document read a YEAR AGO carries whatever version was current then, and
    # the registry only holds today's, so the FAMILY is matched rather than the
    # exact version — the one part designed to change.
    assert doc_type_for_prompt_version("extract:brokerage-base-v1+brokerage-v1") \
        == "brokerage_statement"
    assert doc_type_for_prompt_version("extract:base-v1+checking-v9") == \
        "checking_statement", "a future version must resolve too"
    assert doc_type_for_prompt_version("extract:base-v1+not-a-real-fragment") == ""
    assert doc_type_for_prompt_version("extract:base-v1+nonsense-v1") == "", \
        "an unknown FAMILY is still unknown, however well-formed the version"
    assert doc_type_for_prompt_version("classify-v1") == ""
    assert doc_type_for_prompt_version("") == ""


def test_reingest_can_filter_to_one_document_family_and_cost_nothing_first():
    """`--only` and `--dry-run` are what make a prompt change affordable to test.

    Re-reading every document costs one model call each; re-reading the family
    whose prompt you actually changed costs a handful. And `--dry-run` prints
    exactly what WOULD be read while spending nothing — this is the one command
    in the project that costs real money, so it must be possible to look before
    committing to it.

    Checked as text because the alternative is a live model call in CI."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "viva" / "reingest.py").read_text()
    assert "--only" in src and "--dry-run" in src
    assert "DRY RUN" in src, "a dry run must say plainly that it spent nothing"
    # The regression report is the reason the tool exists at all.
    assert "REGRESSION" in src
    assert "Do not ship this prompt version" in src
    assert "No document changed outcome" in src, \
        "an unchanged run must say so, rather than looking like a success"


def test_one_locale_default_for_every_entry_point(monkeypatch):
    """A setting that four programs each default separately is four defaults.

    "US" is not a language tag, so the amount parser has no decimal convention
    for it and refuses every THREE-DECIMAL figure as ambiguous — silently,
    because an unknown locale is not an error in a money parser, it just makes
    it stricter. Two entry points disagreeing on the default therefore parse the
    same stored reply differently, and leave holdings out of a net-worth
    figure."""
    from vivacore.verify.normalize import known_language_tags, parse_amount
    from viva.env import locale_from_env

    monkeypatch.delenv("VIVA_LOCALE", raising=False)
    assert locale_from_env() == "en-US"

    # Three-decimal figures, as a brokerage statement prints them.
    for raw in ("295.120", "139.770"):
        assert parse_amount(raw, "en-US", "USD").status == "ok"
        assert parse_amount(raw, "US", "USD").status == "ambiguous", \
            "an unrecognised tag makes the parser stricter, not louder"

    # So an unrecognised tag must stop the run, where the fix is obvious.
    monkeypatch.setenv("VIVA_LOCALE", "US")
    with pytest.raises(SystemExit) as exc:
        locale_from_env()
    assert "en-US" in str(exc.value), "say what a valid tag looks like"
    assert "ambiguous" in str(exc.value), "and what would silently go wrong"

    monkeypatch.setenv("VIVA_LOCALE", "en-IN")
    assert locale_from_env() == "en-IN"
    assert "en" in known_language_tags()


def test_no_entry_point_defaults_the_locale_by_hand():
    """One place resolves the locale; no entry point may default it by hand."""
    import pathlib
    viva = pathlib.Path(__file__).resolve().parents[1] / "viva"
    offenders = [p.name for p in viva.rglob("*.py")
                 if 'environ.get("VIVA_LOCALE"' in p.read_text()
                 and p.name != "env.py"]
    assert not offenders, (
        f"{offenders} default VIVA_LOCALE themselves; use locale_from_env() so "
        "there is one value and unrecognised tags are refused in one place")
