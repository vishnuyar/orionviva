"""Verified encrypted directory copies never overwrite a destination."""
import secrets

import pytest

from viva.sql_authority import SQLAuthority, AuthorityError
from viva.sql_authority.application import ApplicationSQLAuthority
from test_sql_application_history import _accepted_statement


pytestmark = pytest.mark.production_kdf


def _bytes(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_encrypted_backup_restore_preserve_exact_sealed_history_and_finances(tmp_path):
    root = tmp_path.resolve() / "application"
    backup = tmp_path.resolve() / "backup"
    restored = tmp_path.resolve() / "restored"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        terminal, head = owner.terminal, owner.head
        original_members = _bytes(root)
        receipt = owner.backup(backup, passphrase=passphrase, expected_terminal=terminal)
        assert receipt == {"format": "viva-sql-application-v1", "root_id": terminal["root_id"], "terminal": terminal}
        assert _bytes(root) == original_members
        assert owner.head == head and owner.terminal == terminal
    original = _bytes(root)
    copied = _bytes(backup)
    for name, data in original.items():
        if name.endswith(".lock"):
            continue
        assert copied[name] == data
    assert not (backup / "sql" / "authority.db").read_bytes().startswith(b"SQLite format 3")
    assert all(b"synthetic source" not in value for name, value in copied.items() if name != "application.lock")
    assert not list((backup / "pending").iterdir())
    assert not list((backup / "sql" / "originals").glob("*.lock"))
    assert (root / "application.lock").stat().st_ino != (backup / "application.lock").stat().st_ino
    restored_receipt = ApplicationSQLAuthority.restore(backup, restored, passphrase, expected_terminal=terminal)
    assert restored_receipt == receipt
    with SQLAuthority.open(restored, passphrase, verification="complete", application=True) as owner:
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert owner.original(accepted.doc_id) == b"synthetic source"
        assert len(owner.transactions(accepted.account_id)) == 1
        assert owner.head == head and owner.terminal == terminal
        assert owner.verify(expected_head=head, expected_terminal=terminal)["verified"] is True


@pytest.mark.parametrize("method", ["backup", "restore"])
@pytest.mark.parametrize("destination_kind", ["file", "empty_directory", "nonempty_directory", "symlink"])
def test_backup_and_restore_refuse_existing_destinations_without_overwrite(tmp_path, method, destination_kind):
    root = tmp_path.resolve() / "application"
    destination = tmp_path.resolve() / "destination"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        _accepted_statement(owner)
        if destination_kind == "file":
            destination.write_bytes(b"synthetic preexisting destination")
        elif destination_kind == "symlink":
            destination.symlink_to(root, target_is_directory=True)
        else:
            destination.mkdir(mode=0o700)
            if destination_kind == "nonempty_directory":
                (destination / "retained").write_bytes(b"synthetic preexisting evidence")
        before = _bytes(root)
        retained = destination.lstat()
        with pytest.raises((AuthorityError, FileExistsError)):
            if method == "backup":
                owner.backup(destination, passphrase=passphrase)
            else:
                ApplicationSQLAuthority.restore(root, destination, passphrase)
        assert _bytes(root) == before
        after = destination.lstat()
        assert (retained.st_dev, retained.st_ino) == (after.st_dev, after.st_ino)
        assert not list(tmp_path.glob(".sql-backup-*"))


@pytest.mark.parametrize("method", ["backup", "restore"])
def test_wrong_passphrase_has_no_destination_or_staging_effects(tmp_path, method):
    root = tmp_path.resolve() / "application"
    destination = tmp_path.resolve() / "destination"
    passphrase = secrets.token_urlsafe(32)
    wrong = secrets.token_urlsafe(32)
    from viva.crypto import CryptoError
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        _accepted_statement(owner)
        before = _bytes(root)
        with pytest.raises(CryptoError):
            if method == "backup":
                owner.backup(destination, passphrase=wrong)
            else:
                ApplicationSQLAuthority.restore(root, destination, wrong)
        assert not destination.exists()
        assert not list(tmp_path.glob(".sql-backup-*"))
        assert _bytes(root) == before


@pytest.mark.parametrize("point", ["after_backup_staging", "after_backup_member", "after_backup_verification", "after_backup_publication"])
def test_injected_backup_failure_preserves_source_and_private_staging(tmp_path, point):
    root = tmp_path.resolve() / "application"
    destination = tmp_path.resolve() / "destination"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        before, terminal = _bytes(root), owner.terminal
        def fault(actual):
            if actual == point:
                raise OSError("injected backup boundary failure")
        owner._fault = fault
        with pytest.raises(OSError, match="backup boundary"):
            owner.backup(destination, passphrase=passphrase)
        owner._fault = lambda _point: None
        assert _bytes(root) == before
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        if point == "after_backup_publication":
            assert destination.is_dir()
            assert not list(tmp_path.glob(".sql-backup-*"))
            assert ApplicationSQLAuthority.verify_live_chain(destination, expected_terminal=terminal)["structural"] is True
        else:
            assert not destination.exists()
            stages = list(tmp_path.glob(".sql-backup-*"))
            assert len(stages) == 1
            assert stages[0].stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("kind", ["file", "directory"])
def test_actual_native_no_replace_preserves_existing_empty_directory(tmp_path, kind):
    from viva.sql_authority import application_io as io
    source = tmp_path.resolve() / "prepared"
    destination = tmp_path.resolve() / "existing-empty-directory"
    if kind == "file":
        io.exclusive_write(source, b"synthetic exact prepared bytes")
    else:
        io.mkdir(source)
    io.mkdir(destination)
    old = destination.stat()
    with pytest.raises(OSError):
        io.no_replace(source, destination)
    assert source.exists()
    new = destination.stat()
    assert (old.st_dev, old.st_ino) == (new.st_dev, new.st_ino)
    assert not list(destination.iterdir())


def test_trusted_final_boundary_is_not_inferred_from_copied_files(tmp_path):
    from viva.sql_authority import IntegrityError
    root = tmp_path.resolve() / "application"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        _accepted_statement(owner)
        wrong = dict(owner.terminal, head="0" * 64)
        with pytest.raises(IntegrityError):
            owner.backup(tmp_path.resolve() / "destination", passphrase=passphrase, expected_terminal=wrong)
        assert not (tmp_path / "destination").exists()
        assert not list(tmp_path.glob(".sql-backup-*"))


@pytest.mark.parametrize("point", ["after_backup_staging", "after_backup_member", "after_backup_verification", "after_backup_publication"])
@pytest.mark.parametrize("method", ["backup", "restore"])
def test_actual_backup_process_exit_leaves_one_explicit_copy_outcome(tmp_path, point, method):
    import json
    from test_sql_application_recovery import _process
    root = tmp_path.resolve() / "application"
    destination = tmp_path.resolve() / "destination"
    passphrase = secrets.token_urlsafe(32)
    with SQLAuthority.create(root, passphrase, verification="complete", application=True) as owner:
        accepted = _accepted_statement(owner)
        terminal = owner.terminal
        if method == "restore":
            source = tmp_path.resolve() / "closed-backup"
            owner.backup(source, passphrase=passphrase)
        else:
            source = root
    before = _bytes(root)
    before_source = _bytes(source)
    program = """
import os
from pathlib import Path
from viva.sql_authority import SQLAuthority
from viva.sql_authority.application import ApplicationSQLAuthority
original_init=ApplicationSQLAuthority.__init__
def controlled_init(self,*args,**kwargs):
    original_init(self,*args,**kwargs)
    if self.root == Path(request["source"]):
        def fault(point):
            if point == request["point"]:
                print(json.dumps({"interrupted": point,"actual_process": True}),flush=True)
                os._exit(73)
        self._fault=fault
ApplicationSQLAuthority.__init__=controlled_init
if request["method"] == "restore":
    ApplicationSQLAuthority.restore(Path(request["source"]),Path(request["destination"]),request["passphrase"])
else:
    owner=SQLAuthority.open(Path(request["source"]),request["passphrase"],verification="complete",application=True)
    owner.backup(Path(request["destination"]),passphrase=request["passphrase"])
raise AssertionError("backup process interruption was not reached")
"""
    result = _process(program, dict(root=str(root), source=str(source), destination=str(destination), passphrase=passphrase, point=point, method=method), root)
    assert result.returncode == 73, result.stderr
    assert json.loads(result.stdout) == {"interrupted": point, "actual_process": True}
    assert _bytes(root) == before
    assert _bytes(source) == before_source
    with SQLAuthority.open(root, passphrase, verification="complete", application=True) as owner:
        assert owner.account(accepted.account_id)["running_balance"] == "90"
        assert len(owner.transactions(accepted.account_id)) == 1
    if point == "after_backup_publication":
        assert destination.is_dir()
        assert not list(tmp_path.glob(".sql-backup-*"))
        assert ApplicationSQLAuthority.verify_live_chain(destination, expected_terminal=terminal)["structural"] is True
    else:
        assert not destination.exists()
        stages = list(tmp_path.glob(".sql-backup-*"))
        assert len(stages) == 1
        assert stages[0].stat().st_mode & 0o077 == 0
