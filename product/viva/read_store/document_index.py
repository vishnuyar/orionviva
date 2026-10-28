"""Canonical Documents identities; capture history remains append-only."""

def json_scalar(column,path):
    # Nested CASE short-circuits before parsing oversized or malformed JSON.
    return f"CASE WHEN length(CAST({column} AS BLOB))<=1000000 THEN CASE WHEN json_valid({column}) THEN json_extract({column},'{path}') END END"

OBSERVATION_DOC_SQL=json_scalar('record_json','$.source.doc_id')
COMPONENT_DOC_SQL=json_scalar('state_json','$.doc_id')


def create_tables(connection):
    connection.execute("""CREATE TABLE read_acquisitions (
        source_sequence INTEGER PRIMARY KEY REFERENCES document_reads(source_sequence)
            DEFERRABLE INITIALLY DEFERRED CHECK(typeof(source_sequence)='integer' AND source_sequence>=0),
        doc_id TEXT NOT NULL CHECK(typeof(doc_id)='text'),
        event_id TEXT NOT NULL CHECK(typeof(event_id)='text'),
        source_record_hash TEXT NOT NULL CHECK(length(source_record_hash)=64 AND source_record_hash NOT GLOB '*[^0-9a-f]*'),
        kind TEXT NOT NULL CHECK(kind IN ('ordinary','local_curated')),
        local_contract TEXT,
        body_sha256 TEXT NOT NULL CHECK(length(body_sha256)=64 AND body_sha256 NOT GLOB '*[^0-9a-f]*'),
        authentication_tag TEXT NOT NULL CHECK(length(authentication_tag)=64 AND authentication_tag NOT GLOB '*[^0-9a-f]*'),
        CHECK((kind='ordinary' AND local_contract IS NULL) OR
              (kind='local_curated' AND local_contract='local-curation-v1')))""")
    connection.execute('CREATE INDEX read_acquisitions_by_document ON read_acquisitions(doc_id,source_sequence)')
    connection.execute('''CREATE TABLE document_library (
        doc_id TEXT PRIMARY KEY, first_sequence INTEGER NOT NULL,
        last_sequence INTEGER NOT NULL, filename TEXT NOT NULL,
        doc_type TEXT NOT NULL, identity_conflict INTEGER NOT NULL CHECK(identity_conflict IN (0,1)))''')
    connection.execute('CREATE UNIQUE INDEX document_library_order ON document_library(first_sequence,doc_id)')
    connection.execute('CREATE TABLE document_type_captures (doc_id TEXT PRIMARY KEY, raw_type TEXT NOT NULL, capture_event_id TEXT NOT NULL)')
    connection.execute('CREATE TABLE document_classify_responses (source_sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL, doc_id TEXT NOT NULL, extraction_id TEXT NOT NULL, phase TEXT NOT NULL, phase_attempt INTEGER NOT NULL, record_json TEXT NOT NULL)')
    connection.execute('CREATE INDEX document_classify_responses_by_phase ON document_classify_responses(doc_id,extraction_id,phase,phase_attempt,source_sequence)')
    connection.execute('CREATE TABLE document_classify_claims (source_sequence INTEGER PRIMARY KEY, event_id TEXT NOT NULL, doc_id TEXT NOT NULL, doc_type TEXT NOT NULL, confidence_json TEXT NOT NULL, receipt_ids_json TEXT NOT NULL)')
    connection.execute('CREATE INDEX document_classify_claims_by_document ON document_classify_claims(doc_id,source_sequence)')
    connection.execute(f"CREATE INDEX instrument_observations_by_document ON instrument_observation_history(({OBSERVATION_DOC_SQL}),source_sequence)")
    connection.execute('CREATE INDEX instrument_observations_by_prior ON instrument_observation_history(prior_id,source_sequence)')
    connection.execute('CREATE INDEX document_hold_resolution_by_doc ON document_hold_resolutions(doc_id,source_sequence DESC)')
    connection.execute(f"CREATE INDEX instrument_components_by_document ON instrument_component_states(({COMPONENT_DOC_SQL}),source_sequence DESC)")


