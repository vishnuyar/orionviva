"""A seed names a label; the anchor carries it; only a person merges two.

Covers the shipped subcategory vocabulary and its reader, the vocabulary a
model is shown, the anchor that grows across a run's chunks, and the shipped
catalog layer the loader sits on.

The rule that governs the first three: a seed leads the list and wins on
spelling where two labels are already one under punctuation; where they differ
at all, both are offered and the label already in use is never removed.
"""

import json

import pytest

from merchantcore import Catalog, Enricher, MerchantRecord
from merchantcore.enrich import build_enrichment_prompt
from merchantcore.taxonomy import (PRIMARY_CATEGORIES, FALLBACK_CATEGORY,
                                   read_subcategory_seed, seed_subcategories,
                                   seed_subcategories_by_category,
                                   subcategory_identity, subcategory_vocabulary)

# Clearly not a vocabulary anybody would ship: four labels invented for a test.
FIXTURE_SEED = {
    "groceries": {"corner shop": "a small food shop",
                  "market stall": "an outdoor food seller"},
    "entertainment": {"board game": "a game played on a table"},
    "other": {"unnamed": "money nothing above describes"},
}


def _seed_file(tmp_path, subcategories=None, version=None) -> str:
    """A seed file is named for the version it declares, exactly as the shipped
    one is; a fixture that disagrees with itself is written on purpose."""
    path = tmp_path / "seed-v1.json"
    path.write_text(json.dumps(
        {"version": path.stem if version is None else version,
         "subcategories": subcategories or FIXTURE_SEED}))
    return str(path)


# --- the file ---------------------------------------------------------------

def test_a_seed_file_reads_as_flat_labels_in_the_order_it_lists_them(tmp_path):
    assert read_subcategory_seed(_seed_file(tmp_path)) == (
        "corner shop", "market stall", "board game", "unnamed")


def test_a_seed_label_that_is_also_a_primary_is_refused(tmp_path):
    """One alias namespace serves both levels, so a label colliding with a
    primary blurs the nested view that is supposed to sum."""
    path = _seed_file(tmp_path, {"groceries": {"personal care": "a collision"}})
    with pytest.raises(ValueError) as e:
        read_subcategory_seed(path)
    assert "primary category name" in str(e.value)


def test_a_seed_grouped_under_something_that_is_not_a_primary_is_refused(tmp_path):
    path = _seed_file(tmp_path, {"snacks": {"crisps": "a salty thing"}})
    with pytest.raises(ValueError) as e:
        read_subcategory_seed(path)
    assert "not a primary category" in str(e.value)


def test_a_label_the_file_already_names_is_refused(tmp_path):
    """A label named twice raises rather than costing the file one entry: a
    reviewer counting lines is the only trace a silent drop would leave."""
    path = _seed_file(tmp_path, {
        "groceries": {"corner shop": "a small food shop"},
        "housing": {"corner shop": "a shop on a corner of a building"}})
    with pytest.raises(ValueError) as e:
        read_subcategory_seed(path)
    assert "corner shop" in str(e.value)


def test_two_spellings_of_one_label_are_refused_as_one_label(tmp_path):
    """Two entries the separator fold gives one identity are one label named
    twice, whatever they look like on the line."""
    path = _seed_file(tmp_path, {
        "groceries": {"corner shop": "a small food shop",
                      "corner-shop": "the same thing, hyphenated"}})
    with pytest.raises(ValueError):
        read_subcategory_seed(path)


def test_a_file_whose_version_is_not_its_name_is_refused(tmp_path):
    """A record's stamped version must resolve to one file's bytes forever, so
    a file copied to a new name and left declaring the old one is refused
    rather than read."""
    path = _seed_file(tmp_path, version="cat-v99")
    with pytest.raises(ValueError) as e:
        read_subcategory_seed(path)
    assert "version" in str(e.value)


def test_a_primary_carrying_no_labels_is_refused(tmp_path):
    with pytest.raises(ValueError):
        read_subcategory_seed(_seed_file(tmp_path, {"groceries": {}}))


def test_a_primary_that_is_not_a_group_of_labels_is_refused(tmp_path):
    with pytest.raises(ValueError):
        read_subcategory_seed(_seed_file(
            tmp_path, {"groceries": ["corner shop"]}))


