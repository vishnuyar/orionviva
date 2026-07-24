"""Slice 4 — pay stubs & income: the first divergent document.

The identity is gross − deductions = net (not a balance); a pay stub decomposes
the checking deposit it explains, income is counted once, deductions land in
universal buckets, and a stub that doesn't balance is held (never guessed)."""

from decimal import Decimal

from viva.answer import answer_balance
from viva.ingest import (AWAITING, CONFLICT, POSTED, Deduction, PayStubFacts,
                         RawStore, ReadResult, StatementFacts, TxnFact,
                         capture_and_ingest, from_paystub_json, post_paystub)
from viva.ingest.registry import can_project, profile_for
from viva.ledger import EventStore, Ledger, LedgerProjection, Provenance
from vivacore.verify.arithmetic import check_paystub_identity


def _stores(tmp_path):
    return (RawStore.open(tmp_path / "raw", "pw"),
            Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")))


def _paystub(gross, net, deductions, doc_id="P1", employer="Acme",
             pay_date="2026-01-15"):
    return PayStubFacts(
        doc_id=doc_id, doc_type="pay_stub", doc_type_confidence=0.99,
        employer=employer, currency="USD", pay_date=pay_date,
        period_start="2026-01-01", period_end="2026-01-15",
        gross=Decimal(gross), net=Decimal(net),
        deductions=[Deduction(l, Decimal(a), c) for l, a, c in deductions])


def _checking_with_deposit(ledger, net, date="2026-01-15", doc="S1"):
    from viva.ledger import (account_opened, closing_balance_observed,
                             opening_balance_observed, simple_transaction)
    ledger.append(account_opened("chk", "depository", "Checking", "USD", "2026-01-01"))
    ledger.append(opening_balance_observed("chk", "1000", "2026-01-01", Provenance(doc, 1)))
    ledger.append(simple_transaction("chk", Decimal(net), "DIRECT DEP PAYROLL",
                                     date, provenance=Provenance(doc, 2)))
    ledger.append(closing_balance_observed("chk", str(1000 + Decimal(net)),
                                           "2026-01-31", Provenance(doc, 6)))


# --- the identity (shared arithmetic) --------------------------------------

def test_paystub_identity():
    assert check_paystub_identity("5000", ["700", "400", "100"], "3800").passed
    assert not check_paystub_identity("5000", ["700", "400"], "3800").passed


def test_parser_refuses_an_unreadable_figure():
    facts, err = from_paystub_json('{"gross_raw":"not-a-number","net_raw":"3800",'
                                   '"deductions":[]}', "P", "en-US", "USD")
    assert facts is None and "gross" in err


# --- the divergent profile --------------------------------------------------

def test_pay_stub_routes_to_its_own_projector():
    assert can_project("pay_stub") and profile_for("pay_stub").identity == "paystub"
    assert profile_for("pay_stub").account_kind == ""      # not an account


# --- decompose the deposit --------------------------------------------------

def test_paystub_decomposes_the_deposit_income_counted_once(tmp_path):
    raw, ledger = _stores(tmp_path)
    _checking_with_deposit(ledger, "3800")
    res = post_paystub(ledger, _paystub("5000", "3800",
                       [("Fed Tax", "700", "tax"), ("401k", "400", "retirement"),
                        ("Health", "100", "insurance")]))
    assert res.action == POSTED and res.grade == "corroborated"
    proj = ledger.projection()
    # Gross recognized once; the deposit's uncategorized placeholder is cancelled.
    assert proj.balance("Income:Salary").amount == Decimal("-5000")
    assert proj.balance("Income:Uncategorized").amount == Decimal("0")
    assert proj.income_by_currency() == {"USD": Decimal("5000")}
    # Deductions in universal buckets; retirement is an ASSET, not spending.
    assert proj.balance("Assets:Retirement").amount == Decimal("400")
    assert proj.balance("Expenses:Tax").amount == Decimal("700")
    assert proj.balance("Expenses:Insurance").amount == Decimal("100")
    # The real deposit is untouched.
    assert proj.balance("chk").amount == Decimal("4800")


def test_unbalanced_paystub_is_held_with_a_localized_finding(tmp_path):
    raw, ledger = _stores(tmp_path)
    _checking_with_deposit(ledger, "3800")
    # 5000 − (700 + 400) = 3900 ≠ 3800; the gap (100) equals the missing Health line.
    res = post_paystub(ledger, _paystub("5000", "3800",
                       [("Fed Tax", "700", "tax"), ("401k", "400", "retirement")]))
    assert res.action == CONFLICT
    assert res.finding is not None and res.finding.status in ("suggested", "unlocalized")
    # Nothing income posted.
    assert "Income:Salary" not in LedgerProjection(ledger.events()).accounts()


def test_paystub_without_deposit_waits_then_heals(tmp_path):
    raw, ledger = _stores(tmp_path)
    ps = _paystub("5000", "3800", [("Fed Tax", "700", "tax"),
                                   ("401k", "400", "retirement"),
                                   ("Health", "100", "insurance")])
    res = post_paystub(ledger, ps)              # no checking deposit yet
    assert res.action == AWAITING
    assert LedgerProjection(ledger.events()).income_by_currency() == {}
    # The deposit arrives via a checking statement → heal posts the decomposition.
    data = b"chk-stmt"
    jan = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Checking 1111", currency="USD",
        opening_amount=Decimal("1000"), opening_date="2026-01-01",
        closing_amount=Decimal("4800"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-15", "DIRECT DEP PAYROLL", Decimal("3800"))],
        account_number="000000001111", institution="Bank")

    def rf(d, doc_id):
        jan.doc_id = doc_id
        return ReadResult("checking_statement", 0.98, jan)
    capture_and_ingest(raw, ledger, data, rf, captured_at="2026-02-01")
    proj = ledger.projection()
    assert proj.income_by_currency() == {"USD": Decimal("5000")}   # healed
    assert proj.balance("Assets:Retirement").amount == Decimal("400")


def test_surface_shows_income_and_pending_paystubs(tmp_path):
    from viva.vault import Vault
    from viva.web import service
    v = Vault.open(tmp_path / "vault", "pw")
    _checking_with_deposit(v.ledger, "3800")
    post_paystub(v.ledger, _paystub("5000", "3800",
                 [("Fed Tax", "700", "tax"), ("401k", "400", "retirement"),
                  ("Health", "100", "insurance")]))
    # A second stub with no deposit yet → pending on the surface.
    post_paystub(v.ledger, _paystub("5000", "3800",
                 [("Fed Tax", "700", "tax"), ("401k", "400", "retirement"),
                  ("Health", "100", "insurance")], doc_id="P2", pay_date="2026-02-15"))
    ov = service.overview(v)
    assert ov["income"] == {"USD": "5000"}
    assert any(r["label"] == "Retirement" for r in ov["income_breakdown"])
    assert ov["paystub_review_count"] == 1
    pr = service.paystub_review(v)["items"]
    assert pr and pr[0]["reason"] == "awaiting_deposit" and pr[0]["employer"] == "Acme"


def test_balance_statements_still_work(tmp_path):
    # The divergent dispatch is behaviour-preserving for the balance family.
    raw, ledger = _stores(tmp_path)
    jan = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Checking 1111", currency="USD",
        opening_amount=Decimal("1000"), opening_date="2026-01-01",
        closing_amount=Decimal("1500"), closing_date="2026-01-31",
        transactions=[TxnFact("2026-01-10", "Pay", Decimal("500"))],
        account_number="000000001111", institution="Bank")

    def rf(d, doc_id):
        jan.doc_id = doc_id
        return ReadResult("checking_statement", 0.98, jan)
    res = capture_and_ingest(raw, ledger, b"s", rf, captured_at="2026-02-01")
    assert res.action == POSTED