def materialize_capture(connection, entry):
    event=entry.event
    if event.event_type!='DocumentCaptured' or not event.body.get('doc_id'):
        return
    body=event.body
    previous = connection.execute('SELECT raw_type FROM document_type_captures WHERE doc_id=?', (body['doc_id'],)).fetchone()
    raw_type = body.get('doc_type', '')
    connection.execute('''INSERT INTO document_library VALUES(?,?,?,?,?,0)
        ON CONFLICT(doc_id) DO UPDATE SET last_sequence=excluded.last_sequence,
        filename=excluded.filename,
        identity_conflict=(document_library.identity_conflict OR
            document_library.filename!=excluded.filename OR ?!=excluded.doc_type)''',
        (body['doc_id'],entry.sequence,entry.sequence,body.get('filename',''),raw_type,
         previous[0] if previous else raw_type))
    connection.execute('INSERT OR REPLACE INTO document_type_captures VALUES(?,?,?)',
                       (body['doc_id'],raw_type,event.event_id))
    _refresh_type(connection, body['doc_id'])


def _refresh_type(connection, doc_id):
    from ..ledger.projection.coverage import effective_type
    raw = connection.execute('SELECT raw_type FROM document_type_captures WHERE doc_id=?', (doc_id,)).fetchone()
    if raw is None:
        return
    claims = connection.execute('SELECT DISTINCT doc_type FROM document_classify_claims INDEXED BY document_classify_claims_by_document WHERE doc_id=?', (doc_id,)).fetchall()
    kind = effective_type(raw[0], claims)
    connection.execute('UPDATE document_library SET doc_type=? WHERE doc_id=?', (kind,doc_id))


def materialize_classification(connection, entry, owner):
    """Index classifier lineage only inside authenticated publication ownership."""
    import json
    from .store import ReadStore, ReadStoreError, _canonical
    from ..ledger.events import Event
    from ..ledger.projection.coverage import classified_claim
    if type(owner) is not ReadStore or owner._closed or not owner._owns_acquisition_writer(connection):
        raise ReadStoreError('classification writer scope is not active')
    event = entry.event
    body = event.body
    if event.event_type == 'ModelExtractionResponseRecorded':
        if body['phase'] == 'classify':
            connection.execute('INSERT INTO document_classify_responses VALUES(?,?,?,?,?,?,?)',
                (entry.sequence,event.event_id,body['doc_id'],body['extraction_id'],body['phase'],body['phase_attempt'],_canonical(event.to_dict()).decode()))
        return
    if event.event_type != 'ReadRecorded' or body.get('phase') != 'classify':
        return
    rows = connection.execute('''SELECT record_json FROM document_classify_responses
        INDEXED BY document_classify_responses_by_phase
        WHERE doc_id=? AND extraction_id=? AND phase=? AND phase_attempt=?
        ORDER BY source_sequence''',tuple(body.get(field) for field in ('doc_id','extraction_id','phase','phase_attempt'))).fetchall()
    responses = [Event.from_dict(json.loads(row[0])) for row in rows]
    claim = classified_claim(event, responses)
    if claim is None:
        return
    kind,confidence,links = claim
    connection.execute('INSERT INTO document_classify_claims VALUES(?,?,?,?,?,?)',
        (entry.sequence,event.event_id,body['doc_id'],kind,json.dumps(confidence),_canonical(links).decode()))
    _refresh_type(connection, body['doc_id'])



