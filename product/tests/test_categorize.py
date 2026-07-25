"""Slice 5 — categorization & spending: the kind-aware counter-leg, the category
overlay, and a real spending-by-category number."""

from decimal import Decimal

from viva.answer import answer_spending
from viva.ingest import (POSTED, RawStore, ReadResult, StatementFacts, TxnFact,
                         account_id_for, assign_category, capture_and_ingest,
                         suggest_categories)
from viva.ledger import (EXPENSE_UNCATEGORIZED, INCOME_UNCATEGORIZED,
                         TRANSFERS_UNCATEGORIZED, EventStore, Ledger,
                         LedgerProjection, counter_account)


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _up(raw, ledger, data, facts):
    return capture_and_ingest(
        raw, ledger, data,
        lambda d, did: (_stamp(facts, did)),
        captured_at="2026-02-01")


def _stamp(facts, doc_id):
    facts.doc_id = doc_id
    return ReadResult(facts.doc_type, 0.98, facts)


def _facts(opening, txns, closing, ref, doc_type, number="", inst="Acme"):
    return StatementFacts(
        doc_id="", doc_type=doc_type, doc_type_confidence=0.98,
        account_ref=ref, currency="USD",
        opening_amount=Decimal(opening), opening_date="2026-01-01",
        closing_amount=Decimal(closing), closing_date="2026-01-31",
        transactions=[TxnFact(d, desc, Decimal(a)) for d, desc, a in txns],
        account_number=number, institution=inst)


# --- the kind-aware counter-leg (the first job) -----------------------------

def test_counter_account_is_kind_aware():
    # asset: in=income, out=expense
    assert counter_account("depository", Decimal("100")) == INCOME_UNCATEGORIZED
    assert counter_account("depository", Decimal("-100")) == EXPENSE_UNCATEGORIZED
    # liability: a charge is an EXPENSE, a payment is a TRANSFER (not income)
    assert counter_account("liability", Decimal("100")) == EXPENSE_UNCATEGORIZED
    assert counter_account("liability", Decimal("-100")) == TRANSFERS_UNCATEGORIZED


def test_card_purchase_is_expense_not_income(tmp_path):
    raw, ledger = _stores(tmp_path)
    # A card with a purchase (+300, owed up) and a payment (-100, owed down).
    card = _facts("0.00", [("2026-01-05", "STORE", "300.00"),
                           ("2026-01-20", "PAYMENT THANK YOU", "-100.00")],
                  "200.00", ref="Card 7799", doc_type="credit_card_statement",
                  number="000000007799")
    _up(raw, ledger, b"card", card)
    proj = ledger.projection()
    # The purchase's counter-leg is an EXPENSE (not income); the payment is a
    # transfer bucket (not an expense). A purchase never touches income.
    assert EXPENSE_UNCATEGORIZED in proj.accounts()
    assert TRANSFERS_UNCATEGORIZED in proj.accounts()
    assert INCOME_UNCATEGORIZED not in proj.accounts()   # a purchase is NOT income
    # The clean aggregate: the $300 purchase is spending; the $100 payment is not.
    assert proj.spending_by_category() == {"Uncategorized": Decimal("300.00")}


# --- the category overlay + spending ----------------------------------------

def _checking_with_spend(tmp_path):
    raw, ledger = _stores(tmp_path)
    chk = _facts("5000.00", [("2026-01-05", "KROGER #123", "-100.00"),
                             ("2026-01-08", "SHELL OIL", "-40.00")],
                 "4860.00", ref="Checking 1111", doc_type="checking_statement",
                 number="000000001111")
    _up(raw, ledger, b"chk", chk)
    return raw, ledger


def test_spending_by_category_and_assignment(tmp_path):
    raw, ledger = _checking_with_spend(tmp_path)
    proj = ledger.projection()
    # Before categorizing, all spending is Uncategorized.
    assert proj.spending_by_category() == {"Uncategorized": Decimal("140.00")}
    assert len(proj.uncategorized_expenses()) == 2

    kroger = next(m for m in proj.movements() if "KROGER" in m.description)
    assert assign_category(ledger, kroger.key, "Groceries") is True
    proj2 = ledger.projection()
    assert proj2.spending_by_category() == {"groceries": Decimal("100.00"),
                                            "Uncategorized": Decimal("40.00")}
    # The assignment is verified, keyed to the movement, and captured the descriptor.
    cat = proj2.category_of(kroger.key)
    assert cat["grade"] == "verified" and "KROGER" in cat["descriptor"]


def test_model_suggestion_is_unverified_human_confirmation_verified(tmp_path):
    raw, ledger = _checking_with_spend(tmp_path)
    # A stub model suggester categorizes by a keyword.
    def suggest(desc):
        return "groceries" if "KROGER" in desc else ("transport" if "SHELL" in desc else None)
    assert suggest_categories(ledger, suggest) == 2
    proj = ledger.projection()
    # Suggestions populate spending but are graded unverified.
    assert proj.spending_by_category() == {"groceries": Decimal("100.00"),
                                           "transport": Decimal("40.00")}
    kroger = next(m for m in proj.movements() if "KROGER" in m.description)
    assert proj.category_of(kroger.key)["grade"] == "unverified"
    # A human confirmation supersedes the model and becomes verified.
    assign_category(ledger, kroger.key, "dining")
    proj2 = ledger.projection()
    assert proj2.category_of(kroger.key)["category"] == "dining"
    assert proj2.category_of(kroger.key)["grade"] == "verified"


def test_categorization_survives_a_replay(tmp_path):
    raw, ledger = _checking_with_spend(tmp_path)
    kroger = next(m for m in ledger.projection().movements() if "KROGER" in m.description)
    assign_category(ledger, kroger.key, "groceries")
    # Rebuilding the projection from events (as a reingest does) keeps the category
    # because it is keyed to the content-derived movement key.
    replayed = LedgerProjection(ledger.events())
    assert replayed.spending_by_category().get("groceries") == Decimal("100.00")


def test_answer_spending_reports_categories(tmp_path):
    raw, ledger = _checking_with_spend(tmp_path)
    kroger = next(m for m in ledger.projection().movements() if "KROGER" in m.description)
    assign_category(ledger, kroger.key, "groceries")
    ans = answer_spending(ledger.projection())
    assert ans.answered and ans.amount == Decimal("140.00")
    assert "groceries" in ans.text.lower() and any("uncategor" in c.lower() for c in ans.caveats)
