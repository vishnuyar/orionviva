from dataclasses import replace
import json
import pytest
from viva.normalization_context import ExtractionNormalizationContext as Context
from viva.ledger.events import document_captured,read_recorded,Event,Provenance
from viva.ingest.pipeline import (_capture_authenticated_replay,_retain_authenticated_replay,
    _validate_retained_replay,ReadResult)
from viva.rebuild import claims_by_doc
from test_instrument_projector_b import setup


def captured(raw,ledger,data):
    doc=raw.put(data)
    ledger.append(document_captured(doc,'synthetic.pdf',len(data),'mortgage_statement',1.0,'2021-01-31'))
    return doc


def receipt(doc,text,ok=True,**kwargs):
    return read_recorded(doc,'configured','p','text+image',text,.0123,9,0,ok,
        None if ok else 'actual failed parse','2021-01-31',resolved_model='resolved',
        usage_reported=True,normalization_context=Context(1,'nv1','en_US','EUR'),**kwargs)


@pytest.mark.parametrize('statuses',[(True,False),(False,True)])
def test_authenticated_original_attempts_order_ids_once_and_latest_failed_selection(tmp_path,statuses):
    raw,ledger=setup(tmp_path/'source')
    first=captured(raw,ledger,b'first synthetic source');second=captured(raw,ledger,b'second synthetic source')
    originals=[receipt(first,'first-1',statuses[0]),receipt(second,'second-1'),receipt(first,'first-2',statuses[1])]
    for event in originals:ledger.append(event)
    capture=_capture_authenticated_replay(ledger,raw)
    assert claims_by_doc(capture.events())[first]['extract']['parse_ok']==statuses[1]
    destination_raw,destination=setup(tmp_path/'destination')
    permits=_retain_authenticated_replay(capture,destination_raw,destination)
    _retain_authenticated_replay(capture,destination_raw,destination)
    actual=[e.to_dict() for e in destination.events()]
    assert actual==[e.to_dict() for e in originals]
    assert sum(e['body']['cost_usd'] for e in actual)==sum(e.body['cost_usd'] for e in originals)
    assert destination_raw.get(first)==raw.get(first)
    _validate_retained_replay(permits[first],destination,b'first synthetic source',ReadResult('unknown',0,None,raw_text='first-2'))
    with pytest.raises(ValueError):
        _validate_retained_replay(permits[first],destination,b'first synthetic source',ReadResult('unknown',0,None,raw_text='first-1'))
    assert not any(e['event_type']=='TransactionRecorded' for e in actual)


def test_exact_duplicate_receipt_identity_retained_once_but_conflict_refuses(tmp_path):
    raw,ledger=setup(tmp_path/'source');doc=captured(raw,ledger,b'synthetic source')
    original=receipt(doc,'raw');ledger.append(original);ledger.append(original)
    cap=_capture_authenticated_replay(ledger,raw)
    dest_raw,dest=setup(tmp_path/'dest');_retain_authenticated_replay(cap,dest_raw,dest)
    assert [e.to_dict() for e in dest.events()]==[original.to_dict()]
    changed=Event.from_dict(original.to_dict());changed.body['response_text']='different original body'
    ledger.append(changed)
    with pytest.raises(ValueError,match='identity is ambiguous'):_capture_authenticated_replay(ledger,raw)


def test_foreign_source_provenance_and_destination_collision_refuse(tmp_path):
    raw,ledger=setup(tmp_path/'source');doc=captured(raw,ledger,b'synthetic source')
    original=receipt(doc,'raw');ledger.append(original)
    cap=_capture_authenticated_replay(ledger,raw)
    dest_raw,dest=setup(tmp_path/'dest')
    collision=Event.from_dict(original.to_dict());collision.body['cost_usd']=999
    dest.append(collision);before=[e.to_dict() for e in dest.events()]
    with pytest.raises(ValueError,match='identity collision'):_retain_authenticated_replay(cap,dest_raw,dest)
    assert [e.to_dict() for e in dest.events()]==before
    foreign=receipt(doc,'foreign',provenance=Provenance(doc_id='foreign-document'));ledger.append(foreign)
    with pytest.raises(ValueError,match='another document'):_capture_authenticated_replay(ledger,raw)


def test_mutated_context_keeps_raw_original_audit_but_reparse_cannot_fallback(monkeypatch):
    from viva import rebuild
    calls=[];monkeypatch.setattr(rebuild,'_parse',lambda *args:calls.append(args))
    body={'response_text':'raw','normalization_context':{'schema_version':1,'normalization_rules_version':'unknown',
        'parser_locale':'en_US','parser_currency':'EUR'}}
    facts,error,context=rebuild._parse_claim('mortgage_statement',body,'doc','HOST','USD')
    assert facts is None and error and calls==[]
    del body['normalization_context']
    monkeypatch.setattr(rebuild,'_parse',lambda *args:(calls.append(args) or (None,'legacy error')))
    assert rebuild._parse_claim('mortgage_statement',body,'doc','HOST','USD')==(None,'legacy error',None)
    assert calls==[('mortgage_statement','raw','doc','HOST','USD')]


def test_client_records_cannot_issue_replay_capability_or_write_destination(tmp_path):
    raw,ledger=setup(tmp_path/'destination')
    with pytest.raises(ValueError,match='capability required'):
        _retain_authenticated_replay({'events':[receipt('doc','provider-invented').to_dict()]},raw,ledger)
    assert tuple(ledger.events())==() and tuple(raw.doc_ids())==()


def test_captured_source_prefix_does_not_follow_later_mutable_attempts(tmp_path):
    raw,ledger=setup(tmp_path/'source');doc=captured(raw,ledger,b'synthetic source')
    first=receipt(doc,'original selected');ledger.append(first)
    capture=_capture_authenticated_replay(ledger,raw)
    ledger.append(receipt(doc,'later failed',False))
    dest_raw,dest=setup(tmp_path/'destination')
    permits=_retain_authenticated_replay(capture,dest_raw,dest)
    assert [event.to_dict() for event in dest.events()]==[first.to_dict()]
    _validate_retained_replay(permits[doc],dest,b'synthetic source',ReadResult('unknown',0,None,raw_text='original selected'))
    # A later destination attempt invalidates the selected authenticated receipt.
    dest.append(receipt(doc,'current destination correction',False))
    with pytest.raises(ValueError,match='selected retained extraction changed'):
        _validate_retained_replay(permits[doc],dest,b'synthetic source',ReadResult('unknown',0,None,raw_text='original selected'))
