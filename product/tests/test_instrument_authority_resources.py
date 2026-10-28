from dataclasses import replace
from decimal import Decimal
from time import monotonic
from types import SimpleNamespace
import pytest
from viva.ingest import instrument_contracts as c
from viva.ingest.instrument_effects import InstrumentComponentState
from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
from viva.read_store.instrument_authority import read_instrument_authority
from viva.read_store.instrument_authority_contracts import InstrumentRequest
from viva.read_store.instrument_authority_sql import AuthoritySourceSnapshot


def snapshot(rows,observations=1):
    from datetime import date as calendar_date,timedelta
    source=c.Source('doc',1);date=c.SourcedDate('2021-03-22' if rows==81 else '2021-01-31',source)
    identity=c.AccountIdentity(c.SourcedText('Synthetic issuer',source),c.SourcedText('CD-A',source),c.SourcedText('Synthetic holder',source))
    movements=tuple(c.DepositMovement(c.DepositKind.INTEREST,c.Money(Decimal(1),'USD',source),c.SourcedDate((calendar_date(2021,1,1)+timedelta(days=index)).isoformat(),source) if rows==81 else date,c.SourcedText('reference-'+str(index),source)) for index in range(rows))
    payload=c.DepositFacts(identity,c.DepositSubtype.PERIODIC,c.SourcedDate('2021-01-01',source),date,
        c.Money(Decimal(100),'USD',source),c.Money(Decimal(100+rows),'USD',source),movements)
    changes=tuple(ObservationChange('observation-'+str(i),'CD-A',ObservationKind.DEPOSIT_COMPONENTS,date,Operation.CREATE,source,payload) for i in range(observations))
    states=tuple(InstrumentComponentState(change.observation_id,'doc',(c.ComponentResult('deposit_balance',c.Disposition.ACCEPTED),),source,date) for change in changes)
    return AuthoritySourceSnapshot(tuple({'change':change,'event_id':'event-'+change.observation_id,'superseded':False} for change in changes),states,())


@pytest.mark.parametrize('rows,observations',[(501,2),(81,1)])
def test_source_row_and_figure_limits_refuse_complete_result_without_partial_truncation(monkeypatch,rows,observations):
    import viva.read_store.instrument_authority as authority
    monkeypatch.setattr(authority,'account_currency',lambda *args:'USD')
    monkeypatch.setattr(authority,'source_snapshot',lambda *args:snapshot(rows,observations))
    result=read_instrument_authority(SimpleNamespace(generation='generation'),InstrumentRequest('period_components','CD-A','USD',
        start='2021-01-01',end='2021-03-22' if rows==81 else '2021-01-31',grouping='none',component_set='deposit'),deadline=monotonic()+2)
    assert result.dispositions[0].disposition=='resource_limit' and not result.figures


def test_expired_deadline_refuses_without_source_query(monkeypatch):
    import viva.read_store.instrument_authority_sql as sql
    revision=SimpleNamespace(generation='generation',connection=SimpleNamespace(execute=lambda *args:pytest.fail('deadline must precede SQL')))
    result=read_instrument_authority(revision,InstrumentRequest('terms','CD-A','USD',as_of='2021-01-31'),deadline=0)
    assert result.dispositions[0].disposition=='resource_limit'


@pytest.mark.parametrize('grouping,end',[('month','2022-01-01'),('year','2030-01-01')])
def test_group_count_bounds_apply_even_without_any_source_events(grouping,end):
    with pytest.raises(ValueError,match='resource_limit'):
        InstrumentRequest('period_components','CD-A','USD',start='2020-12-31',end=end,grouping=grouping,component_set='deposit')


