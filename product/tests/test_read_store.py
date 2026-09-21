from __future__ import annotations

import base64
import json
import os
import sqlite3
import stat
import threading
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from viva.crypto import (KdfParams, SALT_LEN, SCRYPT_N, SCRYPT_P, SCRYPT_R,
                         derive_key, new_vault_header)
from viva.ledger import EventStore, account_opened, simple_transaction
from viva.read_store import (ReadStore, ReadStoreBusy, ReadStoreDegraded,
                             ReadStoreError, assert_sqlcipher_runtime)
from viva.read_store import store as module
from viva.read_store.store import CHECK_TOKEN, METADATA_VERSION

PASSPHRASE = "correct horse battery staple"


def test_runtime_create_publish_and_reopen(tmp_path: Path):
    assert assert_sqlcipher_runtime()
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as store:
        first = store.current_generation
        second = store.publish(lambda db: (
            db.execute("CREATE TABLE sample(value TEXT NOT NULL)"),
            db.execute("INSERT INTO sample VALUES('new')")))
        assert first != second
        with store.open_reader() as reader:
            assert reader.generation == second
            assert reader.connection.execute("SELECT value FROM sample").fetchone() == ("new",)
            with pytest.raises(Exception):
                reader.connection.execute("DELETE FROM sample")

    with ReadStore.open(root, PASSPHRASE) as reopened:
        assert reopened.current_generation == second
        with reopened.open_reader() as reader:
            assert reader.connection.execute("SELECT value FROM sample").fetchone() == ("new",)


def _event_store(tmp_path: Path) -> EventStore:
    store = EventStore.open(tmp_path / "events.jsonl", PASSPHRASE)
    store.append(account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01"))
    return store


def _three_event_store(tmp_path: Path) -> EventStore:
    store = _event_store(tmp_path)
    store.append(simple_transaction("checking", "-2", "coffee", "2026-01-02"))
    store.append(simple_transaction("checking", "-3", "lunch", "2026-01-03"))
    return store


def test_incremental_control_rebuild_catch_up_restart_and_external_writer(tmp_path: Path):
    events = _event_store(tmp_path)
    root = tmp_path / "read-model"
    applied = []
    with ReadStore.create(root, PASSPHRASE) as reads:
        first = reads.synchronize(events, lambda _db, item: applied.append(item.sequence))
        # A blank read store has no EventStore-authenticated genesis cursor;
        # its first synchronization is therefore a rebuild-only bootstrap.
        assert (first.state, first.applied_count, applied) == ("rebuilt", 1, [0])
        assert reads.synchronize(events).state == "equal"

        external = EventStore.open(events.path, PASSPHRASE)
        external.append(simple_transaction(
            "checking", "-2", "coffee", "2026-01-02"))
        caught_up = reads.synchronize(events)
        assert (caught_up.state, caught_up.applied_count) == ("caught_up", 1)

    with ReadStore.open(root, PASSPHRASE) as reopened:
        assert reopened.synchronize(EventStore.open(events.path, PASSPHRASE)).state == "equal"
        with reopened.open_reader() as reader:
            assert reader.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == [(0,), (1,)]


def test_ahead_divergent_corrupt_and_unsupported_control_rebuild(tmp_path: Path):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)

        def make_ahead(db):
            db.execute("INSERT INTO applied_events VALUES(1, ?, ?, ?)",
                       ("synthetic-ahead", "f" * 64, "CorrectionApplied"))
            db.execute("UPDATE projection_meta SET source_count=2, source_head=?, "
                       "last_sequence=1, last_hash=?", ("f" * 64, "f" * 64))
        reads.publish(make_ahead, copy_current=True)
        assert reads.synchronize(events).state == "rebuilt"

        def erase_mapping(db):
            # Remove normalized dependants first: the schema now rejects an
            # orphaned projection instead of permitting the test to create one.
            for table in ("movement_tags", "movements", "transfer_links",
                          "transfer_suggestions", "transfer_history", "category_history",
                          "merchant_history", "tag_history", "ruling_history",
                          "account_alias_history", "event_provenance",
                          "account_names", "transaction_tags", "postings", "accounts",
                          "balance_observations", "transactions", "positions", "documents",
                          "account_entities", "applied_events"):
                db.execute(f"DELETE FROM {table}")
        reads.publish(erase_mapping, copy_current=True)
        assert reads.synchronize(events).state == "rebuilt"
        assert reads.synchronize(events, projector_version="control-v4").state == "rebuilt"


