"""Capture from the desktop: a path in, a document sealed, and nothing read.

Every frame here is one a shell would send. What the file contains is never the
subject — the same bytes stand in for every document, because nothing on this
path looks at them to decide what to do.

Three properties this file exists to hold, each of which would otherwise rest
on someone remembering. Nothing leaves the machine, proved with the socket
layer removed rather than asserted. Nothing reads, proved on a machine whose
environment names a reader, because a fence that only holds where the
environment is empty is not a fence. And the request has one field, which is
what stops a caller asserting an identity for work it did not do.

Every name and value here is invented.
"""

from __future__ import annotations

import json
import socket

import pytest

from viva.desktop_bridge import dispatch_frame, handlers_for_opened_vault
from viva.ingest import RawStore
from viva.ingest.reader import MAX_BYTES
from viva.ledger import EventStore, Ledger
from viva.persona import moment
from viva.vault import Vault

UPLOAD = "viva.documents.upload"
DOCUMENT = b"a document this build has no way of reading"


def _vault(tmp_path) -> Vault:
    return Vault(ledger=Ledger(EventStore.open(tmp_path / "events.jsonl", "pw")),
                 raw=RawStore.open(tmp_path / "raw", "pw"),
                 directory=tmp_path)


class _Sidecar:
    """The frames a desktop would send, over one opened vault's allowlist."""

    def __init__(self, vault: Vault) -> None:
        self._handlers = handlers_for_opened_vault(vault).handlers

    def _answer(self, operation: str, payload: dict) -> dict:
        frame = json.dumps({"protocol": "2.0", "request_id": "capture-1",
                            "operation": operation, "payload": payload})
        return json.loads(dispatch_frame(frame, self._handlers))

    def send(self, operation: str, payload: dict) -> dict:
        response = self._answer(operation, payload)
        assert response["ok"] is True, response
        return response["result"]

    def rejected(self, operation: str, payload: dict) -> dict:
        response = self._answer(operation, payload)
        assert response["ok"] is False, response
        return response


def _file(tmp_path, name: str = "statement.pdf", body: bytes = DOCUMENT):
    path = tmp_path / name
    path.write_bytes(body)
    return path


def _opened(_self):
    raise AssertionError("the file was opened despite being refused unopened")


def _already_settled(vault: Vault) -> None:
    """Put the document into the vault the way the terminal would, with a read
    behind it that landed, so a later copy of it has something to be a copy
    of."""
    from decimal import Decimal

    from viva.ingest import ReadResult, StatementFacts, TxnFact, capture_and_ingest

    facts = StatementFacts(
        doc_id="", doc_type="checking_statement", doc_type_confidence=0.98,
        account_ref="Everyday Account", currency="USD",
        opening_amount=Decimal("2000.00"), opening_date="2026-03-01",
        closing_amount=Decimal("1880.00"), closing_date="2026-03-31",
        transactions=[TxnFact("2026-03-05", "SAMPLE BAKERY", Decimal("-120.00"))],
        account_number="000000001122", institution="Sample Mutual")

    def read(_data, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, 0.98, facts)

    capture_and_ingest(vault.raw, vault.ledger, DOCUMENT, read,
                       filename="statement.pdf", captured_at="2026-05-01")


@pytest.fixture
def unplugged(monkeypatch):
    """A machine with no way of reaching anything.

    Both doors are removed, so a path that opened a connection meets a machine
    with no network rather than a test that never had one. The attempt is
    recorded and read after the test rather than raised inside it: ingest
    catches whatever a reader throws and parks the document, which would turn a
    connection into a quieter failure somewhere downstream instead of the one
    sentence that says what happened."""
    reached = []

    def refuse(*args, **_kwargs):
        reached.append(args)
        raise OSError("there is no network on this machine")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    assert not reached, "this path opened a connection"


def test_a_captured_document_is_sealed_and_the_reply_says_reading_waits(
        tmp_path, unplugged):
    """The whole of what this operation does, end to end and offline."""
    vault = _vault(tmp_path)
    path = _file(tmp_path)

    result = _Sidecar(vault).send(UPLOAD, {"path": str(path)})

    assert result["kind"] == "completed"
    assert result["message"] == moment("documents_saved_no_reader")
    assert result["reason"] is None
    assert vault.raw.doc_ids() == [RawStore.fingerprint(DOCUMENT)]
    assert vault.raw.get(RawStore.fingerprint(DOCUMENT)) == DOCUMENT