def test_a_file_naming_no_vocabulary_is_refused(tmp_path):
    """A file whose labels are missing, emptied or null raises.

    It would otherwise read as a package shipping no vocabulary at all, and the
    prompt would fall back to the vault's own labels with nothing said."""
    for holds in ({}, None, "nothing"):
        path = tmp_path / "seed-v1.json"
        path.write_text(json.dumps({"version": "seed-v1",
                                    "subcategories": holds}))
        with pytest.raises(ValueError) as e:
            read_subcategory_seed(path)
        assert "no subcategories" in str(e.value)
    bare = tmp_path / "seed-v1.json"
    bare.write_text(json.dumps({"version": "seed-v1"}))
    with pytest.raises(ValueError):
        read_subcategory_seed(bare)


def test_a_file_that_is_not_a_vocabulary_at_all_is_refused(tmp_path):
    """Whatever the file turns out to hold, the reader says what is wrong with
    it rather than failing on the shape of its own read."""
    path = tmp_path / "seed-v1.json"
    path.write_text(json.dumps(["corner shop", "market stall"]))
    with pytest.raises(ValueError):
        read_subcategory_seed(path)


def test_a_label_with_no_gloss_is_refused(tmp_path):
    """Every label carries a gloss, so the file can be read line by line."""
    with pytest.raises(ValueError):
        read_subcategory_seed(_seed_file(tmp_path, {"groceries": {"corner shop": ""}}))


def test_a_label_holding_an_ampersand_is_refused(tmp_path):
    """The convention the file states for itself is checked: `and` is spelled
    out rather than written as an ampersand."""
    with pytest.raises(ValueError) as e:
        read_subcategory_seed(_seed_file(
            tmp_path, {"groceries": {"food & drink": "a shop selling both"}}))
    assert "ampersand" in str(e.value)


def test_the_shipped_vocabulary_is_read_through_every_guard():
    """The file this package actually ships goes through the same reader a
    fixture does, so a later edit cannot reintroduce a collision, a repeat, a
    missing gloss or a stale version without the suite saying so."""
    shipped = seed_subcategories()
    assert shipped, "the package ships a vocabulary"
    reserved = {subcategory_identity(p)
                for p in tuple(PRIMARY_CATEGORIES) + (FALLBACK_CATEGORY,)}
    assert not reserved & {subcategory_identity(label) for label in shipped}
    assert all(label == label.strip().lower() for label in shipped)


def test_the_shipped_hierarchy_is_the_same_vocabulary_without_losing_parents():
    grouped = seed_subcategories_by_category()

    assert grouped
    assert set(grouped) <= set(PRIMARY_CATEGORIES) | {FALLBACK_CATEGORY}
    assert tuple(label for labels in grouped.values() for label in labels) == \
        seed_subcategories()
    assert "supermarket" in grouped["groceries"]
    assert "supermarket" not in grouped["dining"]


# --- what a model is shown --------------------------------------------------

def test_the_seed_leads_and_a_vault_label_follows(tmp_path):
    seed = read_subcategory_seed(_seed_file(tmp_path))
    assert subcategory_vocabulary(["night market"], seed=seed) == (
        "corner shop", "market stall", "board game", "unnamed", "night market")


def test_a_seed_and_a_vault_label_differing_only_in_separators_appear_once(tmp_path):
    """The one case a seed may overrule: the same label, spelled two ways."""
    seed = read_subcategory_seed(_seed_file(tmp_path))
    shown = subcategory_vocabulary(["Corner-Shop", "board_game"], seed=seed)
    assert shown == ("corner shop", "market stall", "board game", "unnamed")


def test_a_vault_label_the_seed_does_not_hold_is_never_removed(tmp_path):
    seed = read_subcategory_seed(_seed_file(tmp_path))
    shown = subcategory_vocabulary(["corner shops", "market and stall"], seed=seed)
    assert "corner shops" in shown and "market and stall" in shown, \
        "a plural or a connective may be a distinction somebody meant"


def test_with_no_seed_the_slot_holds_exactly_what_the_vault_uses():
    assert subcategory_vocabulary(["board game"], seed=()) == ("board game",)


def test_the_prompt_carries_the_vocabulary_it_was_given():
    prompt, _ = build_enrichment_prompt({"corner cafe": "CORNER CAFE"},
                                        ["board game"])
    assert "board game" in prompt


# --- the anchor grows within a run -----------------------------------------

def _reply(key, subcategory):
    return json.dumps({key: {"canonical_name": key.title(), "category": "shopping",
                             "subcategory": subcategory}})


