"""Executable legacy and reconstruction boundaries for ordinary SQL work."""
import importlib
from decimal import localcontext

import pytest

from viva.sql_authority import SQLAuthority
from test_sql_authority_bank import ingest

pytestmark = pytest.mark.production_kdf


def test_real_legacy_execution_traps_fail_controls_and_allow_sql_path(tmp_path, monkeypatch):
    ledger = importlib.import_module("viva.ledger.ledger")
    events = importlib.import_module("viva.ledger.store")
    projection = importlib.import_module("viva.ledger.projection")
    pipeline = importlib.import_module("viva.ingest.pipeline")
    projector = importlib.import_module("viva.ingest.statement_projector")
    def forbidden(*_args, **_kwargs):
        raise AssertionError("legacy financial execution forbidden")
    targets = [(ledger.Ledger, "__init__"), (events.EventStore, "__init__"),
               (projection.LedgerProjection, "__init__"), (pipeline, "_settle_read"),
               (projector, "post_statement"), (projector, "heal_gaps"),
               (projector, "heal_corroboration")]
    for owner, name in targets:
        monkeypatch.setattr(owner, name, forbidden)
        with pytest.raises(AssertionError, match="legacy financial"):
            getattr(owner, name)()
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        monkeypatch.setattr(store, "_reconstruct", forbidden)
        monkeypatch.setattr(store, "export_audit", forbidden)
        first = ingest(store)
        second = ingest(store, b"synthetic next source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
        assert first.status == second.status == "accepted"
        assert store.account(first.account_id)["running_balance"] == "80"
        assert len(store.transactions(first.account_id)) == 2
        assert store.postings(second.doc_id)
        assert store.receipt(second.doc_id)
        assert store.original(second.doc_id)
        assert store.last_vm_steps > 0
        assert all("WHERE" in query for query in store.last_queries)


def test_arithmetic_does_not_inherit_low_precision_from_caller(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        with localcontext() as arithmetic:
            arithmetic.prec = 2
            result = ingest(store, opening="100.123", closing="90.122", movement="-10.001")
        assert result.status == "accepted"
        assert store.account(result.account_id)["running_balance"] == "90.122"
        assert [row["amount"] for row in store.postings(result.doc_id)] == ["-10.001", "10.001"]
