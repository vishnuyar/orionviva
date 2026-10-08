"""Sourced measurements follow accepted document authority before value dates."""
import json
from decimal import Decimal
import pytest
from _tool_test_support import *
from test_financial_capability_answering import _answer


def _measurement_events():
    events = [account_opened('cash', 'depository', 'Example Checking', 'USD', '2026-01-01'),
              account_opened('loan', 'liability', 'Example Loan', 'USD', '2026-01-01'),
              account_opened('invest', 'investment', 'Example Investments', 'USD', '2026-01-01')]
    for account, doc, amount, kind in [('cash','cash-doc','100','bank_statement'),
                                       ('loan','loan-doc','30','loan_statement'),
                                       ('invest','invest-doc','50','brokerage_statement')]:
        reply = (_statement_reply('100','2026-01-01',amount,'2026-01-31') if account != 'invest' else json.dumps({
            'currency':'USD','as_of_raw':'2026-01-31','cash_raw':'50','total_raw':'200',
            'positions':[{'instrument':'Example Fund','units_raw':'3','market_value_raw':'150'}]}))
        events.extend([document_captured(doc, doc+'.pdf',100,kind,1,'2026-02-01'),
                       read_recorded(doc,'synthetic','fixture','text',reply,0,0,0,True,None,'2026-02-01'),
                       closing_balance_observed(account,amount,'2026-01-31',_p(doc),confirmed_by='human')])
    events.append(position_observed('invest','Example Fund','3','150','USD','2026-01-31',grade=VERIFIED,provenance=_p('invest-doc')))
    return events


def _measure_registry(extra=()):
    return default_registry(LedgerProjection([*_measurement_events(),*extra]),today='2026-02-01')


def _history(account='cash', **extra):
    return {'view':'account_value_history','account':account,'from':'2026-01-01','to':'2026-01-31',**extra}


def test_accepted_same_document_correction_removes_obsolete_date_before_window():
    reg = _measure_registry([closing_balance_observed('cash','90','2026-01-30',_p('cash-doc'),confirmed_by='human')])
    cash = reg.call('read_account_measurements',{'view':'recorded_cash','account':'cash'})
    assert cash.ok, cash.refusal
    assert [(f['value'],f['dated'],f['record_ids']) for f in cash.figures] == [('90','2026-01-30',['cash-doc'])]
    old = reg.call('read_account_measurements',_history(**{'from':'2026-01-31'}))
    assert not old.ok and old.refusal == 'account_history_unavailable'
    history = reg.call('read_account_measurements',_history())
    assert [(f['value'],f['dated']) for f in history.figures] == [('90','2026-01-30')]


def test_brokerage_cash_is_distinct_from_complete_common_source_total():
    reg = _measure_registry()
    cash = reg.call('read_account_measurements',{'view':'recorded_cash','account':'invest'})
    total = reg.call('read_account_measurements',_history('invest'))
    assert cash.ok and total.ok
    assert [(f['value'],f['quantity']) for f in cash.figures] == [('50','balance')]
    assert [(f['value'],f['dated'],f['record_ids']) for f in total.figures] == [('200','2026-01-31',['invest-doc'])]


def test_same_date_position_from_other_document_is_not_snapshot_proof():
    events = _measurement_events()
    events[-1] = position_observed('invest','Example Fund','3','150','USD','2026-01-31',grade=VERIFIED,provenance=_p('other-doc'))
    result = default_registry(LedgerProjection(events)).call('read_account_measurements',_history('invest'))
    assert not result.ok and result.refusal == 'incomplete_investment_snapshot'


@pytest.mark.parametrize('amount,ok',[('-1',False),('0',True),('30',True)])
def test_owed_sign_guard_preserves_zero(amount,ok):
    result = _measure_registry([closing_balance_observed('loan',amount,'2026-01-31',_p('loan-doc'))]).call('read_account_measurements',_history('loan'))
    assert result.ok is ok
    if ok: assert result.figures[0]['quantity'] == 'owed' and Decimal(result.figures[0]['value']) == Decimal(amount)
    else: assert result.refusal == 'owed_value_not_debt'


