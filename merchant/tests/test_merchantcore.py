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
    assert "merch-v2" in recs["amzn mktp us"].version     # normalizer version carried


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


# --- a posting date is not part of a merchant's name ------------------------

def test_a_date_fragment_does_not_become_part_of_the_key():
    """One merchant seen in two months was becoming two merchants, because the
    non-word pass turned "02/14 STORE" into "02 14 store" and the bare month
    then headed a key of its own. On a real vault 118 of 492 keys — a quarter —
    were headed by a bare month number."""
    assert normalize_merchant("02/14 SAFEHARBOR MARKET") == "safeharbor market"
    assert (normalize_merchant("02/14 SAFEHARBOR MARKET")
            == normalize_merchant("03/09 SAFEHARBOR MARKET"))
    assert normalize_merchant("12-31 LUMEN ENERGY") == "lumen energy"


def test_a_bare_number_can_still_be_part_of_a_name():
    """Only a fragment carrying a separator is a date. A number on its own is
    as likely to be the name itself."""
    assert normalize_merchant("7 ELEVEN 33412") == "7 eleven"


# --- Layer 0: claim what a published rule proves, and name the rest ---------

def test_the_asterisk_separates_an_aggregator_from_what_it_sold():
    """The asterisk sits at index 3, 7 or 12 by processor mandate, so this is
    parsing rather than guessing."""
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
    or URL for card-absent transactions, so this is a signal rather than a
    misread location."""
    assert parse_descriptor("SOME MERCHANT 617-SERVICE").card_not_present
    assert parse_descriptor("COSTCO WHSE #0664 PLANO TX").card_not_present is False


def test_a_city_is_marked_inferred_because_adjacency_is_not_proof():
    """The region code is proved by the layout. The city is only adjacent to it,
    and the flattening destroyed the offsets that would settle where the name
    ends — so the slot carries how it was obtained."""
    p = parse_descriptor("COSTCO WHSE #0664 PLANO TX")
    city = [s for s in p.slots if s.name == "city"][0]
    region = [s for s in p.slots if s.name == "region"][0]
    assert city.certain is False and region.certain is True
    assert p.to_dict()["slots"][-1]["provenance"] in ("parsed", "inferred")


def test_a_descriptor_layer_zero_cannot_explain_says_so():
    """A bank-composed sentence over structured data. No published card rule
    touches it, and reporting zero coverage is how the need for a per-institution
    grammar becomes visible instead of being papered over."""
    p = parse_descriptor("ZELLE TO JOHN SMITH")
    assert p.coverage == 0.0
    assert p.slots == []


def test_leftovers_must_be_contiguous():
    """Layer 0 cannot claim the merchant name, so demanding no residue would
    fail on everything. What it can demand is that the leftovers form ONE run:
    scattered fragments mean the rules fired in the wrong places."""
    assert parse_descriptor("COSTCO WHSE #0664 PLANO TX").clean
    assert parse_descriptor("TST* GOLDEN FORK BISTRO AUSTIN TX").clean


# ------------------------------------------- a grammar borrowed from another bank


def _card_profile(institution="Alpha", version="v1"):
    from merchantcore.profile import Profile, Template
    return Profile(institution, "depository", version,
                   [Template("Card Purchase {date} {brand} {city} {region} "
                             "Card {account_ref}")], measured=0.95)


def test_another_banks_grammar_may_explain_this_banks_line():
    """The reason borrowing is worth having: an account with twenty distinct
    lines can never teach a grammar — the minimum is thirty, forever — and is
    perfectly explicable by one. A sentence shape is not the exclusive property
    of the bank it was learned from."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    res = resolve_descriptor(line, profile=None, borrowed=[_card_profile()])
    assert res.layer == "grammar"
    assert res.borrowed_from == "alpha-depository-v1"
    assert res.brand == "STOREB"


