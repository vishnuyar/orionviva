"""Validate the complete installed source closure before any sample mutation."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
from importlib.resources import files
import json
from types import MappingProxyType

VERSION = 'five-year-life-v1'
MANIFEST_SHA256 = '97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800'
READINGS_SHA256 = 'dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab'
# Pinned prepared artifact metadata; regenerated only by the sample build tool.
SNAPSHOT_MANIFEST_SHA256 = 'unbuilt'
MAX_RESOURCE_BYTES = 8000000

class SampleResourceError(ValueError):
    """Installed sample resources are incomplete or incompatible."""

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()

def digest(blob): return hashlib.sha256(blob).hexdigest()

@dataclass(frozen=True)
class SourcePack:
    root: object
    documents: tuple
    readings: object
    source_event_count: int
    def original(self, document):
        data = self.root.joinpath(document['file']).read_bytes()
        if digest(data) != document['sha256']:
            raise SampleResourceError('sample original changed')
        return data

def load_pack(root=None):
    root = files('viva').joinpath('sample_data', VERSION) if root is None else root
    try:
        if getattr(root,'is_symlink',lambda:False)():
            raise ValueError('sample resource root must be ordinary')
        members=list(root.iterdir())
        if any(getattr(entry, 'is_symlink', lambda:False)() or not entry.is_file() for entry in members):
            raise ValueError('sample resource members must be ordinary files')
        names={entry.name for entry in members}
        manifest_bytes=root.joinpath('manifest.json').read_bytes()
        readings_bytes=root.joinpath('readings.json').read_bytes()
        if (len(manifest_bytes)>MAX_RESOURCE_BYTES or len(readings_bytes)>MAX_RESOURCE_BYTES
                or digest(manifest_bytes)!=MANIFEST_SHA256 or digest(readings_bytes)!=READINGS_SHA256):
            raise ValueError('sample resource digest mismatch')
        manifest=json.loads(manifest_bytes); readings=json.loads(readings_bytes)
        closure=json.loads(root.joinpath('closure.json').read_bytes())
        if closure != {'version':VERSION,'manifest_sha256':MANIFEST_SHA256,
                       'readings_sha256':READINGS_SHA256,'document_count':794,
                       'page_count':913,'source_event_count':3531}:
            raise ValueError('sample closure version is incompatible')
        documents=manifest['documents']
        if (len(documents)!=794 or sum(row['page_count'] for row in documents)!=913
                or readings['contract']!='curated-source-reading-v2'
                or readings['source_event_count']!=3531
                or readings['source_ledger_sha256']!='e4f805f47717d99262a720a8c7e284180f2b157b3713b40ea41efc682a84fb54'
                or len(readings['readings'])!=794):
            raise ValueError('sample closure is incomplete')
        expected={'manifest.json','readings.json','closure.json'} | {row['file'] for row in documents}
        if names!=expected or len(expected)!=797:
            raise ValueError('sample resource members do not match')
        by_id={row['document_sha256']:row for row in readings['readings']}
        if len(by_id)!=794 or set(by_id)!={row['sha256'] for row in documents}:
            raise ValueError('sample reading mapping is not one to one')
        import pypdfium2 as pdfium
        for row in documents:
            if row['file']!=row['file'].split('/')[-1] or not row['file'].endswith('.pdf'):
                raise ValueError('invalid sample resource member')
            data=root.joinpath(row['file']).read_bytes()
            if len(data)>50*1024*1024 or digest(data)!=row['sha256']:
                raise ValueError('sample document digest mismatch')
            pdf=pdfium.PdfDocument(data)
            try:
                if len(pdf)!=row['page_count']: raise ValueError('sample document page mismatch')
            finally: pdf.close()
            reading=by_id[row['sha256']]
            if reading['document_id']!=row['id']: raise ValueError('sample reading identity mismatch')
            def pages(value):
                if type(value) is dict:
                    if 'page' in value and value['page'] is not None:
                        if type(value['page']) is not int or not 1<=value['page']<=row['page_count']:
                            raise ValueError('sample reading page is outside source')
                    for item in value.values(): pages(item)
                elif type(value) is list:
                    for item in value: pages(item)
            pages(reading['envelope'])
        return SourcePack(root,tuple(documents),MappingProxyType(by_id),3531)
    except (OSError,KeyError,TypeError,ValueError) as error:
        raise SampleResourceError('installed sample source closure is invalid') from error
