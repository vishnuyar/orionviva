"""Bounded indexed Documents data and independent selected detail.

Human-facing composition belongs to surface.documents_page.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import re
import time

CONTRACT='documents-page-v1'
PAGE_SIZE=50
MAX_HYDRATED=51
MAX_RESPONSE_BYTES=100000
MAX_SECONDS=2.0
MAX_CURSOR_BYTES=4096
MAX_SCALAR_BYTES=4096
MAX_DETAIL_HISTORY=10000

class DocumentsPageError(ValueError):
    def __init__(self,reason):
        self.reason=reason
        super().__init__(reason)


def parameters(value):
    if type(value) is not dict or set(value)-{'contract_version','cursor','selected_document_id'}:
        raise DocumentsPageError('invalid_parameters')
    if value.get('contract_version')!=CONTRACT or type(value.get('contract_version')) is not str:
        raise DocumentsPageError('unsupported_contract')
    if 'cursor' in value and (type(value['cursor']) is not str or len(value['cursor'].encode('utf-8'))>MAX_CURSOR_BYTES):
        raise DocumentsPageError('invalid_cursor')
    if 'selected_document_id' in value and (type(value['selected_document_id']) is not str or re.fullmatch('[0-9a-f]{64}',value['selected_document_id']) is None):
        raise DocumentsPageError('invalid_selected_identity')
    return dict(value)


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def _encode(body,secret):
    raw=_canonical({'body':body,'mac':hmac.new(secret,_canonical(body),hashlib.sha256).hexdigest()})
    token=base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(token.encode('utf-8'))>MAX_CURSOR_BYTES:raise DocumentsPageError('resource_limit')
    return token


def _decode(token,scope,secret):
    try:
        if type(token) is not str or not 0<len(token.encode('utf-8'))<=MAX_CURSOR_BYTES or re.fullmatch('[A-Za-z0-9_-]+',token) is None:raise ValueError
        raw=base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True)
        envelope=json.loads(raw)
        if type(envelope) is not dict or set(envelope)!={'body','mac'}:raise ValueError
        body=envelope['body']
        if type(body) is not dict or set(body)!={'scope','last','served'} or type(envelope['mac']) is not str:raise ValueError
        if not hmac.compare_digest(envelope['mac'],hmac.new(secret,_canonical(body),hashlib.sha256).hexdigest()):raise ValueError
        if raw!=_canonical(envelope) or base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')!=token:raise ValueError
        if type(body['served']) is not int or body['served']<1:raise ValueError
        if type(body['last']) is not list or len(body['last'])!=2 or type(body['last'][0]) is not int or body['last'][0]<0 or type(body['last'][1]) is not str:raise ValueError
        if re.fullmatch('[0-9a-f]{64}',body['last'][1]) is None:raise ValueError
    except Exception:raise DocumentsPageError('invalid_cursor') from None
    if body['scope']!=scope:raise DocumentsPageError('stale_cursor')
    return body['last'],body['served']


def _flags(connection,doc_id):
    # EXISTS probes are indexed by exact identity, never a Python history fold.
    return connection.execute('''SELECT
      EXISTS(SELECT 1 FROM document_reads WHERE doc_id=?),
      EXISTS(SELECT 1 FROM document_reads WHERE doc_id=? AND phase='extract' AND parse_ok=1),
      EXISTS(SELECT 1 FROM posted_document_events WHERE doc_id=?),
      EXISTS(SELECT 1 FROM document_holds WHERE doc_id=? AND event_type='StatementHeld' AND reason!='activity'),
      COALESCE((SELECT MAX(source_sequence) FROM document_holds WHERE doc_id=? AND (event_type='BrokerageActivityHeld' OR reason='activity')),-1)>
      COALESCE((SELECT MAX(source_sequence) FROM document_hold_resolutions WHERE doc_id=?),-1)''',(doc_id,)*6).fetchone()


def _hydrate_record(revision,key,raw,locale):
    connection=revision.connection
    record=connection.execute('''SELECT
        CASE WHEN length(CAST(filename AS BLOB))<=? THEN filename END,
        CASE WHEN length(CAST(doc_type AS BLOB))<=? THEN doc_type END,
        identity_conflict FROM document_library WHERE doc_id=?''',
        (MAX_SCALAR_BYTES,MAX_SCALAR_BYTES,key)).fetchone()
    if record is None:return None
    if any(value is None for value in record):raise DocumentsPageError('detail_resource_limit')
    filename,doc_type,conflict=record
    if conflict:return {'id':key,'filename':filename,'doc_type':doc_type,'identity_conflict':True}
    acquisition = {}
    from .document_index import owned_read_rows,retained_input,READ_ACQUISITION_COLUMNS,READ_ACQUISITION_JOINS
    sources = owned_read_rows(revision,"SELECT r.source_sequence,"
        "CASE WHEN length(CAST(r.response_text AS BLOB))<=1000000 THEN r.response_text END"+
        READ_ACQUISITION_COLUMNS+"FROM document_reads r"+READ_ACQUISITION_JOINS+
        "WHERE r.doc_id=? ORDER BY r.source_sequence DESC LIMIT 1",(key,))
    if sources:
        source=sources[0]
        from .store import ReadStoreError
        try:
            _reply,_locale,_currency,metadata=retained_input(revision,source[2],key,source[1],locale,'USD')
        except ReadStoreError as error:
            raise DocumentsPageError('detail_acquisition_unavailable') from error
        if metadata is not None: acquisition={'acquisition':metadata}
    attempted,parsed,posted,held,activity=_flags(connection,key)
    # Prefetch bounded histories only for this identity; oversized evidence is
    # unavailable, not silently truncated to a convenient contribution.
    contribution={}
    count=connection.execute('''SELECT COUNT(*) FROM (SELECT 1 FROM statement_periods
        INDEXED BY statement_periods_by_document_source WHERE doc_id=? LIMIT ?)''',(key,MAX_DETAIL_HISTORY+1)).fetchone()[0]
    if count>MAX_DETAIL_HISTORY:raise DocumentsPageError('detail_resource_limit')
    period=connection.execute('''SELECT
        CASE WHEN length(CAST(account_id AS BLOB))<=? THEN account_id END,
        CASE WHEN length(CAST(closing_amount_text AS BLOB))<=? THEN closing_amount_text END,
        CASE WHEN length(CAST(period_end AS BLOB))<=? THEN period_end END FROM statement_periods
        INDEXED BY statement_periods_by_document_source WHERE doc_id=? ORDER BY source_sequence DESC LIMIT 1''',
        (MAX_SCALAR_BYTES,MAX_SCALAR_BYTES,MAX_SCALAR_BYTES,key)).fetchall()
    if period:
        account,amount,dated=period[0]
        if any(type(x) is not str or len(x.encode('utf-8'))>MAX_SCALAR_BYTES for x in (account,amount,dated)):
            raise DocumentsPageError('detail_resource_limit')
        currency=connection.execute('SELECT CASE WHEN length(CAST(currency AS BLOB))<=4096 THEN currency END FROM accounts WHERE account_id=? AND currency IS NOT NULL ORDER BY source_sequence DESC LIMIT 1',(account,)).fetchone()
        contribution[key]={'account':account,'amount':amount,'as_of':dated,'currency':currency[0] if currency else ''}
    from .document_index import instrument_status
    components,observation_statuses,observation_sections=instrument_status(connection,key)
    unresolved=any(item["disposition"] in {"held","conflicted"} for item in components)
    snapshot='posted' if posted else 'held' if held else 'unavailable'
    activity_status='incomplete' if activity else 'complete' if doc_type=='brokerage_statement' and posted else 'unavailable' if doc_type=='brokerage_statement' else 'not_applicable'
    return {'id':key,'filename':filename,'doc_type':doc_type,'component_statuses':components,'observation_statuses':observation_statuses,'observation_sections':observation_sections,'resolved':bool(posted or held) and not unresolved,
        'raw_available':bool(raw.has(key)),'reading':'read' if parsed else 'read_yielded_nothing' if attempted else 'never_read',
        'snapshot_status':snapshot,'snapshot_attention':'partial' if unresolved and any(item['disposition']=='accepted' for item in components) else 'unresolved' if unresolved else '',
        'activity_status':activity_status,
        'contribution_data':contribution, **acquisition}



def _hydrate(revision,key,raw,locale):
    try:return _hydrate_record(revision,key,raw,locale)
    except DocumentsPageError as error:
        # Preserve the canonical row identity, with explicitly unavailable
        # evidence. Do not truncate or pretend an oversized detail is ready.
        return {'id':key,'filename':'','doc_type':'','detail_unavailable':error.reason}


def _row_summary(item):
    # A library row is explicitly incomplete evidence. Full closed source
    # sections belong only to the independently selected detail.
    result={key:value for key,value in item.items() if key not in {'component_statuses','observation_sections','observation_statuses'}}
    result['detail_requires_lookup']=True
    return result


def _read_page(revision,*,raw,secret,parameters_value,session_scope,locale='',reading_configured=False,started=None):
    started=time.monotonic() if started is None else started
    request=parameters(parameters_value)
    if type(secret) is not bytes or len(secret)<32:raise ValueError('Documents cursors require a private session key')
    if type(session_scope) is not str or re.fullmatch('[0-9a-f]{32}',session_scope) is None:raise ValueError('Documents require an explicit provider session')
    source=revision._store.authenticated_source_identity(revision)
    scope={'contract':CONTRACT,'surface':'documents','provider_session':session_scope,'order':1,'limit':PAGE_SIZE,'source':source,'generation':revision.generation}
    anchor=None;served=0
    if request.get('cursor'):anchor,served=_decode(request['cursor'],scope,secret)
    connection=revision.connection
    boundary=' WHERE (first_sequence,doc_id)>(?,?)' if anchor else ''
    keys=connection.execute('SELECT first_sequence,doc_id FROM document_library INDEXED BY document_library_order'+boundary+
        ' ORDER BY first_sequence,doc_id LIMIT ?',(*(anchor or ()),PAGE_SIZE+1)).fetchall()
    if any(type(row[1]) is not str or re.fullmatch('[0-9a-f]{64}',row[1]) is None for row in keys[:PAGE_SIZE]):
        raise DocumentsPageError('invalid_library_identity')
    shown=keys[:PAGE_SIZE];hydrated={}
    for _sequence,doc_id in shown:hydrated[doc_id]=_hydrate(revision,doc_id,raw,locale)
    selection={'state':'none','reason':None,'document':None}
    selected=request.get('selected_document_id')
    if selected:
        try:
            item=hydrated.get(selected)
            if selected not in hydrated:
                item=_hydrate(revision,selected,raw,locale)
                if item is not None:hydrated[selected]=item
            if item is None:selection={'state':'missing','reason':'identity_not_captured','document':None}
            elif item.get('detail_unavailable'):selection={'state':'unavailable','reason':item['detail_unavailable'],'document':None}
            elif item.get('identity_conflict'):selection={'state':'conflicted_identity','reason':'conflicting_capture_identity','document':None}
            else:
                item=dict(item)
                item['retry']=retained_retry_status(revision,item)
                selection={'state':'ready','reason':None,'document':item}
        except DocumentsPageError as error:selection={'state':'unavailable','reason':error.reason,'document':None}
        except Exception:selection={'state':'unavailable','reason':'detail_read_failed','document':None}
    total=None;total_reason=None;summary_counts=None;sentence=''
    try:
        counts=connection.execute('''SELECT COUNT(*),
          COALESCE(SUM(NOT EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id)),0),
          COALESCE(SUM(EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id) AND
            NOT EXISTS(SELECT 1 FROM document_reads r WHERE r.doc_id=d.doc_id AND phase='extract' AND parse_ok=1)),0),
          COALESCE(SUM(length(d.doc_id)!=64 OR d.doc_id GLOB '*[^0-9a-f]*'),0)
          FROM document_library d''').fetchone()
        total,never,yielded,invalid=counts
        if invalid:raise ValueError('invalid aggregate identity')
        summary_counts={'total_documents':total,'never_read':never,'read_yielded_nothing':yielded,'read':total-never-yielded}
        sentence=''
    except Exception:total=None;summary_counts=None;sentence='';total_reason='count_unavailable'
    next_served=served+len(shown)
    next_cursor=_encode({'scope':scope,'last':list(shown[-1]),'served':next_served},secret) if len(keys)>PAGE_SIZE and shown else None
    response={'contract_version':CONTRACT,'state':'ready','revision':{'generation':revision.generation,**source},
        'documents':[_row_summary(hydrated[row[1]]) for row in shown],'selected_document':selection,
        'page':{'total_documents':total,'total_unavailable_reason':total_reason,'page_start':served+1 if shown else 0,
            'page_end':next_served if shown else 0,'page_count':len(shown),'has_more':bool(next_cursor),'next_cursor':next_cursor},
        'summary':{'scope':'revision','counts':summary_counts,'unavailable_reason':total_reason},'reading_sentence':sentence}
    if selection['state']=='ready' and len(json.dumps(response,separators=(',',':'),sort_keys=True).encode('utf-8'))>MAX_RESPONSE_BYTES:
        response['selected_document']={'state':'unavailable','reason':'detail_resource_limit','document':None}
    if len(hydrated)>MAX_HYDRATED or len(json.dumps(response,separators=(',',':'),sort_keys=True).encode('utf-8'))>MAX_RESPONSE_BYTES or time.monotonic()-started>MAX_SECONDS:
        raise DocumentsPageError('resource_limit')
    # Publication may have advanced while detail/raw-presence work ran.
    try:
        if revision._store.authenticated_source_identity(revision)!=source:raise DocumentsPageError('stale_cursor')
    except DocumentsPageError:raise
    except Exception:raise DocumentsPageError('stale_cursor') from None
    if time.monotonic()-started>MAX_SECONDS:raise DocumentsPageError('resource_limit')
    return response


from .document_index import acquisition_scoped

@acquisition_scoped
def documents_page(revision,**kwargs):
    """Interrupt SQL work at the same complete-read budget as hydration."""
    started=kwargs.setdefault('started',time.monotonic())
    connection=revision.connection
    connection.set_progress_handler(lambda:int(time.monotonic()-started>MAX_SECONDS),1000)
    try:
        return _read_page(revision,**kwargs)
    except Exception as error:
        if time.monotonic()-started>MAX_SECONDS:raise DocumentsPageError('resource_limit') from None
        raise
    finally:connection.set_progress_handler(None,0)



def retained_retry_status(revision, item):
    """A bounded selected-only advisory; exact authentication belongs to admission."""
    result = dict(contract_version='retained-reading-v1', state='unavailable',
                  reason='evidence_unavailable', confirmation_token=None)
    def refuse(reason, state='blocked'):
        return {**result, 'state':state, 'reason':reason}
    key=item['id']; c=revision.connection
    from .store import CONTROL_SCHEMA_VERSION, PROJECTOR_VERSION
    version=c.execute('SELECT schema_version,projector_version FROM projection_meta WHERE singleton=1').fetchone()
    if version!=(CONTROL_SCHEMA_VERSION,PROJECTOR_VERSION):return refuse('evidence_unavailable','unavailable')
    if item.get('identity_conflict'): return refuse('capture_conflict')
    if not item.get('raw_available'): return refuse('missing_original')
    if item.get('component_statuses') or item.get('observation_statuses') or item.get('snapshot_status') in {'posted','held'}:
        return refuse('financial_review')
    provenance_count=c.execute('SELECT COUNT(*) FROM (SELECT 1 FROM event_provenance INDEXED BY event_provenance_by_document_source WHERE doc_id=? LIMIT ?)',(key,MAX_DETAIL_HISTORY+1)).fetchone()[0]
    if provenance_count>MAX_DETAIL_HISTORY:return refuse('evidence_unavailable','unavailable')
    if c.execute("""SELECT EXISTS(SELECT 1 FROM event_provenance p
        INDEXED BY event_provenance_by_document_source JOIN applied_events a ON a.sequence=p.source_sequence
        WHERE p.doc_id=? AND a.event_type NOT IN ('DocumentCaptured','ReadRecorded','ModelExtractionResponseRecorded'))""",(key,)).fetchone()[0]:
        return refuse('financial_review')
    if c.execute('SELECT EXISTS(SELECT 1 FROM document_account_history INDEXED BY document_accounts_by_doc WHERE doc_id=?)',(key,)).fetchone()[0]:
        return refuse('financial_review')
    for table in ('document_reads','extraction_responses'):
        index = 'document_reads_by_doc_date' if table=='document_reads' else 'extraction_responses_by_document_source'
        count=c.execute(f'SELECT COUNT(*) FROM (SELECT 1 FROM {table} INDEXED BY {index} WHERE doc_id=? LIMIT ?)',(key,MAX_DETAIL_HISTORY+1)).fetchone()[0]
        if count>MAX_DETAIL_HISTORY:return refuse('evidence_unavailable','unavailable')
    if c.execute("SELECT EXISTS(SELECT 1 FROM document_reads WHERE doc_id=? AND phase='extract' AND parse_ok=1)",(key,)).fetchone()[0]:
        return refuse('already_accepted')
    # JSON scalar probes never return response text/body to this route. Scope,
    # acknowledgement and complete link population are revalidated canonically.
    bad=c.execute("""SELECT EXISTS(SELECT 1 FROM document_reads WHERE doc_id=? AND
        (phase NOT IN ('classify','extract') OR
         (phase='classify' AND parse_ok!=1) OR
         json_type(body_json,'$.acquisition') IS NOT NULL OR
         json_type(body_json,'$.transport_complete') IS NOT 'true' OR
         json_type(body_json,'$.extraction_id') IS NOT 'text' OR
         json_extract(body_json,'$.extraction_id')='' OR
         json_type(body_json,'$.phase_attempt') IS NOT 'integer' OR
         json_type(body_json,'$.transport_receipt_ids') IS NOT 'array' OR
         json_array_length(body_json,'$.transport_receipt_ids')=0))""",(key,)).fetchone()[0]
    if bad:return refuse('uncertain_audit')
    orphan=c.execute("""SELECT EXISTS(SELECT 1 FROM extraction_responses x
        INDEXED BY extraction_responses_by_document_source WHERE x.doc_id=? AND NOT EXISTS
        (SELECT 1 FROM document_reads r INDEXED BY document_reads_by_doc_date,
         json_each(r.body_json,'$.transport_receipt_ids') link
         WHERE r.doc_id=x.doc_id AND r.source_sequence>x.source_sequence
         AND link.value=x.event_id))""",(key,)).fetchone()[0]
    missing=c.execute("""SELECT EXISTS(SELECT 1 FROM document_reads r
        INDEXED BY document_reads_by_doc_date,json_each(r.body_json,'$.transport_receipt_ids') link
        WHERE r.doc_id=? AND NOT EXISTS (SELECT 1 FROM extraction_responses x
        INDEXED BY extraction_responses_by_document_source WHERE x.doc_id=r.doc_id
        AND x.event_id=link.value AND x.source_sequence<r.source_sequence))""",(key,)).fetchone()[0]
    if orphan or missing:return refuse('uncertain_audit')
    return {**result,'state':'available','reason':'new_reading_available'}