def instrument_status(connection,doc_id):
    """Read closed component words and explicit correction/retraction frontiers.

    No financial values are recomputed and absence never means retraction.
    """
    import json
    from ..ledger.instruments import decode,decode_change
    from .document_sections import component_view,OBSERVATIONS
    from ..ingest.instrument_effects import InstrumentComponentState
    from .documents_page import DocumentsPageError
    records=connection.execute(f"""SELECT observation_id,CASE WHEN length(CAST(state_json AS BLOB))<=1000000 THEN state_json END
        FROM instrument_component_states INDEXED BY instrument_components_by_document
        WHERE ({COMPONENT_DOC_SQL})=?
        AND source_sequence=(SELECT MAX(latest.source_sequence) FROM instrument_component_states latest WHERE latest.observation_id=instrument_component_states.observation_id)
        AND NOT EXISTS(SELECT 1 FROM instrument_observation_history newer INDEXED BY instrument_observations_by_prior WHERE newer.prior_id=instrument_component_states.observation_id)
        ORDER BY source_sequence DESC LIMIT 33""",(doc_id,)).fetchall()
    if len(records)>32:raise DocumentsPageError('detail_resource_limit')
    components=[]
    try:
        for observation_id,encoded in records:
            if type(encoded) is not str:raise ValueError()
            state=decode(json.loads(encoded),InstrumentComponentState)
            if state.doc_id!=doc_id or state.effective.source.doc_id!=doc_id:raise ValueError()
            record=connection.execute('SELECT CASE WHEN length(CAST(record_json AS BLOB))<=1000000 THEN record_json END FROM instrument_observation_history WHERE observation_id=?',(observation_id,)).fetchone()
            if record is None or type(record[0]) is not str:raise ValueError()
            change=decode_change(json.loads(record[0]))
            if change.source.doc_id!=doc_id or change.operation.value=='retract':raise ValueError()
            for component in state.components:
                if len(components)>=128 or len(component.component.encode('utf-8'))>4096:raise ValueError()
                view=component_view(component,change.payload,doc_id,state.source)
                view['effective_date']=state.effective.value
                components.append(view)
        seeds=connection.execute(f"""SELECT observation_id,kind,{json_scalar('record_json','$.source.page')} FROM instrument_observation_history
            INDEXED BY instrument_observations_by_document
            WHERE ({OBSERVATION_DOC_SQL})=? ORDER BY source_sequence LIMIT 33""",(doc_id,)).fetchall()
        if len(seeds)>32:raise ValueError()
        statuses=set();sections=[];steps=0
        for seed,kind,page in seeds:
            if kind not in OBSERVATIONS or type(page) is not int or not 1<=page<=200:raise ValueError()
            current=seed;visited=set();later=False
            while True:
                if type(current) is not str or not current or len(current.encode('utf-8'))>4096 or current in visited:raise ValueError()
                visited.add(current);steps+=1
                if steps>128:raise ValueError()
                frontier=connection.execute('SELECT operation FROM instrument_observation_history WHERE observation_id=?',(current,)).fetchone()
                if frontier is None or frontier[0] not in ('create','correct','retract'):raise ValueError()
                following=connection.execute("SELECT observation_id FROM instrument_observation_history INDEXED BY instrument_observations_by_prior WHERE prior_id=? LIMIT 2",(current,)).fetchall()
                if len(following)>1:raise ValueError()
                if not following:
                    lifecycle='retracted' if frontier[0]=='retract' else 'superseded' if later else 'active'
                    statuses.add(lifecycle)
                    sections.append({'kind':kind,'label':OBSERVATIONS[kind],'lifecycle':lifecycle,
                        'source_pages':[{'document_id':doc_id,'page':page,'label':f'Recorded source page {page}'}]})
                    break
                current=following[0][0];later=True
    except (TypeError,ValueError,KeyError):raise DocumentsPageError('invalid_detail_evidence') from None
    return components,sorted(statuses),sections


