"""The product ↔ merchantcore loop: an impersonal boundary, then sync-as-events
so categorization is retrospective and the ledger self-contained."""

from decimal import Decimal

from merchantcore import Catalog
from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         account_id_for, assign_category, capture_and_ingest,
                         enrich_merchants)
from viva.ledger import EventStore, Ledger, LedgerProjection


def _card(txns, tmp_path):
    raw = RawStore.open(tmp_path / "raw", "pw")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"))
    total = sum(Decimal(a) for _, _, a in txns)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Card 7799", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=total, closing_date="2026-01-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000007799", institution="Chase")
    capture_and_ingest(raw, ledger, b"card", lambda data, did: _stamp(card, did),
                       captured_at="2026-02-01")
    return ledger


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def test_only_impersonal_hints_cross_the_boundary(tmp_path):
    ledger = _card([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
                    ("2026-01-06", "VENMO PAYMENT TO JOHN", "20.00")], tmp_path)
    cat = Catalog()
    seen = {}

    def extract(prompt):
        # The prompt (all that reaches the model) must carry no amount/account.
        seen["prompt"] = prompt
        return '{"amzn mktp us": {"canonical_name":"Amazon","category":"shopping"}}'

    enrich_merchants(ledger, cat, extract)
    # The peer-payment merchant was filtered out — never submitted or enriched.
    assert not any("venmo" in k for k in cat.records())
    assert not any("venmo" in k for k in cat.pending())
    # No amount, account number, or statement date leaked into the model prompt.
    for forbidden in ("50.00", "20.00", "000000007799", "2026-01-05"):
        assert forbidden not in seen["prompt"]


def test_enrichment_syncs_as_events_and_categorizes_retrospectively(tmp_path):
    ledger = _card([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
                    ("2026-01-09", "AMZN MKTP US*RH4DD6YM1", "30.00")], tmp_path)
    cat = Catalog()

    def extract(prompt):
        return '{"amzn mktp us": {"canonical_name":"Amazon","category":"shopping"}}'

    res = enrich_merchants(ledger, cat, extract)
    assert res["synced"] == 1
    proj = ledger.projection()
    # BOTH Amazon transactions categorized from the one synced merchant record.
    assert proj.spending_by_category() == {"shopping": Decimal("80.00")}
    # The ledger is self-contained: a replay WITHOUT the catalog keeps the category
    # (the enrichment is a MerchantEnriched event in the log).
    replayed = LedgerProjection(ledger.events())
    assert replayed.spending_by_category() == {"shopping": Decimal("80.00")}


