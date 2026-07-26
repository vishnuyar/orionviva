"""Prompts are retained, addressable, versioned data — not an overwritten string.

The frozen-hash test enforces the retention discipline: a version id's text may
never change. To edit a prompt you add a NEW id, so a read stored under the old
id keeps resolving to exactly what produced it (T8)."""

import hashlib

import pytest

from viva.ingest import prompt_library as pl

# Pinned digests of every ACTIVE version. If one changes, the fix is not to bump
# the number here — it is to add a new version id and leave the old text intact.
FROZEN = {
    "classify-v1": "78d4a6f76dda419c",
    "classify-v2": "b0068911c228303a",
    "base-v1": "93c67860a6626894",
    "balance-generic-v1": "b7c12fe0406a602e",
    "checking-v1": "2bda917dce1ee26f",
    "savings-v1": "222ae6d74f94e8f6",
    "card-v1": "1fb3e7b3dfb1c9c9",
    "paystub-base-v1": "0c6d6940246743c5",
    "paystub-v1": "03b31eadbe878505",
    "interpret-v1": "999d8aa496da5691",
}


def test_active_versions_are_frozen():
    live = {**pl.CLASSIFY_PROMPTS, **pl.EXTRACT_BASE, **pl.TYPE_FRAGMENTS,
            **pl.INTERPRET_PROMPTS}
    for version, digest in FROZEN.items():
        assert version in live, f"{version} disappeared — versions are append-only"
        got = hashlib.sha256(live[version].encode()).hexdigest()[:16]
        assert got == digest, (
            f"{version} text changed. Do not edit a released prompt version; add "
            f"a new id and point the profile at it.")


def test_classify_prompt_carries_its_version():
    text, version = pl.classify_prompt()
    assert version == "classify-v2" and "doc_type" in text
    assert "pay_stub" in text                          # v2 knows pay stubs


def test_compose_extraction_yields_self_describing_version():
    text, version = pl.compose_extraction("base-v1", "card-v1")
    assert version == "extract:base-v1+card-v1"
    # The composite is base THEN the type fragment — shape first, meaning second.
    assert text.startswith(pl.EXTRACT_BASE["base-v1"])
    assert pl.TYPE_FRAGMENTS["card-v1"] in text


def test_resolve_round_trips_every_kind_of_version():
    # A stored read's prompt_version must resolve to its exact text, whether it is
    # a classify id, a base/fragment id, or a composite extract id.
    assert pl.resolve("classify-v1") == pl.CLASSIFY_PROMPTS["classify-v1"]
    assert pl.resolve("card-v1") == pl.TYPE_FRAGMENTS["card-v1"]
    _, version = pl.compose_extraction("base-v1", "checking-v1")
    composed, _ = pl.compose_extraction("base-v1", "checking-v1")
    assert pl.resolve(version) == composed


def test_resolve_unknown_version_raises():
    with pytest.raises(KeyError):
        pl.resolve("does-not-exist")


def test_card_fragment_carries_the_payments_completeness_rule():
    # The card-specific completeness guidance lives ONLY in the card fragment —
    # it must not leak into the checking fragment (the pollution we removed).
    assert "payments" in pl.TYPE_FRAGMENTS["card-v1"].lower()
    assert "separate section" in pl.TYPE_FRAGMENTS["card-v1"].lower()
    assert "separate section" not in pl.TYPE_FRAGMENTS["checking-v1"].lower()


# ------------------------------------------------- the interpret prompt (9a)


def test_the_interpret_prompt_is_addressable_like_every_other():
    """It began life as a module constant in listen.py — unversioned and
    rewritable in place, which would have meant that tuning it silently
    reinterpreted every ruling made before the change (Vishnu, 2026-07-25)."""
    text, version = pl.interpret_prompt()
    assert version == "interpret-v1"
    assert pl.resolve(version) == text          # a recorded ruling round-trips


def test_the_interpret_prompt_assumes_no_particular_instrument():
    """A vault holds cards, brokerages, retirement and loan accounts — and one
    day, accounts in other countries. A prompt that says "your bank account"
    mis-frames all of them (I5: code universal, specifics are data)."""
    import re

    text, _ = pl.interpret_prompt()
    low = text.lower()
    # Word-boundary matching, not substrings — "first" contains "irs".
    for bank_shaped in (r"bank account", r"from their bank", r"on the statement",
                        r"\bdollars?\b", r"\$", r"\birs\b", r"\b1098\b",
                        r"\bchecking\b"):
        assert not re.search(bank_shaped, low), f"prompt assumes {bank_shaped!r}"
    # And it says so positively, rather than merely avoiding the word.
    assert "any financial instrument" in low and "any country" in low


def test_the_interpret_prompt_fills_from_named_placeholders():
    """Placeholders, not string surgery — so a caller can add context without
    editing prose, and a missing one fails loudly instead of silently."""
    text, _ = pl.interpret_prompt()
    filled = text.format(said="i bought a car", counterparty="ACME MOTORS",
                         source="a credit account", category="transport",
                         subcategory="auto dealer")
    assert "i bought a car" in filled and "a credit account" in filled
    assert "{" in text and "{" not in filled.split("Reply with:")[0]

    import pytest
    with pytest.raises(KeyError):
        text.format(said="x")                   # a forgotten arg is not silent


def test_a_ruling_records_which_prompt_read_it():
    """T8. Without this, tuning the prompt makes past rulings unexplainable and
    eval runs incomparable across time."""
    from viva.ledger.events import MAJOR_ASSET, SCOPE_MERCHANT, ruling_recorded
    ev = ruling_recorded(SCOPE_MERCHANT, "acme motors", "2026-07-25",
                         legs=[{"major": MAJOR_ASSET}], said="i bought a car",
                         prompt_version="interpret-v1")
    assert ev.body["prompt_version"] == "interpret-v1"
    assert pl.resolve(ev.body["prompt_version"])       # still reconstructible
