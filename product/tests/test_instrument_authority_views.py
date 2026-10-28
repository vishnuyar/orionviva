from dataclasses import replace
from decimal import Decimal
from time import monotonic
import pytest
from viva.read_store import ReadStore
from viva.read_store.instrument_authority import read_instrument_authority
from viva.read_store.instrument_authority_contracts import InstrumentRequest
from viva.ledger.instruments import reference_accounts
from test_instrument_projector_b import setup,ingest,bank,mortgage
from test_instrument_contracts import deposit_json,printed


def run(tmp_path,ledger,request):
    with ReadStore.create(tmp_path/'read','synthetic-passphrase') as store:
        store.synchronize(ledger.store)
        with store.open_reader() as revision:
            return read_instrument_authority(revision,request,deadline=monotonic()+2)


def test_terms_keep_principal_rate_assertions_and_current_balance_distinct(tmp_path):
    raw,ledger=setup(tmp_path)
    data=deposit_json()
    data['terms']={'principal':printed('1000'),'opened':printed('2021-01-01'),'maturity':printed('2022-01-01'),
        'rate':printed('5.25'),'rate_basis':'simple_nominal','rate_basis_source':{'page':1},
        'day_count':'actual_365','day_count_source':{'page':1},'compounding':printed('No compounding'),
        'withdrawal_restriction':printed('No withdrawal until maturity')}
    ingest(raw,ledger,'cd',data,'term_deposit_statement')
    account=reference_accounts(ledger.projection(),'CD-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('terms',account,'USD',as_of='2021-01-31'))
    values={f.claim:f.value for f in result.figures}
    assert values['deposit_contract_principal']=='1000'
    assert values['deposit_closing_balance']=='1010'
    assert values['deposit_nominal_rate']=='0.0525'
    assertions={a.claim:a.value for a in result.assertions}
    assert assertions['deposit_maturity']=='2022-01-01'
    assert assertions['deposit_rate_basis']=='simple_nominal'
    assert all(f.anchor_ids and f.observation_ids for f in result.figures)


def test_period_components_deduplicate_witnesses_and_require_complete_coverage(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'jan',deposit_json(),'term_deposit_statement')
    ingest(raw,ledger,'jan-second-witness',deposit_json(),'term_deposit_statement')
    account=reference_accounts(ledger.projection(),'CD-A')[0]
    request=InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='deposit')
    result=run(tmp_path,ledger,request)
    assert result.coverage[0].complete
    interest=next(f for f in result.figures if f.claim=='deposit_credited_interest')
    assert interest.value=='10' and len(interest.observation_ids)==2 and len(interest.anchor_ids)==2


def test_missing_period_never_becomes_zero(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'jan',deposit_json(),'term_deposit_statement')
    account=reference_accounts(ledger.projection(),'CD-A')[0]
    request=InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-02-28',grouping='month',component_set='deposit')
    result=run(tmp_path,ledger,request)
    assert not result.figures and not result.coverage[0].complete