@pytest.mark.parametrize('empty_months',[False,True])
def test_complete_year_monthly_endpoints_refuse_instead_of_truncating_and_half_year_fits(monkeypatch,empty_months):
    import calendar,json
    import viva.read_store.instrument_authority as authority
    from viva.ingest.instrument_parser import parse_instrument_json
    from test_instrument_projector_b import mortgage
    changes=[];states=[]
    for month in range(1,13):
        start=f'2021-{month:02d}-01';end=f'2021-{month:02d}-{calendar.monthrange(2021,month)[1]}'
        data=mortgage();data.update(start={'raw':start,'page':1},end={'raw':end,'page':1},
            opening_principal={'raw':str(10000-(month-1)*100),'page':1},closing_principal={'raw':str(10000-month*100),'page':1})
        for key in ('principal_movements','payments'):
            data[key][0].update(dated={'raw':f'2021-{month:02d}-15','page':1},reference={'raw':f'PAY-{month}','page':1})
        data['escrow'].update(opening={'raw':str((month-1)*200),'page':1},closing={'raw':str(month*200),'page':1})
        for index,movement in enumerate(data['escrow']['movements']):
            movement.update(dated={'raw':f'2021-{month:02d}-{15 if index==0 else 20}','page':1},
                reference={'raw':f'{"PAY" if index==0 else "TAX"}-{month}','page':1})
        if empty_months and month!=12:
            data['escrow']['movements']=data['escrow']['movements'][:1]
            data['escrow']['opening']={'raw':str((month-1)*300),'page':1}
            data['escrow']['closing']={'raw':str(month*300),'page':1}
        source=c.Source('month-'+str(month),1)
        payload=parse_instrument_json(json.dumps(data),'mortgage_statement',source.doc_id)
        change=ObservationChange('observation-'+str(month),'LOAN-A',ObservationKind.MORTGAGE_COMPONENTS,c.SourcedDate(end,source),Operation.CREATE,source,payload)
        changes.append({'change':change,'event_id':'event-'+str(month),'superseded':False})
        states.append(InstrumentComponentState(change.observation_id,source.doc_id,c.check_mortgage(payload),source,change.effective))
    monkeypatch.setattr(authority,'account_currency',lambda *args:'USD')
    monkeypatch.setattr(authority,'source_snapshot',lambda *args:AuthoritySourceSnapshot(tuple(changes),tuple(states),()))
    revision=SimpleNamespace(generation='generation')
    request=InstrumentRequest('period_components','LOAN-A','USD',start='2021-01-01',end='2021-12-31',grouping='month',component_set='payment_escrow')
    year=read_instrument_authority(revision,request,deadline=monotonic()+2)
    assert not year.figures and year.dispositions[0].disposition=='resource_limit'
    half=read_instrument_authority(revision,replace(request,end='2021-06-30'),deadline=monotonic()+2)
    assert len(half.figures)==54 and not any(d.disposition=='resource_limit' for d in half.dispositions)
    assert len([f for f in half.figures if f.claim=='escrow_opening_balance'])==6
    assert len([f for f in half.figures if f.claim=='escrow_closing_balance'])==6

    if empty_months:
        assert len([f for f in half.figures if f.claim=='tax_paid' and f.value=='0' and f.calculation_context=='accepted_empty_tax_event_set_v1'])==6
        december=read_instrument_authority(revision,replace(request,start='2021-12-01'),deadline=monotonic()+2)
        assert [(f.value,f.calculation_context) for f in december.figures if f.claim=='tax_paid']==[('100',None)]
    from dataclasses import asdict
    assert len(json.dumps(asdict(half),ensure_ascii=False,separators=(',',':')).encode())<50000


def _empty_tax_snapshot():
    import json
    from viva.ingest.instrument_parser import parse_instrument_json
    from test_instrument_projector_b import mortgage
    data=mortgage();data['escrow']['movements']=data['escrow']['movements'][:1]
    data['escrow']['closing']={'raw':'300','page':2}
    source=c.Source('tax-zero-source',1)
    payload=parse_instrument_json(json.dumps(data),'mortgage_statement',source.doc_id)
    change=ObservationChange('tax-zero-observation','LOAN-A',ObservationKind.MORTGAGE_COMPONENTS,c.SourcedDate('2021-01-31',source),Operation.CREATE,source,payload)
    state=InstrumentComponentState(change.observation_id,source.doc_id,c.check_mortgage(payload),source,change.effective)
    return change,state


