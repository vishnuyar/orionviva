from __future__ import annotations

import base64
import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ledger import (account_opened, opening_balance_observed,
                         simple_transaction)
from viva.ledger.events import Provenance
from viva.ledger.statements import AccountStatements, StatementRecord
from viva.surface.account_ledger import (
    AccountLedgerCursorError, AccountLedgerIdentityError, _direction_display,
    account_ledger)
from viva.vault import Vault


CURSOR_SECRET = b"account-ledger-test-cursor-secret-v1"


def read_ledger(projection, account_id: str, revision: str, **parameters):
    return account_ledger(
        projection, account_id, "en-US", revision,
        cursor_secret=CURSOR_SECRET, **parameters)


class Movement:
    def __init__(self, key: str, account: str, date: str, description: str,
                 amount: str, doc_id: str, page: int) -> None:
        self.key = key
        self.account = account
        self.kind = "depository"
        self.date = date
        self.description = description
        self.amount = Decimal(amount)
        self.currency = "USD"
        self.provenance = Provenance(doc_id, page, f"row:{key}")
        self.linked = False
        self.nature = "spending"
        self.nature_reason = "default"
        self.provisional = False
        self.ruling_account = ""


class Projection:
    ACCOUNT = "acct:checking"
    OTHER = "acct:savings"

    def __init__(self) -> None:
        self._infos = [
            SimpleNamespace(account=self.ACCOUNT, name="Everyday Checking",
                            kind="depository", currency="USD",
                            number="000000004417"),
            SimpleNamespace(account=self.OTHER, name="Rainy Day Savings",
                            kind="depository", currency="USD",
                            number="000000006723"),
        ]
        self._movements = [
            Movement("movement:a", self.ACCOUNT, "2026-04-22", "Market", "-12", "apr", 2),
            Movement("movement:c", self.ACCOUNT, "2026-04-18", "Train", "-4", "apr", 2),
            Movement("movement:b", self.ACCOUNT, "2026-04-18", "Cafe", "-7", "overlap", 4),
            Movement("movement:d", self.ACCOUNT, "2026-02-07", "Pharmacy", "-20", "feb", 2),
            Movement("movement:e", self.ACCOUNT, "2026-01-14", "Payroll", "500", "jan", 2),
            Movement("movement:f", self.ACCOUNT, "2026-01-03", "Bakery", "-8", "jan", 2),
            Movement("movement:other", self.OTHER, "2026-05-01", "Interest", "3", "other", 1),
        ]
        records = [
            StatementRecord("jan", self.ACCOUNT, "2026-01-01", Decimal("100"), "2026-01-31", Decimal("200")),
            StatementRecord("feb", self.ACCOUNT, "2026-02-01", Decimal("200"), "2026-02-28", Decimal("250")),
            StatementRecord("overlap", self.ACCOUNT, "2026-02-15", Decimal("220"), "2026-02-28", Decimal("250")),
            StatementRecord("apr", self.ACCOUNT, "2026-04-01", Decimal("250"), "2026-04-30", Decimal("300")),
        ]
        self._statements = AccountStatements(
            self.ACCOUNT, records,
            [("2026-01-01", "2026-02-28"), ("2026-04-01", "2026-04-30")])

    def account_infos(self): return list(self._infos)
    def account_info(self, account): return next(i for i in self._infos if i.account == account)
    def movements(self): return list(self._movements)
    def statements(self, account):
        return (self._statements if account == self.ACCOUNT
                else getattr(self, "_other_statements", None)
                if account == self.OTHER else None)
    def captured_filenames(self): return {key: f"{key}.pdf" for key in ("jan", "feb", "overlap", "apr", "other")}
    def balance(self, account):
        assert account == self.ACCOUNT
        return SimpleNamespace(amount=Decimal("300"), dated="2026-04-30",
                               grade="corroborated",
                               reconciliation=SimpleNamespace(passed=True))
    def derived_category(self, _movement): return None
    def transfer_suggestions(self): return []
    def transfer_links(self): return []
    def linked_keys(self): return set()
    def tags_of(self, _movement): return []
    def inherited_tags_of(self, _movement): return []
    def known_categories(self): return []
    def known_tags(self): return []


