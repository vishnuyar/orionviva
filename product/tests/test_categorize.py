"""Categorization & spending: the kind-aware counter-leg, the category overlay,
and a real spending-by-category number."""

from dataclasses import replace
from decimal import Decimal

import pytest

from viva.answer import answer_spending
from viva.ingest import (POSTED, RawStore, ReadResult, StatementFacts, TxnFact,
                         account_id_for, assign_category,
                         assign_default_categories, assign_merchant_category,
                         capture_and_ingest,
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


def test_import_defaults_peer_payments_before_asking_questions(tmp_path):
    from viva.ledger.merchant_keys import MerchantKeys
    from viva.questions import MERCHANT, NATURE, open_questions

    raw = RawStore.open(tmp_path / "raw", "pw")

    def resolved(rows):
        rows = list(rows)
        keys = {((account, description), description.lower())
                for account, _institution, _kind, description in rows}
        persons = {(account, description)
                   for account, _institution, _kind, description in rows
                   if description == "ZELLE PAYMENT TO JOHN"}
        return MerchantKeys(keys, persons=persons)

    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "pw"),
                    resolve_keys=resolved)
    checking = _facts(
        "1000.00",
        [("2026-01-05", "ZELLE PAYMENT TO JOHN", "-200.00"),
         ("2026-01-08", "MYSTERY SHOP", "-40.00"),
         ("2026-01-09", "PAYMENT TO IRS", "-60.00")],
        "700.00", ref="Checking 1111", doc_type="checking_statement",
        number="000000001111")
    result = _up(raw, ledger, b"defaulted", checking)

    assert assign_default_categories(ledger, result.doc_id) == 3
    assert assign_default_categories(ledger, result.doc_id) == 0, \
        "the statement-scoped default is idempotent"
    projection = ledger.projection()
    categorized = {
        movement.description: projection.derived_category(movement)
        for movement in projection.movements()
    }
    assert categorized["ZELLE PAYMENT TO JOHN"]["category"] == "transfers"
    assert categorized["MYSTERY SHOP"]["category"] == "other"
    assert categorized["PAYMENT TO IRS"]["category"] == "other"
    assert all(row["by"] == "default" for row in categorized.values())
    peer = next(movement for movement in projection.movements()
                if movement.description == "ZELLE PAYMENT TO JOHN")
    assert peer.nature == "transfer"
    assert projection.spending_by_category() == {"other": Decimal("100.00")}
    routine = [question for question in open_questions(
        ledger, as_of="2026-02-01")["questions"]
               if question["kind"] in (MERCHANT, NATURE)]
    assert routine == [], "a usable default must not turn import into an interview"

    assign_merchant_category(ledger, "mystery shop", "food", by="model")
    refreshed = ledger.projection()
    mystery = next(movement for movement in refreshed.movements()
                   if movement.description == "MYSTERY SHOP")
    assert refreshed.derived_category(mystery)["category"] == "food", \
        "positive catalog knowledge replaces the import fallback"


def test_statement_defaults_do_not_backfill_another_document(tmp_path):
    from viva.ledger import Provenance, account_opened, simple_transaction

    _raw, ledger = _stores(tmp_path)
    ledger.append(account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01"))
    ledger.append(simple_transaction(
        "checking", "-10.00", "OLDER SHOP", "2026-01-02",
        provenance=Provenance(doc_id="older-document")))
    ledger.append(simple_transaction(
        "checking", "-20.00", "NEW SHOP", "2026-01-03",
        provenance=Provenance(doc_id="new-document")))

    assert assign_default_categories(ledger, "new-document") == 1
    projection = ledger.projection()
    categories = {movement.description: projection.derived_category(movement)
                  for movement in projection.movements()}
    assert categories["NEW SHOP"]["category"] == "other"
    assert categories["OLDER SHOP"] is None


def test_upload_defaults_only_the_successfully_posted_statement(tmp_path):
    from viva import engine
    from viva.ledger import Provenance, account_opened, simple_transaction
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "older", "depository", "Older", "USD", "2025-12-01"))
    vault.ledger.append(simple_transaction(
        "older", "-10.00", "OLDER SHOP", "2025-12-02",
        provenance=Provenance(doc_id="older-document")))
    checking = _facts(
        "100.00", [("2026-01-05", "NEW SHOP", "-20.00")], "80.00",
        ref="Checking 1111", doc_type="checking_statement",
        number="000000001111")

    result = engine.upload(
        vault, "checking.pdf", b"new-statement",
        lambda _data, doc_id: _stamp(checking, doc_id))

    assert result["action"] == POSTED
    projection = vault.ledger.projection()
    categories = {movement.description: projection.derived_category(movement)
                  for movement in projection.movements()}
    assert categories["NEW SHOP"]["category"] == "other"
    assert categories["OLDER SHOP"] is None


