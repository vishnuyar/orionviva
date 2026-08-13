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

import re
from decimal import Decimal

from viva.ingest import RawStore, ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ingest.categorize import (assign_category, assign_merchant_category,
                                    rule_category_same_as)
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
    from merchantcore.enrich import PROMPTS, build_enrichment_prompt
    from merchantcore.taxonomy import seed_subcategories
    from vivacore import promptstore
    prompt, version = build_enrichment_prompt(
        {"corner cafe": "CORNER CAFE"}, ["coffee shop", "warehouse club"])
    assert "coffee shop" in prompt and "warehouse club" in prompt
    assert "REUSE" in prompt
    # Which prompt is in force is the manifest's to say, so no version is
    # named here. What is checked is that the version stamped resolves to the
    # text this prompt was built from, and that the labels above are shown by
    # that text.
    stamped = version.split("+")[0]
    body = promptstore.load(PROMPTS, stamped)
    # Composing fills the placeholders and collapses the doubled braces that
    # protect the reply's own shape; everything else in the file survives.
    fixed = [chunk.replace("{{", "{").replace("}}", "}")
             for chunk in re.split(r"\{\w+\}", body)]
    assert all(chunk in prompt for chunk in fixed)
    # A vault with no vocabulary of its own gets the package's shipped one in
    # the slot; only a package shipping nothing falls back to "none yet".
    bare, _ = build_enrichment_prompt({"corner cafe": "CORNER CAFE"})
    shipped = seed_subcategories()
    if shipped:
        assert all(label in bare for label in shipped)
    else:
        assert "none yet" in bare, "an empty vault must not print an empty bracket"


def test_a_seed_label_never_displaces_one_a_person_minted():
    """A seed wins on spelling where the two are already one label under
    punctuation, and nowhere else: a label that differs at all is offered
    alongside and is never removed."""
    from merchantcore.taxonomy import subcategory_vocabulary
    seed = ("coffee shop", "wholesale club")
    shown = subcategory_vocabulary(["coffee-shop", "school lunch"], seed=seed)
    assert shown == ("coffee shop", "wholesale club", "school lunch"), \
        "the seed leads, its own re-spelling folds into it, a new label stays"
    assert "coffee-shop" not in shown, "one idea is offered in one spelling"


def test_a_vault_with_no_seed_is_shown_exactly_what_it_uses():
    """With no shipped vocabulary the slot holds the vault's labels alone."""
    from merchantcore.taxonomy import subcategory_vocabulary
    assert subcategory_vocabulary(["school lunch", "poker night"], seed=()) == \
        ("school lunch", "poker night")


def test_punctuation_is_one_label_and_everything_past_it_is_two():
    """Separators fold into one identity; a plural, a connective or a synonym
    stays a second label. Characters only, no morphology."""
    from merchantcore.taxonomy import subcategory_identity as ident
    assert ident("credit_card_payment") == ident("credit card payment")
    assert ident("peer_to_peer") == ident("peer-to-peer")
    assert ident("gym & fitness") == ident("gym and fitness")
    assert ident("Coffee   Shop") == ident("coffee shop")
    assert ident("restaurant") != ident("restaurants")
    assert ident("internet cable") != ident("internet and cable")
    assert ident("supermarket") != ident("grocery store")


def _three_spellings(tmp_path):
    """A vault whose three merchants were filed under one idea spelled three
    ways: an underscore, a space, and a plural."""
    ledger = _vault(tmp_path, [("2026-03-05", "ALPHA STORE", "-100.00"),
                               ("2026-03-06", "BETA STORE", "-150.00"),
                               ("2026-03-07", "GAMMA STORE", "-40.00")])
    for merchant, subcategory in (("ALPHA STORE", "book_shop"),
                                  ("BETA STORE", "book shop"),
                                  ("GAMMA STORE", "book shops")):
        assign_merchant_category(ledger, merchant, "shopping",
                                 subcategory=subcategory)
    return ledger


def test_two_spellings_of_one_subcategory_are_one_line_in_a_report(tmp_path):
    """The fold reaches the totals, at the funnel every aggregate reads."""
    finer = _three_spellings(tmp_path).projection().spending_by_subcategory()
    assert finer.get("book shop") == Decimal("250.00"), \
        "an underscore is not a distinction"
    assert finer.get("book shops") == Decimal("40.00"), \
        "a plural might be, so nothing here decides it"