@pytest.mark.parametrize("event_id", ["", "   "])
def test_blank_applied_event_id_forces_rebuild(tmp_path: Path, event_id: str):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)
        reads.publish(
            lambda db: db.execute(
                "UPDATE applied_events SET event_id=? WHERE sequence=0",
                (event_id,)),
            copy_current=True)

        assert reads.synchronize(events).state == "rebuilt"
        with reads.open_reader() as reader:
            restored = reader.connection.execute(
                "SELECT event_id FROM applied_events WHERE sequence=0"
            ).fetchone()[0]
            assert restored and restored.strip()


@pytest.mark.parametrize("mutation", ["valid_event_id", "nonterminal_hash", "row_reorder"])
def test_ordered_mapping_digest_forces_rebuild_for_plausible_row_tampering(
        tmp_path: Path, mutation: str):
    events = _three_event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)

        def tamper(db):
            if mutation == "valid_event_id":
                db.execute("UPDATE applied_events SET event_id=? WHERE sequence=0",
                           ("11111111-2222-4333-8444-555555555555",))
            elif mutation == "nonterminal_hash":
                db.execute("UPDATE applied_events SET record_hash=? WHERE sequence=0",
                           ("f" * 64,))
            else:
                first, second = db.execute(
                    "SELECT event_id, record_hash FROM applied_events "
                    "WHERE sequence IN (0, 1) ORDER BY sequence").fetchall()
                db.execute("UPDATE applied_events SET event_id=?, record_hash=? WHERE sequence=0",
                           ("temporary-event-id", "e" * 64))
                db.execute("UPDATE applied_events SET event_id=?, record_hash=? WHERE sequence=1",
                           first)
                db.execute("UPDATE applied_events SET event_id=?, record_hash=? WHERE sequence=0",
                           second)

        reads.publish(tamper, copy_current=True)
        assert reads.synchronize(events).state == "rebuilt"
        with reads.open_reader() as reader:
            rows = reader.connection.execute(
                "SELECT sequence, event_id, record_hash FROM applied_events ORDER BY sequence"
            ).fetchall()
        snapshot = events.committed_snapshot()
        assert rows == [(entry.sequence, entry.event_id, entry.record_hash)
                        for entry in snapshot.events]


def test_mapping_digest_continues_across_authenticated_suffix(tmp_path: Path):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)
        with reads.open_reader() as reader:
            before = reader.connection.execute(
                "SELECT applied_events_digest FROM projection_meta").fetchone()[0]
            first = reader.connection.execute(
                "SELECT sequence, event_id, record_hash, event_type FROM applied_events").fetchone()
        assert before == module._extend_applied_events_digest(
            module._applied_events_genesis(module.CONTROL_SCHEMA_VERSION,
                                           module.PROJECTOR_VERSION), *first)

        events.append(simple_transaction("checking", "-2", "coffee", "2026-01-02"))
        assert reads.synchronize(events).state == "caught_up"
        with reads.open_reader() as reader:
            rows = reader.connection.execute(
                "SELECT sequence, event_id, record_hash, event_type FROM applied_events ORDER BY sequence"
            ).fetchall()
            stored = reader.connection.execute(
                "SELECT applied_events_digest FROM projection_meta").fetchone()[0]
        expected = module._applied_events_genesis(module.CONTROL_SCHEMA_VERSION,
                                                  module.PROJECTOR_VERSION)
        for row in rows:
            expected = module._extend_applied_events_digest(expected, *row)
        assert stored == expected


@pytest.mark.parametrize("mutation", ["duplicate_event_id", "duplicate_hash", "gap"])
def test_applied_event_identity_violations_are_transactional(tmp_path, mutation):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)
        before = reads.current_generation

        def violate(db):
            row = db.execute(
                "SELECT event_id, record_hash FROM applied_events WHERE sequence=0"
            ).fetchone()
            if mutation == "duplicate_event_id":
                db.execute("INSERT INTO applied_events VALUES(1, ?, ?, ?)",
                           (row[0], "f" * 64, "CorrectionApplied"))
            elif mutation == "duplicate_hash":
                db.execute("INSERT INTO applied_events VALUES(1, ?, ?, ?)",
                           ("different-event", row[1], "CorrectionApplied"))
            else:
                identity = SimpleNamespace(
                    count=2, head_hash="f" * 64, end_offset=1,
                    cursor_mac="e" * 64)
                reads._apply_committed_events(
                    db, (SimpleNamespace(sequence=2, event_id="gap-event",
                                         record_hash="f" * 64),), identity,
                    (3, "control-v3", "resolver-v1", "as-of-v1",
                     METADATA_VERSION), None, None, "0" * 64, ())

        with pytest.raises(Exception):
            reads.publish(violate, copy_current=True)
        assert reads.current_generation == before


