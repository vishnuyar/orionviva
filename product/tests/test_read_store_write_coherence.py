"""Canonical commits and disposable read generations have one-way coupling."""
from pathlib import Path
import shutil

import pytest

from viva.ledger import account_opened, closing_balance_observed
from viva.read_store import ReadStoreDegraded
from viva.vault import Vault
from viva.ledger import store as event_store_module
from viva.crypto import CryptoError


PASSPHRASE = "correct horse battery staple"


def _event(amount: str = "10.00"):
    return closing_balance_observed("cash", amount, "2026-01-31")


def _source(vault: Vault) -> tuple[int, str]:
    with vault.read_store.open_reader() as revision:
        identity = vault.read_store.authenticated_source_identity(revision)
    return identity["count"], identity["head"]


def _assert_observer_operations_refused(
        outcomes: dict[str, tuple[str, type[BaseException] | None]],
        expected: set[str]) -> None:
    """Assert callback evidence outside the callback containment boundary."""
    assert set(outcomes) == expected
    assert all(outcome == ("exception", CryptoError)
               for outcome in outcomes.values())


def test_acknowledged_write_is_published_at_the_committed_event_identity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    assert vault.synchronize_read_store() in {"equal", "rebuilt"}
    synchronized_from = []
    real_synchronize = vault.read_store.synchronize

    def synchronize(source):
        synchronized_from.append(source)
        return real_synchronize(source)

    monkeypatch.setattr(vault.read_store, "synchronize", synchronize)
    vault.ledger.append(account_opened(
        "cash", "depository", "Cash", "USD", "2026-01-01"))

    assert synchronized_from == [vault._read_store_event_source]
    assert synchronized_from[0] is not vault.ledger.store
    assert vault.read_store_lifecycle in {"caught_up", "rebuilt"}
    assert _source(vault) == vault.ledger.store.authenticated_identity()[:2]


def test_projection_failure_after_commit_is_explicit_and_retry_never_replays(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.synchronize_read_store()
    before = vault.ledger.store.authenticated_identity()[0]
    real_synchronize = vault.read_store.synchronize
    monkeypatch.setattr(
        vault.read_store, "synchronize",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ReadStoreDegraded("synthetic SQL failure")))

    record = vault.ledger.append(_event())

    assert record["seq"] == before
    assert vault.ledger.store.authenticated_identity()[0] == before + 1
    assert vault.read_store_lifecycle == "stale"
    monkeypatch.setattr(vault.read_store, "synchronize", real_synchronize)
    assert vault.synchronize_read_store() == "caught_up"
    assert vault.ledger.store.authenticated_identity()[0] == before + 1
    assert _source(vault) == vault.ledger.store.authenticated_identity()[:2]


def test_source_advance_during_publication_is_reported_stale_then_caught_up(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.synchronize_read_store()
    external = vault.ledger.store.fork()
    real_synchronize = vault.read_store.synchronize
    advanced = False

    def race(*args, **kwargs):
        nonlocal advanced
        result = real_synchronize(*args, **kwargs)
        if not advanced:
            advanced = True
            external.append(_event("20.00"))
        return result

    monkeypatch.setattr(vault.read_store, "synchronize", race)
    vault.ledger.append(_event("15.00"))

    assert vault.read_store_lifecycle == "stale"
    monkeypatch.setattr(vault.read_store, "synchronize", real_synchronize)
    assert vault.synchronize_read_store() == "caught_up"
    assert _source(vault) == vault.ledger.store.authenticated_identity()[:2]


def test_event_commit_failure_never_invokes_projection_or_advances_truth(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    vault.synchronize_read_store()
    before = vault.ledger.store.authenticated_identity()
    generation = vault.read_store.current_generation
    observed = []
    vault.ledger.store.observe_commits(observed.append)

    def fail_head(*_args, **_kwargs):
        raise OSError("synthetic event-head interruption")

    monkeypatch.setattr(event_store_module, "write_head", fail_head)
    with pytest.raises(OSError, match="event-head interruption"):
        vault.ledger.append(_event())

    assert observed == []
    assert vault.ledger.store.authenticated_identity() == before
    assert vault.read_store.current_generation == generation


def test_post_commit_observer_failure_cannot_turn_success_into_write_failure(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    before = vault.ledger.store.authenticated_identity()[0]
    vault.ledger.store.observe_commits(
        lambda _identity: (_ for _ in ()).throw(RuntimeError("projection failed")))

    record = vault.ledger.append(_event())

    assert record["seq"] == before
    assert vault.ledger.store.authenticated_identity()[0] == before + 1


def test_post_commit_observer_cannot_append_or_notify_twice_for_a_batch(tmp_path: Path):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    store = vault.ledger.store
    calls = []
    outcomes: dict[str, tuple[str, type[BaseException] | None]] = {}

    operations = {
        "append": lambda: store.append(_event("99.00")),
        "atomic append": lambda: store.append_atomically(
            lambda _events: (_event("98.00"),)),
        "fork": store.fork,
        "observer mutation": lambda: store.observe_commits(None),
        "events": store.events,
        "event iteration": lambda: tuple(store.events()),
        "snapshot": store.snapshot_events,
        "snapshot with identity": store.snapshot_events_with_identity,
        "committed snapshot": store.committed_snapshot,
        "committed suffix": lambda: store.committed_suffix_after(None),
        "committed-log audit": store.verify_committed_log,
        "authenticated read": store.authenticated_identity,
        "chain verification": store.verify_chain,
        "len": lambda: len(store),
    }

    def observer(identity):
        calls.append(identity)
        for name, operation in operations.items():
            try:
                operation()
            except BaseException as exc:
                outcomes[name] = ("exception", type(exc))
            else:
                outcomes[name] = ("success", None)

    store.observe_commits(observer)
    records = store.append_atomically(lambda _events: (
        _event("10.00"), _event("20.00")))

    assert [record["seq"] for record in records] == [0, 1]
    assert len(calls) == 1
    _assert_observer_operations_refused(outcomes, set(operations))
    assert store.authenticated_identity()[0] == 2


def test_observer_refusal_evidence_rejects_an_unexpected_success():
    with pytest.raises(AssertionError):
        _assert_observer_operations_refused(
            {"append": ("exception", CryptoError),
             "authenticated read": ("success", None)},
            {"append", "authenticated read"})


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_post_commit_base_exception_cannot_make_a_committed_write_ambiguous(
        tmp_path: Path, interruption):
    vault = Vault.open(tmp_path / "vault", PASSPHRASE)
    store = vault.ledger.store
    calls = 0

    def interrupt(_identity):
        nonlocal calls
        calls += 1
        raise interruption("private observer detail")

    store.observe_commits(interrupt)
    record = store.append(_event())

    assert record["seq"] == 0
    assert calls == 1
    assert store.authenticated_identity()[0] == 1


def test_deleting_disposable_store_reconstructs_exact_canonical_revision(tmp_path: Path):
    directory = tmp_path / "vault"
    vault = Vault.open(directory, PASSPHRASE)
    vault.ledger.append(_event())
    canonical_before = {
        name: (directory / name).read_bytes()
        for name in ("events.jsonl", "events.jsonl.head")
    }
    vault.close()
    shutil.rmtree(directory / "read-model")

    reopened = Vault.open(directory, PASSPHRASE)
    assert reopened.synchronize_read_store() == "rebuilt"
    assert _source(reopened) == reopened.ledger.store.authenticated_identity()[:2]
    assert canonical_before == {
        name: (directory / name).read_bytes()
        for name in ("events.jsonl", "events.jsonl.head")
    }
