"""Merchant knowledge is filed and read under one name.

Enrichment files what it learns under the brand a resolution layer named. Every
read used to ask for the normalized raw descriptor instead, so a catalog full of
merchants and a ledger full of unknown counterparties could describe the same
money and never intersect. These tests hold the two sides to one key.

The second half is the other direction, and matters as much: records written
before a grammar could name a brand sit under the descriptor, and a person's own
answer is the most trustworthy record in a vault. A lookup that saw only the
brand key would lose them.
"""

from decimal import Decimal

import pytest
from merchantcore.normalize import is_shareable
from merchantcore.profile import Profile, Template
from viva.ledger import (LedgerProjection, account_opened,
                         merchant_categorized, simple_transaction)
from viva.ledger.events import (SCOPE_MERCHANT, UNVERIFIED, VERIFIED,
                                merchant_enriched, ruling_recorded)
from viva.ledger.merchant_keys import MerchantKeys, resolve_keys
from viva.ledger.projection import BY_RULING, TIER_STRUCTURAL
from viva.ledger.projection.merchants import is_person

# A grammar for one bank's card lines: the brand sits in a slot, with a store
# number, a city and a posting date around it.
GRAMMAR = Profile("northbank", "depository", "v1", [
    Template("CARD PURCHASE {date} {brand} {city} {region} CARD {account_ref}"),
])

NOISY = "CARD PURCHASE 06/12 GOLDEN FORK BISTRO PLANO TX CARD 0000"
BRAND_KEY = "golden fork bistro"


def _resolver(grammar=GRAMMAR):
    return lambda rows: resolve_keys(rows, profile_for=lambda i, k: grammar)


def _events(extra=None):
    evs = [
        account_opened("chk", "depository", "Checking", "USD", "2026-01-01",
                       institution="northbank"),
        simple_transaction("chk", "-42.10", NOISY, "2026-06-12"),
    ]
    evs.extend(extra or [])
    return evs


def _proj(extra=None, resolver=None):
    proj = LedgerProjection([], resolve_keys=resolver or _resolver())
    for event in _events(extra):
        proj.apply(event)
    return proj


def _movement(proj):
    return proj.movements()[0]


# --- write and read agree ---------------------------------------------------

def test_the_write_side_and_the_read_side_compute_the_same_key():
    """The bug in one line: the stream engine and the projection must derive
    the same key from the same movement."""
    from viva.ledger.streams import build_streams

    proj = _proj()
    m = _movement(proj)
    stream = build_streams([m], lambda _m: GRAMMAR, lambda _m: _m.kind)[0]
    assert stream.counterparty == proj.merchant_key_of(m) == BRAND_KEY


def test_a_brand_keyed_record_categorizes_a_noisy_descriptor():
    """Enrichment files `golden fork bistro`; the movement says
    `CARD PURCHASE 06/12 GOLDEN FORK BISTRO PLANO TX CARD 0000`. One is the
    other."""
    proj = _proj([merchant_enriched(BRAND_KEY, "Dining", occurred_at="2026-06-20")])
    m = _movement(proj)
    assert (proj.derived_category(m) or {}).get("category") == "Dining"
    assert proj.uncategorized_expenses() == []
    assert proj.spending_by_category()["Dining"] == Decimal("42.10")


def test_without_a_resolver_the_descriptor_is_still_the_key():
    """A projection built with no resolver behaves as it did before grammars
    existed — the case for every vault with nothing induced yet."""
    proj = LedgerProjection([], resolve_keys=None)
    for event in _events():
        proj.apply(event)
    m = _movement(proj)
    assert proj.merchant_keys_of(m) == ("card purchase golden fork bistro plano tx card",)


