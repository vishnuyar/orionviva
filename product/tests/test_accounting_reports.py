"""Financial statements preserve money, uncertainty, and accounting scope."""
from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.ledger.accounting import financial_statements
from viva.ledger.events import (Posting, Provenance, account_opened,
                                category_assigned, closing_balance_observed,
                                ruling_recorded, transaction_recorded)
from viva.ledger.postings import (brokerage_activity_transaction,
                                  paystub_decomposition)
from viva.ledger.projection import LedgerProjection


def opened(account="Assets:Checking:Example", kind="depository", currency="USD"):
    return account_opened(account, kind, "Example relationship", currency, "2026-01-01")


def txn(amount, *, account="Assets:Checking:Example", date="2026-02-05", label="Example purchase", doc="statement", counter=None):
    amount = Decimal(amount)
    counter = counter or ("Income:Uncategorized" if amount > 0 else "Expenses:Uncategorized")
    return transaction_recorded([Posting(account, amount, "verified"), Posting(counter, -amount, "verified")], label, date, provenance=Provenance(doc_id=doc))


def test_defaults_include_income_card_expenses_and_period_without_opening():
    proj = LedgerProjection([opened(), opened("Liabilities:Card:Example", "liability"),
        closing_balance_observed("Assets:Checking:Example", "900", "2026-02-28"),
        txn("300", label="Example deposit"), txn("-40", label="Example cash purchase"), txn("25", label="Example card purchase", account="Liabilities:Card:Example", counter="Expenses:Uncategorized"),
        txn("-25", label="Example card payment", account="Liabilities:Card:Example", counter="Transfers:Uncategorized"),
        txn("100", date="2026-03-01")])
    report = financial_statements(proj, start="2026-02-01", end="2026-02-28")
    totals = report["profit_loss"]["by_currency"]["USD"]
    assert totals == {"income": "300", "expenses": "65", "net": "235", "provisional_income": "300", "provisional_expenses": "65"}
    assert report["balance_sheet"]["by_currency"]["USD"]["assets"] == "900"
    assert not report["balance_sheet"]["complete"]
    assert all(line["amount_evidence"]["grade"] == "verified" for line in report["profit_loss"]["lines"])


def test_human_refund_reverses_expense_without_becoming_income():
    proj = LedgerProjection([opened(), txn("-60"), txn("20", label="Example refund")])
    refund = next(m for m in proj.movements() if m.amount > 0)
    proj.apply(ruling_recorded("movement", refund.key, refund.date, legs=[{"major": "expense", "account": "Expenses:Supplies"}]))
    totals = financial_statements(proj)["profit_loss"]["by_currency"]["USD"]
    assert totals["expenses"] == "40"
    assert totals["income"] == "0"


def test_compound_unknown_is_disclosed_and_does_not_invent_principal():
    proj = LedgerProjection([opened(), txn("-75")])
    m = proj.movements()[0]
    proj.apply(ruling_recorded("movement", m.key, m.date, legs=[{"major": "expense", "account": "Expenses:Interest"}, {"major": "liability", "account": "Liabilities:Loan:Example"}]))
    report = financial_statements(proj)
    assert report["profit_loss"]["unresolved_components"][0]["amount"] == "75"
    assert not report["profit_loss"]["complete"]
    assert report["profit_loss"]["by_currency"] == {}
    assert "ask" not in report["balance_sheet"]["missing"][0]


def test_salary_decomposition_and_brokerage_realized_gain_count_once():
    investment = "Assets:Brokerage:Example"
    proj = LedgerProjection([opened(), opened(investment, "investment"),
        txn("80", label="Example payroll"),
        paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")], "Example payroll", "2026-02-05", Provenance(doc_id="paystub")),
        brokerage_activity_transaction(investment, "sell", "90", "Example sale", "2026-02-06", realized_gain="10", provenance=Provenance(doc_id="brokerage")),
        brokerage_activity_transaction(investment, "fee", "3", "Example fee", "2026-02-06", provenance=Provenance(doc_id="brokerage"))])
    totals = financial_statements(proj)["profit_loss"]["by_currency"]["USD"]
    assert totals["income"] == "110"
    assert totals["expenses"] == "23"
    assert totals["net"] == "87"


