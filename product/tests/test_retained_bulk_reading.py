"""Public production-bound retained-reading controls; no live provider/native host."""
import copy
import hashlib
import json
from threading import Barrier, Thread
from types import SimpleNamespace
import pytest
from test_bulk_upload import setup_bulk, spec
from test_reader_two_phase import _EXTRACT_JSON
from test_extraction_responses import wire
from vivacore.models import OpenAICompatAdapter
from viva.desktop_bridge.bulk_documents import BulkDocuments, _retained
from viva.desktop_bridge.jobs import JobRegistry
from viva.desktop_bridge.documents_page import read_documents_page
from viva.ingest.pipeline import _begin_retained_bulk_read, _validate_bulk_read, _audit_bytes
from viva.ingest.pipeline_models import (ReadResult, retained_confirmation_owner,
    retained_source_identity, retained_capture_commitment)
from viva.ingest import reader
from viva.ledger.events import document_captured, Event
from viva.vault import Vault


def capture(sample, index=0, kind='unknown'):
    path=sample.paths[index];data=__import__('pathlib').Path(path).read_bytes()
    document=sample.vault.raw.put(data)
    sample.vault.ledger.append(document_captured(document,__import__('pathlib').Path(path).name,
        len(data),kind,0.97,'2026-01-01'))
    return document


def selected(sample, document, monkeypatch):
    monkeypatch.setattr(reader,'live_reading_configured',lambda:True)
    sample.vault.synchronize_read_store()
    result=read_documents_page(sample.vault,b'x'*32,
        {'contract_version':'documents-page-v1','selected_document_id':document},session_scope='a'*32)
    assert result['state']=='ready',result
    assert result['retained_reading_version']=='retained-reading-v1'
    return result['selected_document']['document']['retry']


def payload(document, token):
    return {'retained_documents':[{'document_id':document,'confirmation_token':token}], 'confirm_reading':True}


def actual_http(monkeypatch, *, failure=False, barrier=None, before=None):
    calls=[]
    def adapter(_spec):return OpenAICompatAdapter(spec())
    monkeypatch.setattr(reader,'adapter_for',adapter)
    def post(self,body,headers):
        self._test_calls=getattr(self,'_test_calls',0)+1
        phase='classify' if self._test_calls==1 else 'extract'
        calls.append((id(self),phase))
        if before:before(phase)
        if phase=='classify':
            if barrier:barrier.wait(timeout=5)
            return wire('openai-compatible','{"doc_type":"credit_card_statement","doc_type_confidence":0.97}')
        if failure:return wire('openai-compatible','not JSON')
        packet=json.loads(_EXTRACT_JSON)
        packet['account_ref']=packet['account_number']=packet['institution']='public-'+str(id(self))
        return wire('openai-compatible',json.dumps(packet))
    monkeypatch.setattr(OpenAICompatAdapter,'_post',post)
    return calls


@pytest.mark.parametrize('bad',[{}, {'document_ids':['a'*64],'confirm_reading':True},
    {'retained_documents':[],'confirm_reading':True},
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'x'}],'confirm_reading':False},
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'x','extra':1}],'confirm_reading':True},
    {'retained_documents':[{'document_id':'A'*64,'confirmation_token':'x'}],'confirm_reading':True},
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'x'*1025}],'confirm_reading':True},
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'é'}],'confirm_reading':True}])
def test_closed_request(bad):
    with pytest.raises(ValueError):_retained(bad)


def test_saved_original_posts_with_exact_old_history_and_no_capture(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);retry=selected(sample,doc,monkeypatch)
    assert retry['state']=='available'
    before=[_audit_bytes(e) for e in sample.vault.ledger.events()]
    blob=(sample.vault.raw.dir/(doc+'.blob')).read_bytes()
    calls=actual_http(monkeypatch)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,retry['confirmation_token']))
    assert result['rows'][0]['action']=='posted',result
    events=list(sample.vault.ledger.events())
    assert [_audit_bytes(e) for e in events[:len(before)]]==before
    assert len([e for e in events if e.event_type=='DocumentCaptured' and e.body['doc_id']==doc])==1
    assert (sample.vault.raw.dir/(doc+'.blob')).read_bytes()==blob
    assert len(calls)==2
    assert selected(sample,doc,monkeypatch)['state']=='blocked'


