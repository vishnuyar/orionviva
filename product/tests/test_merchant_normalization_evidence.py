"""Discarded merchant evidence cannot give a processor identity authority."""

from decimal import Decimal

import pytest
from merchantcore.resolve import resolve_descriptor
from viva.ledger import LedgerProjection, account_opened, simple_transaction
from viva.ledger.events import merchant_enriched
from viva.ledger.hints import enrichment_hints
from viva.ledger.merchant_keys import MerchantKeys, resolve_keys
from viva.ledger.streams import build_streams

PAIR = ("AB *CEDARFURNITURE123, 555-010-0200",
        "AB *PINESUPPLY456, 555-010-0200")
SAFE = "TX*HARBORHEALTH, 555-010-0200"


def events(descriptors=PAIR):
    return [account_opened("synthetic-account", "depository", "Checking", "USD", "2026-01-01"),
            *[simple_transaction("synthetic-account", "-1", d, f"2026-01-{i + 2:02}")
              for i, d in enumerate(descriptors)]]


def projection(descriptors=PAIR, resolver=resolve_keys, extra=()):
    return LedgerProjection([*events(descriptors), *extra], resolve_keys=resolver)


def test_discarded_suffixes_are_distinct_unresolved_streams_without_hints():
    proj = projection()
    movements = proj.movements()
    streams = build_streams(movements, kind_for=lambda m: m.kind)
    assert len(streams) == 2
    assert sum(s.n for s in streams) == 2
    assert sum(m.amount for m in movements) == Decimal("-2")
    assert enrichment_hints(streams) == {}
    for descriptor in PAIR:
        res = resolve_descriptor(descriptor)
        assert res.identity_insufficient
        assert res.identity_candidates == ()
        assert res.brand == ""


@pytest.mark.parametrize("resolver", [resolve_keys, None, lambda rows: MerchantKeys()])
def test_reviewed_prefix_alias_and_stronger_legacy_record_cannot_restore_match(resolver):
    proj = projection(resolver=resolver, extra=[
        merchant_enriched("processor", "shopping", aliases=["ab"], grade="corroborated"),
        merchant_enriched("ab", "dining", grade="verified")])
    assert len(proj.merchant_categories()) == 2
    for movement in proj.movements():
        assert proj.merchant_keys_of(movement) == ("",)
        assert proj.derived_category(movement) is None


def test_order_repeats_accounts_and_sufficient_sibling_do_not_donate_identity():
    data = events([*PAIR, PAIR[0], "AB", SAFE])
    data += [account_opened("second-account", "depository", "Other", "USD", "2026-01-01"),
             simple_transaction("second-account", "-1", PAIR[0], "2026-01-08")]
    movements = LedgerProjection(data, resolve_keys=resolve_keys).movements()
    forward = build_streams(movements, kind_for=lambda m: m.kind)
    backward = build_streams(reversed(movements), kind_for=lambda m: m.kind)
    assert forward == backward
    import json
    exported = json.dumps([s.to_dict() for s in forward])
    for private in (*PAIR, "synthetic-account", "second-account"):
        assert private not in exported
    insufficient = [s for s in forward if s.identity_insufficient]
    assert sorted(s.n for s in insufficient) == [1, 1, 2]
    assert all(s.counterparty == s.brand == "" and not s.identity_candidates
               for s in insufficient)
    assert set(enrichment_hints(forward)) == {"ab", "harborhealth"}
    assert enrichment_hints(forward)["ab"].movements == 1
    assert sum(s.n for s in forward) == 6


@pytest.mark.parametrize("descriptor", [*PAIR, "LONGCONDUIT *CEDARFURNITURE123, 555-010-0200"])
def test_processor_origin_not_prefix_length_controls_refusal(descriptor):
    resolved = resolve_descriptor(descriptor)
    assert resolved.identity_insufficient
    assert resolved.merchant_key == resolved.brand == resolved.example() == ""
    assert resolved.identity_candidates == ()
    assert not resolve_descriptor(descriptor.split("*")[0].strip()).identity_insufficient


def ledger_at(tmp_path, descriptors=PAIR):
    from viva.ledger import EventStore, Ledger
    store = EventStore.open(tmp_path / "synthetic-events", "synthetic-passphrase")
    store.append_atomically(lambda _: tuple(events(descriptors)))
    return Ledger(store, resolve_keys=resolve_keys)


def test_fresh_batch_is_zero_call_and_mixed_prompt_has_only_safe_evidence(tmp_path):
    import json
    from merchantcore import Catalog
    from viva.ingest import enrich_merchants
    ledger = ledger_at(tmp_path)
    catalog = Catalog()
    prompts = []

    def extract(prompt):
        prompts.append(prompt)
        return '{}'

    result = enrich_merchants(ledger, catalog, extract, kind_for=lambda m: m.kind)
    assert result["offered"] == result["submitted"] == result["enriched"] == 0
    assert prompts == [] and catalog.pending() == {} and catalog.records() == {}
    ledger.append(simple_transaction("synthetic-account", "-731.19", SAFE, "2026-01-10"))
    enrich_merchants(ledger, catalog, extract, kind_for=lambda m: m.kind)
    assert len(prompts) == 1 and "HARBORHEALTH" in prompts[0]
    captured = json.dumps([prompts, catalog.pending(), catalog.export()])
    for forbidden in (*PAIR, "CEDARFURNITURE", "PINESUPPLY", "synthetic-account",
                      "2026-01-10", "731.19", "555-010-0200", *[m.key for m in ledger.projection().movements()]):
        assert forbidden not in captured


