"""Cash selectors consume restrictions; recorded asset value remains separate.

The restriction fold's persisted-state tests belong to its owning module. These
contract tests supply that fold's public mapping and check every consumer.
"""
from dataclasses import asdict
from decimal import Decimal
from types import ModuleType, SimpleNamespace
import importlib
import sys

import pytest

from viva.ledger import (LedgerProjection, EventStore, Provenance, account_opened,
                         closing_balance_observed, goal_created, simple_transaction)
from viva.ledger.events import CORROBORATED, merchant_enriched
from viva.ledger.networth import net_worth
from viva.read_store import ReadStore
from viva.read_store.store import ReadRevision
from viva.tools.projections import read_financial_projections
from viva.tools.measurements import read_account_measurements

DAY = '2026-05-01'


def _events():
    events = []
    for account, amount in [('ordinary', '100'), ('deposit', '200'), ('escrow', '300')]:
        events += [account_opened(account, 'depository', 'Identical ordinary label', 'USD', '2026-01-01'),
                   closing_balance_observed(account, amount, DAY, Provenance(account+'-doc', 1))]
    return events + [goal_created('goal', 'Goal', 'USD', '500', '2026-04-01')]


@pytest.fixture
def restrictions(monkeypatch):
    # A stub is needed only while the separate persistence builder publishes the
    # agreed contract. Existing implementations are patched at their real API.
    try:
        module = importlib.import_module('viva.ledger.instruments')
    except ModuleNotFoundError:
        module = ModuleType('viva.ledger.instruments')
        monkeypatch.setitem(sys.modules, module.__name__, module)
    state = {}
    monkeypatch.setattr(module, 'account_restrictions', lambda core: state, raising=False)
    monkeypatch.setattr(LedgerProjection, 'account_restrictions', lambda self: state, raising=False)
    monkeypatch.setattr(ReadRevision, 'account_restrictions', lambda self, *, as_of: state, raising=False)
    return state


def _restrict(state, status):
    for account, family, restriction in [('deposit', 'term_deposit', 'restricted_term_deposit'),
                                          ('escrow', 'escrow', 'restricted_escrow')]:
        state[account] = SimpleNamespace(family=family, restriction=restriction if status=='accepted' else '',
                                        status=status, record_ids=(), doc_ids=(), effective=DAY)


@pytest.mark.parametrize('status', ['accepted', 'missing', 'conflicted'])
def test_instrument_value_is_counted_once_but_never_starts_cash_or_funds_goal(restrictions, status):
    _restrict(restrictions, status)
    projection = LedgerProjection(_events())
    row = projection.current_period(DAY).slices[0]
    assert row.liquid_balance == Decimal('100')
    assert row.steps[0].account_ids == ('ordinary',)
    assert {r.identity:r.reason for r in row.exclusions if r.kind=='account'} == {
        'deposit':'account_restricted', 'escrow':'account_restricted'}
    goal = projection.goal('goal', DAY)
    assert [a.account_id for a in goal.available_accounts] == ['ordinary']
    assert projection.goal_account_stake('deposit','USD')['eligible'] is False
    assert projection.goal_account_stake('escrow','USD')['exclusion_reason']=='account_restricted'
    assert projection.goal_account_stake('ordinary','USD')['eligible'] is True
    assert net_worth(projection, DAY).by_currency()['USD']['net'] == Decimal('600')
    assert len(net_worth(projection, DAY).lines) == 3


def test_ordinary_accounts_keep_existing_eligibility_without_metadata(restrictions):
    projection = LedgerProjection(_events())
    assert projection.current_period(DAY).slices[0].liquid_balance == Decimal('600')
    assert len(projection.goal('goal', DAY).available_accounts)==3


def _normal(value):
    if hasattr(value, '__dataclass_fields__'): value = asdict(value)
    if isinstance(value, dict): return {k:_normal(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)): return [_normal(v) for v in value]
    return value


@pytest.mark.parametrize('status', ['accepted','missing','conflicted'])
def test_sql_and_event_cash_goal_selection_match(restrictions, tmp_path, status):
    _restrict(restrictions,status)
    events=_events(); source=EventStore.open(tmp_path/'events.jsonl','synthetic-test')
    source.append_atomically(lambda existing: events)
    canonical=LedgerProjection(events)
    with ReadStore.create(tmp_path/'read','synthetic-test') as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            period=revision.current_period(today=DAY)
            assert period.slices[0].liquid_balance==Decimal('100')
            assert _normal(period)==_normal(canonical.current_period(DAY))
            sql_goal=revision.current_goal_views(today=DAY)[0]
            assert [a['account_id'] for a in sql_goal['available_accounts']]==['ordinary']
            assert [(r['account_id'],r['reason']) for r in sql_goal['exclusions']]==[
                ('deposit','account_restricted'),('escrow','account_restricted')]


