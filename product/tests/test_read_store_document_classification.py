"""Authenticated incremental classifier indexes reach composed Documents reads."""
import hashlib,json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from viva.ledger import LedgerProjection
from viva.ledger.events import document_captured,read_recorded,model_extraction_response_recorded
from viva.extraction_responses import response_body
from viva.read_store.document_index import materialize_classification
from viva.read_store.store import ReadStoreError
from test_documents_paging import library,read


def saved_events(kind='pay_stub',raw_type='unknown'):
    doc=hashlib.sha256(b'public-classified-document').hexdigest()
    capture=document_captured(doc,'public.pdf',1,raw_type,.3,'2026-01-01')
    response=model_extraction_response_recorded(response_body(doc,'public-extraction','classify',0,0,
        'openai_compatible','public-model','public-prompt','text+image',200,b'{}'),'2026-01-01')
    phase=read_recorded(doc,'public-model','public-prompt','text+image',json.dumps({'doc_type':kind,'doc_type_confidence':.9}),
        0,0,0,True,None,'2026-01-01',phase='classify',transport_receipt_ids=[response.event_id],
        transport_complete=True,extraction_id='public-extraction',phase_attempt=0)
    return doc,[capture,response,phase]


@pytest.mark.parametrize('family',['checking_statement','pay_stub','brokerage_statement','mortgage_statement','utility_bill'])
def test_owned_page_detail_legacy_and_event_projection_agree(library,family):
    doc,events=saved_events(family);library.present.add(doc)
    library.events.append_atomically(lambda _:tuple(events));library.reads.synchronize(library.events)
    data=read(library,selected_document_id=doc)
    assert data['documents'][0]['doc_type']==family
    assert data['selected_document']['document']['doc_type']==family
    with library.reads.open_reader() as revision:
        assert revision.documents_projection().captured_docs()=={doc:family}
        assert revision.connection.execute('SELECT raw_type FROM document_type_captures').fetchone()==('unknown',)
        assert revision.connection.execute('SELECT event_id,receipt_ids_json FROM document_classify_claims').fetchone()==(events[-1].event_id,json.dumps([events[1].event_id],separators=(',',':')))
        assert revision.connection.execute('SELECT identity_conflict FROM document_library').fetchone()==(0,)
    assert LedgerProjection(library.events.events()).captured_docs()=={doc:family}


def test_incremental_prefix_ambiguity_rebuild_reopen_and_cache_invalidation(library):
    doc,events=saved_events();library.present.add(doc)
    library.events.append(events[0]);library.reads.synchronize(library.events)
    held=library.reads.open_reader()
    library.events.append_atomically(lambda _:tuple(events[1:]));library.reads.synchronize(library.events)
    assert held.documents_projection().captured_docs()=={doc:'unknown'};held.close()
    assert read(library)['documents'][0]['doc_type']=='pay_stub'
    # A new successful ordinary classifier claim disagrees, without changing any original event.
    other=read_recorded(doc,'public-model','public-prompt','text+image','{"doc_type":"brokerage_statement","doc_type_confidence":0.8}',
        0,0,0,True,None,'2026-01-02',phase='classify')
    library.events.append(other);library.reads.synchronize(library.events)
    assert read(library)['documents'][0]['doc_type']=='unknown'
    assert library.reads.synchronize(library.events).state=='equal'
    library.reads.synchronize(library.events,schema_version=36,projector_version='materialized-v27')
    assert library.reads.synchronize(library.events).state=='rebuilt'
    assert read(library)['documents'][0]['doc_type']=='unknown'
    assert len(tuple(library.events.events()))==4
    from viva.read_store import ReadStore
    with ReadStore.open(library.reads.directory,'synthetic-paging-only') as reopened:
        assert reopened.synchronize(library.events).state=='equal'
        with reopened.open_reader() as revision:
            assert revision.documents_projection().captured_docs()=={doc:'unknown'}


def test_known_capture_and_true_raw_recapture_conflict(library):
    doc,events=saved_events(raw_type='checking_statement');library.present.add(doc)
    library.events.append_atomically(lambda _:tuple(events));library.reads.synchronize(library.events)
    assert read(library)['documents'][0]['doc_type']=='checking_statement'
    library.events.append(document_captured(doc,'public.pdf',1,'pay_stub',.9,'2026-01-02'))
    library.reads.synchronize(library.events)
    with library.reads.open_reader() as revision:
        assert revision.connection.execute('SELECT identity_conflict FROM document_library WHERE doc_id=?',(doc,)).fetchone()==(1,)


def test_classification_writer_requires_real_publication_owner():
    with pytest.raises(ReadStoreError,match='writer scope'):
        materialize_classification(None,SimpleNamespace(event=saved_events()[1][-1]),object())


def test_encrypted_transfer_retains_exact_classifier_evidence_without_new_events(library,tmp_path):
    from viva.vault import Vault
    from viva.vault_transfer import export_vault,restore_vault
    from viva.read_store import ReadStore
    phrase='public-classification-transfer-only'
    original=b'public-classified-document'
    doc,events=saved_events()
    events[0]=replace(events[0],body={**events[0].body,'byte_len':len(original)})
    source=Vault.open(tmp_path/'source',phrase)
    try:
        assert source.raw.put(original)==doc
        source.ledger.append_atomically(lambda _:tuple(events))
        source.synchronize_read_store()
        before=[event.to_dict() for event in source.ledger.events()]
        assert source.ledger.projection().captured_docs()=={doc:'pay_stub'}
    finally:source.close()
    archive=tmp_path/'public.orionvault'
    export_vault(tmp_path/'source',archive)
    restore_vault(archive,tmp_path/'restored',phrase)
    restored=Vault.open(tmp_path/'restored',phrase)
    try:
        assert [event.to_dict() for event in restored.ledger.events()]==before
        assert restored.raw.get(doc)==original
        restored.synchronize_read_store()
        with restored.read_store.open_reader() as revision:
            assert revision.documents_projection().captured_docs()=={doc:'pay_stub'}
            assert revision.connection.execute('SELECT event_id FROM document_classify_claims').fetchone()==(events[-1].event_id,)
        assert [event.to_dict() for event in restored.ledger.events()]==before
    finally:restored.close()


def test_owned_pages_and_legacy_reads_use_materialized_type_without_reparsing(library,monkeypatch):
    from viva.ledger.projection import coverage
    doc,events=saved_events();library.present.add(doc)
    library.events.append_atomically(lambda _:tuple(events));library.reads.synchronize(library.events)
    def forbidden(*args,**kwargs):
        raise AssertionError('serving a Documents read must not reparse classifier history')
    monkeypatch.setattr(coverage,'parse_classification',forbidden)
    assert read(library,selected_document_id=doc)['documents'][0]['doc_type']=='pay_stub'
    with library.reads.open_reader() as revision:
        queries=[];revision.connection.set_trace_callback(queries.append)
        assert revision.documents_projection().captured_docs()=={doc:'pay_stub'}
        revision.connection.set_trace_callback(None)
        assert not any('document_classify_responses' in query or 'document_classify_claims' in query for query in queries)
