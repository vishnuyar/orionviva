"""Sealed live history beside fully verified SQL financial state."""

import json
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

from viva.sql_authority import SQLAuthority
from test_sql_authority_bank import ingest


pytestmark = pytest.mark.production_kdf


def _accepted_statement(store):
    result = ingest(store)
    assert result.status == "accepted"
    assert store.account(result.account_id)["running_balance"] == "90"
    assert [row["amount"] for row in store.postings(result.doc_id)] == ["-10", "10"]
    assert store.original(result.doc_id) == b"synthetic source"
    verified = store.verify(expected_head=store.head)
    assert verified["verified"] is True
    assert verified["counts"]["accounts"] == 1
    assert verified["counts"]["transactions"] == 1
    return result


def _fresh_keyless_check(root, terminal):
    # A new interpreter receives import locations and the public boundary only.
    # It has no inherited environment, passphrase, keyed handle or open database.
    program = """
import json
import sys
from pathlib import Path

request = json.loads(sys.stdin.read())
sys.path[:] = request["import_paths"]
from viva.sql_authority import IntegrityError
from viva.sql_authority.application import ApplicationSQLAuthority

try:
    result = ApplicationSQLAuthority.verify_live_chain(
        Path(request["root"]), expected_terminal=request["terminal"]
    )
except IntegrityError:
    print(json.dumps({"refused": "IntegrityError"}))
else:
    print(json.dumps({"result": result}))
"""
    request = {
        "import_paths": [str(Path(path).resolve()) for path in sys.path],
        "root": str(root),
        "terminal": terminal,
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program],
        input=json.dumps(request), text=True, capture_output=True,
        env={}, cwd=root.parent, timeout=30, check=True,
    )
    return json.loads(completed.stdout)


