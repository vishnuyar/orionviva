"""merchantcore — the merchant knowledge base: normalize, enrich, catalog."""

from merchantcore.descriptor import (brand_candidate,
                                     parse_descriptor)
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
        assert "subcategory" in prompt and "mcc" in prompt      # the prompt asks
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
    assert "merch-v2" in recs["amzn mktp us"].version     # normalizer version carried


def test_enricher_chunks_a_large_batch_into_several_calls():
    # More merchants than one chunk holds: several calls, merged, none lost.
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


# --- a posting date is not part of a merchant's name ------------------------

def test_a_date_fragment_does_not_become_part_of_the_key():
    """A posting date is stripped, so one merchant seen in two months is one
    key rather than two headed by a bare month number."""
    assert normalize_merchant("02/14 SAFEHARBOR MARKET") == "safeharbor market"
    assert (normalize_merchant("02/14 SAFEHARBOR MARKET")
            == normalize_merchant("03/09 SAFEHARBOR MARKET"))
    assert normalize_merchant("12-31 LUMEN ENERGY") == "lumen energy"


def test_a_bare_number_can_still_be_part_of_a_name():
    """Only a fragment carrying a separator is a date; a bare number stays,
    because it can be the name itself."""
    assert normalize_merchant("7 ELEVEN 33412") == "7 eleven"


# --- Layer 0: claim what a published rule proves, and name the rest ---------

def test_the_asterisk_separates_an_aggregator_from_what_it_sold():
    """The asterisk sits at a processor-mandated index, so the prefix is the
    aggregator and what follows is the brand candidate."""
    p = parse_descriptor("SQ *BLUE BOTTLE COFFEE SAN FRANCISCO CA")
    assert p.get("aggregator") == "SQ"
    assert "BLUE BOTTLE COFFEE" in brand_candidate(p)


def test_a_trailing_two_letter_code_is_the_region_subfield():
    p = parse_descriptor("COSTCO WHSE #0664 PLANO TX")
    assert p.get("region") == "TX"
    assert p.get("store_number") == "#0664"
    assert brand_candidate(p) == "COSTCO WHSE"


def test_a_phone_where_the_city_belongs_means_the_card_was_not_present():
    """The networks require the 13-character city slot to carry a phone number
    or URL for card-absent transactions, so a phone there sets
    `card_not_present` and an ordinary city does not."""
    assert parse_descriptor("SOME MERCHANT 617-SERVICE").card_not_present
    assert parse_descriptor("COSTCO WHSE #0664 PLANO TX").card_not_present is False


def test_a_city_is_marked_inferred_because_adjacency_is_not_proof():
    """The region code is proved by the layout; the city is only adjacent to
    it, so the region slot is `certain` and the city slot is not, and the
    distinction reaches `to_dict` as `provenance`."""
    p = parse_descriptor("COSTCO WHSE #0664 PLANO TX")
    city = [s for s in p.slots if s.name == "city"][0]
    region = [s for s in p.slots if s.name == "region"][0]
    assert city.certain is False and region.certain is True
    assert p.to_dict()["slots"][-1]["provenance"] in ("parsed", "inferred")


def test_a_descriptor_layer_zero_cannot_explain_says_so():
    """A bank-composed sentence that no published card rule touches parses to
    zero coverage and no slots, rather than to a plausible-looking brand."""
    p = parse_descriptor("ZELLE TO JOHN SMITH")
    assert p.coverage == 0.0
    assert p.slots == []


def test_leftovers_must_be_contiguous():
    """Layer 0 cannot claim the merchant name, so `clean` demands one
    contiguous run of residue rather than none."""
    assert parse_descriptor("COSTCO WHSE #0664 PLANO TX").clean
    assert parse_descriptor("TST* GOLDEN FORK BISTRO AUSTIN TX").clean


# ------------------------------------------- a grammar borrowed from another bank


def _card_profile(institution="Alpha", version="v1"):
    from merchantcore.profile import Profile, Template
    return Profile(institution, "depository", version,
                   [Template("Card Purchase {date} {brand} {city} {region} "
                             "Card {account_ref}")], measured=0.95)


