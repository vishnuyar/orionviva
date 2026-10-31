"""Import publication coalesces durable events without changing their authority."""
import pytest
from threading import Event, Thread

from viva.ledger import account_opened, closing_balance_observed
from viva.read_store import ReadStoreDegraded
from viva.vault import Vault


def test_document_scope_publishes_once_and_keeps_prior_revision_immutable(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-publication-test')
    vault.synchronize_read_store()
    before = vault.read_store.current_generation
    calls = []
    synchronize = vault.read_store.synchronize

    def observed(source):
        calls.append(source)
        return synchronize(source)

    monkeypatch.setattr(vault.read_store, 'synchronize', observed)
    with vault.defer_read_store_updates():
        vault.ledger.append(account_opened('cash', 'depository', 'Cash', 'USD', '2026-01-01'))
        with vault.defer_read_store_updates():
            vault.ledger.append(closing_balance_observed('cash', '15.00', '2026-01-31'))
        assert calls == []
        assert vault.read_store.current_generation == before
        assert vault.read_store_lifecycle == 'stale'
        assert vault.ledger.store.authenticated_identity()[0] == 2
    assert len(calls) == 1
    with vault.read_store.open_reader() as revision:
        source = vault.read_store.authenticated_source_identity(revision)
    assert (source['count'], source['head']) == vault.ledger.store.authenticated_identity()[:2]
    vault.close()


def test_failed_import_scope_retains_durable_events_and_releases_publication(tmp_path):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-publication-test')
    with pytest.raises(ValueError, match='synthetic interruption'):
        with vault.defer_read_store_updates():
            vault.ledger.append(account_opened('cash', 'depository', 'Cash', 'USD', '2026-01-01'))
            raise ValueError('synthetic interruption')
    with vault.read_store.open_reader() as revision:
        source = vault.read_store.authenticated_source_identity(revision)
    assert source['count'] == 1
    vault.ledger.append(closing_balance_observed('cash', '15.00', '2026-01-31'))
    assert vault.read_store_lifecycle in {'caught_up', 'rebuilt'}
    vault.close()


def test_publication_failure_does_not_change_canonical_success(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-publication-test')
    vault.synchronize_read_store()
    synchronize = vault.read_store.synchronize

    def unavailable(_source):
        raise ReadStoreDegraded('synthetic publication unavailable')

    monkeypatch.setattr(vault.read_store, 'synchronize', unavailable)
    with vault.defer_read_store_updates():
        vault.ledger.append(account_opened('cash', 'depository', 'Cash', 'USD', '2026-01-01'))
    assert vault.ledger.store.authenticated_identity()[0] == 1
    assert vault.read_store_lifecycle == 'stale'
    monkeypatch.setattr(vault.read_store, 'synchronize', synchronize)
    assert vault.synchronize_read_store() == 'caught_up'
    vault.close()


def test_deferred_publication_does_not_invert_ledger_writer_lock_order(tmp_path):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-publication-test')
    scope_entered, observer_entered = Event(), Event()
    observer = vault._after_canonical_commit
    errors = []

    def observed(identity):
        observer_entered.set()
        observer(identity)

    vault.ledger.store.observe_commits(observed)

    def scoped_writer():
        try:
            with vault.defer_read_store_updates():
                scope_entered.set()
                assert observer_entered.wait(3)
                vault.ledger.append(account_opened('scoped', 'depository', 'Scoped', 'USD', '2026-01-01'))
        except BaseException as error:
            errors.append(error)

    def other_writer():
        try:
            assert scope_entered.wait(3)
            vault.ledger.append(account_opened('other', 'depository', 'Other', 'USD', '2026-01-01'))
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=target, daemon=True) for target in (scoped_writer, other_writer)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(4)
    assert not any(thread.is_alive() for thread in threads), 'publication and writer locks deadlocked'
    assert not errors
    assert vault.ledger.projection().accounts() == vault.ledger.fresh_projection().accounts()
    assert vault.ledger.store.authenticated_identity()[0] == 2
    vault.close()
