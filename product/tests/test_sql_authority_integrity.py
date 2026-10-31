"""Encrypted format boundaries and independent closed audit reconstruction."""
import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from viva.crypto import CryptoError
from viva.sql_authority import SQLAuthority, AuthorityError, IntegrityError
from test_sql_authority_bank import ingest

pytestmark = pytest.mark.production_kdf


def test_ciphertext_sources_staging_and_side_files(tmp_path):
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        def fault(point):
            if point == "after_financial_rows":
                for path in root.rglob("*"):
                    if path.is_file():
                        data = path.read_bytes()
                        assert b"Synthetic movement" not in data
                        assert b"Synthetic Issuer" not in data
                        assert b"synthetic source" not in data
                        assert path.stat().st_mode & 0o077 == 0
        store._fault = fault
        ingest(store)
        assert store.verify()["verified"]
    assert not (root / "authority.db").read_bytes().startswith(b"SQLite format 3")
    with pytest.raises(sqlite3.DatabaseError):
        plain = sqlite3.connect(root / "authority.db")
        try:
            plain.execute("SELECT * FROM accounts").fetchall()
        finally:
            plain.close()
    with pytest.raises(CryptoError):
        SQLAuthority.open(root, "wrong synthetic passphrase")


@pytest.mark.parametrize("mutation", ["unknown_format", "unknown_schema", "weak_kdf", "extra_file", "symlink_database", "symlink_originals"])
def test_unknown_and_unsafe_layout_refused(tmp_path, mutation):
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase"):
        pass
    if mutation in {"unknown_format", "weak_kdf"}:
        path = root / "authority.json"
        metadata = json.loads(path.read_text())
        if mutation == "unknown_format": metadata["format"] = "unknown-format"
        else: metadata["crypto"]["kdf"]["n"] = 16
        path.write_text(json.dumps(metadata))
    elif mutation == "unknown_schema":
        with SQLAuthority.open(root, "synthetic passphrase") as store:
            store._db.execute("UPDATE format SET schema_version=999")
    elif mutation == "extra_file":
        (root / "events.jsonl").touch(mode=0o600)
    elif mutation == "symlink_database":
        database = root / "authority.db"
        target = root.parent / "database"
        database.rename(target)
        database.symlink_to(target)
    else:
        directory = root / "originals"
        target = root.parent / "originals"
        directory.rename(target)
        directory.symlink_to(target, target_is_directory=True)
    with pytest.raises(AuthorityError):
        SQLAuthority.open(root, "synthetic passphrase")


def test_refuses_existing_legacy_root_and_symlink_root(tmp_path):
    legacy = tmp_path.resolve() / "legacy"
    legacy.mkdir(mode=0o700)
    (legacy / "events.jsonl").write_bytes(b"synthetic old format")
    with pytest.raises(FileExistsError):
        SQLAuthority.create(legacy, "synthetic passphrase")
    with pytest.raises((AuthorityError, FileNotFoundError)):
        SQLAuthority.open(legacy, "synthetic passphrase")
    link = tmp_path.resolve() / "link"
    link.symlink_to(legacy, target_is_directory=True)
    with pytest.raises(AuthorityError):
        SQLAuthority.open(link, "synthetic passphrase")


@pytest.mark.parametrize("suffix", [".blob", ".lock"])
def test_source_paths_never_follow_symlinks(tmp_path, suffix):
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        outside = tmp_path.resolve() / "outside"
        outside.write_bytes(b"synthetic outside sentinel")
        outside.chmod(0o600)
        doc_id = hashlib.sha256(b"synthetic source").hexdigest()
        (root / "originals" / (doc_id + suffix)).symlink_to(outside)
        with pytest.raises((AuthorityError, OSError)):
            ingest(store)
        assert outside.read_bytes() == b"synthetic outside sentinel"


