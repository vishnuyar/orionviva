"""Slice 7.6 — categories partition, tags overlay.

The rule was written in discovery and left unbuilt for months, with an empty
`tags` field sitting on the transaction event as a placeholder:

> double-entry governs the money (one balanced truth, verifiable); tags govern
> the meaning (freely multiple, user-owned, the moat).

Vishnu reopened it (2026-07-26) by noticing that an answer can be a category
*and* a tag at once. That question turned out to explain the category sprawl
rather than sit beside it: `poker`, `playing poker`, `martial arts`, `down
payment` are all TAGS that were typed into a category field, because a category
field was the only field there was.

The distinction is load-bearing, not stylistic:

  * a CATEGORY is a **partition** — exactly one per movement, so the parts sum
    to the whole, and "where did my money go?" is checkable.
  * a TAG is an **overlay** — many per movement, overlapping, and tag totals
    deliberately DO NOT sum to spending.

Mixing them yields a report whose parts do not add up to its total. In this
product that is a bluff, so most of what follows tests arithmetic that
deliberately does *not* close, and the honesty of saying so.
"""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest, rule_tag_same_as, tag_merchant,
                         tag_movement)
from viva.ledger import EventStore, Ledger


def _vault(tmp_path, txns):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    total = sum(Decimal(a) for _, _, a in txns)
    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Chase Total Checking", currency="USD",
        opening_amount=Decimal("10000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("10000.00") + total, closing_date="2026-03-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000001122", institution="Chase")

    def read(_data, did):
        facts.doc_id = did
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(raw, ledger, b"doc", read, captured_at="2026-04-01")
    return ledger


def _three(tmp_path):
    return _vault(tmp_path, [("2026-03-05", "TOP KICK MARTIAL ARTS TX", "-100.00"),
                             ("2026-03-06", "TOP KICK MARTIAL ARTS TX", "-100.00"),
                             ("2026-03-07", "ATM WITHDRAWAL PLANO TX", "-300.00")])


def test_tag_totals_do_not_sum_to_spending_and_the_report_says_so(tmp_path):
    """The property that makes a tag a different thing from a category.

    One movement with two tags appears in two lines; money with no tags appears
    in none. So `by_tag` alone would let a person read overlapping figures as a
    breakdown of their spending — which is why `untagged` and `total` come back
    with it and callers must show them."""
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    tag_movement(ledger, keys[0], ["martial arts", "son"])

    out = ledger.projection().spending_by_tag()
    assert out["by_tag"] == {"martial arts": Decimal("100.00"),
                             "son": Decimal("100.00")}
    assert sum(out["by_tag"].values()) == Decimal("200.00")
    assert out["total"] == Decimal("500.00"), "one movement, counted twice"
    assert out["untagged"] == Decimal("400.00")
    assert out["overlaps"] is True


def test_a_merchant_tag_settles_every_movement_from_it(tmp_path):
    """"Everything from this gym is martial arts" — one ruling, not forty."""
    ledger = _three(tmp_path)
    tag_merchant(ledger, "top kick martial arts tx", ["martial arts"])
    out = ledger.projection().spending_by_tag()
    assert out["by_tag"]["martial arts"] == Decimal("200.00")
    assert out["untagged"] == Decimal("300.00")


def test_a_movement_tag_and_a_merchant_tag_are_a_union_not_an_override(tmp_path):
    """Both are true at once. "Everything from this gym is martial arts" and
    "this particular visit was a birthday present" are different statements, and
    a person who set both expects to find the movement under either."""
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    tag_merchant(ledger, "top kick martial arts tx", ["martial arts"])
    tag_movement(ledger, keys[0], ["birthday"])
    proj = ledger.projection()
    first = next(m for m in proj.movements() if m.key == keys[0])
    assert proj.tags_of(first) == ["birthday", "martial arts"]


def test_the_complete_set_is_recorded_so_removing_a_tag_is_appending(tmp_path):
    """Last write wins on the whole set, which keeps the log append-only with no
    'untag' event to reconcile against an 'add' that arrived out of order."""
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    tag_movement(ledger, keys[0], ["martial arts", "son"])
    tag_movement(ledger, keys[0], ["martial arts"])
    out = ledger.projection().spending_by_tag()
    assert "son" not in out["by_tag"]
    assert out["by_tag"]["martial arts"] == Decimal("100.00")
    assert len([e for e in ledger.store.events()
                if e.event_type == "MovementTagged"]) == 2, "nothing was deleted"


def test_tags_are_normalised_and_alias_separately_from_categories(tmp_path):
    """A tag "poker" and a category "poker" are different things, so the two
    alias spaces are kept apart — merging one must not silently merge the other."""
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    tag_movement(ledger, keys[2], ["  Poker Night ", "POKER NIGHT"])
    assert ledger.projection().known_tags() == ["poker night"], "trimmed, lowered, deduped"

    tag_movement(ledger, keys[0], ["poker"])
    rule_tag_same_as(ledger, "poker night", "poker")
    proj = ledger.projection()
    assert proj.known_tags() == ["poker"]
    assert proj.spending_by_tag()["by_tag"]["poker"] == Decimal("400.00")
    assert proj.category_aliases() == {}, "the category vocabulary is untouched"


def test_a_tag_never_touches_the_category_partition(tmp_path):
    """The whole point of the split. Tagging money must not change what it is,
    or the one report whose parts sum to the whole stops summing."""
    from viva.ingest.categorize import assign_category
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    assign_category(ledger, keys[0], "entertainment")
    before = ledger.projection().spending_by_category()
    tag_movement(ledger, keys[0], ["martial arts", "son", "birthday"])
    assert ledger.projection().spending_by_category() == before


def test_tags_live_in_their_own_event_type_so_t9_is_one_rule(tmp_path):
    """A category is shareable world knowledge — a merchant IS a coffee shop,
    for everyone. A tag is personal meaning: this coffee was on the Japan trip.
    No commons can ever know it.

    Keeping tags in their own event makes "tags never leave this device" an
    EVENT-LEVEL rule rather than a per-field check inside an event that is
    itself shareable — much harder to get wrong by accident. This test exists so
    that a later refactor folding tags into CategoryAssigned has to argue with
    something."""
    ledger = _three(tmp_path)
    keys = [m.key for m in ledger.projection().movements()]
    tag_movement(ledger, keys[0], ["japan trip"])
    tagged = [e for e in ledger.store.events() if e.event_type == "MovementTagged"]
    assert tagged, "tags are not a field on another event"
    for e in ledger.store.events():
        if e.event_type == "CategoryAssigned":
            assert "tags" not in (e.body or {}), \
                "a shareable event must not carry personal meaning"


def test_a_tag_cannot_be_attached_to_something_that_is_not_money(tmp_path):
    """Scope is checked at the write side, where an impossible ruling should be
    refused rather than stored and puzzled over later."""
    import pytest

    from viva.ledger.events import movement_tagged
    with pytest.raises(ValueError):
        movement_tagged("acct:chase:1122", ["japan trip"], "2026-03-01",
                        scope="account")
