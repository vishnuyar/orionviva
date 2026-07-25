"""merchantcore — the merchant knowledge base: normalize, enrich, catalog."""

from merchantcore import (Catalog, Enricher, MerchantRecord, PRIMARY_CATEGORIES,
                          canonical_primary, is_shareable, normalize_merchant,
                          NORMALIZER_VERSION)


def test_sixteen_primary_categories():
    assert len(PRIMARY_CATEGORIES) == 16
    assert "groceries" in PRIMARY_CATEGORIES and "travel" in PRIMARY_CATEGORIES
    assert canonical_primary("Groceries") == "groceries"
    assert canonical_primary("nonsense") == "other"      # falls back


def test_enrichment_returns_subcategory_mcc_and_logo():
    def extract(prompt):
        assert "subcategory" in prompt and "mcc" in prompt      # v2 asks for them
        return ('{"costco whse": {"canonical_name":"Costco","category":"groceries",'
                '"subcategory":"Warehouse Club","mcc":"5300",'
                '"website":"costco.com","logo":"logo.clearbit.com/costco.com"}}')
    r = Enricher(extract).enrich({"costco whse": "COSTCO WHSE"})["costco whse"]
    assert r.category == "groceries"
    assert r.subcategory == "warehouse club"               # normalized (lowercased)
    assert r.attributes["mcc"] == "5300"
    assert r.attributes["logo_url"].endswith("costco.com")


def test_normalize_is_deterministic_and_versioned():
    assert normalize_merchant("AMZN MKTP US*RA30Z3BP0") == normalize_merchant("AMZN MKTP US*RH4DD6YM1")
    assert normalize_merchant("KROGER #0548") == "kroger"
    assert NORMALIZER_VERSION


def test_peer_payment_is_not_shareable():
    assert not is_shareable("VENMO PAYMENT TO JOHN SMITH")
    assert is_shareable("COSTCO WHSE #0664")


def test_enricher_is_one_call_and_grades_records():
    calls = []

    def extract(prompt):
        calls.append(prompt)
        return ('{"amzn mktp us": {"canonical_name":"Amazon","category":"shopping",'
                '"description":"online retailer","website":"amazon.com"},'
                '"kroger": {"canonical_name":"Kroger","category":"groceries"}}')

    recs = Enricher(extract).enrich({"amzn mktp us": "AMZN MKTP US", "kroger": "KROGER"})
    assert len(calls) == 1                             # one batched call
    assert recs["amzn mktp us"].canonical_name == "Amazon"
    assert recs["amzn mktp us"].category == "shopping"
    assert recs["amzn mktp us"].attributes["website"] == "amazon.com"
    assert recs["amzn mktp us"].grade == "corroborated"   # a model batch, not verified
    assert "merch-v1" in recs["amzn mktp us"].version     # normalizer version carried


def test_enricher_chunks_a_large_batch_into_several_calls():
    # More merchants than one chunk holds → several calls, all merged, none lost.
    merchants = {f"m{i}": f"MERCHANT {i}" for i in range(95)}
    seen = []

    def extract(prompt):
        # Answer only for the keys this chunk actually asked about.
        keys = [ln.split(":")[0][2:].strip()
                for ln in prompt.splitlines() if ln.startswith("- m")]
        seen.append(len(keys))
        return "{" + ",".join(f'"{k}":{{"category":"shopping"}}' for k in keys) + "}"

    recs = Enricher(extract, chunk_size=40).enrich(merchants)
    assert len(recs) == 95                       # every merchant enriched
    assert seen == [40, 40, 15]                  # 40 + 40 + 15, three calls
    assert all(r.category == "shopping" for r in recs.values())


def test_a_broken_chunk_does_not_sink_the_others():
    merchants = {f"m{i}": f"M{i}" for i in range(60)}

    def extract(prompt):
        keys = [ln.split(":")[0][2:].strip()
                for ln in prompt.splitlines() if ln.startswith("- m")]
        if "m0" in keys:                         # first chunk: truncated garbage
            return '{"m0":{"category":"shopping"'
        return "{" + ",".join(f'"{k}":{{"category":"dining"}}' for k in keys) + "}"

    recs = Enricher(extract, chunk_size=40).enrich(merchants)
    # First chunk parsed to nothing, but the second chunk's 20 still landed.
    assert len(recs) == 20 and all(r.category == "dining" for r in recs.values())


def test_enricher_skips_a_bad_category_and_unknown_keys():
    def extract(prompt):
        return '{"acme": {"canonical_name":"Acme","category":"nonsense"}}'
    recs = Enricher(extract).enrich({"acme": "ACME"})
    assert recs["acme"].category == "other"            # invalid category -> other


def test_catalog_pending_add_and_linted_export(tmp_path):
    cat = Catalog(tmp_path / "catalog.json")
    assert cat.submit([("amzn mktp us", "AMZN"), ("venmo to john", "VENMO TO JOHN")]) == 2
    assert set(cat.pending()) == {"amzn mktp us", "venmo to john"}
    cat.add(MerchantRecord(key="amzn mktp us", canonical_name="Amazon", category="shopping"))
    cat.add(MerchantRecord(key="venmo to john", category="other"))
    assert "amzn mktp us" not in cat.pending()          # promoted out of pending
    # Export is linted: the peer merchant is filtered, and no non-record fields.
    export = cat.export()
    assert "amzn mktp us" in export and "venmo to john" not in export
    # Persists as plain JSON (impersonal, unencrypted-safe) and reloads.
    reloaded = Catalog(tmp_path / "catalog.json")
    assert reloaded.get("amzn mktp us").canonical_name == "Amazon"


def test_catalog_merge_prior_loses_to_local_verified():
    cat = Catalog()
    cat.add(MerchantRecord(key="amzn mktp us", category="groceries", grade="verified"))
    cat.merge({"amzn mktp us": {"key": "amzn mktp us", "category": "shopping",
                                "grade": "corroborated"}})
    assert cat.get("amzn mktp us").category == "groceries"   # local verified wins
