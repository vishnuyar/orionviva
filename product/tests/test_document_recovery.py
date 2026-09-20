"""Explicit recovery uses sealed originals and refuses uncertain financial writes."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from viva.desktop_bridge.document_actions import DocumentActions, READING_STEPS, document_recovery
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.jobs import JobRegistry, JobState
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.ingest import ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.ledger.events import Provenance, document_captured
from viva.vault import Vault

DATA = b"synthetic interrupted statement original"


def reader(data, doc_id):
    assert data == DATA
    facts = StatementFacts(doc_id, "checking_statement", 1.0, "Example checking",
        "USD", Decimal("100"), "2026-01-01", Decimal("90"), "2026-01-31",
        [TxnFact("2026-01-10", "Example purchase", Decimal("-10"))])
    return ReadResult("checking_statement", 1.0, facts)


def setup(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / "vault", "synthetic phrase")
    jobs = JobRegistry(state_file=vault.directory / ".jobs.json")
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: (reader, True))
    monkeypatch.setattr("viva.ingest.reader.live_reading_configured", lambda: True)
    return vault, jobs


def interrupted(vault, jobs, *, stage="reading", cancelled=False):
    job = jobs.open("viva.documents.upload", READING_STEPS)
    job.begin()
    job.bind_document(vault.raw.put(DATA))
    if stage == "settling":
        job.settling()
    if cancelled:
        jobs.cancel(job.job_id)
    else:
        job.fail("interrupted")
    return job.job_id


def recover(vault, jobs, job_id):
    return DocumentActions(vault, jobs).recover({"job_id": job_id, "confirm_reading": True})


def test_hard_exit_during_read_recovers_after_reopen_without_source_file(tmp_path, monkeypatch):
    source = tmp_path / "original.pdf"
    source.write_bytes(DATA)
    directory = tmp_path / "vault"
    code = '''
import os,sys
from viva.vault import Vault
from viva.desktop_bridge.document_actions import DocumentActions
from viva.desktop_bridge.jobs import JobRegistry
import viva.ingest.reader
vault=Vault.open(sys.argv[1], "synthetic phrase")
def crash(data,doc_id): os._exit(17)
viva.ingest.reader.build_reader=lambda:(crash,True)
DocumentActions(vault,JobRegistry(state_file=vault.directory/".jobs.json")).upload({"path":sys.argv[2]})
'''
    run = subprocess.run([sys.executable, "-c", code, str(directory), str(source)], timeout=30)
    assert run.returncode == 17
    source.unlink()
    vault, jobs = setup(tmp_path, monkeypatch)
    original = jobs.records()[0]
    assert original.state == JobState.FAILED and original.recovery_stage == "reading"
    provider = OpenedVaultSurfaceProvider(vault, jobs)
    assert provider.read_surface("jobs", {})["jobs"][0]["recovery"]["state"] == "available"
    result = recover(vault, jobs, original.job_id)
    assert result["kind"] == "completed" and result["state"]["terminal_state"] == "posted"
    count = len(list(vault.ledger.events()))
    assert recover(vault, jobs, original.job_id)["reason"] == "recovery_unavailable"
    assert len(list(vault.ledger.events())) == count
    assert not any(row.get("recovery") for row in provider.read_surface("jobs", {})["jobs"])


@pytest.mark.parametrize("stage", ["reading", "settling"])
def test_any_ledger_event_or_settling_receipt_refuses_without_reader(tmp_path, monkeypatch, stage):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs, stage=stage)
    doc_id = vault.raw.fingerprint(DATA)
    if stage == "reading":
        vault.ledger.append(document_captured(doc_id, "", len(DATA), "unknown", 0, "", Provenance(doc_id)))
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: pytest.fail("unsafe read"))
    count = len(list(vault.ledger.events()))
    assert recover(vault, jobs, job_id)["reason"] == "recovery_unavailable"
    assert len(list(vault.ledger.events())) == count


@pytest.mark.parametrize("after", [1, 2, 3, 4, 5])
def test_interruptions_during_post_are_never_replayed(tmp_path, monkeypatch, after):
    vault, jobs = setup(tmp_path, monkeypatch)
    source = tmp_path / "file.pdf"
    source.write_bytes(DATA)
    append = vault.ledger.append
    calls = 0
    def failing(event):
        nonlocal calls
        result = append(event)
        calls += 1
        if calls == after:
            raise SystemExit("simulated interruption")
        return result
    monkeypatch.setattr(vault.ledger, "append", failing)
    with pytest.raises(SystemExit):
        DocumentActions(vault, jobs).upload({"path": str(source)})
    original = jobs.records()[0]
    assert original.recovery_stage == "settling"
    monkeypatch.setattr(vault.ledger, "append", append)
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: pytest.fail("partial post reread"))
    count = len(list(vault.ledger.events()))
    assert recover(vault, jobs, original.job_id)["reason"] == "recovery_unavailable"
    assert len(list(vault.ledger.events())) == count


def test_cancel_request_survives_restart_and_cannot_recover(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs, cancelled=True)
    restarted = JobRegistry(state_file=vault.directory / ".jobs.json")
    assert restarted.record(job_id).state == JobState.CANCELLED
    assert recover(vault, restarted, job_id)["reason"] == "recovery_unavailable"


@pytest.mark.parametrize("damage", ["missing", "corrupt", "path"])
def test_missing_corrupt_or_invalid_address_never_reads(tmp_path, monkeypatch, damage):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs)
    doc_id = vault.raw.fingerprint(DATA)
    if damage == "missing":
        vault.raw._blob_path(doc_id).unlink()
    elif damage == "corrupt":
        vault.raw._blob_path(doc_id).write_text("bad ciphertext")
    else:
        jobs._move(job_id, "progress", document_id="../../outside")
        monkeypatch.setattr(vault.raw, "has", lambda _: pytest.fail("unvalidated path"))
        monkeypatch.setattr(vault.raw, "get", lambda _: pytest.fail("unvalidated path"))
    assert recover(vault, jobs, job_id)["kind"] == "refused"
    assert not list(vault.ledger.events())


def test_consent_and_configured_reader_are_required(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs)
    for payload in [{"job_id": job_id}, {"job_id": job_id, "confirm_reading": False}]:
        with pytest.raises(BridgeRequestError):
            DocumentActions(vault, jobs).recover(payload)
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: (reader, False))
    assert recover(vault, jobs, job_id)["reason"] == "reader_not_configured"
    assert not list(vault.ledger.events())


def test_jobs_remain_readable_without_sql_or_projection(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    interrupted(vault, jobs)
    monkeypatch.setattr(vault.ledger, "projection", lambda: pytest.fail("jobs replayed ledger"))
    monkeypatch.setattr(vault.ledger, "events", lambda: pytest.fail("jobs decrypted events"))
    vault.read_store_lifecycle = "degraded"
    assert OpenedVaultSurfaceProvider(vault, jobs).read_surface("jobs", {})["jobs"][0]["recovery"]["state"] == "available"


def test_two_recovery_calls_serialize_and_spend_once(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs)
    entered = threading.Event()
    release = threading.Event()
    calls = []
    def waiting(data, doc_id):
        calls.append(doc_id)
        entered.set()
        assert release.wait(10)
        return reader(data, doc_id)
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: (waiting, True))
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(recover, vault, jobs, job_id)
        assert entered.wait(10)
        second = pool.submit(recover, vault, jobs, job_id)
        release.set()
        assert first.result(timeout=15)["kind"] == "completed"
        assert second.result(timeout=15)["kind"] in {"completed", "refused"}
    assert len(calls) == 1
    assert len(vault.ledger.projection().posted_doc_ids()) == 1


def test_normal_ingest_and_recovery_share_document_exclusion(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs)
    entered = threading.Event()
    release = threading.Event()
    def waiting(data, doc_id):
        entered.set()
        assert release.wait(10)
        return reader(data, doc_id)
    monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: (lambda *_: pytest.fail("duplicate model read"), True))
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(capture_and_ingest, vault.raw, vault.ledger, DATA, waiting)
        assert entered.wait(10)
        second = pool.submit(recover, vault, jobs, job_id)
        release.set()
        assert first.result(timeout=15).action == "posted"
        assert second.result(timeout=15)["kind"] in {"completed", "refused"}
    assert len(vault.ledger.projection().posted_doc_ids()) == 1


def test_document_lock_excludes_another_process_through_posting(tmp_path, monkeypatch):
    vault, jobs = setup(tmp_path, monkeypatch)
    job_id = interrupted(vault, jobs)
    entered, release = tmp_path / "entered", tmp_path / "release"
    code = '''
import sys,time
from pathlib import Path
from decimal import Decimal
from viva.vault import Vault
from viva.ingest import capture_and_ingest, ReadResult, StatementFacts, TxnFact
vault=Vault.open(sys.argv[1],"synthetic phrase")
def reader(data,doc_id):
 Path(sys.argv[2]).touch()
 limit=time.monotonic()+15
 while not Path(sys.argv[3]).exists():
  if time.monotonic()>limit: raise RuntimeError("test timed out")
  time.sleep(.01)
 return ReadResult("checking_statement",1.0,StatementFacts(doc_id,"checking_statement",1.0,"Example checking","USD",Decimal("100"),"2026-01-01",Decimal("90"),"2026-01-31",[TxnFact("2026-01-10","Example purchase",Decimal("-10"))]))
capture_and_ingest(vault.raw,vault.ledger,b"synthetic interrupted statement original",reader)
'''
    child = subprocess.Popen([sys.executable, "-c", code, str(vault.directory), str(entered), str(release)])
    try:
        import time
        deadline = time.monotonic() + 10
        while not entered.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        assert entered.exists()
        monkeypatch.setattr("viva.ingest.reader.build_reader", lambda: (lambda *_: pytest.fail("concurrent model read"), True))
        with ThreadPoolExecutor(1) as pool:
            retry = pool.submit(recover, vault, jobs, job_id)
            release.touch()
            assert child.wait(timeout=20) == 0
            assert retry.result(timeout=20)["kind"] in {"completed", "refused"}
        assert len(vault.ledger.projection().posted_doc_ids()) == 1
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()


def test_failed_raw_publication_never_leaves_a_partial_blob(tmp_path, monkeypatch):
    vault, _ = setup(tmp_path, monkeypatch)
    def failed_replace(source, target):
        assert source.is_file()
        raise OSError("simulated durable rename failure")
    monkeypatch.setattr("viva.ingest.raw_store.replace_commit_head", failed_replace)
    with pytest.raises(OSError):
        vault.raw.put(DATA)
    assert not vault.raw.has(vault.raw.fingerprint(DATA))
    assert not list(vault.raw.dir.glob(".capture-*"))
