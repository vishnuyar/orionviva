"""A category is a resolved identity, not a bare string.

Two labels for one thing split every total that touches either, quietly and
without ever raising an error — the worst shape a finance bug can take.

The cause is structural rather than careless. Accounts and merchants are
*resolved* (signals → graded match → ask only when ambiguous → learn the
ruling); a category is the one place a raw string is used, so it is the one
place duplicates accumulate. And they arrive from BOTH ends: the person typing,
and enrichment minting a free-text subcategory per merchant.

Deliberately not fuzzy matching. A tuned similarity threshold is a keyword list
with decimals, and recomputing similarity each run would let categories silently
re-merge and un-merge between runs. A recorded alias is auditable, stable, and
reversed by appending.
"""

from decimal import Decimal

from viva.ingest import RawStore, ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ingest.categorize import assign_category, rule_category_same_as
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


def _spending(ledger):
    return ledger.projection().spending_by_category()


def test_two_labels_for_one_thing_split_a_total_until_they_are_ruled(tmp_path):
    """Two labels for one thing split a total until a ruling merges them."""
    ledger = _vault(tmp_path, [("2026-03-05", "ATM WITHDRAWAL ONE", "-100.00"),
                               ("2026-03-06", "ATM WITHDRAWAL TWO", "-150.00")])
    keys = [m.key for m in ledger.projection().movements()]
    assign_category(ledger, keys[0], "poker")
    assign_category(ledger, keys[1], "playing poker")

    before = _spending(ledger)
    assert before.get("poker") == Decimal("100.00")
    assert before.get("playing poker") == Decimal("150.00"), "the split total"

    rule_category_same_as(ledger, "playing poker", "poker")

    after = _spending(ledger)
    assert after.get("poker") == Decimal("250.00"), "one label, one total"
    assert "playing poker" not in after


def test_the_ruling_is_retroactive_and_rewrites_nothing(tmp_path):
    """The event that said "playing poker" still says it — the fold happens on
    the read side, so a merge costs no re-ingest and is reversible."""
    ledger = _vault(tmp_path, [("2026-03-05", "ATM WITHDRAWAL ONE", "-100.00")])
    key = ledger.projection().movements()[0].key
    assign_category(ledger, key, "playing poker")
    rule_category_same_as(ledger, "playing poker", "poker")

    said = [e for e in ledger.store.events() if e.event_type == "CategoryAssigned"]
    assert said and said[0].body["category"] == "playing poker", \
        "history must keep what was actually recorded"
    assert _spending(ledger).get("poker") == Decimal("100.00")


def test_a_chain_of_aliases_resolves_and_a_cycle_does_not_hang(tmp_path):
    """A ruling loop is a mistake someone made; surviving it matters more than
    trusting it, because the read side must never be taken down by bad data."""
    ledger = _vault(tmp_path, [("2026-03-05", "ATM WITHDRAWAL ONE", "-100.00")])
    proj = ledger.projection()
    rule_category_same_as(ledger, "a", "b")
    rule_category_same_as(ledger, "b", "c")
    assert ledger.projection().canonical_category("a") == "c"

    rule_category_same_as(ledger, "x", "y")
    rule_category_same_as(ledger, "y", "x")
    assert ledger.projection().canonical_category("x") in ("x", "y")


def test_the_known_vocabulary_is_what_every_minting_path_is_offered(tmp_path):
    """Prevention is the cheapest of the three defences: show what exists before
    anything new can be created. Enrichment gets this list in its prompt, which
    is why a subcategory it invents is now a deliberate act."""
    ledger = _vault(tmp_path, [("2026-03-05", "ATM WITHDRAWAL ONE", "-100.00"),
                               ("2026-03-06", "ATM WITHDRAWAL TWO", "-150.00")])
    keys = [m.key for m in ledger.projection().movements()]
    assign_category(ledger, keys[0], "poker")
    assign_category(ledger, keys[1], "playing poker")
    assert set(ledger.projection().known_categories()) == {"poker", "playing poker"}

    rule_category_same_as(ledger, "playing poker", "poker")
    assert ledger.projection().known_categories() == ["poker"], \
        "a merged label must leave the vocabulary it was merged into"


def test_enrichment_is_shown_the_labels_that_already_exist():
    """The other end of the sprawl. Enrichment mints one free-text subcategory
    per merchant, hundreds of times, so its prompt is handed the labels that
    already exist rather than merely *asked* for consistency."""
    from merchantcore.enrich import build_enrichment_prompt
    prompt, version = build_enrichment_prompt(
        {"corner cafe": "CORNER CAFE"}, ["coffee shop", "warehouse club"])
    assert "coffee shop" in prompt and "warehouse club" in prompt
    assert "REUSE" in prompt
    assert version.startswith("enrich-v5")
    bare, _ = build_enrichment_prompt({"corner cafe": "CORNER CAFE"})
    assert "none yet" in bare, "an empty vault must not print an empty bracket"
