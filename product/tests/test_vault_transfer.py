"""A whole vault leaves, and a whole vault comes back — verified on a copy.

What travels is two independently salted keystreams and a chain head, not a
folder. Every test here is about one of the ways an archive can look like a
vault and not be one.
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from viva.ingest.raw_store import RawStore
from viva.ledger.events import document_captured
from viva.vault import Vault
from viva.vault_transfer import (EVENTS, HEAD, MANIFEST, RAW_HEADER,
                                 TransferError, export_vault, read_manifest,
                                 restore_vault, vault_members)

PASSPHRASE = "a-real-passphrase"
DOCUMENT = b"%PDF-1.4 a statement that is not a folder"


def _vault(tmp_path: Path, name: str = "vault") -> Vault:
    vault = Vault.open(tmp_path / name, PASSPHRASE)
    doc_id = vault.raw.put(DOCUMENT)
    vault.ledger.append(document_captured(
        doc_id, "statement.pdf", len(DOCUMENT), "statement", 0.9, "2026-08-01"))
    return vault


def test_every_part_of_a_vault_travels_and_nothing_else_does(tmp_path):
    """Two keystreams and a chain head. An archive that carried only the log
    would open and then fail to read a single document."""
    vault = _vault(tmp_path)

    members = {member.name for member in vault_members(vault.directory)}

    assert {EVENTS, HEAD, RAW_HEADER} <= members
    assert any(name.endswith(".blob") for name in members)


def test_a_vault_missing_its_second_keystream_is_refused_rather_than_shortened(tmp_path):
    vault = _vault(tmp_path)
    (vault.directory / RAW_HEADER).unlink()

    with pytest.raises(TransferError, match="no raw/raw-header.json"):
        vault_members(vault.directory)


def test_the_archive_carries_ciphertext_and_the_manifest_carries_no_content(tmp_path):
    """The export needs no passphrase, and the manifest is readable without
    one: a name, a length and a digest of ciphertext say nothing about money."""
    vault = _vault(tmp_path)

    export_vault(vault.directory, tmp_path / "vault.orionvault")
    with tarfile.open(tmp_path / "vault.orionvault", "r:gz") as bundle:
        manifest = json.loads(bundle.extractfile(MANIFEST).read())
        events = bundle.extractfile(EVENTS).read()

    assert b"statement.pdf" not in events
    assert DOCUMENT not in events
    assert "statement" not in json.dumps(manifest)


def test_an_export_never_replaces_an_archive_that_is_already_there(tmp_path):
    vault = _vault(tmp_path)
    archive = tmp_path / "vault.orionvault"
    export_vault(vault.directory, archive)
    before = archive.read_bytes()

    with pytest.raises(TransferError, match="already exists"):
        export_vault(vault.directory, archive)

    assert archive.read_bytes() == before


def test_an_export_that_dies_half_way_leaves_nothing_that_looks_like_one(tmp_path, monkeypatch):
    vault = _vault(tmp_path)
    archive = tmp_path / "vault.orionvault"

    def die(*_args, **_kwargs):
        raise OSError("the disk went away")

    monkeypatch.setattr(Path, "replace", die)
    with pytest.raises(TransferError, match="could not be written"):
        export_vault(vault.directory, archive)

    assert not archive.exists()
    assert not list(tmp_path.glob("*.partial"))


def test_a_round_trip_comes_back_whole_and_is_read_to_prove_it(tmp_path):
    vault = _vault(tmp_path)
    doc_id = RawStore.fingerprint(DOCUMENT)
    archive = tmp_path / "vault.orionvault"
    export_vault(vault.directory, archive)

    result = restore_vault(archive, tmp_path / "brought-back", PASSPHRASE)

    assert result.event_count == 1
    assert result.blob_count == 1
    assert result.chain_intact and result.blobs_readable
    brought_back = Vault.open(tmp_path / "brought-back", PASSPHRASE)
    assert brought_back.raw.get(doc_id) == DOCUMENT
    assert [event.event_type for event in brought_back.events()] == ["DocumentCaptured"]


def test_a_restore_never_lands_on_a_directory_that_holds_something(tmp_path):
    """Not caution about overwriting a file: two event logs under one head
    cannot be told apart from one log at any later moment."""
    vault = _vault(tmp_path)
    archive = tmp_path / "vault.orionvault"
    export_vault(vault.directory, archive)

    with pytest.raises(TransferError, match="already holds something"):
        restore_vault(archive, vault.directory, PASSPHRASE)

    assert Vault.open(vault.directory, PASSPHRASE).raw.doc_ids() == [
        RawStore.fingerprint(DOCUMENT)]


def test_a_restore_with_the_wrong_passphrase_fails_where_it_is_read(tmp_path):
    """Unpacking proves the bytes arrived. Only opening proves the passphrase
    reaches the keystreams, which is why the reply cannot be written before
    that."""
    vault = _vault(tmp_path)
    archive = tmp_path / "vault.orionvault"
    export_vault(vault.directory, archive)

    with pytest.raises(TransferError, match="would not open"):
        restore_vault(archive, tmp_path / "brought-back", "the-wrong-one")


def test_an_archive_whose_bytes_were_changed_is_refused_by_its_own_manifest(tmp_path):
    vault = _vault(tmp_path)
    archive = tmp_path / "vault.orionvault"
    export_vault(vault.directory, archive)
    members = read_manifest(archive)
    manifest = {
        "format": "orionvault-v1",
        "members": [member.as_dict() for member in members],
    }
    tampered = tmp_path / "tampered.orionvault"
    with tarfile.open(archive, "r:gz") as source, tarfile.open(tampered, "w:gz") as out:
        for entry in source.getmembers():
            data = source.extractfile(entry).read()
            if entry.name == EVENTS:
                data = data[:-2] + b"x\n"
            elif entry.name == MANIFEST:
                data = json.dumps(manifest, indent=2, sort_keys=True).encode()
            entry.size = len(data)
            import io
            out.addfile(entry, io.BytesIO(data))

    with pytest.raises(TransferError, match="different bytes"):
        restore_vault(tampered, tmp_path / "brought-back", PASSPHRASE)


def test_an_archive_naming_a_path_outside_a_vault_writes_nothing(tmp_path):
    """An archive is a file somebody handed you. A parent step is refused
    rather than normalised into something acceptable-looking."""
    hostile = tmp_path / "hostile.orionvault"
    manifest = {
        "format": "orionvault-v1",
        "members": [
            {"name": EVENTS, "length": 0, "digest": ""},
            {"name": HEAD, "length": 0, "digest": ""},
            {"name": RAW_HEADER, "length": 0, "digest": ""},
            {"name": "../escaped", "length": 0, "digest": ""},
        ],
    }
    with tarfile.open(hostile, "w:gz") as bundle:
        import io
        written = json.dumps(manifest).encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(written)
        bundle.addfile(info, io.BytesIO(written))

    with pytest.raises(TransferError, match="outside a vault's own two places"):
        restore_vault(hostile, tmp_path / "brought-back", PASSPHRASE)

    assert not (tmp_path / "escaped").exists()


def test_an_archive_in_a_format_this_build_does_not_restore_is_not_unpacked(tmp_path):
    strange = tmp_path / "strange.orionvault"
    with tarfile.open(strange, "w:gz") as bundle:
        import io
        written = json.dumps({"format": "orionvault-v99", "members": []}).encode()
        info = tarfile.TarInfo(MANIFEST)
        info.size = len(written)
        bundle.addfile(info, io.BytesIO(written))

    with pytest.raises(TransferError, match="this build restores"):
        read_manifest(strange)


def test_two_exports_of_an_unchanged_vault_are_the_same_manifest(tmp_path):
    """One archive can be compared against another without opening either."""
    vault = _vault(tmp_path)
    first = export_vault(vault.directory, tmp_path / "one.orionvault")
    second = export_vault(vault.directory, tmp_path / "two.orionvault")

    assert [member.as_dict() for member in first.members] == \
        [member.as_dict() for member in second.members]


def test_a_vault_that_has_taken_in_no_document_is_whole(tmp_path):
    empty = Vault.open(tmp_path / "empty", PASSPHRASE)
    empty.ledger.append(document_captured(
        "d" * 64, "nothing.pdf", 0, "statement", 0.0, "2026-08-01"))

    export_vault(empty.directory, tmp_path / "empty.orionvault")
    result = restore_vault(tmp_path / "empty.orionvault",
                           tmp_path / "brought-back", PASSPHRASE)

    assert result.blob_count == 0
    assert result.event_count == 1