def test_restricted_recurring_interest_never_increases_known_remainder(restrictions,tmp_path):
    _restrict(restrictions,'accepted')
    events=_events()
    events += [simple_transaction('deposit','10','SYNTHETIC CREDIT',f'2026-{month:02d}-15',kind='depository')
               for month in range(1,5)]
    events.append(merchant_enriched('synthetic credit','income',occurred_at='2026-04-16',grade=CORROBORATED,
                  attributes={'counterparty_kind':'business','billing':'standing','billing_period':'monthly'}))
    projection=LedgerProjection(events)
    row=projection.current_period(DAY).slices[0]
    assert row.expected_income_max==0
    assert row.remainder_max==100
    from viva.tools.ledger_aggregates import _aggregate_income
    income=_aggregate_income(projection,{})
    assert income.ok and Decimal(income.data['by_currency']['USD'])==Decimal('40')
    source=EventStore.open(tmp_path/'events.jsonl','synthetic-test');source.append_atomically(lambda existing: events)
    with ReadStore.create(tmp_path/'read','synthetic-test') as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            assert _normal(revision.current_period(today=DAY))==_normal(projection.current_period(DAY))


def test_restricted_unaccepted_cash_does_not_poison_ordinary_known_remainder(restrictions):
    from test_measurement_tools import _measurement_events
    _restrict(restrictions,'accepted')
    # Ordinary cash has accepted source records. Restricted balances deliberately
    # have no accepted measurement records and must be excluded before checking.
    events=_measurement_events()+[e for e in _events() if e.body.get('account_id') != 'ordinary']
    projection=LedgerProjection(events)
    result=read_financial_projections(projection,{'view':'known_remainder','currency':'USD'},today='2026-02-01')
    assert result.ok, result.refusal
    assert all('deposit' not in row['account_ids'] and 'escrow' not in row['account_ids'] for row in result.data['slices'])


@pytest.mark.parametrize('status',['accepted','missing','conflicted'])
def test_restricted_scenario_start_refuses_but_source_cash_history_remain_accessible(restrictions,status):
    from test_measurement_tools import _measure_registry
    from test_scenario_tools import _measured_scenario_setup
    restrictions['cash']=SimpleNamespace(family='term_deposit',status=status)
    registry=_measure_registry()
    args,question,read,graph=_measured_scenario_setup(registry)
    assert read.ok and read.figures[0]['value']=='100'
    result=registry.call('simulate_scenario',args,figures=graph.book,question=question)
    assert not result.ok and result.refusal=='scenario_starting_account_restricted' and not result.figures
    assert 'restricted or unresolved availability' in result.text
    history=registry.call('read_account_measurements',{'view':'account_value_history','account':'cash',
                                               'from':'2026-01-01','to':'2026-01-31'})
    assert history.ok and history.figures[0]['value']=='100'


def test_restrictions_do_not_change_explicit_hypothetical_or_owed_starts(restrictions):
    from test_measurement_tools import _measure_registry
    from test_scenario_tools import _case, _scenario_args
    from viva.tools.scenarios import simulate_scenario
    restrictions['cash']=SimpleNamespace(family='term_deposit',status='accepted')
    registry=_measure_registry()
    case=_case('savings_monthly_one_percent')
    args=_scenario_args(case)
    result=registry.call('simulate_scenario',args,figures={},question=case.question)
    assert result.ok and result.figures
    assert all(f['kind']=='hypothetical' for f in result.figures)


def test_recorded_owed_path_does_not_use_cash_restriction_predicate(restrictions):
    from test_scenario_tools import _case, _parsed_scenario
    from viva.answer_program.execute import ProgramExecutor
    from viva.answer_program.schema import AnswerResourcePolicy
    case=_case('loan_measured_owed_partial_final')
    registry,raw,semantic,program=_parsed_scenario(case)
    restrictions[raw['parameters']['account_phrase']]=SimpleNamespace(family='escrow',status='missing')
    execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,case.question)
    assert any(row.tool=='simulate_scenario' and row.ok for row in execution.transcript)


def test_maturity_zero_and_duplicate_balance_witness_do_not_release_instrument(restrictions,tmp_path):
    _restrict(restrictions,'accepted')
    redemption=closing_balance_observed('deposit','0','2026-06-01',Provenance('redemption',1))
    events=_events()+[redemption,
        closing_balance_observed('deposit','0','2026-06-01',Provenance('redemption',1)),
        account_opened('receiving','depository','Same label','USD','2026-06-01'),
        closing_balance_observed('receiving','200','2026-06-01',Provenance('receiving-doc',1))]
    projection=LedgerProjection(events)
    current=projection.current_period('2026-06-01')
    assert current.slices[0].liquid_balance==Decimal('300')
    assert current.slices[0].steps[0].account_ids==('ordinary','receiving')
    assert net_worth(projection,'2026-06-01').by_currency()['USD']['net']==Decimal('600')
    assert len(net_worth(projection,'2026-06-01').lines)==4
    source=EventStore.open(tmp_path/'events.jsonl','synthetic-test');source.append_atomically(lambda existing: events)
    with ReadStore.create(tmp_path/'read','synthetic-test') as reads:
        reads.synchronize(source)
        with reads.open_reader() as revision:
            assert _normal(revision.current_period(today='2026-06-01'))==_normal(current)


