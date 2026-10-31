"""Portable prepared-artifact rejection and private-copy boundaries."""
import hashlib
import json
import os
from pathlib import Path
import stat
import zipfile

import pytest

from viva.sample import resources, snapshot
from viva.sample.instances import SampleBuildError


def fixture_artifact(root, monkeypatch, *, names=None):
    root.mkdir()
    names = names or {'vault/events.jsonl':b'events', 'vault/events.jsonl.head':b'head',
                      'vault/raw/raw-header.json':b'header'}
    with zipfile.ZipFile(root/'vault.zip', 'w') as bundle:
        for name, data in names.items(): bundle.writestr(name, data)
    metadata = {'contract':snapshot.CONTRACT, 'version':resources.VERSION,
                'manifest_sha256':resources.MANIFEST_SHA256,
                'readings_sha256':resources.READINGS_SHA256, 'documents':794,
                'members':{name:{'size':len(data), 'sha256':hashlib.sha256(data).hexdigest()}
                           for name, data in names.items()},
                'archive_sha256':hashlib.sha256((root/'vault.zip').read_bytes()).hexdigest(),
                'build_runtime_identity':{'fixture':'synthetic'}, 'event_identity':[1,'fixture',1],
                'code_compatibility':'fixture-code'}
    monkeypatch.setattr(snapshot, 'code_compatibility', lambda:'fixture-code')
    write_metadata(root, metadata, monkeypatch)
    return metadata


def write_metadata(root, metadata, monkeypatch):
    data = json.dumps(metadata).encode()
    (root/'snapshot.json').write_bytes(data)
    monkeypatch.setattr(resources, 'SNAPSHOT_MANIFEST_SHA256', hashlib.sha256(data).hexdigest())


def test_metadata_is_pinned_and_code_bound(tmp_path, monkeypatch):
    root = tmp_path/'artifact'; metadata = fixture_artifact(root, monkeypatch)
    assert snapshot._metadata(root)['documents'] == 794
    monkeypatch.setattr(snapshot, 'code_compatibility', lambda:'changed-code')
    with pytest.raises(SampleBuildError, match='code compatibility'): snapshot._metadata(root)
    monkeypatch.setattr(snapshot, 'code_compatibility', lambda:'fixture-code')
    (root/'snapshot.json').write_bytes(b'{}')
    with pytest.raises(SampleBuildError, match='manifest'): snapshot._metadata(root)


@pytest.mark.parametrize('name', ['vault/../../escape', '/vault/escape', 'vault//escape',
                                  'vault/./escape', 'vault\\escape', 'other/escape'])
def test_member_names_cannot_escape(name):
    with pytest.raises(SampleBuildError): snapshot._name(name)


@pytest.mark.parametrize('change', ['version','closure','oversize','missing'])
def test_incompatible_or_unbounded_metadata_rejected(tmp_path, monkeypatch, change):
    root = tmp_path/'artifact'; metadata = fixture_artifact(root, monkeypatch)
    if change == 'version': metadata['contract'] = 'future-contract'
    elif change == 'closure': metadata['documents'] = 793
    elif change == 'oversize': metadata['members']['vault/events.jsonl']['size'] = snapshot.MAX_FILE_BYTES+1
    else: del metadata['members']['vault/events.jsonl.head']
    write_metadata(root, metadata, monkeypatch)
    with pytest.raises(SampleBuildError): snapshot._metadata(root)


