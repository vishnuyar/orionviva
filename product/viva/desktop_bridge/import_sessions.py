"""Encrypted folder queues preserve selected originals across app restarts."""
from contextlib import contextmanager
import hmac
import json
import os
from pathlib import Path
import re
import stat
import uuid

from ..crypto import open_sealed, seal
from ..ledger.platform_io import lock_writer, unlock_writer, replace_commit_head
from .handlers import BridgeRequestError
from .jobs import JobCancelled

CONTRACT = 'document-import-session-v1'
READ_OPERATION = 'viva.documents.imports.read'
MAX_ROWS = 1000
MAX_RECEIPT_BYTES = 8_000_000
_STATES = {'capturing', 'pending', 'running', 'posted', 'held', 'parked', 'duplicate',
           'refused', 'failed', 'cancelled', 'conflict', 'gap', 'identity', 'awaiting'}


class ImportSessions:
    def __init__(self, vault):
        self.vault = vault
        self.root = vault.directory / 'import-sessions'
        self.key = hmac.digest(vault.raw._key, CONTRACT.encode(), 'sha256')

    def _directory(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        mode = self.root.lstat()
        if (not stat.S_ISDIR(mode.st_mode) or mode.st_uid != os.getuid()
                or mode.st_mode & 0o077):
            raise BridgeRequestError('import queue storage unavailable')

    def _path(self, identifier):
        if type(identifier) is not str or re.fullmatch('[0-9a-f]{32}', identifier) is None:
            raise BridgeRequestError('invalid import session')
        return self.root / (identifier + '.json')

    @contextmanager
    def _locked(self, identifier):
        self._directory()
        path = self._path(identifier).with_suffix('.lock')
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise BridgeRequestError('import queue lock unavailable')
            lock_writer(descriptor)
            yield
        finally:
            unlock_writer(descriptor)
            os.close(descriptor)

    def _save(self, record):
        path = self._path(record['session_id'])
        payload = json.dumps(record, separators=(',', ':'), ensure_ascii=False).encode()
        if len(payload) > MAX_RECEIPT_BYTES:
            raise BridgeRequestError('import queue exceeds bound')
        encoded = json.dumps(seal(self.key, payload, (CONTRACT + record['session_id']).encode())).encode()
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as target:
                target.write(encoded)
                target.flush()
                os.fsync(target.fileno())
            replace_commit_head(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _load(self, identifier):
        path = self._path(identifier)
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as source:
                info = os.fstat(source.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                        or info.st_mode & 0o077 or info.st_size > MAX_RECEIPT_BYTES * 2):
                    raise ValueError()
                encoded = source.read(MAX_RECEIPT_BYTES * 2 + 1)
            if len(encoded) > MAX_RECEIPT_BYTES * 2:
                raise ValueError()
            record = json.loads(open_sealed(self.key, json.loads(encoded),
                                           (CONTRACT + identifier).encode()))
            if (set(record) != {'contract', 'session_id', 'rows'} or record['contract'] != CONTRACT
                    or record['session_id'] != identifier or type(record['rows']) is not list
                    or not 1 <= len(record['rows']) <= MAX_ROWS):
                raise ValueError()
            for ordinal, row in enumerate(record['rows']):
                if (type(row) is not dict or set(row) != {'ordinal', 'document_id', 'filename', 'path', 'status', 'outcome'}
                        or row['ordinal'] != ordinal or row['status'] not in _STATES
                        or type(row['filename']) is not str or type(row['path']) is not str
                        or row['document_id'] is not None and re.fullmatch('[0-9a-f]{64}', row['document_id']) is None):
                    raise ValueError()
            return record
        except Exception:
            raise BridgeRequestError('import queue unavailable') from None

    def snapshot(self, record, *, rows=True):
        pending = sum(row['status'] in {'capturing', 'pending', 'running'} for row in record['rows'])
        interrupted = any(row['status'] == 'running' for row in record['rows'])
        result = dict(session_id=record['session_id'], total=len(record['rows']),
                      completed=len(record['rows']) - pending, remaining=pending,
                      state='interrupted' if interrupted else 'pending' if pending else 'completed',
                      label=record['rows'][0]['filename'][:240])
        if rows:
            result['rows'] = [{key: value for key, value in row.items() if key != 'path'}
                              for row in record['rows']]
        return result

    def _capture(self, record, jobs=None, job=None):
        from .document_actions import _refusal
        from ..ingest.reader import MAX_BYTES
        for row in record['rows']:
            if row['status'] != 'capturing':
                continue
            if job is not None:
                job.checkpoint()
            path = Path(row['path'])
            refusal = _refusal(path)
            reason = refusal.reason if refusal else None
            if reason is None:
                try:
                    with path.open('rb') as original:
                        data = original.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        reason = 'file_over_size_limit'
                    else:
                        row['document_id'] = self.vault.raw.put(data)
                except OSError:
                    reason = 'file_unreadable'
            row['status'] = 'refused' if reason else 'pending'
            row['path'] = ''
            if reason:
                row['outcome'] = dict(ordinal=row['ordinal'], document_id=None,
                                      action='refused', disposition=None, reason=reason)
            self._save(record)

    def enqueue(self, paths, jobs):
        if (type(paths) is not list or not 1 <= len(paths) <= MAX_ROWS
                or any(type(path) is not str or not path.strip() or len(path.encode()) > 4096 for path in paths)):
            raise BridgeRequestError('one to one thousand bounded import paths required')
        identifier = uuid.uuid4().hex
        record = dict(contract=CONTRACT, session_id=identifier, rows=[
            dict(ordinal=index, document_id=None, filename=Path(path).name, path=str(Path(path).absolute()),
                 status='capturing', outcome=None) for index, path in enumerate(paths)])
        with self._locked(identifier):
            self._save(record)
            job = jobs.open('viva.documents.upload_many', ('queued', 'captured'))
            try:
                with job:
                    job.reached('queued')
                    self._capture(record, jobs, job)
                    job.reached('captured')
            except JobCancelled:
                pass
            result = {**self.snapshot(record), 'job_id': job.job_id}
            if jobs.cancel_requested(job.job_id):
                result['state'] = 'stopped'
            return result

    def listing(self):
        if not self.root.exists() and not self.root.is_symlink():
            return {'sessions': []}
        self._directory()
        sessions = []
        paths = sorted(self.root.glob('*.json'))
        if len(paths) > 1000:
            raise BridgeRequestError('import queue listing exceeds bound')
        for path in paths:
            record = self._load(path.stem)
            summary = self.snapshot(record, rows=False)
            if summary['remaining']:
                sessions.append(summary)
        return {'sessions': sessions}

    def inspect(self, identifier):
        self._directory()
        return self.snapshot(self._load(identifier))

    def resume(self, identifier, operation):
        with self._locked(identifier):
            record = self._load(identifier)
            if any(row['status'] == 'capturing' for row in record['rows']):
                job = operation.jobs.open('viva.documents.upload_many', ('queued', 'captured'))
                operation.job_id = job.job_id
                try:
                    with job:
                        job.reached('queued')
                        self._capture(record, operation.jobs, job)
                        job.reached('captured')
                except JobCancelled:
                    return dict(job_id=job.job_id, rows=[],
                                session={**self.snapshot(record), 'state': 'stopped'})
                finally:
                    operation.job_id = None
            selected = [row for row in record['rows'] if row['status'] in {'pending', 'running'}][:3]
            if not selected:
                return dict(job_id='', rows=[], session=self.snapshot(record))
            for row in selected:
                row['status'] = 'running'
            self._save(record)
            result = operation.run_queued([dict(doc_id=row['document_id'], filename=row['filename'])
                                           for row in selected])
            if len(result['rows']) != len(selected):
                raise BridgeRequestError('import queue outcome is incomplete')
            for row, outcome in zip(selected, result['rows']):
                if outcome.get('document_id') not in (None, row['document_id']):
                    raise BridgeRequestError('import queue outcome identity differs')
                row['outcome'] = {**outcome, 'ordinal': row['ordinal']}
                if outcome.get('reason') == 'outcome_unknown':
                    row['status'] = 'running'
                else:
                    row['status'] = outcome['action'] if outcome['action'] in _STATES else 'failed'
            self._save(record)
            return {**result, 'session': self.snapshot(record)}


def handle(vault, jobs, payload, operation):
    """Dispatch only closed queue forms; ordinary bulk payloads pass through."""
    if type(payload) is not dict:
        return None
    if set(payload) == {'queue_paths'}:
        return ImportSessions(vault).enqueue(payload['queue_paths'], jobs)
    if set(payload) == {'list_sessions'} and payload['list_sessions'] is True:
        return ImportSessions(vault).listing()
    if set(payload) == {'session_id', 'resume'} and payload['resume'] is True:
        return ImportSessions(vault).resume(payload['session_id'], operation)
    if set(payload) == {'session_id', 'inspect'} and payload['inspect'] is True:
        return ImportSessions(vault).inspect(payload['session_id'])
    return None
