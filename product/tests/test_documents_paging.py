"""Actual event→SQL→surface provider paging, with no document/model/vault opens."""
import hashlib,json,time
from types import SimpleNamespace
import pytest
from viva.ledger import EventStore,Provenance
from viva.ledger.events import document_captured
from viva.read_store import ReadStore
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.desktop_bridge.handlers import handlers_with_surface_provider
from viva.desktop_bridge.rpc import dispatch_frame
from viva.read_store import documents_page as paging

@pytest.fixture
def library(tmp_path,monkeypatch):
    import socket
    from viva import env
    from viva.ingest import reader
    for name,child in [('HOME','home'),('MERCHANTCORE_HOME','merchant'),('VIVA_PROFILES','profiles')]:
        path=tmp_path/child;path.mkdir();monkeypatch.setenv(name,str(path))
    monkeypatch.setattr(env,'CONFIG_HOME',tmp_path/'config')
    empty=tmp_path/'empty.env';empty.write_text('');monkeypatch.setenv('VIVA_ENV_FILE',str(empty))
    monkeypatch.setenv('VIVA_CATALOG',str(tmp_path/'merchant/catalog.json'))
    def denied(*args,**kwargs):raise AssertionError('provider/network calls forbidden in Documents read test')
    monkeypatch.setattr(socket.socket,'connect',denied);monkeypatch.setattr(socket,'create_connection',denied)
    monkeypatch.setattr(reader,'live_reading_configured',lambda:False)
    events=EventStore.open(tmp_path/'events.jsonl','synthetic-paging-only')
    reads=ReadStore.create(tmp_path/'reads','synthetic-paging-only')
    present=set();all_ids=[]
    def add(count,start=0,duplicate=None):
        ids=[hashlib.sha256(f'captured-{i}'.encode()).hexdigest() for i in range(start,start+count)] if duplicate is None else [duplicate]*count
        events.append_atomically(lambda _:tuple(document_captured(doc,f'{doc}.pdf',1,'statement',1,'2026-01-01',Provenance(doc)) for doc in ids))
        present.update(ids);all_ids.extend(ids);reads.synchronize(events);return ids
    def prohibited(*a,**k):raise AssertionError('paging may not enumerate raw IDs')
    raw=SimpleNamespace(has=lambda doc:doc in present,doc_ids=prohibited)
    vault=SimpleNamespace(read_store=reads,read_store_lifecycle='equal',poll_read_store_worker=lambda:None,raw=raw)
    provider=OpenedVaultSurfaceProvider(vault)
    yield SimpleNamespace(add=add,events=events,reads=reads,provider=provider,present=present,raw=raw,vault=vault)
    reads.close()

def read(lib,**params):
    frame={'protocol':'2.1','request_id':'paging-read','operation':'viva.surface.read',
        'payload':{'surface':'documents','parameters':{'contract_version':paging.CONTRACT,**params},'job_id':'paging-test'}}
    wire=dispatch_frame(json.dumps(frame),handlers_with_surface_provider(lib.provider).handlers)
    read.last_frame_bytes=len(wire.encode('utf-8'))
    assert read.last_frame_bytes<=100000
    response=json.loads(wire)
    assert response['protocol']=='2.1' and response['ok'],response
    return response['result']['data']

@pytest.mark.parametrize('count',[0,1,49,50,51,200,201,794])
def test_actual_composed_pages_and_full_traversal(library,count):
    ids=library.add(count);seen=[];cursor=None;sizes=[];measurements=[]
    while True:
        started=time.monotonic();data=read(library,**({'cursor':cursor} if cursor else {}))
        elapsed=time.monotonic()-started
        assert elapsed<2
        measurements.append({'page':len(sizes)+1,'rows':len(data['documents']),'seconds':elapsed,'surface_utf8_bytes':len(json.dumps(data,separators=(',',':')).encode('utf-8')),'bridge_response_utf8_bytes':read.last_frame_bytes})
        assert data['state']=='ready' and data['page']['total_documents']==count
        assert len(json.dumps(data,separators=(',',':')).encode('utf-8'))<=100000
        rows=data['documents'];sizes.append(len(rows));seen.extend(row['id'] for row in rows)
        assert len(rows)<=50 and data['summary']['scope']=='revision'
        assert data['summary']['counts']['never_read']==count
        cursor=data['page']['next_cursor']
        if not cursor:break
    assert seen==ids and len(set(seen))==count
    if count==794:
        assert sizes==[50]*15+[44]
        from pathlib import Path
        Path('/private/tmp/persona-documents-paging-prep/composed-794-measurements.json').write_text(json.dumps({'path':'actual event→SQL→OpenedVaultSurfaceProvider→VaultSurfaceReader→dispatch_frame2.1','provider_calls':0,'pages':measurements},indent=2)+'\n')