def test_currency_and_merchant_hierarchy_partition_without_duplicate_totals():
    proj = LedgerProjection([opened(), opened("Assets:Checking:Foreign", currency="EUR"), txn("-10"), txn("-5", account="Assets:Checking:Foreign")])
    for m in proj.movements():
        proj.apply(category_assigned(m.key, m.description, "Household", "verified", m.date, subcategory="Supplies"))
    report = financial_statements(proj)["profit_loss"]
    assert report["by_currency"]["USD"]["expenses"] == "10"
    assert report["by_currency"]["EUR"]["expenses"] == "5"
    assert {row["currency"] for row in report["hierarchy_tree"]} == {"USD", "EUR"}
    assert sum(Decimal(row["amount"]) for row in report["hierarchy"]) == Decimal("15")
    assert financial_statements(LedgerProjection([]))["profit_loss"]["lines"] == []
    with pytest.raises(ValueError):
        financial_statements(proj, start="2026-03-01", end="2026-02-01")


def test_inferred_asset_cost_stays_inferred_and_refund_reduces_same_asset():
    proj = LedgerProjection([opened(), txn("-60"), txn("20", label="Example asset refund")])
    for m in proj.movements():
        proj.apply(ruling_recorded("movement", m.key, m.date,
                                  legs=[{"major": "asset", "account": "Assets:Equipment:Example"}],
                                  by="model", grade="unverified"))
    report = financial_statements(proj)
    line = report["balance_sheet"]["lines"][0]
    assert line["amount"] == "40"
    assert line["grade"] == "unverified"
    assert not line["provable"]
    assert report["profit_loss"]["lines"] == []


def test_same_day_descriptor_collision_does_not_hide_ordinary_activity():
    proj = LedgerProjection([opened(), txn("-40"),
        txn("30", counter="Transfers:Uncategorized")])
    totals = financial_statements(proj)["profit_loss"]["by_currency"]["USD"]
    assert totals["expenses"] == "40"
    assert totals["income"] == "0"


def test_explicit_correction_replaces_original_named_fee_without_double_counting():
    investment = "Assets:Brokerage:Example"
    proj = LedgerProjection([opened(investment, "investment"),
        brokerage_activity_transaction(investment, "fee", "12", "Example activity", "2026-02-06", provenance=Provenance(doc_id="brokerage"))])
    m = proj.movements()[0]
    proj.apply(ruling_recorded("movement", m.key, m.date,
                              legs=[{"major": "asset", "account": "Assets:Deposit:Example"}]))
    report = financial_statements(proj)
    assert report["profit_loss"]["lines"] == []
    assert report["balance_sheet"]["lines"][0]["amount"] == "12"


def test_sql_reports_match_replay_with_allocations_and_inferred_assets(tmp_path):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    investment = "Assets:Brokerage:Example"
    events = [opened(), opened(investment, "investment"),
              txn("80", label="Example payroll"),
              paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")], "Example payroll", "2026-02-05", Provenance(doc_id="paystub")),
              brokerage_activity_transaction(investment, "sell", "90", "Example sale", "2026-02-06", realized_gain="10", provenance=Provenance(doc_id="brokerage")),
              txn("-40", label="Example equipment"),
              closing_balance_observed("Assets:Checking:Example", "400", "2026-02-28", provenance=Provenance(doc_id="statement"))]
    canonical = LedgerProjection(events)
    equipment = next(m for m in canonical.movements() if m.amount == Decimal("-40"))
    correction = ruling_recorded("movement", equipment.key, equipment.date,
                                legs=[{"major": "asset", "account": "Assets:Equipment:Example"}],
                                by="model", grade="unverified")
    events.append(correction)
    canonical.apply(correction)
    source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
    source.append_atomically(lambda _existing: tuple(events))
    with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            actual = financial_statements(revision.overview_projection(today="2026-03-01"))
    assert actual == financial_statements(canonical)