def test_account_ledger_is_scoped_sorted_grouped_and_paginated_before_any_client():
    projection = Projection()
    first = read_ledger(projection, projection.ACCOUNT, "revision-one", limit=3)

    assert first["scope"] == {"kind": "account", "account_id": projection.ACCOUNT}
    assert first["account"] == {
        "id": projection.ACCOUNT, "name": "Everyday Checking",
        "number_masked": "••••4417", "type": "depository", "currency": "USD",
        "balance": {"state": "available", "kind": "current_balance", "exact_value": "300",
                    "display": "USD 300.00", "as_of": "2026-04-30",
                    "grade": "corroborated"},
    }
    first_rows = [row for group in first["groups"] for row in group["movements"]]
    assert [row["id"] for row in first_rows] == [
        "movement:a", "movement:c", "movement:b"]
    assert all(row["account_id"] == projection.ACCOUNT for row in first_rows)
    assert "movement:other" not in json.dumps(first)
    assert first["groups"][0]["label"] == "April 2026"
    assert first["page"]["remaining"] == 3
    assert all(row["deduplication"]["state"] == "single" for row in first_rows)
    assert {row["direction_display"] for row in first_rows} <= {
        "Debit", "Credit"}

    second = read_ledger(
        projection, projection.ACCOUNT, "revision-one", limit=3,
        cursor=first["page"]["next_cursor"])
    second_rows = [row for group in second["groups"] for row in group["movements"]]
    assert [row["id"] for row in second_rows] == [
        "movement:d", "movement:e", "movement:f"]
    assert not ({row["id"] for row in first_rows}
                & {row["id"] for row in second_rows})
    assert second["page"]["next_cursor"] is None


def test_account_ledger_authors_direction_words_without_client_financial_logic():
    assert _direction_display("out") == "Debit"
    assert _direction_display("in") == "Credit"
    assert _direction_display("unknown") == "Direction unavailable"


def test_account_ledger_reports_attested_runs_gap_overlap_sources_and_no_running_balance():
    read = read_ledger(Projection(), Projection.ACCOUNT, "revision-one")

    assert read["coverage"] == {
        "state": "gapped",
        "runs": [
            {"from": "2026-01-01", "to": "2026-02-28",
             "statement_ids": ["jan", "feb", "overlap"]},
            {"from": "2026-04-01", "to": "2026-04-30",
             "statement_ids": ["apr"]},
        ],
        "gaps": [{"from": "2026-03-01", "to": "2026-03-31",
                  "reason": "missing_statement_coverage"}],
    }
    assert read["reconciliation"]["overlap"] == {
        "state": "overlap_present", "deduplication": {
            "state": "none",
            "policy": "exact_economic_posting_in_overlapping_statements_only",
            "collapsed": [], "unresolved": [],
        },
        "groups": [{"from": "2026-02-15", "to": "2026-02-28",
                    "document_ids": ["feb", "overlap"]}],
    }
    assert read["reconciliation"]["balance"] == "reconciled"
    assert read["reconciliation"]["running_balance"]["state"] == "absent"
    assert all("running_balance" not in row for group in read["groups"]
               for row in group["movements"])
    assert {source["document_id"] for source in read["sources"]} == {
        "jan", "feb", "overlap", "apr"}
    assert all(row["actions"] == [] for group in read["groups"]
               for row in group["movements"])


