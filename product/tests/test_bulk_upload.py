"""Synthetic concurrency controls; no provider, campaign or installed-host claim."""
import importlib.util
import json
from pathlib import Path
from threading import Barrier,Event,Lock,Thread,get_ident
from types import SimpleNamespace
import pytest
from viva.ingest import reader
from viva.desktop_bridge.bulk_documents import BulkDocuments,_paths
from viva.desktop_bridge.jobs import JobRegistry
from viva.vault import Vault
from vivacore.models.base import ModelResult,PageImage
from vivacore.models.spec import ModelSpec
from test_reader_two_phase import _EXTRACT_JSON


def response(text,cost=.02):
    return ModelResult(text,'resolved',7,11,cost,0,{}, {'usage':{'prompt_tokens':7,'completion_tokens':11}})


def spec():
    return ModelSpec('fake','openai-compatible','configured','https://example.invalid',api_key_env=None)


@pytest.fixture
def setup_bulk(tmp_path,monkeypatch):
    vault=Vault.open(tmp_path/'vault','synthetic-only')
    paths=[]
    for index in range(3):
        p=tmp_path/f'document-{index}.pdf';p.write_bytes(f'SYNTHETIC-{index}'.encode());paths.append(str(p))
    parent=get_ident();renders=[];adapters=[]
    def prepare(data,checkpoint=None):
        assert get_ident()==parent
        if checkpoint:checkpoint()
        renders.append(data)
        return (PageImage(1,b'png',data.decode()),),data.decode()
    def build():
        def unused(*args):raise AssertionError('bulk reran ordinary reading')
        unused.prepare=prepare
        unused.read_prepared=lambda pages,text,doc_id,**kwargs:reader.read_prepared_statement(pages,text,doc_id,spec(),'en-US','USD',**kwargs)
        return unused,True
    monkeypatch.setattr(reader,'build_reader',build)
    def configure(barrier=None,gate=None,fail_extract=False):
        class Adapter:
            def __init__(self):self.calls=0;adapters.append(self)
            def extract(self,pages,prompt):
                assert get_ident()!=parent
                self.calls+=1
                if self.calls==1:
                    if barrier:barrier.wait(timeout=3)
                    if gate:gate.wait(timeout=3)
                    return response('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}')
                if fail_extract:raise RuntimeError('synthetic transport failure')
                packet=json.loads(_EXTRACT_JSON);packet['account_ref']=pages[0].sha256
                packet['account_number']=pages[0].sha256;packet['institution']=pages[0].sha256
                return response(json.dumps(packet))
        monkeypatch.setattr(reader,'adapter_for',lambda _spec:Adapter())
    configure()
    yield SimpleNamespace(vault=vault,paths=paths,renders=renders,adapters=adapters,configure=configure)
    vault.close()


@pytest.mark.parametrize('payload',[{}, {'paths':[]},{'paths':['a']*4},{'paths':'a'}, {'paths':[True]}, {'paths':['']}, {'paths':['x'*4097]},{'paths':['a'],'workers':3}])
def test_chunk_request_is_closed_and_bounded(payload):
    with pytest.raises(ValueError):_paths(payload)


def test_classify_response_survives_later_extraction_exception(monkeypatch):
    class Adapter:
        calls=0
        def extract(self,*args):
            self.calls+=1
            if self.calls==1:return response('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}')
            raise RuntimeError('after completed classification')
    monkeypatch.setattr(reader,'adapter_for',lambda _spec:Adapter())
    result=reader.read_prepared_statement((PageImage(1,b'img','sha'),),'text','doc',spec(),'en-US','USD')
    assert result.facts is None and result.error
    assert len(result.phases)==1 and result.phases[0].phase=='classify'
    assert result.phases[0].raw_text=='{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'
    assert result.phases[0].cost_usd==.02 and result.phases[0].usage_reported


def test_later_retry_failure_keeps_original_attempt_without_fallback():
    count=0
    def extract(prompt):
        nonlocal count
        count+=1
        if count==1:return response('not valid json')
        raise RuntimeError('second transport failed')
    observed=[]
    result=reader.read_with_retry(extract,'fixture','doc','en-US','USD',phase_sink=observed.append)
    assert count==2 and result.facts is None and result.error
    assert len(result.phases)==len(observed)==1
    assert result.phases[0].raw_text=='not valid json'
    assert result.phases[0].cost_usd==.02 and result.phases[0].parse_ok is False