def test_human_override_beats_the_synced_enrichment(tmp_path):
    ledger = _card([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00")], tmp_path)
    cat = Catalog()
    enrich_merchants(ledger, cat, lambda p: '{"amzn mktp us":{"category":"shopping"}}')
    amazon = next(m for m in ledger.projection().movements() if "RA30Z" in m.description)
    assign_category(ledger, amazon.key, "groceries")      # per-transaction override
    proj = ledger.projection()
    assert proj.spending_by_category() == {"groceries": Decimal("50.00")}
    assert proj.derived_category(amazon)["grade"] == "verified"


def test_subcategory_enables_a_finer_slice(tmp_path):
    ledger = _card([("2026-01-05", "NETFLIX.COM", "15.00"),
                    ("2026-01-06", "SPOTIFY USA", "10.00"),
                    ("2026-01-08", "AMC THEATRES 123", "30.00")], tmp_path)
    cat = Catalog()

    def extract(prompt):
        return ('{"netflix com": {"category":"entertainment","subcategory":"streaming"},'
                '"spotify usa": {"category":"entertainment","subcategory":"streaming"},'
                '"amc theatres": {"category":"entertainment","subcategory":"movies"}}')

    enrich_merchants(ledger, cat, extract)
    proj = ledger.projection()
    # Primary category groups all three under entertainment...
    assert proj.spending_by_category() == {"entertainment": Decimal("55.00")}
    # ...while the subcategory slices streaming from movies.
    assert proj.spending_by_subcategory() == {"streaming": Decimal("25.00"),
                                              "movies": Decimal("30.00")}


def test_a_subcategory_summary_keeps_its_parent_and_names_the_remainder(tmp_path):
    """A finer summary that a person can add up.

    `spending_by_subcategory` falls back to the category label when a movement
    has no subcategory, so its keys are two vocabularies in one namespace and
    nothing says which category a slice came from. The nested read keeps them
    apart: every category's inner values sum to exactly what
    `spending_by_category` gives that category, and the money no subcategory
    names sits under `""` rather than being dropped or silently folded into a
    sibling."""
    ledger = _card([("2026-01-05", "NETFLIX.COM", "15.00"),
                    ("2026-01-06", "SPOTIFY USA", "10.00"),
                    ("2026-01-08", "AMC THEATRES 123", "30.00"),
                    ("2026-01-09", "CORNER NEWSAGENT", "5.00")], tmp_path)
    cat = Catalog()

    def extract(prompt):
        # The newsagent is entertainment with no finer name — the ordinary case
        # early on, and the one a flat view cannot show.
        return ('{"netflix com": {"category":"entertainment","subcategory":"streaming"},'
                '"spotify usa": {"category":"entertainment","subcategory":"streaming"},'
                '"amc theatres": {"category":"entertainment","subcategory":"movies"},'
                '"corner newsagent": {"category":"entertainment"}}')

    enrich_merchants(ledger, cat, extract)
    proj = ledger.projection()
    tree = proj.spending_by_category_then_subcategory()

    assert tree == {"entertainment": {"streaming": Decimal("25.00"),
                                      "movies": Decimal("30.00"),
                                      "": Decimal("5.00")}}
    # It closes: the finer view adds up to the coarser one, category by category.
    coarse = proj.spending_by_category()
    for label, within in tree.items():
        assert sum(within.values()) == coarse[label], label


def test_the_category_report_shows_each_subcategory_under_its_parent(tmp_path):
    """The report is where a person reads this, so the nesting and the named
    remainder are asserted on the rendered text, not only on the read."""
    from viva.debug.categories import report

    ledger = _card([("2026-01-05", "NETFLIX.COM", "15.00"),
                    ("2026-01-08", "AMC THEATRES 123", "30.00"),
                    ("2026-01-09", "CORNER NEWSAGENT", "5.00")], tmp_path)
    cat = Catalog()
    enrich_merchants(ledger, cat, lambda prompt: (
        '{"netflix com": {"category":"entertainment","subcategory":"streaming"},'
        '"amc theatres": {"category":"entertainment","subcategory":"movies"},'
        '"corner newsagent": {"category":"entertainment"}}'))

    text = report(ledger.projection())
    assert "what each subcategory is worth, under its category" in text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    heading = next(i for i, ln in enumerate(lines)
                   if "under its category" in ln)
    section = lines[heading + 1:heading + 5]
    assert any("entertainment" in ln and "50.00" in ln for ln in section)
    assert any("streaming" in ln and "15.00" in ln for ln in section)
    assert any("movies" in ln and "30.00" in ln for ln in section)
    assert any("unassigned" in ln and "5.00" in ln for ln in section), (
        "money the category holds that no subcategory names went unreported")


def test_a_category_with_no_name_is_unnamed_in_both_views(tmp_path):
    """The coarse and finer views must agree about how much is unnamed.

    A nature ruling on a merchant with no catalog record writes a category that
    is present but empty. Defaulting only on a *missing* key left that money in
    a `''` bucket the coarse view reported and the finer one did not, so a
    report rendering both showed one page disagreeing with itself. An empty
    name is not a category in either."""
    from viva.ingest import rule_merchant_nature

    ledger = _card([("2026-01-05", "NETFLIX.COM", "15.00"),
                    ("2026-01-09", "CORNER NEWSAGENT", "5.00")], tmp_path)
    enrich_merchants(ledger, Catalog(), lambda prompt: (
        '{"netflix com": {"category":"entertainment","subcategory":"streaming"}}'))
    rule_merchant_nature(ledger, "CORNER NEWSAGENT", "spending")

    proj = ledger.projection()
    coarse = proj.spending_by_category()
    tree = proj.spending_by_category_then_subcategory()
    assert "" not in coarse, "money is filed under a name a person cannot read"
    assert set(tree) == set(coarse)
    for label, within in tree.items():
        assert sum(within.values()) == coarse[label], label


def test_the_uncategorized_caveat_states_what_is_actually_unnamed(tmp_path):
    """The caveat a person reads verbatim must be the figure it claims to be.

    The read grouped by category defaulted only on a MISSING category key, so
    money whose ruling carried an empty one sat in a group the caveat's lookup
    never saw. A caveat is joined into the answer text as written, so a person
    read a confident amount, with no id and no grade behind it, understating
    what the agent does not know."""
    from viva.ingest import rule_merchant_nature
    from viva.tools import default_registry

    ledger = _card([("2026-01-05", "NETFLIX.COM", "15.00"),
                    ("2026-01-09", "CORNER NEWSAGENT", "5.00"),
                    ("2026-01-10", "UNKNOWN SHOP", "3.00")], tmp_path)
    enrich_merchants(ledger, Catalog(), lambda prompt: (
        '{"netflix com": {"category":"entertainment","subcategory":"streaming"}}'))
    rule_merchant_nature(ledger, "CORNER NEWSAGENT", "spending")
    proj = ledger.projection()

    result = default_registry(proj).call(
        "query_ledger", {"entity": "aggregate", "metric": "spending",
                         "group_by": "category"})
    assert result.ok, result.text
    assert "" not in result.data["by_group"], (
        "a group holding money under no name a person could read or filter on")

    unnamed = proj.spending_by_category()["Uncategorized"]
    (said,) = [str(c) for c in result.caveats if "uncategorized" in str(c).lower()]
    assert str(unnamed) in said.replace(",", ""), (
        f"the caveat states a different figure from what is unnamed: {said!r} "
        f"against {unnamed}")


def test_sync_is_idempotent(tmp_path):
    ledger = _card([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00")], tmp_path)
    cat = Catalog()
    ext = lambda p: '{"amzn mktp us":{"category":"shopping"}}'
    enrich_merchants(ledger, cat, ext)
    n_events = len(list(ledger.events()))
    enrich_merchants(ledger, cat, ext)                    # again, nothing new
    assert len(list(ledger.events())) == n_events         # no duplicate events


def test_the_catalog_is_shared_across_vaults_not_kept_inside_one(tmp_path, monkeypatch):
    """The catalog lives outside the vault directory, because keeping it inside
    contradicts the reason it exists.

    It holds IMPERSONAL merchant knowledge — a normalized key, a category, a
    counterparty kind — and nothing about anyone's money. That is exactly why
    it can be kept once, reused by every vault, and eventually shared with other
    people: "Costco is a warehouse club" is true for everybody, and nobody
    should pay a model to learn it twice.

    Keeping it beside the vault makes every rebuild start from zero and pay
    again for knowledge already bought — the network effect the catalog exists
    for, running in reverse."""
    from viva.enrich import catalog_path

    monkeypatch.delenv("VIVA_CATALOG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("MERCHANTCORE_HOME", raising=False)
    vault = tmp_path / "some-vault"
    vault.mkdir()

    # With no legacy file, the shared location wins — and crucially it is NOT
    # inside the vault, so a rebuild into a new directory keeps the knowledge.
    shared = catalog_path(vault)
    assert vault not in shared.parents, "a rebuild must not start from zero"
    assert shared == tmp_path / ".merchantcore" / "catalog.json"

    # An explicit path always wins, so a catalog can be pointed at a shared or
    # checked-out location.
    monkeypatch.setenv("VIVA_CATALOG", str(tmp_path / "team.json"))
    assert catalog_path(vault) == tmp_path / "team.json"

    # And nobody loses what they already paid for: an existing in-vault catalog
    # is still honoured while no shared one exists.
    monkeypatch.delenv("VIVA_CATALOG", raising=False)
    (tmp_path / ".viva" / "merchant-catalog.json").unlink(missing_ok=True)
    legacy = vault / "merchant-catalog.json"
    legacy.write_text("{}")
    assert catalog_path(vault) == legacy


# ------------------------------- only bank and card accounts reach a model


def test_only_accounts_whose_lines_name_a_party_are_enriched(tmp_path):
    """An allowlist, not a denylist of one.

    Enrichment used to exclude investment BY NAME, which meant any kind nobody
    had thought of — crypto, property, a pension — had its lines shipped to a
    model as merchants by default. A list of what is permitted cannot be wrong
    about a thing that did not exist when it was written."""
    ledger = _card([("2026-01-05", "COSTCO WHSE PLANO TX", "84.10"),
                    ("2026-01-06", "SUNDIAL BREW PLANO TX", "6.25")], tmp_path)
    asked: list = []

    def extract(prompt):
        asked.append(prompt)
        return '{"costco whse": {"category": "shopping"}}'

    # every account an investment: nothing may be offered at all
    enrich_merchants(ledger, Catalog(), extract, kind_for=lambda m: "investment")
    assert asked == [], "an investment line names a security, not a merchant"

    # a kind nobody has modelled: same answer, without anyone having listed it
    enrich_merchants(ledger, Catalog(), extract, kind_for=lambda m: "crypto")
    assert asked == [], "an unknown kind is silent until somebody decides otherwise"

    # a bank account: this is what enrichment is for
    enrich_merchants(ledger, Catalog(), extract, kind_for=lambda m: "depository")
    assert asked, "a depository line has a merchant in it"


def test_a_card_account_is_enriched_like_a_bank_account(tmp_path):
    ledger = _card([("2026-01-05", "COSTCO WHSE PLANO TX", "84.10")], tmp_path)
    seen: list = []
    enrich_merchants(ledger, Catalog(),
                     lambda p: (seen.append(p) or '{"costco whse": {"category": "shopping"}}'),
                     kind_for=lambda m: "liability")
    assert seen