def test_account_ledger_unions_nested_and_overlapping_runs_before_finding_gaps():
    projection = Projection()
    projection._statements.records = [
        StatementRecord("jan", projection.ACCOUNT, "2026-01-01",
                        Decimal("100"), "2026-01-31", Decimal("200")),
        StatementRecord("nested", projection.ACCOUNT, "2026-01-10",
                        Decimal("120"), "2026-01-20", Decimal("160")),
        StatementRecord("extends", projection.ACCOUNT, "2026-01-20",
                        Decimal("160"), "2026-02-15", Decimal("240")),
        StatementRecord("apr", projection.ACCOUNT, "2026-04-01",
                        Decimal("240"), "2026-04-30", Decimal("300")),
    ]
    projection._statements.runs = [
        ("2026-01-01", "2026-01-31"),
        ("2026-01-10", "2026-01-20"),
        ("2026-01-20", "2026-02-15"),
        ("2026-04-01", "2026-04-30"),
    ]

    coverage = read_ledger(
        projection, projection.ACCOUNT, "nested-revision")["coverage"]

    assert coverage == {
        "state": "gapped",
        "runs": [
            {"from": "2026-01-01", "to": "2026-02-15",
             "statement_ids": ["jan", "nested", "extends"]},
            {"from": "2026-04-01", "to": "2026-04-30",
             "statement_ids": ["apr"]},
        ],
        "gaps": [{"from": "2026-02-16", "to": "2026-03-31",
                  "reason": "missing_statement_coverage"}],
    }
    assigned = [document_id for run in coverage["runs"]
                for document_id in run["statement_ids"]]
    assert len(assigned) == len(set(assigned))


def test_account_ledger_refuses_malformed_stale_cross_account_and_missing_identity():
    projection = Projection()
    first = read_ledger(projection, projection.ACCOUNT, "r1", limit=2)
    cursor = first["page"]["next_cursor"]

    with pytest.raises(AccountLedgerCursorError, match="malformed"):
        read_ledger(projection, projection.ACCOUNT, "r1", cursor="not-a-cursor")
    for suffix in ("!", " ", "\n", "="):
        with pytest.raises(AccountLedgerCursorError, match="malformed"):
            read_ledger(projection, projection.ACCOUNT, "r1",
                        cursor=cursor + suffix)
    padded = cursor + "=" * (-len(cursor) % 4)
    envelope = json.loads(base64.urlsafe_b64decode(padded).decode())
    alternative_encodings = (
        json.dumps(envelope, indent=2).encode("utf-8"),
        json.dumps({"mac": envelope["mac"], "body": envelope["body"]},
                   separators=(",", ":")).encode("utf-8"),
    )
    for raw in alternative_encodings:
        noncanonical = base64.urlsafe_b64encode(raw).decode().rstrip("=")
        with pytest.raises(AccountLedgerCursorError, match="malformed"):
            read_ledger(projection, projection.ACCOUNT, "r1",
                        cursor=noncanonical)
    with pytest.raises(AccountLedgerCursorError, match="stale"):
        read_ledger(projection, projection.ACCOUNT, "r2", cursor=cursor)
    with pytest.raises(AccountLedgerCursorError, match="another account"):
        read_ledger(projection, projection.OTHER, "r1", cursor=cursor)
    with pytest.raises(AccountLedgerIdentityError):
        read_ledger(projection, "acct:unknown", "r1")

    projection._infos[0] = SimpleNamespace(
        account=projection.ACCOUNT, name="", kind="depository",
        currency="USD", number="000000004417")
    with pytest.raises(AccountLedgerIdentityError):
        read_ledger(projection, projection.ACCOUNT, "r1")


def test_account_ledger_refuses_duplicate_stable_account_identity():
    projection = Projection()
    projection._infos.append(projection._infos[0])
    with pytest.raises(AccountLedgerIdentityError):
        read_ledger(projection, projection.ACCOUNT, "r1")


def test_account_ledger_refuses_an_unsupported_account_family():
    projection = Projection()
    projection._infos[0] = SimpleNamespace(
        account=projection.ACCOUNT, name="House", kind="asset",
        currency="USD", number="000000004417")
    with pytest.raises(AccountLedgerIdentityError):
        read_ledger(projection, projection.ACCOUNT, "r1")