def test_selected_last_is_independent_and_hydration_never_exceeds51(library,monkeypatch):
    ids=library.add(794);calls=[];original=paging._hydrate
    def tracked(*args,**kwargs):calls.append(args[1]);return original(*args,**kwargs)
    monkeypatch.setattr(paging,'_hydrate',tracked)
    data=read(library,selected_document_id=ids[-1])
    assert data['selected_document']['state']=='ready' and data['selected_document']['document']['id']==ids[-1]
    assert ids[-1] not in [row['id'] for row in data['documents']]
    assert len(calls)==len(set(calls))==51
    calls.clear();read(library,selected_document_id=ids[0]);assert len(calls)==50
    with library.reads.open_reader() as revision:
        plan=' '.join(str(row[-1]) for row in revision.connection.execute('EXPLAIN QUERY PLAN SELECT first_sequence,doc_id FROM document_library INDEXED BY document_library_order WHERE (first_sequence,doc_id)>(?,?) ORDER BY first_sequence,doc_id LIMIT 51',(1,ids[0])))
        assert 'document_library_order' in plan and 'TEMP B-TREE' not in plan


def test_duplicate_capture_multiplicity_does_not_move_anchor_or_break_page(library):
    ids=library.add(51);first=read(library)
    library.add(10001,duplicate=ids[0])
    data=read(library)
    assert data['state']=='ready' and data['page']['total_documents']==51
    assert [row['id'] for row in data['documents']]==[row['id'] for row in first['documents']]
    with library.reads.open_reader() as revision:
        assert revision.connection.execute('SELECT COUNT(*) FROM documents').fetchone()[0]==10052
        assert revision.connection.execute('SELECT first_sequence,last_sequence FROM document_library WHERE doc_id=?',(ids[0],)).fetchone()==(0,10051)

@pytest.mark.parametrize('params',[{'contract_version':'unknown'},{'cursor':'x'},{'contract_version':True},{'contract_version':paging.CONTRACT,'extra':1},{'contract_version':paging.CONTRACT,'cursor':True},{'contract_version':paging.CONTRACT,'cursor':'雪'*1400},{'contract_version':paging.CONTRACT,'selected_document_id':'A'*64},{'contract_version':paging.CONTRACT,'selected_document_id':1}])
def test_closed_request_rejects_unknown_types_versions_keys(library,params):
    from viva.desktop_bridge.handlers import BridgeRequestError
    with pytest.raises(BridgeRequestError):library.provider.read_surface('documents',params)


def test_authenticated_cursor_tamper_other_provider_and_new_revision_refuse(library):
    library.add(51);cursor=read(library)['page']['next_cursor']
    assert read(library,cursor=cursor[:-1]+('a' if cursor[-1]!='a' else 'b'))['state']=='failed'
    other=OpenedVaultSurfaceProvider(library.vault)
    data=other.read_surface('documents',{'contract_version':paging.CONTRACT,'cursor':cursor})
    assert data['reason']=='invalid_cursor'
    library.add(1,start=1000)
    assert read(library,cursor=cursor)['reason']=='stale_cursor'


def test_malformed_unselected_tail_does_not_block_valid_page_or_selected_detail(library):
    ids=library.add(51)
    library.reads.publish(lambda connection:connection.execute('UPDATE document_library SET filename=? WHERE doc_id=?',('x'*4097,ids[-1])),copy_current=True)
    data=read(library);assert data['state']=='ready' and len(data['documents'])==50
    data=read(library,selected_document_id=ids[-1]);assert data['selected_document']['state']=='unavailable'
    assert data['selected_document']['reason']=='detail_resource_limit'
    data=read(library,selected_document_id='f'*64);assert data['selected_document']['state']=='missing'


def test_original_presence_is_independent_from_valid_detail_and_identity_conflict(library):
    ids=library.add(1);library.present.clear()
    data=read(library,selected_document_id=ids[0]);assert data['selected_document']['state']=='ready'
    assert data['selected_document']['document']['raw_available'] is False
    library.events.append(document_captured(ids[0],'different.pdf',1,'statement',1,'2026-01-02',Provenance(ids[0])))
    library.reads.synchronize(library.events)
    data=read(library,selected_document_id=ids[0]);assert data['selected_document']['state']=='conflicted_identity'
    assert data['page']['total_documents']==1