def test_the_implication_layer_reads_through_the_brand_key():
    """Tier 2 — the counterparty implying an asset or a liability — was
    unreachable for the same reason, and everything downstream of it with it."""
    proj = _proj([merchant_enriched(
        BRAND_KEY, "Dining",
        attributes={"implies": [{"relationship": "a home loan",
                                 "major": "liability", "on": "outflow",
                                 "account_group": "Mortgage", "compound": True,
                                 "confidence": "suggested",
                                 "documents": "mortgage statement",
                                 "ask": "Shall I set up the loan?"}]},
        occurred_at="2026-06-20")])
    m = _movement(proj)
    assert proj.implication_of(m) is not None
    assert proj.tier_of(m) == TIER_STRUCTURAL


def test_a_merchant_scoped_ruling_reads_through_the_brand_key():
    proj = _proj([ruling_recorded(
        SCOPE_MERCHANT, BRAND_KEY, legs=[{"major": "expense", "share": ""}],
        grade=VERIFIED, occurred_at="2026-06-20")])
    m = _movement(proj)
    assert m.nature_reason == BY_RULING


def test_the_queue_asks_under_the_brand_key():
    """The question a person is shown, and the key their answer is written
    under, are the brand — so the answer is readable by the same lookup that
    reads enrichment."""
    from viva.questions import _merchant_questions

    proj = _proj()
    merchant_questions = _merchant_questions(proj)
    assert [q.refs["merchant"] for q in merchant_questions] == [BRAND_KEY]
    assert merchant_questions[0].amount == Decimal("42.10")


# --- knowledge filed under the older name is not lost -----------------------

def test_a_descriptor_keyed_answer_still_reads():
    """Every merchant answer given before this existed was written under the
    normalized descriptor. Losing them would be the same bug pointed the other
    way."""
    descriptor_key = "card purchase golden fork bistro plano tx card"
    proj = _proj([merchant_categorized(descriptor_key, "Dining", VERIFIED,
                                       "2026-06-20")])
    m = _movement(proj)
    assert proj.merchant_key_of(m) == BRAND_KEY          # the brand still wins as the name
    assert (proj.derived_category(m) or {}).get("category") == "Dining"


def test_a_persons_answer_beats_a_models_whichever_key_it_is_under():
    """Grade decides, not which name the record happens to be filed under."""
    descriptor_key = "card purchase golden fork bistro plano tx card"
    proj = _proj([
        merchant_enriched(BRAND_KEY, "Groceries", grade=UNVERIFIED,
                          occurred_at="2026-06-20"),
        merchant_categorized(descriptor_key, "Dining", VERIFIED, "2026-06-21"),
    ])
    assert (proj.derived_category(_movement(proj)) or {}).get("category") == "Dining"


def test_the_brand_wins_a_tie():
    """Two records of equal trust: the brand is the settled identity, and a
    descriptor record is what the older key left behind."""
    descriptor_key = "card purchase golden fork bistro plano tx card"
    proj = _proj([
        merchant_categorized(descriptor_key, "Groceries", VERIFIED, "2026-06-20"),
        merchant_enriched(BRAND_KEY, "Dining", grade=VERIFIED,
                          occurred_at="2026-06-21"),
    ])
    assert (proj.derived_category(_movement(proj)) or {}).get("category") == "Dining"


# --- the map itself ---------------------------------------------------------

def test_two_locations_of_one_brand_are_one_key():
    """Identity is brand-level: the store number and the city belong to the
    visit, not to the counterparty."""
    other = "CARD PURCHASE 07/03 GOLDEN FORK BISTRO AUSTIN TX CARD 0000"
    proj = _proj([simple_transaction("chk", "-18.00", other, "2026-07-03")])
    assert {proj.merchant_key_of(m) for m in proj.movements()} == {BRAND_KEY}


def test_a_new_transaction_re_resolves_rather_than_reusing_a_stale_map():
    proj = _proj()
    assert len(proj.uncategorized_merchants()) == 1
    proj.apply(simple_transaction("chk", "-9.00",
                                  "CARD PURCHASE 07/03 BLUE HERON MARKET AUSTIN TX "
                                  "CARD 0000", "2026-07-03"))
    assert set(proj.uncategorized_merchants()) == {BRAND_KEY, "blue heron market"}


