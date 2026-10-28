"""Real retention callback order keeps classified routing metadata after raw capture."""
import hashlib,json
from contextlib import nullcontext
from types import SimpleNamespace
import pytest
from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_response,_retain_bulk_phase
from viva.ingest.pipeline_models import ModelPhase
from viva.extraction_responses import response_body
from viva.ledger import LedgerProjection

class Raw:
    def fingerprint(self,data):return hashlib.sha256(data).hexdigest()
    def put(self,data):return self.fingerprint(data)
    def document_lock(self,doc):return nullcontext()

class Ledger:
    def __init__(self):self.rows=[]
    def append(self,event):self.rows.append(event)
    def events(self):return tuple(self.rows)


@pytest.mark.parametrize('family',['credit_card_statement','pay_stub','brokerage_statement','mortgage_statement','utility_bill'])
def test_actual_response_then_phase_callbacks_recover_classification(family):
    ledger=Ledger();owner=_begin_bulk_read(Raw(),ledger,b'public pdf','public.pdf','2026-01-01')
    text=json.dumps({'doc_type':family,'doc_type_confidence':.97})
    body=response_body(owner.document,'public-extraction','classify',0,0,
        'openai_compatible','public-model','public-prompt','text+image',200,b'{}')
    identity=_retain_bulk_response(owner,body)
    phase=ModelPhase('classify','public-model','public-prompt',text,
        transport_receipt_ids=[identity],transport_complete=True,
        extraction_id='public-extraction',phase_attempt=0)
    _retain_bulk_phase(owner,phase,family,.97)
    assert ledger.rows[0].body['doc_type']=='unknown'
    assert LedgerProjection(ledger.events()).captured_docs()=={owner.document:family}
    assert LedgerProjection(ledger.events()).read_parsed_docs()==set()
    owner.close()


@pytest.mark.parametrize('transport',[True,False])
def test_real_reader_phase_sink_only_retains_supported_empty_or_unscoped_metadata(monkeypatch,transport):
    from viva.ingest import reader
    from vivacore.models.base import PageImage,ModelResult,retain_extraction_response
    ledger=Ledger();owner=_begin_bulk_read(Raw(),ledger,b'phase-only pdf','public.pdf','2026-01-01')
    class Adapter:
        def extract(self,images,prompt):
            if transport:
                retain_extraction_response('openai_compatible','public-model',0,
                    SimpleNamespace(status_code=200,content=b'{}'))
            return ModelResult('{"doc_type":"utility_bill","doc_type_confidence":0.9}',
                               'public-model',0,0,0,0,{}, {})
    monkeypatch.setattr(reader,'adapter_for',lambda spec:Adapter())
    result=reader.read_prepared_statement((PageImage(1,b'public','hash'),),'public',
        owner.document,SimpleNamespace(model='public-model'),'en-US','USD',
        phase_sink=lambda phase,kind,confidence:_retain_bulk_phase(owner,phase,kind,confidence))
    assert result.facts is None and result.error.startswith('no projector')
    event=ledger.rows[-1]
    assert ('transport_complete' in event.body) is transport
    if transport:assert event.body['transport_complete'] is True and event.body['transport_receipt_ids']==[]
    assert LedgerProjection(ledger.events()).captured_docs()=={owner.document:'utility_bill'}
    owner.close()