@pytest.mark.parametrize('bound,value',[('MAX_HYDRATED',49),('MAX_RESPONSE_BYTES',1),('MAX_SECONDS',0)])
def test_complete_resource_limits_fail_with_typed_response(library,monkeypatch,bound,value):
    library.add(50);monkeypatch.setattr(paging,bound,value)
    data=read(library);assert data['state']=='failed' and data['reason']=='resource_limit'
    assert data['page']['total_documents'] is None and not data['documents']


def test_count_failure_is_nullable_and_does_not_become_loaded_count(library):
    library.add(51)
    from sqlcipher3 import dbapi2 as sql
    with library.reads.open_reader() as revision:
        denied=[]
        def authorize(action,first,second,database,trigger):
            if action==sql.SQLITE_FUNCTION and second=='sum':
                denied.append((action,first,second))
                return sql.SQLITE_DENY
            return sql.SQLITE_OK
        revision.connection.set_authorizer(authorize)
        try:data=paging.documents_page(revision,raw=library.raw,secret=b'x'*32,session_scope='a'*32,parameters_value={'contract_version':paging.CONTRACT})
        finally:revision.connection.set_authorizer(None)
        assert denied and all(action==sql.SQLITE_FUNCTION and function=='sum'
                              for action,_argument,function in denied)
        assert revision.connection.execute('SELECT SUM(1)').fetchone()==(1,)
    assert len(data['documents'])==50 and data['page']['total_documents'] is None
    assert data['page']['total_unavailable_reason']=='count_unavailable' and data['summary']['counts'] is None


def test_actual_instrument_held_component_and_retracted_source_stay_explicit(library):
    from dataclasses import replace
    from viva.ledger import Ledger
    from viva.ingest.instrument_read import parser_for
    from viva.ingest.instrument_projector import post_instrument
    from viva.ingest.instrument_observations import Operation,ObservationKind
    from viva.ledger.instruments import append_change,decode_change
    from test_instrument_reader_b import _proposal
    doc=library.add(1)[0];ledger=Ledger(library.events)
    facts,error=parser_for('mortgage_statement')(json.dumps(_proposal('mortgage_statement')),doc,'en-US','USD')
    assert error is None
    post_instrument(ledger,facts);library.reads.synchronize(library.events)
    data=read(library,selected_document_id=doc)
    detail=data['selected_document']['document'];components={item['component']:item['disposition'] for item in detail['component_statuses']}
    assert components['principal_balance']=='accepted' and components['payment:PAY-X']=='held'
    changes=[decode_change(event.body['record']) for event in ledger.events() if event.event_type=='InstrumentObservationRecorded']
    snapshot=next(change for change in changes if change.kind==ObservationKind.MORTGAGE_COMPONENTS)
    append_change(ledger,replace(snapshot,observation_id='explicit-retraction',operation=Operation.RETRACT,payload=None,prior_id=snapshot.observation_id))
    library.reads.synchronize(library.events)
    data=read(library,selected_document_id=doc)
    assert data['selected_document']['state']=='ready' and 'retracted' in data['selected_document']['document']['observation_statuses']
    assert data['page']['total_documents']==1 and data['selected_document']['document']['raw_available']


def test_real_large_serialized_payload_refuses_instead_of_truncating(library):
    library.add(50)
    library.reads.publish(lambda connection:connection.execute('UPDATE document_library SET filename=?',('雪'*1300,)),copy_current=True)
    data=read(library)
    assert data['state']=='failed' and data['reason']=='resource_limit' and data['documents']==[]


def test_invalid_unselected_identity_makes_global_count_unavailable_not_false_zero(library):
    ids=library.add(51)
    library.reads.publish(lambda connection:connection.execute('UPDATE document_library SET doc_id=? WHERE doc_id=?',('invalid-tail',ids[-1])),copy_current=True)
    data=read(library)
    assert data['state']=='ready' and len(data['documents'])==50
    assert data['page']['total_documents'] is None and data['page']['total_unavailable_reason']=='count_unavailable'


def test_reopen_and_authenticated_scope_mutations_do_not_continue(library):
    import base64
    library.add(51);token=read(library)['page']['next_cursor']
    envelope=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
    original=envelope['body']
    for name,value in [('contract','unknown'),('surface','activity'),('order',2),('limit',51),('generation','different')]:
        scope={**original['scope'],name:value}
        mutated=paging._encode({**original,'scope':scope},library.provider._cursor_secret)
        assert read(library,cursor=mutated)['reason']=='stale_cursor'
    reopened=OpenedVaultSurfaceProvider(library.vault)
    assert reopened.read_surface('documents',{'contract_version':paging.CONTRACT,'cursor':token})['reason']=='invalid_cursor'