def test_application_live_history_after_positive_complete_sql(tmp_path, record_property):
    passphrase = secrets.token_urlsafe(32)
    prototype_root = tmp_path.resolve() / "complete-prototype"
    with SQLAuthority.create(
        prototype_root, passphrase, verification="complete"
    ) as prototype:
        assert prototype.verification == "complete"
        baseline = _accepted_statement(prototype)
        exported = prototype.export_audit()
        assert exported["revision"] > 0
        assert exported["sources"] == [{
            "doc_id": baseline.doc_id, "sha256": baseline.doc_id,
            "byte_count": len(b"synthetic source"),
        }]
        assert prototype.check_export_structure(
            exported, expected_head=prototype.head
        ) == {
            "structural": True, "authenticated": False,
            "revision": exported["revision"],
        }
    record_property("positive_complete_sql_and_detached_structure", "passed")

    application_root = tmp_path.resolve() / "application"
    assert not application_root.exists()
    with SQLAuthority.create(
        application_root, passphrase, verification="complete", application=True
    ) as application:
        assert application.verification == "complete"
        accepted = _accepted_statement(application)
        assert accepted.doc_id == baseline.doc_id
        assert accepted.account_id
        sql_head = application.head
        terminal = application.terminal
        assert set(terminal) == {
            "root_id", "sequence", "head", "sql_revision", "sql_head",
        }
        assert terminal["sequence"] > 1
        assert terminal["sql_revision"] == sql_head["revision"]
        assert terminal["sql_head"] == sql_head["head"]
        assert application.verify(
            expected_head=sql_head, expected_terminal=terminal
        )["verified"] is True

    with SQLAuthority.open(
        application_root, passphrase, verification="complete", application=True
    ) as reopened:
        assert reopened.account(accepted.account_id)["running_balance"] == "90"
        assert reopened.original(accepted.doc_id) == b"synthetic source"
        assert len(reopened.transactions(accepted.account_id)) == 1
        assert reopened.terminal == terminal
        assert reopened.verify(
            expected_head=sql_head, expected_terminal=terminal
        )["verified"] is True

    assert _fresh_keyless_check(application_root, terminal) == {"result": {
        "structural": True, "authenticated": False,
        "root_id": terminal["root_id"], "terminal": terminal,
    }}
    record_property("fresh_process_keyless_live_chain", "passed")

    terminal_path = application_root / "terminal.json"
    damaged = json.loads(terminal_path.read_text(encoding="utf-8"))
    assert damaged["head"] == terminal["head"]
    damaged["head"] = ("1" if damaged["head"][0] == "0" else "0") + damaged["head"][1:]
    terminal_path.write_text(
        json.dumps(damaged, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    assert _fresh_keyless_check(application_root, terminal) == {
        "refused": "IntegrityError",
    }
    record_property("fresh_process_keyless_terminal_tamper_refusal", "passed")


@pytest.mark.parametrize("reader", (
    "head", "item", "original", "receipt", "movements", "transfer_inventory",
    "transfer_bindings", "transfer_links", "transfer_suggestions", "transfer_assertions",
    "transfer_decisions", "transfer_as_of", "account", "transactions", "postings",
    "balance_observations", "source_admission", "source_transactions", "source_occurrences",
    "source_observations", "identity_decision", "resolve_source_identity", "export_audit", "verify",
))
def test_application_each_canonical_reader_refuses_unrelated_posting_tamper(tmp_path, reader):
    from viva.sql_authority import IntegrityError
    from test_sql_authority_complete_verification import _answer
    with SQLAuthority.create(tmp_path.resolve() / "application", secrets.token_urlsafe(32),
                             verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        _answer(owner, reader, accepted)
        changed = owner._engine._db.execute(
            "UPDATE postings SET amount='999' WHERE doc_id=? AND account_id=?",
            (accepted.doc_id, accepted.account_id),
        )
        assert changed.rowcount == 1
        with pytest.raises(IntegrityError):
            _answer(owner, reader, accepted)


@pytest.mark.parametrize("application", [None, 0, 1, "yes", [], {}])
@pytest.mark.parametrize("method", ["create", "open"])
def test_application_selector_refuses_before_effects(tmp_path, application, method):
    from viva.sql_authority import AuthorityError
    root = tmp_path.resolve() / "untouched"
    with pytest.raises(AuthorityError, match="application selection"):
        getattr(SQLAuthority, method)(root, secrets.token_urlsafe(32),
                                     verification="complete", application=application)
    assert not root.exists()


def test_application_requires_complete_and_closed_format_routing(tmp_path):
    from viva.sql_authority import AuthorityError
    passphrase = secrets.token_urlsafe(32)
    with pytest.raises(AuthorityError, match="complete"):
        SQLAuthority.create(tmp_path.resolve() / "untouched", passphrase, application=True)
    assert not (tmp_path / "untouched").exists()
    with SQLAuthority.create(tmp_path.resolve() / "prototype", passphrase):
        pass
    with pytest.raises((AuthorityError, FileNotFoundError)):
        SQLAuthority.open(tmp_path.resolve() / "prototype", passphrase, verification="complete", application=True)
    root = tmp_path.resolve() / "application"
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        _accepted_statement(owner)
        before = owner.terminal
        with pytest.raises(AuthorityError):
            SQLAuthority.open(root, passphrase)
        with pytest.raises(AuthorityError):
            SQLAuthority.open(root / "sql", passphrase, verification="complete")
        assert owner.terminal == before
        assert not hasattr(owner, "_db")
        assert not hasattr(owner, "key")
        assert not hasattr(owner, "engine")


@pytest.mark.parametrize("mutation", ["trigger", "view", "index", "known_table", "constraint"])
def test_application_exact_schema_refuses_before_answer_or_mutation(tmp_path, mutation):
    from viva.sql_authority import IntegrityError
    with SQLAuthority.create(tmp_path.resolve() / "application", secrets.token_urlsafe(32),
                             verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        db = owner._engine._db
        if mutation == "trigger":
            db.execute("CREATE TRIGGER unwanted AFTER INSERT ON documents BEGIN SELECT 1; END")
        elif mutation == "view":
            db.execute("CREATE VIEW unwanted AS SELECT * FROM accounts")
        elif mutation == "index":
            db.execute("CREATE INDEX unwanted ON documents(byte_count)")
        elif mutation == "known_table":
            db.execute("ALTER TABLE control RENAME TO replaced_control")
            db.execute("CREATE TABLE control(singleton,revision,head,mac)")
        else:
            db.execute("PRAGMA writable_schema=ON")
            changed = db.execute("UPDATE sqlite_schema SET sql=sql || ' ' WHERE name='documents' AND type='table'")
            assert changed.rowcount == 1
            db.execute("PRAGMA writable_schema=OFF")
        changes = db.total_changes
        with pytest.raises(IntegrityError, match="schema"):
            owner.account(accepted.account_id)
        with pytest.raises(IntegrityError, match="schema"):
            owner.reject_transfer("synthetic-missing-reference", today="2026-02-01")
        assert db.total_changes == changes


@pytest.mark.parametrize("mutation", ["remove_middle", "reorder", "head_delete", "head_change", "duplicate_key", "noncanonical", "nonfinite", "unknown"])
def test_keyless_actual_live_history_rejects_structural_tamper(tmp_path, mutation):
    from viva.sql_authority import IntegrityError
    from viva.sql_authority.application import ApplicationSQLAuthority
    from viva.sql_authority.application_io import RecoveryRequired
    root = tmp_path.resolve() / "application"
    with SQLAuthority.create(root, secrets.token_urlsafe(32), verification="complete", application=True) as owner:
        _accepted_statement(owner)
        expected = owner.terminal
    assert ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=expected)["structural"] is True
    members = sorted((root / "history").iterdir())
    assert len(members) > 2
    if mutation == "remove_middle":
        members[1].unlink()
    elif mutation == "reorder":
        a, b = members[1].read_bytes(), members[2].read_bytes()
        members[1].write_bytes(b)
        members[2].write_bytes(a)
    elif mutation == "head_delete":
        (root / "terminal.json").unlink()
    elif mutation == "head_change":
        value = json.loads((root / "terminal.json").read_text())
        value["head"] = "0" * 64
        (root / "terminal.json").write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    elif mutation == "duplicate_key":
        data = members[0].read_text()
        members[0].write_text('{"version":1,' + data[1:])
    elif mutation == "noncanonical":
        members[0].write_text(members[0].read_text() + "\n")
    elif mutation == "nonfinite":
        members[0].write_text('{"version":NaN}')
    else:
        (root / "history" / "unknown.json").write_text("{}")
        (root / "history" / "unknown.json").chmod(0o600)
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises((IntegrityError, RecoveryRequired)):
        ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=expected)
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("forgery", ["missing", "copied", "foreign", "expired", "engine_changed"])
def test_private_engine_binding_cannot_downgrade_history(tmp_path, forgery):
    import copy
    from viva.sql_authority import AuthorityError
    from viva.sql_authority.application import _ISSUED
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(tmp_path.resolve() / "application", passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        binding = owner._engine._application_binding
        with SQLAuthority.create(tmp_path.resolve() / "other", passphrase, verification="complete", application=True) as other:
            if forgery == "missing":
                owner._engine._application_binding = None
            elif forgery == "copied":
                owner._engine._application_binding = copy.copy(binding)
            elif forgery == "foreign":
                owner._engine._application_binding = other._binding
            elif forgery == "expired":
                record = _ISSUED.pop(id(binding))
            else:
                binding.engine = other._engine
            try:
                with pytest.raises(AuthorityError):
                    owner.account(accepted.account_id)
            finally:
                owner._engine._application_binding = binding
                binding.engine = owner._engine
                if forgery == "expired":
                    _ISSUED[id(binding)] = record
        assert owner.account(accepted.account_id)["running_balance"] == "90"


def test_observed_handle_refuses_old_history_and_accepts_verified_extension(tmp_path):
    from viva.sql_authority import IntegrityError
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        old_terminal = (root / "terminal.json").read_bytes()
        old_members = {path.name: path.read_bytes() for path in (root / "history").iterdir()}
        with SQLAuthority.open(root, passphrase, verification="complete", application=True) as second:
            result = ingest(second, b"synthetic forward source", opening="90", closing="80", start="2026-01-31", end="2026-02-28")
            assert result.status == "accepted"
        assert owner.account(accepted.account_id)["running_balance"] == "80"
        assert owner.terminal["sequence"] > len(old_members)
        for path in (root / "history").iterdir():
            if path.name not in old_members:
                path.unlink()
        (root / "terminal.json").write_bytes(old_terminal)
        with pytest.raises(IntegrityError, match="prefix"):
            owner.account(accepted.account_id)


def test_application_genuine_transfer_actions_retain_original_money_and_unlink_history(tmp_path):
    from test_sql_authority_transfers import fixed_initial
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        a, b, c = fixed_initial(owner)
        original_postings = {item.doc_id: owner.postings(item.doc_id) for item in (a, b, c)}
        balances = {item.account_id: owner.account(item.account_id)["running_balance"] for item in (a, b, c)}
        suggestion = owner.transfer_suggestions()[0]
        source, counterpart = suggestion["a"], suggestion["candidates"][0]
        assert owner.confirm_transfer(source, counterpart, today="2024-03-01") is True
        assert owner.confirm_transfer(source, counterpart, today="2024-03-01") is False
        assert owner.transfer_links()[0]["by"] == "human"
        assert owner.unlink_transfer(source, counterpart, today="2024-03-02") is True
        assert owner.transfer_links() == []
        assert len(owner.transfer_as_of("2024-03-01")["links"]) == 1
        assert len(owner.transfer_as_of("2024-03-02")["links"]) == 0
        remaining = owner.transfer_suggestions()
        assert remaining
        assert owner.reject_transfer(remaining[0]["a"], today="2024-03-03") is True
        assertions = owner.transfer_assertions()
        assert any(row["event_type"] == "TransferLinked" and row["body"]["by"] == "human" for row in assertions)
        assert any(row["event_type"] == "TransferUnlinked" for row in assertions)
        assert assertions[-1]["body"]["b"] == ""
        for item in (a, b, c):
            assert owner.postings(item.doc_id) == original_postings[item.doc_id]
            assert owner.account(item.account_id)["running_balance"] == balances[item.account_id]
        terminal = owner.terminal
        assert owner.verify()["verified"] is True
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as reopened:
        assert reopened.terminal == terminal
        assert reopened.transfer_assertions() == assertions
        assert len(reopened.transfer_as_of("2024-03-01")["links"]) == 1


def test_wrong_passphrase_and_foreign_prefix_refuse_without_rewriting(tmp_path):
    from viva.crypto import CryptoError
    from viva.sql_authority import IntegrityError
    from viva.sql_authority.application import ApplicationSQLAuthority
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        _accepted_statement(owner)
        terminal = owner.terminal
    before = {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(CryptoError):
        SQLAuthority.open(root, secrets.token_urlsafe(32), verification="complete", application=True)
    with pytest.raises(IntegrityError):
        ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=dict(terminal, root_id="f" * 64))
    with pytest.raises(IntegrityError):
        ApplicationSQLAuthority.recover(root, passphrase, expected_prefix=dict(terminal, root_id="f" * 64))
    assert before == {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_equivalent_keyed_sql_resealing_cannot_replace_authoritative_operation_bytes(tmp_path):
    from viva.sql_authority import IntegrityError
    from viva.sql_authority.application import ApplicationSQLAuthority
    from test_sql_authority_integrity import _resealed_export
    root = tmp_path.resolve() / "application"
    with SQLAuthority.create(root, secrets.token_urlsafe(32), verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        terminal = owner.terminal
        engine = owner._engine
        original = owner.export_audit()
        altered = _resealed_export(engine, original, lambda _payload: None)
        assert altered["head"] != original["head"]
        original_state = engine._reconstruct(original, {"revision": original["revision"], "head": original["head"]})
        altered_state = engine._reconstruct(altered, {"revision": altered["revision"], "head": altered["head"]})
        assert altered_state == original_state
        db = engine._db
        db.execute("BEGIN IMMEDIATE")
        for sequence, previous, envelope, digest in altered["records"]:
            assert db.execute("UPDATE audit SET previous_hash=?,envelope=?,record_hash=? WHERE sequence=?",
                              (previous, envelope, digest, sequence)).rowcount == 1
        for revision, head, mac in altered["commits"]:
            assert db.execute("UPDATE commits SET head=?,mac=? WHERE revision=?", (head, mac, revision)).rowcount == 1
        db.execute("UPDATE control SET head=?,mac=? WHERE singleton=1", (altered["head"], altered["mac"]))
        db.execute("COMMIT")
        assert db.execute("SELECT current_amount FROM accounts WHERE account_id=?", (accepted.account_id,)).fetchone() == ("90",)
        with pytest.raises(IntegrityError, match="authoritative sealed operations"):
            owner.account(accepted.account_id)
        # Keyless structural continuity does not authenticate the SQL representation.
        assert ApplicationSQLAuthority.verify_live_chain(root, expected_terminal=terminal)["structural"] is True


def test_engine_handoff_cannot_cross_another_threads_held_operation(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from viva.sql_authority import AuthorityError
    with SQLAuthority.create(tmp_path.resolve() / "application", secrets.token_urlsafe(32),
                             verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        with owner.operation("phase"):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(owner.account, accepted.account_id)
                with pytest.raises(AuthorityError, match="another thread"):
                    future.result(timeout=5)
        assert owner.account(accepted.account_id)["running_balance"] == "90"
