"""Full unchanged persona cardinalities at the bounded SQL selection seam."""
from collections import Counter
from dataclasses import replace
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
import json
import sqlite3
import pytest
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
from viva.ingest.instrument_effects import InstrumentComponentState
from viva.ingest.instrument_contracts import Source,SourcedDate,ComponentResult,Disposition
from viva.ingest.apr_context_contracts import AprContextPayload,AprContextResult
from viva.ledger.instruments import encode_change,encode
from viva.read_store.instrument_sql import create_tables
from viva.read_store.instrument_authority_sql import source_snapshot
from viva.read_store.instrument_authority_contracts import InstrumentRequest
from test_instrument_contracts import mortgage_json,printed


def test_actual_sixty_month_persona_scopes_effective_rows_and_latest_component_states():
    path=Path(__file__).parents[2]/'output/pdf/synthetic_life_5y/source-ledger.json'
    if not path.is_file():pytest.skip('campaign source ledger is not packaged with product')
    source=json.loads(path.read_text())
    documents=[d for d in source['documents'] if d['family']=='mortgage']
    assert len(documents)==60
    assert Counter(d['account_ref'] for d in documents)=={'LOAN-A':24,'LOAN-B':36}
    db=sqlite3.connect(':memory:')
    db.execute('CREATE TABLE applied_events(sequence INTEGER PRIMARY KEY)')
    create_tables(db)
    sequence=0;changes=[]
    def insert(change):
        nonlocal sequence
        sequence+=1
        db.execute('INSERT INTO instrument_observation_history VALUES(?,?,?,?,?,?,?,?,?)',(sequence,'event-'+str(sequence),
            change.observation_id,change.subject_id,change.kind.value,change.operation.value,change.prior_id,
            change.effective.value,json.dumps(encode_change(change))))
    for doc in documents:
        data=mortgage_json();data['start']=printed(doc['period_start']);data['end']=printed(doc['period_end'])
        data['identity']['account_reference']=printed(doc['account_ref'])
        data['terms']={'original_principal':printed(doc['facts']['original_principal']),
            'note_rate':printed(doc['facts']['nominal_note_rate'])}
        payload=parse_instrument_json(json.dumps(data),'mortgage_statement',doc['id'])
        change=ObservationChange(doc['id'],doc['account_ref'],ObservationKind.MORTGAGE_COMPONENTS,
            SourcedDate(doc['period_end'],Source(doc['id'],1)),Operation.CREATE,Source(doc['id'],1),payload)
        changes.append(change);insert(change)
        for field in ('status','context'):
            contextual=AprContextPayload(1,change.subject_id,change.observation_id,change.effective.value,field,
                AprContextResult('unavailable',reason='not_printed'),doc['id'],doc['id'])
            insert(ObservationChange(doc['id']+field,change.subject_id,ObservationKind.APR_CONTEXT,
                change.effective,Operation.CREATE,change.source,contextual))
        for healing in range(5):
            sequence+=1
            state=InstrumentComponentState(change.observation_id,doc['id'],(ComponentResult('mortgage_terms',Disposition.ACCEPTED),),change.source,change.effective)
            db.execute('INSERT INTO instrument_component_states VALUES(?,?,?,?)',
                (sequence,change.observation_id,change.effective.value,json.dumps(encode(state))))
    # A long correction stream is historical resource use, not 151 effective
    # observations. The live successor must still be selected for its period.
    prior=next(change for change in changes if change.subject_id=='LOAN-B')
    for index in range(150):
        change=replace(prior,observation_id='corrected-'+str(index),operation=Operation.CORRECT,prior_id=prior.observation_id)
        insert(change);prior=change
    revision=SimpleNamespace(connection=db,_closed=False,generation='test-generation')
    annual=InstrumentRequest('period_components','LOAN-B','USD',start='2025-01-01',end='2025-12-31',grouping='month',component_set='loan_principal')
    selected=source_snapshot(revision,annual,monotonic()+2)
    assert len(selected.observations)==12 and len(selected.component_states)==12
    assert all(row['change'].effective.value.startswith('2025') for row in selected.observations)
    terms=source_snapshot(revision,InstrumentRequest('terms','LOAN-B','USD',as_of='2025-12-31'),monotonic()+2)
    assert len(terms.observations)==3 and len(terms.component_states)==1
    january=source_snapshot(revision,replace(annual,start='2023-01-01',end='2023-01-31'),monotonic()+2)
    assert len(january.observations)==1 and january.observations[0]['change'].observation_id=='corrected-149'
    assert db.execute('SELECT COUNT(*) FROM instrument_observation_history').fetchone()[0]==330
    assert db.execute('SELECT COUNT(*) FROM instrument_component_states').fetchone()[0]==300