# One encoding is shared by the writer and both owned read contexts.
def acquisition_row_bytes(row):
    from .store import _canonical, ReadStoreError
    sequence, doc, event, source_hash, kind, contract, body_hash = row
    import re
    if (type(sequence) is not int or sequence < 0 or not isinstance(doc,str) or not doc
            or not isinstance(event,str) or not event
            or any(type(value) is not str or re.fullmatch('[0-9a-f]{64}',value) is None
                   for value in (source_hash,body_hash))
            or (kind,contract) not in (('ordinary',None),('local_curated','local-curation-v1'))):
        raise ReadStoreError('read acquisition selector has invalid fields')
    return _canonical(('viva-read-acquisition-row-v1', *row))


def materialize_read(connection, entry, owner):
    from .store import _canonical, ReadStoreError, ReadStore
    import hashlib
    if type(owner) is not ReadStore or owner._closed:
        raise ReadStoreError('read acquisition writer is not owned')
    if not owner._owns_acquisition_writer(connection):
        raise ReadStoreError('read acquisition writer scope is not active')
    body=entry.event.to_dict()['body']
    kind,contract='ordinary',None
    if 'acquisition' in body:
        from ..acquisition import local_read
        from ..sample.curation import decode_retained_input
        if not local_read(body):
            raise ReadStoreError('explicit acquisition metadata is invalid')
        decode_retained_input(body)
        kind,contract='local_curated','local-curation-v1'
    row=(entry.sequence,body['doc_id'],entry.event_id,entry.record_hash,
         kind,contract,hashlib.sha256(_canonical(body)).hexdigest())
    tag=owner._sign_acquisition_row(row,connection)
    connection.execute('INSERT INTO read_acquisitions VALUES(?,?,?,?,?,?,?,?)',(*row,tag))



READ_ACQUISITION_COLUMNS = ",a.source_sequence,a.doc_id,a.event_id,a.source_record_hash,a.kind,a.local_contract,a.body_sha256,a.authentication_tag,r.doc_id,r.source_sequence,e.event_id,e.record_hash,e.event_type,m.source_count,m.source_head,m.source_end_offset,m.source_cursor_mac "
READ_ACQUISITION_JOINS = " LEFT JOIN read_acquisitions a ON a.source_sequence=r.source_sequence LEFT JOIN applied_events e ON e.sequence=r.source_sequence JOIN projection_meta m ON m.singleton=1 "


from contextlib import contextmanager
from functools import wraps


@contextmanager
def acquisition_scope(context,account_id=None):
    from .store import _registered_acquisition_owner, _acquisition_owner
    owner,expected=_registered_acquisition_owner(context)
    depth=owner._acquisition_scopes.get(context,0)
    if account_id is not None:
        from .store import ReadStoreError
        key=(context,account_id)
        if key not in owner._acquisition_currencies:
            # The existing account-currency lookup is composed with a singleton
            # anchor: unknown accounts still return authenticated source metadata.
            row=context.connection.execute("""SELECT m.source_count,m.source_head,
                m.source_end_offset,m.source_cursor_mac,
                (SELECT currency FROM accounts INDEXED BY accounts_by_identity_source
                 WHERE account_id=? AND event_type='AccountOpened'
                 ORDER BY source_sequence DESC LIMIT 1)
                FROM projection_meta m WHERE m.singleton=1""",(account_id,)).fetchone()
            if row is None or tuple(row[:4])!=expected:
                raise ReadStoreError('read acquisition owned source revision differs')
            owner._acquisition_currencies[key]=(row[4] or '') or 'USD'
    elif not depth:
        _acquisition_owner(context)  # authoritative even when the SQL returns no rows
    owner._acquisition_scopes[context]=depth+1
    try:
        yield
    finally:
        if depth:
            owner._acquisition_scopes[context]=depth
        else:
            owner._acquisition_scopes.pop(context,None)
            for key in tuple(owner._acquisition_currencies):
                if key[0] is context: owner._acquisition_currencies.pop(key,None)
            for token,binding in tuple(owner._acquisition_witnesses.items()):
                if binding[0] is context: owner._acquisition_witnesses.pop(token,None)


def acquisition_scoped(function):
    @wraps(function)
    def wrapped(context,*args,**kwargs):
        with acquisition_scope(context):
            return function(context,*args,**kwargs)
    return wrapped


