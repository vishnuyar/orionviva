"""A whole vault leaves and comes back, over the bridge.

The engine half is tested where it lives. What is tested here is the half a
person meets: which frame reaches which reply, that each way it can go wrong
gets its own reason and its own reviewed sentence, and that neither action ever
touches the vault the sidecar has open.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from viva.desktop_bridge.handlers import handlers_for_opened_vault
from viva.desktop_bridge.rpc import dispatch_frame
from viva.ingest.raw_store import RawStore
from viva.ledger.events import document_captured
from viva.persona import moment
from viva.surface import CURRENT_PROTOCOL
from viva.vault import Vault

PASSPHRASE = "a-real-passphrase"
DOCUMENT = b"%PDF-1.4 a statement"
EXPORT = "viva.vault.export"
RESTORE = "viva.vault.restore"


class _Sidecar:
    """One opened vault behind the real allowlist, spoken to in real frames."""

    def __init__(self, vault: Vault) -> None:
        self._handlers = handlers_for_opened_vault(vault).handlers

    def _answer(self, operation: str, payload: dict) -> dict:
        return json.loads(dispatch_frame(json.dumps({
            "protocol": CURRENT_PROTOCOL.wire(), "request_id": "r1",
            "operation": operation, "payload": payload}), self._handlers))

    def send(self, operation: str, payload: dict) -> dict:
        answered = self._answer(operation, payload)
        assert answered["ok"] is True, answered
        return answered["result"]

    def rejected(self, operation: str, payload: dict) -> dict:
        answered = self._answer(operation, payload)
        assert answered["ok"] is False, answered
        return answered


def _vault(tmp_path: Path, name: str = "vault") -> Vault:
    vault = Vault.open(tmp_path / name, PASSPHRASE)
    doc_id = vault.raw.put(DOCUMENT)
    vault.ledger.append(document_captured(
        doc_id, "statement.pdf", len(DOCUMENT), "statement", 0.9, "2026-08-01"))
    return vault


def test_a_copy_is_written_and_says_what_it_wrote_about(tmp_path):
    """What was written about, never what any of it holds: a count of
    documents is already on the documents screen; a name from inside one is
    not."""
    vault = _vault(tmp_path)

    result = _Sidecar(vault).send(EXPORT, {"archive": str(tmp_path / "copy.orionvault")})

    assert result["kind"] == "completed"
    assert result["message"] == moment("vault_exported")
    assert result["state"]["blob_count"] == 1
    assert "statement.pdf" not in json.dumps(result)
    assert (tmp_path / "copy.orionvault").is_file()


def test_the_open_vault_is_not_touched_by_a_copy(tmp_path):
    vault = _vault(tmp_path)
    before = (vault.directory / "events.jsonl").read_bytes()

    _Sidecar(vault).send(EXPORT, {"archive": str(tmp_path / "copy.orionvault")})

    assert (vault.directory / "events.jsonl").read_bytes() == before


def test_each_way_a_copy_can_be_refused_carries_its_own_reason_and_sentence(tmp_path):
    """A name already taken and a vault missing a part ask a person to do two
    completely different things next, so they are never one refusal."""
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    archive = str(tmp_path / "copy.orionvault")
    sidecar.send(EXPORT, {"archive": archive})

    taken = sidecar.send(EXPORT, {"archive": archive})
    assert taken["kind"] == "refused"
    assert taken["reason"] == "archive_exists"
    assert taken["message"] == moment("vault_export_exists")

    (vault.directory / "raw" / "raw-header.json").unlink()
    incomplete = sidecar.send(EXPORT, {"archive": str(tmp_path / "second.orionvault")})
    assert incomplete["reason"] == "vault_incomplete"
    assert incomplete["message"] == moment("vault_export_incomplete")


def test_a_vault_comes_back_and_the_reply_reports_what_reading_it_established(tmp_path):
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    archive = str(tmp_path / "copy.orionvault")
    sidecar.send(EXPORT, {"archive": archive})

    result = sidecar.send(RESTORE, {
        "archive": archive, "directory": str(tmp_path / "brought-back"),
        "passphrase": PASSPHRASE})

    assert result["kind"] == "completed"
    assert result["message"] == moment("vault_restored")
    assert result["state"]["event_count"] == 1
    assert result["state"]["blob_count"] == 1
    assert result["state"]["chain_intact"] is True
    brought = Vault.open(tmp_path / "brought-back", PASSPHRASE)
    assert brought.raw.get(RawStore.fingerprint(DOCUMENT)) == DOCUMENT


def test_a_restore_onto_a_folder_in_use_is_refused_and_unpacks_nothing(tmp_path):
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    archive = str(tmp_path / "copy.orionvault")
    sidecar.send(EXPORT, {"archive": archive})

    result = sidecar.send(RESTORE, {
        "archive": archive, "directory": str(vault.directory),
        "passphrase": PASSPHRASE})

    assert result["reason"] == "directory_occupied"
    assert result["message"] == moment("vault_restore_occupied")
    assert Vault.open(vault.directory, PASSPHRASE).raw.doc_ids() == [
        RawStore.fingerprint(DOCUMENT)]


def test_a_restore_that_would_not_read_back_is_refused_rather_than_reported(tmp_path):
    """Unpacking proves the bytes arrived. Only opening proves the passphrase
    reaches both keystreams, so nothing here reports a restore nobody read."""
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    archive = str(tmp_path / "copy.orionvault")
    sidecar.send(EXPORT, {"archive": archive})

    result = sidecar.send(RESTORE, {
        "archive": archive, "directory": str(tmp_path / "brought-back"),
        "passphrase": "the-wrong-one"})

    assert result["reason"] == "archive_unreadable"
    assert result["message"] == moment("vault_restore_unreadable")


def test_no_engine_sentence_travels_to_a_screen(tmp_path):
    """An engine's own exception text can carry a path, and worse, a message
    shaped like an answer. Every branch here is matched to a reason and the
    sentence is the pack's."""
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    archive = str(tmp_path / "copy.orionvault")
    sidecar.send(EXPORT, {"archive": archive})

    refused = sidecar.send(EXPORT, {"archive": archive})

    assert refused["message"] in {moment(key) for key in (
        "vault_export_exists", "vault_export_incomplete",
        "vault_export_unwritable")}
    assert archive not in refused["message"]


def test_each_request_takes_the_fields_it_needs_and_no_others(tmp_path):
    sidecar = _Sidecar(_vault(tmp_path))

    assert sidecar.rejected(EXPORT, {"archive": "a", "directory": "b"})["error"]["code"] == "invalid_request"
    assert sidecar.rejected(RESTORE, {"archive": "a"})["error"]["code"] == "invalid_request"
    assert sidecar.rejected(RESTORE, {"archive": "a", "directory": "b", "passphrase": ""})["error"]["code"] == "invalid_request"


def test_both_transfer_actions_are_served_by_an_opened_vault(tmp_path):
    handlers = handlers_for_opened_vault(object()).handlers

    assert EXPORT in handlers
    assert RESTORE in handlers