@pytest.mark.parametrize('change', ['bytes', 'duplicate', 'symlink', 'extra'])
def test_archive_tampering_never_opens_vault(tmp_path, monkeypatch, change):
    root = tmp_path/'artifact'; metadata = fixture_artifact(root, monkeypatch)
    instance = tmp_path/'instance'; instance.mkdir(mode=0o700)
    monkeypatch.setattr('viva.sample.instances._runtime_identity', lambda:{'fixture':'runtime'})
    if change == 'bytes':
        with (root/'vault.zip').open('ab') as stream: stream.write(b'changed')
    elif change == 'symlink':
        with zipfile.ZipFile(root/'vault.zip', 'r') as bundle:
            contents = {item.filename:bundle.read(item) for item in bundle.infolist()}
        with zipfile.ZipFile(root/'vault.zip', 'w') as bundle:
            for name, data in contents.items():
                entry = zipfile.ZipInfo(name)
                entry.create_system = 3
                entry.external_attr = ((stat.S_IFLNK if name == 'vault/events.jsonl' else stat.S_IFREG)|0o600)<<16
                bundle.writestr(entry, data)
        metadata['archive_sha256'] = hashlib.sha256((root/'vault.zip').read_bytes()).hexdigest()
        write_metadata(root, metadata, monkeypatch)
    else:
        with zipfile.ZipFile(root/'vault.zip', 'a') as bundle:
            if change == 'duplicate': bundle.writestr('vault/events.jsonl', b'events')
            elif change == 'extra': bundle.writestr('vault/extra', b'extra')
            else:
                entry = zipfile.ZipInfo('vault/events.jsonl')
                entry.create_system = 3; entry.external_attr = (stat.S_IFLNK|0o777)<<16
                bundle.writestr(entry, b'events')
        metadata['archive_sha256'] = hashlib.sha256((root/'vault.zip').read_bytes()).hexdigest()
        write_metadata(root, metadata, monkeypatch)
    with pytest.raises(SampleBuildError): snapshot.restore(instance, root)
    assert not (instance/'sample-instance.json').exists()
    assert not (tmp_path/'escape').exists()


def test_stream_hash_has_a_size_bound(monkeypatch):
    import io
    monkeypatch.setattr(snapshot, 'MAX_FILE_BYTES', 4)
    with pytest.raises(SampleBuildError): snapshot._hash(io.BytesIO(b'12345'))


def test_existing_or_linked_destination_is_rejected(tmp_path, monkeypatch):
    instance=tmp_path/'instance'; instance.mkdir(mode=0o700)
    target=tmp_path/'foreign'; target.mkdir()
    (instance/'vault').symlink_to(target)
    monkeypatch.setattr('viva.sample.instances._runtime_identity', lambda:{'fixture':'runtime'})
    with pytest.raises(SampleBuildError, match='fresh destination'): snapshot.restore(instance, tmp_path/'absent')
    assert list(target.iterdir()) == []


def test_reduced_source_fixture_restores_encrypted_stores_and_regenerates_receipt(tmp_path, monkeypatch):
    """Exercise copy/open against real stores; production load_pack enforces all794."""
    from types import SimpleNamespace
    from viva.vault import Vault
    from viva.ledger.events import document_captured
    from viva.sample import instances
    from viva.demo import _prepare_demo_read_store
    source = tmp_path/'source'; source.mkdir(mode=0o700)
    data = b'Synthetic source fixture for portable storage checks.'
    vault = Vault.open(source/'vault', instances.PASSPHRASE)
    identifier = vault.raw.put(data)
    vault.ledger.append(document_captured(identifier, 'synthetic.pdf', len(data),
                                         'unknown', 0.0, '2025-01-01'))
    _prepare_demo_read_store(vault)
    identity = list(vault.ledger.store.authenticated_identity())
    vault.close()
    contents = {path.relative_to(source).as_posix():path.read_bytes()
                for path in (source/'vault').rglob('*') if path.is_file() and not path.name.endswith('.lock')}
    artifact = tmp_path/'artifact'
    metadata = fixture_artifact(artifact, monkeypatch, names=contents)
    metadata['event_identity'] = identity
    write_metadata(artifact, metadata, monkeypatch)
    pack = SimpleNamespace(documents=({'sha256':identifier},), original=lambda document:data)
    monkeypatch.setattr(resources, 'load_pack', lambda:pack)
    monkeypatch.setattr(instances, 'completion_failures', lambda pack, projection:[])
    monkeypatch.setattr(instances, '_runtime_identity', lambda:{'fixture':'restoring-runtime'})
    target = tmp_path/'target'; target.mkdir(mode=0o700)
    report = snapshot.restore(target, artifact)
    assert report['state'] == 'ready'
    assert report['runtime_identity'] == {'fixture':'restoring-runtime'}
    assert report['event_identity'] == identity
    restored = Vault.open(target/'vault', instances.PASSPHRASE, create=False)
    try:
        assert restored.raw.get(identifier) == data
        assert list(restored.ledger.store.authenticated_identity()) == identity
        _prepare_demo_read_store(restored)
    finally: restored.close()
    for path in (target/'vault').rglob('*'):
        assert not path.is_symlink()
        assert path.stat().st_uid == os.getuid()
        assert path.stat().st_mode & 0o077 == 0
    original = source/'vault/events.jsonl'
    copied = target/'vault/events.jsonl'
    assert original.stat().st_ino != copied.stat().st_ino
    assert (source/'sample-instance.json').exists() is False