def account_acquisition_scoped(function):
    @wraps(function)
    def wrapped(context,account_id,*args,**kwargs):
        with acquisition_scope(context,account_id):
            return function(context,account_id,*args,**kwargs)
    return wrapped


def acquisition_currency(context,account_id):
    from .store import _registered_acquisition_owner,ReadStoreError
    owner,_expected=_registered_acquisition_owner(context)
    key=(context,account_id)
    if not owner._acquisition_scopes.get(context) or key not in owner._acquisition_currencies:
        raise ReadStoreError('account currency has no owned acquisition scope')
    return owner._acquisition_currencies[key]


class _OwnedReadWitness:
    pass


# Closed internal query contract: only the five reviewed owned SQL paths issue witnesses.
_OWNED_READ_QUERY_SHA256 = {'78fcb36bd236c5ac0782c900f8bfa8c38d7521b1f03e5030a068746732c93b73': 'point', 'd07ed54b3ea43e4e86c444a4e859a0207716351f55e3e333048124813fef88a0': 'detail', '6611e6f1edfcfabcbd56faf2e2c2ec3c5f0ba17480254a11a33f5c6615ad3619': 'overview', '4b698952fda38aa77a6d64b684b8f64dc44d5e054677aec35e07943634bdb009': 'statements', '08ee868aaf24d5b3d7c0a22830dc6c740b7261c317e25f43597055db61d98bc1': 'ownership'}


def _owned_query_operation(sql,parameters):
    from .store import ReadStoreError
    import hashlib,re
    if type(sql) is not str or type(parameters) is not tuple:
        raise ReadStoreError('read acquisition selection is not a closed owned SQL path')
    pattern=r'(WHERE p\.doc_id IN \()(\?(?:,\?)*)(\) AND p\.account_id<>\? )'
    matched=re.search(pattern,sql)
    width=matched[2].count('?') if matched else 0
    if width>400:
        raise ReadStoreError('read acquisition ownership parameters exceed their bound')
    template=re.sub(pattern,lambda match:match[1]+'?batch'+match[3],sql)
    operation=_OWNED_READ_QUERY_SHA256.get(hashlib.sha256(template.encode('utf-8')).hexdigest())
    if operation is None or len(parameters)!=sql.count('?'):
        raise ReadStoreError('read acquisition selection is not a closed owned SQL path')
    integer=lambda value: type(value) is int
    text=lambda value: type(value) is str
    valid=False
    if operation=='point':valid=len(parameters)==1 and integer(parameters[0]) and parameters[0]>=0
    elif operation=='detail':valid=len(parameters)==1 and text(parameters[0])
    elif operation=='overview':valid=(len(parameters)==2 and integer(parameters[0]) and 0<parameters[0]<=1000000
        and integer(parameters[1]) and 1<=parameters[1]<=10001)
    elif operation=='statements':valid=(len(parameters)==3 and integer(parameters[0]) and 0<parameters[0]<=1000000
        and text(parameters[1]) and integer(parameters[2]) and 1<=parameters[2]<=2001)
    elif operation=='ownership':valid=(1<=width<=400 and len(parameters)==width+3
        and integer(parameters[0]) and 0<parameters[0]<=1000000
        and all(text(value) for value in parameters[1:-1])
        and integer(parameters[-1]) and 1<=parameters[-1]<=2001)
    if not valid:
        raise ReadStoreError('read acquisition owned SQL path parameters are invalid')
    return operation