@pytest.mark.parametrize("mutation", ["accepted_amount", "staged_amount", "receipt", "audit_delete", "audit_modify", "audit_reorder", "audit_truncate", "commit_delete", "control_head"])
def test_independent_verification_detects_direct_tampering(tmp_path, mutation):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        result = ingest(store)
        trusted = store.head
        assert store.verify(expected_head=trusted)["verified"]
        if mutation == "accepted_amount": store._db.execute("UPDATE postings SET amount='999'")
        elif mutation == "staged_amount": store._db.execute("UPDATE staged_lines SET amount='999'")
        elif mutation == "receipt": store._db.execute("UPDATE receipts SET body='{}'")
        elif mutation == "audit_delete": store._db.execute("DELETE FROM audit WHERE sequence=2")
        elif mutation == "audit_modify": store._db.execute("UPDATE audit SET envelope='{}' WHERE sequence=2")
        elif mutation == "audit_reorder": store._db.execute("UPDATE audit SET previous_hash=? WHERE sequence=2", ("f" * 64,))
        elif mutation == "audit_truncate": store._db.execute("DELETE FROM audit WHERE sequence=(SELECT max(sequence) FROM audit)")
        elif mutation == "commit_delete": store._db.execute("DELETE FROM commits WHERE revision=(SELECT max(revision) FROM commits)")
        else: store._db.execute("UPDATE control SET head=?", ("f" * 64,))
        with pytest.raises(IntegrityError):
            store.verify(expected_head=trusted)