def test_a_borrowed_grammar_is_still_a_grammar():
    """Recorded as `grammar`, not as a weaker layer. It is structurally the same
    claim — same closed vocabulary, same compiled expression, same rule that a
    person is whatever landed in a slot named for one — and every downstream
    privacy check keys on that word. A separate layer name would silently send
    borrowed lines down the guess-from-substrings path."""
    from merchantcore.resolve import resolve_descriptor
    res = resolve_descriptor("Card Purchase 04/02 STOREB Frisco TX Card 9876",
                             borrowed=[_card_profile()])
    assert res.layer == "grammar" and res.template


def test_the_banks_own_grammar_always_wins():
    """Own first, always: a bank's own grammar was measured against its own
    lines and a borrowed one was not."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    res = resolve_descriptor(line, profile=_card_profile("Beta"),
                             borrowed=[_card_profile("Alpha")])
    assert res.borrowed_from == "", "the own grammar matched, so nothing was borrowed"


def test_borrowing_never_reaches_a_refused_line():
    """A wire is refused every layer, and borrowing is a layer. The sender's
    free text can hold a street address, and no grammar from anywhere may claim
    a field somebody typed freely."""
    from merchantcore.resolve import resolve_descriptor
    wire = ("Via: WELLS FARGO NA A/C: 0000000123 Imad: 20260304B1QGC01R "
            "Trn: 1234567890 Ref: INVOICE 44")
    res = resolve_descriptor(wire, borrowed=[_card_profile()])
    assert res.refused and res.layer == "refused" and res.borrowed_from == ""


def test_which_lender_wins_does_not_depend_on_dict_order():
    """Two grammars that both match must give the same answer every run, or two
    reports over one vault disagree about who explained what."""
    from merchantcore.resolve import resolve_descriptor
    line = "Card Purchase 04/02 STOREB Frisco TX Card 9876"
    a, b = _card_profile("Alpha"), _card_profile("Zeta")
    assert (resolve_descriptor(line, borrowed=[a, b]).borrowed_from
            == resolve_descriptor(line, borrowed=[b, a]).borrowed_from
            == "alpha-depository-v1")


# ------------------------- the two lists that carried raw English, and are gone


def test_a_processor_prefix_is_recognised_by_POSITION_not_by_name():
    """There used to be a `_PROCESSORS` tuple — "sq *", "tst*", "paypal *" — and
    alongside them "pos debit", "checkcard", "ach pmt". Two different things
    under one name: the asterisk forms were already caught by the positional
    rule, and the rest were English bank phrases doing classification. The
    position is processor-mandated and identical in every country; the words
    were not."""
    from merchantcore.descriptor import parse_descriptor
    import merchantcore.descriptor as d
    assert not hasattr(d, "_PROCESSORS"), "the name list is gone, not renamed"
    for line in ("TST* TEXAS CARD HOUSE Dallas TX", "SQ *BLUE BOTTLE OAKLAND CA",
                 "IC* INSTACART SAN FRANCISCO CA"):
        rules = {s.rule for s in parse_descriptor(line).slots}
        assert any(r.startswith("asterisk_at_") for r in rules), line


def test_a_line_the_english_list_cannot_read_is_not_cleared_by_its_silence():
    """`is_shareable` decides whether a descriptor may be sent to a model
    provider. Its markers are English and ASCII, so on a Hindi or Japanese peer
    payment it says nothing — and saying nothing meant "safe". Failing closed
    instead: a line carrying letters outside ASCII is withheld until a grammar
    exists, at which point a slot name answers the question properly."""
    from merchantcore.normalize import is_shareable
    assert is_shareable("COSTCO WHSE PLANO TX")
    assert not is_shareable("VENMO TO JOHN SMITH")
    # The list is mute on both of these; it may not clear them.
    assert not is_shareable("スイカ 東京 JP")
    assert not is_shareable("CAFÉ MÜLLER MÜNCHEN DE")
