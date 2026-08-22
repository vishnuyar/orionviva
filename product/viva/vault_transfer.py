"""Taking a whole vault somewhere else, and bringing one back.

What travels is not a folder. It is an event log carrying its own key
derivation salt, a head file holding a count, a head hash and a message
authentication code, a raw-store header carrying a **second, independently
salted** derivation, and the content-addressed encrypted blobs beneath it. Two
keystreams and a chain head. Anything that sizes this as a copy will lose one
of those halves and produce an archive that opens and then cannot read its own
documents.

Three properties hold everything else up.

**Nothing is decrypted to travel.** Every member goes into the archive as the
bytes that were on disk. The export therefore needs no passphrase, and an
archive on a stranger's disk is exactly as readable as the vault was — which is
to say not at all.

**The manifest carries no vault content.** It names each member, its length and
the digest of its bytes. A file name and a digest of ciphertext say nothing
about a person's money, which is what makes it safe to read the manifest
without a key and check an archive somebody handed you.

**A restore is verified on a copy or it is not a restore.** Restoring writes
into a directory that does not already hold a vault, never over one, and then
opens what it wrote with the passphrase and reads it: the chain is walked, the
head is checked against it, and every blob is decrypted and re-addressed
against its own content. A restore that only unpacked files would report
success for an archive whose second keystream never arrived.
"""

from __future__ import annotations

import hashlib
import json
import logging
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# The archive format, stamped into every manifest. It is read back on restore
# and refused when it is not one this build knows: an archive from a later
# format may hold a member this build would silently not restore, and a vault
# missing a member is a vault that opens and cannot read itself.
FORMAT = "orionvault-v1"

# What the manifest is called inside the archive. It is the first thing read
# and it is never itself a vault member.
MANIFEST = "manifest.json"

# The parts of a vault, by the name each has on disk. Every one of them is
# required for a vault to be whole, and the export refuses rather than writing
# an archive that is missing one — a partial archive that restores is worse
# than one that will not, because the loss shows up months later as a document
# that cannot be opened.
EVENTS = "events.jsonl"
HEAD = "events.jsonl.head"
RAW_DIRECTORY = "raw"
RAW_HEADER = "raw/raw-header.json"
REQUIRED = (EVENTS, HEAD, RAW_HEADER)


class TransferError(RuntimeError):
    """A vault could not be taken out or brought back, and nothing was left half done."""


@dataclass(frozen=True)
class Member:
    """One file of a vault, as the archive carries it."""

    name: str
    length: int
    digest: str

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "length": self.length, "digest": self.digest}


@dataclass(frozen=True)
class ExportResult:
    """What an export wrote, and what it wrote about."""

    archive: Path
    members: tuple[Member, ...]
    blob_count: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "archive": str(self.archive),
            "member_count": len(self.members),
            "blob_count": self.blob_count,
            "byte_length": sum(member.length for member in self.members),
        }


@dataclass(frozen=True)
class RestoreResult:
    """What a restore produced, and what reading it established.

    Every field here is something that was checked rather than assumed. A
    restore that could not establish one of them raises instead of reporting
    it false: a half-restored vault on disk with a report saying so is a thing
    somebody will keep.
    """

    directory: Path
    event_count: int
    blob_count: int
    chain_intact: bool = True
    blobs_readable: bool = True
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "event_count": self.event_count,
            "blob_count": self.blob_count,
            "chain_intact": self.chain_intact,
            "blobs_readable": self.blobs_readable,
            "warnings": list(self.warnings),
        }


def _digest(path: Path) -> tuple[int, str]:
    """The length and the digest of one file's bytes, read in one pass."""
    hashed = hashlib.sha256()
    length = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            hashed.update(chunk)
            length += len(chunk)
    return length, hashed.hexdigest()