def test_the_second_chunk_is_shown_what_the_first_one_minted():
    """A label chunk N mints is in the list chunk N+1 is shown."""
    prompts, answers = [], iter(["board game", "board game"])

    def extract(prompt):
        prompts.append(prompt)
        key = prompt.rsplit("- ", 1)[1].split(":")[0]
        return _reply(key, next(answers))

    Enricher(extract, chunk_size=1).enrich({"alpha shop": "ALPHA SHOP",
                                            "beta shop": "BETA SHOP"})
    assert "board game" not in prompts[0]
    assert "board game" in prompts[1]


def test_a_run_reports_the_labels_it_minted():
    """A label outside the list a chunk was shown is counted, not blocked."""
    answers = iter(["board game", "kite shop"])

    def extract(prompt):
        key = prompt.rsplit("- ", 1)[1].split(":")[0]
        return _reply(key, next(answers))

    enricher = Enricher(extract, chunk_size=1, known_subcategories=["board game"])
    enricher.enrich({"alpha shop": "ALPHA SHOP", "beta shop": "BETA SHOP"})
    assert enricher.minted == ["kite shop"], "only what the list did not hold"


def test_respelling_a_label_that_was_shown_is_not_minting():
    def extract(prompt):
        key = prompt.rsplit("- ", 1)[1].split(":")[0]
        return _reply(key, "Board-Game")

    enricher = Enricher(extract, chunk_size=1, known_subcategories=["board game"])
    enricher.enrich({"alpha shop": "ALPHA SHOP"})
    assert enricher.minted == []


def test_a_second_run_starts_from_the_anchor_it_was_given():
    """The growth belongs to a run. A new run reads the vault's vocabulary
    again, so nothing is carried on an object's memory instead of the record."""
    def extract(prompt):
        key = prompt.rsplit("- ", 1)[1].split(":")[0]
        return _reply(key, "kite shop")

    enricher = Enricher(extract, chunk_size=1)
    enricher.enrich({"alpha shop": "ALPHA SHOP"})
    enricher.enrich({"beta shop": "BETA SHOP"})
    assert enricher.minted == ["kite shop"]


# --- the shipped catalog the loader was written for -------------------------

def _catalog_file(path, key, grade="corroborated") -> str:
    path.write_text(json.dumps({"records": {
        key: MerchantRecord(key=key, canonical_name=key.title(),
                            category="shopping", grade=grade).to_dict()}}))
    return str(path)


def test_a_shipped_catalog_is_read_and_marked_as_shipped(tmp_path):
    shipped = _catalog_file(tmp_path / "shipped.json", "alpha shop")
    catalog = Catalog(tmp_path / "learned.json", shipped=shipped)
    assert catalog.get("alpha shop").source == "shipped"


def test_a_learned_catalog_does_not_erase_the_seed(tmp_path):
    """The seed is laid down first and what this installation learned sits on
    top of it, key by key."""
    shipped = _catalog_file(tmp_path / "shipped.json", "alpha shop")
    learned = _catalog_file(tmp_path / "learned.json", "beta shop")
    catalog = Catalog(learned, shipped=shipped)
    assert set(catalog.records()) == {"alpha shop", "beta shop"}


def test_a_learned_record_wins_over_a_shipped_one_whatever_the_grade(tmp_path):
    """Learned first, shipped second — the precedence `home` states for every
    store — per key and outright, whatever grade either record carries."""
    shipped = tmp_path / "shipped.json"
    _catalog_file(shipped, "alpha shop", grade="verified")
    learned = tmp_path / "learned.json"
    _catalog_file(learned, "alpha shop", grade="unverified")
    catalog = Catalog(learned, shipped=str(shipped))
    assert catalog.get("alpha shop").grade == "unverified"
    assert catalog.get("alpha shop").source == "model"


def test_a_seed_survives_the_first_save_and_stays_distinguishable(tmp_path):
    shipped = _catalog_file(tmp_path / "shipped.json", "alpha shop")
    learned = tmp_path / "learned.json"
    catalog = Catalog(learned, shipped=shipped)
    catalog.add(MerchantRecord(key="beta shop", category="shopping"))
    reopened = Catalog(learned, shipped=shipped)
    assert set(reopened.records()) == {"alpha shop", "beta shop"}
    assert reopened.get("alpha shop").source == "shipped"
    assert reopened.get("beta shop").source == "model"


def test_a_seeded_merchant_is_never_asked_about(tmp_path):
    """A key the shipped catalog already holds is neither submitted nor
    pending, so it costs no model call."""
    shipped = _catalog_file(tmp_path / "shipped.json", "alpha shop")
    catalog = Catalog(tmp_path / "learned.json", shipped=shipped)
    assert catalog.submit([("alpha shop", "ALPHA SHOP")]) == 0
    assert catalog.pending() == {}
