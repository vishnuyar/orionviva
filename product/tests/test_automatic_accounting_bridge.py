"""Synthetic bridge corrections refresh exact report revisions and undo receipts."""
import json

import pytest

from viva import engine
from viva.desktop_bridge import dispatch_frame, handlers_for_opened_vault
from viva.ledger import Posting, Provenance
from viva.ledger.events import account_opened, transaction_recorded
from viva.ledger.accounting import financial_statements
from viva.vault import Vault


def send(handlers, operation, payload):
    response = json.loads(dispatch_frame(json.dumps({"protocol": "2.0", "request_id": "synthetic",
        "operation": operation, "payload": payload}), handlers))
    assert response["ok"], response
    return response["result"]


def test_selected_correction_report_reload_and_undo_are_sql_canonical_identical(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "synthetic", "synthetic")
    vault.ledger.append(account_opened("cash", "depository", "Example account", "USD", "2026-01-01"))
    vault.ledger.append(transaction_recorded([Posting("cash", "-15", "verified"),
        Posting("Expenses:Uncategorized", "15", "verified")], "Example equipment", "2026-01-05",
        provenance=Provenance(doc_id="synthetic-statement")))
    selected = vault.ledger.projection().movements()[0].key
    monkeypatch.setattr(engine, "_interpreter", lambda: lambda _prompt: json.dumps({
        "legs": [{"major": "asset", "account_hint": "Example equipment"}], "future_scope": "one"}))
    handlers = handlers_for_opened_vault(vault).handlers
    correction = send(handlers, "viva.conversation.ask", {"question": "This bought my equipment",
        "movement_ids": [selected]})
    assert correction["kind"] == "completed"
    assert correction["state"]["accounting_correction"]["movement_ids"] == [selected]
    correction_id = correction["state"]["accounting_correction"]["id"]
    assert financial_statements(vault.ledger.projection())["profit_loss"]["lines"] == []
    undo = send(handlers, "viva.conversation.ask", {"question": "Undo", "undo_correction_id": correction_id})
    assert undo["kind"] == "completed"
    vault.synchronize_read_store()
    expected = financial_statements(vault.ledger.fresh_projection(), end="2026-01-31")
    with vault.read_store.open_reader() as revision:
        assert financial_statements(revision.overview_projection(today="2026-01-31"), end="2026-01-31") == expected
        assert financial_statements(revision.historical_overview_projection(as_of="2026-01-31", today="2026-01-31"), end="2026-01-31") == financial_statements(vault.ledger.projection_as_of("2026-01-31"), end="2026-01-31")
    report = send(handlers, "viva.surface.read", {"surface": "accounting", "parameters": {
        "start": "2026-01-01", "end": "2026-01-31"}})["data"]
    assert report["profit_loss"]["by_currency"]["USD"]["expenses"] == "15"
    assert report["profit_loss"]["start"] == "2026-01-01"


@pytest.mark.parametrize("parameters", [{"start": "20260101"}, {"end": "bad"},
    {"start": "2026-03-01", "end": "2026-01-01"}])
def test_report_period_rejects_invalid_or_reversed_dates(tmp_path, parameters):
    vault = Vault.open(tmp_path / "synthetic", "synthetic")
    handlers = handlers_for_opened_vault(vault).handlers
    response = json.loads(dispatch_frame(json.dumps({"protocol": "2.0", "request_id": "synthetic",
        "operation": "viva.surface.read", "payload": {"surface": "accounting", "parameters": parameters}}), handlers))
    assert not response["ok"]


@pytest.mark.parametrize("later_major", ["asset", "expense"])
def test_chained_correction_undo_preserves_later_decision_and_sql_reports(tmp_path, monkeypatch, later_major):
    vault = Vault.open(tmp_path / "synthetic", "synthetic")
    vault.ledger.append(account_opened("cash", "depository", "Example account", "USD", "2026-01-01"))
    vault.ledger.append(transaction_recorded([Posting("cash", "-15", "verified"),
        Posting("Expenses:Uncategorized", "15", "verified")], "Example purchase", "2026-01-05"))
    selected = vault.ledger.projection().movements()[0].key
    initial = financial_statements(vault.ledger.fresh_projection(), end="2026-01-31")
    handlers = handlers_for_opened_vault(vault).handlers
    ids = []
    for major in ("asset", later_major):
        monkeypatch.setattr(engine, "_interpreter", lambda major=major: lambda _prompt: json.dumps({
            "legs": [{"major": major, "account_hint": "Example equipment"}], "future_scope": "one"}))
        outcome = send(handlers, "viva.conversation.ask", {"question": "This bought my equipment", "movement_ids": [selected]})
        ids.append(outcome["state"]["accounting_correction"]["id"])
    latest = financial_statements(vault.ledger.fresh_projection(), end="2026-01-31")
    for index, identity in enumerate(ids):
        send(handlers, "viva.conversation.ask", {"question": "Undo", "undo_correction_id": identity})
        expected = latest if index == 0 else initial
        assert financial_statements(vault.ledger.fresh_projection(), end="2026-01-31") == expected
        vault.synchronize_read_store()
        with vault.read_store.open_reader() as revision:
            assert financial_statements(revision.overview_projection(today="2026-01-31"), end="2026-01-31") == expected
