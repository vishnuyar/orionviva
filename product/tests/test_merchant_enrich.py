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
    vault = tmp_path / "some-vault"
    vault.mkdir()

    # With no legacy file, the shared location wins — and crucially it is NOT
    # inside the vault, so a rebuild into a new directory keeps the knowledge.
    shared = catalog_path(vault)
    assert vault not in shared.parents, "a rebuild must not start from zero"
    assert shared == tmp_path / ".viva" / "merchant-catalog.json"

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