def vault_members(directory: Path) -> tuple[Member, ...]:
    """Every file of this vault, in a fixed order, with each one's digest.

    The order is fixed so that two exports of an unchanged vault produce the
    same manifest, which is what lets one archive be compared against another
    without opening either.

    Raises TransferError when a required part is missing. A blob store with no
    blobs is not missing anything — a vault that has taken in no document is
    whole — so only the header is required under `raw/`."""
    directory = Path(directory)
    found: list[Member] = []
    for name in (EVENTS, HEAD, RAW_HEADER):
        path = directory / name
        if not path.is_file():
            raise TransferError(
                f"this vault has no {name}, so there is no whole vault to take "
                "out; nothing was written")
        length, digest = _digest(path)
        found.append(Member(name, length, digest))
    raw = directory / RAW_DIRECTORY
    for blob in sorted(raw.glob("*.blob")) if raw.is_dir() else []:
        length, digest = _digest(blob)
        found.append(Member(f"{RAW_DIRECTORY}/{blob.name}", length, digest))
    return tuple(found)


def export_vault(directory: Path, archive: Path) -> ExportResult:
    """Write one whole vault to one archive, decrypting nothing.

    The archive is written beside where it will live and moved into place at
    the end, so a run that dies half way leaves no file that looks like an
    export. Nothing is overwritten: an archive path that already exists is
    refused, because the one thing worse than no backup is a backup that was
    quietly replaced by a shorter one."""
    directory = Path(directory)
    archive = Path(archive)
    if archive.exists():
        raise TransferError(
            f"{archive.name} already exists; nothing was written, and an "
            "existing archive is never replaced in place")
    members = vault_members(directory)
    manifest = {
        "format": FORMAT,
        "members": [member.as_dict() for member in members],
    }
    archive.parent.mkdir(parents=True, exist_ok=True)
    partial = archive.with_name(archive.name + ".partial")
    try:
        with tarfile.open(partial, "w:gz") as bundle:
            written = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(written)
            # A fixed mtime and a cleared owner: an archive of an unchanged
            # vault is the same bytes whenever it is written, which is what
            # makes two of them comparable.
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            import io

            bundle.addfile(info, io.BytesIO(written))
            for member in members:
                source = directory / member.name
                entry = bundle.gettarinfo(str(source), arcname=member.name)
                entry.mtime = 0
                entry.uid = entry.gid = 0
                entry.uname = entry.gname = ""
                with source.open("rb") as handle:
                    bundle.addfile(entry, handle)
        partial.replace(archive)
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise TransferError(f"the archive could not be written: {exc}") from exc
    blob_count = sum(1 for member in members if member.name.endswith(".blob"))
    log.info("exported %d members (%d blobs) to %s",
             len(members), blob_count, archive)
    return ExportResult(archive, members, blob_count)


def read_manifest(archive: Path) -> tuple[Member, ...]:
    """What an archive says it holds, without unpacking any of it.

    Readable without the passphrase, because it holds no vault content: a name,
    a length and a digest of ciphertext. That is what lets somebody check an
    archive they were handed before deciding to restore it."""
    archive = Path(archive)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            entry = bundle.extractfile(MANIFEST)
            if entry is None:
                raise TransferError(
                    f"{archive.name} carries no {MANIFEST}, so nothing in it "
                    "can be checked against what it claims to be")
            manifest = json.loads(entry.read().decode("utf-8"))
    except (OSError, tarfile.TarError, json.JSONDecodeError) as exc:
        raise TransferError(f"{archive.name} could not be read: {exc}") from exc
    if manifest.get("format") != FORMAT:
        raise TransferError(
            f"{archive.name} is in the {manifest.get('format')!r} format and "
            f"this build restores {FORMAT!r}; nothing was unpacked")
    members = tuple(
        Member(str(item["name"]), int(item["length"]), str(item["digest"]))
        for item in manifest.get("members", []))
    missing = [name for name in REQUIRED
               if name not in {member.name for member in members}]
    if missing:
        raise TransferError(
            f"{archive.name} names no {', '.join(missing)}; a vault without "
            "one of those is one that opens and cannot read itself")
    return members


def _safe(name: str) -> bool:
    """Whether a member name is one this restore will write.

    An archive is a file somebody handed you, so nothing about a path inside it
    is trusted: an absolute path, a parent step, or a name outside the two
    places a vault keeps things is refused rather than normalised into
    something that looks acceptable."""
    if name != name.strip() or not name:
        return False
    if name.startswith("/") or ".." in Path(name).parts:
        return False
    if name in (EVENTS, HEAD, RAW_HEADER):
        return True
    parts = Path(name).parts
    return (len(parts) == 2 and parts[0] == RAW_DIRECTORY
            and parts[1].endswith(".blob"))


