"""A scoped read keeps genuine prefix checks inside its finite preparation budget."""
from contextlib import contextmanager
import time
import pytest
from viva.vault import Vault
from viva.ledger.events import account_opened, opening_balance_observed, closing_balance_observed, Provenance
from viva.instrument_runtime import InstrumentRuntime, vault_revision_supplier


@pytest.fixture
def prepared_vault(tmp_path):
    vault=Vault.open(tmp_path/'vault','synthetic-only',start_read_store_worker=False)
    try:
        vault.ledger.append(account_opened('cash','depository','Synthetic account','USD','2025-01-01'))
        vault.ledger.append(opening_balance_observed('cash','100.00','2025-01-01',Provenance('synthetic-source',1)))
        vault.ledger.append(closing_balance_observed('cash','100.00','2025-01-31',Provenance('synthetic-source',1)))
        vault.synchronize_read_store();vault.ledger.projection()
        yield vault
    finally:vault.close()


def test_unmanaged_preparation_uses_one_primary_physical_identity_pair(prepared_vault,monkeypatch):
    from viva.ledger.store import EventStore
    vault=prepared_vault;original=EventStore.authenticated_identity;calls=[]
    def authenticated(store):
        calls.append(store);return original(store)
    monkeypatch.setattr(EventStore,'authenticated_identity',authenticated)
    with vault_revision_supplier(vault)(deadline=time.monotonic()+2) as revision:
        identity=vault.read_store.authenticated_source_identity(revision)
        assert (identity['count'],identity['head'])==original(vault.ledger.store)[:2]
        assert revision._store is vault.read_store and not revision._closed
        assert len(calls)==2
        assert all(store is vault.ledger.store for store in calls)


def custom_runtime(vault):
    @contextmanager
    def supplier():
        with vault.read_store.open_reader() as revision:yield revision
    supplier.source_identity=vault.ledger.store.authenticated_identity
    supplier.expected_projection_identity=vault.ledger.store.authenticated_identity()
    return InstrumentRuntime(supplier)


def test_source_check_refuses_expiry_during_genuine_final_authentication(prepared_vault,monkeypatch):
    from viva import instrument_runtime
    runtime=custom_runtime(prepared_vault);clock=[100.0]
    monkeypatch.setattr(instrument_runtime,'monotonic',lambda:clock[0])
    authenticate=runtime.supplier.source_identity
    def expires():
        result=authenticate();clock[0]=103.0;return result
    runtime.supplier.source_identity=expires
    with runtime.execution(102.0):
        assert runtime.revision is not None
        assert runtime.source_is_current() is False


def test_completed_execution_keeps_original_deadline_for_delivery(prepared_vault,monkeypatch):
    from viva import instrument_runtime
    runtime=custom_runtime(prepared_vault);clock=[100.0]
    monkeypatch.setattr(instrument_runtime,'monotonic',lambda:clock[0])
    with runtime.execution(102.0):assert runtime.revision is not None
    assert runtime.deadline is None
    clock[0]=103.0
    assert runtime.source_is_current() is False