def test_two_preselected_tokens_stale_after_complete_failed_extract(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample)
    a=selected(sample,doc,monkeypatch)['confirmation_token'];b=selected(sample,doc,monkeypatch)['confirmation_token']
    calls=actual_http(monkeypatch,failure=True)
    first=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,a))
    assert first['rows'][0]['reason']=='read_failed',first
    prefix=[_audit_bytes(e) for e in sample.vault.ledger.events()];n=len(calls)
    second=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,b))
    assert second['rows'][0]['reason']=='stale_confirmation',second
    assert len(calls)==n and [_audit_bytes(e) for e in sample.vault.ledger.events()]==prefix
    fresh=selected(sample,doc,monkeypatch)
    assert fresh['state']=='available',fresh
    assert len(calls)==n
    third=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,fresh['confirmation_token']))
    assert third['rows'][0]['reason']=='read_failed' and len(calls)>n,third
    assert [_audit_bytes(e) for e in list(sample.vault.ledger.events())[:len(prefix)]]==prefix


def test_no_event_preparation_failure_consumes_gesture(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    original=reader.build_reader
    def failed_build():
        read,configured=original()
        def fail(*a,**k):raise ValueError('public preparation refusal')
        read.prepare=fail
        return read,configured
    monkeypatch.setattr(reader,'build_reader',failed_build)
    prefix=[_audit_bytes(e) for e in sample.vault.ledger.events()]
    first=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert first['rows'][0]['reason']=='read_failed',first
    assert [_audit_bytes(e) for e in sample.vault.ledger.events()]==prefix
    second=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert second['rows'][0]['reason']=='confirmation_used',second
    assert [_audit_bytes(e) for e in sample.vault.ledger.events()]==prefix


def test_three_retained_workers_admit_one_prefix_overlap_then_serial_settle(setup_bulk,monkeypatch):
    sample=setup_bulk;docs=[capture(sample,i) for i in range(3)]
    choices=[{'document_id':doc,'confirmation_token':selected(sample,doc,monkeypatch)['confirmation_token']} for doc in docs]
    calls=actual_http(monkeypatch,barrier=Barrier(3))
    real=sample.vault.ledger.append;settlements=[]
    def append(event):
        if event.event_type=='TransactionRecorded':
            assert len(calls)==6
            assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==6
            settlements.append(event)
        return real(event)
    monkeypatch.setattr(sample.vault.ledger,'append',append)
    result=BulkDocuments(sample.vault,JobRegistry()).run({'retained_documents':choices,'confirm_reading':True})
    assert [row['ordinal'] for row in result['rows']]==[0,1,2]
    assert [row['document_id'] for row in result['rows']]==docs
    assert all(row['action']=='posted' for row in result['rows']),result
    assert settlements and len(calls)==6


@pytest.mark.parametrize('source',[None,{}, {'count':True,'head':'a'*64},(None,None,0),
    {'count':0,'head':None},{'count':0,'head':'A'*64}])
def test_source_codec_refuses_unavailable(source):
    with pytest.raises(ValueError):retained_source_identity(source)


def test_source_codec_only_count_head():
    assert retained_source_identity({'count':2,'head':'a'*64,'generation':'changed','last_sequence':1})==retained_source_identity((2,'a'*64,999))


def test_close_revokes_before_teardown_failure_and_reopen_new_owner(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    owner=retained_confirmation_owner(sample.vault)
    real=sample.vault.stop_read_store_worker
    monkeypatch.setattr(sample.vault,'stop_read_store_worker',lambda:(_ for _ in ()).throw(ValueError('synthetic teardown')))
    with pytest.raises(ValueError):sample.vault.close()
    with pytest.raises(ValueError):retained_confirmation_owner(sample.vault,create=True)
    assert owner.revoked and owner.consume([(doc,'b'*64,token)],sample.vault.ledger.store.authenticated_identity)==['confirmation_unavailable']
    monkeypatch.setattr(sample.vault,'stop_read_store_worker',real)
    reopened=Vault.open(sample.vault.directory,'synthetic-only',create=False)
    try:
        replacement=retained_confirmation_owner(reopened,create=True)
        assert replacement is not owner and replacement.epoch!=owner.epoch
        assert replacement.consume([(doc,'b'*64,token)],reopened.ledger.store.authenticated_identity)==['confirmation_unavailable']
    finally:reopened.close()


def test_capacity_rotation_never_revives_consumed_tokens(setup_bulk):
    owner=retained_confirmation_owner(setup_bulk.vault,create=True);source={'count':1,'head':'a'*64}
    doc='b'*64;capture='c'*64;tokens=[]
    for _ in range(128):
        t=owner.issue(doc,capture,source);tokens.append(t)
        assert owner.consume([(doc,capture,t)],source)==[None]
    old_epoch=owner.epoch;t=owner.issue(doc,capture,source)
    assert owner.consume([(doc,capture,t)],source)==['confirmation_unavailable']
    assert owner.epoch!=old_epoch and not owner.consumed
    for old in [tokens[0],tokens[-1],t]:
        assert owner.consume([(doc,capture,old)],source)==['confirmation_unavailable']


@pytest.mark.parametrize('fault',['token','document','capture','source'])
def test_substitutions_refuse_before_dispatch(setup_bulk,monkeypatch,fault):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    calls=actual_http(monkeypatch)
    if fault=='token':token=token[:-1]+('a' if token[-1]!='a' else 'b')
    if fault=='document':doc=capture(sample,1)
    if fault=='capture':
        sample.vault.ledger.append(document_captured(doc,'different.pdf',len(b'SYNTHETIC-0'),'unknown',0,'2026-01-01'))
    if fault=='source':
        capture(sample,1)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['action']=='refused',result
    assert not calls


def test_old_prefix_mutation_and_duplicate_old_receipt_refuse(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);owner=_begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')
    try:
        result=ReadResult('unknown',0,None)
        _validate_bulk_read(owner,result)
        sample.vault.ledger.append(Event.from_dict(owner.capture))
        with pytest.raises(ValueError):_validate_bulk_read(owner,result)
    finally:owner.close()



def test_scoped_old_classify_only_and_audit_body_identity_survive_new_read(setup_bulk,monkeypatch):
    sample=setup_bulk
    calls=actual_http(monkeypatch)
    real_post=OpenAICompatAdapter._post
    def classify_then_raise(self,body,headers):
        if getattr(self,'_test_calls',0):raise OSError('public no extract response')
        return real_post(self,body,headers)
    monkeypatch.setattr(OpenAICompatAdapter,'_post',classify_then_raise)
    initial=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    doc=initial['rows'][0]['document_id']
    old=[_audit_bytes(e) for e in sample.vault.ledger.events()]
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==1
    retry=selected(sample,doc,monkeypatch);assert retry['state']=='available',retry
    calls=actual_http(monkeypatch)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,retry['confirmation_token']))
    assert result['rows'][0]['action']=='posted',result
    assert [_audit_bytes(e) for e in list(sample.vault.ledger.events())[:len(old)]]==old
    assert len(calls)==2


