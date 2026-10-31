"""Folder queues retain encrypted sources and bounded, durable row outcomes."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.import_sessions import ImportSessions
from viva.desktop_bridge.jobs import JobRegistry
from viva.vault import Vault


def _files(tmp_path, count=5):
    paths = []
    for number in range(count):
        path = tmp_path / f'private-statement-{number}.pdf'
        path.write_bytes(f'synthetic original {number}'.encode())
        paths.append(str(path))
    return paths


def _operation(vault, calls):
    def run_queued(entries):
        assert 1 <= len(entries) <= 3
        calls.append(entries)
        for entry in entries:
            assert vault.raw.get(entry['doc_id']).startswith(b'synthetic original')
        return {'job_id': 'synthetic-job', 'rows': [
            dict(ordinal=index, document_id=entry['doc_id'], action='posted', disposition='read', reason=None)
            for index, entry in enumerate(entries)]}
    return SimpleNamespace(run_queued=run_queued, jobs=JobRegistry(), job_id=None)


def test_folder_queue_is_encrypted_and_retains_originals_before_sources_disappear(tmp_path):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-folder-key')
    paths = _files(tmp_path)
    queue = ImportSessions(vault)
    receipt = queue.enqueue(paths, JobRegistry())
    assert receipt['remaining'] == 5
    on_disk = queue._path(receipt['session_id']).read_bytes()
    assert b'private-statement' not in on_disk
    assert str(tmp_path).encode() not in on_disk
    for path in paths:
        Path(path).unlink()
    calls = []
    first = queue.resume(receipt['session_id'], _operation(vault, calls))
    assert first['session']['completed'] == 3
    assert first['session']['remaining'] == 2
    vault.close()
    reopened = Vault.open(tmp_path / 'vault', 'synthetic-folder-key', create=False)
    restored = ImportSessions(reopened)
    assert restored.listing()['sessions'][0]['remaining'] == 2
    final = restored.resume(receipt['session_id'], _operation(reopened, calls))
    assert final['session']['completed'] == 5
    assert restored.listing() == {'sessions': []}
    assert [len(call) for call in calls] == [3, 2]
    assert restored.resume(receipt['session_id'], _operation(reopened, calls))['rows'] == []
    assert len(calls) == 2
    reopened.close()


def test_uncertain_chunk_retains_pending_work_and_interrupt_state(tmp_path):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-folder-key')
    queue = ImportSessions(vault)
    receipt = queue.enqueue(_files(tmp_path), JobRegistry())

    def interrupted(_entries):
        raise OSError('synthetic process interruption')

    with pytest.raises(OSError, match='synthetic process interruption'):
        queue.resume(receipt['session_id'], SimpleNamespace(run_queued=interrupted))
    summary = ImportSessions(vault).listing()['sessions'][0]
    assert summary['state'] == 'interrupted'
    assert summary['remaining'] == 5
    assert 'rows' not in summary
    vault.close()


def test_queue_ciphertext_cannot_move_between_vaults_or_sessions(tmp_path):
    first = Vault.open(tmp_path / 'one', 'synthetic-folder-key')
    queue = ImportSessions(first)
    receipt = queue.enqueue(_files(tmp_path, 1), JobRegistry())
    data = queue._path(receipt['session_id']).read_bytes()
    second = Vault.open(tmp_path / 'two', 'different-synthetic-key')
    foreign = ImportSessions(second)
    foreign._directory()
    target = foreign._path(receipt['session_id'])
    target.write_bytes(data)
    target.chmod(0o600)
    with pytest.raises(BridgeRequestError, match='unavailable'):
        foreign.listing()
    alternate = queue._path('a' * 32)
    alternate.write_bytes(data)
    alternate.chmod(0o600)
    with pytest.raises(BridgeRequestError, match='unavailable'):
        queue._load('a' * 32)
    first.close()
    second.close()


def test_queue_rejects_symlinks_and_unbounded_selection(tmp_path):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-folder-key')
    queue = ImportSessions(vault)
    with pytest.raises(BridgeRequestError):
        queue.enqueue(['a'] * 1001, JobRegistry())
    outside = tmp_path / 'outside'
    outside.mkdir()
    queue.root.symlink_to(outside, target_is_directory=True)
    with pytest.raises(BridgeRequestError, match='unavailable'):
        queue.listing()
    vault.close()


def test_cancelled_capture_keeps_queue_paused_and_can_resume_without_losing_sources(tmp_path, monkeypatch):
    vault = Vault.open(tmp_path / 'vault', 'synthetic-folder-key')
    queue = ImportSessions(vault)
    jobs = JobRegistry()
    put = vault.raw.put

    def stop_after_capture(data):
        document = put(data)
        jobs.cancel(jobs.active('viva.documents.upload_many').job_id)
        return document

    monkeypatch.setattr(vault.raw, 'put', stop_after_capture)
    saved = queue.enqueue(_files(tmp_path, 3), jobs)
    assert saved['state'] == 'stopped'
    assert saved['remaining'] == 3
    assert [row['status'] for row in saved['rows']] == ['pending', 'capturing', 'capturing']
    monkeypatch.setattr(vault.raw, 'put', put)
    calls = []
    result = queue.resume(saved['session_id'], _operation(vault, calls))
    assert result['session']['completed'] == 3
    assert len(calls) == 1
    vault.close()


def test_status_operation_never_admits_capture_or_resume_and_does_not_create_empty_queue(tmp_path):
    from viva.desktop_bridge.document_actions import DocumentActions
    vault = Vault.open(tmp_path / 'vault', 'synthetic-folder-key')
    actions = DocumentActions(vault)
    before = vault.ledger.store.authenticated_identity()
    assert actions.imports_read({'list_sessions': True}) == {'sessions': []}
    assert not (vault.directory / 'import-sessions').exists()
    for payload in ({'queue_paths': ['synthetic']}, {'session_id': 'a' * 32, 'resume': True},
                    {'list_sessions': True, 'resume': True}):
        with pytest.raises(BridgeRequestError):
            actions.imports_read(payload)
    assert vault.ledger.store.authenticated_identity() == before
    vault.close()
