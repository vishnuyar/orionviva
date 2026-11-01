"""Complete decision verification beside the experimental indexed profile."""

import pytest

from viva.sql_authority import IntegrityError, SQLAuthority
from test_sql_authority_bank import ingest


pytestmark = pytest.mark.production_kdf


def _accepted_statement(store):
    result = ingest(store)
    assert result.status == "accepted"
    assert store.account(result.account_id)["running_balance"] == "90"
    assert [row["amount"] for row in store.postings(result.doc_id)] == ["-10", "10"]
    assert store.original(result.doc_id) == b"synthetic source"
    assert store.verify()["verified"]
    return result


def _mutate_unrelated_posting(store, result):
    changed = store._db.execute(
        "UPDATE postings SET amount='999' WHERE doc_id=? AND account_id=?",
        (result.doc_id, result.account_id),
    )
    assert changed.rowcount == 1


def test_complete_account_read_refuses_unrelated_posting_tamper(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "indexed", "synthetic passphrase") as indexed:
        result = _accepted_statement(indexed)
        trusted = indexed.head
        _mutate_unrelated_posting(indexed, result)
        # The account row and terminal commitment remain readable while a
        # different audited table disagrees with its authenticated history.
        assert indexed.account(result.account_id)["running_balance"] == "90"
        assert indexed.head == trusted
        with pytest.raises(IntegrityError, match="audited state mismatch: postings"):
            indexed.verify(expected_head=trusted)

    with SQLAuthority.create(
        tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete"
    ) as complete:
        result = _accepted_statement(complete)
        _mutate_unrelated_posting(complete, result)
        with pytest.raises(IntegrityError):
            complete.account(result.account_id)


# These readers answer canonical financial, source, identity or history questions.
# Diagnostics and configuration accessors intentionally are not in this set.
_READERS = (
    "head", "item", "original", "receipt", "movements", "transfer_inventory",
    "transfer_bindings", "transfer_links", "transfer_suggestions",
    "transfer_assertions", "transfer_decisions", "transfer_as_of", "account",
    "transactions", "postings", "balance_observations", "source_admission",
    "source_transactions", "source_occurrences", "source_observations",
    "identity_decision", "resolve_source_identity", "export_audit", "verify",
)


def _answer(store, name, result):
    from test_sql_authority_bank import reading

    if name == "head":
        return store.head
    facts = reading(result.doc_id, number="").facts
    facts.account_names = ["Synthetic holder"]
    facts.source_account_ref = "SYNTHETIC-SOURCE-A"
    facts.source_account_ref_page = 1
    facts.validated_source_page_count = 1
    arguments = {
        "item": (result.doc_id,), "original": (result.doc_id,),
        "receipt": (result.doc_id,), "transfer_as_of": ("2026-01-31",),
        "account": (result.account_id,), "transactions": (result.account_id,),
        "postings": (result.doc_id,), "balance_observations": (result.account_id,),
        "source_admission": (result.doc_id,), "source_transactions": (result.doc_id,),
        "source_occurrences": (result.doc_id,), "source_observations": (result.doc_id,),
        "identity_decision": (result.doc_id,),
        "resolve_source_identity": (facts,),
    }
    return getattr(store, name)(*arguments.get(name, ()))


@pytest.mark.parametrize("name", _READERS)
def test_each_canonical_reader_checks_the_complete_authority(tmp_path, name):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        _answer(store, name, result)
        _mutate_unrelated_posting(store, result)
        with pytest.raises(IntegrityError, match="audited state mismatch: postings"):
            _answer(store, name, result)
        assert not store._db.in_transaction
        assert not store._verified_operation
        assert not store._verifying


@pytest.mark.parametrize("policy", [None, True, 1, [], {}, "", "COMPLETE", "later"])
@pytest.mark.parametrize("operation", ["create", "open"])
def test_unknown_policy_refuses_before_root_changes(tmp_path, policy, operation):
    from viva.sql_authority import AuthorityError
    root = tmp_path.resolve() / "untouched"
    with pytest.raises(AuthorityError, match="verification policy"):
        getattr(SQLAuthority, operation)(root, "synthetic passphrase", verification=policy)
    assert not root.exists()


def test_complete_native_configuration_and_reopen(tmp_path):
    root = tmp_path.resolve() / "complete"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        trusted = store.head
        assert store.verification == "complete"
        assert store._db.execute("PRAGMA cipher_use_hmac").fetchall() in ([(1,)], [("1",)])
        assert store._db.execute("PRAGMA cipher_integrity_check").fetchall() == []
        assert store._db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert store._db.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(AttributeError):
            store.verification = "indexed"
    with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as reopened:
        assert reopened.verify(expected_head=trusted)["verified"]
        assert reopened.account(result.account_id)["running_balance"] == "90"
    with SQLAuthority.open(root, "synthetic passphrase") as indexed:
        assert indexed.verification == "indexed"
        assert indexed.verify(expected_head=trusted)["verified"]