@pytest.mark.parametrize('history',['accepted_unsupported','earlier_accepted_later_failure','unscoped','orphan','incomplete','partial_finance','held','unknown_provenance'])
def test_conservative_history_refuses_without_calls(setup_bulk,monkeypatch,history):
    from viva.ledger.events import read_recorded,model_extraction_response_recorded,statement_held
    from viva.extraction_responses import response_body
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    if history in {'accepted_unsupported','earlier_accepted_later_failure','unscoped'}:
        sample.vault.ledger.append(read_recorded(doc,'public','unsupported-schema','text+image','{}',0,0,0,
            history!='unscoped',None,'2026-01-02',phase='extract'))
        if history=='earlier_accepted_later_failure':
            sample.vault.ledger.append(read_recorded(doc,'public','unsupported-schema','text+image','bad',0,0,0,False,'public failure','2026-01-03',phase='extract'))
    elif history in {'orphan','incomplete'}:
        body=response_body(doc,'public','extract',0,0,'openai_compatible','public','v1','text+image',200,b'{}')
        event=model_extraction_response_recorded(body,'2026-01-02');sample.vault.ledger.append(event)
        if history=='incomplete':
            sample.vault.ledger.append(read_recorded(doc,'public','v1','text+image','bad',0,0,0,False,'incomplete','2026-01-02',phase='extract',transport_receipt_ids=[event.event_id],transport_complete=False,extraction_id='public',phase_attempt=0))
    elif history=='held':sample.vault.ledger.append(statement_held(doc,{},None,'gap','2026-01-02'))
    else:
        from viva.ledger.events import Provenance
        sample.vault.ledger.append(Event('PublicUnknownFinancialState','2026-01-02',body={'source':{'doc_id':doc}},provenance=Provenance(doc_id=doc) if history=='unknown_provenance' else Provenance()))
    calls=actual_http(monkeypatch)
    before=[_audit_bytes(e) for e in sample.vault.ledger.events()]
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['action']=='refused',result
    assert not calls and [_audit_bytes(e) for e in sample.vault.ledger.events()]==before