def test_another_banks_grammar_may_explain_this_banks_line():
    """With no grammar of its own, a line matched by another institution's
    grammar resolves through it, and the lender's profile id is recorded."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    res = resolve_descriptor(line, profile=None, borrowed=[_card_profile()])
    assert res.layer == "grammar"
    assert res.borrowed_from == "alpha-depository-v1"
    assert res.brand == "STOREB"


def test_a_borrowed_grammar_is_still_a_grammar():
    """A borrowed match reports layer `grammar`, not a weaker layer name; every
    downstream privacy check keys on that word."""
    from merchantcore.resolve import resolve_descriptor
    res = resolve_descriptor("Card Purchase 04/02 STOREB Frisco TX Card 9876",
                             borrowed=[_card_profile()])
    assert res.layer == "grammar" and res.template


def test_the_banks_own_grammar_always_wins():
    """When the bank's own grammar matches, nothing is borrowed."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    res = resolve_descriptor(line, profile=_card_profile("Beta"),
                             borrowed=[_card_profile("Alpha")])
    assert res.borrowed_from == "", "the own grammar matched, so nothing was borrowed"


def test_borrowing_never_reaches_a_refused_line():
    """A wire is refused every layer, borrowing included."""
    from merchantcore.resolve import resolve_descriptor
    wire = ("Via: WELLS FARGO NA A/C: 0000000123 Imad: 20260304B1QGC01R "
            "Trn: 1234567890 Ref: INVOICE 44")
    res = resolve_descriptor(wire, borrowed=[_card_profile()])
    assert res.refused and res.layer == "refused" and res.borrowed_from == ""


def test_which_lender_wins_does_not_depend_on_dict_order():
    """When two borrowed grammars both match, the one chosen is the same
    whichever order they are supplied in."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    a, b = _card_profile("Alpha"), _card_profile("Zeta")
    assert (resolve_descriptor(line, borrowed=[a, b]).borrowed_from
            == resolve_descriptor(line, borrowed=[b, a]).borrowed_from
            == "alpha-depository-v1")


# ------------------------------ position, and silence that is not a clearance


def test_a_processor_prefix_is_recognised_by_POSITION_not_by_name():
    """A processor prefix is claimed by the asterisk's index, and no list of
    processor names exists to claim it by spelling."""
    from merchantcore.descriptor import parse_descriptor
    import merchantcore.descriptor as d
    assert not hasattr(d, "_PROCESSORS"), "the name list is gone, not renamed"
    for line in ("TST* TEXAS CARD HOUSE Dallas TX", "SQ *BLUE BOTTLE OAKLAND CA",
                 "IC* INSTACART SAN FRANCISCO CA"):
        rules = {s.rule for s in parse_descriptor(line).slots}
        assert any(r.startswith("asterisk_at_") for r in rules), line


def test_a_line_the_english_list_cannot_read_is_not_cleared_by_its_silence():
    """`is_shareable` fails closed on a line its English, ASCII markers cannot
    read: a descriptor carrying non-ASCII letters is withheld rather than
    cleared by the list's silence."""
    from merchantcore.normalize import is_shareable
    assert is_shareable("COSTCO WHSE PLANO TX")
    assert not is_shareable("VENMO TO JOHN SMITH")
    # The list is mute on both of these; it may not clear them.
    assert not is_shareable("スイカ 東京 JP")
    assert not is_shareable("CAFÉ MÜLLER MÜNCHEN DE")


# --- how a merchant bills, as a fact about the merchant ---------------------

def test_a_billing_model_and_its_period_land_in_the_attributes_bag():
    """The world's knowledge of how a merchant charges, filed beside every
    other impersonal fact about them — no new field, no new record shape."""
    def extract(prompt):
        assert "billing" in prompt                       # the prompt asks for it
        return ('{"lumen tv": {"canonical_name":"Lumen TV","category":"other",'
                '"billing":"standing","billing_period":"monthly"}}')
    r = Enricher(extract).enrich({"lumen tv": "LUMEN TV"})["lumen tv"]
    assert r.attributes["billing"] == "standing"
    assert r.attributes["billing_period"] == "monthly"


def test_a_billing_model_outside_the_closed_set_is_dropped():
    """The model's answer is untrusted input: the vocabulary is ours, and a
    word outside it buys silence rather than a new value nothing validates."""
    def extract(prompt):
        return ('{"acme": {"canonical_name":"Acme","category":"other",'
                '"billing":"quarterly-ish","billing_period":"monthly"}}')
    r = Enricher(extract).enrich({"acme": "ACME"})["acme"]
    assert "billing" not in r.attributes
    # And the period goes with it: an interval with no model behind it says a
    # merchant bills on a cycle without saying they bill on one at all.
    assert "billing_period" not in r.attributes


