"""Injected vault-backed transfer actions: a copy out, and a copy back.

This module knows neither the vault implementation nor the desktop transport. A
sidecar entry point injects one already-open vault and gets back the handlers
for the transfer actions this build serves.

**Neither action touches the open vault in place.** The export reads the files
this vault is made of and writes them somewhere else; the restore writes into a
directory that holds nothing and reads back what it wrote. There is no branch in
either that opens the running vault for writing, which is what makes it safe to
offer them while a vault is open.

**A refusal here is an ordinary reply.** A name already taken, a folder in use
and a file that would not read back are three different things to be told, and
each asks a person to do something different next; a single "export failed"
would ask them to guess. The engine's own exception text never travels — it can
carry a path, and worse, a message shaped like an answer — so each branch is
matched to a machine reason and the sentence is the pack's.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from viva.surface import ActionOutcome

from .handlers import BridgeRequestError
from .jobs import JobCancelled, JobRegistry

# Why a transfer was refused, in the machine's own words. Each names a distinct
# thing that stopped, and each is paired with exactly one reviewed sentence.
ARCHIVE_EXISTS = "archive_exists"
VAULT_INCOMPLETE = "vault_incomplete"
ARCHIVE_UNWRITABLE = "archive_unwritable"
DIRECTORY_OCCUPIED = "directory_occupied"
ARCHIVE_UNREADABLE = "archive_unreadable"
ARCHIVE_UNSAFE = "archive_unsafe"
CANCELLED = "job_cancelled"

# The steps each declares, in the order it reaches them. Every one is a thing
# that happens, and the export's are deliberately not the restore's: an archive
# is written in two moves and read back in three, and one list standing for both
# would move a bar past a place nothing happens.
EXPORT_STEPS = ("listed", "written")
RESTORE_STEPS = ("unpacked", "checked", "read")

# How the engine's own way of failing is matched to a reason a person can be
# told. It is read off the sentence the engine raised because that is where the
# distinction lives; nothing here re-derives which failure happened by looking
# at the disk a second time, which would be a second answer to one question.
_REASONS: tuple[tuple[str, str], ...] = (
    ("already exists", ARCHIVE_EXISTS),
    ("this vault has no", VAULT_INCOMPLETE),
    ("could not be written", ARCHIVE_UNWRITABLE),
    ("already holds something", DIRECTORY_OCCUPIED),
    ("outside a vault's own two places", ARCHIVE_UNSAFE),
)

_SENTENCES: dict[str, str] = {
    ARCHIVE_EXISTS: "vault_export_exists",
    VAULT_INCOMPLETE: "vault_export_incomplete",
    ARCHIVE_UNWRITABLE: "vault_export_unwritable",
    DIRECTORY_OCCUPIED: "vault_restore_occupied",
    ARCHIVE_UNREADABLE: "vault_restore_unreadable",
    ARCHIVE_UNSAFE: "vault_restore_unsafe",
}


class VaultTransferActions:
    """Adapt one already-open vault into the allowlisted transfer handlers."""

    def __init__(self, vault: Any, jobs: JobRegistry | None = None) -> None:
        self._vault = vault
        self._jobs = jobs if jobs is not None else JobRegistry()

    def export(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Write this whole vault to one file, decrypting nothing.

        The reply says what was written about — how many files and how many
        documents — and never what any of them holds. A count of documents is
        already on the documents screen; a name from inside one is not."""
        from viva.persona import moment
        from viva.vault_transfer import TransferError, export_vault

        archive = _one_path(payload, "archive", "viva.vault.export")
        job = self._jobs.open("viva.vault.export", EXPORT_STEPS)
        try:
            with job:
                job.checkpoint()
                job.reached("listed")
                job.checkpoint()
                written = export_vault(Path(self._vault.directory), archive)
                job.reached("written")
                return ActionOutcome(
                    "completed", moment("vault_exported"),
                    state={"job_id": job.job_id, **written.as_dict()},
                ).as_dict()
        except JobCancelled:
            return _stopped(job.job_id)
        except TransferError as exc:
            reason = _reason_for(exc, ARCHIVE_UNWRITABLE)
            job.fail(reason)
            return _refused(reason, job.job_id)

    def restore(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Bring a vault back into a directory of its own, and read it.

        The reply reports what reading it established rather than what
        unpacking it attempted: how many records the chain carried and how many
        documents decrypted back to their own content. Nothing here reports a
        restore that was not read."""
        from viva.persona import moment
        from viva.vault_transfer import TransferError, restore_vault

        archive, directory, passphrase = _restore_request(payload)
        job = self._jobs.open("viva.vault.restore", RESTORE_STEPS)
        try:
            with job:
                job.checkpoint()
                job.reached("unpacked")
                job.checkpoint()
                job.reached("checked")
                job.checkpoint()
                brought = restore_vault(archive, directory, passphrase)
                job.reached("read")
                return ActionOutcome(
                    "completed", moment("vault_restored"),
                    state={"job_id": job.job_id, **brought.as_dict()},
                ).as_dict()
        except JobCancelled:
            return _stopped(job.job_id)
        except TransferError as exc:
            reason = _reason_for(exc, ARCHIVE_UNREADABLE)
            job.fail(reason)
            return _refused(reason, job.job_id)


def _reason_for(exc: Exception, fallback: str) -> str:
    said = str(exc)
    for phrase, reason in _REASONS:
        if phrase in said:
            return reason
    return fallback


def _refused(reason: str, job_id: str) -> dict[str, Any]:
    from viva.persona import moment

    return ActionOutcome("refused", moment(_SENTENCES[reason]), reason=reason,
                         state={"job_id": job_id}).as_dict()


def _stopped(job_id: str) -> dict[str, Any]:
    from viva.persona import moment

    return ActionOutcome("refused", moment("jobs_stopped"), reason=CANCELLED,
                         state={"job_id": job_id}).as_dict()


def _one_path(payload: Mapping[str, Any], field: str, operation: str) -> Path:
    allowed = {field}
    _fenced(payload, allowed, operation)
    return _path(payload, field)


def _restore_request(payload: Mapping[str, Any]) -> tuple[Path, Path, str]:
    allowed = {"archive", "directory", "passphrase"}
    _fenced(payload, allowed, "viva.vault.restore")
    passphrase = payload.get("passphrase")
    if not isinstance(passphrase, str) or not passphrase:
        raise BridgeRequestError("passphrase must be a non-empty string")
    return _path(payload, "archive"), _path(payload, "directory"), passphrase


def _fenced(payload: Mapping[str, Any], allowed: set[str], operation: str) -> None:
    unexpected = set(payload) - allowed
    if unexpected:
        raise BridgeRequestError(
            f"{operation} does not accept fields: {', '.join(sorted(unexpected))}")


def _path(payload: Mapping[str, Any], field: str) -> Path:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BridgeRequestError(f"{field} must be a non-empty string")
    return Path(value)
