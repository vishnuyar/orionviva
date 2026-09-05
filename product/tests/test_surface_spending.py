from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import _parameters
from viva.ledger.events import Provenance
from viva.ledger.statements import AccountStatements, StatementRecord
from viva.surface.spending import (SpendingBreakdownRequestError,
                                   spending_breakdown)


class Movement:
    def __init__(self, key, account, date, amount, description, currency,
                 doc, *, nature="spending", nature_reason="ruling",
                 provisional=False, kind="depository"):
        self.key, self.account, self.date = key, account, date
        self.amount, self.description = Decimal(amount), description
        self.currency, self.kind = currency, kind
        self.provenance = Provenance(doc)
        self.nature, self.nature_reason = nature, nature_reason
        self.provisional = provisional


class Projection:
    def __init__(self):
        self.infos = [
            SimpleNamespace(account="acct:usd", name="Everyday", kind="depository", currency="USD"),
            SimpleNamespace(account="acct:eur", name="Travel", kind="depository", currency="EUR"),
        ]
        self.rows = [
            Movement("food", "acct:usd", "2026-08-01", "-50", "Food", "USD", "usd-main"),
            Movement("dining", "acct:usd", "2026-08-31", "-25", "Dining", "USD", "usd-main"),
            Movement("uncat", "acct:usd", "2026-08-12", "-5", "Unknown", "USD", "usd-main"),
            Movement("class-conflict", "acct:usd", "2026-08-13", "-8", "Conflict", "USD", "usd-main"),
            Movement("duplicate-a", "acct:usd", "2026-08-20", "-20", "Train", "USD", "usd-main"),
            Movement("duplicate-b", "acct:usd", "2026-08-20", "-20", "Train", "USD", "usd-overlap"),
            Movement("transfer", "acct:usd", "2026-08-21", "-100", "Transfer", "USD", "usd-main", nature="transfer"),
            Movement("settlement", "acct:usd", "2026-08-21", "-17", "Debt", "USD", "usd-main", nature="settlement"),
            Movement("mixed", "acct:usd", "2026-08-21", "-18", "Mortgage", "USD", "usd-main", nature="mixed"),
            Movement("income", "acct:usd", "2026-08-22", "500", "Pay", "USD", "usd-main"),
            Movement("unattested", "acct:usd", "2026-08-23", "-10", "Weak", "USD", "usd-main"),
            Movement("provisional", "acct:usd", "2026-08-24", "-11", "Hint", "USD", "usd-main", provisional=True),
            Movement("eur", "acct:eur", "2026-08-10", "-30", "Museum", "EUR", "eur-main"),
            Movement("eur-gap", "acct:eur", "2026-08-20", "-40", "Hotel", "EUR", "eur-main"),
        ]
        self.usd = AccountStatements("acct:usd", [
            StatementRecord("usd-main", "acct:usd", "2026-08-01", Decimal("0"), "2026-08-31", Decimal("0")),
            StatementRecord("usd-overlap", "acct:usd", "2026-08-15", Decimal("0"), "2026-08-31", Decimal("0")),
        ], [("2026-08-01", "2026-08-31")])
        self.eur = AccountStatements("acct:eur", [
            StatementRecord("eur-main", "acct:eur", "2026-08-01", Decimal("0"), "2026-08-15", Decimal("0")),
        ], [("2026-08-01", "2026-08-15")])

    def account_infos(self): return list(self.infos)
    def movements(self): return list(self.rows)
    def statements(self, account): return {"acct:usd": self.usd, "acct:eur": self.eur}.get(account)
    def movement_grades(self):
        return {row.key: ("unverified" if row.key == "unattested" else "verified") for row in self.rows}
    def _is_expense(self, row):
        return ((row.kind == "depository" and row.amount < 0)
                or (row.kind == "liability" and row.amount > 0))
    def derived_category(self, row):
        return {
            "food": {"category": "groceries", "subcategory": "fresh_produce", "grade": "verified"},
            "dining": {"category": "dining", "subcategory": "cafes", "grade": "verified"},
            "class-conflict": {"category": "travel", "subcategory": "hotels", "grade": "conflicted"},
            "duplicate-a": {"category": "transport", "subcategory": "rail", "grade": "verified"},
            "duplicate-b": {"category": "transport", "subcategory": "rail", "grade": "verified"},
            "eur": {"category": "entertainment", "subcategory": "museums", "grade": "verified"},
        }.get(row.key)