def test_the_reply_carries_the_identity_the_sidecar_minted(tmp_path, unplugged):
    """A capture answers with the identity of the job that did it, because a
    second frame — the cancel — has to be able to name this job and no other.
    The identity is beside the sentence rather than inside it: a sentence a
    caller has to parse to find one is a contract nobody wrote down."""
    vault = _vault(tmp_path)

    result = _Sidecar(vault).send(UPLOAD, {"path": str(_file(tmp_path))})

    assert result["state"]["job_id"].startswith("viva.documents.upload-")
    assert result["state"]["job_id"] not in result["message"]


def test_a_caller_cannot_assert_a_job_id_because_the_request_has_no_room_for_one(
        tmp_path):
    """Identity is minted by whoever knows what a unit of work is, and this
    request gives a caller nowhere to put one."""
    sidecar = _Sidecar(_vault(tmp_path))
    path = str(_file(tmp_path))

    refusal = sidecar.rejected(UPLOAD, {"path": path, "job_id": "desktop-1"})

    assert refusal["error"]["code"] == "invalid_request"
    assert "job_id" in refusal["error"]["message"]


def test_a_configured_environment_still_captures_and_still_reads_nothing(
        tmp_path, unplugged, monkeypatch):
    """The money fence is structural. A machine that names a reader gets the
    same capture as one that does not, because this path asks for the reader
    that cannot read rather than building one and declining to use it."""
    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "some-adapter")
    monkeypatch.setenv("VIVA_MODEL", "some-pinned-model")
    vault = _vault(tmp_path)

    result = _Sidecar(vault).send(UPLOAD, {"path": str(_file(tmp_path))})

    assert result["kind"] == "completed"
    # A different true sentence, and the same absence of a reading behind it.
    assert result["message"] == moment("documents_saved_unread")
    documents = vault.ledger.projection()
    assert documents.read_attempted_docs() == set()
    assert documents.captured_docs() == {RawStore.fingerprint(DOCUMENT): "unknown"}


def test_a_document_the_vault_has_already_settled_is_not_taken_twice(
        tmp_path, unplugged):
    """A second copy of a document the vault has already made something of is
    an outcome and not a refusal: the document is in the vault, and saying no
    would be a lie about where things stand."""
    vault = _vault(tmp_path)
    _already_settled(vault)

    result = _Sidecar(vault).send(UPLOAD, {"path": str(_file(tmp_path))})

    assert result["kind"] == "completed"
    assert result["message"] == moment("documents_already_held")
    assert vault.raw.doc_ids() == [RawStore.fingerprint(DOCUMENT)]


def test_a_file_over_the_ceiling_is_refused_before_it_is_opened(
        tmp_path, unplugged, monkeypatch):
    """The ceiling refuses rather than freezes, and it refuses on what the
    filesystem says the file weighs rather than on what reading it would show.

    It is the reader's own ceiling, so one number bounds what this product will
    take in however a document arrives. The file is never opened, which is the
    point: a ceiling enforced after the read has already paid for the thing it
    was meant to prevent."""
    vault = _vault(tmp_path)
    path = tmp_path / "beyond-the-ceiling.pdf"
    path.write_bytes(b"")
    # Written sparsely: the file weighs more than the ceiling and costs no disk.
    with path.open("r+b") as handle:
        handle.truncate(MAX_BYTES + 1)
    monkeypatch.setattr("pathlib.Path.read_bytes", _opened)

    refusal = _Sidecar(vault).send(UPLOAD, {"path": str(path)})

    assert refusal["kind"] == "refused"
    assert refusal["reason"] == "file_over_size_limit"
    assert refusal["message"] == moment(
        "documents_too_large", limit=f"{MAX_BYTES // (1024 * 1024)} MB")
    assert vault.raw.doc_ids() == []


@pytest.mark.parametrize("what, why", [
    ("missing", "file_unavailable"),
    ("directory", "not_a_regular_file"),
])
def test_a_path_that_is_not_a_file_is_refused_with_a_machine_reason(
        tmp_path, unplugged, what, why):
    """A refusal names a reason a machine can read, and says in words that
    nothing changed."""
    vault = _vault(tmp_path)
    target = tmp_path / what
    if what == "directory":
        target.mkdir()

    refusal = _Sidecar(vault).send(UPLOAD, {"path": str(target)})

    assert refusal["kind"] == "refused"
    assert refusal["reason"] == why
    assert refusal["message"] == moment("documents_cannot_open")
    assert vault.raw.doc_ids() == []


@pytest.mark.parametrize("payload", [{}, {"path": ""}, {"path": 7}])
def test_a_request_without_a_usable_path_is_refused_by_the_request(
        tmp_path, payload):
    refusal = _Sidecar(_vault(tmp_path)).rejected(UPLOAD, payload)

    assert refusal["error"]["code"] == "invalid_request"