def test_export_structure_does_not_claim_authentication_and_trusted_head_rejects_rollback(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        ingest(store)
        earlier = store.export_audit()
        earlier_head = store.head
        ingest(store, b"synthetic next source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
        current = store.head
        assert store.check_export_structure(earlier, expected_head=earlier_head) == {"structural": True, "authenticated": False, "revision": earlier["revision"]}
        with pytest.raises(IntegrityError):
            store.check_export_structure(earlier, expected_head=current)
        modified = copy.deepcopy(earlier)
        modified["mac"] = "0" * 64
        assert store.check_export_structure(modified)["structural"]
        with pytest.raises(IntegrityError, match="MAC"):
            store._reconstruct(modified, earlier_head)


def test_failed_dependency_query_has_executable_index_proof(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        plans = store.dependency_plans()
        assert "INDEX" in str(plans["account"])
        assert "INDEX" in str(plans["period"])
        assert "dependencies_boundary" in str(plans["pending"])
        store._db.execute("DROP INDEX dependencies_boundary")
        # Change the SQL text so SQLite cannot serve an earlier prepared EXPLAIN.
        plan = store._db.execute("EXPLAIN QUERY PLAN SELECT doc_id FROM dependencies WHERE identity=? AND boundary_amount=? AND direction=? /* independent counterfactual */", ("x", "0", "forward")).fetchall()
        assert "SCAN dependencies" in str(plan)


def test_export_source_catalog_is_bound_by_keyed_reconstruction(tmp_path):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        result = ingest(store)
        exported = store.export_audit()
        assert exported["sources"] == [{"doc_id": result.doc_id, "sha256": result.doc_id, "byte_count": len(b"synthetic source")}]
        exported["sources"][0]["byte_count"] += 1
        assert store.check_export_structure(exported)["structural"]
        with pytest.raises(IntegrityError, match="sources disagree"):
            store._reconstruct(exported, store.head)


def test_legacy_noncreating_open_cannot_recognize_or_upgrade_prototype(tmp_path):
    from viva.vault import Vault, VaultNotFound, holds_a_vault
    root = tmp_path.resolve() / "authority"
    with SQLAuthority.create(root, "synthetic passphrase") as store:
        ingest(store)
        head = store.head
        before = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
        assert not holds_a_vault(root)
        with pytest.raises(VaultNotFound):
            Vault.open(root, "synthetic passphrase", create=False)
        after = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob("*") if path.is_file()}
        assert before == after
        assert store.head == head


def _resealed_export(store, exported, mutate):
    from viva.crypto import seal, open_sealed
    from viva.sql_authority.store import canonical
    changed = copy.deepcopy(exported)
    previous = "0" * 64
    for index, record in enumerate(exported["records"], 1):
        payload = json.loads(open_sealed(store._audit_key, json.loads(record[2]), aad=canonical([index, record[1]]).encode()))
        mutate(payload)
        envelope = canonical(seal(store._audit_key, canonical(payload).encode(), aad=canonical([index, previous]).encode()))
        digest = hashlib.sha256(canonical([index, previous, envelope]).encode()).hexdigest()
        changed["records"][index - 1] = [index, previous, envelope, digest]
        changed["commits"][index - 1] = [index, digest, store._mac(index, digest)]
        previous = digest
    changed["head"] = previous
    changed["mac"] = store._mac(changed["revision"], previous)
    return changed


@pytest.mark.parametrize("bad_page", ["not-an-integer", True, -1])
def test_authenticated_audit_page_requires_exact_integer_protocol(tmp_path, bad_page):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        ingest(store)
        original = store.export_audit()
        def mutate(payload):
            for operation in payload["operations"]:
                if operation["table"] == "staged_lines":
                    operation["row"]["page"] = bad_page
        altered = _resealed_export(store, original, mutate)
        # Disposable-key resealing tests protocol robustness, not MAC forgery.
        with pytest.raises(IntegrityError, match="audited row"):
            store._reconstruct(altered, {"revision": altered["revision"], "head": altered["head"]})
        assert store._reconstruct(original, store.head)["staged_lines"]
        assert store.verify()["verified"]


@pytest.mark.parametrize("location", ["payload_version", "record_sequence", "commit_revision", "expected_revision"])
def test_boolean_one_cannot_stand_for_integer_audit_protocol(tmp_path, location):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        ingest(store)
        exported = store.export_audit()
        expected = store.head
        if location == "payload_version":
            def mutate(payload):
                payload["version"] = True
            exported = _resealed_export(store, exported, mutate)
            expected = {"revision": exported["revision"], "head": exported["head"]}
        elif location == "record_sequence":
            exported["records"][0][0] = True
        elif location == "commit_revision":
            exported["commits"][0][0] = True
        else:
            exported = _resealed_export(store, exported, lambda _payload: None)
            # A nonempty authority has several commits, so use an isolated
            # valid genesis export to prove bool-versus-zero boundary typing.
            exported = {"format": exported["format"], "revision": 0, "head": "0" * 64,
                        "mac": store._mac(0, "0" * 64), "sources": [], "records": [], "commits": []}
            expected = {"revision": False, "head": "0" * 64}
        with pytest.raises(IntegrityError):
            store._reconstruct(exported, expected)


@pytest.mark.parametrize("table,column,bad", [
    ("staged_lines", "page", 0), ("staged_lines", "page", 201),
    ("staged_lines", "amount", 1.0), ("staged_lines", "amount", "NaN"),
    ("staged_lines", "date", "2026-99-99"), ("staged_lines", "line_index", True),
    ("items", "state", "invented"), ("items", "revision", True),
    ("documents", "byte_count", True), ("postings", "grade", "invented"),
    ("accounts", "currency", ""), ("accounts", "number", None),
])
def test_reconstruction_validates_known_column_types_bounds_and_enums(tmp_path, table, column, bad):
    with SQLAuthority.create(tmp_path.resolve() / "authority", "synthetic passphrase") as store:
        ingest(store)
        def mutate(payload):
            for operation in payload["operations"]:
                if operation["table"] == table:
                    operation["row"][column] = bad
        altered = _resealed_export(store, store.export_audit(), mutate)
        with pytest.raises(IntegrityError, match="audited row"):
            store._reconstruct(altered, {"revision": altered["revision"], "head": altered["head"]})