def test_account_ledger_refuses_statement_projection_contaminated_by_another_account():
    projection = Projection()
    contaminated = list(projection._statements.records)
    contaminated[0] = StatementRecord(
        "jan", projection.OTHER, "2026-01-01", Decimal("100"),
        "2026-01-31", Decimal("200"))
    projection._statements.records = contaminated

    with pytest.raises(AccountLedgerIdentityError, match="another account"):
        read_ledger(projection, projection.ACCOUNT, "r1")


def test_account_ledger_refuses_evidence_document_owned_by_another_account():
    projection = Projection()
    projection._other_statements = AccountStatements(
        projection.OTHER,
        [StatementRecord("apr", projection.OTHER, "2026-04-01",
                         Decimal("50"), "2026-04-30", Decimal("60"))],
        [("2026-04-01", "2026-04-30")])
    with pytest.raises(AccountLedgerIdentityError, match="evidence belongs"):
        read_ledger(projection, projection.ACCOUNT, "r1")


def test_account_ledger_conservatively_deduplicates_only_exact_overlapping_postings():
    projection = Projection()
    projection._movements = [
        Movement("movement:exact-a", projection.ACCOUNT, "2026-02-20",
                 "Corner Market", "-10.00", "feb", 2),
        Movement("movement:exact-b", projection.ACCOUNT, "2026-02-20",
                 "Corner Market", "-10", "overlap", 4),
        Movement("movement:probable-a", projection.ACCOUNT, "2026-02-21",
                 "Metro Market", "-12", "feb", 2),
        Movement("movement:probable-b", projection.ACCOUNT, "2026-02-21",
                 "METRO MKT", "-12", "overlap", 4),
        Movement("movement:conflict-a", projection.ACCOUNT, "2026-02-22",
                 "Fuel", "-20", "feb", 2),
        Movement("movement:conflict-b", projection.ACCOUNT, "2026-02-22",
                 "Fuel", "-22", "overlap", 4),
        Movement("movement:far-a", projection.ACCOUNT, "2026-01-15",
                 "Same Merchant", "-8", "jan", 2),
        Movement("movement:far-b", projection.ACCOUNT, "2026-04-15",
                 "Same Merchant", "-8", "apr", 2),
    ]

    read = read_ledger(projection, projection.ACCOUNT, "dedup-revision")
    rows = [row for group in read["groups"] for row in group["movements"]]

    assert len(rows) == 7
    exact = next(row for row in rows if row["id"] == "movement:exact-a")
    assert exact["deduplication"] == {
        "state": "exact_duplicate",
        "canonical_movement_id": "movement:exact-a",
        "member_movement_ids": ["movement:exact-a", "movement:exact-b"],
    }
    assert {link["document_id"] for link in exact["evidence_links"]} == {
        "feb", "overlap"}
    assert {row["id"] for row in rows} >= {
        "movement:probable-a", "movement:probable-b",
        "movement:conflict-a", "movement:conflict-b",
        "movement:far-a", "movement:far-b",
    }
    dedup = read["reconciliation"]["overlap"]["deduplication"]
    assert dedup["state"] == "exact_duplicates_collapsed_with_unresolved_candidates"
    assert dedup["collapsed"] == [{
        "canonical_movement_id": "movement:exact-a",
        "member_movement_ids": ["movement:exact-a", "movement:exact-b"],
        "document_ids": ["feb", "overlap"],
    }]
    assert {(item["kind"], tuple(item["movement_ids"]))
            for item in dedup["unresolved"]} == {
        ("probable", ("movement:probable-a", "movement:probable-b")),
        ("conflicting", ("movement:conflict-a", "movement:conflict-b")),
    }


def test_account_ledger_does_not_collapse_matching_details_outside_overlap():
    projection = Projection()
    projection._movements = [
        Movement("movement:jan", projection.ACCOUNT, "2026-03-15",
                 "Same Merchant", "-8", "jan", 2),
        Movement("movement:apr", projection.ACCOUNT, "2026-03-15",
                 "Same Merchant", "-8", "apr", 2),
    ]
    rows = [row for group in read_ledger(
        projection, projection.ACCOUNT, "separate-periods")["groups"]
            for row in group["movements"]]
    assert {row["id"] for row in rows} == {"movement:jan", "movement:apr"}
    assert [row["deduplication"]["state"] for row in rows] == ["single", "single"]


