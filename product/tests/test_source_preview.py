"""Read-only original preview, independently specified source bytes."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from viva.ingest.raw_store import RawStore
from viva.source_preview import preview_document


def source(tmp_path, data=b'<script>PRIVATE MARKER</script>'):
    raw = RawStore(tmp_path, b'x' * 32)
    doc = raw.put(data)
    events = [SimpleNamespace(event_type='DocumentCaptured', body={'doc_id': doc, 'filename': 'source.txt'})]
    from contextlib import nullcontext
    ledger = SimpleNamespace(events=lambda: iter(events), store=SimpleNamespace(authenticated_identity=lambda:(1,'head',1)))
    def identity(_doc):
        rows={(event.body.get('filename',''),event.body.get('doc_type','')) for event in ledger.events() if event.body['doc_id']==_doc}
        if len(rows)>1:
            raise ValueError('conflicting identity')
        return next(iter(rows)) if rows else None
    revision=SimpleNamespace(generation='synthetic-generation',preview_capture_identity=identity,close=lambda:None)
    read_store=SimpleNamespace(open_reader=lambda:revision,authenticated_source_identity=lambda _:dict(count=1,head='head'))
    vault = SimpleNamespace(raw=raw, ledger=ledger, read_store=read_store)
    return vault, doc


def test_text_is_original_and_no_canonical_write(tmp_path):
    vault, doc = source(tmp_path)
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    reply = preview_document(vault, {'document_id': doc, 'page': 1})
    assert reply['status'] == 'ready'
    assert reply['text'] == '<script>PRIVATE MARKER</script>'
    assert reply['rendition_sha256'] == doc == reply['original_sha256']
    assert reply['png_base64'] is None
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('payload', [{'document_id':'../secret','page':1}, {'document_id':'a'*64,'page':True}, {'document_id':'a'*64,'page':1,'path':'SECRET'}])
def test_invalid_request_never_reflects_input(tmp_path, payload):
    vault, _ = source(tmp_path)
    reply = preview_document(vault, payload)
    assert reply['reason'] == 'invalid_request'
    assert 'secret' not in json.dumps(reply).lower()


def test_uncaptured_and_tampered_and_symlink_refused(tmp_path):
    vault, doc = source(tmp_path)
    assert preview_document(vault, {'document_id':'a'*64,'page':1})['reason'] == 'original_unavailable'
    blob = tmp_path / f'{doc}.blob'
    original = blob.read_bytes()
    blob.write_bytes(b'{}')
    assert preview_document(vault, {'document_id':doc,'page':1})['reason'] == 'damaged_original'
    blob.unlink()
    other = tmp_path / 'other'; other.write_bytes(original); blob.symlink_to(other)
    assert preview_document(vault, {'document_id':doc,'page':1})['reason'] == 'damaged_original'


def two_page_pdf():
    # Independently specified minimal PDF. Page 1 marker at (20,80), page 2
    # marker at (20,50); distinct source instructions, not product metadata.
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 120] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 120] /Resources << /Font << /F1 5 0 R >> >> /Contents 7 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    for text in (b'BT /F1 9 Tf 20 80 Td (SOURCE ALPHA PAGE ONE) Tj ET',
                 b'BT /F1 9 Tf 20 50 Td (SOURCE BETA PAGE TWO) Tj ET'):
        objects.append(b'<< /Length ' + str(len(text)).encode() + b' >>\nstream\n' + text + b'\nendstream')
    result = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref = len(result)
    result.extend(b'xref\n0 8\n0000000000 65535 f \n')
    for off in offsets[1:]:
        result.extend(f'{off:010d} 00000 n \n'.encode())
    result.extend(f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    return bytes(result)


def test_actual_pdf_requested_pages_distinct_and_exact_source_markers(tmp_path):
    vault, doc = source(tmp_path, two_page_pdf())
    replies = [preview_document(vault, {'document_id':doc,'page':n}) for n in (1,2)]
    assert all(x['status'] == 'ready' for x in replies), replies
    assert 'SOURCE ALPHA PAGE ONE' in replies[0]['text']
    assert 'SOURCE BETA PAGE TWO' not in replies[0]['text']
    assert 'SOURCE BETA PAGE TWO' in replies[1]['text']
    assert replies[0]['png_base64'] != replies[1]['png_base64']
    assert replies[0]['original_sha256'] == replies[1]['original_sha256'] == doc
    assert all(x['page_count'] == 2 and x['width'] <= 2000 for x in replies)
    assert preview_document(vault, {'document_id':doc,'page':3})['reason'] == 'page_unavailable'


def test_actual_png_normalized_no_metadata(tmp_path):
    import io, base64
    from PIL import Image, PngImagePlugin
    buf = io.BytesIO(); metadata=PngImagePlugin.PngInfo(); metadata.add_text('private','SECRET EXIF')
    Image.new('RGB',(64,32),'red').save(buf, format='PNG', pnginfo=metadata)
    vault, doc = source(tmp_path, buf.getvalue())
    reply = preview_document(vault, {'document_id':doc,'page':1})
    assert reply['status'] == 'ready', reply
    decoded=base64.b64decode(reply['png_base64'])
    assert b'SECRET EXIF' not in decoded
    assert reply['width'] == 64 and reply['height'] == 32
    assert reply['rendition_sha256'] == hashlib.sha256(decoded).hexdigest()


@pytest.mark.parametrize('data,reason', [(b'%PDF-corrupt', 'damaged_original'), (b'\xff\x00binary', 'unsupported_encoding'), (b'<svg>bad</svg>', 'unsupported_type'), (b'x'*(256*1024+1), 'over_limit')])
def test_unsupported_corrupt_or_bounded_original(tmp_path, data, reason):
    vault,doc=source(tmp_path,data)
    assert preview_document(vault,{'document_id':doc,'page':1})['reason'] == reason


def test_bounded_raw_hash_mismatch_and_envelope_limit(tmp_path):
    from viva.crypto import seal
    raw=RawStore(tmp_path,b'x'*32); doc='a'*64
    blob=tmp_path/f'{doc}.blob'; blob.write_text(json.dumps(seal(b'x'*32,b'wrong',aad=doc.encode())))
    with pytest.raises(ValueError, match='address mismatch'):
        raw.get_bounded(doc)
    blob.write_bytes(b'x'*100)
    with pytest.raises(OverflowError):
        raw.get_bounded(doc,max_envelope=99)


def test_worker_crash_timeout_and_output_bound(tmp_path,monkeypatch):
    import viva.source_preview as preview
    vault,doc=source(tmp_path)
    monkeypatch.setattr(preview,'worker_command',lambda:[os.sys.executable,'-c','raise SystemExit(2)'])
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='renderer_unavailable'
    monkeypatch.setattr(preview,'WORKER_TIMEOUT',.05)
    monkeypatch.setattr(preview,'worker_command',lambda:[os.sys.executable,'-c','import time; time.sleep(5)'])
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='timed_out'
    monkeypatch.setattr(preview,'WORKER_TIMEOUT',2)
    monkeypatch.setattr(preview,'worker_command',lambda:[os.sys.executable,'-c','import sys;sys.stdout.write("x"*2000000)'])
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='over_limit'


def test_real_authenticated_vault_membership_and_handler_absence(tmp_path):
    from viva.vault import Vault
    from viva.ledger.events import Event
    from viva.desktop_bridge.handlers import default_handlers, handlers_for_opened_vault
    from viva.source_preview import OPERATION
    vault=Vault.open(tmp_path/'vault','test source phrase',create=True)
    try:
        doc=vault.raw.put(b'CAPTURED REAL LEDGER SOURCE')
        assert OPERATION not in default_handlers().handlers
        vault.synchronize_read_store()
        assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='original_unavailable'
        vault.ledger.append(Event(event_type='DocumentCaptured',occurred_at='2026-10-24',body={'doc_id':doc,'filename':'source.txt'}))
        vault.synchronize_read_store()
        handler=handlers_for_opened_vault(vault).handlers[OPERATION]
        reply=handler({'document_id':doc,'page':1})
        assert reply['text']=='CAPTURED REAL LEDGER SOURCE'
    finally:
        vault.close()


def test_worker_render_has_no_network_or_configuration_import(monkeypatch):
    import socket, sys
    from viva import source_preview_worker as worker
    def forbidden(*args,**kwargs):
        raise AssertionError('outbound access')
    monkeypatch.setattr(socket,'socket',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)
    # PDF URI annotations are data; local rendering never follows them.
    pdf=two_page_pdf().replace(b'/Contents 6 0 R',b'/Annots [<< /Type /Annot /Subtype /Link /Rect [0 0 100 100] /A << /S /URI /URI (https://invalid.example/secret) >> >>] /Contents 6 0 R')
    # Replacing bytes invalidates xref offsets, which PDFium repairs locally.
    result=worker.render(pdf,1)
    assert 'SOURCE ALPHA PAGE ONE' in result['text']


def test_worker_dispatch_precedes_configuration_vault_imports():
    import ast
    from pathlib import Path
    source_text=(Path(__file__).parents[1]/'viva/desktop_bridge/__main__.py').read_text()
    tree=ast.parse(source_text)
    dispatch=next(n for n in tree.body if isinstance(n,ast.If) and 'source-preview-worker' in ast.get_source_segment(source_text,n))
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.module in ('viva.configuration','viva.vault','viva.desktop_bridge.handlers'):
            assert dispatch.lineno < node.lineno


def test_untrusted_worker_result_refused(tmp_path,monkeypatch):
    import viva.source_preview as preview
    vault,doc=source(tmp_path)
    monkeypatch.setattr(preview,'run_worker',lambda *_:dict(status='ready',source_kind='text',page=1,page_count=1,text='changed',png_base64=None,width=None,height=None,rendition_sha256='a'*64))
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='renderer_unavailable'


def test_worker_runs_with_no_configuration_or_vault_imports_and_empty_environment(tmp_path):
    import subprocess
    from pathlib import Path
    entry=Path(__file__).parents[1]/'viva/desktop_bridge/__main__.py'
    product=str(entry.parents[2])
    # Import hooks fail if the early dispatch reaches any private subsystem.
    script=f'''import runpy,sys,os
sys.path.insert(0,{product!r})
class Guard:
 def find_spec(self,name,path=None,target=None):
  if name in ("viva.configuration","viva.vault","viva.desktop_bridge.handlers"):
   raise AssertionError("private subsystem imported")
sys.meta_path.insert(0,Guard())
sys.argv=[{str(entry)!r},"--source-preview-worker"]
runpy.run_path({str(entry)!r},run_name="__main__")
'''
    result=subprocess.run([os.sys.executable,'-c',script],input=b'1\nSOURCE WITHOUT CONFIG',capture_output=True,env={},cwd='/',timeout=10)
    assert result.returncode==0, result.stderr
    reply=json.loads(result.stdout)
    assert reply['text']=='SOURCE WITHOUT CONFIG'


def test_foreign_conflicting_identity_and_plaintext_bound(tmp_path):
    vault,doc=source(tmp_path,b'x'*(8*1024*1024+1))
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='over_limit'
    events=[SimpleNamespace(event_type='DocumentCaptured',body={'doc_id':doc,'filename':name}) for name in ('a','b')]
    vault.ledger.events=lambda:iter(events)
    assert preview_document(vault,{'document_id':doc,'page':1})['reason']=='identity_unverifiable'


def test_actual_jpeg_and_multiframe_and_large_png_refused(tmp_path):
    import io
    from PIL import Image
    image=Image.new('RGB',(10,20),'blue'); buf=io.BytesIO(); image.save(buf,format='JPEG')
    vault,doc=source(tmp_path,buf.getvalue())
    assert preview_document(vault,{'document_id':doc,'page':1})['source_kind']=='image'
    from viva.source_preview_worker import render, Refusal
    buf=io.BytesIO(); image.save(buf,format='PNG',save_all=True,append_images=[Image.new('RGB',(10,20),'red')],duration=100,loop=0)
    with pytest.raises(Refusal) as refusal:
        render(buf.getvalue(),1)
    assert refusal.value.reason=='unsupported_type'
    buf=io.BytesIO(); Image.new('RGB',(2001,1),'blue').save(buf,format='PNG')
    with pytest.raises(Refusal) as refusal:
        render(buf.getvalue(),1)
    assert refusal.value.reason=='over_limit'


@pytest.mark.parametrize('format_name', ['PNG', 'JPEG'])
def test_normalized_pixels_remove_icc_and_exif_metadata(tmp_path, format_name):
    import io, base64
    from PIL import Image
    image=Image.new('RGB',(64,32),'green')
    exif=Image.Exif(); exif[270]='SYNTHETIC PRIVATE DESCRIPTION'
    original=io.BytesIO()
    image.save(original,format=format_name,icc_profile=b'SYNTHETIC PRIVATE ICC PROFILE',exif=exif)
    vault,doc=source(tmp_path,original.getvalue())
    result=preview_document(vault,{'document_id':doc,'page':1})
    assert result['status']=='ready'
    png=base64.b64decode(result['png_base64'])
    with Image.open(io.BytesIO(png)) as decoded:
        assert not decoded.info
        assert not decoded.getexif()
        assert decoded.getpixel((30,15))[1] > 100
    assert b'SYNTHETIC PRIVATE' not in png


def test_windows_refuses_before_filesystem_or_pipe_access(tmp_path,monkeypatch):
    import viva.source_preview as preview
    vault,doc=source(tmp_path)
    def forbidden(*args,**kwargs):
        raise AssertionError('unsupported platform touched backend')
    monkeypatch.setattr(vault.raw,'get_bounded',forbidden)
    monkeypatch.setattr(preview,'run_worker',forbidden)
    with monkeypatch.context() as scope:
        scope.setattr(preview.sys,'platform','win32')
        result=preview_document(vault,{'document_id':doc,'page':1})
    assert result['reason']=='renderer_unavailable'


def test_current_index_authorizes_without_event_replay(tmp_path,monkeypatch):
    from viva.vault import Vault
    from viva.ledger.events import Event
    vault=Vault.open(tmp_path/'vault','test source phrase',create=True)
    try:
        doc=vault.raw.put(b'INDEXED ORIGINAL SOURCE')
        vault.ledger.append(Event(event_type='DocumentCaptured',occurred_at='2026-10-24',body={'doc_id':doc,'filename':'source.txt'}))
        vault.synchronize_read_store()
        def forbidden(*args,**kwargs):
            raise AssertionError('full history replay')
        monkeypatch.setattr(vault.ledger,'events',forbidden)
        monkeypatch.setattr(vault.ledger.store,'snapshot_events',forbidden)
        canonical=[vault.directory/'events.jsonl', vault.raw.dir/f'{doc}.blob']
        before={str(path):path.read_bytes() for path in canonical}
        result=preview_document(vault,{'document_id':doc,'page':1})
        assert result.get('text')=='INDEXED ORIGINAL SOURCE', result
        assert before=={str(path):path.read_bytes() for path in canonical}
    finally:
        vault.close()


@pytest.mark.parametrize('change_during_worker',[False,True])
def test_genuine_stale_or_changed_source_refused(tmp_path,monkeypatch,change_during_worker):
    from viva.vault import Vault
    from viva.ledger.events import Event
    import viva.source_preview as preview
    vault=Vault.open(tmp_path/'vault','test source phrase',create=True)
    try:
        doc=vault.raw.put(b'CURRENT ORIGINAL SOURCE')
        vault.ledger.append(Event(event_type='DocumentCaptured',occurred_at='2026-10-24',body={'doc_id':doc,'filename':'source.txt'}))
        vault.synchronize_read_store()
        def change():
            vault.read_store_lifecycle='rebuilding'
            vault.ledger.store.append(Event(event_type='SyntheticSourceChange',occurred_at='2026-10-24',body={}))
        original_worker=preview.run_worker
        if change_during_worker:
            def changed_worker(data,page):
                result=original_worker(data,page)
                change()
                return result
            monkeypatch.setattr(preview,'run_worker',changed_worker)
        else:
            change()
            monkeypatch.setattr(preview,'run_worker',lambda *_:pytest.fail('stale source reached parser'))
        result=preview_document(vault,{'document_id':doc,'page':1})
        assert result['reason']=='identity_unverifiable'
    finally:
        vault.close()


@pytest.mark.parametrize('filename,count',[('x'*4097,1),('source.txt',33)])
def test_indexed_capture_lookup_bounds_scalars_and_duplicate_history(filename,count):
    import sqlite3
    from viva.read_store.documents import preview_capture_identity
    from viva.read_store import ReadStoreError
    connection=sqlite3.connect(':memory:')
    try:
        connection.execute('CREATE TABLE documents(doc_id TEXT,filename TEXT,doc_type TEXT)')
        connection.execute('CREATE INDEX documents_by_doc ON documents(doc_id)')
        connection.executemany('INSERT INTO documents VALUES(?,?,?)',[('a'*64,filename,'text')]*count)
        calls=[]; connection.set_trace_callback(calls.append)
        with pytest.raises(ReadStoreError):
            preview_capture_identity(SimpleNamespace(connection=connection),'a'*64)
        assert len(calls)==1
        assert 'INDEXED BY documents_by_doc' in calls[0] and 'LIMIT 33' in calls[0]
    finally:
        connection.close()


def test_one_revision_held_through_worker_then_closed(tmp_path,monkeypatch):
    import viva.source_preview as preview
    vault,doc=source(tmp_path)
    revision=vault.read_store.open_reader()
    state={'opens':0,'closed':False}
    def opened():
        state['opens']+=1
        return revision
    revision.close=lambda:state.update(closed=True)
    vault.read_store.open_reader=opened
    actual_worker=preview.run_worker
    def checked_worker(data,page):
        assert state['opens']==1 and not state['closed']
        return actual_worker(data,page)
    monkeypatch.setattr(preview,'run_worker',checked_worker)
    assert preview_document(vault,{'document_id':doc,'page':1})['status']=='ready'
    assert state=={'opens':1,'closed':True}