def test_three_models_overlap_all_phase_acks_precede_any_post(setup_bulk,monkeypatch):
    sample=setup_bulk;sample.configure(barrier=Barrier(3))
    real=sample.vault.ledger.append;posted=[]
    def append(event):
        if event.event_type=='TransactionRecorded':
            receipts=[e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded']
            assert len(receipts)==6
            assert all(adapter.calls==2 for adapter in sample.adapters)
            posted.append(event)
        return real(event)
    monkeypatch.setattr(sample.vault.ledger,'append',append)
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths})
    assert [row['ordinal'] for row in result['rows']]==[0,1,2]
    assert all(row['action']=='posted' for row in result['rows']),result
    assert posted and len(sample.renders)==3
    receipts=[e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded']
    assert len(receipts)==6 and len({e.event_id for e in receipts})==6
    assert sum(e.body['cost_usd'] for e in receipts)==pytest.approx(.12)
    assert all(e.body.get('normalization_context') for e in receipts if e.body['phase']=='extract')


def test_identical_bytes_pay_once_in_chunk_and_later_chunks(setup_bulk):
    sample=setup_bulk
    path=sample.paths[0]
    first=BulkDocuments(sample.vault,JobRegistry()).run({'paths':[path,path,path]})
    assert [row['action'] for row in first['rows']]==['posted','duplicate','duplicate']
    second=BulkDocuments(sample.vault,JobRegistry()).run({'paths':[path]})
    assert second['rows'][0]['action']=='duplicate'
    assert len(sample.adapters)==1 and sample.adapters[0].calls==2
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==2


def test_classified_transport_failure_is_retained_without_posting(setup_bulk):
    sample=setup_bulk;sample.configure(fail_extract=True)
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    assert result['rows'][0]['reason']=='read_failed'
    assert result['rows'][0]['disposition']!='never_read'
    receipts=[e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded']
    assert len(receipts)==1 and receipts[0].body['phase']=='classify'
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_settlement_error_after_actual_write_is_uncertain_and_stops_other_settlement(setup_bulk,monkeypatch):
    import viva.engine as engine
    sample=setup_bulk;real=engine.upload;calls=[]
    def fail_after_write(*args,**kwargs):
        result=real(*args,**kwargs);calls.append(result)
        raise RuntimeError('failure after source posting')
    monkeypatch.setattr(engine,'upload',fail_after_write)
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths})
    assert len(calls)==1 and calls[0]['action']=='posted'
    assert all(row['reason']=='outcome_unknown' and row['disposition'] is None for row in result['rows'])
    assert len(sample.vault.ledger.projection().posted_doc_ids())==1
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==6


def test_no_model_keeps_originals_and_records_no_network_receipts(setup_bulk,monkeypatch):
    sample=setup_bulk
    monkeypatch.setattr(reader,'build_reader',lambda:(reader.parking_reader(),False))
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths})
    assert all(row['action']=='parked' and row['reason']=='no_model' for row in result['rows'])
    assert not sample.adapters and not sample.renders
    assert len(sample.vault.ledger.projection().captured_docs())==3
    assert not [e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded']


def test_copy_context_preserves_parent_observer_binding(setup_bulk,monkeypatch):
    from contextvars import ContextVar
    sample=setup_bulk;binding=ContextVar('synthetic_binding',default='missing')
    original=reader.adapter_for;seen=[]
    def adapter(candidate):seen.append(binding.get());return original(candidate)
    monkeypatch.setattr(reader,'adapter_for',adapter)
    token=binding.set('same-authorized-context')
    try:BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths})
    finally:binding.reset(token)
    assert seen==['same-authorized-context']*3