def test_historical_pending_is_retained_and_consumed_independently(tmp_path):
    from merchantcore import Catalog
    from viva.ingest import enrich_merchants
    ledger = ledger_at(tmp_path)
    catalog = Catalog()
    catalog.submit([("ab", "AB")])
    prompts = []
    result = enrich_merchants(ledger, catalog, lambda p: prompts.append(p) or '{}',
                              kind_for=lambda m: m.kind)
    assert result["offered"] == result["submitted"] == 0
    assert len(prompts) == 1
    assert "ab" in catalog.queued()
    assert "ab" in catalog.unanswered()


def test_existing_key_refresh_retains_records_without_restoring_movement_match(tmp_path):
    from merchantcore import Catalog, MerchantRecord
    from viva.ingest.categorize import merchant_records_to_sync, sync_merchant_records
    ledger = ledger_at(tmp_path, [*PAIR, "AB"])
    ledger.append(merchant_enriched("ab", "shopping", grade="unverified"))
    catalog = Catalog()
    catalog.add(MerchantRecord(key="ab", category="dining", grade="verified"))
    assert set(merchant_records_to_sync(ledger, catalog, offered={})) == {"ab"}
    assert sync_merchant_records(ledger, catalog, offered={}) == 1
    proj = ledger.projection()
    assert proj.merchant_categories()["ab"]["grade"] == "verified"
    for movement in proj.movements():
        if movement.description in PAIR:
            assert proj.derived_category(movement) is None
        else:
            assert proj.derived_category(movement)["category"] == "dining"


def test_historical_merchant_ruling_stays_recorded_and_movement_correction_wins(tmp_path):
    from viva.ingest import assign_category
    from viva.ledger.events import ruling_recorded
    ledger = ledger_at(tmp_path)
    ruling = ruling_recorded("merchant", "ab", "2026-01-09", grade="verified", by="human",
                             legs=[{"major": "asset", "account": "Unassigned"}])
    ledger.append(ruling)
    stored_ruling = next(e for e in ledger.events() if e.event_type == "RulingRecorded")
    assert stored_ruling.body["scope"] == "merchant"
    assert stored_ruling.body["subject"] == "ab"
    assert stored_ruling.body["grade"] == "verified"
    proj = ledger.projection()
    first, second = proj.movements()
    assert all(m.nature_reason != "ruling" for m in (first, second))
    assert stored_ruling in ledger.events()
    assign_category(ledger, first.key, "shopping")
    proj = ledger.projection()
    assert proj.derived_category(first)["category"] == "shopping"
    assert proj.derived_category(second) is None
    assert stored_ruling in ledger.events()


def test_installed_import_sync_does_not_offer_prefix(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from merchantcore import Catalog, MerchantRecord
    from viva import enrich, induce_profile
    ledger = ledger_at(tmp_path)
    catalog_path = tmp_path / "isolated-catalog.json"
    catalog = Catalog(catalog_path)
    catalog.add(MerchantRecord(key="ab", category="shopping", grade="verified", aliases=["ab"]))
    monkeypatch.setattr(enrich, "catalog_path", lambda _: catalog_path)
    monkeypatch.setattr(induce_profile, "profile_store", lambda: SimpleNamespace(latest_for=lambda *args: None))
    monkeypatch.setattr("merchantcore.home.shipped_catalog_file", lambda: tmp_path / "no-shipped.json")
    assert enrich.sync_installed_merchants(SimpleNamespace(ledger=ledger), "") == 0
    assert ledger.projection().merchant_categories() == {}


def test_indexed_lookup_rebuild_and_reopen_keep_insufficient_evidence_unmatched(tmp_path):
    from viva.read_store import ReadStore
    ledger = ledger_at(tmp_path)
    ledger.append(merchant_enriched("ab", "shopping", grade="verified", aliases=["ab"]))
    root = tmp_path / "read"
    with ReadStore.create(root, "synthetic-passphrase") as reads:
        reads.synchronize(ledger.store, projector_version="synthetic-older-projector")
        assert reads.synchronize(ledger.store).state == "rebuilt"
    with ReadStore.open(root, "synthetic-passphrase") as reads:
        with reads.open_reader() as revision:
            rows = revision.connection.execute("SELECT movement_key,merchant_key,category FROM movements").fetchall()
            assert {row[0] for row in rows} == {m.key for m in ledger.projection().movements()}
            assert all(row[1:] == ("", "") for row in rows)
        ledger.append(merchant_enriched("ab", "dining", grade="verified"))
        reads.synchronize(ledger.store)
        with reads.open_reader() as revision:
            assert revision.connection.execute("SELECT merchant_key,category FROM movements").fetchall() == [("", ""), ("", "")]


def test_unresolved_descriptors_do_not_borrow_a_siblings_rail():
    unknown = "AB*CEDARFURNITURE123"
    proj = projection([unknown, PAIR[1]])
    streams = build_streams(proj.movements(), kind_for=lambda m: m.kind)
    assert {s.occurrences[0].description: s.channel for s in streams} == {
        unknown: "unknown", PAIR[1]: "card"}


def test_independent_grammar_brand_still_uses_existing_corroboration():
    from merchantcore.profile import Profile, Template
    grammar = Profile("invented", "depository", "v1", [
        Template("{brand}*{reference}")])
    raw = "XY*CEDARFURNITURE123"
    res = resolve_descriptor(raw, grammar)
    assert res.brand == "XY" and not res.identity_insufficient
    streams = build_streams(projection([raw]).movements(),
                            profile_for=lambda _: grammar, kind_for=lambda m: m.kind)
    assert enrichment_hints(streams) == {}