@pytest.mark.parametrize("mutation", ["delete_middle", "reorder_middle", "source_missing", "source_tamper", "format"])
def test_complete_reads_refuse_unrelated_history_or_original_corruption(tmp_path, mutation):
    import base64
    import json
    from viva.crypto import CryptoError
    from viva.sql_authority import AuthorityError
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        assert store.head["revision"] > 2
        if mutation == "delete_middle":
            assert store._db.execute("DELETE FROM audit WHERE sequence=2").rowcount == 1
        elif mutation == "reorder_middle":
            assert store._db.execute("UPDATE audit SET previous_hash=? WHERE sequence=2", ("f" * 64,)).rowcount == 1
        elif mutation == "format":
            store._db.execute("UPDATE format SET schema_version=999")
        else:
            path = store.root / "originals" / (result.doc_id + ".blob")
            if mutation == "source_missing":
                path.unlink()
            else:
                envelope = json.loads(path.read_text())
                version, nonce = envelope["v"], envelope["nonce"]
                ciphertext = base64.b64decode(envelope["ct"], validate=True)
                changed = bytearray(ciphertext)
                assert changed
                changed[0] ^= 1
                assert bytes(changed) != ciphertext
                envelope["ct"] = base64.b64encode(changed).decode("ascii")
                assert envelope["v"] == version and envelope["nonce"] == nonce
                assert base64.b64decode(envelope["ct"], validate=True) == bytes(changed)
                path.write_text(json.dumps(envelope))
        with pytest.raises((AuthorityError, CryptoError, OSError)) as refusal:
            store.account(result.account_id)
        if mutation == "source_tamper":
            assert isinstance(refusal.value, CryptoError)
        assert not store._db.in_transaction
        assert not store._verified_operation


