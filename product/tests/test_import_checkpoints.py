"""Crash-boundary document continuation uses synthetic readers and no network."""
import json
from pathlib import Path

import pytest

from viva.desktop_bridge.bulk_documents import BulkDocuments
from viva.desktop_bridge.import_checkpoints import ImportCheckpoints
from viva.desktop_bridge.jobs import JobRegistry
from viva.ingest.pipeline import _begin_bulk_read
from viva.vault import Vault
from test_bulk_upload import setup_bulk


def before_settlement(sample, monkeypatch):
    from viva import engine
    original = engine.upload
    def stopped(*args, **kwargs):
        raise RuntimeError('synthetic process interruption before settlement')
    monkeypatch.setattr(engine, 'upload', stopped)
    first = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    monkeypatch.setattr(engine, 'upload', original)
    assert first['rows'][0]['reason'] == 'outcome_unknown'
    return first['rows'][0]['document_id']


def test_completed_read_resumes_after_reopen_without_provider_or_extraction(setup_bulk, monkeypatch):
    sample = setup_bulk
    document = before_settlement(sample, monkeypatch)
    calls = len(sample.adapters)
    directory = sample.vault.directory
    sample.vault.close()
    reopened = Vault.open(directory, 'synthetic-only')
    try:
        assert ImportCheckpoints(reopened).read(document)['state'] == 'settling'
        def forbidden(*args, **kwargs):
            raise AssertionError('completed extraction was requested again')
        monkeypatch.setattr('viva.ingest.reader.adapter_for', forbidden)
        result = BulkDocuments(reopened, JobRegistry()).run({'paths': sample.paths[:1]})
        assert result['rows'][0]['action'] == 'posted'
        assert len(sample.adapters) == calls
        assert ImportCheckpoints(reopened).read(document)['state'] == 'settled'
        before = len(tuple(reopened.ledger.events()))
        duplicate = BulkDocuments(reopened, JobRegistry()).run({'paths': sample.paths[:1]})
        assert duplicate['rows'][0]['action'] == 'duplicate'
        assert len(tuple(reopened.ledger.events())) == before
    finally:
        reopened.close()


def test_unknown_external_request_never_retries_automatically(setup_bulk):
    sample = setup_bulk
    data = Path(sample.paths[0]).read_bytes()
    owner = _begin_bulk_read(sample.vault.raw, sample.vault.ledger, data, 'private-name.pdf', '')
    try:
        ImportCheckpoints(sample.vault).begin(owner)
    finally:
        owner.close()
    result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert result['rows'][0]['reason'] == 'outcome_unknown'
    assert not sample.adapters
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_contract_change_and_tampered_checkpoint_fail_closed(setup_bulk, monkeypatch):
    sample = setup_bulk
    document = before_settlement(sample, monkeypatch)
    checkpoint = ImportCheckpoints(sample.vault)
    encoded = checkpoint._path(document).read_bytes()
    assert b'document-0.pdf' not in encoded and b'account_ref' not in encoded
    assert b'opening_amount' not in encoded
    with monkeypatch.context() as scoped:
        scoped.setattr('viva.desktop_bridge.import_checkpoints.extraction_contract', lambda: 'changed')
        result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
        assert result['rows'][0]['reason'] == 'outcome_unknown'
    envelope = json.loads(encoded)
    envelope['ct'] = ('A' if envelope['ct'][0] != 'A' else 'B') + envelope['ct'][1:]
    checkpoint._path(document).write_text(json.dumps(envelope))
    result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert result['rows'][0]['reason'] == 'outcome_unknown'
    assert len(sample.adapters) == 1


