"""Executable source/cash boundaries for the four instrument source families."""
import json
from dataclasses import replace
from decimal import Decimal

import pytest

from viva.ingest import RawStore, ReadResult, capture_and_ingest
from viva.ingest.instrument_read import InstrumentReadFacts
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_projector import heal_instruments, post_instrument
from viva.ingest.instrument_observations import ObservationKind
from viva.ledger import EventStore, Ledger, LedgerProjection
from viva.ledger.instruments import reference_accounts
from viva.ledger.accounting import financial_statements
from viva.ingest.statement import from_model_json
from test_instrument_contracts import mortgage_json, deposit_json, refinance_json, printed, identity


def setup(tmp_path):
    return (RawStore.open(tmp_path / 'raw', 'synthetic-passphrase'),
            Ledger(EventStore.open(tmp_path / 'events.jsonl', 'synthetic-passphrase')))


def ingest(raw, ledger, label, data, kind):
    def read(blob, doc_id):
        facts = InstrumentReadFacts(doc_id, kind, 1.0,
            parse_instrument_json(json.dumps(data), kind, doc_id), 'USD')
        return ReadResult(kind, 1.0, facts)
    return capture_and_ingest(raw, ledger, label.encode(), read)


def bank(raw, ledger, *, amount='600', counterpart='LOAN-A', reference='PAY-A', dated='2021-01-15', label='bank'):
    data = {'doc_type':'checking_statement','doc_type_confidence':1,
        'institution':'Fixture Bank','account_ref':'Fixture Checking','account_names':['Synthetic Person'],
        'source_account_ref':'CHECK-A','source_account_ref_page':1,
        'opening':{'amount_raw':'2000','date_raw':'2021-01-01','page':1},
        'closing':{'amount_raw':str(Decimal('2000')-Decimal(amount)),'date_raw':'2021-01-31','page':1},
        'transactions':[{'amount_raw':amount,'balance_effect':'decrease','date_raw':dated,'page':1,
            'description':'Printed source payment','source_reference':reference,'counterparty_reference':counterpart}]}
    def read(blob, doc_id):
        facts,error=from_model_json(json.dumps(data),doc_id,'en-US','USD')
        assert error is None
        return ReadResult('checking_statement',1.0,facts)
    return capture_and_ingest(raw,ledger,label.encode(),read)


def mortgage():
    data=mortgage_json()
    data['payments'][0]['funding_account_reference']=printed('CHECK-A')
    data['escrow']['continuity_reference']=printed('ESCROW-A')
    data['escrow']['withdrawal_restriction']=printed('Restricted escrow; servicer disbursements only')
    data['escrow']['movements'][1].update(property_reference=printed('PROPERTY-A'),tax_year=2021)
    return data


@pytest.mark.parametrize('bank_first',[True,False])
def test_real_dispatch_preserves_600_cash_100_debt_200_interest_300_escrow_and_heals(tmp_path,bank_first):
    raw,ledger=setup(tmp_path)
    if bank_first: bank(raw,ledger)
    result=ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    if not bank_first: bank(raw,ledger)
    assert result.action in {'posted','awaiting'}
    assert len(ledger.projection().instrument_allocations())==1
    loan=reference_accounts(ledger.projection(),'LOAN-A')[0]
    escrow=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    checking=reference_accounts(ledger.projection(),'CHECK-A')[0]
    for proj in (ledger.projection(),LedgerProjection(ledger.events())):
        assert proj.running_balance(loan)==Decimal('900')
        assert proj.running_balance(escrow)==Decimal('200')
        assert proj.running_balance(checking)==Decimal('1400')
        cash=[m for m in proj.movements() if m.account==checking]
        assert len(cash)==1 and cash[0].amount==Decimal('-600')
        assert cash[0].component_spending==Decimal('200')
        assert proj.spending_by_currency()=={'USD':Decimal('300')}
        report=financial_statements(proj)['profit_loss']
        assert not report['unresolved_components']
        assert sum((Decimal(r['amount']) for r in report['lines'] if r['root']=='expenses'),Decimal(0))==Decimal('300')
    count=len(list(ledger.events()))
    assert heal_instruments(ledger)==0
    assert len(list(ledger.events()))==count
    assert ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement').action=='duplicate'