@pytest.mark.parametrize('extra',[{'from':'2026-01-01'},{'account':'Example Checking'},{'currency':''},{'anything':True}])
def test_recorded_cash_closed_direct_boundary(extra):
    from viva.tools.measurements import read_account_measurements
    result = read_account_measurements(LedgerProjection(_measurement_events()),{'view':'recorded_cash','account':'cash',**extra})
    assert not result.ok


def test_liability_is_not_cash_and_missing_cash_is_not_zero():
    reg = _measure_registry()
    assert reg.call('read_account_measurements',{'view':'recorded_cash','account':'loan'}).refusal == 'cash_account_ineligible'
    assert reg.call('read_account_measurements',{'view':'recorded_cash','account':'cash','currency':'EUR'}).refusal == 'cash_measurement_unavailable'


def test_statement_coverage_has_document_sources_and_clipped_uncovered_intervals():
    result = _measure_registry().call('read_statement_coverage',{'account':'cash','from':'2025-12-30','to':'2026-02-02'})
    assert result.ok, result.refusal
    assert result.record_ids == ['cash-doc']
    assert result.covers == [{'account':'cash','from':'2026-01-01','to':'2026-01-31'}]
    assert result.data['uncovered'] == [{'from':'2025-12-30','to':'2025-12-31'},{'from':'2026-02-01','to':'2026-02-02'}]
    assert result.figures[0]['kind'] == 'activity' and result.figures[0]['quantity'] == 'count'
    assert 'does not prove' in ' '.join(result.caveats)
    snapshot = _measure_registry().call('read_statement_coverage',{'account':'invest','from':'2026-01-01','to':'2026-01-31'})
    assert snapshot.refusal == 'statement_coverage_unavailable'


@pytest.mark.parametrize('family,params',[('recorded_cash',{'account_phrase':'cash'}),('account_value_history',{'account_phrase':'cash','from':'2026-01-01','to':'2026-01-31'}),('statement_period_coverage',{'account_phrase':'cash','from':'2026-01-01','to':'2026-01-31'})])
def test_measurement_families_deliver_sourced_answer(family,params):
    answer, execution = _answer(family,params,registry=_measure_registry())
    assert answer.result.answered, answer.result.text
    assert answer.result.figures and all(f['record_ids'] for f in answer.result.figures)


def test_history_exact_fifty_bound_and_fifty_one_refusal():
    import datetime
    events=[account_opened('cash','depository','Example Cash','USD','2025-01-01')]
    for i in range(51):
        day=(datetime.date(2025,1,1)+datetime.timedelta(days=i)).isoformat(); source='history-'+str(i)
        events.extend([document_captured(source,'history.pdf',100,'bank_statement',1,day),
                       closing_balance_observed('cash',str(i),day,_p(source))])
    reg=default_registry(LedgerProjection(events))
    fifty=reg.call('read_account_measurements',{'view':'account_value_history','account':'cash','from':'2025-01-01','to':'2025-02-19'})
    assert fifty.ok and len(fifty.figures)==len(fifty.data['measurements'])==50
    assert len(json.dumps(fifty.to_dict()).encode())<=50000
    fifty_one=reg.call('read_account_measurements',{'view':'account_value_history','account':'cash','from':'2025-01-01','to':'2025-02-20'})
    assert not fifty_one.ok and not fifty_one.figures and fifty_one.refusal=='history_row_limit'


def test_same_date_latest_source_order_wins_for_cash():
    events=_measurement_events()
    events.extend([document_captured('aaa-later','later.pdf',100,'bank_statement',1,'2026-02-02'),
                   closing_balance_observed('cash','80','2026-01-31',_p('aaa-later'))])
    result=default_registry(LedgerProjection(events)).call('read_account_measurements',{'view':'recorded_cash','account':'cash'})
    assert result.ok and result.figures[0]['value']=='80' and result.figures[0]['record_ids']==['aaa-later']