def test_injected_same_key_does_not_waive_new_provider_session_scope(library):
    library.add(51);token=read(library)['page']['next_cursor']
    other=OpenedVaultSurfaceProvider(library.vault,cursor_secret=library.provider._cursor_secret)
    result=other.read_surface('documents',{'contract_version':paging.CONTRACT,'cursor':token})
    assert result['state']=='failed' and result['reason']=='stale_cursor'


@pytest.mark.parametrize('job_id,request_id',[('x'*100001,'normal'),('雪'*19000,'normal'),('x'*100001,'雪'*50000)])
def test_actual_rpc_resource_refusal_bounds_job_and_correlation(job_id,request_id):
    from viva.desktop_bridge.surface_read import VaultSurfaceReader
    provider=SimpleNamespace(read_surface=lambda surface,params:{'contract_version':paging.CONTRACT,'state':'ready','documents':[]})
    handlers={'viva.surface.read':VaultSurfaceReader(provider).read}
    frame={'protocol':'2.1','request_id':request_id,'operation':'viva.surface.read',
        'payload':{'surface':'documents','parameters':{'contract_version':paging.CONTRACT},'job_id':job_id}}
    wire=dispatch_frame(json.dumps(frame),handlers)
    assert len(wire.encode('utf-8'))<=100000
    result=json.loads(wire)
    assert result['ok'] is False and result['error']['code']=='resource_limit'


def test_complete_rpc_envelope_limit_catches_near_boundary_surface():
    from viva.desktop_bridge.surface_read import VaultSurfaceReader
    data={'contract_version':paging.CONTRACT,'state':'ready','documents':[],'padding':''}
    base=len(json.dumps({'surface':'documents','job_id':'test','data':data},separators=(',',':')).encode('utf-8'))
    data['padding']='x'*(99990-base)
    provider=SimpleNamespace(read_surface=lambda surface,params:data)
    frame={'protocol':'2.1','request_id':'test','operation':'viva.surface.read',
        'payload':{'surface':'documents','parameters':{'contract_version':paging.CONTRACT},'job_id':'test'}}
    wire=dispatch_frame(json.dumps(frame),{'viva.surface.read':VaultSurfaceReader(provider).read})
    assert len(wire.encode('utf-8'))<=100000 and json.loads(wire)['error']['code']=='resource_limit'


def test_current_source_attention_heals_without_rewriting_historical_import(library,tmp_path):
    from viva.ledger import Ledger
    from viva.ingest import RawStore
    from test_instrument_projector_b import ingest,mortgage,bank
    from viva.read_store.instrument_review import document_attention
    raw=RawStore.open(tmp_path/'attention-raw','synthetic-only')
    ledger=Ledger(library.events)
    result=ingest(raw,ledger,'attention-mortgage',mortgage(),'mortgage_statement')
    assert result.action=='awaiting'
    library.reads.synchronize(library.events)
    with library.reads.open_reader() as revision:
        attention=document_attention(revision)
    assert attention['state']=='ready' and attention['total_documents']==1
    row=attention['documents'][0]
    assert row['document_id']==result.doc_id
    assert any(component['component']=='payment:PAY-A' and component['disposition']=='held' for component in row['components'])
    assert all(source['document_id']==result.doc_id and source['page']==1 for component in row['components'] for source in component['source_pages'])
    bank(raw,ledger)
    library.reads.synchronize(library.events)
    with library.reads.open_reader() as revision:
        healed=document_attention(revision)
    assert healed['state']=='ready' and healed['total_documents']==0 and healed['documents']==[], json.dumps(healed)
    assert result.action=='awaiting'  # Saved initial receipt is historical, not current attention.
    detail=read(library,selected_document_id=result.doc_id)['selected_document']['document']
    assert all(component['disposition']!='held' for component in detail['component_statuses'])


@pytest.mark.parametrize('family',['term_deposit_statement','mortgage_statement','refinance_settlement','property_tax_receipt'])
def test_all_family_source_sections_are_closed_labeled_and_page_bound(library,family):
    from viva.ledger import Ledger
    from viva.ingest.instrument_read import parser_for
    from viva.ingest.instrument_projector import post_instrument
    from test_instrument_reader_b import _proposal
    doc=library.add(1)[0]
    facts,error=parser_for(family)(json.dumps(_proposal(family)),doc,'en-US','USD');assert error is None
    post_instrument(Ledger(library.events),facts);library.reads.synchronize(library.events)
    detail=read(library,selected_document_id=doc)['selected_document']['document']
    assert detail['component_statuses']
    for component in detail['component_statuses']:
        assert component['label']!='Source component' and component['reason'] and component['reason_code']
        assert component['source_pages']
        assert all(page['document_id']==doc and 1<=page['page']<=200 for page in component['source_pages'])
    for observation in detail['observation_sections']:
        assert observation['lifecycle'] in ('active','superseded','retracted')
        assert observation['source_pages']