def test_cancel_drains_paid_classify_receipts_before_terminal_and_starts_no_extract(setup_bulk):
    sample=setup_bulk;gate=Event();sample.configure(barrier=Barrier(3),gate=gate)
    jobs=None;requested=False
    def pump():
        nonlocal requested
        if not requested and len(sample.adapters)==3 and all(a.calls==1 for a in sample.adapters):
            requested=True
            job=jobs.records()[0] if hasattr(jobs,'records') else jobs.record(operation.job_id)
            jobs.cancel(operation.job_id)
            assert jobs.record(operation.job_id).state.value=='running'
            gate.set()
    jobs=JobRegistry(pump=pump);operation=BulkDocuments(sample.vault,jobs)
    result=operation.run({'paths':sample.paths})
    assert requested and jobs.record(result['job_id']).state.value=='cancelled'
    assert all(adapter.calls==1 for adapter in sample.adapters)
    receipts=[e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded']
    assert len(receipts)==3 and all(e.body['phase']=='classify' for e in receipts)
    assert not sample.vault.ledger.projection().posted_doc_ids()
    assert all(row['document_id'] and row['reason']=='job_cancelled' for row in result['rows'])


def test_sorted_unique_content_locks_and_originals_saved_before_model(setup_bulk,monkeypatch):
    from contextlib import contextmanager
    sample=setup_bulk;real=sample.vault.raw.document_lock;acquired=[];active=[]
    @contextmanager
    def lock(document):
        acquired.append(document)
        with real(document):
            active.append(document)
            try:yield
            finally:active.remove(document)
    monkeypatch.setattr(sample.vault.raw,'document_lock',lock)
    sample.configure(barrier=Barrier(3))
    original=reader.adapter_for
    def factory(candidate):
        assert len(active)==3
        assert all(sample.vault.raw.get(document) for document in active)
        return original(candidate)
    monkeypatch.setattr(reader,'adapter_for',factory)
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':list(reversed(sample.paths))})
    assert len(acquired)==3 and acquired==sorted(acquired)
    assert not active and all(row['action']=='posted' for row in result['rows'])


def test_phase_is_durable_before_next_model_request(setup_bulk,monkeypatch):
    import hashlib
    sample=setup_bulk;original=reader.adapter_for
    class Guard:
        def __init__(self,inner):self.inner=inner
        def extract(self,pages,prompt):
            if self.inner.calls:
                document=hashlib.sha256(pages[0].sha256.encode()).hexdigest()
                assert any(e.event_type=='ReadRecorded' and e.body['doc_id']==document
                    and e.body['phase']=='classify' for e in sample.vault.ledger.events())
            return self.inner.extract(pages,prompt)
    monkeypatch.setattr(reader,'adapter_for',lambda candidate:Guard(original(candidate)))
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths})
    assert all(row['action']=='posted' for row in result['rows'])


def test_read_statement_wrapper_preserves_phase_on_later_request_failure(monkeypatch):
    monkeypatch.setattr(reader,'_render_and_read_text',lambda data:((PageImage(1,b'png','s'),),'text'))
    class Adapter:
        count=0
        def extract(self,*args):
            self.count+=1
            if self.count==1:return response('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}')
            raise RuntimeError('synthetic later failure')
    monkeypatch.setattr(reader,'adapter_for',lambda candidate:Adapter())
    result=reader.read_statement(b'original','doc',spec(),'en-US','USD')
    assert result.facts is None and len(result.phases)==1 and result.phases[0].phase=='classify'


def test_eof_pump_stops_active_bulk_without_closing_vault(monkeypatch):
    import io,os
    from viva.desktop_bridge.__main__ import Sidecar
    read_fd,write_fd=os.pipe();os.close(write_fd)
    source=os.fdopen(read_fd)
    stopped=[]
    class Owner:
        def upload_many(self,payload):pass
        def stop_bulk(self):stopped.append(True)
    owner=Owner();sidecar=Sidecar(io.StringIO(),source)
    sidecar._dispatcher=SimpleNamespace(handlers={'viva.documents.upload_many':owner.upload_many})
    sentinel=object();sidecar._vault=sentinel
    try:sidecar.pump()
    finally:source.close()
    assert stopped==[True] and sidecar._vault is sentinel


def test_private_receipt_owner_refuses_tampered_and_expired_phase(setup_bulk):
    from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_phase,_validate_bulk_read,_check_bulk_owner,ModelPhase,ReadResult
    sample=setup_bulk;data=b'new-source'
    owner=_begin_bulk_read(sample.vault.raw,sample.vault.ledger,data,'test.pdf','2026-01-01')
    phase=ModelPhase('classify','configured','classify-fixture','{"doc_type":"unknown"}')
    try:
        _retain_bulk_phase(owner,phase,'unknown',0.0)
        result=ReadResult('unknown',0.0,None,phases=[phase])
        _validate_bulk_read(owner,result)
        phase.raw_text='changed'
        with pytest.raises(ValueError):_validate_bulk_read(owner,result)
        with pytest.raises(ValueError):_check_bulk_owner(owner,sample.vault.raw,object(),data)
    finally:owner.close()
    with pytest.raises(ValueError):_check_bulk_owner(owner,sample.vault.raw,sample.vault.ledger,data)

def test_absent_usage_and_measured_zero_remain_distinct(setup_bulk,monkeypatch):
    sample=setup_bulk
    class Adapter:
        def extract(self,pages,prompt):
            measured=pages[0].sha256.endswith('1')
            usage={'usage':{'prompt_tokens':0,'completion_tokens':0}} if measured else {}
            return ModelResult('{"doc_type":"unknown"}','resolved',0,0,0.0,0,{},usage)
    monkeypatch.setattr(reader,'adapter_for',lambda candidate:Adapter())
    result=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:2]})
    receipts=[event.body for event in sample.vault.ledger.events() if event.event_type=='ReadRecorded']
    assert len(receipts)==2 and all(body['cost_usd']==0 for body in receipts)
    assert sum(body.get('usage_reported') is True for body in receipts)==1
    missing=next(body for body in receipts if 'usage_reported' not in body)
    assert 'input_tokens' not in missing and 'output_tokens' not in missing
    zero=next(body for body in receipts if body.get('usage_reported'))
    assert zero['input_tokens']==zero['output_tokens']==0