def test_missing_tampered_and_symlink_originals_never_dispatch(setup_bulk,monkeypatch,tmp_path):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    blob=sample.vault.raw.dir/(doc+'.blob');saved=blob.read_bytes();calls=actual_http(monkeypatch)
    for replacement in ('missing','tamper','symlink'):
        blob.unlink(missing_ok=True)
        if replacement=='tamper':blob.write_bytes(b'not sealed JSON')
        elif replacement=='symlink':
            target=tmp_path/'public-target';target.write_bytes(saved);blob.symlink_to(target)
        result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
        assert result['rows'][0]['action']=='refused' and not calls,result
    blob.unlink();blob.write_bytes(saved)


def test_stop_consumes_selection_and_drains_classification_without_second_request(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    action=BulkDocuments(sample.vault,JobRegistry());calls=actual_http(monkeypatch,before=lambda phase:action.stop())
    result=action.run(payload(doc,token))
    assert len(calls)==1 and result['rows'][0]['action']!='posted',result
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ModelExtractionResponseRecorded'])==1
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ReadRecorded'])==1
    replay=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert replay['rows'][0]['action']=='refused' and len(calls)==1


def test_close_while_response_inflight_drains_owned_response_no_next_dispatch(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    calls=actual_http(monkeypatch,before=lambda phase:sample.vault.close())
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert len(calls)==1 and result['rows'][0]['reason']=='outcome_unknown',result
    assert len([e for e in sample.vault.ledger.events() if e.event_type=='ModelExtractionResponseRecorded'])==1
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_capture_type_conflict_preserves_new_audit_and_blocks_finance(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample,kind='bank_statement');token=selected(sample,doc,monkeypatch)['confirmation_token']
    before=[_audit_bytes(e) for e in sample.vault.ledger.events()];calls=actual_http(monkeypatch)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['reason']=='outcome_unknown' and len(calls)==2,result
    events=list(sample.vault.ledger.events())
    assert [_audit_bytes(e) for e in events[:len(before)]]==before
    assert len([e for e in events if e.event_type=='ReadRecorded'])==2
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_concurrent_token_consumption_is_atomic(setup_bulk):
    owner=retained_confirmation_owner(setup_bulk.vault,create=True);source={'count':1,'head':'a'*64}
    doc='b'*64;capture='c'*64;token=owner.issue(doc,capture,source);results=[];gate=Barrier(2)
    def consume():gate.wait();results.append(owner.consume([(doc,capture,token)],lambda:source)[0])
    threads=[Thread(target=consume) for _ in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=5)
    assert sorted(str(r) for r in results)==['None','confirmation_used']


def test_raw_bound_accepts_exact_fifty_mib_and_refuses_one_more(setup_bulk):
    from viva.ingest.reader import MAX_BYTES
    sample=setup_bulk;data=b'P'*MAX_BYTES;doc=sample.vault.raw.put(data)
    sample.vault.ledger.append(document_captured(doc,'max-public.pdf',len(data),'unknown',0,'2026-01-01'))
    owner=_begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')
    try:assert owner.data==data
    finally:owner.close()
    oversized=data+b'P';doc=sample.vault.raw.put(oversized)
    sample.vault.ledger.append(document_captured(doc,'oversized-public.pdf',len(oversized),'unknown',0,'2026-01-01'))
    with pytest.raises(OverflowError):_begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')


def test_selected_provenance_probe_is_indexed_and_unknown_or_oversized_unavailable():
    import sqlite3
    from viva.read_store.documents_page import retained_retry_status
    c=sqlite3.connect(':memory:')
    c.executescript("""CREATE TABLE projection_meta(singleton INTEGER,schema_version INTEGER,projector_version TEXT);
      INSERT INTO projection_meta VALUES(1,39,'materialized-v30');
      CREATE TABLE event_provenance(doc_id TEXT,source_sequence INTEGER);
      CREATE INDEX event_provenance_by_document_source ON event_provenance(doc_id,source_sequence);
      CREATE TABLE applied_events(sequence INTEGER PRIMARY KEY,event_type TEXT);
      CREATE TABLE document_account_history(doc_id TEXT);
      CREATE INDEX document_accounts_by_doc ON document_account_history(doc_id);
      CREATE TABLE document_reads(doc_id TEXT,source_sequence INTEGER,phase TEXT,parse_ok INTEGER,body_json TEXT);
      CREATE INDEX document_reads_by_doc_date ON document_reads(doc_id,source_sequence);
      CREATE TABLE extraction_responses(doc_id TEXT,source_sequence INTEGER,event_id TEXT);
      CREATE INDEX extraction_responses_by_document_source ON extraction_responses(doc_id,source_sequence);""")
    doc='a'*64;item={'id':doc,'raw_available':True}
    plans=c.execute('EXPLAIN QUERY PLAN SELECT source_sequence FROM event_provenance INDEXED BY event_provenance_by_document_source WHERE doc_id=? LIMIT 10001',(doc,)).fetchall()
    assert any('COVERING INDEX event_provenance_by_document_source' in p[-1] for p in plans)
    plans=c.execute('EXPLAIN QUERY PLAN SELECT source_sequence FROM extraction_responses INDEXED BY extraction_responses_by_document_source WHERE doc_id=? LIMIT 10001',(doc,)).fetchall()
    assert any('COVERING INDEX extraction_responses_by_document_source' in p[-1] for p in plans)
    revision=SimpleNamespace(connection=c);queries=[];c.set_trace_callback(queries.append)
    assert retained_retry_status(revision,item)['state']=='available'
    c.execute("UPDATE projection_meta SET schema_version=38,projector_version='materialized-v29'")
    assert retained_retry_status(revision,item)['state']=='unavailable'
    c.execute("UPDATE projection_meta SET schema_version=39,projector_version='materialized-v30'")
    c.execute('INSERT INTO event_provenance VALUES(?,0)',(doc,));c.execute("INSERT INTO applied_events VALUES(0,'PublicUnknownFinancialState')")
    assert retained_retry_status(revision,item)['reason']=='financial_review'
    c.executemany('INSERT INTO event_provenance VALUES(?,?)',((doc,n) for n in range(1,10001)))
    assert retained_retry_status(revision,item)['state']=='unavailable'
    assert not any('response_text' in q or 'SELECT body_json' in q for q in queries)
    c.close()



def test_retained_raw_ack_precedes_json_decode_and_own_next_http(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    actual_http(monkeypatch);real_post=OpenAICompatAdapter._post;checks=[]
    def post(self,body,headers):
        phase='classify' if not getattr(self,'_test_calls',0) else 'extract'
        if phase=='extract':
            events=list(sample.vault.ledger.events())
            assert any(e.event_type=='ReadRecorded' and e.body['doc_id']==doc and e.body['phase']=='classify' for e in events)
            checks.append('classify_phase_ack_before_extract')
        response=real_post(self,body,headers);real_json=response.json
        def decode(*args,**kwargs):
            events=list(sample.vault.ledger.events())
            assert any(e.event_type=='ModelExtractionResponseRecorded' and e.body['doc_id']==doc and e.body['phase']==phase for e in events)
            checks.append(phase+'_raw_ack_before_decode')
            return real_json(*args,**kwargs)
        response.json=decode
        return response
    monkeypatch.setattr(OpenAICompatAdapter,'_post',post)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['action']=='posted',result
    assert checks==['classify_raw_ack_before_decode','classify_phase_ack_before_extract','extract_raw_ack_before_decode']


def test_entire_old_canonical_prefix_is_immutable_even_for_unrelated_events(setup_bulk,monkeypatch):
    sample=setup_bulk;old=Event('PublicUnrelated','2026-01-01',body={'note':'public old fact'})
    sample.vault.ledger.append(old);doc=capture(sample)
    owner=_begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')
    try:
        result=ReadResult('unknown',0,None)
        _validate_bulk_read(owner,result)
        events=[Event.from_dict(copy.deepcopy(e.to_dict())) for e in sample.vault.ledger.events()]
        events[0].body['note']='public changed fact'
        monkeypatch.setattr(sample.vault.ledger,'events',lambda:iter(events))
        with pytest.raises(ValueError,match='canonical prefix'):_validate_bulk_read(owner,result)
    finally:owner.close()


def test_ordinary_paths_still_skip_saved_original_and_empty_owner_bypass_refuses(setup_bulk,monkeypatch):
    from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_phase
    from viva.ingest.pipeline_models import ModelPhase
    sample=setup_bulk;calls=actual_http(monkeypatch)
    real_post=OpenAICompatAdapter._post
    def classify_only(self,body,headers):
        if getattr(self,'_test_calls',0):raise OSError('public no extraction response')
        return real_post(self,body,headers)
    monkeypatch.setattr(OpenAICompatAdapter,'_post',classify_only)
    first=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    doc=first['rows'][0]['document_id'];n=len(calls)
    duplicate=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    assert duplicate['rows'][0]['action']=='duplicate' and len(calls)==n
    data=__import__('pathlib').Path(sample.paths[0]).read_bytes()
    owner=_begin_bulk_read(sample.vault.raw,sample.vault.ledger,data,'document-0.pdf','2026-01-02')
    try:
        with pytest.raises(ValueError,match='another reading'):_validate_bulk_read(owner,ReadResult('unknown',0,None))
    finally:owner.close()



def test_derived_generation_rebuild_preserves_history_token_but_old_schema_cannot_issue(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample)
    old=selected(sample,doc,monkeypatch)['confirmation_token']
    source=retained_source_identity(sample.vault.ledger.store.authenticated_identity())
    store=sample.vault.read_store;generation=store.current_generation
    changed=store.synchronize(sample.vault.ledger.store,schema_version=37,projector_version='materialized-v28')
    assert changed.state=='rebuilt' and store.current_generation!=generation
    result=read_documents_page(sample.vault,b'x'*32,
        {'contract_version':'documents-page-v1','selected_document_id':doc},session_scope='a'*32)
    retry=result['selected_document']['document']['retry']
    assert retry['state']=='unavailable' and retry['confirmation_token'] is None,result
    sample.vault.synchronize_read_store()
    fresh=selected(sample,doc,monkeypatch)
    assert fresh['state']=='available' and retained_source_identity(sample.vault.ledger.store.authenticated_identity())==source
    calls=actual_http(monkeypatch)
    outcome=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,old))
    assert outcome['rows'][0]['action']=='posted' and len(calls)==2,outcome



def test_prior_effective_classification_conflict_cannot_authorize_new_financial_facts(setup_bulk,monkeypatch):
    sample=setup_bulk;actual_http(monkeypatch)
    monkeypatch.setattr(OpenAICompatAdapter,'_post',lambda *args,**kwargs:wire('openai-compatible','{"doc_type":"utility_bill","doc_type_confidence":0.97}'))
    first=BulkDocuments(sample.vault,JobRegistry()).run({'paths':sample.paths[:1]})
    doc=first['rows'][0]['document_id'];assert sample.vault.ledger.projection().captured_docs()[doc]=='utility_bill'
    token=selected(sample,doc,monkeypatch)['confirmation_token'];assert token
    calls=actual_http(monkeypatch)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert len(calls)==2 and result['rows'][0]['reason']=='outcome_unknown',result
    assert not sample.vault.ledger.projection().posted_doc_ids()


def test_canonical_admission_excludes_complete_accepted_unknown_schema_without_finance(setup_bulk):
    from viva.ingest.pipeline import _begin_bulk_read,_retain_bulk_response,_retain_bulk_phase
    from viva.ingest.pipeline_models import ModelPhase
    from viva.extraction_responses import response_body
    sample=setup_bulk;data=b'public unsupported accepted schema'
    owner=_begin_bulk_read(sample.vault.raw,sample.vault.ledger,data,'public.pdf','2026-01-01')
    try:
        for phase,text in [('classify','{"doc_type":"credit_card_statement","doc_type_confidence":0.97}'),('extract','{"schema":"unsupported-v99"}')]:
            receipt=_retain_bulk_response(owner,response_body(owner.document,'public-reading',phase,0,0,'openai_compatible','public','unsupported-v99','text+image',200,b'{}'))
            _retain_bulk_phase(owner,ModelPhase(phase,'public','unsupported-v99',text,parse_ok=True,
                transport_receipt_ids=[receipt],transport_complete=True,extraction_id='public-reading',phase_attempt=0),'credit_card_statement',0.97)
        doc=owner.document
    finally:owner.close()
    assert not sample.vault.ledger.projection().posted_doc_ids()
    with pytest.raises(ValueError,match='already_accepted'):
        _begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')


def test_canonical_admission_blocks_partial_unknown_financial_provenance(setup_bulk):
    sample=setup_bulk;doc=capture(sample)
    sample.vault.ledger.append(Event('PublicUnknownFinancialState','2026-01-01',body={'partial':{'source':{'doc_id':doc}}}))
    with pytest.raises(ValueError,match='financial_review'):
        _begin_retained_bulk_read(sample.vault.raw,sample.vault.ledger,doc,'2026-01-02')



def test_late_reader_exception_still_checks_retained_old_prefix(setup_bulk,monkeypatch):
    sample=setup_bulk
    sample.vault.ledger.append(Event('PublicUnrelated','2026-01-01',body={'note':'original old prefix'}))
    doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    calls=actual_http(monkeypatch);real_build=reader.build_reader;real_events=sample.vault.ledger.events
    def build():
        read,configured=real_build();prepared=read.read_prepared
        def late(*args,**kwargs):
            prepared(*args,**kwargs)
            def altered():
                events=[Event.from_dict(copy.deepcopy(e.to_dict())) for e in real_events()]
                events[0].body['note']='changed old prefix'
                return iter(events)
            monkeypatch.setattr(sample.vault.ledger,'events',altered)
            raise RuntimeError('public late reader exception after acknowledged phases')
        read.read_prepared=late
        return read,configured
    monkeypatch.setattr(reader,'build_reader',build)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['reason']=='outcome_unknown',result
    assert len(calls)==2
    assert len([e for e in real_events() if e.event_type=='ModelExtractionResponseRecorded'])==2
    assert len([e for e in real_events() if e.event_type=='ReadRecorded'])==2
    assert not sample.vault.ledger.projection().posted_doc_ids()



@pytest.mark.parametrize('ordinary',[False,True])
def test_same_id_complete_actions_serialize_without_duplicate_paid_work(setup_bulk,monkeypatch,ordinary):
    from contextlib import contextmanager
    from threading import Event as ThreadEvent,Lock
    from vivacore.models import PageImage
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    real_build=reader.build_reader
    def build():
        read,configured=real_build()
        def prepare(data,checkpoint=None):
            if checkpoint:checkpoint()
            return (PageImage(1,b'public png',data.decode()),),data.decode()
        read.prepare=prepare
        return read,configured
    monkeypatch.setattr(reader,'build_reader',build)
    both_attempted=ThreadEvent();mutex=Lock();attempts=[];real_lock=sample.vault.raw.document_lock
    @contextmanager
    def lock(document):
        with mutex:
            attempts.append(document)
            if len(attempts)>=2:both_attempted.set()
        with real_lock(document):yield
    monkeypatch.setattr(sample.vault.raw,'document_lock',lock)
    def before(phase):
        if phase=='classify':assert both_attempted.wait(timeout=5)
    calls=actual_http(monkeypatch,before=before)
    requests=[payload(doc,token),{'paths':sample.paths[:1]} if ordinary else payload(doc,token)]
    start=Barrier(2);results=[None,None];errors=[]
    def run(index):
        try:
            start.wait(timeout=5)
            results[index]=BulkDocuments(sample.vault,JobRegistry()).run(requests[index])
        except BaseException as exc:errors.append((type(exc).__name__,str(exc)))
    threads=[Thread(target=run,args=(index,)) for index in range(2)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads) and not errors,errors
    actions=sorted(result['rows'][0]['action'] for result in results)
    assert actions==(['duplicate','posted'] if ordinary else ['posted','refused']),results
    assert len(calls)==2 and len(attempts)==2
    events=list(sample.vault.ledger.events())
    assert len([e for e in events if e.event_type=='DocumentCaptured'])==1
    assert len([e for e in events if e.event_type=='ReadRecorded'])==2
    assert len([e for e in events if e.event_type=='ModelExtractionResponseRecorded'])==2


@pytest.mark.parametrize('bad',[
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'one'},{'document_id':'a'*64,'confirmation_token':'two'}],'confirm_reading':True},
    {'retained_documents':[{'document_id':'a'*64,'confirmation_token':'same'},{'document_id':'b'*64,'confirmation_token':'same'}],'confirm_reading':True},
    {'retained_documents':[{'document_id':c*64,'confirmation_token':c+'\x00'*1023} for c in 'abc'],'confirm_reading':True},
    {'retained_documents':[{'document_id':c*64,'confirmation_token':c} for c in 'abcd'],'confirm_reading':True},
])
def test_duplicate_and_serialized_oversized_selectors_refuse_before_admission(bad):
    with pytest.raises(ValueError):_retained(bad)