def test_held_first_document_discloses_coverage_without_a_balance_date():
    from viva.ledger.events import statement_held

    proj = LedgerProjection([statement_held("held-example", {}, None, "unreconciled", "2026-02-28")])
    report = financial_statements(proj)
    assert report["balance_sheet"]["held"][0]["doc_id"] == "held-example"
    assert not report["balance_sheet"]["complete"]
    assert report["profit_loss"]["by_currency"] == {}


@pytest.mark.parametrize("sql", [False, True])
def test_payroll_allocation_matches_bank_descriptor_and_settlement_date_difference(tmp_path, sql):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    events = [opened(), txn("80", label="ACH Example payroll", date="2026-02-08"),
              paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")],
                                    "Pay from Example Employer", "2026-02-05", Provenance(doc_id="paystub"))]
    if sql:
        source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
        source.append_atomically(lambda _existing: tuple(events))
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(source)
            with reads.open_reader() as revision:
                report = financial_statements(revision.overview_projection(today="2026-03-01"))
    else:
        report = financial_statements(LedgerProjection(events))
    assert set(report["profit_loss"]["by_currency"]) == {"USD"}
    assert report["profit_loss"]["by_currency"]["USD"] == {
        "income": "100", "expenses": "20", "net": "80",
        "provisional_income": "0", "provisional_expenses": "0"}


@pytest.mark.parametrize("sql", [False, True])
def test_explicit_attested_loan_split_reports_interest_and_preserves_unknown_balance(tmp_path, sql):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    events = [opened(), txn("-100", label="Example loan payment")]
    m = LedgerProjection(events).movements()[0]
    events.append(ruling_recorded("movement", m.key, m.date, by="human", grade="verified",
                  legs=[{"major": "expense", "account": "Expenses:Interest", "share": "0.2"},
                        {"major": "liability", "account": "Liabilities:Loan:Example", "share": "0.8"}]))
    if sql:
        source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
        source.append_atomically(lambda _existing: tuple(events))
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(source)
            with reads.open_reader() as revision:
                report = financial_statements(revision.overview_projection(today="2026-03-01"))
    else:
        report = financial_statements(LedgerProjection(events))
    pl = report["profit_loss"]
    assert Decimal(pl["by_currency"]["USD"]["expenses"]) == Decimal("20")
    assert pl["unresolved_components"] == []
    assert [Decimal(c["amount"]) for c in pl["component_allocations"][0]["components"]] == [Decimal("20"), Decimal("80")]
    assert not report["balance_sheet"]["complete"]
    assert report["balance_sheet"]["missing"][0]["account"] == "Liabilities:Loan:Example"


def test_model_shares_cannot_fabricate_component_amounts():
    proj = LedgerProjection([opened(), txn("-100")])
    m = proj.movements()[0]
    proj.apply(ruling_recorded("movement", m.key, m.date, by="model", grade="unverified",
                  legs=[{"major": "expense", "account": "Expenses:Interest", "share": "0.2"},
                        {"major": "liability", "account": "Liabilities:Loan:Example", "share": "0.8"}]))
    pl = financial_statements(proj)["profit_loss"]
    assert pl["by_currency"] == {}
    assert pl["unresolved_components"][0]["amount"] == "100"
    assert pl["component_allocations"] == []


@pytest.mark.parametrize("sql", [False, True])
def test_durable_payroll_link_selects_one_of_two_equal_net_deposits(tmp_path, sql):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    events = [opened(), txn("80", label="First deposit", date="2026-02-05"),
              txn("80", label="Second deposit", date="2026-02-06")]
    selected = next(m for m in LedgerProjection(events).movements() if m.description == "Second deposit")
    events.append(paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")],
                  "Pay from Example Employer", "2026-02-05", Provenance(doc_id="paystub"),
                  matched_movement_key=selected.key, matched_currency="USD"))
    if sql:
        source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
        source.append_atomically(lambda _existing: tuple(events))
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(source)
            with reads.open_reader() as revision:
                report = financial_statements(revision.overview_projection(today="2026-03-01"))
    else:
        report = financial_statements(LedgerProjection(events))
    pl = report["profit_loss"]
    assert pl["by_currency"]["USD"]["income"] == "180"
    assert pl["by_currency"]["USD"]["provisional_income"] == "80"
    salary = next(row for row in pl["lines"] if row["account"] == "Income:Salary")
    assert salary["amount_evidence"]["related_sources"][0]["movement_key"] == selected.key
    assert pl["unresolved_components"] == []


