"""Merchant catalog: categorize the merchant once, fill every transaction; the
per-transaction override still wins; unknown merchants wait."""

from decimal import Decimal

from viva.ingest import (RawStore, ReadResult, StatementFacts, TxnFact,
                         assign_category, assign_merchant_category,
                         capture_and_ingest, categorize_merchants_batch,
                         export_catalog, is_shareable, normalize_merchant)
from viva.ledger import EventStore, Ledger, LedgerProjection
from viva.ingest.merchants import NORMALIZER_VERSION


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _card_with(txns, tmp_path):
    raw, ledger = _stores(tmp_path)
    total = sum(Decimal(a) for _, _, a in txns)
    card = StatementFacts(
        doc_id="", doc_type="credit_card_statement", doc_type_confidence=0.98,
        account_ref="Card 7799", currency="USD",
        opening_amount=Decimal("0"), opening_date="2026-01-01",
        closing_amount=total, closing_date="2026-01-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number="000000007799", institution="Chase")
    capture_and_ingest(raw, ledger, b"card",
                       lambda data, did: (_stamp(card, did)),
                       captured_at="2026-02-01")
    return ledger


def _stamp(f, doc_id):
    f.doc_id = doc_id
    return ReadResult(f.doc_type, 0.98, f)


# --- normalizer -------------------------------------------------------------

def test_normalizer_is_deterministic_and_versioned():
    assert normalize_merchant("AMZN MKTP US*RA30Z3BP0") == normalize_merchant("AMZN MKTP US*RH4DD6YM1")
    assert normalize_merchant("KROGER #0548") == "kroger"
    assert NORMALIZER_VERSION                      # a version exists (portable keys)


def test_peer_payment_is_not_shareable():
    assert not is_shareable("VENMO PAYMENT TO JOHN SMITH")
    assert not is_shareable("ZELLE FROM JANE")
    assert is_shareable("COSTCO WHSE #0664")


# --- categorize the merchant once, fill every transaction -------------------

def test_merchant_ruling_fills_all_its_transactions(tmp_path):
    ledger = _card_with([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
                         ("2026-01-09", "AMZN MKTP US*RH4DD6YM1", "30.00"),
                         ("2026-01-12", "KROGER #0548", "100.00")], tmp_path)
    proj = ledger.projection()
    # 2 distinct merchants (two Amazon variants collapse), 3 uncategorized txns.
    assert len(proj.uncategorized_merchants()) == 2
    assert len(proj.uncategorized_expenses()) == 3

    assign_merchant_category(ledger, "AMZN MKTP US*RA30Z3BP0", "shopping")
    proj2 = ledger.projection()
    # BOTH Amazon transactions are now categorized from the one ruling.
    assert proj2.spending_by_category() == {"shopping": Decimal("80.00"),
                                            "Uncategorized": Decimal("100.00")}
    assert len(proj2.uncategorized_expenses()) == 1        # only Kroger left


def test_per_transaction_override_beats_the_merchant_rule(tmp_path):
    ledger = _card_with([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
                         ("2026-01-09", "AMZN MKTP US*RH4DD6YM1", "30.00")], tmp_path)
    amazon_key = normalize_merchant("AMZN MKTP US*RA30Z3BP0")   # the queue's key
    assign_merchant_category(ledger, amazon_key, "shopping")    # merchant prior
    amazon1 = next(m for m in ledger.projection().movements() if "RA30Z" in m.description)
    assign_category(ledger, amazon1.key, "groceries")          # override this one
    proj = ledger.projection()
    # The overridden one is groceries (verified), the other stays shopping.
    assert proj.spending_by_category() == {"groceries": Decimal("50.00"),
                                           "shopping": Decimal("30.00")}
    assert proj.derived_category(amazon1)["grade"] == "verified"


def test_batched_categorizer_is_one_call_over_deduped_merchants(tmp_path):
    ledger = _card_with([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00"),
                         ("2026-01-09", "AMZN MKTP US*RH4DD6YM1", "30.00"),
                         ("2026-01-12", "KROGER #0548", "100.00")], tmp_path)
    calls = []

    def categorize_fn(merchants):          # {normalized -> example}
        calls.append(sorted(merchants))
        return {"amzn mktp us": "shopping", "kroger": "groceries"}

    n = categorize_merchants_batch(ledger, categorize_fn, threshold=1)
    assert n == 2 and len(calls) == 1      # ONE call over the 2 deduped merchants
    proj = ledger.projection()
    assert proj.spending_by_category() == {"shopping": Decimal("80.00"),
                                           "groceries": Decimal("100.00")}
    # A batched (model) ruling is corroborated, not verified.
    m = next(mv for mv in proj.movements() if "KROGER" in mv.description)
    assert proj.derived_category(m)["grade"] == "corroborated"


def test_merchant_ruling_survives_a_replay(tmp_path):
    ledger = _card_with([("2026-01-05", "AMZN MKTP US*RA30Z3BP0", "50.00")], tmp_path)
    assign_merchant_category(ledger, normalize_merchant("AMZN MKTP US*RA30Z3BP0"), "shopping")
    replayed = LedgerProjection(ledger.events())
    assert replayed.spending_by_category().get("shopping") == Decimal("50.00")


def test_export_catalog_is_linted_and_carries_no_amounts(tmp_path):
    ledger = _card_with([("2026-01-05", "COSTCO WHSE #0664", "50.00")], tmp_path)
    assign_merchant_category(ledger, "COSTCO WHSE", "shopping")
    # A peer-payment merchant rule must NOT be exported.
    assign_merchant_category(ledger, "VENMO TO JOHN SMITH", "other")
    export = export_catalog(ledger)
    assert "costco whse" in export and export["costco whse"]["category"] == "shopping"
    assert not any("venmo" in k for k in export)          # PII filtered out
    # Only category + grade — no amounts, dates, or transaction links.
    assert set(export["costco whse"].keys()) == {"category", "grade"}