def test_a_line_no_layer_can_decompose_keeps_a_key():
    """A descriptor nothing explains is still filed under something stable — it
    still recurs, and a person can still answer about it."""
    proj = _proj([simple_transaction("chk", "-31.00", "CHECK 4021", "2026-07-03")])
    keys = {proj.merchant_key_of(m) for m in proj.movements()}
    assert "" not in keys and len(keys) == 2


def test_a_peer_line_is_not_given_a_cleaner_key_than_it_earned():
    """A grammar that names a PERSON names no brand, so a peer line keeps the
    whole descriptor as its key.

    Load-bearing: the catalog export refuses a key `is_shareable` rejects, and
    that refusal reads the key itself. A peer line promoted to a bare name would
    walk through the filter."""
    grammar = Profile("northbank", "depository", "v1", [
        Template("ZELLE PAYMENT TO {counterparty} {reference}"),
    ])
    proj = LedgerProjection([], resolve_keys=_resolver(grammar))
    for event in [account_opened("chk", "depository", "Checking", "USD",
                                 "2026-01-01", institution="northbank"),
                  simple_transaction("chk", "-25.00",
                                     "ZELLE PAYMENT TO ALEX RIVERA X9F2",
                                     "2026-05-04")]:
        proj.apply(event)
    key = proj.merchant_key_of(_movement(proj))
    assert "alex rivera" in key and not is_shareable(key)


def test_a_resolver_declaring_nothing_is_told_apart_from_one_of_the_wrong_shape():
    """A resolver that named nobody reads as silence; a mapping that cannot
    carry a declaration raises.

    A plain dict of the same pairs and a copy of a `MerchantKeys` both lose the
    declaration, so `is_person` raises `TypeError` on either. A `MerchantKeys`
    declaring nobody answers False, and the keys resolve the same either way."""
    grammar = Profile("northbank", "depository", "v1", [
        Template("ZELLE PAYMENT TO {counterparty} {reference}"),
    ])
    peer_line = "ZELLE PAYMENT TO ALEX RIVERA X9F2"

    def resolved(rows):
        return resolve_keys(rows, profile_for=lambda i, k: grammar)

    def built(resolver):
        proj = LedgerProjection([], resolve_keys=resolver)
        for event in [account_opened("chk", "depository", "Checking", "USD",
                                     "2026-01-01", institution="northbank"),
                      simple_transaction("chk", "-25.00", peer_line,
                                         "2026-05-04")]:
            proj.apply(event)
        return proj

    declared = built(resolved)
    m = declared.movements()[0]
    assert is_person(declared.core, m)

    # The same mapping with nothing declared over it, read as silence, with the
    # keys themselves unchanged.
    silent = built(lambda rows: MerchantKeys(resolved(rows)))
    assert not is_person(silent.core, m)
    assert silent.merchant_key_of(m) == declared.merchant_key_of(m)

    # And the shapes that lost the declaration on the way out.
    for shapeless in (lambda rows: dict(resolved(rows)),
                      lambda rows: resolved(rows).copy()):
        with pytest.raises(TypeError):
            is_person(built(shapeless).core, m)


def test_the_key_map_is_built_once_per_read_not_once_per_lookup():
    """Every aggregate reads merchant keys for every movement several times
    over. Resolving on each lookup would put a run of regular expressions and a
    grammar match inside that loop."""
    builds = []

    def counting(rows):
        builds.append(sorted({r[0] for r in rows}))
        return resolve_keys(rows, profile_for=lambda i, k: GRAMMAR)

    proj = _proj(resolver=counting)
    for m in proj.movements():
        proj.merchant_key_of(m)
        proj.derived_category(m)
        proj.tier_of(m)
    # One build, and it looked only at the accounts movements come from.
    assert builds == [["chk"]]