@pytest.mark.parametrize("doc_type", [
    "combined_bank_statement", "money_market_statement", "card_statement"])
def test_upload_defaults_every_registered_balance_statement_alias(
        tmp_path, doc_type):
    from viva import engine
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    statement = _facts(
        "100.00", [("2026-01-05", "NEW SHOP", "-20.00")], "80.00",
        ref="Statement 1111", doc_type=doc_type, number="000000001111")

    result = engine.upload(
        vault, "statement.pdf", doc_type.encode(),
        lambda _data, doc_id: _stamp(statement, doc_id))

    assert result["action"] == POSTED
    movement = vault.ledger.projection().movements()[0]
    assert vault.ledger.projection().derived_category(movement)["category"] == "other"


def test_upload_defaults_the_connector_and_every_gap_statement_it_releases(
        tmp_path):
    from viva import engine
    from viva.questions import MERCHANT, NATURE, open_questions
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    statements = [
        (b"january", replace(_facts(
            "100.00", [("2026-01-10", "JANUARY SHOP", "-20.00")], "80.00",
            ref="Checking 1111", doc_type="checking_statement",
            number="000000001111"), opening_date="2026-01-01",
            closing_date="2026-01-31")),
        (b"march", replace(_facts(
            "60.00", [("2026-03-10", "MARCH SHOP", "-20.00")], "40.00",
            ref="Checking 1111", doc_type="checking_statement",
            number="000000001111"), opening_date="2026-03-01",
            closing_date="2026-03-31")),
        (b"february", replace(_facts(
            "80.00", [("2026-02-10", "FEBRUARY SHOP", "-20.00")], "60.00",
            ref="Checking 1111", doc_type="checking_statement",
            number="000000001111"), opening_date="2026-02-01",
            closing_date="2026-02-28")),
    ]

    outcomes = [engine.upload(
        vault, f"{facts.closing_date}.pdf", body,
        lambda _data, doc_id, facts=facts: _stamp(facts, doc_id))
        for body, facts in statements]

    assert [outcome["action"] for outcome in outcomes] == [
        POSTED, "gap", POSTED]
    projection = vault.ledger.projection()
    assert {movement.description: projection.derived_category(movement)["category"]
            for movement in projection.movements()} == {
        "JANUARY SHOP": "other", "FEBRUARY SHOP": "other",
        "MARCH SHOP": "other"}
    routine = [question for question in open_questions(
        vault.ledger, as_of="2026-04-01")["questions"]
               if question["kind"] in (MERCHANT, NATURE)]
    assert routine == []


def test_human_correction_defaults_the_statement_it_posts(tmp_path):
    from viva import engine
    from viva.vault import Vault

    vault = Vault.open(tmp_path / "vault", "pw")
    held = _facts(
        "1000.00", [("2026-01-10", "PAY", "400.00"),
                    ("2026-01-20", "RENT", "-100.00")], "1500.00",
        ref="Checking 1111", doc_type="checking_statement",
        number="000000001111")
    uploaded = engine.upload(
        vault, "held.pdf", b"held",
        lambda _data, doc_id: _stamp(held, doc_id))
    assert uploaded["action"] == "conflict"

    corrected = engine.confirm_correction(
        vault, uploaded["doc_id"], "amount", "600.00", 0)

    assert corrected["action"] == POSTED
    projection = vault.ledger.projection()
    assert {projection.derived_category(movement)["category"]
            for movement in projection.movements()} == {"other"}


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
