"""Portable, pinned synthetic vault artifacts and private verified restoration."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import os
import re
from pathlib import Path, PurePosixPath
import stat
import zipfile

from .resources import VERSION, MANIFEST_SHA256, READINGS_SHA256

CONTRACT = 'prepared-synthetic-vault-v1'
MAX_FILES = 4096
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
CHUNK = 1024 * 1024


def _error(message):
    from .instances import SampleBuildError
    return SampleBuildError(message)


def _name(name):
    if type(name) is not str: raise _error('invalid prepared sample member')
    path = PurePosixPath(name)
    if (type(name) is not str or not name or '\\' in name
            or path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/'))
            or path.parts[0] != 'vault' or len(path.parts) < 2):
        raise _error('invalid prepared sample member')
    return path


def _hash(stream, sink=None):
    digest = hashlib.sha256(); size = 0
    while block := stream.read(CHUNK):
        size += len(block)
        if size > MAX_FILE_BYTES:
            raise _error('prepared sample member exceeds its bound')
        digest.update(block)
        if sink is not None: sink.write(block)
    return size, digest.hexdigest()


def code_compatibility():
    """Bind portable behavior to package sources, prompts and financial schemas."""
    import viva, vivacore, merchantcore
    rows = {}
    for package in (viva, vivacore, merchantcore):
        root = Path(package.__file__).resolve().parent
        if not (root/'__init__.py').is_file():
            raise _error('sample compatibility package source is missing')
        for path in sorted(root.rglob('*')):
            relative = path.relative_to(root).as_posix()
            if (path.suffix not in ('.py', '.json', '.txt')
                    or '__pycache__' in path.parts or relative.startswith('sample_snapshots/')):
                continue
            if path.is_symlink() or not path.is_file():
                raise _error('sample code compatibility source is not ordinary')
            with path.open('rb') as source:
                if package.__name__ == 'viva' and relative == 'sample/resources.py':
                    data = source.read(MAX_FILE_BYTES+1)
                    if len(data) > MAX_FILE_BYTES: raise _error('sample compatibility source exceeds its bound')
                    data, count = re.subn(rb"(?m)^SNAPSHOT_MANIFEST_SHA256 = '[^']*'$",
                                          b"SNAPSHOT_MANIFEST_SHA256 = '<artifact pin>'", data)
                    if count != 1: raise _error('sample artifact pin assignment is ambiguous')
                    digest = hashlib.sha256(data).hexdigest()
                else: _, digest = _hash(source)
            rows[package.__name__+'/'+relative] = digest
    if not rows: raise _error('sample code compatibility source is missing')
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _metadata(root):
    from .resources import SNAPSHOT_MANIFEST_SHA256
    if isinstance(root, Path) and any(parent.is_symlink() for parent in (root, *root.parents)):
        raise _error('prepared sample resources traverse a symlink')
    for member in (root, root.joinpath('snapshot.json'), root.joinpath('vault.zip')):
        if getattr(member, 'is_symlink', lambda:False)():
            raise _error('prepared sample resources must be ordinary')
    if (not root.is_dir() or not root.joinpath('snapshot.json').is_file()
            or not root.joinpath('vault.zip').is_file()):
        raise _error('prepared sample resource closure is missing')
    with root.joinpath('snapshot.json').open('rb') as stream:
        data = stream.read(MAX_MANIFEST_BYTES+1)
    if len(data) > MAX_MANIFEST_BYTES or hashlib.sha256(data).hexdigest() != SNAPSHOT_MANIFEST_SHA256:
        raise _error('prepared sample manifest is incompatible')
    from .worker import _closed_object
    value = json.loads(data, object_pairs_hook=_closed_object)
    if (set(value) != {'contract', 'version', 'manifest_sha256', 'readings_sha256',
                      'documents', 'members', 'archive_sha256', 'build_runtime_identity', 'event_identity', 'code_compatibility'}
            or value['contract'] != CONTRACT or value['version'] != VERSION
            or value['manifest_sha256'] != MANIFEST_SHA256 or value['readings_sha256'] != READINGS_SHA256
            or value['documents'] != 794 or type(value['members']) is not dict
            or not 1 <= len(value['members']) <= MAX_FILES):
        raise _error('prepared sample contract is incompatible')
    if (type(value['archive_sha256']) is not str
            or re.fullmatch('[0-9a-f]{64}', value['archive_sha256']) is None):
        raise _error('prepared sample archive receipt is invalid')
    if value['code_compatibility'] != code_compatibility():
        raise _error('prepared sample code compatibility differs')
    total = 0
    for name, row in value['members'].items():
        _name(name)
        if (type(row) is not dict or set(row) != {'size', 'sha256'}
                or type(row['size']) is not int or not 0 <= row['size'] <= MAX_FILE_BYTES
                or type(row['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None):
            raise _error('prepared sample member receipt is invalid')
        total += row['size']
    if total > MAX_TOTAL_BYTES: raise _error('prepared sample exceeds its bound')
    if not {'vault/events.jsonl', 'vault/events.jsonl.head', 'vault/raw/raw-header.json'} <= set(value['members']):
        raise _error('prepared sample canonical stores are missing')
    return value


def restore(instance, root=None):
    """Copy authenticated members into a fresh private instance, then verify sources."""
    from .instances import PASSPHRASE, _ordinary, _runtime_identity, _write, completion_failures
    from .resources import load_pack
    from ..vault import Vault
    from ..demo import _prepare_demo_read_store
    import time
    started = time.monotonic(); runtime = _runtime_identity()
    runtime_done = time.monotonic()
    root = files('viva').joinpath('sample_snapshots', VERSION) if root is None else root
    _ordinary(instance)
    if any(ancestor.is_symlink() for ancestor in (instance, *instance.parents)):
        raise _error('prepared sample destination traverses a symlink')
    if (instance/'vault').exists() or (instance/'vault').is_symlink():
        raise _error('prepared sample requires a fresh destination')
    metadata = _metadata(root)
    archive = root.joinpath('vault.zip')
    with archive.open('rb') as stream:
        # Archive and every decompressed member are independently authenticated.
        size, digest = _hash(stream)
        if digest != metadata['archive_sha256']: raise _error('prepared sample archive differs')
    with archive.open('rb') as stream, zipfile.ZipFile(stream) as bundle:
        members = bundle.infolist()
        if (len(members) != len(metadata['members'])
                or {item.filename for item in members} != set(metadata['members'])):
            raise _error('prepared sample member closure differs')
        for item in members:
            name = _name(item.filename)
            mode = item.external_attr >> 16
            if item.is_dir() or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                raise _error('prepared sample member is not ordinary')
            expected = metadata['members'][item.filename]
            if item.file_size != expected['size']: raise _error('prepared sample member length differs')
            target = instance.joinpath(*name.parts)
            parent = instance
            for part in name.parts[:-1]:
                parent = parent/part
                parent.mkdir(mode=0o700, exist_ok=True)
                _ordinary(parent)
            fd = os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'wb') as output, bundle.open(item) as source:
                actual = _hash(source, output)
                output.flush(); os.fsync(output.fileno())
            if actual != (expected['size'], expected['sha256']):
                raise _error('prepared sample member digest differs')
    for directory in sorted((path for path in (instance/'vault').rglob('*') if path.is_dir()), reverse=True):
        descriptor = os.open(directory, os.O_RDONLY|os.O_NOFOLLOW)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    descriptor = os.open(instance/'vault', os.O_RDONLY|os.O_NOFOLLOW)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)
    archive_done = time.monotonic()
    pack = load_pack(); resources_done = time.monotonic()
    vault = Vault.open(instance/'vault', PASSPHRASE, create=False)
    opened = time.monotonic()
    try:
        projection = vault.ledger.projection(); expected = {row['sha256'] for row in pack.documents}
        if set(projection.captured_docs()) != expected or set(vault.raw.doc_ids()) != expected:
            raise _error('prepared sample source closure differs')
        for document in pack.documents:
            if vault.raw.get(document['sha256']) != pack.original(document):
                raise _error('prepared sample original differs')
        if completion_failures(pack, projection): raise _error('prepared sample financial checks failed')
        identity = list(vault.ledger.store.authenticated_identity())
        if identity != metadata['event_identity']: raise _error('prepared sample history differs')
        validation_done = time.monotonic()
        _prepare_demo_read_store(vault)
        sql_done = time.monotonic()
        if _runtime_identity() != runtime: raise _error('sample runtime changed during restoration')
        runtime_final_done = time.monotonic()
        posted = min(len(projection.posted_doc_ids()), 794)
        report = {'contract':'sample-instance-v1', 'version':VERSION, 'state':'ready',
                  'readiness_failures':[], 'manifest_sha256':MANIFEST_SHA256,
                  'readings_sha256':READINGS_SHA256, 'documents':794,
                  'event_identity':identity, 'runtime_identity':runtime,
                  'reference_day':'2026-01-01', 'recorded_through':'2025-12-31',
                  'complete_seconds':time.monotonic()-started, 'prepared_snapshot':CONTRACT,
                  'phase_seconds':{'runtime_identity_initial':runtime_done-started,
                      'archive_restore':archive_done-runtime_done,
                      'source_pack_validation':resources_done-archive_done,
                      'vault_open':opened-resources_done,
                      'financial_source_validation':validation_done-opened,
                      'sql':sql_done-validation_done,
                      'runtime_identity_final':runtime_final_done-sql_done}}
        _write(instance/'progress-0794.json', {'completed_documents':794,
               'posted_documents':posted, 'held_documents':794-posted})
        _write(instance/'sample-instance.json', report)
        return report
    finally: vault.close()


def _public_build_identity(runtime):
    """Publish portable build proof while retaining paths in the private receipt."""
    encoded = json.dumps(runtime, sort_keys=True, separators=(',', ':')).encode()
    return {name: runtime[name] for name in
            ('files_sha256', 'file_count', 'python', 'executable_sha256')} | {
                'identity_sha256': hashlib.sha256(encoded).hexdigest()}


def export(instance, destination):
    """Export only a fully validated synthetic instance; never accept personal vaults."""
    from .instances import _reopen_worker
    report = _reopen_worker(instance)
    receipt = json.loads((instance/'sample-instance.json').read_text())
    if (receipt.get('documents') != 794
            or report['event_identity'] != receipt.get('event_identity')
            or len(receipt.get('outcomes', [])) != 794
            or receipt.get('replay_agreement', {}).get('state') != 'equal'
            or receipt['replay_agreement'].get('event_identity') != receipt.get('event_identity')):
        raise _error('cannot export an incomplete or modified sample')
    from ..vault import Vault
    from .instances import PASSPHRASE
    from .resources import load_pack
    vault = Vault.open(instance/'vault', PASSPHRASE, create=False)
    try:
        expected = {row['sha256'] for row in load_pack().documents}
        if set(vault.raw.doc_ids()) != expected or set(vault.ledger.projection().captured_docs()) != expected:
            raise _error('cannot export a sample with additional sources')
    finally: vault.close()
    destination = Path(destination); destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    members = {}; total = 0
    with zipfile.ZipFile(destination/'vault.zip', 'x', compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((instance/'vault').rglob('*')):
            if path.is_symlink(): raise _error('cannot export linked sample members')
            if path.is_dir(): continue
            if not path.is_file(): raise _error('cannot export special sample members')
            if path.name.endswith('.lock') or 'quarantine' in path.relative_to(instance).parts: continue
            name = path.relative_to(instance).as_posix(); _name(name)
            with path.open('rb') as source: size, digest = _hash(source)
            total += size
            if len(members) >= MAX_FILES or total > MAX_TOTAL_BYTES: raise _error('sample export exceeds its bound')
            members[name] = {'size':size, 'sha256':digest}
            bundle.write(path, name)
    with (destination/'vault.zip').open('rb') as source: _, archive_digest = _hash(source)
    metadata = {'contract':CONTRACT, 'version':VERSION, 'manifest_sha256':MANIFEST_SHA256,
                'readings_sha256':READINGS_SHA256, 'documents':794, 'members':members,
                'archive_sha256':archive_digest, 'build_runtime_identity':_public_build_identity(receipt['runtime_identity']),
                'event_identity':report['event_identity'], 'code_compatibility':code_compatibility()}
    encoded = json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode()
    (destination/'snapshot.json').write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()