@pytest.mark.parametrize('field,value',[('counterparty_reference','WRONG-LOAN'),('source_reference','WRONG-PAY')])
def test_amount_date_alone_never_match(tmp_path,field,value):
    raw,ledger=setup(tmp_path)
    kwargs={'counterpart':value} if field=='counterparty_reference' else {'reference':value}
    bank(raw,ledger,**kwargs)
    result=ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    assert result.action=='awaiting'
    assert ledger.projection().instrument_allocations()=={}
    # Valid principal and escrow sections remain accepted independently.
    assert ledger.projection().running_balance(reference_accounts(ledger.projection(),'LOAN-A')[0])==Decimal('900')


def test_terms_only_cd_is_restricted_but_has_no_invented_balance(tmp_path):
    raw,ledger=setup(tmp_path)
    data={'identity':identity('CD-A'),'subtype':'opening','terms':{
        'principal':printed('1000'),'opened':printed('2021-01-01'),'maturity':printed('2022-01-01'),
        'withdrawal_restriction':printed('No withdrawal until maturity')}}
    result=ingest(raw,ledger,'cd-certificate',data,'term_deposit_statement')
    proj=ledger.projection(); account=reference_accounts(proj,'CD-A')[0]
    assert result.action=='awaiting'
    assert proj.is_resolved(result.doc_id)
    assert not proj.is_seeded(account)
    assert proj.account_restrictions()[account].status=='accepted'
    assert not proj.movements()
    assert proj.spending_by_currency()=={}


def test_cd_period_backfill_and_maturity_are_once_only_and_receiving_cash_is_independent(tmp_path):
    raw,ledger=setup(tmp_path)
    second=deposit_json();second.update(start=printed('2021-02-01'),end=printed('2021-02-28'),
        opening=printed('1010'),closing=printed('1020'))
    second['movements'][0].update(dated=printed('2021-02-28'),reference=printed('INT-B'))
    ingest(raw,ledger,'cd-feb',second,'term_deposit_statement')
    ingest(raw,ledger,'cd-jan',deposit_json(),'term_deposit_statement')
    proj=ledger.projection(); account=reference_accounts(proj,'CD-A')[0]
    assert proj.running_balance(account)==Decimal('1020')
    assert len([m for m in proj.movements() if m.account==account])==2
    assert proj.account_restrictions()[account].status=='missing'
    assert heal_instruments(ledger)==0
    # No receiving bank witness is manufactured at maturity.
    maturity=deposit_json();maturity.update(subtype='maturity',start=printed('2021-03-01'),end=printed('2021-03-31'),
        opening=printed('1020'),closing=printed('0'))
    maturity['movements']=[{'kind':'redemption','amount':printed('1020'),'dated':printed('2021-03-31'),
        'reference':printed('CD-REDEMPTION'),'counterparty_reference':printed('CHECK-A')}]
    ingest(raw,ledger,'cd-mature',maturity,'term_deposit_statement')
    assert ledger.projection().running_balance(account)==0
    assert account in ledger.projection().account_restrictions()
    assert len([a for a in ledger.projection().account_infos() if a.kind=='depository'])==1