@pytest.mark.parametrize('mutation',['none_array','held','missing_state','partial_source','wrong_currency','missing_amount','unknown_kind','duplicate_event','conflicting_witness','partial_request','missing_month'])
def test_empty_tax_month_refuses_incomplete_ambiguous_or_unaccepted_evidence(monkeypatch,mutation):
    import viva.read_store.instrument_authority as authority
    change,state=_empty_tax_snapshot();payload=change.payload;escrow=payload.escrow
    changes=[change];states=[state];start='2021-01-01';end='2021-01-31'
    if mutation=='none_array':escrow=replace(escrow,movements=None)
    if mutation=='held':states=[replace(state,components=(c.ComponentResult('escrow_balance',c.Disposition.HELD),))]
    if mutation=='missing_state':states=[]
    if mutation=='partial_source':payload=replace(payload,start=replace(payload.start,value='2021-01-02'))
    if mutation=='wrong_currency':escrow=replace(escrow,opening=replace(escrow.opening,currency='EUR'))
    if mutation=='missing_amount':escrow=replace(escrow,movements=(replace(escrow.movements[0],amount=None),))
    if mutation=='unknown_kind':escrow=replace(escrow,movements=(replace(escrow.movements[0],kind=None),))
    if mutation=='duplicate_event':escrow=replace(escrow,movements=escrow.movements*2)
    if mutation=='partial_request':start='2021-01-02'
    if mutation=='missing_month':end='2021-02-28'
    changes[0]=replace(change,payload=replace(payload,escrow=escrow))
    if mutation=='conflicting_witness':
        other=replace(change,observation_id='other-witness',payload=replace(payload,escrow=replace(escrow,movements=(replace(escrow.movements[0],reference=replace(escrow.movements[0].reference,value='DIFFERENT-EVENT')),))))
        changes.append(other);states.append(replace(state,observation_id=other.observation_id))
    monkeypatch.setattr(authority,'account_currency',lambda *args:'USD')
    monkeypatch.setattr(authority,'source_snapshot',lambda *args:AuthoritySourceSnapshot(tuple({'change':r} for r in changes),tuple(states),()))
    result=read_instrument_authority(SimpleNamespace(generation='generation'),InstrumentRequest('period_components','LOAN-A','USD',start=start,end=end,grouping='month',component_set='payment_escrow'),deadline=monotonic()+2)
    assert not [f for f in result.figures if f.claim=='tax_paid' and f.value=='0']


def test_empty_tax_month_pools_duplicate_witnesses_all_pages_and_independent_component(monkeypatch):
    import viva.read_store.instrument_authority as authority
    change,state=_empty_tax_snapshot()
    duplicate=replace(change,observation_id='duplicate-observation',source=c.Source('duplicate-document',3))
    # Payment/principal state is deliberately held: accepted escrow stays independent.
    state=replace(state,components=(c.ComponentResult('escrow_balance',c.Disposition.ACCEPTED),c.ComponentResult('principal_balance',c.Disposition.HELD)))
    monkeypatch.setattr(authority,'account_currency',lambda *args:'USD')
    monkeypatch.setattr(authority,'source_snapshot',lambda *args:AuthoritySourceSnapshot(tuple({'change':r} for r in (change,duplicate)),(state,replace(state,observation_id=duplicate.observation_id)),()))
    result=read_instrument_authority(SimpleNamespace(generation='generation'),InstrumentRequest('period_components','LOAN-A','USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='payment_escrow'),deadline=monotonic()+2)
    zero=next(f for f in result.figures if f.claim=='tax_paid')
    assert zero.value=='0' and zero.observation_ids==tuple(sorted((change.observation_id,duplicate.observation_id)))
    assert {(a.document_id,a.page) for a in result.anchors if a.anchor_id in zero.anchor_ids}=={('tax-zero-source',1),('tax-zero-source',2),('duplicate-document',3)}
    assert zero.component_ids==('escrow_balance',) and zero.grade=='corroborated'
    from dataclasses import asdict
    import json
    from pathlib import Path
    Path('/tmp/instrument-c-tax-zero-public-fixture.json').write_text(json.dumps(asdict(result),indent=2))
    with pytest.raises(ValueError,match='calculation context'):
        replace(zero,calculation_context='model_guess')
    with pytest.raises(ValueError,match='calculation context'):
        replace(zero,value='1')