def read(**kwargs):
    return spending_breakdown(Projection(), "en-US", "2026-09-04", **kwargs)


def test_breakdown_authors_exact_currency_totals_groups_deduplication_and_exclusions():
    result = read()

    assert result["contract"] == "SpendingBreakdown.v1"
    assert result["period"] == {
        "id": "latest_complete_month",
        "label": "Last complete month · Aug 1, 2026–Aug 31, 2026",
        "start_date": "2026-08-01", "end_date": "2026-08-31"}
    assert result["coverage"]["state"] == "partial"
    assert [section["currency"] for section in result["sections"]] == ["EUR", "USD"]
    usd = result["sections"][1]
    assert usd["total_display"] == "USD 108.00"
    assert usd["included_count"] == 5
    assert [bar["label"] for bar in usd["bars"]] == [
        "groceries", "dining", "transport", "Uncategorized"]
    assert sum(bar["share_basis_points"] for bar in usd["bars"]) == 10000
    assert usd["bars"][0]["bar_basis_points"] == 10000
    assert [bar["order"] for bar in usd["bars"]] == list(range(len(usd["bars"])))
    assert result["coverage"]["included_count"] == 6
    kinds = {item["kind"]: item["count"] for item in result["exclusions"]}
    assert kinds == {
        "outside_attested_coverage": 1, "unattested_posting": 1,
        "provisional_treatment": 1, "transfer": 1,
        "debt_or_settlement": 1, "mixed_treatment": 1,
        "income_or_non_expense": 1}
    assert "exact duplicate" in " ".join(result["notes"])


def test_subcategory_account_and_currency_are_compound_and_exactly_scoped():
    result = read(granularity="subcategory", account_id="acct:usd", currency="USD")

    assert len(result["sections"]) == 1
    assert result["scope_summary"] == "Everyday · USD"
    assert [bar["label"] for bar in result["sections"][0]["bars"]] == [
        "groceries · fresh_produce", "dining · cafes",
        "transport · rail", "Uncategorized"]
    assert result["controls"]["selected_account_id"] == "acct:usd"
    assert result["controls"]["selected_currency"] == "USD"
    assert [item["id"] for item in result["controls"]["accounts"]] == ["acct:usd"]


def test_currency_filter_authors_coverage_for_only_that_currency_scope():
    result = read(currency="USD")

    assert result["coverage"]["state"] == "complete"
    assert result["scope_summary"] == "All available USD accounts · USD"
    assert result["sections"][0]["included_count"] == 5


def test_periods_are_inclusive_calendar_ranges_and_handle_leap_years():
    latest = spending_breakdown(Projection(), "en-US", "2024-03-01")
    current = spending_breakdown(Projection(), "en-US", "2026-09-04", period="current_month")
    three = spending_breakdown(Projection(), "en-US", "2026-01-10", period="last_3_months")

    assert (latest["period"]["start_date"], latest["period"]["end_date"]) == (
        "2024-02-01", "2024-02-29")
    assert (current["period"]["start_date"], current["period"]["end_date"]) == (
        "2026-09-01", "2026-09-04")
    assert three["period"]["start_date"] == "2025-11-01"