def test_a_run_can_say_which_spellings_it_folded(tmp_path):
    """The spellings the separator fold brought together are reportable, and a
    plural is not among them."""
    assert _three_spellings(tmp_path).projection().subcategory_merges() == {
        "book shop": ["book shop", "book_shop"]}, \
        "only where two spellings actually met, and never a plural"


def test_the_finer_vocabulary_is_offered_as_the_totals_count_it(tmp_path):
    """The offered vocabulary is spelled as the totals count it."""
    assert _three_spellings(tmp_path).projection().known_subcategories() == \
        ["book shop", "book shops"]


def test_a_ruling_on_either_spelling_moves_the_whole_folded_line(tmp_path):
    """A ruling recorded against either spelling of a folded line moves the
    whole line, and leaves a label outside the fold where it was."""
    for ruled in ("book shop", "book_shop"):
        ledger = _three_spellings(tmp_path / ruled.replace(" ", "-"))
        before = ledger.projection().spending_by_subcategory()
        assert before.get("book shop") == Decimal("250.00"), "one line"

        rule_category_same_as(ledger, ruled, "stationery")

        after = ledger.projection().spending_by_subcategory()
        assert after.get("stationery") == Decimal("250.00"), \
            f"ruling {ruled!r} must move the whole line"
        assert "book shop" not in after and "book_shop" not in after
        assert after.get("book shops") == Decimal("40.00"), \
            "a plural is still nobody's decision but the person's"


def test_a_ruling_naming_its_target_in_another_spelling_still_merges(tmp_path):
    """The fold reaches both sides of a ruling: whichever spelling the subject
    or the target is written in, the money lands on one line."""
    ledger = _vault(tmp_path, [("2026-03-05", "ALPHA STORE", "-250.00"),
                               ("2026-03-06", "BETA STORE", "-40.00")])
    for merchant, subcategory in (("ALPHA STORE", "coffee shop"),
                                  ("BETA STORE", "cafe")):
        assign_merchant_category(ledger, merchant, "shopping",
                                 subcategory=subcategory)
    before = ledger.projection().spending_by_subcategory()
    assert before == {"coffee shop": Decimal("250.00"),
                      "cafe": Decimal("40.00")}, "two labels, two totals"

    rule_category_same_as(ledger, "cafe", "coffee_shop")

    assert ledger.projection().spending_by_subcategory() == {
        "coffee shop": Decimal("290.00")}, \
        "a ruled merge is one line, however the target was spelled"
    assert ledger.projection().known_subcategories() == ["coffee shop"], \
        "and the vocabulary offers the one label, not the spelling ruled to"


def test_a_ruling_on_a_folded_line_does_not_silence_the_merge_report(tmp_path):
    """A ruling landing on a folded group does not remove it from the merge
    report; it changes the label the spellings are counted under."""
    ledger = _three_spellings(tmp_path)
    rule_category_same_as(ledger, "book_shop", "stationery")
    assert ledger.projection().subcategory_merges() == {
        "stationery": ["book shop", "book_shop"]}
    assert ledger.projection().known_subcategories() == \
        ["book shops", "stationery"], \
        "the vocabulary is spelled as the totals count it, after a ruling too"


def test_a_merge_a_person_ruled_is_not_reported_as_one_nobody_asked_about(tmp_path):
    """A fold a person recorded has an event behind it and is not reported as
    a merge nobody was asked about."""
    ledger = _vault(tmp_path, [("2026-03-05", "ALPHA STORE", "-100.00"),
                               ("2026-03-06", "BETA STORE", "-150.00")])
    for merchant, subcategory in (("ALPHA STORE", "book shop"),
                                  ("BETA STORE", "stationery")):
        assign_merchant_category(ledger, merchant, "shopping",
                                 subcategory=subcategory)
    rule_category_same_as(ledger, "book shop", "stationery")
    assert ledger.projection().spending_by_subcategory() == {
        "stationery": Decimal("250.00")}
    assert ledger.projection().subcategory_merges() == {}