@pytest.mark.parametrize("kind,amount,expected", [
    ("depository", "10", "current_balance"),
    ("investment", "-10", "current_balance"),
    ("liability", "10", "amount_owed"),
    ("liability", "0", "amount_owed"),
    ("liability", "-10", "current_balance"),
])
def test_account_ledger_balance_kind_is_authored_from_account_type_and_sign(
        kind, amount, expected):
    projection = Projection()
    projection._infos[0].kind = kind
    projection.balance = lambda _account: SimpleNamespace(
        amount=Decimal(amount), dated="2026-04-30", grade="corroborated",
        reconciliation=None)
    assert read_ledger(projection, projection.ACCOUNT, "balance-kind")[
        "account"]["balance"]["kind"] == expected


def test_opened_vault_read_binds_cursor_to_the_event_snapshot_and_allowlists_parameters(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    account = "acct:checking"
    vault.ledger.append(account_opened(
        account, "depository", "Everyday Checking", "USD", "2026-01-01",
        account_number="000000004417"))
    vault.ledger.append(opening_balance_observed(
        account, "100", "2026-01-01", Provenance()))
    vault.ledger.append(simple_transaction(
        account, "-5", "Cafe", "2026-01-02"))
    vault.ledger.append(simple_transaction(
        account, "-7", "Market", "2026-01-03"))
    provider = OpenedVaultSurfaceProvider(vault)

    first = provider.read_surface(
        "account_ledger", {"account_id": account, "limit": 1})
    cursor = first["page"]["next_cursor"]
    assert cursor

    # Recomputing the old public checksum after changing a cursor body does not
    # produce a valid MAC, and another opened-provider session has another key.
    padded = cursor + "=" * (-len(cursor) % 4)
    forged = json.loads(base64.urlsafe_b64decode(padded).decode())
    forged["body"]["after"]["movement_id"] = "forged-anchor"
    canonical = json.dumps(
        forged["body"], sort_keys=True, separators=(",", ":"))
    forged["mac"] = hashlib.sha256(canonical.encode()).hexdigest()
    tampered = base64.urlsafe_b64encode(json.dumps(
        forged, sort_keys=True, separators=(",", ":")).encode()).decode().rstrip("=")
    with pytest.raises(BridgeRequestError, match="malformed"):
        provider.read_surface(
            "account_ledger", {"account_id": account, "limit": 1,
                               "cursor": tampered})
    with pytest.raises(BridgeRequestError, match="malformed"):
        OpenedVaultSurfaceProvider(vault).read_surface(
            "account_ledger", {"account_id": account, "limit": 1,
                               "cursor": cursor})

    vault.ledger.append(simple_transaction(
        account, "-9", "Pharmacy", "2026-01-04"))
    with pytest.raises(BridgeRequestError, match="stale"):
        provider.read_surface(
            "account_ledger", {"account_id": account, "limit": 1,
                               "cursor": cursor})
    with pytest.raises(BridgeRequestError, match="do not accept fields"):
        provider.read_surface(
            "account_ledger", {"account_id": account, "as_of": "2026-01-03"})
    for invalid_limit in (0, -1, 101):
        with pytest.raises(BridgeRequestError, match="limit"):
            provider.read_surface(
                "account_ledger", {"account_id": account,
                                   "limit": invalid_limit})


def test_transaction_only_account_has_no_invented_balance(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    account = "acct:checking"
    vault.ledger.append(account_opened(
        account, "depository", "Everyday Checking", "USD", "2026-01-01",
        account_number="000000004417"))
    vault.ledger.append(simple_transaction(
        account, "-5", "Cafe", "2026-01-02"))

    read = OpenedVaultSurfaceProvider(vault).read_surface(
        "account_ledger", {"account_id": account})

    assert read["account"]["balance"] == {
        "state": "absent",
        "reason": "no_authoritative_balance_observation",
    }
    assert read["groups"][0]["movements"]