def test_the_document_is_in_the_read_the_panel_makes_before_anything_reads_it(
        tmp_path, unplugged):
    """The other half of the cycle: what was captured shows up in the read the
    Documents panel is composed from, under the name it arrived with, saying
    once that nothing has read it."""
    vault = _vault(tmp_path)
    sidecar = _Sidecar(vault)
    sidecar.send(UPLOAD, {"path": str(_file(tmp_path, "quarterly-summary.pdf"))})

    read = sidecar.send("viva.surface.read",
                        {"surface": "documents", "parameters": {}})["data"]

    assert read["state"] == "ready"
    assert read["reading_sentence"] == moment("documents_saved_no_reader")
    assert len(read["documents"]) == 1
    row = read["documents"][0]
    assert row["filename"] == "quarterly-summary.pdf"
    assert row["reading"] == "never_read"
    assert row["raw_available"] is True
    assert row["resolved"] is False


def test_the_blob_is_already_sealed_when_the_read_begins_on_this_path(
        tmp_path, unplugged, monkeypatch):
    """Capture-first, held on the path a desktop actually drives.

    The reader this path asks for is replaced by one that looks in the raw
    store at the moment it is called; everything else is the real frame, the
    real allowlist and the real engine."""
    vault = _vault(tmp_path)
    seen: dict[str, object] = {}

    def probe(data, doc_id):
        from viva.ingest import ReadResult

        seen["stored"] = vault.raw.has(doc_id)
        seen["bytes"] = vault.raw.get(doc_id) if vault.raw.has(doc_id) else None
        return ReadResult("unknown", 0.0, None, "nothing read this document")

    monkeypatch.setattr("viva.ingest.reader._parking_reader", probe)

    _Sidecar(vault).send(UPLOAD, {"path": str(_file(tmp_path))})

    assert seen["stored"] is True
    assert seen["bytes"] == DOCUMENT


@pytest.mark.parametrize("action", ["posted", "awaiting", "conflict", "gap",
                                   "identity", "something-else", None])
def test_an_outcome_this_route_has_no_word_for_raises_rather_than_guessing(action):
    """A route that reads nothing produces two actions and no others. Handing
    one of the rest the nearest available sentence would put words about a
    different event in front of a person, so the mapping refuses to answer at
    all."""
    from viva.desktop_bridge.document_actions import _outcome
    from viva.desktop_bridge.review_actions import UnreadableOutcome

    with pytest.raises(UnreadableOutcome):
        _outcome({"action": action}, False)


def test_the_sentence_a_refusal_to_answer_carries_sends_nobody_anywhere():
    """A person who has just added a file is not standing at a queue, so the
    words said when the vault answers unreadably do not send them to one."""
    from viva.desktop_bridge.document_actions import _outcome
    from viva.desktop_bridge.review_actions import UnreadableOutcome

    with pytest.raises(UnreadableOutcome) as raised:
        _outcome({"action": "something-else"}, False)

    assert str(raised.value) == moment("documents_outcome_unstated")
    assert "queue" not in str(raised.value)


def test_the_two_reachable_actions_each_have_their_own_sentence():
    from viva.desktop_bridge.document_actions import _outcome

    parked = _outcome({"action": "parked"}, False)
    duplicate = _outcome({"action": "duplicate"}, False)

    assert parked.kind == duplicate.kind == "completed"
    assert parked.message != duplicate.message


def test_stopping_a_job_nothing_minted_is_refused_rather_than_answered(tmp_path):
    """A cancel that quietly succeeds against an identity nothing minted tells
    a person their work stopped when nothing was ever asked. It is a refusal
    with a reason, which is an ordinary reply and not an error frame."""
    result = _Sidecar(_vault(tmp_path)).send(
        "viva.documents.cancel", {"job_id": "viva.documents.upload-404"})

    assert result["kind"] == "refused"
    assert result["reason"] == "job_unknown"


def test_stopping_a_capture_that_already_finished_says_so(tmp_path, unplugged):
    """A job that finished a moment before the ask is not moved, and the reply
    says which of the two unhappy things happened rather than reporting a
    cancel that reached nothing as one that worked."""
    sidecar = _Sidecar(_vault(tmp_path))
    captured = sidecar.send(UPLOAD, {"path": str(_file(tmp_path))})

    result = sidecar.send("viva.documents.cancel",
                          {"job_id": captured["state"]["job_id"]})

    assert result["kind"] == "refused"
    assert result["reason"] == "job_already_settled"
    assert result["state"]["job"]["state"] == "completed"


def test_a_cancel_request_takes_a_job_and_nothing_else(tmp_path):
    """The field set is the fence. A cancel naming a path would be a caller
    asserting which work its identity stands for."""
    refusal = _Sidecar(_vault(tmp_path)).rejected(
        "viva.documents.cancel", {"job_id": "j", "path": "/tmp/x"})

    assert refusal["error"]["code"] == "invalid_request"
