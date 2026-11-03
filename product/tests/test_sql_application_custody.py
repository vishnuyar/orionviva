"""Original custody remains distinct from financial acceptance."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import secrets

import pytest

from viva.sql_authority import SQLAuthority, AuthorityError, IntegrityError
from viva.sql_authority.application import ApplicationSQLAuthority
from viva.sql_authority.application_io import RecoveryRequired
from test_sql_authority_bank import ingest, reading
from test_sql_application_history import _accepted_statement


pytestmark = pytest.mark.production_kdf


def _kinds(root):
    return [json.loads(path.read_text())["kind"] for path in sorted((root / "history").iterdir())]


def test_custody_duplicate_and_unsupported_are_not_duplicate_money(tmp_path):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        head, before = owner.head, owner.postings(accepted.doc_id)
        duplicate = owner.ingest(b"synthetic source", lambda *_args: pytest.fail("duplicate reader repeated"),
                                 contract="synthetic-balance-v1")
        assert duplicate.doc_id == accepted.doc_id
        assert duplicate.status == "accepted"
        assert owner.head == head
        assert owner.postings(accepted.doc_id) == before
        assert _kinds(root).count("custody") == 1
        unsupported = ingest(owner, b"synthetic unsupported source", doc_type="pay_stub")
        assert unsupported.status == "unsupported"
        assert unsupported.reason == "unsupported_family"
        assert owner.postings(unsupported.doc_id) == []
        assert owner.original(unsupported.doc_id) == b"synthetic unsupported source"
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert owner.verify()["counts"]["accounts"] == 1
        assert _kinds(root).count("custody") == 2
        terminal = owner.terminal
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as reopened:
        assert reopened.terminal == terminal
        assert reopened.original(unsupported.doc_id) == b"synthetic unsupported source"
        assert reopened.postings(unsupported.doc_id) == []


@pytest.mark.parametrize("mutation", ["missing", "ciphertext", "unknown", "symlink", "hardlink"])
def test_custody_refuses_unknown_or_substituted_original_without_adoption(tmp_path, mutation):
    root = tmp_path.resolve() / "application"
    with SQLAuthority.create(root, secrets.token_urlsafe(32), verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        original = root / "sql" / "originals" / (accepted.doc_id + ".blob")
        captured = original.read_bytes()
        terminal = (root / "terminal.json").read_bytes()
        if mutation == "missing":
            original.unlink()
        elif mutation == "ciphertext":
            value = json.loads(captured)
            import base64
            payload = bytearray(base64.b64decode(value["ct"]))
            payload[0] ^= 1
            value["ct"] = base64.b64encode(payload).decode("ascii")
            original.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        elif mutation == "unknown":
            unknown = original.with_name("f" * 64 + ".blob")
            unknown.write_bytes(captured)
            unknown.chmod(0o600)
        elif mutation == "symlink":
            retained = tmp_path / "retained-original"
            retained.write_bytes(captured)
            retained.chmod(0o600)
            original.unlink()
            original.symlink_to(retained)
        else:
            import os
            os.link(original, tmp_path / "linked-original")
        with pytest.raises((AuthorityError, FileNotFoundError)):
            owner.account(accepted.account_id)
        assert (root / "terminal.json").read_bytes() == terminal
        assert not list((root / "pending").iterdir())


def test_reader_has_document_exclusion_but_no_root_or_sql_writer_lock(tmp_path):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        observations = []
        def reader(_data, doc_id):
            assert owner._root_lock.depth == 0
            assert not owner._engine._db.in_transaction
            def independent_read():
                with SQLAuthority.open(root, passphrase, verification="complete", application=True) as second:
                    return second.account(accepted.account_id)["running_balance"]
            with ThreadPoolExecutor(max_workers=1) as pool:
                observations.append(pool.submit(independent_read).result(timeout=15))
            return reading(doc_id, opening="90", closing="80", start="2026-01-31", end="2026-02-28")
        result = owner.ingest(b"synthetic callback source", reader, contract="synthetic-callback-v1")
        assert result.status == "accepted"
        assert observations == ["90"]
        assert owner.account(accepted.account_id)["running_balance"] == "80"


def test_reader_failure_retains_uncertainty_and_is_not_repeated(tmp_path):
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    original = b"synthetic uncertain source"
    doc_id = hashlib.sha256(original).hexdigest()
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        calls = []
        def reader(_data, _doc_id):
            calls.append(_doc_id)
            raise TimeoutError("synthetic reader uncertainty")
        with pytest.raises(TimeoutError):
            owner.ingest(original, reader, contract="synthetic-uncertain-v1")
        assert calls == [doc_id]
        assert not list((root / "pending").iterdir())
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        outcome = owner.ingest(original, lambda *_args: pytest.fail("uncertain reader repeated"), contract="synthetic-uncertain-v1")
        assert outcome.status == "read_uncertain"
        assert owner.original(doc_id) == original
        assert owner.postings(doc_id) == []
        assert owner.verify()["counts"]["transactions"] == 0


@pytest.mark.parametrize("partial", ["intent.next", "prepared-original.blob", "prepared-publication.json"])
def test_partial_capture_artifacts_are_diagnosed_and_preserved(tmp_path, monkeypatch, partial):
    from viva.sql_authority import application_io as io
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        original_write = io.exclusive_write
        original_head = io.replace_head
        def interrupted(path, data):
            if path.name == partial:
                original_write(path, b"{")
                raise OSError("injected partial filesystem write")
            return original_write(path, data)
        def interrupted_head(path, data, *, temporary, **kwargs):
            if temporary == partial:
                original_write(path.with_name(temporary), b"{")
                raise OSError("injected partial mutable-head write")
            return original_head(path, data, temporary=temporary, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(io, "exclusive_write", interrupted)
            patch.setattr(io, "replace_head", interrupted_head)
            with pytest.raises(OSError):
                ingest(owner)
        evidence = {str(path.relative_to(root)): path.read_bytes() for path in (root / "pending").rglob("*") if path.is_file()}
        assert any(name.endswith(partial) for name in evidence)
    with pytest.raises((IntegrityError, RecoveryRequired)):
        ApplicationSQLAuthority.recover(root, passphrase)
    assert evidence == {str(path.relative_to(root)): path.read_bytes() for path in (root / "pending").rglob("*") if path.is_file()}