def test_altered_canonical_read_population_blocks_resume_without_new_charge(setup_bulk, monkeypatch):
    sample = setup_bulk
    document = before_settlement(sample, monkeypatch)
    from viva.ledger.events import Event
    record = next(e for e in sample.vault.ledger.events() if e.event_type == 'ReadRecorded')
    copied = record.to_dict(); copied['event_id'] = 'another-synthetic-receipt'
    sample.vault.ledger.append(Event.from_dict(copied))
    result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert result['rows'][0]['reason'] == 'outcome_unknown'
    assert len(sample.adapters) == 1
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_checkpoint_storage_refuses_symlink_directory(setup_bulk, tmp_path):
    sample = setup_bulk
    outside = tmp_path / 'other'; outside.mkdir()
    (sample.vault.directory / 'import-work').symlink_to(outside, target_is_directory=True)
    owner = _begin_bulk_read(sample.vault.raw, sample.vault.ledger, b'SYNTHETIC-new', 'secret.pdf', '')
    try:
        with pytest.raises(ValueError, match='storage unavailable'):
            ImportCheckpoints(sample.vault).begin(owner)
    finally:
        owner.close()
    assert not list(outside.iterdir())


def test_mid_settlement_exception_leaves_no_partial_financial_effects_and_resumes_free(setup_bulk, monkeypatch):
    from viva.ingest import pipeline
    sample = setup_bulk
    original = pipeline.post_statement
    def interrupted(staged, facts):
        result = original(staged, facts)
        assert staged.projection().is_resolved(facts.doc_id)
        raise RuntimeError('synthetic crash after staged financial effects')
    monkeypatch.setattr(pipeline, 'post_statement', interrupted)
    first = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    document = first['rows'][0]['document_id']
    assert first['rows'][0]['reason'] == 'outcome_unknown'
    assert not sample.vault.ledger.projection().posted_doc_ids()
    assert not any(event.event_type == 'TransactionRecorded' for event in sample.vault.ledger.events())
    assert ImportCheckpoints(sample.vault).read(document)['state'] == 'settling'
    monkeypatch.setattr(pipeline, 'post_statement', original)
    second = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert second['rows'][0]['action'] == 'posted'
    assert len(sample.adapters) == 1


def test_crash_after_canonical_settlement_never_repeats_money_or_reading(setup_bulk, monkeypatch):
    sample = setup_bulk
    original = ImportCheckpoints.mark
    def interrupted(self, document, state, outcome=None):
        if state == 'settled':
            raise RuntimeError('synthetic crash before final operational receipt')
        return original(self, document, state, outcome)
    monkeypatch.setattr(ImportCheckpoints, 'mark', interrupted)
    first = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert first['rows'][0]['reason'] == 'outcome_unknown'
    assert sample.vault.ledger.projection().posted_doc_ids()
    before = tuple(event.to_dict() for event in sample.vault.ledger.events())
    monkeypatch.setattr(ImportCheckpoints, 'mark', original)
    second = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert second['rows'][0]['action'] == 'duplicate'
    assert tuple(event.to_dict() for event in sample.vault.ledger.events()) == before
    assert len(sample.adapters) == 1


def test_acknowledged_extraction_survives_death_before_completed_snapshot(setup_bulk, monkeypatch):
    from vivacore.models.base import PageImage
    sample = setup_bulk
    from test_retained_bulk_reading import actual_http
    calls = actual_http(monkeypatch)
    original = ImportCheckpoints.complete
    def interrupted(*args, **kwargs):
        raise RuntimeError('synthetic death after phase ack before completion envelope')
    monkeypatch.setattr(ImportCheckpoints, 'complete', interrupted)
    first = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    document = first['rows'][0]['document_id']
    assert first['rows'][0]['reason'] == 'outcome_unknown'
    assert ImportCheckpoints(sample.vault).read(document)['state'] == 'reading'
    receipts = [event for event in sample.vault.ledger.events() if event.event_type == 'ReadRecorded']
    assert receipts[-1].body['phase'] == 'extract' and receipts[-1].body['parse_ok']
    monkeypatch.setattr(ImportCheckpoints, 'complete', original)
    errors = []
    resume = ImportCheckpoints.resume
    def diagnosed(self, owner, body):
        try:return resume(self, owner, body)
        except Exception as exc:
            errors.append(repr(exc));raise
    monkeypatch.setattr(ImportCheckpoints, 'resume', diagnosed)
    monkeypatch.setattr('viva.ingest.reader._render_and_read_text', lambda data: ((PageImage(1, b'png', 'synthetic'),), 'synthetic'))
    second = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths[:1]})
    assert second['rows'][0]['action'] == 'posted', (second, errors)
    assert len(calls) == 2