def test_liability_charges_use_account_kind_direction_and_count_as_spending():
    projection = Projection()
    projection.infos.append(SimpleNamespace(
        account="acct:card", name="Card", kind="liability", currency="USD"))
    projection.rows.append(Movement(
        "card-charge", "acct:card", "2026-08-09", "15", "Fee", "USD",
        "card", kind="liability"))
    projection.card = AccountStatements("acct:card", [
        StatementRecord("card", "acct:card", "2026-08-01", Decimal("0"),
                        "2026-08-31", Decimal("15"))],
        [("2026-08-01", "2026-08-31")])
    original_statements = projection.statements
    projection.statements = lambda account: (projection.card if account == "acct:card"
                                               else original_statements(account))

    result = spending_breakdown(projection, "en-US", "2026-09-04",
                                account_id="acct:card")

    assert result["sections"][0]["total_display"] == "USD 15.00"
    assert result["sections"][0]["bars"][0]["label"] == "Uncategorized"


def test_duplicate_meaning_and_account_currency_conflicts_are_excluded():
    projection = Projection()
    original = projection.derived_category
    projection.derived_category = lambda movement: (
        {"category": "dining", "subcategory": "cafes", "grade": "verified"}
        if movement.key == "duplicate-b" else original(movement))
    projection.rows.append(Movement(
        "currency-conflict", "acct:usd", "2026-08-14", "-99", "Wrong",
        "EUR", "usd-main"))

    result = spending_breakdown(projection, "en-US", "2026-09-04")
    exclusions = {item["kind"]: item["count"] for item in result["exclusions"]}

    assert exclusions["duplicate_conflict"] == 1
    assert exclusions["account_scope_conflict"] == 1
    assert result["sections"][1]["total_display"] == "USD 88.00"


@pytest.mark.parametrize("mutation", [
    "statement_account", "record_account", "empty_run", "overlapping_empty_run",
    "duplicate_document", "cross_account_movement_evidence",
])
def test_account_and_document_identity_ambiguity_refuses_atomically(mutation):
    projection = Projection()
    if mutation == "statement_account":
        projection.usd.account = "acct:eur"
    elif mutation == "record_account":
        projection.usd.records[0] = StatementRecord(
            "usd-main", "acct:eur", "2026-08-01", Decimal("0"),
            "2026-08-31", Decimal("0"))
    elif mutation == "empty_run":
        projection.usd.runs.append(("2026-07-01", "2026-07-31"))
    elif mutation == "overlapping_empty_run":
        projection.usd.runs.append(("2026-08-10", "2026-08-14"))
    elif mutation == "duplicate_document":
        projection.eur.records[0] = StatementRecord(
            "usd-main", "acct:eur", "2026-08-01", Decimal("0"),
            "2026-08-15", Decimal("0"))
    else:
        projection.rows.append(Movement(
            "wrong-owner", "acct:eur", "2026-08-10", "-4", "Wrong",
            "EUR", "usd-main"))

    with pytest.raises(SpendingBreakdownRequestError):
        spending_breakdown(projection, "en-US", "2026-09-04")


def test_coverage_uses_bound_statement_records_not_a_broader_run():
    projection = Projection()
    projection.usd.records = [StatementRecord(
        "usd-main", "acct:usd", "2026-08-10", Decimal("0"),
        "2026-08-20", Decimal("0"))]
    projection.usd.runs = [("2026-08-01", "2026-08-31")]
    projection.rows = [row for row in projection.rows
                       if row.account != "acct:usd" or row.provenance.doc_id == "usd-main"]

    result = spending_breakdown(
        projection, "en-US", "2026-09-04", account_id="acct:usd")

    assert result["coverage"]["state"] == "partial"
    assert [(gap["from"], gap["to"]) for gap in result["coverage"]["gaps"]] == [
        ("2026-08-01", "2026-08-09"), ("2026-08-21", "2026-08-31")]
    assert all(gap["account_label"] == "Everyday"
               and "Everyday" in gap["sentence"]
               for gap in result["coverage"]["gaps"])