def test_attention_global_count_and_fifty_row_bound_are_current_indexed_and_truthful(library):
    from viva.ledger import Ledger
    from viva.ingest.instrument_read import parser_for
    from viva.ingest.instrument_projector import post_instrument
    from viva.read_store.instrument_review import document_attention
    from test_instrument_reader_b import _proposal
    ids=library.add(51);ledger=Ledger(library.events)
    for doc in ids:
        facts,error=parser_for('mortgage_statement')(json.dumps(_proposal('mortgage_statement')),doc,'en-US','USD')
        assert error is None
        post_instrument(ledger,facts)
    library.reads.synchronize(library.events)
    page=read(library,selected_document_id=ids[-1])
    assert len(page['documents'])==50 and page['selected_document']['state']=='ready'
    with library.reads.open_reader() as revision:
        attention=document_attention(revision)
    assert attention['state']=='ready'
    assert attention['total_documents']==51 and attention['shown_count']==50 and attention['remaining_count']==1
    assert [row['document_id'] for row in attention['documents']]==ids[:50]
    assert len(json.dumps(attention,ensure_ascii=True).encode('utf-8'))<=100000


def test_actual_review_rpc_carries_source_attention_without_question_mutations(library):
    from viva.ledger import Ledger
    from viva.ingest.instrument_read import parser_for
    from viva.ingest.instrument_projector import post_instrument
    from test_instrument_reader_b import _proposal
    doc=library.add(1)[0]
    facts,error=parser_for('mortgage_statement')(json.dumps(_proposal('mortgage_statement')),doc,'en-US','USD');assert error is None
    post_instrument(Ledger(library.events),facts);library.reads.synchronize(library.events)
    wire=dispatch_frame(json.dumps({'protocol':'2.1','request_id':'source-attention','operation':'viva.surface.read','payload':{'surface':'review','parameters':{},'job_id':'review-test'}}),handlers_with_surface_provider(library.provider).handlers)
    result=json.loads(wire);assert result['ok'],result
    data=result['result']['data'];attention=data['document_attention']
    assert attention['state']=='ready' and attention['total_documents']==1
    assert attention['documents'][0]['document_id']==doc
    assert all(item['type']=='question' for group in data['groups'] for item in group['items'])


def test_oversized_selected_detail_does_not_poison_otherwise_bounded_page(library,monkeypatch):
    ids=library.add(51)
    original=paging._hydrate_record
    def hydrate(revision,key,raw,locale):
        value=original(revision,key,raw,locale)
        if key==ids[-1]:value['observation_sections']=[{'label':'X'*100000}]
        return value
    monkeypatch.setattr(paging,'_hydrate_record',hydrate)
    data=read(library,selected_document_id=ids[-1])
    assert len(data['documents'])==50 and data['page']['total_documents']==51
    assert all(row['detail_requires_lookup'] for row in data['documents'])
    assert all('component_statuses' not in row and 'observation_sections' not in row for row in data['documents'])
    assert data['selected_document']=={'state':'unavailable','reason':'detail_resource_limit','document':None}


def test_final_surface_composition_is_inside_actual_rpc_byte_budget(library,monkeypatch):
    from viva.surface import documents_page as surface
    library.add(1)
    monkeypatch.setattr(surface,'moment',lambda *_:'é'*100000)
    result=read(library)
    assert result['state']=='failed' and result['reason']=='resource_limit'
    assert result['documents']==[] and read.last_frame_bytes<=100000


def test_final_surface_composition_keeps_original_read_deadline(library,monkeypatch):
    from viva.surface import documents_page as surface
    library.add(1)
    monkeypatch.setattr(surface,'time',SimpleNamespace(monotonic=lambda:time.monotonic()+2.01))
    result=read(library)
    assert result['state']=='failed' and result['reason']=='resource_limit'
    assert result['selected_document']['state']=='unavailable'


def test_indexed_data_has_no_surface_composition(library):
    library.add(1)
    with library.reads.open_reader() as revision:
        result=paging.documents_page(revision,raw=library.raw,secret=b'x'*32,session_scope='a'*32,parameters_value={'contract_version':paging.CONTRACT})
    row=result['documents'][0]
    assert 'contribution_data' in row and 'snapshot_attention' in row
    assert not {'snapshot_sentence','activity_sentence','contribution'} & row.keys()
