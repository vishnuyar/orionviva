"""Existing projection inputs retain their limits while future values are hypothetical."""
import pytest
from decimal import Decimal
from _tool_test_support import *
from viva.ledger.events import goal_created,goal_funds_reserved
from test_financial_capability_answering import _answer,_runtime_answer


def _projection_events(amounts=None, merchant='Example Membership', category='other'):
    events=[account_opened('cash','depository','Example Checking','USD','2025-11-01')]
    opening=Decimal('1000')
    for month,amount in zip(('2025-11','2025-12','2026-01'),amounts or ('25','25','25')):
        source='projection-'+month; closing=opening-Decimal(amount)
        events.extend([document_captured(source,'synthetic.pdf',100,'bank_statement',1,month+'-28'),
            read_recorded(source,'synthetic','fixture','text',_statement_reply(str(opening),month+'-01',str(closing),month+'-28'),0,0,0,True,None,month+'-28'),
            opening_balance_observed('cash',opening,month+'-01',_p(source)),
            simple_transaction('cash',-Decimal(amount),merchant,month+'-15',provenance=_p(source)),
            closing_balance_observed('cash',closing,month+'-28',_p(source),confirmed_by='human')])
        opening=closing
    events.extend([merchant_enriched(merchant.lower(),category,attributes={'counterparty_kind':'business','billing':'standing','billing_period':'monthly'},occurred_at='2026-01-29'),
                   goal_created('g','Example Goal','USD','500','2026-01-29',target_date='2026-05-20',monthly_contribution='50',contribution_day=20),
                   goal_funds_reserved('g','cash','100','2026-01-30')])
    return events


def _projection_registry():
    return default_registry(LedgerProjection(_projection_events()),today='2026-02-01')


def test_known_remainder_preserves_reserves_ranges_stale_inputs_and_missing_spending():
    reg=_projection_registry()
    result=reg.call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok,result.text
    assert [(f['value'],f['kind'],f['grade']) for f in result.figures] == [('750','hypothetical',''),('750','hypothetical','')]
    data=result.data['slices'][0]
    assert data['reserved_for_goals']=='100' and data['goal_contributions']=='50'
    assert data['grade']=='verified' and '2026-01-28' in data['evidence_dates']
    assert data['missing_inputs']==['planned_spending'] and not data['completeness']['planned_spending']
    assert 'not spending permission' in ' '.join(result.caveats)
    delivered,_=_answer('known_remainder',{},registry=reg)
    assert delivered.result.answered and 'hypothetical' in delivered.result.text.lower()
    assert 'not spending permission' in delivered.result.text


def test_next_expectations_do_not_generate_more_occurrences_in_long_horizon():
    result=_projection_registry().call('read_financial_projections',{'view':'upcoming_obligations','horizon_days':'90'})
    assert result.ok,result.text
    assert len(result.data['next_expectations'])==1
    assert {f['dated'] for f in result.figures}=={'2026-02-15'}
    assert all(f['kind']=='hypothetical' and f['grade']=='' and f['record_ids'] for f in result.figures)
    assert result.data['next_expectations'][0]['grade']=='verified'
    assert 'not a full payment calendar' in ' '.join(result.caveats)
    delivered,_=_answer('upcoming_obligations',{'horizon_days':'90'},registry=_projection_registry())
    assert delivered.result.answered and 'not a full payment calendar' in delivered.result.text
    assert _projection_registry().call('read_financial_projections',{'view':'upcoming_obligations','horizon_days':'10'}).refusal=='no_upcoming_expectations'


def test_goal_progress_separates_recorded_local_terms_from_future_calculations():
    result=_projection_registry().call('read_financial_projections',{'view':'goal_progress'})
    assert result.ok,result.text
    assert {(f['value'],f['kind']) for f in result.figures}=={('500','activity'),('100','activity'),('400','hypothetical'),('50','activity'),('100.00','hypothetical')}
    assert all(not f['grade'] and f['record_ids'] for f in result.figures)
    assert result.data['goals'][0]['projected_completion_date']=='2026-09-20'
    delivered,_=_answer('goal_progress',{},registry=_projection_registry())
    assert delivered.result.answered and 'not a bank transfer' in delivered.result.text


@pytest.mark.parametrize('args',[{'view':'goal_progress','horizon_days':'30'},{'view':'known_remainder','horizon_days':30},{'view':'known_remainder','horizon_days':'0'},{'view':'known_remainder','horizon_days':'367'},{'view':'known_remainder','currency':''},{'view':'known_remainder','account':'cash'},{'view':'unknown'}])
def test_projection_direct_boundary_is_closed(args):
    from viva.tools.projections import read_financial_projections
    result=read_financial_projections(LedgerProjection(_projection_events()),args,today='2026-02-01')
    assert not result.ok and not result.figures