def test_incomplete_same_currency_account_is_disclosed_and_selected_scope_refuses():
    projection = Projection()
    projection.infos.append(SimpleNamespace(
        account="acct:incomplete", name="", kind="depository", currency="USD"))

    result = spending_breakdown(projection, "en-US", "2026-09-04")

    assert result["coverage"]["state"] == "partial"
    assert result["coverage"]["unsupported_accounts"] == [{
        "order": 0,
        "account_id": "acct:incomplete", "label": "Account acct:incomplete",
        "currency": "USD", "reason": "missing_account_name",
        "sentence": "Account acct:incomplete has no account name and is outside this spending scope.",
    }]
    with pytest.raises(SpendingBreakdownRequestError, match="complete spending identity"):
        spending_breakdown(projection, "en-US", "2026-09-04",
                            account_id="acct:incomplete")


def test_missing_account_ids_remain_missing_and_cannot_collide_with_real_ids():
    projection = Projection()
    # Before unsupported disclosures stopped fabricating identities, the first
    # missing ID below became ``unsupported-4`` and collided with this real ID.
    projection.infos.extend([
        SimpleNamespace(account="unsupported-4", name="Real placeholder name",
                        kind="depository", currency="USD"),
        SimpleNamespace(account="", name="First missing identity",
                        kind="depository", currency="USD"),
        SimpleNamespace(account="", name="Second missing identity",
                        kind="depository", currency="USD"),
    ])
    projection.placeholder = AccountStatements("unsupported-4", [
        StatementRecord("placeholder-doc", "unsupported-4", "2026-08-01",
                        Decimal("0"), "2026-08-31", Decimal("0"))],
        [("2026-08-01", "2026-08-31")])
    original_statements = projection.statements
    projection.statements = lambda account: (
        projection.placeholder if account == "unsupported-4"
        else original_statements(account))

    result = spending_breakdown(projection, "en-US", "2026-09-04")

    assert "unsupported-4" in [item["id"] for item in result["controls"]["accounts"]]
    assert result["coverage"]["unsupported_accounts"] == [
        {"order": 0, "account_id": "", "label": "First missing identity",
         "currency": "USD", "reason": "missing_account_id",
         "sentence": "First missing identity has no stable account identity and is outside this spending scope."},
        {"order": 1, "account_id": "", "label": "Second missing identity",
         "currency": "USD", "reason": "missing_account_id",
         "sentence": "Second missing identity has no stable account identity and is outside this spending scope."},
    ]
    selected = spending_breakdown(projection, "en-US", "2026-09-04",
                                  account_id="unsupported-4")
    assert selected["controls"]["selected_account_id"] == "unsupported-4"
    with pytest.raises(SpendingBreakdownRequestError, match="identify one"):
        spending_breakdown(projection, "en-US", "2026-09-04",
                            account_id="unsupported-5")


def test_unsupported_account_reason_fields_follow_missing_field_precedence():
    projection = Projection()
    projection.infos.extend([
        SimpleNamespace(account="", name="", kind="mystery", currency=""),
        SimpleNamespace(account="acct:no-name", name="", kind="depository",
                        currency=""),
        SimpleNamespace(account="acct:bad-kind", name="Bad kind", kind="mystery",
                        currency=""),
        SimpleNamespace(account="acct:no-money", name="No money",
                        kind="depository", currency=""),
    ])

    unsupported = spending_breakdown(
        projection, "en-US", "2026-09-04")["coverage"]["unsupported_accounts"]

    assert [(item["reason"], item["account_id"], item["currency"])
            for item in unsupported] == [
        ("missing_account_id", "", ""),
        ("missing_account_name", "acct:no-name", ""),
        ("unsupported_account_kind", "acct:bad-kind", ""),
        ("missing_account_currency", "acct:no-money", ""),
    ]