def test_removed_investment_holding_is_not_carried_into_next_snapshot():
    events=_measurement_events(); source='invest-new'
    reply=json.dumps({'currency':'USD','as_of_raw':'2026-02-28','cash_raw':'70','total_raw':'70','positions':[]})
    events.extend([document_captured(source,'new.pdf',100,'brokerage_statement',1,'2026-03-01'),
                   read_recorded(source,'synthetic','fixture','text',reply,0,0,0,True,None,'2026-03-01'),
                   closing_balance_observed('invest','70','2026-02-28',_p(source))])
    result=default_registry(LedgerProjection(events)).call('read_account_measurements',{'view':'account_value_history','account':'invest','from':'2026-02-01','to':'2026-02-28'})
    assert result.ok and [f['value'] for f in result.figures]==['70']


@pytest.mark.parametrize('family',['recorded_cash','account_value_history','statement_period_coverage'])
def test_named_measurements_keep_unique_ambiguous_and_absent_catalog_behavior(family):
    from viva.answer_program.intents import SemanticFamilyRegistry,SemanticRequest,SemanticOutcome
    from viva.answer_program import CapabilityManifest
    registry=_measure_registry(); families=SemanticFamilyRegistry(registry.semantic_entities())
    dates={'from':'2026-01-01','to':'2026-01-31'} if family!='recorded_cash' else {}
    request=SemanticRequest(family,{'account_phrase':'Example Checking',**dates},families.get(family).claims,families.catalog_digest)
    program=families.lower(SemanticOutcome('request',request),CapabilityManifest.from_registry(registry))
    assert program.nodes[0].args['account']=='cash'
    ambiguous=SemanticFamilyRegistry({'accounts':[{'id':'a','name':'Example Checking','kind':'depository'},
                                                {'id':'b','name':'Example Checking','kind':'depository'}]})
    assert ambiguous._named_account_outcome(SemanticOutcome('request',request)).kind=='clarify'
    absent=SemanticFamilyRegistry({'accounts':[]})
    assert absent._named_account_outcome(SemanticOutcome('request',request)).kind=='unsupported'


@pytest.mark.parametrize('key',['measurements','measurement_tools','projection_tools','position_projection',
    'current_period_projection','obligation_projection','goal_projection','brokerage_normalization',
    'arithmetic_verification','number_normalization','projection_facade',
    'answer_binding','answer_execution','answer_evidence','answer_validation','answer_contract_schema',
    'figure_envelope','claim_boundary','claim_shape','figure_binding','answer_delivery','evidence_ground',
    'arithmetic_tool','financial_quantity','financial_rendering'])
def test_each_measurement_projection_authority_change_changes_admission_digest(monkeypatch,key):
    import inspect
    from viva.answer_program.intents import SemanticFamilyRegistry
    before=SemanticFamilyRegistry()._admitted_implementation_digests()
    assert key in before
    from pathlib import Path
    original=Path.read_bytes
    def changed(path):
        data=original(path)
        import hashlib
        return data+b'\n# controlled authority counterfactual\n' if hashlib.sha256(data).hexdigest()[:16]==before[key] else data
    monkeypatch.setattr(Path,'read_bytes',changed)
    after=SemanticFamilyRegistry()._admitted_implementation_digests()
    assert after[key]!=before[key]
    assert {k:v for k,v in after.items() if k!=key}=={k:v for k,v in before.items() if k!=key}