def test_portable_code_digest_normalizes_only_its_own_artifact_pin(tmp_path, monkeypatch):
    import viva, vivacore, merchantcore
    for package in (viva, vivacore, merchantcore):
        root = tmp_path/package.__name__; root.mkdir()
        (root/'__init__.py').write_text('"""Synthetic package source."""\n')
        monkeypatch.setattr(package, '__file__', str(root/'__init__.py'))
    sample = tmp_path/'viva/sample'; sample.mkdir()
    resource = sample/'resources.py'
    resource.write_text("SNAPSHOT_MANIFEST_SHA256 = 'first-pin'\nVALIDATION_CONTRACT = 1\n")
    original = snapshot.code_compatibility()
    resource.write_text("SNAPSHOT_MANIFEST_SHA256 = 'second-pin'\nVALIDATION_CONTRACT = 1\n")
    assert snapshot.code_compatibility() == original
    resource.write_text("SNAPSHOT_MANIFEST_SHA256 = 'second-pin'\nVALIDATION_CONTRACT = 2\n")
    assert snapshot.code_compatibility() != original
    artifact = tmp_path/'viva/sample_snapshots'; artifact.mkdir()
    (artifact/'synthetic.json').write_text('{}')
    before_artifact = snapshot.code_compatibility()
    (artifact/'synthetic.json').write_text('{"updated":true}')
    assert snapshot.code_compatibility() == before_artifact
    (tmp_path/'merchantcore/__init__.py').unlink()
    with pytest.raises(SampleBuildError, match='package source'): snapshot.code_compatibility()


def test_public_build_identity_retains_proof_without_publishing_private_paths():
    from copy import deepcopy
    private = {'roots': {'viva': '/private/synthetic-builder/product/viva'},
               'files_sha256': 'a'*64, 'file_count': 42,
               'python': 'synthetic-python-version',
               'executable': '/private/synthetic-builder/python',
               'executable_sha256': 'b'*64}
    original = deepcopy(private)
    public = snapshot._public_build_identity(private)
    assert set(public) == {'files_sha256', 'file_count', 'python',
                           'executable_sha256', 'identity_sha256'}
    for field in ('files_sha256', 'file_count', 'python', 'executable_sha256'):
        assert public[field] == private[field]
    assert public['identity_sha256'] == hashlib.sha256(
        json.dumps(private, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    assert '/private/synthetic-builder' not in json.dumps(public)
    assert private == original
    # Paths remain bound by proof even though the public representation omits them.
    for field in private:
        changed = deepcopy(private)
        changed[field] = {'viva': '/private/another-builder/viva'} if field == 'roots' else 'different'
        assert snapshot._public_build_identity(changed)['identity_sha256'] != public['identity_sha256']
    public.clear()
    assert private == original
