"""Composed read cost and instrument evidence bounds stay enforced."""
import json
import os
import re
from pathlib import Path
import time
from collections import Counter
import pytest

from viva.read_store import ReadStore,ReadStoreError
from viva.read_store import instrument_sql as instrument
from viva.surface.overview import overview
from test_read_store_overview import _source
from test_read_store_composition import _composition_events,PASSPHRASE
from test_instrument_projector_b import setup,bank,ingest,mortgage


def test_real_composed_overview_retains_existing_query_budget(tmp_path):
    source=_source(tmp_path,_composition_events())
    with ReadStore.create(tmp_path/'read',PASSPHRASE) as reads:
        reads.synchronize(source)
        traced=[];started=time.perf_counter()
        with reads.open_reader() as revision:
            revision.connection.set_trace_callback(traced.append)
            result=overview(revision.overview_projection(today='2026-05-01'),'en-US','2026-05-01')
            revision.connection.set_trace_callback(None)
        elapsed=time.perf_counter()-started
    selects=[s for s in traced if s.lstrip().upper().startswith(('SELECT','WITH'))]
    evidence={'operation':'open immutable reader, compose actual SQL Overview and surface',
        'select_count':len(selects),'seconds':elapsed,'selects':selects}
    path=Path(os.environ.get('INSTRUMENT_REPAIR2_EVIDENCE',str(tmp_path/'composed.json')))
    path.write_text(json.dumps(evidence,indent=2)+'\n')
    assert result is not None
    assert len(selects)<=78


class _FetchSpy:
    def __init__(self,connection,table,column):self.connection=connection;self.table=table;self.column=column;self.max_bytes=0;self.sql=[]
    def execute(self,sql,params=()):
        cursor=self.connection.execute(sql,params)
        if self.table not in sql:return cursor
        self.sql.append(sql)
        owner=self
        class Cursor:
            def fetchall(self):
                rows=cursor.fetchall()
                names=[d[0] for d in cursor.description]
                positions=[i for i,name in enumerate(names) if name==owner.column]
                if not positions:
                    positions=[i for i,name in enumerate(names) if re.search(r'\b'+re.escape(owner.column)+r'\b',name)]
                assert len(positions)==1,names
                owner.max_bytes=max([owner.max_bytes]+[len(row[positions[0]].encode('utf-8')) for row in rows if isinstance(row[positions[0]],str)])
                return rows
        return Cursor()