def test_receipt_corresponds_to_escrow_disbursement_and_never_posts_a_second_tax(tmp_path):
    raw,ledger=setup(tmp_path)
    receipt={'authority':printed('Fixture County'),'property_reference':printed('PROPERTY-A'),'tax_year':2021,
        'dated':printed('2021-01-20'),'reference':printed('TAX-A'),'amount':printed('100'),
        'status':'paid','tax_year_source':{'page':1},'status_source':{'page':1},
        'source_account_reference':printed('ESCROW-A')}
    first=ingest(raw,ledger,'tax-receipt',receipt,'property_tax_receipt')
    assert first.action=='awaiting'
    ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    tax_states=[state for state in ledger.projection().instrument_component_states().values()
        if state.doc_id==first.doc_id]
    assert any(r.component=='tax_payment_link' and r.disposition.value=='accepted' for r in tax_states[0].components)
    assert sum(1 for m in ledger.projection().movements() if m.description=='TAX-A')==1
    assert heal_instruments(ledger)==0


def test_refinance_1000_fee25_creates_debt_measurement_and_no_income(tmp_path):
    raw,ledger=setup(tmp_path)
    bank(raw,ledger,amount='25',counterpart='LOAN-B',reference='FEE-A')
    data=refinance_json();data['dated']=printed('2021-01-15')
    data.update(fee_payment_reference=printed('FEE-A'),funding_account_reference=printed('CHECK-A'),fee_payment_date=printed('2021-01-15'))
    result=ingest(raw,ledger,'refinance-source',data,'refinance_settlement')
    proj=ledger.projection(); account=reference_accounts(proj,'LOAN-B')[0]
    assert result.action=='awaiting' # old loan-zero witness is unavailable
    assert proj.running_balance(account)==Decimal('1000')
    assert proj.spending_by_currency()=={'USD':Decimal('25')}
    report=financial_statements(proj)['profit_loss']
    assert not any(row['root']=='income' for row in report['lines'])
    assert sum(Decimal(row['amount']) for row in report['lines'] if row['root']=='expenses')==Decimal('25')

@pytest.mark.parametrize('section',['principal','payment','escrow','refinance'])
def test_one_cent_mutation_holds_only_its_independent_component(tmp_path,section):
    raw,ledger=setup(tmp_path)
    if section=='refinance':
        data=refinance_json();data['old_payoff_principal']=printed('1000.01')
        result=ingest(raw,ledger,'refi-bad',data,'refinance_settlement')
        assert not [m for m in ledger.projection().movements()]
        assert not ledger.projection().is_seeded(result.account)
        return
    bank(raw,ledger)
    data=mortgage()
    field={'principal':('closing_principal','900.01'), 'payment':('interest','200.01'), 'escrow':('closing','200.01')}[section]
    target=data if section=='principal' else data['payments'][0] if section=='payment' else data['escrow']
    target[field[0]]=printed(field[1])
    result=ingest(raw,ledger,'one-cent-'+section,data,'mortgage_statement')
    states=[s for s in ledger.projection().instrument_component_states().values() if s.doc_id==result.doc_id]
    failed=[r.component for r in states[0].components if r.disposition.value=='held']
    assert failed==[{'principal':'principal_balance','payment':'payment:PAY-A','escrow':'escrow_balance'}[section]]
    loan=reference_accounts(ledger.projection(),'LOAN-A')[0]
    assert ledger.projection().is_seeded(loan)==(section!='principal')
    assert len(ledger.projection().instrument_allocations())==(0 if section=='payment' else 1)


def test_missing_funding_reference_and_ambiguous_bank_witness_do_not_guess(tmp_path):
    from viva.ledger.events import Provenance, account_opened
    from viva.ledger.instruments import reference_event
    from viva.ingest.instrument_contracts import Source
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['payments'][0].pop('funding_account_reference')
    result=ingest(raw,ledger,'missing-funding',data,'mortgage_statement')
    assert result.action=='awaiting' and not ledger.projection().instrument_allocations()
    # A second known financial account with the same printed short reference
    # makes the reference ambiguous even when one amount/date happens to match.
    source=next(iter(ledger.projection().captured_docs()))
    ledger.append(account_opened('second-bank','depository','Second','USD','2021-01-01',provenance=Provenance(source,1)))
    ledger.append(reference_event('second-bank','CHECK-A','2021-01-01',Source(source,1)))
    result=ingest(raw,ledger,'ambiguous-funding',mortgage(),'mortgage_statement')
    assert result.action=='awaiting' and not ledger.projection().instrument_allocations()