@pytest.mark.parametrize('family,tag',[('known_remainder','no_eligible_liquid_balance'),('upcoming_obligations','no_upcoming_expectations'),('goal_progress','no_recorded_goals')])
def test_empty_projection_is_actionable_missing_data_without_zero(family,tag):
    registry=default_registry(LedgerProjection([]),today='2026-02-01')
    result=_runtime_answer(family,{},registry=registry)
    assert result.result.status==result.outcome.status=='missing_data'
    assert result.result.refusal==result.outcome.tag==tag
    assert not result.result.figures
    assert all(item['label']==result.result.text and item['source']=='measurement' and 'question' not in item for item in result.result.missing)


def test_goal_payload_limit_has_an_applicable_remedy_and_no_hidden_subset():
    events=_projection_events()
    events.extend(goal_created('extra-'+str(i),'Example Goal '+str(i),'USD','100','2026-01-29') for i in range(9))
    result=_runtime_answer('goal_progress',{},registry=default_registry(LedgerProjection(events),today='2026-02-01'))
    assert result.outcome.tag=='goal_progress_payload_limit' and not result.result.figures
    assert 'shorter horizon' not in result.result.text and 'whole set' in result.result.text
    assert all(item['label']==result.result.text for item in result.result.missing)


@pytest.mark.parametrize('horizon',['0','367','-1','1.0','1e2'])
def test_semantic_horizon_uses_same_closed_boundary(horizon):
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.schema import ContractError
    families=SemanticFamilyRegistry()
    with pytest.raises(ContractError):
        families._validate_parameters(families.get('known_remainder').parameter_schema,{'horizon_days':horizon})


def test_debt_arrangement_next_occurrence_is_signed_movement_with_ordered_range():
    events=_projection_events(('25','30','35'),merchant='Example Loan',category='debt')
    registry=default_registry(LedgerProjection(events),today='2026-02-01')
    result=registry.call('read_financial_projections',{'view':'upcoming_obligations'})
    assert result.ok,result.text
    assert [(f['value'],f['quantity'],f['what']) for f in result.figures]==[
        ('-35','movement','lower expected outgoing cash movement — example loan — expected 2026-02-15'),
        ('-25','movement','upper expected outgoing cash movement — example loan — expected 2026-02-15')]
    assert result.data['next_expectations'][0]['amount_min']=='25'
    assert result.data['next_expectations'][0]['amount_max']=='35'
    assert all(f['kind']=='hypothetical' and f['record_ids'] and not f['grade'] for f in result.figures)
    delivered,_=_answer('upcoming_obligations',{},registry=registry)
    assert delivered.result.answered and all(f['quantity']=='movement' for f in delivered.result.figures)


def test_superseded_closing_never_becomes_a_projection_start():
    events=_projection_events()
    events.append(closing_balance_observed('cash','920','2026-01-27',_p('projection-2026-01'),confirmed_by='human'))
    result=_runtime_answer('known_remainder',{},registry=default_registry(LedgerProjection(events),today='2026-02-01'))
    assert result.outcome.tag=='projection_start_unavailable' and not result.result.figures
    assert all(item['label']==result.result.text for item in result.result.missing)