def restore_vault(archive: Path, directory: Path, passphrase: str) -> RestoreResult:
    """Bring a vault back into a directory that holds none, and read it.

    The destination must not already hold a vault. This is not caution about
    overwriting a file: a restore that landed on top of a live vault would mix
    two event logs under one head, and there is no later moment at which that
    could be told apart from one log.

    What comes back is verified by being read. The chain is walked and checked
    against the head, and every blob is decrypted and re-addressed against its
    own content — which is the only check that reaches the second keystream at
    all, and the one an archive missing `raw/raw-header.json` fails."""
    archive = Path(archive)
    directory = Path(directory)
    members = read_manifest(archive)
    if directory.exists() and any(directory.iterdir()):
        raise TransferError(
            f"{directory} already holds something; a vault is restored into a "
            "directory of its own, never over one that is in use")
    expected = {member.name: member for member in members}
    unsafe = [name for name in expected if not _safe(name)]
    if unsafe:
        raise TransferError(
            "this archive names a member outside a vault's own two places: "
            + ", ".join(sorted(unsafe)[:3]))

    directory.mkdir(parents=True, exist_ok=True)
    (directory / RAW_DIRECTORY).mkdir(exist_ok=True)
    try:
        with tarfile.open(archive, "r:gz") as bundle:
            for entry in bundle.getmembers():
                if entry.name == MANIFEST:
                    continue
                if entry.name not in expected:
                    raise TransferError(
                        f"{entry.name} is in this archive and not in its own "
                        "manifest; nothing that is not declared is written")
                if not entry.isfile():
                    raise TransferError(
                        f"{entry.name} is not a plain file; a vault is made of "
                        "plain files and nothing else is unpacked")
                source = bundle.extractfile(entry)
                if source is None:
                    raise TransferError(f"{entry.name} could not be read out")
                target = directory / entry.name
                with target.open("wb") as handle:
                    while chunk := source.read(1024 * 1024):
                        handle.write(chunk)
    except (OSError, tarfile.TarError) as exc:
        raise TransferError(f"{archive.name} could not be unpacked: {exc}") from exc

    for member in members:
        path = directory / member.name
        if not path.is_file():
            raise TransferError(
                f"{member.name} is named in the manifest and is not in the "
                "archive; what was unpacked is not a whole vault")
        length, digest = _digest(path)
        if (length, digest) != (member.length, member.digest):
            raise TransferError(
                f"{member.name} came out of the archive with different bytes "
                "than its manifest records; nothing about this restore is "
                "trusted")

    return _verified(directory, passphrase, members)


def _verified(directory: Path, passphrase: str,
              members: tuple[Member, ...]) -> RestoreResult:
    """Open what was restored and read it, or raise.

    This is the half that makes a restore a restore. Unpacking proves the bytes
    arrived; only opening proves that the passphrase reaches both keystreams,
    that the chain is whole, that the head agrees with it, and that every
    document can still be decrypted and still addresses its own content."""
    from .crypto import CryptoError
    from .vault import Vault

    try:
        vault = Vault.open(directory, passphrase)
    except CryptoError as exc:
        raise TransferError(
            "the restored vault would not open with that passphrase, so "
            f"nothing in it could be read: {exc}") from exc

    intact, count = vault.ledger.store.verify_chain()
    if not intact:
        raise TransferError(
            f"the restored event log breaks its own chain at record {count}; "
            "this archive does not carry a whole log")

    declared = {member.name for member in members if member.name.endswith(".blob")}
    readable = 0
    for doc_id in vault.raw.doc_ids():
        try:
            data = vault.raw.get(doc_id)
        except (CryptoError, OSError, ValueError) as exc:
            raise TransferError(
                f"a document in the restored vault could not be read back: "
                f"{exc}") from exc
        if vault.raw.fingerprint(data) != doc_id:
            raise TransferError(
                "a document in the restored vault no longer addresses its own "
                "content; what came back is not what went in")
        readable += 1
    if readable != len(declared):
        raise TransferError(
            f"the restored vault holds {readable} documents and its archive "
            f"declared {len(declared)}")

    log.info("restored %d events and %d documents into %s",
             count, readable, directory)
    return RestoreResult(directory, event_count=count, blob_count=readable)