def test_coverage_payload_limit_refuses_whole_result_without_truncation():
    import datetime
    events=[account_opened('cash','depository','Example Cash','USD','2025-01-01')]
    for i in range(70):
        start=(datetime.date(2025,1,1)+datetime.timedelta(days=i*2)).isoformat();source='interval-'+str(i)
        events.extend([document_captured(source,'interval.pdf',100,'bank_statement',1,start),
                       read_recorded(source,'synthetic','fixture','text',_statement_reply('100',start,'100',start),0,0,0,True,None,start),
                       closing_balance_observed('cash','100',start,_p(source))])
    from test_financial_capability_answering import _runtime_answer
    result=_runtime_answer('statement_period_coverage',{'account_phrase':'cash','from':'2025-01-01','to':'2025-05-31'},registry=default_registry(LedgerProjection(events)))
    assert result.outcome.tag=='coverage_payload_limit' and not result.result.figures
    assert all(item['label']==result.result.text for item in result.result.missing)


def test_account_metadata_currency_change_does_not_relabel_historical_sources():
    events=_measurement_events()
    events.extend([account_opened('cash','depository','Example Checking','EUR','2026-02-01'),
                   document_captured('eur-doc','eur.pdf',100,'bank_statement',1,'2026-03-01'),
                   closing_balance_observed('cash','200','2026-02-28',_p('eur-doc'))])
    proj=LedgerProjection(events); reg=default_registry(proj)
    jan=reg.call('read_account_measurements',_history(currency='USD'))
    assert jan.ok and jan.figures[0]['value']=='100' and jan.figures[0]['currency']=='USD'
    assert reg.call('read_account_measurements',{'view':'recorded_cash','account':'cash','currency':'EUR'}).figures[0]['value']=='200'
    incremental=LedgerProjection([])
    for event in events: incremental.apply(event)
    replay=default_registry(incremental).call('read_account_measurements',_history(currency='USD'))
    assert replay.figures==jan.figures


def test_generator_as_of_and_incremental_context_keep_historical_currency():
    events=_measurement_events()
    events.extend([account_opened('cash','depository','Example Checking','EUR','2026-02-01'),
                   closing_balance_observed('cash','90','2026-01-30',_p('cash-doc'))])
    reg=default_registry(LedgerProjection(event for event in events))
    conflict=reg.call('read_account_measurements',_history())
    assert conflict.refusal=='measurement_source_context_conflict' and not conflict.figures
    past=default_registry(LedgerProjection((event for event in events),as_of='2026-01-31'))
    # Future capture metadata is also absent at this horizon: not a measured zero.
    assert not past.call('read_account_measurements',_history()).ok
    events.append(account_opened('cash','depository','Example Checking','USD','2026-02-02',provenance=_p('cash-doc')))
    events.append(closing_balance_observed('cash','80','2026-01-30',_p('cash-doc')))
    resolved=default_registry(LedgerProjection(event for event in events)).call('read_account_measurements',_history())
    assert resolved.ok and resolved.figures[0]['currency']=='USD' and resolved.figures[0]['value']=='80'


def test_historical_source_kind_is_not_relabelled_with_current_account_type():
    events=_measurement_events()+[account_opened('cash','liability','Example Relationship','USD','2026-02-01')]
    result=default_registry(LedgerProjection(events)).call('read_account_measurements',_history())
    assert result.ok and result.figures[0]['quantity']=='balance'


def test_as_of_ignores_later_metadata_and_later_measurements_without_consuming_generator_twice():
    events=[account_opened('cash','depository','Example Cash','USD','2026-01-01'),
            document_captured('past','past.pdf',100,'bank_statement',1,'2026-01-01'),
            closing_balance_observed('cash','100','2026-01-31',_p('past')),
            account_opened('cash','depository','Example Cash','EUR','2026-02-01'),
            document_captured('future','future.pdf',100,'bank_statement',1,'2026-02-01'),
            closing_balance_observed('cash','200','2026-02-28',_p('future'))]
    past=LedgerProjection((event for event in events),as_of='2026-01-31')
    result=default_registry(past).call('read_account_measurements',_history())
    assert result.ok and [(f['value'],f['currency']) for f in result.figures]==[('100','USD')]
    for event in events[3:]: past.apply(event)
    assert default_registry(past).call('read_account_measurements',_history()).figures==result.figures