def test_invalid_durable_payroll_link_never_falls_back_to_another_deposit():
    events = [opened(), txn("80", label="Valid deposit")]
    events.append(paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")],
                  "Pay from Example Employer", "2026-02-05", Provenance(doc_id="paystub"),
                  matched_movement_key="missing-deposit", matched_currency="USD"))
    pl = financial_statements(LedgerProjection(events))["profit_loss"]
    assert pl["by_currency"]["USD"]["income"] == "80"
    assert pl["by_currency"]["USD"]["provisional_income"] == "80"
    assert not pl["complete"]
    assert pl["unresolved_components"][0]["movement_key"] == "missing-deposit"


def test_conversation_income_uses_same_working_totals_and_discloses_inference():
    from viva.tools import default_registry

    projection = LedgerProjection([opened(), txn("75", date="2026-02-05"),
                                  txn("25", date="2026-03-05")])
    report = financial_statements(projection, start="2026-02-01", end="2026-02-28")["profit_loss"]
    result = default_registry(projection).call("query_ledger", {
        "entity": "aggregate", "metric": "income",
        "filters": {"window": {"from": "2026-02-01", "to": "2026-02-28"}}})
    assert result.ok
    assert result.data["by_currency"]["USD"] == report["by_currency"]["USD"]["income"]
    assert result.data["provisional_income_by_currency"] == {"USD": "75"}
    assert result.grade == "unverified"
    assert any("provisional" in caveat for caveat in result.caveats)
    assert result.data["basis"] == "working_profit_loss"


@pytest.mark.parametrize("sql", [False, True])
def test_attested_mixed_asset_expense_has_cost_and_profit_loss_without_mortgage_gap(tmp_path, sql):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    events = [opened(), txn("-150", label="Example equipment and repair"),
              txn("30", label="Example partial return", date="2026-03-05")]
    for movement in LedgerProjection(events).movements():
        events.append(ruling_recorded("movement", movement.key, movement.date,
                      legs=[{"major": "asset", "account": "Assets:Equipment:Example", "share": "0.5"},
                            {"major": "expense", "account": "Expenses:Repair", "share": "0.5"}],
                      by="human", grade="verified"))
    canonical = LedgerProjection(events)
    if sql:
        source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
        source.append_atomically(lambda _existing: tuple(events))
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(source)
            with reads.open_reader() as revision:
                report = financial_statements(revision.overview_projection(today="2026-04-01"), end="2026-02-28", as_of="2026-02-28")
                later = financial_statements(revision.overview_projection(today="2026-04-01"))
    else:
        report = financial_statements(canonical, end="2026-02-28", as_of="2026-02-28")
        later = financial_statements(canonical)
    equipment = next(row for row in report["balance_sheet"]["lines"] if row["account"] == "Assets:Equipment:Example")
    assert Decimal(equipment["amount"]) == Decimal("75")
    assert equipment["currency"] == "USD"
    assert equipment["as_of"] == "2026-02-05"
    assert equipment["grade"] == "verified"
    assert not equipment["provable"]
    assert report["balance_sheet"]["missing"] == []
    assert Decimal(report["profit_loss"]["by_currency"]["USD"]["expenses"]) == Decimal("75")
    assert Decimal(later["balance_sheet"]["lines"][0]["amount"]) == Decimal("60")
    assert Decimal(later["profit_loss"]["by_currency"]["USD"]["expenses"]) == Decimal("60")


