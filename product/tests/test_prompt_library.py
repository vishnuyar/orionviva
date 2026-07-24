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
    "base-v1": "93c67860a6626894",
    "balance-generic-v1": "b7c12fe0406a602e",
    "checking-v1": "2bda917dce1ee26f",
    "savings-v1": "222ae6d74f94e8f6",
    "card-v1": "1fb3e7b3dfb1c9c9",
}


def test_active_versions_are_frozen():
    live = {**pl.CLASSIFY_PROMPTS, **pl.EXTRACT_BASE, **pl.TYPE_FRAGMENTS}
    for version, digest in FROZEN.items():
        assert version in live, f"{version} disappeared — versions are append-only"
        got = hashlib.sha256(live[version].encode()).hexdigest()[:16]
        assert got == digest, (
            f"{version} text changed. Do not edit a released prompt version; add "
            f"a new id and point the profile at it.")


def test_classify_prompt_carries_its_version():
    text, version = pl.classify_prompt()
    assert version == "classify-v1" and "doc_type" in text


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