def test_authored_contract_uses_exact_json_scalar_types():
    result = read()

    assert type(result["as_of"]) is str
    for option in result["controls"]["accounts"]:
        assert type(option["order"]) is int
    for option in result["controls"]["currencies"]:
        assert type(option["order"]) is int
    for section in result["sections"]:
        assert type(section["order"]) is int
        assert type(section["included_count"]) is int
        assert type(section["empty_message"]) is str
        for bar in section["bars"]:
            assert all(type(bar[field]) is int for field in (
                "order", "count", "share_basis_points", "bar_basis_points"))
    assert all(type(result["coverage"][field]) is int
               for field in ("included_count", "excluded_count"))
    assert all(type(item["order"]) is int
               for item in result["coverage"]["gaps"])


def test_default_treatment_refunds_credits_and_non_spending_natures_are_excluded():
    projection = Projection()
    projection.rows.extend([
        Movement("default", "acct:usd", "2026-08-09", "-12", "Default",
                 "USD", "usd-main", nature_reason="default"),
        Movement("unknown-reason", "acct:usd", "2026-08-09", "-13", "Unknown",
                 "USD", "usd-main", nature_reason="conflicted"),
        Movement("refund", "acct:usd", "2026-08-10", "12", "Refund",
                 "USD", "usd-main"),
    ])
    projection.infos.append(SimpleNamespace(
        account="acct:card", name="Card", kind="liability", currency="USD"))
    projection.rows.append(Movement(
        "credit", "acct:card", "2026-08-11", "-7", "Credit", "USD",
        "card", kind="liability"))
    projection.card = AccountStatements("acct:card", [StatementRecord(
        "card", "acct:card", "2026-08-01", Decimal("0"),
        "2026-08-31", Decimal("0"))], [("2026-08-01", "2026-08-31")])
    original_statements = projection.statements
    projection.statements = lambda account: (
        projection.card if account == "acct:card" else original_statements(account))

    result = spending_breakdown(projection, "en-US", "2026-09-04")
    exclusions = {item["kind"]: item["count"] for item in result["exclusions"]}

    assert exclusions["undecided_treatment"] == 1
    assert exclusions["unknown_treatment"] == 1
    assert exclusions["income_or_non_expense"] == 3
    assert exclusions["transfer"] == 1
    assert exclusions["debt_or_settlement"] == 1
    assert exclusions["mixed_treatment"] == 1
    assert result["sections"][1]["total_display"] == "USD 108.00"


def test_equal_amount_labels_use_backend_ordinals_for_deterministic_order():
    projection = Projection()
    projection.rows = [
        Movement("z", "acct:usd", "2026-08-09", "-5", "Z", "USD", "usd-main"),
        Movement("umlaut", "acct:usd", "2026-08-10", "-5", "U", "USD", "usd-main"),
    ]
    projection.infos = projection.infos[:1]
    projection.derived_category = lambda movement: {
        "category": "z" if movement.key == "z" else "ä",
        "subcategory": "", "grade": "verified"}

    result = spending_breakdown(projection, "en-US", "2026-09-04")

    assert [(bar["label"], bar["order"]) for bar in result["sections"][0]["bars"]] == [
        ("z", 0), ("ä", 1)]


@pytest.mark.parametrize("kwargs", [
    {"period": "unknown"},
    {"granularity": "merchant"},
    {"period": "custom"},
    {"period": "custom", "start_date": "2026-08-02", "end_date": "2026-08-01"},
    {"period": "custom", "start_date": "2026-08-01", "end_date": "2027-01-01"},
    {"period": "current_month", "start_date": "2026-08-01"},
    {"account_id": "acct:missing"},
    {"currency": "GBP"},
])
def test_invalid_or_incoherent_parameters_are_refused(kwargs):
    with pytest.raises(SpendingBreakdownRequestError):
        read(**kwargs)


def test_bridge_parameters_are_closed_for_spending():
    assert _parameters("spending", {"period": "current_month", "granularity": "category", "read_on": "2026-09-04"})
    with pytest.raises(BridgeRequestError, match="do not accept fields"):
        _parameters("spending", {"merchant": "Market"})
    with pytest.raises(BridgeRequestError, match="must be a string"):
        _parameters("spending", {"period": 4})
