"""Bounded current source-section attention, separate from human Questions."""
import json
import re
import sqlite3
import time
from .document_index import instrument_status,json_scalar
from .documents_page import DocumentsPageError

CONTRACT='instrument-document-review-v1'
LIMIT=50
MAX_SECONDS=2.0
MAX_BYTES=100000


def document_attention(revision):
    started=time.monotonic()
    connection=revision.connection
    unavailable={'contract_version':CONTRACT,'scope':'revision','state':'unavailable',
        'total_documents':None,'shown_count':0,'remaining_count':None,
        'unavailable_reason':'source_attention_unavailable','documents':[]}
    # The normalized state table contains only live accepted/held states. A
    # historical import receipt is deliberately not an attention predicate.
    predicate=f"""EXISTS(SELECT 1 FROM instrument_component_states s
        INDEXED BY instrument_components_by_document, json_each(CASE WHEN length(CAST(s.state_json AS BLOB))<=1000000 THEN CASE WHEN json_valid(s.state_json) THEN s.state_json ELSE '{{}}' END ELSE '{{}}' END,'$.components') c
        WHERE ({json_scalar('s.state_json','$.doc_id')})=d.doc_id
        AND s.source_sequence=(SELECT MAX(latest.source_sequence) FROM instrument_component_states latest WHERE latest.observation_id=s.observation_id)
        AND NOT EXISTS(SELECT 1 FROM instrument_observation_history newer INDEXED BY instrument_observations_by_prior WHERE newer.prior_id=s.observation_id)
        AND json_extract(c.value,'$.disposition') IN ('held','conflicted'))"""
    try:
        connection.set_progress_handler(lambda: int(time.monotonic()-started>MAX_SECONDS),1000)
        if connection.execute(f"SELECT 1 FROM instrument_component_states INDEXED BY instrument_components_by_document WHERE ({json_scalar('state_json','$.doc_id')}) IS NULL LIMIT 1").fetchone():raise DocumentsPageError('invalid_detail_evidence')
        total=connection.execute('SELECT COUNT(*) FROM document_library d WHERE '+predicate).fetchone()[0]
        keys=connection.execute('SELECT d.doc_id,CASE WHEN length(CAST(d.filename AS BLOB))<=4096 THEN d.filename END,d.identity_conflict FROM document_library d WHERE '+predicate+' ORDER BY d.first_sequence,d.doc_id LIMIT ?', (LIMIT,)).fetchall()
        documents=[]
        for doc_id,filename,conflict in keys:
            if time.monotonic()-started>MAX_SECONDS:raise DocumentsPageError('resource_limit')
            if re.fullmatch('[0-9a-f]{64}',doc_id) is None or type(filename) is not str or conflict:raise DocumentsPageError('invalid_detail_evidence')
            components,_,_=instrument_status(connection,doc_id)
            held=[component for component in components if component['disposition'] in ('held','conflicted')]
            if not held:raise DocumentsPageError('invalid_detail_evidence')
            documents.append({'document_id':doc_id,'filename':filename,'components':held})
        result={'contract_version':CONTRACT,'scope':'revision','state':'ready','total_documents':total,
            'shown_count':len(documents),'remaining_count':total-len(documents),'unavailable_reason':None,'documents':documents}
        if len(json.dumps(result,ensure_ascii=True).encode('utf-8'))>MAX_BYTES or time.monotonic()-started>MAX_SECONDS:raise DocumentsPageError('resource_limit')
        return result
    except (DocumentsPageError,sqlite3.DatabaseError,ValueError,TypeError,KeyError):
        return unavailable
    finally:
        connection.set_progress_handler(None,0)