def test_unknown_asset_split_discloses_allocation_gap_without_guessing_document_type():
    proj = LedgerProjection([opened(), txn("-150")])
    movement = proj.movements()[0]
    proj.apply(ruling_recorded("movement", movement.key, movement.date,
               legs=[{"major": "asset", "account": "Assets:Equipment:Example"},
                     {"major": "expense", "account": "Expenses:Repair"}], by="human"))
    report = financial_statements(proj)
    gap = report["balance_sheet"]["missing"][0]
    assert gap["account"] == "Assets:Equipment:Example"
    assert "allocated" in gap["why"]
    assert "mortgage" not in str(gap).lower()
    assert "1098" not in str(gap)
    assert report["profit_loss"]["unresolved_components"][0]["amount"] == "150"


@pytest.mark.parametrize("sql", [False, True])
def test_payroll_document_preserves_conflicting_human_refund_treatment(tmp_path, sql):
    from viva.ledger import EventStore
    from viva.read_store import ReadStore

    events = [opened(), txn("80", label="Example returned deposit")]
    selected = LedgerProjection(events).movements()[0]
    events.append(ruling_recorded("movement", selected.key, selected.date,
                  legs=[{"major": "expense", "account": "Expenses:Supplies"}],
                  by="human", grade="verified", said="This was my returned supplies deposit"))
    events.append(paystub_decomposition("100", "80", [SimpleNamespace(amount=Decimal("20"), category="tax")],
                  "Pay from Example Employer", "2026-02-05", Provenance(doc_id="paystub"),
                  matched_movement_key=selected.key, matched_currency="USD"))
    if sql:
        source = EventStore.open(tmp_path / "events.jsonl", "synthetic-password")
        source.append_atomically(lambda _existing: tuple(events))
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(source)
            with reads.open_reader() as revision:
                report = financial_statements(revision.overview_projection(today="2026-03-01"))
    else:
        report = financial_statements(LedgerProjection(events))
    pl = report["profit_loss"]
    assert pl["by_currency"]["USD"]["income"] == "0"
    assert pl["by_currency"]["USD"]["expenses"] == "-80"
    assert not pl["complete"]
    conflict = pl["unresolved_components"][0]
    assert conflict["classification_evidence"]["reason"] == "conflicting_user_treatment"
    assert conflict["classification_evidence"]["existing_treatment"]["said"] == "This was my returned supplies deposit"
    assert conflict["classification_evidence"]["source_refs"] == ["paystub"]
    assert any(row["account"] == "Income:Salary" and row["amount"] == "-100"
               for row in conflict["supporting_components"])
    assert conflict["classification_evidence"]["related_sources"][0]["movement_key"] == selected.key


@pytest.mark.parametrize("sql", [False, True])
def test_undo_restores_default_report_date_without_orphan_account(tmp_path, monkeypatch, sql):
    from viva import engine, accounting_intelligence
    from viva.accounting_intelligence import undo_accounting
    from viva.engine import record_ruling
    from viva.ledger import EventStore, Ledger
    from viva.listen import Interpretation
    from viva.read_store import ReadStore

    monkeypatch.setattr(engine, "_today", lambda: "2026-03-01")
    monkeypatch.setattr(accounting_intelligence, "_today", lambda: "2026-03-01")
    ledger = Ledger(EventStore.open(tmp_path / "events.jsonl", "synthetic-password"))
    ledger.append(opened())
    ledger.append(txn("-15"))
    ledger.append(closing_balance_observed("Assets:Checking:Example", "85", "2026-02-28"))
    vault = SimpleNamespace(ledger=ledger)
    before = financial_statements(ledger.projection())
    m = ledger.projection().movements()[0]
    result = record_ruling(vault, Interpretation(legs=[{"major": "asset", "account_hint": "Workshop"}],
                            said="Example equipment", future_scope="one"), m.description, movement_key=m.key)
    assert result["ok"]
    assert undo_accounting(vault, result["correction_id"])["ok"]
    if sql:
        with ReadStore.create(tmp_path / "read-model", "synthetic-password") as reads:
            reads.synchronize(ledger.store)
            with reads.open_reader() as revision:
                after = financial_statements(revision.overview_projection(today="2026-03-01"))
    else:
        after = financial_statements(ledger.projection())
    assert after == before
    assert after["balance_sheet"]["as_of"] == "2026-02-28"
    assert not after["balance_sheet"]["missing"]