def fixture_read(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    reads=ReadStore.create(tmp_path/'read','synthetic-passphrase');reads.synchronize(ledger.store)
    return reads,ledger


def invoke(connection,kind):
    return {'observations':lambda:instrument.observation_history(connection),
        'families':lambda:instrument.restrictions(connection,'2021-12-31'),
        'allocations':lambda:instrument.allocations(connection,'2021-12-31'),
        'roles':lambda:instrument.cash_roles(connection)}[kind]()


@pytest.mark.parametrize('glyph',['X','雪'])
@pytest.mark.parametrize('kind,table,column,bound',[
    ('observations','instrument_observation_history','record_json',1_000_000),
    ('observations','instrument_observation_history','event_id',4096),
    ('families','instrument_family_history','account_id',4096),
    ('families','instrument_family_history','doc_id',4096),
    ('allocations','instrument_allocations','allocation_json',1_000_000),
    ('roles','instrument_cash_roles','role',4096),
])
def test_instrument_sql_refuses_oversize_before_fetch(tmp_path,glyph,kind,table,column,bound):
    reads,ledger=fixture_read(tmp_path)
    size=len(glyph.encode('utf-8'));value=glyph*((bound+1)//size)+'X'*((bound+1)%size)
    assert len(value.encode('utf-8'))==bound+1
    with reads:
        reads.publish(lambda c:c.execute(f'UPDATE {table} SET {column}=?',(value,)),copy_current=True)
        with reads.open_reader() as revision:
            spy=_FetchSpy(revision.connection,table,column);error=None
            try:invoke(spy,kind)
            except Exception as caught:error=caught
            assert spy.max_bytes<=bound,'oversized SQL text crossed into Python before refusal'
            assert isinstance(error,ReadStoreError),repr(error)
            assert 'byte bound' in str(error)
            assert any('length(CAST(' in sql for sql in spy.sql)


@pytest.mark.parametrize('kind,table,column,value',[
    ('observations','instrument_observation_history','record_json','{'),
    ('observations','instrument_observation_history','record_json','[]'),
    ('families','instrument_family_history','family','not_a_family'),
    ('families','instrument_family_history','account_id',''),
    ('allocations','instrument_allocations','allocation_json','{'),
    ('allocations','instrument_allocations','allocation_json','[]'),
    ('roles','instrument_cash_roles','role','not_a_role'),
])
def test_instrument_sql_malformed_inputs_produce_typed_refusal(tmp_path,kind,table,column,value):
    reads,ledger=fixture_read(tmp_path)
    with reads:
        reads.publish(lambda c:c.execute(f'UPDATE {table} SET {column}=?',(value,)),copy_current=True)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError):invoke(revision.connection,kind)


# Complete SQL frozen from the independently paired Source10 traces (count1/24),
# QUERY_CLASSIFICATION_FINDING SHA256
# 2a9364d1123148c53a9f9092e0082454b3ce2d290cce1e1e4a4a8e7156cb9da5.
# These fixtures are independent of production SQL and the trace being checked.
# The role join changes three existing posting reads; it adds no overlay read.
_AUDITED_FINANCIAL_OVERLAY_SQL = (
    'WITH allocated(source_sequence,allocation_json) AS (SELECT source_sequence,CASE WHEN length(CAST(all'
    'ocation_json AS BLOB))<=1000000 THEN allocation_json END FROM instrument_allocations WHERE effective'
    "<='9999-12-31' ORDER BY source_sequence LIMIT 10001),roles(source_sequence,movement_key,role) AS (SE"
    'LECT m.source_sequence,CASE WHEN m.movement_key IS NULL THEN NULL WHEN length(CAST(m.movement_key AS'
    ' BLOB))<=4096 THEN m.movement_key ELSE 1 END,CASE WHEN r.role IS NULL THEN NULL WHEN length(CAST(r.r'
    'ole AS BLOB))<=4096 THEN r.role ELSE 1 END FROM movements m JOIN instrument_cash_roles r ON r.source'
    "_sequence=m.source_sequence WHERE m.occurred_at<='9999-12-31' ORDER BY m.source_sequence,m.posting_i"
    "ndex LIMIT 10001) SELECT 'allocation',source_sequence,NULL,allocation_json FROM allocated UNION ALL "
    "SELECT 'role',source_sequence,movement_key,role FROM roles"
)
_AUDITED_RESTRICTION_OVERLAY_SQL = (
    'WITH families(source_sequence,account_id,family,event_id,doc_id,effective) AS (SELECT source_sequenc'
    'e,CASE WHEN account_id IS NULL THEN NULL WHEN length(CAST(account_id AS BLOB))<=4096 THEN account_id'
    ' ELSE 1 END,CASE WHEN family IS NULL THEN NULL WHEN length(CAST(family AS BLOB))<=4096 THEN family E'
    'LSE 1 END,CASE WHEN event_id IS NULL THEN NULL WHEN length(CAST(event_id AS BLOB))<=4096 THEN event_'
    'id ELSE 1 END,CASE WHEN doc_id IS NULL THEN NULL WHEN length(CAST(doc_id AS BLOB))<=4096 THEN doc_id'
    ' ELSE 1 END,CASE WHEN effective IS NULL THEN NULL WHEN length(CAST(effective AS BLOB))<=4096 THEN ef'
    "fective ELSE 1 END FROM instrument_family_history WHERE effective<='9999-12-31' ORDER BY source_sequ"
    'ence LIMIT 10001),observations(source_sequence,event_id,record_json) AS (SELECT source_sequence,CASE'
    ' WHEN event_id IS NULL THEN NULL WHEN length(CAST(event_id AS BLOB))<=4096 THEN event_id ELSE 1 END,'
    'CASE WHEN length(CAST(record_json AS BLOB))<=1000000 THEN record_json END FROM instrument_observatio'
    "n_history ORDER BY source_sequence LIMIT 10001) SELECT 'family',source_sequence,account_id,family,ev"
    "ent_id,doc_id,effective FROM families UNION ALL SELECT 'observation',source_sequence,event_id,record"
    '_json,NULL,NULL,NULL FROM observations'
)
_AUDITED_RHYTHM_POSTING_SQL = (
    'SELECT t.source_sequence,p.posting_index,CASE WHEN p.account_id IS NULL THEN NULL WHEN length(CAST(p'
    '.account_id AS BLOB))<=4096 THEN p.account_id ELSE 1 END,CASE WHEN t.occurred_at IS NULL THEN NULL W'
    'HEN length(CAST(t.occurred_at AS BLOB))<=4096 THEN t.occurred_at ELSE 1 END,CASE WHEN p.amount_text '
    'IS NULL THEN NULL WHEN length(CAST(p.amount_text AS BLOB))<=4096 THEN p.amount_text ELSE 1 END,CASE '
    'WHEN p.grade IS NULL THEN NULL WHEN length(CAST(p.grade AS BLOB))<=4096 THEN p.grade ELSE 1 END,CASE'
    ' WHEN t.description IS NULL THEN NULL WHEN length(CAST(t.description AS BLOB))<=4096 THEN t.descript'
    'ion ELSE 1 END,CASE WHEN t.provenance_doc_id IS NULL THEN NULL WHEN length(CAST(t.provenance_doc_id '
    'AS BLOB))<=4096 THEN t.provenance_doc_id ELSE 1 END,t.provenance_page,CASE WHEN t.provenance_region '
    'IS NULL THEN NULL WHEN length(CAST(t.provenance_region AS BLOB))<=4096 THEN t.provenance_region ELSE'
    ' 1 END,CASE WHEN t.provenance_note IS NULL THEN NULL WHEN length(CAST(t.provenance_note AS BLOB))<=4'
    "096 THEN t.provenance_note ELSE 1 END,CASE WHEN COALESCE(r.role,'') IS NULL THEN NULL WHEN length(CA"
    "ST(COALESCE(r.role,'') AS BLOB))<=4096 THEN COALESCE(r.role,'') ELSE 1 END FROM transactions t JOIN "
    'postings p ON p.source_sequence=t.source_sequence LEFT JOIN instrument_cash_roles r ON r.source_sequ'
    "ence=t.source_sequence WHERE t.occurred_at>='2011-01-24' AND t.occurred_at<='2021-01-31' ORDER BY t."
    'occurred_at,t.source_sequence,p.posting_index LIMIT 10001'
)


def _classify_instrument_queries(traced):
    overlays=[];postings=[]
    expected_overlays={_AUDITED_FINANCIAL_OVERLAY_SQL,_AUDITED_RESTRICTION_OVERLAY_SQL}
    for sql in traced:
        if not sql.lstrip().upper().startswith(('SELECT','WITH')):
            continue
        if not re.search(r'\binstrument_(?:allocations|family_history|observation_history|cash_roles)\b',sql,re.IGNORECASE):
            continue
        if sql==_AUDITED_RHYTHM_POSTING_SQL:
            postings.append(sql)
        else:
            assert sql in expected_overlays,('unrecognized instrument SQL',sql)
            overlays.append(sql)
    assert Counter(overlays)==Counter({sql:1 for sql in expected_overlays}),overlays
    assert len(postings)==3,postings
    return overlays


@pytest.mark.parametrize('mutation',[
    'extra_overlay','unbounded_role_join','near_miss_role_join',
    'unknown_role_statement','fourth_posting','unknown_replaces_overlay',
])
def test_instrument_query_classifier_rejects_unreviewed_reads(mutation):
    traced=[_AUDITED_FINANCIAL_OVERLAY_SQL,_AUDITED_RESTRICTION_OVERLAY_SQL,
        *([_AUDITED_RHYTHM_POSTING_SQL]*3)]
    if mutation=='extra_overlay':
        traced.append(_AUDITED_FINANCIAL_OVERLAY_SQL)
    elif mutation=='unbounded_role_join':
        traced[-1]=_AUDITED_RHYTHM_POSTING_SQL.removesuffix(' LIMIT 10001')
    elif mutation=='near_miss_role_join':
        traced[-1]=_AUDITED_RHYTHM_POSTING_SQL.replace(
            'r.source_sequence=t.source_sequence','r.source_sequence>=t.source_sequence')
    elif mutation=='unknown_role_statement':
        traced.append('SELECT role FROM instrument_cash_roles')
    elif mutation=='fourth_posting':
        traced.append(_AUDITED_RHYTHM_POSTING_SQL)
    elif mutation=='unknown_replaces_overlay':
        traced[0]='SELECT role FROM instrument_cash_roles'
    with pytest.raises(AssertionError):
        _classify_instrument_queries(traced)


@pytest.mark.parametrize('count',[1,24])
def test_nonempty_instrument_overlay_queries_are_constant_and_revision_scoped(tmp_path,count):
    from copy import deepcopy
    from decimal import Decimal
    from viva.ingest import ReadResult,capture_and_ingest
    from viva.ingest.statement import from_model_json
    from test_instrument_contracts import printed
    raw,ledger=setup(tmp_path)
    data={'doc_type':'checking_statement','doc_type_confidence':1,
        'institution':'Fixture Bank','account_ref':'Fixture Checking','account_names':['Synthetic Person'],
        'source_account_ref':'CHECK-A','source_account_ref_page':1,
        'opening':{'amount_raw':'100000','date_raw':'2021-01-01','page':1},
        'closing':{'amount_raw':str(100000-600*count),'date_raw':'2021-01-31','page':1},
        'transactions':[{'amount_raw':'600','balance_effect':'decrease','date_raw':'2021-01-15','page':1,
          'description':'Printed payment','source_reference':f'PAY-{i}','counterparty_reference':'LOAN-A'} for i in range(count)]}
    def read(blob,doc_id):
        facts,error=from_model_json(json.dumps(data),doc_id,'en-US','USD')
        assert error is None
        return ReadResult('checking_statement',1.0,facts)
    capture_and_ingest(raw,ledger,b'checking-multiple-payments',read)
    data=mortgage();data['opening_principal']=printed('100000');data['closing_principal']=printed(str(100000-100*count))
    principal,payment,deposit=(deepcopy(data['principal_movements'][0]),deepcopy(data['payments'][0]),deepcopy(data['escrow']['movements'][0]))
    data['principal_movements']=[];data['payments']=[];data['escrow']['movements']=[]
    for i in range(count):
        for template,rows in [(principal,data['principal_movements']),(payment,data['payments']),(deposit,data['escrow']['movements'])]:
            row=deepcopy(template);row['reference']=printed(f'PAY-{i}');rows.append(row)
    data['escrow']['closing']=printed(str(300*count))
    ingest(raw,ledger,'many-mortgage-payments',data,'mortgage_statement')
    assert len(ledger.projection().instrument_allocations())==count
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as reads:
        reads.synchronize(ledger.store)
        traced=[];started=time.perf_counter()
        with reads.open_reader() as revision:
            revision.connection.set_trace_callback(traced.append)
            projection=revision.overview_projection(today='2021-01-31')
            result=overview(projection,'en-US','2021-01-31')
            for _ in range(5):
                assert len(projection.instrument_allocations())==count
                assert len(projection.account_restrictions())==1
                movements=projection.movements()
                assert sum((m.component_spending or Decimal(0) for m in movements if m.component_spending is not None),Decimal(0))==200*count
            revision.connection.set_trace_callback(None)
        instrument_queries=_classify_instrument_queries(traced)
        assert len(instrument_queries)==2,instrument_queries
        assert result is not None
        (tmp_path/f'heavy-{count}.json').write_text(json.dumps({'count':count,'movements':len(movements),'instrument_selects':len(instrument_queries),'seconds':time.perf_counter()-started,'selects':traced},indent=2))
        # A fresh immutable generation/revision must execute and validate its own reads.
        reads.publish(lambda c:c.execute("UPDATE instrument_cash_roles SET role='corrupted'"),copy_current=True)
        with reads.open_reader() as current:
            with pytest.raises(ReadStoreError):current.instrument_allocations(as_of='9999-12-31')
        with pytest.raises(ReadStoreError):revision.instrument_allocations(as_of='9999-12-31')


def test_account_balance_cache_preserves_bounds_dates_defensive_copy_and_closed_lifetime(tmp_path):
    source=_source(tmp_path,_composition_events())
    with ReadStore.create(tmp_path/'read',PASSPHRASE) as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            original=revision._goal_account_balances(as_of='9999-12-31',limit=200)
            assert original
            original[next(iter(original))]['provenance'].clear()
            again=revision._goal_account_balances(as_of='9999-12-31',limit=200)
            assert any(row['provenance'] for row in again.values())
            with pytest.raises(ReadStoreError):revision._goal_account_balances(as_of='9999-12-31',limit=0)
            assert revision._goal_account_balances(as_of='1900-01-01',limit=200)=={}
        with pytest.raises(ReadStoreError):revision._goal_account_balances(as_of='9999-12-31',limit=200)


@pytest.mark.parametrize('mode',['restriction','overlay'])
def test_batched_snapshot_enforces_independent_row_probe_bounds(tmp_path,monkeypatch,mode):
    reads,_=fixture_read(tmp_path)
    with reads:
        with reads.open_reader() as revision:
            monkeypatch.setattr(instrument,'MAX_INSTRUMENT_HISTORY',0)
            with pytest.raises(ReadStoreError,match='row read bound'):
                (instrument.restriction_snapshot if mode=='restriction' else instrument.financial_overlay_snapshot)(revision.connection,'9999-12-31')


@pytest.mark.parametrize('mode,table,column',[
    ('restriction','instrument_observation_history','record_json'),
    ('restriction','instrument_family_history','doc_id'),
    ('overlay','instrument_allocations','allocation_json'),
    ('overlay','instrument_cash_roles','role'),
])
def test_revision_batched_reads_refuse_oversize_without_crossing_target_into_python(tmp_path,mode,table,column):
    reads,_=fixture_read(tmp_path);bound=1_000_000 if column.endswith('json') else 4096
    value='雪'*(bound//3+1)
    class Spy:
        def __init__(self,connection):self.connection=connection;self.saw=False
        def execute(self,sql,params=()):
            cursor=self.connection.execute(sql,params);owner=self
            class Cursor:
                def fetchall(self):
                    rows=cursor.fetchall();owner.saw=True
                    assert all(value not in row for row in rows),'oversized target crossed SQL boundary'
                    return rows
            return Cursor()
    with reads:
        reads.publish(lambda c:c.execute(f'UPDATE {table} SET {column}=?',(value,)),copy_current=True)
        with reads.open_reader() as revision:
            spy=Spy(revision.connection)
            with pytest.raises(ReadStoreError,match='byte bound'):
                (instrument.restriction_snapshot if mode=='restriction' else instrument.financial_overlay_snapshot)(spy,'9999-12-31')
            assert spy.saw


@pytest.mark.parametrize('glyph',['X','雪'])
def test_allocation_valid_exact_utf8_boundary_and_one_byte_over(tmp_path,glyph):
    reads,_=fixture_read(tmp_path)
    with reads:
        with reads.open_reader() as revision:
            row=revision.connection.execute('SELECT source_sequence,allocation_json FROM instrument_allocations LIMIT 1').fetchone()
            data=json.loads(row[1]);data['payment']['reference']['value']=''
            base=json.dumps(data,ensure_ascii=False,separators=(',',':'))
            remaining=instrument.MAX_INSTRUMENT_RECORD_BYTES-len(base.encode('utf-8'))
            width=len(glyph.encode('utf-8'));data['payment']['reference']['value']=glyph*(remaining//width)+'X'*(remaining%width)
            encoded=json.dumps(data,ensure_ascii=False,separators=(',',':'))
            assert len(encoded.encode('utf-8'))==instrument.MAX_INSTRUMENT_RECORD_BYTES
        reads.publish(lambda c:c.execute('UPDATE instrument_allocations SET allocation_json=? WHERE source_sequence=?',(encoded,row[0])),copy_current=True)
        with reads.open_reader() as revision:
            assert len(revision.instrument_allocations(as_of='9999-12-31'))==1
        data['payment']['reference']['value']+='X';oversized=json.dumps(data,ensure_ascii=False,separators=(',',':'))
        reads.publish(lambda c:c.execute('UPDATE instrument_allocations SET allocation_json=? WHERE source_sequence=?',(oversized,row[0])),copy_current=True)
        with reads.open_reader() as revision:
            with pytest.raises(ReadStoreError,match='byte bound'):revision.instrument_allocations(as_of='9999-12-31')


def test_new_restriction_voice_is_closed_and_all_released_words_are_unchanged():
    from viva import persona
    root=Path(persona.__file__).parent
    old=json.loads((root/'pack-v53/moments.json').read_text())
    current=json.loads((root/'pack-v54/moments.json').read_text())
    assert persona.ACTIVE_PACK=='pack-v62'
    assert set(current)-set(old)=={'current_period_exclusion_restricted'}
    assert all(current[key]==value for key,value in old.items())
    assert persona.MOMENT_FIELDS['current_period_exclusion_restricted']==frozenset()
    assert persona.moment('current_period_exclusion_restricted')=='Funds with restricted or unconfirmed availability are excluded from liquid funds for this view.'
    for name in ['phrasings.json','tone.md']:
        assert (root/'pack-v54'/name).read_bytes()==(root/'pack-v53'/name).read_bytes()


@pytest.mark.parametrize('status',['accepted','missing','conflicted'])
def test_restriction_exclusion_copy_truthfully_renders_all_fail_closed_states(monkeypatch,status):
    from types import SimpleNamespace
    from viva.ledger import LedgerProjection
    from viva.ledger.instruments import AccountRestriction
    from test_instrument_availability_selectors import _events,DAY
    from viva.surface.current_period import _exclusion
    import viva.ledger.instruments as instruments
    mapping={account:AccountRestriction(family,restriction if status=='accepted' else '',status,(),(),DAY)
        for account,family,restriction in [('deposit','term_deposit','restricted_term_deposit'),('escrow','escrow','restricted_escrow')]}
    monkeypatch.setattr(instruments,'account_restrictions',lambda core:mapping)
    projection=LedgerProjection(_events())
    rows=[row for row in projection.current_period(DAY).slices[0].exclusions if row.reason=='account_restricted']
    assert {row.identity for row in rows}=={'deposit','escrow'}
    for row in rows:
        view=_exclusion(projection,row)
        assert view.reason=='account_restricted'
        assert view.sentence=='Funds with restricted or unconfirmed availability are excluded from liquid funds for this view.'