def test_a_period_offered_for_a_per_purchase_merchant_is_dropped():
    def extract(prompt):
        return ('{"acme": {"canonical_name":"Acme","category":"other",'
                '"billing":"per_purchase","billing_period":"monthly"}}')
    r = Enricher(extract).enrich({"acme": "ACME"})["acme"]
    assert r.attributes["billing"] == "per_purchase"
    assert "billing_period" not in r.attributes


def test_an_unknown_period_is_dropped_and_the_model_survives():
    def extract(prompt):
        return ('{"acme": {"canonical_name":"Acme","category":"other",'
                '"billing":"standing","billing_period":"fortnightly"}}')
    r = Enricher(extract).enrich({"acme": "ACME"})["acme"]
    assert r.attributes["billing"] == "standing"
    assert "billing_period" not in r.attributes


def test_saying_nothing_about_billing_is_a_normal_answer():
    def extract(prompt):
        return '{"acme": {"canonical_name":"Acme","category":"other"}}'
    r = Enricher(extract).enrich({"acme": "ACME"})["acme"]
    assert "billing" not in r.attributes and "billing_period" not in r.attributes


def test_the_billing_question_is_separate_from_what_a_merchant_implies():
    """A billing model licenses a question; an implication creates an account.
    A reply that names one must not be read as naming the other."""
    def extract(prompt):
        return ('{"acme": {"canonical_name":"Acme","category":"other",'
                '"billing":"standing","implies":[]}}')
    r = Enricher(extract).enrich({"acme": "ACME"})["acme"]
    assert r.attributes["billing"] == "standing"
    assert "implies" not in r.attributes


# --- a released prompt version reaching the records it was written for ------

def test_a_version_stale_record_is_restaged_and_asked_about_again(tmp_path):
    from merchantcore.enrich import ENRICHMENT_VERSION, enrichment_is_stale
    cat = Catalog(tmp_path / "catalog.json")
    cat.add(MerchantRecord(key="acme", category="other",
                           version="enrich-v1+tax-v1+merch-v2"))
    cat.add(MerchantRecord(key="borea", category="other",
                           version=f"{ENRICHMENT_VERSION}+tax-v1+merch-v2"))
    # Measured first, and measuring changes nothing.
    assert cat.restage(enrichment_is_stale, dry_run=True) == ["acme"]
    assert not cat.restaged() and not cat.pending()

    assert cat.restage(enrichment_is_stale) == ["acme"]
    # What is already known keeps answering while it waits to be re-asked.
    assert cat.get("acme").category == "other"
    assert cat.submit([("acme", "ACME"), ("borea", "BOREA")]) == 1
    assert set(cat.pending()) == {"acme"}


def test_a_restaged_record_is_asked_about_once_not_every_run(tmp_path):
    """A re-ask that came back is over — including where the answer did not
    outrank what a person had already confirmed, which would otherwise buy the
    same model call every time."""
    from merchantcore.enrich import enrichment_is_stale
    cat = Catalog(tmp_path / "catalog.json")
    cat.add(MerchantRecord(key="acme", category="other", grade="verified",
                           version="enrich-v1+tax-v1+merch-v2"))
    cat.restage(enrichment_is_stale)
    cat.submit([("acme", "ACME")])
    cat.add(MerchantRecord(key="acme", category="shopping",
                           grade="corroborated", version="enrich-v1+tax-v1"))
    assert cat.get("acme").category == "other"          # the human ruling stands
    assert not cat.restaged()
    assert cat.submit([("acme", "ACME")]) == 0          # and it is not re-queued


def test_a_record_with_no_version_is_not_stale():
    """Nothing says which prompt wrote it, so nothing says it is superseded."""
    from merchantcore.enrich import enrichment_is_stale
    assert not enrichment_is_stale(MerchantRecord(key="acme", version=""))


def test_a_new_taxonomy_does_not_restage_a_record():
    """Staleness compares the prompt component of a record's version alone, so
    a record stamped with an older taxonomy is not restaged."""
    from merchantcore.enrich import ENRICHMENT_VERSION, enrichment_is_stale
    assert not enrichment_is_stale(MerchantRecord(
        key="acme", version=f"{ENRICHMENT_VERSION}+an-older-taxonomy+merch-v2"))


def test_restaging_survives_a_reload(tmp_path):
    from merchantcore.enrich import enrichment_is_stale
    cat = Catalog(tmp_path / "catalog.json")
    cat.add(MerchantRecord(key="acme", category="other", version="enrich-v1"))
    cat.restage(enrichment_is_stale)
    assert Catalog(tmp_path / "catalog.json").restaged() == {"acme"}