def test_cash_never_reinterprets_historical_liability_stock():
    events=[account_opened('changed','liability','Example Relationship','USD','2026-01-01'),
            document_captured('debt','debt.pdf',100,'loan_statement',1,'2026-01-01'),
            closing_balance_observed('changed','100','2026-01-31',_p('debt')),
            account_opened('changed','depository','Example Relationship','USD','2026-02-01')]
    result=default_registry(LedgerProjection(events)).call('read_account_measurements',{'view':'recorded_cash','account':'changed'})
    assert not result.ok and result.refusal=='cash_measurement_unavailable'


@pytest.mark.parametrize('family,params',[('recorded_cash',{'account_phrase':'cash'}),('account_value_history',{'account_phrase':'cash','from':'2026-01-01','to':'2026-01-31'})])
def test_each_delivered_measurement_has_its_actual_date_beside_amount(family,params):
    answer,_=_answer(family,params,registry=_measure_registry())
    assert answer.result.answered
    for item in answer.result.figures:
        assert item['dated'] in item['what']
        assert item['what'] in answer.result.text


def test_coverage_boundary_uses_held_account_name_without_changing_identity():
    from test_financial_capability_answering import _runtime_answer
    result=_runtime_answer('statement_period_coverage',{'account_phrase':'cash','from':'2025-12-30','to':'2026-02-02'},registry=_measure_registry())
    assert result.result.answered and 'only what is on Example Checking' in result.result.text
    assert result.result.figures[0]['boundary']['selected']==[{'kind':'account','value':'cash'}]


def _large_measurement_events(rows,label_length):
    import datetime,hashlib
    events=[account_opened('cash','depository','Example '+('A'*label_length),'USD','2025-01-01')]
    for index in range(rows):
        day=(datetime.date(2025,1,1)+datetime.timedelta(days=index)).isoformat()
        doc=hashlib.sha256(('measurement-'+str(index)).encode()).hexdigest()
        events.extend([document_captured(doc,'synthetic.pdf',100,'bank_statement',1,day),
                       closing_balance_observed('cash','100',day,_p(doc),confirmed_by='human')])
    return events


@pytest.mark.parametrize('family,rows,length,params,tag',[
    ('account_value_history',50,1024,{'from':'2025-01-01','to':'2025-02-19'},'history_payload_limit'),
    ('recorded_cash',1,51_000,{},'cash_payload_limit')])
def test_complete_measurement_payload_refuses_whole_large_details(family,rows,length,params,tag):
    from test_financial_capability_answering import _runtime_answer
    registry=default_registry(LedgerProjection(_large_measurement_events(rows,length)),today='2026-02-01')
    result=_runtime_answer(family,{'account_phrase':'cash',**params},registry=registry)
    assert result.result.status==result.outcome.status=='missing_data'
    assert result.outcome.tag==tag and not result.result.figures
    assert result.result.text==result.outcome.text
    assert all(item['label']==result.result.text and 'question' not in item for item in result.result.missing)


def test_fifty_normal_measurements_retain_complete_sources_and_size_bound():
    events=_large_measurement_events(50,12)
    registry=default_registry(LedgerProjection(events))
    result=registry.call('read_account_measurements',{'view':'account_value_history','account':'cash','from':'2025-01-01','to':'2025-02-19'})
    assert result.ok and len(result.figures)==50 and len(result.record_ids)==50
    assert len(json.dumps(result.to_dict()).encode())<=50_000


def test_delivered_history_distinguishes_every_recorded_date_and_value():
    from test_projection_tools import _projection_events
    registry=default_registry(LedgerProjection(_projection_events()))
    answer,_=_answer('account_value_history',{'account_phrase':'cash','from':'2025-11-01','to':'2026-01-31'},registry=registry)
    assert answer.result.answered
    assert [(item['value'],item['dated']) for item in answer.result.figures]==[('975','2025-11-28'),('950','2025-12-28'),('925','2026-01-28')]
    assert all(item['dated'] in item['what'] and item['what'] in answer.result.text for item in answer.result.figures)