def test_independent_duplicate_source_witnesses_do_not_duplicate_money_or_allocations(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    first=ingest(raw,ledger,'loan-source-a',mortgage(),'mortgage_statement')
    second=ingest(raw,ledger,'loan-source-b',mortgage(),'mortgage_statement')
    assert first.doc_id!=second.doc_id
    proj=ledger.projection()
    assert len([r for r in proj.core._instrument_observations.values() if r['change'].kind==ObservationKind.MORTGAGE_COMPONENTS])==2
    assert len(proj.instrument_allocations())==1
    assert proj.spending_by_currency()=={'USD':Decimal('300')}
    assert len([m for m in proj.movements() if m.description=='PAY-A'])==2 # principal and escrow; bank description differs
    assert heal_instruments(ledger)==0


def test_conflicting_same_period_source_cannot_silently_corroborate(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    ingest(raw,ledger,'loan-source-a',mortgage(),'mortgage_statement')
    data=mortgage();data['closing_principal']=printed('800');data['principal_movements'][0]['amount']=printed('200')
    result=ingest(raw,ledger,'loan-conflicting-source',data,'mortgage_statement')
    assert result.action=='awaiting'
    proj=ledger.projection();assert proj.running_balance(reference_accounts(proj,'LOAN-A')[0])==Decimal('900')
    state=next(s for s in proj.instrument_component_states().values() if s.doc_id==result.doc_id)
    assert next(r for r in state.components if r.component=='principal_balance').disposition.value=='held'


def test_financial_sql_replay_current_knowledge_correction_retraction_and_historical_parity(tmp_path):
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    from viva.ledger.events import document_captured
    from viva.ledger.instruments import append_change
    from viva.ingest.instrument_observations import Operation
    from viva.ingest.instrument_contracts import SourcedDate,Source
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    first=ingest(raw,ledger,'loan-source',mortgage(),'mortgage_statement')
    reads=ReadStore.create(tmp_path/'read','synthetic-passphrase');reads.synchronize(ledger.store)
    held=reads.open_reader()
    def assert_sql():
        reads.synchronize(ledger.store)
        for horizon in ('2021-01-31','2021-02-28'):
            oracle=LedgerProjection(ledger.events(),as_of=horizon)
            with reads.open_reader() as revision:
                sql=SQLOverviewProjection(revision,horizon,projected_as_of=horizon)
                assert sql.account_restrictions()==oracle.account_restrictions()
                assert sql.spending_by_currency()==oracle.spending_by_currency()
                assert sql.instrument_allocations()==oracle.instrument_allocations()
                assert financial_statements(sql)['profit_loss']['by_currency']==financial_statements(oracle)['profit_loss']['by_currency']
    assert_sql()
    prior=next(r['change'] for r in ledger.projection().core._instrument_observations.values()
        if r['change'].kind==ObservationKind.MORTGAGE_COMPONENTS)
    data=mortgage();data['payments'][0].update(principal=printed('150'),interest=printed('150'))
    data['principal_movements'][0]['amount']=printed('150');data['closing_principal']=printed('850')
    doc='corrected-source';ledger.append(document_captured(doc,'corrected.pdf',100,'mortgage_statement',1,'2021-01-31'))
    facts=InstrumentReadFacts(doc,'mortgage_statement',1.0,parse_instrument_json(json.dumps(data),'mortgage_statement',doc),'USD')
    result=post_instrument(ledger,facts,prior_id=prior.observation_id)
    assert result.action=='posted'
    assert ledger.projection().spending_by_currency()=={'USD':Decimal('250')}
    assert_sql()
    corrected=next(r['change'] for r in ledger.projection().core._instrument_observations.values()
        if r['change'].prior_id==prior.observation_id)
    with pytest.raises(ValueError,match='frontier'):
        append_change(ledger,
            replace(corrected,observation_id='stale-correction'))
    retract=replace(corrected,observation_id='retract-corrected',operation=Operation.RETRACT,
        prior_id=corrected.observation_id,payload=None)
    append_change(ledger,retract);heal_instruments(ledger)
    assert not ledger.projection().instrument_allocations()
    assert not ledger.projection().is_seeded(result.account)
    assert any(row.family=='escrow' for row in ledger.projection().account_restrictions().values())
    assert_sql()
    assert SQLOverviewProjection(held,'2021-01-31').spending_by_currency()=={'USD':Decimal('300')}
    held.close();reads.close()
    with ReadStore.open(tmp_path/'read','synthetic-passphrase') as reopened:
        assert reopened.synchronize(ledger.store).state=='equal'
        with reopened.open_reader() as revision:
            assert SQLOverviewProjection(revision,'2021-02-28').spending_by_currency()==ledger.projection().spending_by_currency()


def test_corrected_predecessor_retires_future_financial_effects_and_reholds_gap(tmp_path):
    from viva.ledger.events import document_captured
    raw,ledger=setup(tmp_path)
    first=ingest(raw,ledger,'cd-jan',deposit_json(),'term_deposit_statement')
    second=deposit_json();second.update(start=printed('2021-02-01'),end=printed('2021-02-28'),
        opening=printed('1010'),closing=printed('1020'))
    second['movements'][0].update(dated=printed('2021-02-28'),reference=printed('INT-B'))
    later=ingest(raw,ledger,'cd-feb',second,'term_deposit_statement')
    from viva.read_store import ReadStore
    from viva.read_store.overview import SQLOverviewProjection
    reads=ReadStore.create(tmp_path/'future-read','synthetic-passphrase');reads.synchronize(ledger.store)
    prior=next(r['change'] for r in ledger.projection().core._instrument_observations.values()
        if r['change'].source.doc_id==first.doc_id)
    data=deposit_json();data['closing']=printed('1011');data['movements'][0]['amount']=printed('11')
    doc='cd-corrected';ledger.append(document_captured(doc,'corrected.pdf',100,'term_deposit_statement',1,'2021-01-31'))
    facts=InstrumentReadFacts(doc,'term_deposit_statement',1.0,parse_instrument_json(json.dumps(data),'term_deposit_statement',doc),'USD')
    post_instrument(ledger,facts,prior_id=prior.observation_id);heal_instruments(ledger)
    proj=ledger.projection();account=reference_accounts(proj,'CD-A')[0]
    assert proj.running_balance(account)==Decimal('1011')
    assert not any(m.description=='INT-B' for m in proj.movements())
    state=next(s for s in proj.instrument_component_states().values() if s.doc_id==later.doc_id)
    assert next(r for r in state.components if r.component=='deposit_balance').disposition.value=='held'
    reads.synchronize(ledger.store)
    with reads.open_reader() as revision:
        sql=SQLOverviewProjection(revision,'2021-02-28')
        assert sql.balance(account).amount==Decimal('1011')
        assert not any(m.description=='INT-B' for m in sql.movements())
        assert sql.account_restrictions()==proj.account_restrictions()
    reads.close()


def test_observation_and_financial_effect_batch_are_atomic_on_planner_error(tmp_path,monkeypatch):
    from viva.ingest import instrument_projector
    from viva.ledger.events import document_captured
    raw,ledger=setup(tmp_path)
    doc='atomic-source';ledger.append(document_captured(doc,'atomic.pdf',100,'term_deposit_statement',1,'2021-01-31'))
    facts=InstrumentReadFacts(doc,'term_deposit_statement',1.0,parse_instrument_json(json.dumps(deposit_json()),'term_deposit_statement',doc),'USD')
    original=instrument_projector._plan
    def broken(proj,change):
        for event in original(proj,change):
            yield event
            raise RuntimeError('synthetic planner interruption')
    monkeypatch.setattr(instrument_projector,'_plan',broken)
    before=len(list(ledger.events()))
    with pytest.raises(RuntimeError,match='planner interruption'):post_instrument(ledger,facts)
    assert len(list(ledger.events()))==before
    assert not ledger.projection().core._instrument_observations

@pytest.mark.parametrize('reverse',[False,True])
def test_explicit_continuing_escrow_survives_servicer_change_once_in_both_orders(tmp_path,reverse):
    raw,ledger=setup(tmp_path)
    old=mortgage();new=mortgage()
    new.update(identity=identity('LOAN-B'),start=printed('2021-02-01'),end=printed('2021-02-28'),
        opening_principal=printed('500'),closing_principal=printed('450'))
    new['identity']['institution']=printed('Replacement Servicer')
    new['principal_movements']=[{'kind':'principal_reduction','amount':printed('50'),
        'dated':printed('2021-02-15'),'reference':printed('PAY-B')}]
    new['payments']=[]
    new['escrow'].update(identity=identity('ESCROW-A'),opening=printed('200'),closing=printed('500'),
        movements=[{'kind':'deposit','amount':printed('300'),'dated':printed('2021-02-15'),'reference':printed('PAY-B')}])
    new['escrow']['identity']['institution']=printed('Replacement Servicer')
    rows=[('old-servicer',old),('new-servicer',new)]
    for label,data in reversed(rows) if reverse else rows:
        ingest(raw,ledger,label,data,'mortgage_statement')
    for proj in (ledger.projection(),LedgerProjection(ledger.events())):
        escrow=[a for a,r in proj.account_restrictions().items() if r.family=='escrow']
        assert len(escrow)==1
        assert proj.running_balance(escrow[0])==Decimal('500')
        assert len([m for m in proj.movements() if m.account==escrow[0]])==3
        assert proj.account_restrictions()[escrow[0]].status=='accepted'
    assert heal_instruments(ledger)==0


def test_printed_family_later_restricts_existing_ordinary_account_without_reopening(tmp_path):
    from viva.ledger.events import Provenance,account_opened,document_captured
    from viva.ledger.instruments import reference_event
    from viva.ingest.instrument_contracts import Source
    raw,ledger=setup(tmp_path)
    doc='earlier-source';ledger.append(document_captured(doc,'earlier.pdf',10,'checking_statement',1,'2020-12-31'))
    ledger.append(account_opened('ordinary-first','depository','CD-A','USD','2020-12-31',
        institution='Fixture Institution',account_names=['Synthetic Person'],provenance=Provenance(doc,1)))
    ledger.append(reference_event('ordinary-first','CD-A','2020-12-31',Source(doc,1)))
    assert 'ordinary-first' not in ledger.projection().account_restrictions()
    ingest(raw,ledger,'cd-recognized',deposit_json(),'term_deposit_statement')
    assert reference_accounts(ledger.projection(),'CD-A')==('ordinary-first',)
    assert ledger.projection().account_restrictions()['ordinary-first'].family=='term_deposit'
    assert sum(1 for e in ledger.events() if e.event_type=='AccountOpened' and e.body['account_id']=='ordinary-first')==1

@pytest.mark.parametrize('bank_first',[False,True])
def test_cd_funding_matches_only_explicit_bank_witness_and_interest_counts_once(tmp_path,bank_first):
    raw,ledger=setup(tmp_path)
    if bank_first:bank(raw,ledger,amount='1000',counterpart='CD-A',reference='CD-FUND-A')
    data=deposit_json();data.update(opening=printed('0'),closing=printed('1010'))
    data['movements'].insert(0,{'kind':'funding','amount':printed('1000'),'dated':printed('2021-01-15'),
        'reference':printed('CD-FUND-A'),'counterparty_reference':printed('CHECK-A')})
    ingest(raw,ledger,'cd-funded',data,'term_deposit_statement')
    if not bank_first:bank(raw,ledger,amount='1000',counterpart='CD-A',reference='CD-FUND-A')
    proj=ledger.projection()
    assert len(proj.transfer_links())==1
    assert proj.income_by_currency()=={'USD':Decimal('10')}
    assert proj.spending_by_currency()=={}
    assert proj.running_balance(reference_accounts(proj,'CD-A')[0])==Decimal('1010')
    assert heal_instruments(ledger)==0


def test_source_allocated_payment_is_not_reported_as_unknown_compound_payment(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    ingest(raw,ledger,'mortgage-source',mortgage(),'mortgage_statement')
    assert ledger.projection().undecomposed()['count']==0
    assert not any(m.component_spending is not None for m in ledger.projection().excluded_from_spending())

@pytest.mark.parametrize('settlement_first',[True,False])
def test_paid_off_loan_and_settlement_share_one_principal_transfer(tmp_path,settlement_first):
    raw,ledger=setup(tmp_path)
    initial=mortgage();initial.update(end=printed('2021-01-14'),closing_principal=printed('1000'),principal_movements=[],payments=[],escrow=None)
    ingest(raw,ledger,'old-loan-initial',initial,'mortgage_statement')
    settlement=refinance_json();settlement.update(dated=printed('2021-01-15'),old_closing_principal=printed('0'))
    paid=mortgage();paid.update(start=printed('2021-01-15'),end=printed('2021-01-15'),closing_principal=printed('0'),payments=[],escrow=None)
    paid['principal_movements']=[{'kind':'payoff','amount':printed('1000'),'dated':printed('2021-01-15'),'reference':printed('REFI-A')}]
    rows=[('settlement',settlement,'refinance_settlement'),('old-paid',paid,'mortgage_statement')]
    for label,data,kind in rows if settlement_first else reversed(rows):ingest(raw,ledger,label,data,kind)
    proj=ledger.projection();old=reference_accounts(proj,'LOAN-A')[0];new=reference_accounts(proj,'LOAN-B')[0]
    assert proj.running_balance(old)==0 and proj.running_balance(new)==Decimal('1000')
    assert len([m for m in proj.movements() if m.account==old])==1
    assert not proj.income_by_currency()
    assert heal_instruments(ledger)==0


def test_duplicate_financial_references_within_one_source_are_held(tmp_path):
    raw,ledger=setup(tmp_path)
    data=deposit_json();data['movements']*=2;data['closing']=printed('1020')
    result=ingest(raw,ledger,'duplicate-ref-source',data,'term_deposit_statement')
    assert result.action=='awaiting'
    assert not ledger.projection().is_seeded(result.account)
    assert not ledger.projection().movements()


def test_known_cd_family_is_restricted_during_its_first_source_period(tmp_path):
    raw,ledger=setup(tmp_path)
    result=ingest(raw,ledger,'cd-first-month',deposit_json(),'term_deposit_statement')
    historical=LedgerProjection(ledger.events(),as_of='2021-01-15')
    assert result.account in historical.account_restrictions()


def test_conflicting_explicit_contract_rate_holds_terms_and_preserves_valid_balance(tmp_path):
    raw,ledger=setup(tmp_path)
    data=deposit_json();data['terms']={'principal':printed('1000'),'opened':printed('2021-01-01'),
        'maturity':printed('2022-01-01'),'rate':printed('5.25%')}
    first=ingest(raw,ledger,'terms-first',data,'term_deposit_statement')
    data['terms']['rate']=printed('6.25%')
    second=ingest(raw,ledger,'terms-conflict',data,'term_deposit_statement')
    assert second.action=='awaiting'
    proj=ledger.projection()
    assert proj.running_balance(first.account)==Decimal('1010')
    for state in proj.instrument_component_states().values():
        if state.doc_id not in {first.doc_id,second.doc_id}:continue
        assert next(r for r in state.components if r.component=='deposit_terms').disposition.value=='held'
        assert next(r for r in state.components if r.component=='deposit_balance').disposition.value=='accepted'