def test_real_restriction_lifecycle_sql_event_historical_reload_and_closure(tmp_path):
    from dataclasses import replace
    from viva.ingest.instrument_contracts import (Availability, ContractError, Family,
                                                 Restriction, Source, SourcedDate)
    from viva.ingest.instrument_observations import ObservationChange, ObservationKind, Operation
    from viva.ledger.events import document_captured
    from viva.ledger.instruments import family_event, observation_event

    events=_events()
    for account,family in [('deposit','term_deposit'),('escrow','escrow')]:
        source=Source(account+'-doc',1)
        events += [document_captured(source.doc_id,account+'.pdf',10,'term_deposit_statement' if account=='deposit' else 'mortgage_statement',1,DAY),
                   family_event(account,family,DAY,source)]
    source=EventStore.open(tmp_path/'events.jsonl','synthetic-test')
    source.append_atomically(lambda existing: events)
    root=tmp_path/'read'
    reads=ReadStore.create(root,'synthetic-test');reads.synchronize(source)
    held=reads.open_reader()
    assert {r.status for r in held.account_restrictions(as_of=DAY).values()}=={'missing'}

    changes=[]
    for account,family,restriction in [('deposit',Family.DEPOSIT,Restriction.TERM),
                                      ('escrow',Family.ESCROW,Restriction.ESCROW)]:
        evidence=Source(account+'-doc',1)
        changes.append(ObservationChange(account+'-restriction',account,ObservationKind.AVAILABILITY,
            SourcedDate(DAY,evidence),Operation.CREATE,evidence,Availability(family,restriction,evidence)))
    original=changes[0]
    correction=replace(original,observation_id='deposit-corrected',operation=Operation.CORRECT,
                       prior_id=original.observation_id,effective=SourcedDate('2026-05-02',original.source))
    # Invalid release attempts must fail rather than manufacture cash eligibility.
    with pytest.raises(ContractError):
        replace(correction,observation_id='illegal-release',operation=Operation.RETRACT,
                prior_id=correction.observation_id,payload=None)
    stages=[([observation_event(c) for c in changes],DAY,'accepted','100'),
            ([observation_event(correction)],'2026-05-02','accepted','100'),
            ([family_event('deposit','escrow','2026-05-03',original.source)],'2026-05-03','conflicted','100'),
            ([closing_balance_observed('deposit','0','2026-06-01',Provenance('redemption',1)),
              account_opened('receiving','depository','Ordinary receiving account','USD','2026-06-01'),
              closing_balance_observed('receiving','200','2026-06-01',Provenance('receiving-doc',1))],
             '2026-06-01','conflicted','300')]
    for suffix,day,status,amount in stages:
        source.append_atomically(lambda existing,suffix=tuple(suffix): suffix)
        events.extend(suffix);reads.synchronize(source)
        oracle=LedgerProjection(events,as_of=day)
        assert oracle.account_restrictions()['deposit'].status==status
        assert oracle.current_period(day).slices[0].liquid_balance==Decimal(amount)
        assert net_worth(oracle,day).by_currency()['USD']['net']==Decimal('600')
        with reads.open_reader() as revision:
            assert revision.account_restrictions(as_of=day)==oracle.account_restrictions()
            assert _normal(revision.current_period(today=day))==_normal(oracle.current_period(day))
            goal=revision.current_goal_views(today=day)[0]
            assert not {'deposit','escrow'}.intersection(a['account_id'] for a in goal['available_accounts'])
            assert [a['account_id'] for a in goal['available_accounts']]==[
                a.account_id for a in oracle.goal('goal',day).available_accounts]
    # An immutable pre-observation reader retains its original missing status.
    assert held.account_restrictions(as_of='2026-06-01')['deposit'].status=='missing'
    held.close();reads.close()
    with ReadStore.open(root,'synthetic-test') as reopened:
        assert reopened.synchronize(source).state=='equal'
        with reopened.open_reader() as revision:
            assert revision.account_restrictions(as_of='2026-06-01')==LedgerProjection(events).account_restrictions()
            assert revision.current_period(today='2026-06-01').slices[0].liquid_balance==Decimal('300')
            assert revision.account_restrictions(as_of=DAY)==LedgerProjection(events,as_of=DAY).account_restrictions()
            assert revision.account_restrictions(as_of='2026-04-30')=={}
