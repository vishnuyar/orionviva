"""Optimized preparation refuses changed ownership, source bytes and visibility."""
import json,time
import pytest
from test_unmanaged_revision_preparation import prepared_vault,custom_runtime
from viva.instrument_runtime import InstrumentRuntime,vault_revision_supplier
from viva.read_store import ReadStore,ReadStoreError
from viva.ledger.postings import simple_transaction


def test_same_head_same_size_physical_prefix_tampering_is_not_cached(prepared_vault):
    vault=prepared_vault;path=vault.ledger.store.path;before=path.read_bytes();head=path.with_suffix(path.suffix+'.head').read_bytes()
    lines=before.decode().splitlines(keepends=True)
    for i,line in enumerate(lines):
        record=json.loads(line)
        if 'sealed' in record:
            value=record['sealed']['ct'];record['sealed']['ct']=('B' if value[0]=='A' else 'A')+value[1:]
            lines[i]=json.dumps(record,ensure_ascii=False)+'\n';break
    changed=''.join(lines).encode();assert len(changed)==len(before);path.write_bytes(changed)
    assert path.with_suffix(path.suffix+'.head').read_bytes()==head
    runtime=InstrumentRuntime(vault_revision_supplier(vault))
    with runtime.execution(time.monotonic()+2):assert runtime.revision is None
    assert sum(vault.read_store._references.values())==0


def test_concurrent_append_during_sql_acquisition_refuses_and_releases(prepared_vault,monkeypatch):
    vault=prepared_vault;original=vault.read_store.authenticated_source_identity;changed=[]
    def append(revision):
        result=original(revision)
        if not changed:
            changed.append(True)
            vault.ledger.store.fork().append(simple_transaction('cash','1.00','Synthetic concurrent append','2025-01-31'))
        return result
    monkeypatch.setattr(vault.read_store,'authenticated_source_identity',append)
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('stale revision served')
    assert changed and sum(vault.read_store._references.values())==0


def test_visibility_changed_during_acquisition_stays_held(prepared_vault,monkeypatch):
    vault=prepared_vault;original=vault.read_store.authenticated_source_identity;serial=[]
    def fenced(revision):
        result=original(revision);serial.append(vault.hold_read_store_visibility());return result
    monkeypatch.setattr(vault.read_store,'authenticated_source_identity',fenced)
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('fenced revision served')
    assert vault.holds_read_store_visibility(serial[-1])
    assert sum(vault.read_store._references.values())==0


def test_mode_transition_during_native_sync_refuses(prepared_vault,monkeypatch):
    vault=prepared_vault;original=vault.read_store.synchronize
    def managed(source):
        result=original(source);vault._read_store_worker_managed=True;return result
    monkeypatch.setattr(vault.read_store,'synchronize',managed)
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('mode transition served')
    assert sum(vault.read_store._references.values())==0


def test_dead_managed_worker_uses_existing_fallback(prepared_vault,monkeypatch):
    vault=prepared_vault;vault._read_store_worker_managed=True;calls=[]
    def unavailable(*,timeout):calls.append(timeout);return False
    monkeypatch.setattr(vault,'wait_for_read_store',unavailable)
    runtime=InstrumentRuntime(vault_revision_supplier(vault))
    with runtime.execution(time.monotonic()+2):assert runtime.revision is None
    assert len(calls)==1


def test_changed_generation_after_authentication_refuses(prepared_vault,monkeypatch):
    from viva.ledger.store import EventStore
    vault=prepared_vault;original=EventStore.authenticated_identity;calls=[]
    def publish(store):
        result=original(store)
        if store is vault.ledger.store:
            calls.append(True)
            if len(calls)==2:
                with ReadStore.open(vault.read_store.directory,'synthetic-only') as other:
                    other.synchronize(vault._read_store_event_source,as_of_version='synthetic-generation-change')
        return result
    monkeypatch.setattr(EventStore,'authenticated_identity',publish)
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('superseded generation served')
    assert len(calls)==2 and sum(vault.read_store._references.values())==0


def test_foreign_same_count_source_fork_is_refused(prepared_vault,tmp_path):
    from viva.ledger import Ledger
    from viva.ledger.events import account_opened,opening_balance_observed,closing_balance_observed,Provenance
    vault=prepared_vault;foreign=Ledger.open(tmp_path/'other.jsonl','synthetic-only')
    foreign.append(account_opened('cash','depository','Other account','USD','2025-01-01'))
    foreign.append(opening_balance_observed('cash','900.00','2025-01-01',Provenance('other',1)))
    foreign.append(closing_balance_observed('cash','900.00','2025-01-31',Provenance('other',1)))
    assert foreign.store.authenticated_identity()[0]==vault.ledger.store.authenticated_identity()[0]
    vault._read_store_event_source=foreign.store.fork()
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('foreign owner served')
    assert sum(vault.read_store._references.values())==0


def test_failed_sql_authentication_releases_lease(prepared_vault,monkeypatch):
    vault=prepared_vault
    def invalid(revision):raise ReadStoreError('synthetic invalid generation')
    monkeypatch.setattr(vault.read_store,'authenticated_source_identity',invalid)
    with pytest.raises(ReadStoreError):
        with vault._owned_current_read_revision(deadline=time.monotonic()+2):pytest.fail('invalid SQL served')
    assert sum(vault.read_store._references.values())==0


def test_new_request_authenticates_again_and_does_not_inherit_expiry(prepared_vault,monkeypatch):
    from viva import instrument_runtime
    clock=[100.0];runtime=custom_runtime(prepared_vault)
    monkeypatch.setattr(instrument_runtime,'monotonic',lambda:clock[0])
    with runtime.execution(102.0):assert runtime.source_is_current()
    clock[0]=103.0;assert not runtime.source_is_current()
    clock[0]=200.0
    with runtime.execution(202.0):assert runtime.source_is_current()
    assert runtime.source_is_current()


def test_managed_eligibility_never_takes_visibility_lock(prepared_vault):
    vault = prepared_vault
    original = vault._read_store_visibility_lock
    class VisibilityMustNotBeAcquired:
        def __enter__(self):
            pytest.fail("managed eligibility inverted the worker/visibility lock order")
        def __exit__(self, *args):
            return False
    vault._read_store_worker_managed = True
    vault._read_store_visibility_lock = VisibilityMustNotBeAcquired()
    try:
        assert not vault._can_open_current_revision()
    finally:
        vault._read_store_visibility_lock = original
