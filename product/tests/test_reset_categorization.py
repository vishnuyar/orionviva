"""The one-time cleanup: rewind a vault to before categorization, keep all else.

Proves the migration removes exactly the three overlay event types, leaves every
other event (and the raw store, and the source vault) untouched, and produces a
verifying chain the ledger reads as a clean categorization slate."""

import collections
from decimal import Decimal

import pytest

from merchantcore import Catalog
from viva.crypto import HEAD_BOUND_HEADER_VERSION
from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         assign_category, capture_and_ingest, enrich_merchants)
from viva.ledger import EventStore, Ledger
from viva.reset_categorization import (CATEGORIZATION_EVENTS, rebuild_log,
                                       reset_vault)
from viva.vault import Vault


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


def _seed_vault(directory):
    """A vault with a real card statement AND categorization overlays on top."""
    vault = Vault.open(directory, "pw")
    txns = [("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
            ("2026-01-06", "NETFLIX.COM", "15.00"),
            ("2026-01-08", "COSTCO WHSE #123", "80.00")]
    total = sum(Decimal(a) for _, _, a in txns)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Card 7799", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=total, closing_date="2026-01-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000007799", institution="Chase")
    capture_and_ingest(vault.raw, vault.ledger, b"card",
                       lambda data, did: _stamp(card, did),
                       captured_at="2026-02-01")
    # Overlay categorization three ways: merchant enrichment (MerchantEnriched)
    # and one per-transaction human ruling (CategoryAssigned).
    enrich_merchants(vault.ledger, Catalog(),
                     lambda p: ('{"amzn mktp us":{"category":"shopping"},'
                                '"netflix com":{"category":"entertainment",'
                                '"subcategory":"streaming"},'
                                '"costco whse":{"category":"groceries"}}'),
                     kind_for=lambda m: m.kind)
    costco = next(m for m in vault.ledger.projection().movements()
                  if "COSTCO" in m.description)
    assign_category(vault.ledger, costco.key, "groceries", by="human")
    return vault


def _counts(vault):
    return collections.Counter(e.event_type for e in vault.events())


def test_reset_drops_model_categorization_but_keeps_my_rulings(tmp_path):
    """The guard: a model's categorization is derived data and goes; a ruling YOU
    made is the moat and stays."""
    src = _seed_vault(tmp_path / "src")
    before = _counts(src)
    assert before["MerchantEnriched"] > 0        # model-made
    assert before["CategoryAssigned"] > 0        # human-made (the Costco ruling)

    reset_vault(tmp_path / "src", tmp_path / "dst", "pw")

    clean = Vault.open(tmp_path / "dst", "pw")
    after = _counts(clean)
    # The model's enrichment is gone...
    assert after["MerchantEnriched"] == 0
    assert after["MerchantCategorized"] == 0
    # ...but every human ruling survived.
    human = [e for e in clean.events()
             if e.event_type == "CategoryAssigned" and e.body.get("by") == "human"]
    assert len(human) == before["CategoryAssigned"]
    # And every OTHER event type survives with an identical count.
    for et, n in before.items():
        if et in CATEGORIZATION_EVENTS:
            continue
        assert after[et] == n, f"{et} changed: {n} -> {after[et]}"


def test_reset_can_discard_my_rulings_only_when_asked(tmp_path):
    """Discarding a person's own rulings is possible, but never the default."""
    _seed_vault(tmp_path / "src")
    reset_vault(tmp_path / "src", tmp_path / "dst", "pw", keep_human=False)
    after = _counts(Vault.open(tmp_path / "dst", "pw"))
    for et in CATEGORIZATION_EVENTS:
        assert after[et] == 0                     # now truly a blank slate


def test_reset_leaves_the_source_untouched(tmp_path):
    src = _seed_vault(tmp_path / "src")
    before = _counts(src)
    reset_vault(tmp_path / "src", tmp_path / "dst", "pw")
    # Re-open the source independently: it must be exactly as it was.
    reopened = _counts(Vault.open(tmp_path / "src", "pw"))
    assert reopened == before
    assert reopened["MerchantEnriched"] > 0


def test_reset_preserves_the_ledger_and_raw_store(tmp_path):
    src = _seed_vault(tmp_path / "src")
    src_proj = src.ledger.projection()
    src_total = src_proj.balance(src_proj.account_infos()[0].account).amount
    src_docs = set(src.raw.doc_ids())

    reset_vault(tmp_path / "src", tmp_path / "dst", "pw")
    clean = Vault.open(tmp_path / "dst", "pw")
    proj = clean.ledger.projection()

    # The card balance (the money) is identical — postings were never touched.
    assert proj.balance(proj.account_infos()[0].account).amount == src_total
    # Raw captures carried across verbatim.
    assert set(clean.raw.doc_ids()) == src_docs
    # The model's categorization is a clean slate, but the human ruling on Costco
    # survives — so groceries remains and only the model-categorized two return
    # to the queue (rulings are the asset).
    assert proj.spending_by_category() == {"Uncategorized": Decimal("65.00"),
                                           "groceries": Decimal("80.00")}
    assert len(proj.uncategorized_merchants()) == 2


def test_reset_chain_verifies_and_reindexes_sequences(tmp_path):
    _seed_vault(tmp_path / "src")
    reset_vault(tmp_path / "src", tmp_path / "dst", "pw")
    clean = Vault.open(tmp_path / "dst", "pw")
    ok, count = clean.store.verify_chain()
    assert ok
    # Sequences are a gap-free 0..count-1 after the drops re-chained the log.
    seqs = [e for e in range(count)]
    raw_seqs = []
    import json
    with (tmp_path / "dst" / "events.jsonl").open() as f:
        header = json.loads(next(f))
        for line in f:
            raw_seqs.append(json.loads(line)["seq"])
    assert header["v"] == HEAD_BOUND_HEADER_VERSION
    assert raw_seqs == seqs


def test_rebuild_refuses_to_overwrite_the_source(tmp_path):
    _seed_vault(tmp_path / "src")
    with pytest.raises(ValueError):
        rebuild_log(tmp_path / "src" / "events.jsonl",
                    tmp_path / "src" / "events.jsonl", "pw")


def test_reset_refuses_a_nonempty_destination(tmp_path):
    _seed_vault(tmp_path / "src")
    (tmp_path / "dst").mkdir()
    (tmp_path / "dst" / "something").write_text("x")
    with pytest.raises(ValueError):
        reset_vault(tmp_path / "src", tmp_path / "dst", "pw")
