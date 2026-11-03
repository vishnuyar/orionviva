"""Encrypted closed-directory snapshots with verification before publication."""
from pathlib import Path
import secrets

from . import application_io as io
from . import application_history as history
from .store import AuthorityError, IntegrityError


def _destination(source, destination):
    destination = Path(destination).absolute()
    io.directory(destination.parent, private=False)
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("backup destination already exists")
    if source == destination or source in destination.parents or destination in source.parents:
        raise AuthorityError("backup requires distinct nonoverlapping roots")
    return destination


def _copy(owner, staging):
    source = owner.root
    for name in ("history", "pending", "sql", "sql/originals"):
        io.mkdir(staging / name)
    for relative in ("application.json", "terminal.json", "sql/authority.json", "sql/authority.db"):
        io.exclusive_write(staging / relative, io.read(source / relative))
        owner._fault("after_backup_member")
    for member in sorted((source / "history").iterdir()):
        io.exclusive_write(staging / "history" / member.name, io.read(member))
        owner._fault("after_backup_member")
    for member in sorted((source / "sql" / "originals").iterdir()):
        if member.suffix == ".blob":
            io.exclusive_write(staging / "sql" / "originals" / member.name, io.read(member))
            owner._fault("after_backup_member")
        elif member.suffix != ".lock":
            raise IntegrityError("unknown source member during backup")
    lock = io.FileLock(staging / "application.lock", create=True)
    lock.close()
    for relative in ("history", "pending", "sql/originals", "sql", "."):
        io.sync_directory(staging / relative)


def backup(owner, destination, *, passphrase, expected_terminal=None):
    from .application import ApplicationSQLAuthority, _metadata
    owner._check_open()
    destination = _destination(owner.root, destination)
    with owner.operation("decision"):
        # Credential verification precedes creation of any staging artifact.
        metadata, _key = _metadata(owner.root, passphrase)
        if metadata != owner._metadata:
            raise IntegrityError("backup source metadata changed")
        with owner._engine._snapshot():
            owner._engine._verify_current()
            captured = dict(owner._observed)
            if expected_terminal is not None and history.boundary(expected_terminal) != captured:
                raise IntegrityError("backup expected terminal differs")
            staging = destination.parent / (".sql-backup-" + secrets.token_hex(32))
            io.mkdir(staging)
            io.sync_directory(staging.parent)
            owner._fault("after_backup_staging")
            _copy(owner, staging)
            with ApplicationSQLAuthority.open(
                staging, passphrase, curated_source=owner._engine._curated_owner
            ) as verified:
                verified.verify(expected_terminal=captured)
                if verified.terminal != captured:
                    raise IntegrityError("staged backup terminal differs")
            owner._fault("after_backup_verification")
            io.no_replace(staging, destination)
            owner._fault("after_backup_publication")
            return dict(format=history.FORMAT, root_id=captured["root_id"], terminal=captured)


def restore(backup_directory, destination, passphrase, *, curated_source=None, expected_terminal=None):
    from .application import ApplicationSQLAuthority
    source = io.directory(backup_directory)
    destination = _destination(source, destination)
    with ApplicationSQLAuthority.open(source, passphrase, curated_source=curated_source) as owner:
        return backup(owner, destination, passphrase=passphrase, expected_terminal=expected_terminal)