def test_legacy_control_schema_rebuilds_instead_of_partial_migration(tmp_path):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)

        def install_old_schema(db):
            # Normalized children prevent reshaping their
            # applied-event parent into an orphan-producing legacy table.
            # The persisted schema identity alone is the rebuild contract.
            db.execute("UPDATE projection_meta SET schema_version=1")
            rows = tuple(db.execute(
                "SELECT institution, account_kind, profile_json "
                "FROM resolver_profiles ORDER BY institution, account_kind"
            ).fetchall())
            db.execute(
                "UPDATE projection_meta SET resolver_content_hash=?",
                (module._resolver_snapshot_hash(rows, schema_version=1),))

        reads.publish(install_old_schema, copy_current=True)
        assert reads.synchronize(events).state == "rebuilt"
        with reads.open_reader() as reader:
            columns = [row[1] for row in reader.connection.execute(
                "PRAGMA table_info(applied_events)")]
            assert columns == ["sequence", "event_id", "record_hash", "event_type"]


def test_physically_corrupt_current_generation_opens_only_for_authenticated_rebuild(
        tmp_path: Path):
    events = _event_store(tmp_path)
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(events)
        database = root / "generations" / reads.current_generation / "projection.db"
    content = bytearray(database.read_bytes())
    content[:64] = b"x" * 64
    database.write_bytes(content)

    with pytest.raises(ReadStoreError):
        ReadStore.open(root, PASSPHRASE)
    with ReadStore.open_for_recovery(root, PASSPHRASE) as recovering:
        assert recovering.synchronize(events).state == "rebuilt"
        assert recovering.synchronize(events).state == "equal"


@pytest.mark.parametrize("boundary", [
    "before_event_rows", "during_event_rows", "before_metadata_advance",
    "after_metadata_advance", "after_mapping_digest_advance", "after_database_commit",
])
def test_projection_failure_never_replays_event_write_or_publishes_stale_as_current(
        tmp_path: Path, boundary: str):
    events = _event_store(tmp_path)
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as reads:
        reads.synchronize(events)
        old = reads.current_generation
        events.append(simple_transaction(
            "checking", "-3", "lunch", "2026-01-03"))
        committed = events.committed_snapshot().identity

        with pytest.raises(ReadStoreDegraded, match="degraded"):
            reads.synchronize(events, fail_at=boundary)
        assert reads.current_generation == old
        assert events.committed_snapshot().identity == committed
        assert reads.synchronize(events).applied_count == 1
        assert events.committed_snapshot().identity == committed


@pytest.mark.parametrize("boundary", [
    "before_event_rows", "during_event_rows", "before_metadata_advance",
    "after_metadata_advance", "after_database_commit",
])
def test_version_rebuild_interruption_retains_old_reader_and_recovers_once(
        tmp_path: Path, boundary: str):
    events = _three_event_store(tmp_path)
    root = tmp_path / "read-model"
    next_version = module.PROJECTOR_VERSION + "-synthetic-next"
    source = events.committed_snapshot().identity
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(events)
        old = reads.current_generation
        with reads.open_reader() as held:
            old_rows = held.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall()
            with pytest.raises(ReadStoreDegraded):
                reads.synchronize(events, projector_version=next_version,
                                  fail_at=boundary)
            assert reads.current_generation == old
            assert held.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == old_rows
            assert events.committed_snapshot().identity == source
            result = reads.synchronize(events, projector_version=next_version)
            assert (result.state, result.applied_count) == ("rebuilt", source.count)
            assert reads.current_generation != old
            assert held.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == old_rows
            assert reads.synchronize(events, projector_version=next_version).state == "equal"
            assert events.committed_snapshot().identity == source
        with reads.open_reader() as current:
            assert current.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == old_rows