def test_independently_held_payment_does_not_hide_accepted_principal(tmp_path):
    raw,ledger=setup(tmp_path)
    data=mortgage();data['payments'][0]['interest']=printed('201')
    ingest(raw,ledger,'loan',data,'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    request=InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='loan_principal')
    result=run(tmp_path,ledger,request)
    assert next(f.value for f in result.figures if f.claim=='principal_repayment')=='100'


def test_wrong_currency_and_deadline_refuse(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'jan',deposit_json(),'term_deposit_statement')
    account=reference_accounts(ledger.projection(),'CD-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('terms',account,'EUR',as_of='2021-01-31'))
    assert not result.figures and result.dispositions[0].disposition=='unavailable'


@pytest.mark.parametrize('body',[{'view':'terms','account':'a','currency':'USD','as_of':'2021-01-01','field':'arbitrary'},
    {'view':'allocation','account':'a','currency':'USD','as_of':'2021-01-01','axis':'vehicle','target_premise_ref':'x'},
    {'view':'period_components','account':'a','currency':'USD','from':'2021-01-01','to':'2021-01-31','grouping':'month','component_set':'annual_summary'}])
def test_closed_request_rejects_unsupported_shapes(body):
    with pytest.raises(ValueError):InstrumentRequest.from_dict(body)


def test_held_principal_does_not_hide_independent_accepted_payment_and_escrow(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['closing_principal']=printed('900.01')
    ingest(raw,ledger,'loan',data,'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='payment_escrow'))
    assert next(f.value for f in result.figures if f.claim=='payment_total')=='600'
    assert next(f.value for f in result.figures if f.claim=='escrow_funding')=='300'
    assert not any(f.claim=='principal_repayment' for f in result.figures)


def test_tax_receipt_corroborates_one_cash_payment_and_keeps_property_reference(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'loan',mortgage(),'mortgage_statement')
    receipt={'authority':printed('Synthetic county'),'property_reference':printed('PROPERTY-A'),'tax_year':2021,
        'dated':printed('2021-01-20'),'reference':printed('TAX-A'),'amount':printed('100'),
        'status':'paid','tax_year_source':{'page':1},'status_source':{'page':1},'source_account_reference':printed('ESCROW-A')}
    ingest(raw,ledger,'tax',receipt,'property_tax_receipt')
    account=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('tax_payments',account,'USD',start='2021-01-01',end='2021-01-31',grouping='year'))
    figure=next(f for f in result.figures if f.claim=='tax_paid')
    assert figure.value=='100' and len(figure.observation_ids)==2 and len(figure.anchor_ids)==2
    assert next(a.value for a in result.assertions if a.claim=='property_identity')=='PROPERTY-A'
    assert 'tax_year:2021' in figure.component_ids


def test_refinance_old_zero_and_payoff_have_old_canonical_subject(tmp_path):
    from test_instrument_contracts import refinance_json
    raw,ledger=setup(tmp_path)
    old=mortgage();old.update(closing_principal=printed('0'),payments=None,escrow=None)
    old['principal_movements']=[{'kind':'payoff','amount':printed('1000'),'dated':printed('2021-01-31'),'reference':printed('OLD-PAYOFF')}]
    ingest(raw,ledger,'old-loan',old,'mortgage_statement')
    data=refinance_json();data['dated']=printed('2021-01-31')
    ingest(raw,ledger,'settlement',data,'refinance_settlement')
    old_account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    new_account=reference_accounts(ledger.projection(),'LOAN-B')[0]
    result=run(tmp_path,ledger,InstrumentRequest('refinances',new_account,'USD',start='2021-01-01',end='2021-01-31'))
    figures={f.claim:f for f in result.figures}
    assert figures['refinance_old_payoff'].account==old_account
    assert figures['refinance_old_zero'].account==old_account and figures['refinance_old_zero'].value=='0'
    assert figures['refinance_new_advance'].account==new_account
    assert {r.role:r.account for r in result.relationships}=={'refinance_old_loan':old_account,'refinance_new_loan':new_account}


def test_conflicting_availability_is_not_recertified_from_one_typed_field(tmp_path):
    from viva.ingest import instrument_contracts as c
    from viva.ingest.instrument_observations import ObservationChange,ObservationKind,Operation
    from viva.ledger.instruments import append_change
    raw,ledger=setup(tmp_path)
    data=deposit_json();data['terms']={'principal':printed('1000'),'opened':printed('2021-01-01'),
        'maturity':printed('2022-01-01'),'withdrawal_restriction':printed('Restricted until maturity')}
    result=ingest(raw,ledger,'certificate',data,'term_deposit_statement')
    account=reference_accounts(ledger.projection(),'CD-A')[0]
    source=c.Source(result.doc_id,1)
    append_change(ledger,ObservationChange('second-availability',account,ObservationKind.AVAILABILITY,c.SourcedDate('2021-01-01',source),
        Operation.CREATE,source,c.Availability(c.Family.DEPOSIT,c.Restriction.TERM,source)))
    response=run(tmp_path,ledger,InstrumentRequest('terms',account,'USD',as_of='2021-01-31'))
    assert not any(a.claim=='availability_restriction' for a in response.assertions)
    assert any(d.component=='availability_restriction' and d.disposition=='conflicted' for d in response.dispositions)
    assert any(f.claim=='deposit_contract_principal' for f in response.figures)


def test_tax_reference_collision_requires_canonical_clarification(tmp_path):
    from viva.ledger.events import account_opened
    from viva.ledger.instruments import reference_event
    from viva.ingest.instrument_contracts import Source
    raw,ledger=setup(tmp_path)
    captured=ingest(raw,ledger,'loan',mortgage(),'mortgage_statement')
    account=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    ledger.append(account_opened('other-escrow','depository','Other synthetic escrow','USD','2021-01-01'))
    ledger.append(reference_event('other-escrow','ESCROW-A','2021-01-01',Source(captured.doc_id,1)))
    result=run(tmp_path,ledger,InstrumentRequest('tax_payments',account,'USD',start='2021-01-01',end='2021-01-31',grouping='year'))
    assert not result.figures and result.dispositions[0].disposition=='unavailable'


def two_accepted_months(raw,ledger):
    import json
    from viva.ingest import capture_and_ingest,ReadResult
    from viva.ingest.statement import from_model_json
    bank(raw,ledger)
    first=ingest(raw,ledger,'loan-january',mortgage(),'mortgage_statement')
    data={'doc_type':'checking_statement','doc_type_confidence':1,
        'institution':'Fixture Bank','account_ref':'Fixture Checking','account_names':['Synthetic Person'],
        'source_account_ref':'CHECK-A','source_account_ref_page':1,
        'opening':{'amount_raw':'1400','date_raw':'2021-02-01','page':1},
        'closing':{'amount_raw':'800','date_raw':'2021-02-28','page':1},
        'transactions':[{'amount_raw':'600','balance_effect':'decrease','date_raw':'2021-02-15','page':1,
            'description':'Printed source payment','source_reference':'PAY-B','counterparty_reference':'LOAN-A'}]}
    def read(blob,doc_id):
        facts,error=from_model_json(json.dumps(data),doc_id,'en-US','USD')
        assert error is None
        return ReadResult('checking_statement',1.0,facts,source_locale='en-US')
    capture_and_ingest(raw,ledger,b'bank-february',read)
    second=mortgage()
    second.update(start=printed('2021-02-01'),end=printed('2021-02-28'),opening_principal=printed('900'),closing_principal=printed('800'))
    second['principal_movements'][0].update(dated=printed('2021-02-15'),reference=printed('PAY-B'))
    second['payments'][0].update(dated=printed('2021-02-15'),reference=printed('PAY-B'))
    second['escrow'].update(opening=printed('200'),closing=printed('500'))
    second['escrow']['movements']=second['escrow']['movements'][:1]
    second['escrow']['movements'][0].update(dated=printed('2021-02-15'),reference=printed('PAY-B'))
    last=ingest(raw,ledger,'loan-february',second,'mortgage_statement')
    return first,last


def test_monthly_principal_endpoints_keep_each_accepted_source_month(tmp_path):
    raw,ledger=setup(tmp_path);first,last=two_accepted_months(raw,ledger)
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-02-28',grouping='month',component_set='loan_principal'))
    stocks={(figure.claim,figure.as_of):(figure.value,{anchor.document_id for anchor in result.anchors if anchor.anchor_id in figure.anchor_ids})
        for figure in result.figures if figure.claim in {'loan_opening_principal','loan_closing_principal'}}
    assert stocks=={('loan_opening_principal','2021-01-01'):('1000',{first.doc_id}),
        ('loan_closing_principal','2021-01-31'):('900',{first.doc_id}),
        ('loan_opening_principal','2021-02-01'):('900',{last.doc_id}),
        ('loan_closing_principal','2021-02-28'):('800',{last.doc_id})}


def test_monthly_escrow_endpoints_keep_each_accepted_source_month(tmp_path):
    raw,ledger=setup(tmp_path);first,last=two_accepted_months(raw,ledger)
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-02-28',grouping='month',component_set='payment_escrow'))
    stocks={(figure.claim,figure.as_of):figure.value for figure in result.figures
        if figure.claim in {'escrow_opening_balance','escrow_closing_balance'}}
    assert stocks=={('escrow_opening_balance','2021-01-01'):'0',('escrow_closing_balance','2021-01-31'):'200',
        ('escrow_opening_balance','2021-02-01'):'200',('escrow_closing_balance','2021-02-28'):'500'}


def test_source_payoff_is_not_a_scheduled_principal_reduction(tmp_path):
    raw,ledger=setup(tmp_path);bank(raw,ledger)
    data=mortgage();data['closing_principal']=printed('0')
    data['principal_movements'].append({'kind':'payoff','amount':printed('900'),'dated':printed('2021-01-31'),'reference':printed('SOURCE-PAYOFF')})
    ingest(raw,ledger,'loan-payoff',data,'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-01-31',grouping='month',component_set='loan_principal'))
    assert next(f.value for f in result.figures if f.claim=='principal_repayment')=='100'
    payoff=next(f for f in result.figures if f.claim=='principal_payoff')
    assert payoff.value=='900' and payoff.account==account
    assert payoff.start=='2021-01-01' and payoff.end=='2021-01-31'


def test_monthly_endpoint_pools_all_witness_observation_lineage(tmp_path):
    raw,ledger=setup(tmp_path);first,last=two_accepted_months(raw,ledger)
    repeated=ingest(raw,ledger,'january-independent-witness',mortgage(),'mortgage_statement')
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-02-28',grouping='month',component_set='loan_principal'))
    january=next(f for f in result.figures if f.claim=='loan_closing_principal' and f.as_of=='2021-01-31')
    february=next(f for f in result.figures if f.claim=='loan_opening_principal' and f.as_of=='2021-02-01')
    assert len(january.observation_ids)==2 and len(january.anchor_ids)==2
    assert {a.document_id for a in result.anchors if a.anchor_id in january.anchor_ids}=={first.doc_id,repeated.doc_id}
    assert len(february.observation_ids)==1 and {a.document_id for a in result.anchors if a.anchor_id in february.anchor_ids}=={last.doc_id}


def two_same_page_tax_events(*,reverse=False,ambiguous=False):
    data=mortgage();data['escrow']['closing']=printed('100')
    first=data['escrow']['movements'][1]
    second={**first,'reference':printed('TAX-A' if ambiguous else 'TAX-B'),'property_reference':printed('PROPERTY-B'),'tax_year':2020}
    data['escrow']['movements'].append(second)
    if reverse:data['escrow']['movements']=list(reversed(data['escrow']['movements']))
    return data


def tax_event_fields(result):
    fields={}
    for assertion in result.assertions:
        if assertion.claim in {'tax_payment_reference','tax_payment_date','property_identity'}:
            assert assertion.record_association
            fields.setdefault(assertion.record_association,{})[assertion.claim]=assertion.value
    return fields


def test_same_statement_equal_tax_events_keep_permutation_invariant_associations(tmp_path):
    associated=[]
    for index,reverse in enumerate((False,True)):
        raw,ledger=setup(tmp_path/str(index))
        ingest(raw,ledger,'two-tax-source',two_same_page_tax_events(reverse=reverse),'mortgage_statement')
        account=reference_accounts(ledger.projection(),'ESCROW-A')[0]
        result=run(tmp_path/str(index),ledger,InstrumentRequest('tax_payments',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))
        fields=tax_event_fields(result)
        assert len(fields)==2 and len(result.figures)==2 and len({f.record_id for f in result.figures})==2
        assert len({a.receipt_id for a in result.assertions})==6
        assert {f.record_association for f in result.figures}==set(fields)
        assert all(f.value=='100' for f in result.figures)
        assert {(r['tax_payment_reference'],r['property_identity'],r['tax_payment_date']) for r in fields.values()}=={
            ('TAX-A','PROPERTY-A','2021-01-20'),('TAX-B','PROPERTY-B','2021-01-20')}
        associated.append(fields)
    assert associated[0]==associated[1]


def test_tax_association_deduplicates_independent_witnesses_and_pools_lineage(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'first-tax-witness',two_same_page_tax_events(),'mortgage_statement')
    ingest(raw,ledger,'second-tax-witness',two_same_page_tax_events(reverse=True),'mortgage_statement')
    account=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('tax_payments',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))
    assert len(result.figures)==2 and len(tax_event_fields(result))==2
    assert all(f.value=='100' and len(f.observation_ids)==2 for f in result.figures)
    assert all(len(a.observation_ids)==2 and len(a.anchor_ids)==2 for a in result.assertions)


def test_ambiguous_same_source_financial_tax_identity_refuses_association(tmp_path):
    raw,ledger=setup(tmp_path)
    ingest(raw,ledger,'ambiguous-tax-source',two_same_page_tax_events(ambiguous=True),'mortgage_statement')
    account=reference_accounts(ledger.projection(),'ESCROW-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('tax_payments',account,'USD',start='2021-01-01',end='2021-01-31',grouping='none'))
    assert not result.figures and not result.assertions


def test_complete_accepted_empty_month_tax_set_emits_derived_zero(tmp_path):
    raw,ledger=setup(tmp_path);first,last=two_accepted_months(raw,ledger)
    account=reference_accounts(ledger.projection(),'LOAN-A')[0]
    result=run(tmp_path,ledger,InstrumentRequest('period_components',account,'USD',start='2021-01-01',end='2021-02-28',grouping='month',component_set='payment_escrow'))
    taxes={f.start:f for f in result.figures if f.claim=='tax_paid'}
    assert {period:f.value for period,f in taxes.items()}=={'2021-01-01':'100','2021-02-01':'0'}
    zero=taxes['2021-02-01']
    assert zero.calculation_context=='accepted_empty_tax_event_set_v1'
    assert zero.grade=='corroborated' and zero.component_ids==('escrow_balance',)
    assert {a.document_id for a in result.anchors if a.anchor_id in zero.anchor_ids}=={last.doc_id}
    assert taxes['2021-01-01'].calculation_context is None