def owned_read_rows(context,sql,parameters):
    """Only the internal owned SQL path issues a witness for its exact joined row."""
    from .store import _registered_acquisition_owner, ReadStoreError
    owner,_expected=_registered_acquisition_owner(context)
    if not owner._acquisition_scopes.get(context):
        raise ReadStoreError('read acquisition selection has no owned scope')
    _owned_query_operation(sql,parameters)
    try:
        rows=context.connection.execute(sql,parameters).fetchall()
    except Exception as error:
        raise ReadStoreError('read acquisition owned SQL selection is unavailable') from error
    result=[]
    for row in rows:
        if len(row)<17:
            raise ReadStoreError('read acquisition owned query has incomplete binding')
        witness=_OwnedReadWitness()
        owner._acquisition_witnesses[witness]=(context,tuple(row[-17:]))
        result.append((*row[:-17],witness))
    return result


def retained_input(context,witness,doc_id,ordinary_reply,locale,currency):
    """Verify an actual owned query row before selecting any retained local body."""
    from .store import _registered_acquisition_owner, ReadStoreError
    import hashlib,json
    owner,expected=_registered_acquisition_owner(context)
    issued=owner._acquisition_witnesses.get(witness) if type(witness) is _OwnedReadWitness else None
    if (not owner._acquisition_scopes.get(context) or issued is None or issued[0] is not context):
        raise ReadStoreError('read acquisition joined-row witness is foreign or revoked')
    row=issued[1];sequence=row[9]
    if type(sequence) is not int or not 0<=sequence<expected[0] or tuple(row[13:])!=expected:
        raise ReadStoreError('read acquisition joined source revision differs')
    selected=tuple(row[:7]);tag=row[7]
    if (row[0]!=sequence or row[1]!=doc_id or row[8]!=doc_id or row[2]!=row[10]
            or row[3]!=row[11] or row[12]!='ReadRecorded'
            or not owner._verify_acquisition_row(selected,tag)):
        raise ReadStoreError('read acquisition selector authentication failed')
    if row[4]=='ordinary':
        return ordinary_reply,locale,currency,None
    raw=context.connection.execute("""SELECT CASE WHEN length(CAST(body_json AS BLOB))<=1000000
        THEN body_json END FROM document_reads WHERE source_sequence=?""",(sequence,)).fetchone()
    if raw is None or raw[0] is None:
        raise ReadStoreError('local read acquisition body exceeds its byte limit')
    text=raw[0]
    if hashlib.sha256(text.encode('utf-8')).hexdigest()!=row[6]:
        raise ReadStoreError('local read acquisition body hash mismatch')
    try:
        body=json.loads(text)
        from ..sample.curation import decode_retained_input
        reply=decode_retained_input(body)
        if body['doc_id']!=doc_id or body['response_text']!=ordinary_reply:
            raise ValueError('read columns differ from canonical body')
        return reply,body['normalization_locale'],body['source_currency'],body['acquisition']
    except Exception as error:
        raise ReadStoreError('local read acquisition retained context is invalid') from error


@acquisition_scoped
def read_input(context,sequence,doc_id,ordinary_reply,locale,currency):
    from .store import ReadStoreError
    rows=owned_read_rows(context,'SELECT r.source_sequence'+READ_ACQUISITION_COLUMNS+
        'FROM document_reads r'+READ_ACQUISITION_JOINS+'WHERE r.source_sequence=?',(sequence,))
    if len(rows)!=1:
        raise ReadStoreError('read acquisition selector source is missing')
    return retained_input(context,rows[0][-1],doc_id,ordinary_reply,locale,currency)



def retry_capture_identity(connection, document):
    """Selected identity scalars only; no response body or source replay."""
    row = connection.execute("""SELECT d.filename,
        CASE WHEN length(CAST(c.raw_type AS BLOB))<=4096 THEN c.raw_type END,
        CASE WHEN length(CAST(c.capture_event_id AS BLOB))<=4096 THEN c.capture_event_id END
        FROM document_library d JOIN document_type_captures c USING(doc_id)
        WHERE d.doc_id=? AND d.identity_conflict=0
        AND length(CAST(d.filename AS BLOB))<=4096""", (document,)).fetchone()
    if row is None: raise ValueError('capture_conflict')
    from ..ingest.pipeline_models import retained_capture_commitment
    return retained_capture_commitment(document, *row)