def test_retained_phase_only_adapter_cannot_settle_without_scoped_raw_ack(setup_bulk,monkeypatch):
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['reason']=='outcome_unknown',result
    assert not sample.vault.ledger.projection().posted_doc_ids()
    events=list(sample.vault.ledger.events())
    assert len([e for e in events if e.event_type=='ReadRecorded'])==2
    assert not [e for e in events if e.event_type=='ModelExtractionResponseRecorded']



def test_retained_flat_facts_without_any_owned_phase_cannot_post(setup_bulk,monkeypatch):
    from dataclasses import replace
    sample=setup_bulk;doc=capture(sample);token=selected(sample,doc,monkeypatch)['confirmation_token']
    real_build=reader.build_reader
    def build():
        read,configured=real_build();original=read.read_prepared
        def without_receipts(pages,text,document,**kwargs):
            result=original(pages,text,document)
            assert result.facts is not None
            return replace(result,phases=[])
        read.read_prepared=without_receipts
        return read,configured
    monkeypatch.setattr(reader,'build_reader',build)
    result=BulkDocuments(sample.vault,JobRegistry()).run(payload(doc,token))
    assert result['rows'][0]['reason']=='outcome_unknown',result
    assert not sample.vault.ledger.projection().posted_doc_ids()



@pytest.mark.parametrize('column',['filename','raw_type','capture_event_id'])
def test_selected_capture_identity_scalars_are_bounded(column):
    import sqlite3
    from viva.read_store.document_index import retry_capture_identity
    c=sqlite3.connect(':memory:')
    c.executescript("""CREATE TABLE document_library(doc_id TEXT,filename TEXT,identity_conflict INTEGER);
        CREATE TABLE document_type_captures(doc_id TEXT,raw_type TEXT,capture_event_id TEXT);""")
    values={'filename':'public.pdf','raw_type':'unknown','capture_event_id':'public-capture'}
    values[column]='P'*4097
    c.execute('INSERT INTO document_library VALUES(?,?,0)',('a'*64,values['filename']))
    c.execute('INSERT INTO document_type_captures VALUES(?,?,?)',('a'*64,values['raw_type'],values['capture_event_id']))
    with pytest.raises(ValueError):retry_capture_identity(c,'a'*64)
    c.close()