def test_duplicate_receipt_identity_cannot_be_replayed_as_owned(setup_bulk):
    from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_phase,_validate_bulk_read,ModelPhase,ReadResult
    from viva.ledger.events import Event
    sample=setup_bulk;owner=_begin_bulk_read(sample.vault.raw,sample.vault.ledger,b'duplicate-receipt','fixture.pdf','2026-01-01')
    phase=ModelPhase('classify','configured','fixture','{"doc_type":"unknown"}')
    try:
        _retain_bulk_phase(owner,phase,'unknown',0.0)
        sample.vault.ledger.append(Event.from_dict(owner.records[0]))
        with pytest.raises(ValueError):_validate_bulk_read(owner,ReadResult('unknown',0,None,phases=[phase]))
    finally:owner.close()


def test_actual_pdf_capture_render_parser_post_and_receipts(tmp_path,monkeypatch):
    from io import BytesIO
    from reportlab.pdfgen.canvas import Canvas
    from hashlib import sha256
    packet=json.loads(_EXTRACT_JSON)
    stream=BytesIO();pdf=Canvas(stream,invariant=1);y=770
    pdf.drawString(24,y,'SYNTHETIC TEST SOURCE');y-=16
    for line in json.dumps(packet,indent=2).splitlines():
        pdf.drawString(24,y,line);y-=12
    pdf.showPage();pdf.save();data=stream.getvalue()
    original=tmp_path/'synthetic.pdf';original.write_bytes(data)
    vault=Vault.open(tmp_path/'actual-pdf-vault','synthetic-only')
    parent=get_ident();calls=[]
    class Adapter:
        def extract(self,pages,prompt):
            assert get_ident()!=parent and len(pages)==1
            assert pages[0].png_bytes.startswith(b'\x89PNG')
            calls.append(prompt)
            return response('{"doc_type":"credit_card_statement","doc_type_confidence":0.97}' if len(calls)==1 else json.dumps(packet))
    monkeypatch.setattr(reader,'adapter_for',lambda candidate:Adapter())
    def build():
        def unused(*args):raise AssertionError('no second model reading')
        unused.prepare=reader.prepare_statement
        unused.read_prepared=lambda pages,text,doc,**kwargs:reader.read_prepared_statement(tuple(pages),text,doc,spec(),'en-US','USD',**kwargs)
        return unused,True
    monkeypatch.setattr(reader,'build_reader',build)
    try:
        result=BulkDocuments(vault,JobRegistry()).run({'paths':[str(original)]})
        document=sha256(data).hexdigest()
        assert result['rows'][0]['action']=='posted'
        assert vault.raw.get(document)==data and vault.ledger.projection().posted_doc_ids()=={document}
        receipts=[e for e in vault.ledger.events() if e.event_type=='ReadRecorded']
        assert len(calls)==len(receipts)==2
        assert receipts[1].body['response_text']==json.dumps(packet)
        assert receipts[1].body['normalization_context']['parser_locale']=='en-US'
    finally:vault.close()


def test_raw_owner_failure_still_drains_completed_phases(setup_bulk):
    sample=setup_bulk;gate=Event();sample.configure(barrier=Barrier(3),gate=gate)
    failed=False
    def pump():
        nonlocal failed
        if len(sample.adapters)==3 and all(a.calls==1 for a in sample.adapters):
            gate.set()
            if not failed:
                failed=True
                raise RuntimeError('synthetic coordinator pump failure')
    result=BulkDocuments(sample.vault,JobRegistry(pump=pump)).run({'paths':sample.paths})
    assert failed and all(row['reason']=='outcome_unknown' for row in result['rows'])
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==3
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_completed_classification_survives_classification_parser_exception(monkeypatch):
    raw='{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'
    class Adapter:
        def extract(self,*args):return response(raw)
    monkeypatch.setattr(reader,'adapter_for',lambda _spec:Adapter())
    def broken(_text):raise RuntimeError('classification interpretation failed')
    monkeypatch.setattr(reader,'_peek_classification',broken)
    phases=[]
    result=reader.read_prepared_statement((PageImage(1,b'img','sha'),),'text','doc',spec(),'en-US','USD',phase_sink=lambda phase,*_:phases.append(phase))
    assert result.facts is None
    assert len(result.phases)==len(phases)==1
    assert result.phases[0].raw_text==raw and result.phases[0].cost_usd==.02
    assert result.phases[0].parse_ok is False