def test_missing_replayed_start_is_unavailable_but_sourced_zero_is_valid():
    events=[account_opened('cash','depository','Example Cash','USD','2026-01-01')]
    reg=default_registry(LedgerProjection(events),today='2026-02-01')
    assert reg.call('read_financial_projections',{'view':'known_remainder'}).refusal=='projection_start_unavailable'
    events.extend([document_captured('zero','zero.pdf',100,'bank_statement',1,'2026-01-01'),
                   closing_balance_observed('cash','0','2026-01-31',_p('zero'),confirmed_by='human')])
    measured=default_registry(LedgerProjection(events),today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert measured.ok and all(f['value']=='0' and f['record_ids']==['zero'] for f in measured.figures)


def test_currency_narrowing_precedes_start_consistency_guard():
    events=_projection_events()+[account_opened('unmeasured-eur','depository','Example EUR','EUR','2026-01-01')]
    reg=default_registry(LedgerProjection(events),today='2026-02-01')
    assert reg.call('read_financial_projections',{'view':'known_remainder','currency':'USD'}).ok
    assert reg.call('read_financial_projections',{'view':'known_remainder'}).refusal=='projection_start_unavailable'


def test_compatible_conflicted_start_keeps_original_grade_limit():
    events=[account_opened('cash','depository','Example Cash','USD','2026-01-01'),
            document_captured('conflict','conflict.pdf',100,'bank_statement',1,'2026-01-01'),
            opening_balance_observed('cash','100','2026-01-01',_p('conflict')),
            simple_transaction('cash','-5','Example Purchase','2026-01-15',provenance=_p('conflict')),
            closing_balance_observed('cash','100','2026-01-31',_p('conflict'))]
    result=default_registry(LedgerProjection(events),today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok and result.data['slices'][0]['grade']=='conflicted'
    assert 'balance_conflicted' in result.data['slices'][0]['caveats']
    assert all(f['kind']=='hypothetical' and not f['grade'] for f in result.figures)


def test_exclusion_references_preserve_exact_slice_association():
    events=_projection_events()+[account_opened('loan','liability','Example Loan','USD','2026-01-01'),
                                account_opened('eur-investment','investment','Example EUR Investment','EUR','2026-01-01')]
    projection=LedgerProjection(events)
    original=projection.current_period('2026-02-01',30)
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder','currency':'USD'})
    assert result.ok
    from dataclasses import asdict
    from viva.tools.projections import _json
    assert result.data['exclusions']==[_json(asdict(row)) for row in original.exclusions]
    assert [result.data['exclusions'][i] for i in result.data['slices'][0]['exclusion_refs']]==[_json(asdict(row)) for row in original.slices[0].exclusions]
    assert 'indexes the top-level exclusions' in result.data['exclusion_encoding']


def _eleven_depository_events():
    """Eleven accounts, nineteen statements; full production-length source IDs."""
    import hashlib
    from dataclasses import replace
    events=_projection_events()
    docs={e.body['doc_id']:hashlib.sha256(e.body['doc_id'].encode()).hexdigest() for e in events if e.event_type=='DocumentCaptured'}
    events=[replace(e,body={key:docs.get(value,value) if isinstance(value,str) else value for key,value in e.body.items()},
                    provenance=replace(e.provenance,doc_id=docs.get(e.provenance.doc_id,e.provenance.doc_id))) for e in events]
    for index in range(10):
        account='resource-'+str(index)
        events.append(account_opened(account,'depository','Example Resource Account '+str(index),'USD','2025-12-01'))
        for month in (('2025-12','2026-01') if index<6 else ('2026-01',)):
            doc=hashlib.sha256((account+month).encode()).hexdigest()
            events.extend([document_captured(doc,'synthetic.pdf',100,'bank_statement',1,month+'-28'),
                           closing_balance_observed(account,'100',month+'-28',_p(doc),confirmed_by='human')])
    return events


def test_complete_projection_with_eleven_accounts_and_realistic_source_ids_is_usable():
    import json
    projection=LedgerProjection(_eleven_depository_events())
    assert len(projection.captured_docs())==19
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok,result.refusal
    assert len(result.data['slices'][0]['account_ids'])==11
    captured=set(projection.core._captured)
    assert len(captured.intersection(result.record_ids))==13
    assert all(len(doc)==64 for doc in captured.intersection(result.record_ids))
    assert result.data['slices'][0]['reserved_for_goals']=='100'
    assert result.data['slices'][0]['goal_contributions']=='50'
    assert len(json.dumps(result.to_dict()).encode())<=10_000
    delivered,_=_answer('known_remainder',{},registry=default_registry(projection,today='2026-02-01'))
    assert delivered.result.answered and len(delivered.result.figures)==2


def test_oversized_projection_refuses_whole_set_without_truncating_sources():
    import hashlib
    events=_eleven_depository_events()
    for index in range(100):
        account='oversize-'+str(index)
        doc=hashlib.sha256(account.encode()).hexdigest()
        events.extend([account_opened(account,'depository','Example Oversized Account','USD','2026-01-01'),
                       document_captured(doc,'synthetic.pdf',100,'bank_statement',1,'2026-01-28'),
                       closing_balance_observed(account,'100','2026-01-28',_p(doc),confirmed_by='human')])
    result=_runtime_answer('known_remainder',{},registry=default_registry(LedgerProjection(events),today='2026-02-01'))
    assert result.outcome.tag=='projection_payload_limit' and not result.result.figures
    assert all(item['label']==result.result.text for item in result.result.missing)


@pytest.mark.parametrize('family',['known_remainder','upcoming_obligations'])
def test_hypothetical_projection_date_is_visible_beside_every_amount(family):
    result,_=_answer(family,{},registry=_projection_registry())
    assert result.result.answered
    assert all(item['dated'] in item['what'] and item['what'] in result.result.text for item in result.result.figures)


def test_remainder_boundary_uses_held_duplicate_names_and_masks():
    from dataclasses import replace
    events=_projection_events()
    events[0]=replace(events[0],body={**events[0].body,'name':'Example Shared','account_number':'SYNTHETIC0001'})
    events.extend([account_opened('other-cash','depository','Example Shared','USD','2026-01-01',account_number='SYNTHETIC0002'),
                   document_captured('other-cash-source','synthetic.pdf',100,'bank_statement',1,'2026-01-31'),
                   closing_balance_observed('other-cash','100','2026-01-31',_p('other-cash-source'))])
    result,_=_answer('known_remainder',{},registry=default_registry(LedgerProjection(events),today='2026-02-01'))
    assert result.result.answered and 'Example Shared' in result.result.text
    assert '0001' in result.result.text and '0002' in result.result.text
    assert 'only what is on cash' not in result.result.text and 'other-cash' not in result.result.text
    assert {item['value'] for item in result.result.figures[0]['boundary']['selected']}=={'cash','other-cash'}


def test_projection_human_limitations_keep_raw_known_and_unknown_diagnostics(monkeypatch):
    from dataclasses import replace
    projection=LedgerProjection(_projection_events())
    original=projection.current_period('2026-02-01',30)
    raw=('balance_freshness_unconfirmed','balance_conflicted','balance_undated','income_interrupted','unknown_internal_limit','balance_conflicted:unexpected_suffix')
    changed=replace(original,slices=(replace(original.slices[0],caveats=raw),))
    monkeypatch.setattr(projection,'current_period',lambda *args:changed)
    registry=default_registry(projection,today='2026-02-01')
    read=registry.call('read_financial_projections',{'view':'known_remainder'})
    assert read.ok and read.data['slices'][0]['caveats']==list(raw)
    delivered,_=_answer('known_remainder',{},registry=registry)
    assert delivered.result.answered and all(tag not in delivered.result.text for tag in raw)
    assert 'freshness is unconfirmed' in delivered.result.text
    assert 'review the underlying records' in delivered.result.text


def test_goal_status_and_issues_use_human_copy_with_original_codes_retained(monkeypatch):
    from dataclasses import replace
    projection=LedgerProjection(_projection_events())
    original=projection.goals('2026-02-01')[0]
    changed=replace(original,status='unknown_internal_status',issues=('release_exceeds_reserved:cash:internal-event','unknown_internal_issue'))
    monkeypatch.setattr(projection,'goals',lambda *args:[changed])
    registry=default_registry(projection,today='2026-02-01')
    read=registry.call('read_financial_projections',{'view':'goal_progress'})
    assert read.ok and read.data['goals'][0]['status']==changed.status and read.data['goals'][0]['issues']==list(changed.issues)
    delivered,_=_answer('goal_progress',{},registry=registry)
    assert delivered.result.answered
    assert all(code not in delivered.result.text for code in [changed.status,*changed.issues,'internal-event'])
    assert 'release exceeded the reserved funds' in delivered.result.text
    assert 'review the underlying records' in delivered.result.text


def test_measured_cadence_and_risk_are_described_in_plain_language():
    upcoming,_=_answer('upcoming_obligations',{},registry=_projection_registry())
    goals,_=_answer('goal_progress',{},registry=_projection_registry())
    assert 'measured_not_confirmed' not in upcoming.result.text
    assert 'measured from history' in upcoming.result.text
    assert 'at_risk' not in goals.result.text and 'at risk of missing the recorded target' in goals.result.text


def test_unknown_obligation_basis_is_not_forwarded_as_user_prose(monkeypatch):
    from dataclasses import replace
    projection=LedgerProjection(_projection_events())
    original=projection.obligations('2026-02-01')[0]
    changed=replace(original,basis='unknown_internal_basis',caveats=('unknown_internal_obligation_limit',))
    monkeypatch.setattr(projection,'obligations',lambda *args:[changed])
    registry=default_registry(projection,today='2026-02-01')
    read=registry.call('read_financial_projections',{'view':'upcoming_obligations'})
    assert read.data['next_expectations'][0]['basis']==changed.basis
    delivered,_=_answer('upcoming_obligations',{},registry=registry)
    assert delivered.result.answered and changed.basis not in delivered.result.text
    assert changed.caveats[0] not in delivered.result.text and 'review the underlying records' in delivered.result.text


@pytest.mark.parametrize('code,known',[
    ('release_exceeds_reserved:cash:internal-event',True),
    ('release_exceeds_reserved:Assets:Example:cash:internal-event',True),
    ('release_exceeds_reserved',False),
    ('release_exceeds_reserved:',False),
    ('release_exceeds_reserved:unexpected_suffix',False),
    ('release_exceeds_reserved:cash:',False),
    ('release_exceeds_reserved::internal-event',False),
    ('release_exceeds_reserved: :internal-event',False),
    ('release_exceeds_reserved:cash: ',False),
])
def test_release_issue_requires_complete_dynamic_source_shape(monkeypatch,code,known):
    from dataclasses import replace
    projection=LedgerProjection(_projection_events())
    original=projection.goals('2026-02-01')[0]
    changed=replace(original,issues=(code,))
    monkeypatch.setattr(projection,'goals',lambda *args:[changed])
    registry=default_registry(projection,today='2026-02-01')
    read=registry.call('read_financial_projections',{'view':'goal_progress'})
    assert read.ok and read.data['goals'][0]['issues']==[code]
    delivered,_=_answer('goal_progress',{},registry=registry)
    assert delivered.result.answered and code not in delivered.result.text
    if known:
        assert 'A recorded release exceeded the reserved funds.' in delivered.result.text
        assert 'review the underlying records' not in delivered.result.text
    else:
        assert 'A recorded release exceeded the reserved funds.' not in delivered.result.text
        assert 'An additional recorded input limitation applies; review the underlying records.' in delivered.result.text


def test_known_remainder_retains_participating_local_numerical_sources():
    from dataclasses import asdict
    from viva.tools.projections import _json
    projection=LedgerProjection(_projection_events())
    original=projection.current_period('2026-02-01',30).slices[0]
    local=set(projection.goals('2026-02-01')[0].event_ids)
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok
    assert all(set(f['record_ids'])==set(original.record_ids)|local for f in result.figures)
    assert result.data['slices'][0]['record_ids']==sorted(set(original.record_ids)|local)
    assert result.data['record_ids']==result.record_ids==sorted(set(original.record_ids)|local)
    receipt=result.data['slices'][0]['local_goal_inputs']
    assert receipt==[{'goal_id':'g','record_ids':sorted(local),
        'reservations':[{'account_id':'cash','amount':'100','currency':'USD'}],
        'contributions':[{'date':'2026-02-20','amount':'50','currency':'USD'}]}]
    assert result.data['slices'][0]['steps']==_json(asdict(original))['steps']
    assert result.data['slices'][0]['grade']==original.grade
    assert all(not f['grade'] and f['kind']=='hypothetical' for f in result.figures)


def test_known_remainder_missing_local_lineage_refuses_without_partial_figures(monkeypatch):
    from dataclasses import replace
    from viva.ledger.projection import goals as goal_module
    projection=LedgerProjection(_projection_events())
    original=projection.goals('2026-02-01')[0]
    monkeypatch.setattr(goal_module,'goals',lambda *args:[replace(original,event_ids=())])
    answer=_runtime_answer('known_remainder',{},registry=default_registry(projection,today='2026-02-01'))
    assert answer.outcome.tag=='projection_goal_sources_unavailable' and not answer.result.figures
    assert all(item['label']==answer.result.text for item in answer.result.missing)


def test_local_goal_sources_use_ids_for_duplicate_titles_and_exclude_nonparticipants():
    from viva.ledger.events import goal_state_changed
    events=_projection_events()+[
        goal_created('g2','Example Goal','USD','500','2026-01-31',monthly_contribution='50',contribution_day=20),
        goal_created('quiet','Example Goal','USD','500','2026-01-31'),
        goal_created('paused','Example Goal','USD','500','2026-01-31',monthly_contribution='50',contribution_day=20),
        goal_state_changed('paused','paused','2026-01-31'),
        goal_created('foreign','Example Goal','EUR','500','2026-01-31',monthly_contribution='50',contribution_day=20),
        goal_created('excluded','Example Goal','USD','500','2026-01-31'),
        account_opened('loan-source','liability','Example Other Loan','USD','2026-01-31'),
        goal_funds_reserved('excluded','loan-source','100','2026-01-31')]
    projection=LedgerProjection(events); goals={g.goal_id:g for g in projection.goals('2026-02-01')}
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok,result.refusal
    inputs=result.data['slices'][0]['local_goal_inputs']
    assert [item['goal_id'] for item in inputs]==['g','g2']
    assert [item['record_ids'] for item in inputs]==[sorted(goals[k].event_ids) for k in ('g','g2')]
    assert all(item['contributions']==[{'date':'2026-02-20','amount':'50','currency':'USD'}] for item in inputs)
    actual=set(result.figures[0]['record_ids'])
    assert set(goals['g'].event_ids)|set(goals['g2'].event_ids)<=actual
    assert not actual.intersection(source for k in ('quiet','paused','foreign','excluded') for source in goals[k].event_ids)


@pytest.mark.parametrize('change',['paused','goal_currency'])
def test_held_reservation_sources_survive_inactive_or_changed_currency_schedule(change):
    from viva.ledger.events import goal_state_changed,goal_terms_changed
    events=_projection_events()
    events.append(goal_state_changed('g','paused','2026-01-31') if change=='paused' else
        goal_terms_changed('g','Example Goal','EUR','500','2026-01-31',monthly_contribution='50',contribution_day=20))
    projection=LedgerProjection(events);goal=projection.goals('2026-02-01')[0]
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder','currency':'USD'})
    assert result.ok,result.refusal
    inputs=result.data['slices'][0]['local_goal_inputs']
    assert inputs==[{'goal_id':'g','record_ids':sorted(goal.event_ids),
        'reservations':[{'account_id':'cash','amount':'100','currency':'USD'}],'contributions':[]}]
    assert all(set(goal.event_ids)<=set(f['record_ids']) for f in result.figures)
    assert result.data['slices'][0]['goal_contributions']=='0'


def test_fully_released_reserve_and_outside_horizon_schedule_attach_no_sources():
    from viva.ledger.events import goal_funds_released
    projection=LedgerProjection(_projection_events()+[goal_funds_released('g','cash','100','used_elsewhere','2026-01-31')])
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder','horizon_days':'10'})
    assert result.ok and result.data['slices'][0]['local_goal_inputs']==[]
    assert result.data['slices'][0]['reserved_for_goals']=='0' and result.data['slices'][0]['goal_contributions']=='0'
    assert not set(result.record_ids).intersection(projection.goals('2026-02-01')[0].event_ids)


@pytest.mark.parametrize('amount',['20','0'])
def test_capped_or_zero_emitted_contributions_keep_local_lineage(monkeypatch,amount):
    from dataclasses import replace
    from viva.ledger.projection import goals as goal_module
    projection=LedgerProjection(_projection_events());original=projection.goals('2026-02-01')[0]
    # The existing helper receives the same held input view as the wrapper.
    changed=replace(original,monthly_contribution=Decimal('50') if amount=='20' else Decimal('0'),remaining=Decimal('20'))
    monkeypatch.setattr(goal_module,'goals',lambda *args:[changed])
    result=default_registry(projection,today='2026-02-01').call('read_financial_projections',{'view':'known_remainder'})
    assert result.ok,result.refusal
    assert result.data['slices'][0]['local_goal_inputs'][0]['contributions']==[{'date':'2026-02-20','amount':amount,'currency':'USD'}]
    assert all(set(changed.event_ids)<=set(f['record_ids']) for f in result.figures)


@pytest.mark.parametrize('field',['reserve_total','contribution_total','occurrence','multiplicity'])
def test_local_goal_helper_mismatch_refuses_whole_projection(monkeypatch,field):
    from dataclasses import replace
    projection=LedgerProjection(_projection_events());original=projection.current_period('2026-02-01',30);row=original.slices[0]
    if field=='reserve_total':changed=replace(row,reserved_for_goals=row.reserved_for_goals+1)
    elif field=='contribution_total':changed=replace(row,goal_contributions=row.goal_contributions+1)
    elif field=='occurrence':changed=replace(row,steps=tuple(replace(step,date='2026-02-21') if step.kind=='goal' else step for step in row.steps))
    else:changed=replace(row,steps=(*row.steps,next(step for step in row.steps if step.kind=='goal')))
    monkeypatch.setattr(projection,'current_period',lambda *args:replace(original,slices=(changed,)))
    answer=_runtime_answer('known_remainder',{},registry=default_registry(projection,today='2026-02-01'))
    assert answer.outcome.tag=='projection_goal_sources_unavailable' and not answer.result.figures
    assert all(item['label']==answer.result.text for item in answer.result.missing)
