from pathlib import Path
from contextlib import closing
import hashlib,json
import pytest
from viva.sample import curation
from viva.ingest.pipeline import capture_and_ingest,_capture_authenticated_replay
from viva.ingest.pipeline_models import ReadResult
from viva.ledger.events import Event
from viva.vault import Vault


SOURCE=Path(__file__).parents[1]/'normalization_inputs/local-source'


def original(document_id):
    raw=(SOURCE/'readings.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab'
    row=next(row for row in json.loads(raw)['readings'] if row['document_id']==document_id)
    meta=next(row for row in json.loads((SOURCE/'manifest.json').read_bytes())['documents'] if row['id']==document_id)
    data=(SOURCE/meta['file']).read_bytes();assert hashlib.sha256(data).hexdigest()==row['document_sha256']
    text=curation.canonical(row['envelope']).decode()
    acquisition={'kind':'local-curation-v1','sample_version':'five-year-life-v1',
        'corpus_manifest_sha256':'97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800',
        'readings_sha256':hashlib.sha256(raw).hexdigest(),'reading_contract':curation.CONTRACT,
        'document_sha256':row['document_sha256'],'reading_sha256':hashlib.sha256(text.encode()).hexdigest()}
    return data,{'doc_id':row['document_sha256'],'doc_type':row['doc_type'],'response_text':text,
        'parse_ok':True,'parse_error':None,'phase':'extract','acquisition':acquisition,
        'normalization_locale':row['locale'],'source_currency':row['currency']}


def test_actual_local_v2_full_decoder_source_pdf_rebuild_no_model_metadata(tmp_path,monkeypatch):
    from viva import rebuild
    source=tmp_path/'source';destination=tmp_path/'destination'
    with closing(Vault.open(source,'synthetic-passphrase')) as vault:
        for document in ['D0013','D0012']:
            data,body=original(document)
            capture_and_ingest(vault.raw,vault.ledger,data,curation.RetainedCuratedReader(body))
        receipts=[event.to_dict() for event in vault.ledger.events() if event.event_type=='ReadRecorded']
        assert len(receipts)==2 and len(vault.ledger.projection().instrument_allocations())==1
        cash=[event.body for event in vault.ledger.events() if event.event_type=='TransactionRecorded']
    calls=[];closed=[];envelopes=[];parse=rebuild._parse;decode=curation.decode_retained_input;envelope=curation.decode_envelope
    def tracked(*args):calls.append(args);return parse(*args)
    def closed_shape(body):closed.append(body['doc_id']);return decode(body)
    def envelope_shape(*args):envelopes.append(args[1]);return envelope(*args)
    monkeypatch.setattr(rebuild,'_parse',tracked)
    monkeypatch.setattr(curation,'decode_retained_input',closed_shape)
    monkeypatch.setattr(curation,'decode_envelope',envelope_shape)
    rebuild.rebuild(source,destination,'synthetic-passphrase',locale='de-DE',currency='EUR',log=lambda *args:None)
    assert len(calls)==4 and all(args[-2:]==('en-US','USD') for args in calls)
    # These validations deliberately remain repeated in the unchanged existing
    # local reader. They are shape checks, separately counted from interpretation.
    assert len(closed)>=8 and len(envelopes)>len(closed)
    print('LOCAL_VALIDATION_COUNTS',json.dumps({'financial_rebuild_parse_operations':len(calls),
        'closed_retained_input_validations':len(closed),'closed_envelope_validations':len(envelopes)}))
    with closing(Vault.open(destination,'synthetic-passphrase')) as vault:
        actual=[event.to_dict() for event in vault.ledger.events() if event.event_type=='ReadRecorded']
        assert actual==receipts
        assert all(not set(event['body'])&{'normalization_context','model','cost_usd','input_tokens','output_tokens'} for event in actual)
        assert len(vault.ledger.projection().instrument_allocations())==1
        assert [event.body for event in vault.ledger.events() if event.event_type=='TransactionRecorded']==cash
        from viva.read_store.overview import SQLOverviewProjection
        vault.read_store.synchronize(vault.ledger.store)
        with vault.read_store.open_reader() as revision:
            assert SQLOverviewProjection(revision,'2021-01-31').instrument_allocations()==vault.ledger.projection().instrument_allocations()


def test_malformed_local_envelope_can_remain_audit_but_never_trusted_partial_finance(tmp_path):
    data,body=original('D0012')
    envelope=json.loads(body['response_text']);envelope['extra_untrusted_field']='not part of closed contract'
    text=curation.canonical(envelope).decode();body['response_text']=text
    body['acquisition']={**body['acquisition'],'reading_sha256':hashlib.sha256(text.encode()).hexdigest()}
    def failed_local(blob,doc):
        try:curation.RetainedCuratedReader(body)(blob,doc)
        except ValueError as error:
            return ReadResult(body['doc_type'],None,None,str(error),raw_text=text,
                source_locale='en-US',acquisition=body['acquisition'])
        raise AssertionError('malformed closed local envelope accepted')
    with closing(Vault.open(tmp_path/'source','synthetic-passphrase')) as vault:
        result=capture_and_ingest(vault.raw,vault.ledger,data,failed_local)
        events=list(vault.ledger.events())
        assert result.action=='parked'
        assert [event.event_type for event in events]==['DocumentCaptured','ReadRecorded']
        assert events[-1].body['parse_ok'] is False and events[-1].body['response_text']==text
        assert not vault.ledger.projection().accounts() and not vault.ledger.projection().instrument_allocations()
        with pytest.raises(ValueError,match='envelope'):_capture_authenticated_replay(vault.ledger,vault.raw)
        assert [event.to_dict() for event in vault.ledger.events()]==[event.to_dict() for event in events]