def test_wrong_expected_head_refuses_and_next_operation_is_fresh(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        trusted = store.head
        with pytest.raises(IntegrityError, match="trusted audit boundary"):
            store.verify(expected_head={"revision": trusted["revision"], "head": "f" * 64})
        assert not store._db.in_transaction
        assert store.account(result.account_id)["running_balance"] == "90"
        _mutate_unrelated_posting(store, result)
        with pytest.raises(IntegrityError):
            store.account(result.account_id)


def _canonical_rows(store):
    from viva.sql_authority.schema import TABLES
    return {name: store._db.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
            for name in (*TABLES, "audit", "commits", "control")}


@pytest.mark.parametrize("operation", ["ingest", "resume", "confirm", "reject", "unlink"])
def test_each_write_refuses_bad_preimage_without_accepted_effects(tmp_path, operation):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        _mutate_unrelated_posting(store, result)
        before = _canonical_rows(store)
        with pytest.raises(IntegrityError, match="audited state mismatch: postings"):
            if operation == "ingest":
                store.ingest(b"synthetic captured orphan", lambda *_args: pytest.fail("reader called after corrupt preimage"), contract="synthetic-balance-v1")
            elif operation == "resume":
                store.resume(result.doc_id)
            elif operation == "reject":
                store.reject_transfer("synthetic unknown movement", today="2026-01-31")
            else:
                getattr(store, operation + "_transfer")("synthetic movement a", "synthetic movement b", today="2026-01-31")
        assert _canonical_rows(store) == before
        assert not store._db.in_transaction
        assert store._operations is None
        assert not store._verified_operation


def test_nested_helpers_share_only_current_verified_operation(tmp_path, monkeypatch):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        original = store._verify_current
        calls = []
        def counted(**kwargs):
            calls.append(True)
            return original(**kwargs)
        monkeypatch.setattr(store, "_verify_current", counted)
        with store._decision():
            assert store.account(result.account_id)["running_balance"] == "90"
            assert store.original(result.doc_id) == b"synthetic source"
            assert store.head["revision"] > 0
        assert len(calls) == 1
        store.account(result.account_id)
        assert len(calls) == 2
        store.export_audit()
        assert len(calls) == 3
        store.verify()
        assert len(calls) == 4


def test_explicit_verification_refuses_inflight_work_without_rolling_it_back(tmp_path):
    from viva.sql_authority import AuthorityError
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        with store._transaction():
            before = list(store._operations)
            with pytest.raises(AuthorityError, match="independent committed operation"):
                store.verify()
            assert store._db.in_transaction
            assert store._operations == before
            with pytest.raises(AuthorityError, match="committed authority snapshot"):
                store.export_audit()
            assert store._db.in_transaction
            assert store.account(result.account_id)["running_balance"] == "90"
        store._db.execute("BEGIN IMMEDIATE")
        try:
            with pytest.raises(AuthorityError, match="independent committed operation"):
                store.verify()
            assert store._db.in_transaction
        finally:
            store._db.execute("ROLLBACK")
        assert store.verify()["verified"]


def test_reader_callback_is_outside_transaction_and_lost_ack_is_idempotent(tmp_path):
    from test_sql_authority_bank import reading
    root = tmp_path.resolve() / "complete"
    data = b"synthetic lost acknowledgement"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as store:
        def reader(_source, doc_id):
            assert not store._db.in_transaction
            assert not store._verified_operation
            return reading(doc_id)
        def fault(point):
            if point == "after_commit":
                rows = store._db.execute("SELECT state FROM items").fetchall()
                if rows == [("accepted",)]:
                    assert not store._db.in_transaction
                    assert not store._verified_operation
                    raise SystemExit("synthetic lost response")
        store._fault = fault
        with pytest.raises(SystemExit):
            store.ingest(data, reader, contract="synthetic-balance-v1")
        assert not store._verified_operation
    with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as reopened:
        trusted = reopened.head
        assert reopened.ingest(data, lambda *_args: pytest.fail("retained reader repeated"), contract="synthetic-balance-v1").status == "accepted"
        assert reopened.head == trusted
        assert reopened.verify()["counts"]["transactions"] == 1


def test_fault_rollback_clears_operation_before_next_attempt(tmp_path):
    from test_sql_authority_bank import reading
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        def fault(point):
            if point == "after_financial_rows":
                raise RuntimeError("synthetic interruption")
        store._fault = fault
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            store.ingest(b"synthetic interrupted source", lambda _data, doc_id: reading(doc_id), contract="synthetic-balance-v1")
        assert not store._db.in_transaction
        assert not store._verified_operation
        assert store._operations is None
        doc_id = store._db.execute("SELECT doc_id FROM documents").fetchone()[0]
        assert store.item(doc_id)["state"] == "staged"
        assert store.verify()["counts"]["transactions"] == 0
        store._fault = lambda _point: None
        assert store.resume(doc_id).status == "accepted"
        assert store.verify()["counts"]["transactions"] == 1


def test_writer_reservation_precedes_full_preimage_verification(tmp_path, monkeypatch):
    from sqlcipher3 import dbapi2 as sql
    root = tmp_path.resolve() / "complete"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as writer:
        _accepted_statement(writer)
        with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as contender:
            contender._db.execute("PRAGMA busy_timeout=0")
            original = writer._verify_current
            calls = []
            def verify_while_reserved(**kwargs):
                with pytest.raises(sql.OperationalError, match="locked"):
                    contender._db.execute("BEGIN IMMEDIATE")
                calls.append(True)
                return original(**kwargs)
            monkeypatch.setattr(writer, "_verify_current", verify_while_reserved)
            with writer._transaction():
                assert writer._db.in_transaction
            assert calls == [True]
            assert not contender._db.in_transaction


def test_full_reader_snapshot_survives_another_writers_uncommitted_change(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    root = tmp_path.resolve() / "complete"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as reader:
        result = _accepted_statement(reader)
        changed = threading.Event()
        start = threading.Event()
        def other_writer():
            with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as writer:
                assert start.wait(5)
                writer._db.execute("BEGIN IMMEDIATE")
                try:
                    _mutate_unrelated_posting(writer, result)
                    changed.set()
                    writer._db.execute("COMMIT")
                finally:
                    if writer._db.in_transaction:
                        writer._db.execute("ROLLBACK")
        original = reader._verify_current
        def verified_snapshot(**kwargs):
            answer = original(**kwargs)
            start.set()
            assert changed.wait(5)
            return answer
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(other_writer)
            monkeypatch.setattr(reader, "_verify_current", verified_snapshot)
            try:
                assert reader.account(result.account_id)["running_balance"] == "90"
            finally:
                monkeypatch.setattr(reader, "_verify_current", original)
                start.set()
            future.result(timeout=5)
        with pytest.raises(IntegrityError):
            reader.account(result.account_id)


def test_two_complete_writers_keep_economic_duplicate_single(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from test_sql_authority_bank import reading
    root = tmp_path.resolve() / "complete"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete"):
        pass
    barrier = threading.Barrier(2)
    def writer(index):
        with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as store:
            def reader(_data, doc_id):
                assert not store._db.in_transaction
                barrier.wait(timeout=5)
                return reading(doc_id)
            return store.ingest(f"synthetic duplicate {index}".encode(), reader, contract="synthetic-balance-v1")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(writer, range(2)))
    assert sorted(result.status for result in results) == ["accepted", "pending"]
    assert next(result.reason for result in results if result.status == "pending") == "economic_duplicate"
    with SQLAuthority.open(root, "synthetic passphrase", verification="complete") as store:
        assert store.verify()["counts"]["transactions"] == 1


def test_complete_open_closes_connection_on_verification_failure(tmp_path, monkeypatch):
    from sqlcipher3 import dbapi2 as sql
    import viva.sql_authority.store as implementation
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as indexed:
        result = _accepted_statement(indexed)
        _mutate_unrelated_posting(indexed, result)
    original = implementation._connect
    connections = []
    def observed(*args, **kwargs):
        connection = original(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(implementation, "_connect", observed)
    with pytest.raises(IntegrityError):
        SQLAuthority.open(root, "synthetic passphrase", verification="complete")
    assert len(connections) == 1
    with pytest.raises(sql.ProgrammingError):
        connections[0].execute("SELECT 1")


def test_native_disabled_page_authentication_refuses_complete_decision(tmp_path):
    """Native capability-gate proof, not an initialized public-handle toggle."""
    import secrets
    from sqlcipher3 import dbapi2 as sql
    from viva.sql_authority import AuthorityError
    from viva.sql_authority.store import _cipher_capability
    key = secrets.token_bytes(32)
    for setting, expected in (("OFF", 0), ("ON", 1)):
        connection = sql.connect(str(tmp_path.resolve() / ("native-hmac-" + setting)), isolation_level=None)
        try:
            connection.execute(f"PRAGMA key = \"x'{key.hex()}'\"")
            connection.execute(f"PRAGMA cipher_use_hmac={setting}")
            assert connection.execute("PRAGMA cipher_use_hmac").fetchall() in ([(expected,)], [(str(expected),)])
            if setting == "OFF":
                with pytest.raises(AuthorityError, match="page authentication"):
                    _cipher_capability(connection)
            else:
                _cipher_capability(connection)
        finally:
            connection.close()


def test_native_bad_encrypted_page_is_detected_before_complete_open(tmp_path):
    from sqlcipher3 import dbapi2 as sql
    from viva.sql_authority import AuthorityError
    from viva.sql_authority.store import _derive
    root = tmp_path.resolve() / "complete"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as store:
        _accepted_statement(store)
        database_key = _derive(store._key, b"database")
        page_size = int(store._db.execute("PRAGMA cipher_page_size").fetchone()[0])
    path = root / "authority.db"
    data = bytearray(path.read_bytes())
    assert len(data) >= 2 * page_size
    data[len(data) - page_size + 100] ^= 1
    path.write_bytes(data)
    connection = sql.connect(str(path), isolation_level=None)
    try:
        connection.execute(f"PRAGMA key = \"x'{database_key.hex()}'\"")
        connection.execute("PRAGMA cipher_use_hmac=ON")
        assert connection.execute("PRAGMA cipher_integrity_check").fetchall()
    finally:
        connection.close()
    with pytest.raises((AuthorityError, sql.DatabaseError)):
        SQLAuthority.open(root, "synthetic passphrase", verification="complete")


@pytest.mark.parametrize("version,hmac_rows", [(None, [(1,)]), ("", [(1,)]), ("unknown", [(1,)]), ("4.1.0", [(1,)]), ("4.2.0", []), ("4.2.0", [(0,)])])
def test_injected_unsupported_capability_cannot_treat_empty_pragma_as_success(version, hmac_rows):
    from viva.sql_authority import AuthorityError
    from viva.sql_authority.store import _cipher_capability
    class Response:
        def fetchone(self):
            return (version,) if version is not None else None
        def fetchall(self):
            return hmac_rows
    class CapabilityResponse:
        def execute(self, statement):
            assert statement in {"PRAGMA cipher_version", "PRAGMA cipher_use_hmac"}
            return Response()
    with pytest.raises(AuthorityError):
        _cipher_capability(CapabilityResponse())


@pytest.mark.parametrize("pragma,bad_rows", [
    ("PRAGMA cipher_integrity_check", [("injected bad page",)]),
    ("PRAGMA integrity_check", []),
    ("PRAGMA integrity_check", [("injected broken index",)]),
    ("PRAGMA foreign_key_check", [("synthetic table", 1, "parent", 0)]),
])
def test_injected_negative_integrity_responses_refuse_without_audit_changes(tmp_path, monkeypatch, pragma, bad_rows):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        before = _canonical_rows(store)
        connection = store._db
        class Response:
            def fetchall(self):
                return bad_rows
        class ConnectionResponse:
            def __getattr__(self, name):
                return getattr(connection, name)
            def execute(self, statement, *args):
                if statement == pragma:
                    return Response()
                return connection.execute(statement, *args)
        with monkeypatch.context() as patch:
            patch.setattr(store, "_db", ConnectionResponse())
            with pytest.raises(IntegrityError):
                store.account(result.account_id)
        assert not connection.in_transaction
        assert _canonical_rows(store) == before
        assert store.account(result.account_id)["running_balance"] == "90"


def test_native_foreign_key_violation_refuses_complete_decision(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        store._db.execute("PRAGMA foreign_keys=OFF")
        store._db.execute("INSERT INTO items VALUES(?,?,?,?,?)", ("f" * 64, "captured", "", "", 1))
        store._db.execute("PRAGMA foreign_keys=ON")
        assert store._db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert store._db.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(IntegrityError, match="reference integrity"):
            store.account(result.account_id)
        assert not store._db.in_transaction


def test_real_curated_member_requires_issued_owner_before_complete_reopen(tmp_path, monkeypatch, record_property):
    from sqlcipher3 import dbapi2 as sql
    from viva.sql_authority import AuthorityError, CuratedSource
    import viva.sql_authority.store as implementation
    # This validates the entire immutable pack through the production owner
    # factory. Only the selected member is ingested; setup time is not hidden.
    source = CuratedSource.open()
    record_property("whole_pack_fixture_setup_seconds", source.setup_seconds)
    record_property("validated_pack_document_count", source.identity["document_count"])
    record_property("ingested_member_count", 1)
    assert source.identity["document_count"] == 794
    document = next(member for member in source.documents if member["doc_type"] == "checking_statement")
    original = source.original(document["sha256"])
    root = tmp_path.resolve() / "one-curated-member"
    with SQLAuthority.create(root, "synthetic passphrase", verification="complete") as store:
        accepted = store.ingest_curated(original, source)
        assert accepted.status == "accepted"
        assert store.verify()["counts"]["documents"] == 1
        assert store.original(accepted.doc_id) == original
        trusted = store.head
    connect = implementation._connect
    connections = []
    def observed(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(implementation, "_connect", observed)
    with pytest.raises(IntegrityError, match="authenticated"):
        SQLAuthority.open(root, "synthetic passphrase", verification="complete")
    assert len(connections) == 1
    with pytest.raises(sql.ProgrammingError):
        connections[0].execute("SELECT 1")
    with SQLAuthority.open(root, "synthetic passphrase", verification="complete", curated_source=source) as reopened:
        assert reopened.verify(expected_head=trusted)["verified"]
        assert reopened.item(accepted.doc_id)["state"] == "accepted"
        assert reopened.original(accepted.doc_id) == original
        assert reopened.verify()["counts"]["documents"] == 1
    before_connections = len(connections)
    for forged in (object(), object.__new__(CuratedSource)):
        with pytest.raises(AuthorityError, match="ownership was not issued"):
            SQLAuthority.open(root, "synthetic passphrase", verification="complete", curated_source=forged)
        absent = tmp_path.resolve() / "must-not-open"
        with pytest.raises(AuthorityError, match="ownership was not issued"):
            SQLAuthority.open(absent, "synthetic passphrase", verification="complete", curated_source=forged)
        assert not absent.exists()
    assert len(connections) == before_connections
    with SQLAuthority.open(root, "synthetic passphrase") as indexed:
        indexed.attach_curated(source)
        assert indexed.verify(expected_head=trusted)["verified"]
    with SQLAuthority.open(root, "synthetic passphrase", curated_source=source) as indexed:
        assert indexed.verify(expected_head=trusted)["verified"]


def test_malformed_original_json_refuses_before_answer_and_cleans_operation(tmp_path):
    import json
    with SQLAuthority.create(tmp_path.resolve() / "complete", "synthetic passphrase", verification="complete") as store:
        result = _accepted_statement(store)
        path = store.root / "originals" / (result.doc_id + ".blob")
        path.write_bytes(b"synthetic damaged encrypted original")
        answered = False
        with pytest.raises(json.JSONDecodeError):
            store.account(result.account_id)
            answered = True
        assert not answered
        assert not store._db.in_transaction
        assert not store._verified_operation
        assert not store._verifying
