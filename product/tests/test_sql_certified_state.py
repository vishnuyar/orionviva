"""Fresh complete-state binding preserves financial, custody and lifecycle guards."""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import hashlib
import json
import secrets
import threading

import pytest

from viva.crypto import seal
from viva.sql_authority import SQLAuthority, AuthorityError, IntegrityError
from viva.sql_authority import application as application_module
from viva.sql_authority import application_history as history
from viva.sql_authority import certified_state
from viva.sql_authority.application_io import RecoveryRequired
from test_sql_application_history import _accepted_statement
from test_sql_authority_bank import ingest

pytestmark = pytest.mark.production_kdf


@contextmanager
def _owner(tmp_path, label):
    secret = secrets.token_urlsafe(32)
    root = tmp_path.resolve() / label
    with SQLAuthority.create(root, secret, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        assert owner._certificate is not None
        yield owner, accepted, secret


def test_certified_reads_and_preimages_preserve_complete_outputs(tmp_path, monkeypatch):
    with _owner(tmp_path, "complete-outputs") as (owner, accepted, secret):
        expected = (owner.account(accepted.account_id), owner.postings(accepted.doc_id), owner.receipt(accepted.doc_id), owner.original(accepted.doc_id))
        before_head, before_terminal = owner.head, owner.terminal
        full_calls, physical = [], []
        full, fresh = owner._engine._verify_current, owner._engine._fresh_physical_checks
        def count_full(*args, **kwargs):
            full_calls.append(True)
            return full(*args, **kwargs)
        def count_physical():
            physical.append(True)
            return fresh()
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", count_full)
            patch.setattr(owner._engine, "_fresh_physical_checks", count_physical)
            actual = (owner.account(accepted.account_id), owner.postings(accepted.doc_id), owner.receipt(accepted.doc_id), owner.original(accepted.doc_id))
            assert actual == expected and full_calls == [] and len(physical) >= 4
            assert owner.head == before_head and owner.terminal == before_terminal
            with pytest.raises(FrozenInstanceError):
                owner._certificate.sql_digest = "unchecked"
            with owner._engine._transaction():
                pass
            assert len(full_calls) == 1, "the no-op publication still receives full postverification"
            assert owner.head == before_head and owner.terminal["sequence"] == before_terminal["sequence"] + 1
            assert owner._certificate is not None and not owner._certificate.representation.pending
            assert owner.verify()["verified"] and len(full_calls) == 2
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert owner.postings(accepted.doc_id) == expected[1]
        root, terminal = owner.root, owner.terminal
    opened = []
    original = SQLAuthority._verify_current
    def count_open(self, *args, **kwargs):
        opened.append(True)
        return original(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(SQLAuthority, "_verify_current", count_open)
        with SQLAuthority.open(root, secret, verification="complete", application=True) as reopened:
            assert opened and reopened.terminal == terminal
            assert reopened.account(accepted.account_id) == expected[0]


def test_certified_binding_refuses_same_head_old_evidence(tmp_path):
    for mutation in ("row", "audit", "commit", "control_extra", "history", "metadata", "terminal", "schema", "foreign_key", "original"):
        for route in ("read", "writer"):
            with _owner(tmp_path, "tamper-" + route + "-" + mutation) as (owner, accepted, _secret):
                engine = owner._engine
                head = owner.head
                if mutation == "row":
                    engine._db.execute("UPDATE postings SET amount='999' WHERE doc_id=? AND account_id=?", (accepted.doc_id, accepted.account_id))
                elif mutation == "audit":
                    engine._db.execute("UPDATE audit SET envelope='{}' WHERE sequence=1")
                elif mutation == "commit":
                    engine._db.execute("UPDATE commits SET mac=? WHERE revision=1", ("0" * 64,))
                elif mutation == "control_extra":
                    engine._db.execute("PRAGMA ignore_check_constraints=ON")
                    engine._db.execute("INSERT INTO control VALUES(2,0,?,?)", ("0"*64,"0"*64))
                elif mutation == "history":
                    path = sorted((owner.root / "history").iterdir())[0]
                    value = json.loads(path.read_bytes())
                    value["mac"] = ("1" if value["mac"][0] == "0" else "0") + value["mac"][1:]
                    path.write_bytes(history.encoded(value))
                elif mutation == "metadata":
                    path = owner.root / "application.json"
                    value = json.loads(path.read_bytes()); value["version"] = 99
                    path.write_bytes(history.encoded(value))
                elif mutation == "terminal":
                    path = owner.root / "terminal.json"
                    value = json.loads(path.read_bytes())
                    value["mac"] = ("1" if value["mac"][0] == "0" else "0") + value["mac"][1:]
                    path.write_bytes(history.encoded(value))
                elif mutation == "schema":
                    engine._db.execute("CREATE TABLE unexpected_certified_table(value TEXT)")
                elif mutation == "foreign_key":
                    engine._db.execute("PRAGMA foreign_keys=OFF")
                    engine._db.execute("UPDATE postings SET account_id='missing-account' WHERE doc_id=?", (accepted.doc_id,))
                else:
                    path = owner.root / "sql/originals" / (accepted.doc_id + ".blob")
                    data = owner.original(accepted.doc_id)
                    path.write_bytes(history.encoded(seal(engine._raw._key, data, aad=accepted.doc_id.encode("ascii"))))
                assert engine._db.execute("SELECT revision,head FROM control WHERE singleton=1").fetchone() == (head["revision"], head["head"])
                if route == "writer":
                    entered = []
                    with pytest.raises((AuthorityError, IntegrityError)):
                        with engine._transaction():
                            entered.append(True)
                    assert entered == [], "tampered writer preimage must refuse before its body"
                else:
                    with pytest.raises((AuthorityError, IntegrityError)):
                        owner.account(accepted.account_id)
                assert engine._db.execute("SELECT revision,head FROM control WHERE singleton=1").fetchone() == (head["revision"], head["head"])
                assert owner._certificate is None and owner._pending_certificate is None


def test_certified_collection_and_promotion_refuse_filesystem_races(tmp_path, monkeypatch):
    with _owner(tmp_path, "scan-race") as (owner, accepted, _secret):
        original = owner._history._scan_with_proof
        touched = []
        def race(*args, **kwargs):
            result = original(*args, **kwargs)
            if not touched:
                touched.append(True)
                path = sorted((owner.root / "history").iterdir())[0]
                value = json.loads(path.read_bytes())
                value["mac"] = ("1" if value["mac"][0] == "0" else "0") + value["mac"][1:]
                path.write_bytes(history.encoded(value))
            return result
        with monkeypatch.context() as patch:
            patch.setattr(owner._history, "_scan_with_proof", race)
            with pytest.raises(IntegrityError):
                owner.verify()
        assert touched and owner._certificate is None and owner._pending_certificate is None
    with _owner(tmp_path, "promotion-race") as (owner, accepted, _secret):
        data = owner.original(accepted.doc_id)
        touched = []
        def race(point):
            if point == "after_history_publication":
                assert owner._certificate is None and owner._pending_certificate is not None
                touched.append(True)
                path = owner.root / "sql/originals" / (accepted.doc_id + ".blob")
                path.write_bytes(history.encoded(seal(owner._engine._raw._key, data, aad=accepted.doc_id.encode("ascii"))))
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_fault", race)
            with pytest.raises(IntegrityError):
                with owner._engine._transaction():
                    pass
        assert touched and owner._certificate is None and owner._pending_certificate is None


def test_certified_custody_digest_uses_authenticated_buffer(tmp_path, monkeypatch):
    from viva.ingest import raw_store
    with _owner(tmp_path, "same-buffer") as (owner, accepted, _secret):
        path = owner.root / "sql/originals" / (accepted.doc_id + ".blob")
        before = path.read_bytes()
        plain = owner.original(accepted.doc_id)
        public = owner._engine._raw.get_bounded(accepted.doc_id)
        assert type(public) is bytes and public == plain
        with pytest.raises(OverflowError, match="original exceeds preview bound"):
            owner._engine._raw.get_bounded(accepted.doc_id, max_envelope=len(before)-1)
        decrypt = raw_store.open_sealed
        changed = []
        def race(key, envelope, *, aad):
            if not changed:
                changed.append(True)
                path.write_bytes(history.encoded(seal(key, plain, aad=aad)))
            return decrypt(key, envelope, aad=aad)
        with monkeypatch.context() as patch:
            patch.setattr(raw_store, "open_sealed", race)
            data, digest = owner._engine._raw._get_bounded_with_commitment(
                accepted.doc_id, max_plaintext=50*1024*1024, max_envelope=72*1024*1024)
        assert data == plain and digest == hashlib.sha256(before).hexdigest()
        assert digest != hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(IntegrityError):
            owner.original(accepted.doc_id)
        assert owner._certificate is None


def test_certified_initial_intent_and_rollback_invalidate_trust(tmp_path, monkeypatch):
    with _owner(tmp_path, "intent") as (owner, accepted, _secret):
        foreign = owner.root / "pending" / ("f" * 64)
        foreign.mkdir(mode=0o700)
        try:
            with pytest.raises(RecoveryRequired):
                owner.account(accepted.account_id)
        finally:
            foreign.rmdir()
        assert owner._certificate is None
        owner.verify()
        proof = owner._certificate
        with owner._root_lock.hold():
            issued = owner._issue("transaction")
            owner._begin(issued)
            owner._prepare(issued, "noop", {"intent_sha256": history.digest(history.encoded(issued))}, issued["prior_sql"])
            with owner._engine._snapshot():
                with pytest.raises(IntegrityError):
                    owner._engine._bind_verified_state(proof, initial=True)
            owner._abort()
        assert owner._certificate is None and owner._pending_certificate is None
        owner.verify()
        before = owner.account(accepted.account_id)
        def fail(point):
            if point == "before_audit" and any(op["table"] == "transactions" for op in owner._engine._operations):
                raise RuntimeError("controlled certified writer rollback")
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_fault", fail)
            with pytest.raises(RuntimeError, match="controlled certified writer rollback"):
                ingest(owner, b"synthetic certified rollback", number="7654321")
        assert owner._certificate is None and owner._pending_certificate is None
        assert owner.account(accepted.account_id) == before and owner.verify()["verified"]


def test_certified_extension_thread_and_pid_boundaries(tmp_path, monkeypatch):
    with _owner(tmp_path, "extension") as (owner, accepted, secret):
        before = owner.account(accepted.account_id)
        with SQLAuthority.open(owner.root, secret, verification="complete", application=True) as other:
            added = ingest(other, b"synthetic independent extension", number="7654321")
            assert added.status == "accepted"
            assert owner.account(accepted.account_id) == before
            assert owner.account(added.account_id)["running_balance"] == "90"
            owner._certificate = other._certificate
            with pytest.raises(IntegrityError):
                owner.account(accepted.account_id)
            assert owner._certificate is None
        owner.verify()
        answers, errors = [], []
        def serialized_phase():
            try:
                with owner.operation("phase"):
                    certified_state._owner(owner._certificate, owner)
                    answers.append(True)
            except BaseException as error:
                errors.append(type(error).__name__)
        thread = threading.Thread(target=serialized_phase)
        thread.start(); thread.join(timeout=5)
        assert not thread.is_alive() and answers == [True] and errors == []
        # This proves proof ownership across serialized phases, not off-thread SQL.
        pid = application_module.os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr(application_module.os, "getpid", lambda: pid + 1)
            with pytest.raises(AuthorityError):
                owner.account(accepted.account_id)
        assert owner._certificate is None and owner._pending_certificate is None
        assert owner.account(accepted.account_id) == before


def test_certified_capture_and_explicit_verify_keep_full_paths(tmp_path, monkeypatch):
    with _owner(tmp_path, "capture") as (owner, accepted, _secret):
        raw = b"synthetic certified receipt-only original"
        doc = hashlib.sha256(raw).hexdigest()
        owner.capture(doc, raw)
        assert owner._certificate is None and owner._pending_certificate is None
        assert owner.verify()["verified"] and owner.original(doc) == raw
        full_calls = []
        original = owner._engine._verify_current
        def full(*args, **kwargs):
            full_calls.append(True)
            return original(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", full)
            assert owner.verify()["verified"]
            assert owner.verify()["verified"]
        assert len(full_calls) == 2
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert owner._certificate is not None and not owner._certificate.representation.pending


def test_certified_changed_write_full_check_and_lost_ack_recover(tmp_path, monkeypatch):
    from viva.sql_authority.application import ApplicationSQLAuthority
    with _owner(tmp_path, "changed-full") as (owner, accepted, _secret):
        before = owner.head
        checks = []
        full = owner._engine._verify_current
        def count_full(*args, **kwargs):
            pending = owner._pending
            revision = owner._engine._db.execute("SELECT revision FROM control WHERE singleton=1").fetchone()[0]
            changed = (pending is not None and owner._committed
                       and revision > pending[1]["prior_sql"]["revision"])
            result = full(*args, **kwargs)
            if changed:
                assert owner._extension is not None
                assert owner._pending_certificate is not None
                assert owner._pending_certificate.representation.pending
                assert owner._certificate is None
                checks.append(revision)
            return result
        with monkeypatch.context() as patch:
            patch.setattr(owner._engine, "_verify_current", count_full)
            added = ingest(owner, b"synthetic certified changed forward", opening="90", closing="80",
                           start="2026-01-31", end="2026-02-28")
        assert added.status == "accepted" and added.account_id == accepted.account_id
        after = owner.head
        assert after["revision"] > before["revision"] and after["head"] != before["head"]
        assert after["revision"] in checks, "actual changed SQL receives the full pending-transaction checker"
        assert owner.account(accepted.account_id)["running_balance"] == "80"
        assert len(owner.transactions(accepted.account_id)) == 2
        assert owner._certificate is not None and not owner._certificate.representation.pending

    with _owner(tmp_path, "lost-ack") as (owner, accepted, secret):
        root, trusted = owner.root, owner.terminal
        interrupted = []
        def lose_ack(point):
            if (point == "after_sql_commit" and any(
                    op["table"] == "transactions" for op in owner._engine._operations)):
                interrupted.append(True)
                raise RuntimeError("controlled certified lost acknowledgement")
        with monkeypatch.context() as patch:
            patch.setattr(owner, "_fault", lose_ack)
            with pytest.raises(RuntimeError, match="controlled certified lost acknowledgement"):
                ingest(owner, b"synthetic certified lost acknowledgement", opening="90", closing="80",
                       start="2026-01-31", end="2026-02-28")
        assert interrupted == [True]
        assert owner._certificate is None and owner._pending_certificate is None
        assert owner._engine._db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
        assert list((root / "pending").iterdir())
        with pytest.raises(RecoveryRequired):
            owner.account(accepted.account_id)
    recovered = ApplicationSQLAuthority.recover(root, secret, expected_prefix=trusted)
    assert recovered["status"] == "ready" and recovered["outcome"] == "committed"
    assert not list((root / "pending").iterdir())
    with SQLAuthority.open(root, secret, verification="complete", application=True) as owner:
        assert owner.account(accepted.account_id)["running_balance"] == "80"
        assert len(owner.transactions(accepted.account_id)) == 2
        assert owner.verify()["verified"]
        assert owner._certificate is not None and not owner._certificate.representation.pending
        head, terminal = owner.head, owner.terminal
        assert ApplicationSQLAuthority.recover(root, secret, expected_prefix=trusted)["outcome"] == "already_ready"
        assert owner.head == head and owner.terminal == terminal


def test_certified_curated_application_reauthenticates_source_owner(tmp_path, monkeypatch):
    from viva.sql_authority import CuratedSource, curated
    source = CuratedSource.open()
    document = next(row for row in source.documents if row["doc_type"] == "checking_statement")
    original = source.original(document["sha256"])
    root, secret = tmp_path.resolve() / "curated-application", secrets.token_urlsafe(32)
    with SQLAuthority.create(root, secret, verification="complete", application=True) as owner:
        accepted = owner.ingest_curated(original, source)
        assert accepted.status == "accepted" and accepted.doc_id == document["sha256"]
        assert owner._certificate is not None and not owner._certificate.representation.pending
        account = owner.account(accepted.account_id)
        calls, full_calls = [], []
        authenticate, full = curated.authenticate, owner._engine._verify_current
        def reauthenticate(store, receipt, reading):
            calls.append((store is owner._engine, receipt["doc_id"] == accepted.doc_id))
            return authenticate(store, receipt, reading)
        def count_full(*args, **kwargs):
            full_calls.append(True)
            return full(*args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(curated, "authenticate", reauthenticate)
            patch.setattr(owner._engine, "_verify_current", count_full)
            assert owner.account(accepted.account_id) == account
            assert calls and all(pair == (True, True) for pair in calls) and full_calls == []
            owner._engine._curated_owner = None
            with pytest.raises(AuthorityError):
                owner.account(accepted.account_id)
            assert owner._certificate is None and owner._pending_certificate is None
    reopened_checks = []
    full = SQLAuthority._verify_current
    def reopened_full(self, *args, **kwargs):
        reopened_checks.append(True)
        return full(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(SQLAuthority, "_verify_current", reopened_full)
        with SQLAuthority.open(root, secret, verification="complete", application=True, curated_source=source) as owner:
            assert reopened_checks and owner._certificate is not None
            assert owner.account(accepted.account_id) == account
            assert owner.original(accepted.doc_id) == original
            assert owner.verify()["verified"]