@pytest.mark.parametrize("boundary,committed_count", [
    ("before_head", 1), ("during_batch", 1), ("after_head", 3),
])
def test_ambiguous_event_batch_is_resolved_from_canonical_head_before_sql_sync(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        boundary: str, committed_count: int):
    events = _event_store(tmp_path)
    ledger_module = import_module("viva.ledger.store")
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as reads:
        reads.synchronize(events)
        old = reads.current_generation
        with reads.open_reader() as held:
            original_head = ledger_module.write_head
            original_batch = ledger_module._write_batch

            def interrupted_head(*args, **kwargs):
                if boundary == "after_head":
                    original_head(*args, **kwargs)
                raise OSError("synthetic event acknowledgement lost")

            def interrupted_batch(stream, content):
                first = content.splitlines(keepends=True)[0]
                stream.write(first)
                stream.flush()
                raise OSError("synthetic event acknowledgement lost")

            if boundary == "during_batch":
                monkeypatch.setattr(ledger_module, "_write_batch", interrupted_batch)
            else:
                monkeypatch.setattr(ledger_module, "write_head", interrupted_head)
            with pytest.raises(OSError, match="acknowledgement lost"):
                events.append_atomically(lambda _before: (
                    simple_transaction("checking", "-2", "coffee", "2026-01-02"),
                    simple_transaction("checking", "-3", "lunch", "2026-01-03"),
                ))
            monkeypatch.setattr(ledger_module, "write_head", original_head)
            monkeypatch.setattr(ledger_module, "_write_batch", original_batch)

            reopened = EventStore.open(events.path, PASSPHRASE)
            committed = reopened.committed_snapshot()
            assert committed.identity.count == committed_count
            assert [item.sequence for item in committed.events] == list(range(committed_count))
            assert reads.current_generation == old
            assert held.connection.execute(
                "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == [(0,)]
            result = reads.synchronize(reopened)
            assert result.state == ("caught_up" if committed_count == 3 else "equal")
            assert result.applied_count == committed_count - 1
            assert reads.synchronize(reopened).state == "equal"
            assert reopened.committed_snapshot().identity == committed.identity
            with reads.open_reader() as current:
                assert current.connection.execute(
                    "SELECT sequence FROM applied_events ORDER BY sequence").fetchall() == [
                        (sequence,) for sequence in range(committed_count)]


def test_required_connection_settings_and_projection_metadata(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        with store.open_reader() as reader:
            expected = {"cipher_plaintext_header_size": 0, "temp_store": 2,
                        "journal_mode": "delete", "synchronous": 2,
                        "foreign_keys": 1, "trusted_schema": 0,
                        "busy_timeout": 5000, "query_only": 1}
            for name, value in expected.items():
                found = reader.connection.execute(f"PRAGMA {name}").fetchone()[0]
                if isinstance(value, int): found = int(found)
                assert found == value
            assert reader.connection.execute(
                "SELECT schema_version, projector_version, resolver_version, "
                "as_of_version, key_derivation_version, "
                "source_count, source_head, last_sequence, last_hash, "
                "applied_events_digest, state "
                "FROM projection_meta").fetchone() == (
                    module.CONTROL_SCHEMA_VERSION, module.PROJECTOR_VERSION,
                    "resolver-v1", "as-of-v1",
                    METADATA_VERSION, 0, "0" * 64, -1, "0" * 64,
                    module._applied_events_genesis(module.CONTROL_SCHEMA_VERSION,
                                                   module.PROJECTOR_VERSION), "ready")


def test_wrong_passphrase_and_authenticated_manifest_tampering_refuse(tmp_path: Path):
    root = tmp_path / "read-model"
    ReadStore.create(root, PASSPHRASE).close()
    with pytest.raises(ReadStoreError, match="authentication failed"):
        ReadStore.open(root, "wrong horse battery staple")

    manifest_path = root / "current.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["generation"] = "g-" + "0" * 32
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ReadStoreError, match="manifest authentication failed"):
        ReadStore.open(root, PASSPHRASE)


def test_authenticated_manifest_replay_is_refused_while_coordinator_has_anchor(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        old = (store.directory / "current.json").read_bytes()
        store.publish()
        (store.directory / "current.json").write_bytes(old)
        with pytest.raises(ReadStoreError, match="rollback detected"):
            _ = store.current_generation


def test_manifest_is_bound_to_database_source_identity_and_epoch(tmp_path: Path):
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as store:
        manifest = json.loads((root / "current.json").read_text())
        database = root / "generations" / manifest["generation"] / "projection.db"
        connection = module._connect(database, store._database_key)
        connection.execute("UPDATE projection_meta SET source_head='different'")
        connection.commit(); connection.close()
    with pytest.raises(ReadStoreError, match="does not match its source revision"):
        ReadStore.open(root, PASSPHRASE)


def test_manifest_is_bound_to_database_mapping_digest(tmp_path: Path):
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as store:
        manifest = json.loads((root / "current.json").read_text())
        database = root / "generations" / manifest["generation"] / "projection.db"
        connection = module._connect(database, store._database_key)
        connection.execute("UPDATE projection_meta SET applied_events_digest=?",
                           ("f" * 64,))
        connection.commit(); connection.close()
    with pytest.raises(ReadStoreError, match="does not match its source revision"):
        ReadStore.open(root, PASSPHRASE)


def test_recovery_rejects_ambiguous_authenticated_temporaries(tmp_path: Path):
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as store:
        first = root / "current.json"
        first_generation, first_bytes = store.current_generation, first.read_bytes()
        second_generation = store.publish()
        one = root / f"current.{first_generation}.tmp"
        one.write_bytes(first_bytes)
        two = root / f"current.{second_generation}.tmp"
        two.write_bytes((root / "current.json").read_bytes())
        first.unlink()
        with pytest.raises(ReadStoreError, match="recovery is ambiguous"):
            store._current_manifest(recover=True)


@pytest.mark.parametrize("damage", ["corrupt", "unknown_identity"])
def test_corrupt_or_incompatible_current_generation_is_never_trusted(
        tmp_path: Path, damage: str):
    root = tmp_path / "read-model"
    store = ReadStore.create(root, PASSPHRASE)
    database = root / "generations" / store.current_generation / "projection.db"
    if damage == "corrupt":
        store.close()
        content = bytearray(database.read_bytes())
        content[:64] = b"x" * 64
        database.write_bytes(content)
    else:
        connection = module._connect(database, store._database_key)
        connection.execute("UPDATE read_store_identity SET format_version='unknown'")
        connection.commit(); connection.close(); store.close()
    with pytest.raises(ReadStoreError):
        ReadStore.open(root, PASSPHRASE)


def test_missing_manifest_recovers_only_authenticated_ready_temporary(tmp_path: Path):
    root = tmp_path / "read-model"
    store = ReadStore.create(root, PASSPHRASE)
    generation = store.current_generation
    current = root / "current.json"
    temporary = root / f"current.{generation}.tmp"
    current.replace(temporary)
    store.close()

    with ReadStore.open(root, PASSPHRASE) as recovered:
        assert recovered.current_generation == generation
    assert current.exists()
    assert not temporary.exists()


@pytest.mark.parametrize("boundary", ["after_build", "after_ready",
    "after_database_fsync", "before_manifest_replace"])
def test_interruption_before_publication_preserves_old_revision(tmp_path: Path, boundary: str):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        old = store.current_generation
        with pytest.raises(RuntimeError, match=boundary):
            store.publish(lambda db: db.execute("CREATE TABLE abandoned(value TEXT)"),
                          fail_at=boundary)
        assert store.current_generation == old
        assert list((store.directory / "quarantine").iterdir())
        assert not list(store.directory.glob("current.g-*.tmp"))


def test_interruption_after_replace_leaves_new_complete_revision(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        old = store.current_generation
        with pytest.raises(RuntimeError, match="after_manifest_replace"):
            store.publish(lambda db: db.execute("CREATE TABLE landed(value TEXT)"),
                          fail_at="after_manifest_replace")
        assert store.current_generation != old
        with store.open_reader() as reader:
            assert reader.connection.execute(
                "SELECT name FROM sqlite_master WHERE name='landed'").fetchone() == ("landed",)


def test_root_fsync_failure_after_replace_is_committed_and_reopens(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "read-model"
    with ReadStore.create(root, PASSPHRASE) as store:
        old = store.current_generation
        real_fsync_dir = module._fsync_dir
        failed = False

        def fail_root_once(path):
            nonlocal failed
            if Path(path) == root and not failed:
                failed = True
                raise OSError("synthetic root directory fsync failure")
            return real_fsync_dir(path)

        monkeypatch.setattr(module, "_fsync_dir", fail_root_once)
        new = store.publish(lambda db: db.execute("CREATE TABLE committed(value TEXT)"))
        assert new != old
        assert store.current_generation == new
        assert (root / "generations" / new).is_dir()
        assert store.publication_warning == "OSError: synthetic root directory fsync failure"

    monkeypatch.setattr(module, "_fsync_dir", real_fsync_dir)
    with ReadStore.open(root, PASSPHRASE) as reopened:
        assert reopened.current_generation == new
        with reopened.open_reader() as reader:
            assert reader.connection.execute(
                "SELECT name FROM sqlite_master WHERE name='committed'").fetchone() == (
                    "committed",)


def test_reported_replace_error_rereads_pointer_before_quarantine(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        real_replace = module._replace_manifest

        def replace_then_report_error(source, target):
            real_replace(source, target)
            raise OSError("synthetic uncertain replace result")

        monkeypatch.setattr(module, "_replace_manifest", replace_then_report_error)
        new = store.publish(lambda db: db.execute("CREATE TABLE landed(value TEXT)"))
        assert store.current_generation == new
        assert (store.directory / "generations" / new).is_dir()


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires no-follow opens")
def test_manifest_leaf_swap_between_check_and_open_is_refused(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "read-model"
    ReadStore.create(root, PASSPHRASE).close()
    manifest = root / "current.json"
    saved = root / "saved-current.json"
    outside = tmp_path / "outside.json"
    outside.write_text(manifest.read_text())
    real_lstat_kind = module._lstat_kind
    swapped = False

    def swap_after_check(path, *, directory):
        nonlocal swapped
        real_lstat_kind(path, directory=directory)
        if Path(path) == manifest and not swapped:
            swapped = True
            manifest.replace(saved)
            manifest.symlink_to(outside)

    monkeypatch.setattr(module, "_lstat_kind", swap_after_check)
    with pytest.raises(ReadStoreError, match=r"read[- ]store"):
        ReadStore.open(root, PASSPHRASE)


def test_old_reader_finishes_while_new_readers_bind_to_new_generation(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        store.publish(lambda db: (db.execute("CREATE TABLE sample(value TEXT)"),
                                  db.execute("INSERT INTO sample VALUES('old')")))
        old_reader = store.open_reader()
        old = old_reader.generation
        new = store.publish(lambda db: (db.execute("CREATE TABLE sample(value TEXT)"),
                                  db.execute("INSERT INTO sample VALUES('new')")))
        with store.open_reader() as new_reader:
            assert new_reader.generation == new
            assert new_reader.connection.execute("SELECT value FROM sample").fetchone() == ("new",)
        assert old_reader.connection.execute("SELECT value FROM sample").fetchone() == ("old",)
        assert (store.directory / "generations" / old).exists()
        old_reader.close()


def test_reader_binding_is_atomic_against_cleanup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        entered, resume = threading.Event(), threading.Event()
        real_connect = module._connect
        def paused_connect(path, key, *, readonly=False):
            if readonly and not entered.is_set():
                entered.set(); assert resume.wait(2)
            return real_connect(path, key, readonly=readonly)
        monkeypatch.setattr(module, "_connect", paused_connect)
        holder, inspect = {}, threading.Event()
        def open_and_hold():
            reader = store.open_reader(); holder["reader"] = reader
            inspect.wait(2); reader.close()
        thread = threading.Thread(target=open_and_hold)
        thread.start(); assert entered.wait(1)
        publish_done = threading.Event()
        publisher = threading.Thread(target=lambda: (store.publish(), publish_done.set()))
        publisher.start()
        assert not publish_done.wait(.05)
        resume.set(); publisher.join(2)
        bound = holder["reader"].generation
        assert bound != store.current_generation
        assert (store.directory / "generations" / bound).exists()
        inspect.set(); thread.join(2)


def test_cleanup_failure_after_commit_is_reported_without_failing_publish(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        old = store.current_generation
        monkeypatch.setattr(store, "cleanup", lambda: (_ for _ in ()).throw(OSError("denied")))
        new = store.publish()
        assert new != old and store.current_generation == new
        assert "denied" in store.cleanup_error


def test_cleanup_failure_on_open_is_deferred_and_observable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "read-model"; ReadStore.create(root, PASSPHRASE).close()
    monkeypatch.setattr(ReadStore, "cleanup",
                        lambda _self: (_ for _ in ()).throw(OSError("delete denied")))
    with ReadStore.open(root, PASSPHRASE) as store:
        assert store.current_generation
        assert "delete denied" in store.cleanup_error


def test_reader_close_failure_keeps_generation_pinned(tmp_path: Path):
    class FailingClose:
        def __init__(self, connection): self.connection, self.fail = connection, True
        def __getattr__(self, name): return getattr(self.connection, name)
        def close(self):
            if self.fail: self.fail = False; raise OSError("close failed")
            self.connection.close()
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        reader = store.open_reader(); reader.connection = FailingClose(reader.connection)
        generation = reader.generation
        with pytest.raises(OSError, match="close failed"): reader.close()
        for _ in range(4): store.publish()
        assert (store.directory / "generations" / generation).exists()
        with pytest.raises(ReadStoreError, match="revisions are open"): store.close()
        reader.close()


def test_retention_waits_for_references_then_is_bounded(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        protected = store.open_reader()
        protected_path = store.directory / "generations" / protected.generation
        for index in range(5):
            store.publish(lambda db, value=index: (
                db.execute("CREATE TABLE sample(value INTEGER)"),
                db.execute("INSERT INTO sample VALUES(?)", (value,))))
        assert protected_path.exists()
        protected.close()
        generations = list((store.directory / "generations").iterdir())
        quarantined = list((store.directory / "quarantine").iterdir())
        assert len(generations) <= 1 + module.RETAIN_SUPERSEDED_GENERATIONS
        assert len(quarantined) <= module.RETAIN_QUARANTINED_GENERATIONS


def test_incomplete_unreferenced_generation_is_quarantined_on_open(tmp_path: Path):
    root = tmp_path / "read-model"
    store = ReadStore.create(root, PASSPHRASE)
    incomplete = "g-" + "1" * 32
    path = root / "generations" / incomplete
    path.mkdir(mode=0o700)
    database = path / "projection.db"
    module._create_private_file(database)
    connection = module._connect(database, store._database_key)
    store._create_schema(connection, "building")
    connection.commit(); connection.close(); store.close()

    with ReadStore.open(root, PASSPHRASE):
        assert not path.exists()
        assert any(p.name.startswith(incomplete) for p in (root / "quarantine").iterdir())


def test_second_writer_has_a_bounded_wait(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        def holding_build(_db):
            entered.set(); release.wait(2)
        def publish():
            try: store.publish(holding_build)
            finally: finished.set()
        thread = threading.Thread(target=publish); thread.start(); assert entered.wait(1)
        with pytest.raises(ReadStoreBusy, match="timed out"):
            store.publish(lock_timeout=.02)
        release.set(); assert finished.wait(2); thread.join()


def test_manifest_replace_retries_only_windows_sharing_violations(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_text("new"); target.write_text("old")
    real_replace, calls = module.os.replace, []
    def sharing_then_success(left, right):
        calls.append(1)
        if len(calls) == 1:
            error = PermissionError("sharing"); error.winerror = 32; raise error
        return real_replace(left, right)
    monkeypatch.setattr(module.os, "name", "nt")
    monkeypatch.setattr(module.os, "replace", sharing_then_success)
    module._replace_manifest(source, target)
    assert len(calls) == 2 and target.read_text() == "new"

    source.write_text("again")
    def denied(_left, _right):
        error = PermissionError("denied"); error.winerror = 5; raise error
    monkeypatch.setattr(module.os, "replace", denied)
    with pytest.raises(PermissionError): module._replace_manifest(source, target)


def test_stock_sqlite_refuses_all_generation_data(tmp_path: Path):
    sentinel = "ORIONVIVA_SYNTHETIC_SENTINEL_71D949"
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        store.publish(lambda db: (db.execute("CREATE TABLE sentinel(value TEXT)"),
                                  db.execute("INSERT INTO sentinel VALUES(?)", (sentinel,))))
        database = store.directory / "generations" / store.current_generation / "projection.db"
        content = database.read_bytes()
        assert not content.startswith(b"SQLite format 3") and sentinel.encode() not in content
        with pytest.raises(sqlite3.DatabaseError):
            sqlite3.connect(database).execute("SELECT * FROM sentinel").fetchall()


def test_metadata_key_is_an_authenticated_sibling(tmp_path: Path):
    event_header, event_key = new_vault_header(PASSPHRASE)
    root = tmp_path / "read-model"; ReadStore.create(root, PASSPHRASE).close()
    metadata_path = root / "key.json"; metadata = json.loads(metadata_path.read_text())
    read_key = derive_key(PASSPHRASE, KdfParams.from_dict(metadata["kdf"]))
    assert metadata["kdf"]["salt"] != event_header["kdf"]["salt"] and read_key != event_key
    salt = base64.b64decode(metadata["kdf"]["salt"])
    metadata["kdf"]["salt"] = base64.b64encode(bytes([salt[0] ^ 1]) + salt[1:]).decode()
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ReadStoreError, match="authentication failed"):
        ReadStore.open(root, PASSPHRASE)


def test_authenticated_weaker_scrypt_cost_is_refused(tmp_path: Path):
    root = tmp_path / "read-model"; ReadStore.create(root, PASSPHRASE).close()
    metadata_path = root / "key.json"; metadata = json.loads(metadata_path.read_text())
    weak = KdfParams(salt=os.urandom(SALT_LEN), n=SCRYPT_N // 2, r=SCRYPT_R, p=SCRYPT_P)
    kdf, nonce = weak.to_dict(), os.urandom(12)
    key = derive_key(PASSPHRASE, weak)
    aad = b"viva-read-store-metadata:" + json.dumps(
        {"v": METADATA_VERSION, "kdf": kdf}, sort_keys=True, separators=(",", ":")).encode()
    ciphertext = AESGCM(key).encrypt(nonce, CHECK_TOKEN, aad)
    metadata.update({"kdf": kdf, "check": {"nonce": base64.b64encode(nonce).decode(),
                                            "ct": base64.b64encode(ciphertext).decode()}})
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(ReadStoreError, match="unsupported read-store KDF parameters"):
        ReadStore.open(root, PASSPHRASE)


@pytest.mark.skipif(os.name == "nt", reason="Windows ACL proof belongs to its release runner")
def test_read_store_tree_is_owner_only(tmp_path: Path):
    with ReadStore.create(tmp_path / "read-model", PASSPHRASE) as store:
        store.publish()
        assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
        for directory in (store.directory / "generations", store.directory / "quarantine"):
            assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        for path in store.directory.rglob("*"):
            expected = 0o700 if path.is_dir() else 0o600
            assert stat.S_IMODE(path.stat().st_mode) == expected


@pytest.mark.skipif(os.name == "nt", reason="symlink semantics are platform-specific")
@pytest.mark.parametrize("target", ["root", "manifest", "generation", "database",
                                     "metadata", "lock", "temporary", "wal", "quarantine"])
def test_symlinks_at_every_read_store_boundary_are_refused(tmp_path: Path, target: str):
    root = tmp_path / "read-model"; ReadStore.create(root, PASSPHRASE).close()
    outside = tmp_path / "outside"; outside.mkdir(); (outside / "file").write_text("{}")
    if target == "root":
        alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
        path = alias
    else:
        path = root
        if target == "manifest": victim = root / "current.json"; replacement = outside / "file"
        elif target == "metadata": victim = root / "key.json"; replacement = outside / "file"
        elif target == "lock": victim = root / "writer.lock"; replacement = outside / "file"
        elif target == "temporary":
            victim = root / ("current.g-" + "1" * 32 + ".tmp")
            replacement = outside / "file"
        elif target == "quarantine":
            victim = root / "quarantine" / "entry"; replacement = outside / "file"
        else:
            generation = json.loads((root / "current.json").read_text())["generation"]
            if target == "generation":
                victim = root / "generations" / generation; replacement = outside
            elif target == "wal":
                victim = root / "generations" / generation / "projection.db-wal"
                replacement = outside / "file"
            else:
                victim = root / "generations" / generation / "projection.db"
                replacement = outside / "file"
        if victim.exists():
            if victim.is_dir(): victim.rename(tmp_path / "saved")
            else: victim.unlink()
        victim.symlink_to(replacement, target_is_directory=replacement.is_dir())
    with pytest.raises(ReadStoreError, match="read-store"):
        ReadStore.open(path, PASSPHRASE)


@pytest.mark.parametrize("flush_fails", [False, True])
def test_generation_flush_uses_writable_descriptor_and_always_closes(
        tmp_path, monkeypatch, flush_fails):
    with ReadStore.create(tmp_path / "reads", PASSPHRASE) as reads:
        previous = reads.current_generation
        real_open, real_fsync, real_close = os.open, os.fsync, os.close
        database_descriptors = {}
        flushed, closed = [], []

        def open_file(path, flags, *args, **kwargs):
            descriptor = real_open(path, flags, *args, **kwargs)
            if Path(path).name == module.DATABASE_NAME and not flags & os.O_CREAT:
                database_descriptors[descriptor] = flags
            return descriptor

        def flush_file(descriptor):
            if descriptor in database_descriptors:
                flags = database_descriptors[descriptor]
                # Model Windows' writable-handle requirement on every CI host.
                if not flags & (os.O_WRONLY | os.O_RDWR):
                    raise OSError("synthetic Windows flush refused read-only handle")
                flushed.append(descriptor)
                if flush_fails:
                    raise OSError("synthetic database flush failure")
            return real_fsync(descriptor)

        def close_file(descriptor):
            if descriptor in database_descriptors:
                closed.append(descriptor)
                del database_descriptors[descriptor]
            return real_close(descriptor)

        monkeypatch.setattr(module, "os", SimpleNamespace(
            **{**vars(os), "open": open_file, "fsync": flush_file,
               "close": close_file}))
        if flush_fails:
            with pytest.raises(OSError, match="synthetic database flush failure"):
                reads.publish()
            assert reads.current_generation == previous
        else:
            assert reads.publish() != previous
        assert len(flushed) == 1
        assert closed == flushed
        assert not database_descriptors
