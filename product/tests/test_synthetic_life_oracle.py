"""Hand-calculated oracle tests; corpus mutation checks take an explicit ledger path."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('life_oracle',ROOT/'scripts/verify_synthetic_life_5y.py')
oracle=importlib.util.module_from_spec(spec)
spec.loader.exec_module(oracle)


def event(ident,kind,amount,**extra):
    return dict(id=ident,date='2021-01-28',account_ref='BROKER-A',kind=kind,
                amount=amount,currency='USD',transfer_ref='',counterpart_ref='',**extra)


def test_fifo_replays_partial_lots_and_uses_sold_basis():
    # Two differently priced lots: selling 3 consumes 2 at $10 and 1 at $13.
    events=[event('E1','buy','-20.00',security='AAPL',units='2',unit_price='10'),
            event('E2','buy','-26.00',security='AAPL',units='2',unit_price='13'),
            event('E3','sell','45.00',security='AAPL',units='3',unit_price='15',realized_gain='12.00',cost_basis='33.00')]
    assert oracle.verify_fifo(events)=={'AAPL':(oracle.D('1'),oracle.D('13'))}
    wrong=deepcopy(events);wrong[-1]['realized_gain']='11.99'
    with pytest.raises(oracle.VerificationError,match='FIFO realized gain'):
        oracle.verify_fifo(wrong)
    wrong=deepcopy(events);wrong[-1]['units']='5';wrong[-1]['amount']='75'
    with pytest.raises(oracle.VerificationError,match='uncovered sale'):
        oracle.verify_fifo(wrong)


def test_fifo_rejects_one_unit_even_with_self_consistent_cash():
    events=[event('E1','sell','30.00',security='AAPL',units='3',unit_price='10',realized_gain='0.00')]
    with pytest.raises(oracle.VerificationError,match='uncovered sale'):
        oracle.verify_fifo(events,[dict(security='AAPL',units='2',cost_basis='20')])


def test_transfer_counterpart_and_cent_are_independent_checks():
    a=event('E1','transfer','-20');a.update(account_ref='CHECK-A',counterpart_ref='SAVE-A',transfer_ref='X')
    b=event('E2','transfer','20');b.update(account_ref='SAVE-A',counterpart_ref='CHECK-A',transfer_ref='X')
    assert len(oracle.verify_transfers([a,b]))==1
    wrong=deepcopy(b);wrong['counterpart_ref']='BROKER-A'
    with pytest.raises(oracle.VerificationError,match='counterpart'):
        oracle.verify_transfers([a,wrong])
    wrong=deepcopy(b);wrong['amount']='20.01'
    with pytest.raises(oracle.VerificationError,match='amounts'):
        oracle.verify_transfers([a,wrong])


def loan_fixture():
    facts=dict(opening='630000',closing='629277.37',nominal_note_rate='5.25',interest='2756.25',
               principal='722.63',principal_and_interest='3478.88',remaining_term='359',
               payment_number='1',escrow_opening='0',escrow_deposit='916.67',
               property_tax_disbursement='0',escrow_closing='916.67',payment='4395.55')
    doc=dict(id='D1',family='mortgage',account_ref='LOAN-A',period_end='2021-01-31',facts=facts)
    a=event('E1','mortgage_payment','-4395.55');a.update(account_ref='CHECK-A',counterpart_ref='LOAN-A',transfer_ref='M1')
    b=event('E2','principal_payment','-722.63');b.update(account_ref='LOAN-A',counterpart_ref='CHECK-A',transfer_ref='M1')
    return doc,[a,b]


def test_mortgage_uses_principal_and_interest_independently_of_cash_bridge():
    doc,events=loan_fixture()
    oracle.verify_loans([doc],events,False)
    # Change both principal effect and ending balance: balance arithmetic still
    # holds, but amortization must reject a one-cent incorrect principal split.
    doc['facts']['principal']='722.64';doc['facts']['closing']='629277.36'
    events[1]['amount']='-722.64'
    with pytest.raises(oracle.VerificationError,match='principal'):
        oracle.verify_loans([doc],events,False)


def test_missing_and_empty_sources_fail_closed():
    for source in ({},dict(schema_version='synthetic-life-v1',accounts=[],events=[],documents=[])):
        with pytest.raises(oracle.VerificationError):
            oracle.verify_ledger(source)


def test_decimal_inputs_reject_float_and_nonfinite():
    for value in (0.1,'NaN','Infinity',True):
        with pytest.raises(oracle.VerificationError):
            oracle.D(value)


@pytest.mark.skipif(not os.environ.get('SYNTHETIC_LIFE_LEDGER'),reason='Set SYNTHETIC_LIFE_LEDGER to check a separately generated full corpus')
def test_complete_external_corpus_and_required_mutations():
    source=json.loads(Path(os.environ['SYNTHETIC_LIFE_LEDGER']).read_text())
    assert oracle.verify_ledger(source)['documents']==794
    assert set(oracle.mutation_checks(source))=={'cent','unit','counterpart','payoff','class','empty','missing'}


def printed_fixture():
    opening=dict(security='AAPL',units='3.00000000',unit_price='9.00',market_value='27.00',cost_basis='24.00',exposure_class='equity',vehicle='individual_security')
    closing=dict(security='AAPL',units='1.00000000',unit_price='10.00',market_value='10.00',cost_basis='8.00',exposure_class='equity',vehicle='individual_security')
    doc=dict(id='D0001',account_ref='BROKER-A',currency='USD',locale='en-US',period_start='2021-01-01',period_end='2021-01-31',as_of='2021-01-31',facts=dict(opening_cash='100.00',cash='119.75',total='129.75',opening_positions=[opening],positions=[closing]))
    events=[dict(id='E000001',date='2021-01-28',kind='sell',amount='19.75',description='Sell AAPL settled trade',
                 transfer_ref='X-TRANSFER',counterpart_ref='CHECK-A',security='AAPL',units='2.00000000',
                 unit_price='10.00',cost_basis='16.00',realized_gain='3.75',fee='0.25')]
    # Security names intentionally wrap and include punctuation. Numeric fields
    # belong to their specific opening/closing row and transaction labels.
    text='''Document D0001 | Account reference BROKER-A | USD | en-US
Period 2021-01-01 to 2021-01-31 | As of 2021-01-31
Opening cash: 100.00
Cash: 119.75
Total: 129.75
Opening holdings - synthetic prices
Security Units Unit price Market value Cost basis
AAPL Apple
Inc. 3.00000000 9.00 27.00 24.00 Exposure class: equity; Vehicle: individual_security
Closing holdings - synthetic prices
Security Units Unit price Market value Cost basis
AAPL Apple Inc. 1.00000000 10.00 10.00 8.00 Exposure class: equity; Vehicle: individual_security
Transactions - signed effect
E000001 / 2021-01-28
Sell AAPL settled trade | Kind sell | Link X-TRANSFER | Counterpart CHECK-A |
Security AAPL Apple Inc. | Units 2.00000000 | Unit price 10.00 |
Cost basis 16.00 | Realized gain 3.75 | Fee 0.25
19.75
'''
    return doc,events,text


def test_printed_holdings_accept_full_names_and_both_boundaries():
    doc,events,text=printed_fixture()
    oracle.verify_printed_text(text,doc,events)


@pytest.mark.parametrize(('old','new','message'),[
    ('Document D0001','Document D0002','header'),
    ('As of 2021-01-31','As of 2021-01-30','as-of'),
    ('3.00000000 9.00','4.00000000 9.00','opening holdings'),
    ('1.00000000 10.00','2.00000000 10.00','closing holdings'),
    ('Exposure class: equity; Vehicle: individual_security','Exposure class: bond; Vehicle: individual_security','holdings'),
    ('Vehicle: individual_security','Vehicle: mutual_fund','holdings'),
    ('Opening holdings','Wrong opening header','Opening holdings'),
    ('Fee 0.25','Fee 0.24','Fee'),
    ('Realized gain 3.75','Realized gain 3.76','Realized gain'),
    ('Counterpart CHECK-A','Counterpart SAVE-A','counterpart'),
    ('Link X-TRANSFER','Link X-WRONG','counterpart'),
    ('Opening cash: 100.00','Opening cash: 100.001','printed field'),
    ('Cost basis 16.00','Cost basis 16.01','Cost basis'),
    ('Unit price 10.00 |','Unit price 10.01 |','Unit price'),
    ('\n19.75\n','\n16.00\n','cash/balance effect'),
])
def test_printed_source_mutations_fail_by_field(old,new,message):
    doc,events,text=printed_fixture()
    with pytest.raises(oracle.VerificationError,match=message):
        oracle.verify_printed_text(text.replace(old,new),doc,events)


def test_expected_dispositions_cover_each_source_without_product_imports():
    docs=[dict(id=f'D{i}',file=f'{i}.pdf',family=family,account_ref='SYNTHETIC',events=[])
          for i,family in enumerate(oracle.COUNTS)]
    for d in docs:
        d['facts']={'positions':[],'cash':'0','total':'0'}
    result=oracle.expected_document_dispositions({'documents':docs})
    assert len(result)==12
    assert all(d['expected_read_status']=='supported' for d in result)
    assert {d['family'] for d in result}==set(oracle.COUNTS)


@pytest.mark.parametrize(('security','exposure','vehicle'),[
    ('FXNAX','equity','mutual_fund'),
    ('FSKAX','bond','mutual_fund'),
    ('AAPL','equity','mutual_fund'),
    ('MSFT','equity','individual_security'),
])
def test_source_classification_fixed_instrument_contract(security,exposure,vehicle):
    p=dict(security=security,exposure_class=exposure,vehicle=vehicle)
    if security=='MSFT':
        oracle.verify_classifications([p],'handwritten seed')
    else:
        with pytest.raises(oracle.VerificationError,match='classification'):
            oracle.verify_classifications([p],'handwritten seed')


@pytest.fixture
def complete_source():
    path=os.environ.get('SYNTHETIC_LIFE_LEDGER')
    if not path:
        pytest.skip('Set SYNTHETIC_LIFE_LEDGER for independent full-source controls')
    return json.loads(Path(path).read_text())


def test_source_completeness_rejects_every_required_field_control(complete_source):
    outcomes=oracle.source_completeness_mutation_checks(complete_source)
    targets=oracle.completeness_field_targets(complete_source)
    assert len(outcomes)==2*len(targets)
    keys={path[-1] for label,path in targets}
    assert {'opened','restriction','restriction_text','day_count','convention_definition',
            'nominal_annual_rate','nominal_note_rate','rate_basis','rate_type','origination_date',
            'origination_date_basis','original_term_months','original_principal','disclosure_apr_status',
            'escrow_account_ref','escrow_restriction','escrow_continuity','escrow_components',
            'source_account_ref','destination_account_ref','property_ref','tax_year','source_event_id',
            'payment_date','payment_date_basis','payment_reference','paid_status','source_escrow_account_ref',
            'fee_payment_reference','funding_reference','borrower_contribution_reference','sources_total',
            'uses_total','financed_fees','fee_items','retirement_contribution_ref','contribution_ref'}<=keys


def test_escrow_is_one_restricted_source_subaccount_and_not_extra_cash(complete_source):
    result=oracle.verify_source_completeness(complete_source)
    assert result=={'primary_source_identities':22,'source_subaccounts':1}
    bad=deepcopy(complete_source)
    bad['accounts'].append(dict(ref='ESCROW-A',kind='depository'))
    with pytest.raises(oracle.VerificationError,match='22 primary'):
        oracle.verify_source_completeness(bad)
    bad=deepcopy(complete_source)
    bad['source_subaccounts'].append(deepcopy(bad['source_subaccounts'][0]))
    with pytest.raises(oracle.VerificationError,match='Exactly one'):
        oracle.verify_source_completeness(bad)


def test_note_rate_cannot_be_supplied_as_disclosure_apr(complete_source):
    source=deepcopy(complete_source)
    doc=next(d for d in source['documents'] if d['family']=='mortgage')
    doc['facts']['apr']=doc['facts']['nominal_note_rate']
    with pytest.raises(oracle.VerificationError,match='APR mislabeled'):
        oracle.verify_source_completeness(source)


def test_wrong_borrower_fee_funding_rejected_even_when_sources_and_uses_balance(complete_source):
    source=deepcopy(complete_source)
    f=next(d['facts'] for d in source['documents'] if d['family']=='refinance')
    f['fee_items'][0]['amount']='1999.99'
    f['borrower_contribution']='2999.99'
    f['sources_total']=f['uses_total']='614755.65'
    with pytest.raises(oracle.VerificationError,match='borrower contribution'):
        oracle.verify_source_completeness(source)


def test_old_frozen_source_fails_new_gate_and_financial_history_is_preserved(complete_source):
    path=os.environ.get('SYNTHETIC_LIFE_PREVIOUS_LEDGER')
    if not path:
        pytest.skip('Set SYNTHETIC_LIFE_PREVIOUS_LEDGER for old-freeze counterfactual')
    old=json.loads(Path(path).read_text())
    with pytest.raises(oracle.VerificationError):
        oracle.verify_source_completeness(old)
    comparison=oracle.compare_financial_history(old,complete_source)
    assert comparison['events_preserved']==3531
    assert comparison['primary_identities_preserved']==22
    assert comparison['document_identities_preserved']==794
    assert comparison['replacement_original_principal_terms_corrected']==36
    altered=deepcopy(complete_source)
    altered['events'][0]['amount']='0.01'
    with pytest.raises(oracle.VerificationError,match='changed financial events'):
        oracle.compare_financial_history(old,altered)


def test_actual_pdf_text_rejects_every_source_completeness_field(complete_source):
    import subprocess
    root=os.environ.get('SYNTHETIC_LIFE_PDF_ROOT')
    executable=os.environ.get('ORACLE_PDF_PYTHON')
    if not root or not executable:
        pytest.skip('Set SYNTHETIC_LIFE_PDF_ROOT and ORACLE_PDF_PYTHON for actual PDF-text controls')
    indexes={path[1] for label,path in oracle.completeness_field_targets(complete_source) if path[0]=='documents'}
    requests=[{'id':complete_source['documents'][i]['id'],'file':str(Path(root)/complete_source['documents'][i]['file'])} for i in sorted(indexes)]
    program='''import sys,json,fitz
result={}
for item in json.load(sys.stdin):
    with fitz.open(item['file']) as pdf:
        result[item['id']]='\\n'.join(page.get_text() for page in pdf)
print(json.dumps(result))
'''
    extracted=subprocess.run([executable,'-c',program],input=json.dumps(requests),capture_output=True,text=True,check=True)
    outcomes=oracle.printed_completeness_mutation_checks(complete_source,root,json.loads(extracted.stdout))
    expected={f'{label}:{operation}' for label,path in oracle.completeness_field_targets(complete_source) if path[0]=='documents' for operation in ('missing','changed')}
    assert set(outcomes)==expected


@pytest.mark.parametrize('suffix',['EXTRA',' now unrestricted'])
def test_printed_scalar_value_cannot_be_satisfied_by_prefix(suffix):
    doc,events,text=printed_fixture()
    with pytest.raises(oracle.VerificationError,match='printed field'):
        oracle.verify_printed_text(text.replace('Opening cash: 100.00','Opening cash: 100.00'+suffix),doc,events)


CD_CONTRADICTIONS=[
    ('restriction_text','Principal and credited interest are unrestricted before redemption and may be withdrawn to SAVE-A.'),
    ('restriction_text','Principal and credited interest are not restricted until redemption; transfer them to SAVE-A at any time.'),
    ('convention_definition','Fictional twelve equal month year: principal times nominal annual percentage rate divided by 1200; whole and partial month schedules supported. Not actual_365 or actual_360.'),
    ('convention_definition','Fictional twelve-equal-month year; each complete credited month earns principal times nominal annual percentage rate divided by 1200; only whole-month schedules supported. Not actual_365 or actual_360. Partial-month schedules are also supported.'),
]


@pytest.mark.parametrize('ref',['CD-A','CD-B','CD-C','CD-D'])
@pytest.mark.parametrize(('field','contradiction'),CD_CONTRADICTIONS)
def test_closed_cd_disclosure_rejects_opposites_across_complete_lifecycle(complete_source,ref,field,contradiction):
    bad=deepcopy(complete_source)
    witnesses=[d for d in bad['documents'] if d['account_ref']==ref]
    assert {d['family'] for d in witnesses}=={'cd-opening','cd','cd-maturity'}
    for d in witnesses:
        d['facts'][field]=contradiction
    with pytest.raises(oracle.VerificationError):
        oracle.verify_source_completeness(bad)


@pytest.fixture(scope='module')
def actual_disclosure_texts():
    import subprocess
    source_path=os.environ.get('SYNTHETIC_LIFE_LEDGER')
    root=os.environ.get('SYNTHETIC_LIFE_PDF_ROOT')
    executable=os.environ.get('ORACLE_PDF_PYTHON')
    if not source_path or not root or not executable:
        pytest.skip('Set source, PDF root and extraction runtime for actual disclosure controls')
    source=json.loads(Path(source_path).read_text())
    docs=[d for d in source['documents'] if d['family'] in {'cd-opening','cd','cd-maturity','retirement'}]
    requests=[dict(id=d['id'],file=str(Path(root)/d['file'])) for d in docs]
    program='''import sys,json,fitz
result={}
for item in json.load(sys.stdin):
    with fitz.open(item['file']) as pdf:
        result[item['id']]='\\n'.join(page.get_text() for page in pdf)
print(json.dumps(result))
'''
    result=subprocess.run([executable,'-c',program],input=json.dumps(requests),capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


@pytest.mark.parametrize('ref',['CD-A','CD-B','CD-C','CD-D'])
@pytest.mark.parametrize(('field','contradiction'),CD_CONTRADICTIONS)
def test_actual_cd_pdf_disclosures_cannot_be_authenticated_by_matching_false_ledger(complete_source,actual_disclosure_texts,ref,field,contradiction):
    events={e['id']:e for e in complete_source['events']}
    witnesses=[d for d in complete_source['documents'] if d['account_ref']==ref]
    assert {d['family'] for d in witnesses}=={'cd-opening','cd','cd-maturity'}
    for d in witnesses:
        text=actual_disclosure_texts[d['id']]
        evidence=[events[e] for e in d['events']]
        oracle.verify_printed_text(text,d,evidence)
        compact=oracle.compact_source_text(text)
        assert d['facts'][field] in compact
        altered=deepcopy(d)
        altered['facts'][field]=contradiction
        mutated=compact.replace(d['facts'][field],contradiction)
        with pytest.raises(oracle.VerificationError):
            oracle.verify_printed_text(mutated,altered,evidence)


@pytest.mark.parametrize('ref',['RET-A','RET-B','RET-C'])
def test_adjacent_allocation_disclosure_cannot_assert_no_drift(complete_source,ref):
    bad=deepcopy(complete_source)
    for d in bad['documents']:
        if d['account_ref']==ref:
            d['facts']['allocation_policy']='Contribution target only; market values never drift'
    with pytest.raises(oracle.VerificationError):
        oracle.verify_ledger(bad)


@pytest.mark.parametrize('ref',['RET-A','RET-B','RET-C'])
def test_actual_allocation_disclosure_cannot_match_a_false_ledger(complete_source,actual_disclosure_texts,ref):
    events={e['id']:e for e in complete_source['events']}
    for d in complete_source['documents']:
        if d['account_ref']!=ref:
            continue
        evidence=[events[e] for e in d['events']]
        text=actual_disclosure_texts[d['id']]
        oracle.verify_printed_text(text,d,evidence)
        altered=deepcopy(d)
        altered['facts']['allocation_policy']='Contribution target only; market values never drift'
        mutated=oracle.compact_source_text(text).replace(d['facts']['allocation_policy'],altered['facts']['allocation_policy'])
        with pytest.raises(oracle.VerificationError):
            oracle.verify_printed_text(mutated,altered,evidence)


ORIGINAL_APR_BAD_FIELDS=[
    {'disclosure_apr':None},
    {'disclosure_apr':'5.26'},
    {'disclosure_apr_status':None},
    {'disclosure_apr_status':'unavailable'},
    {'disclosure_apr_status':'computed_legal_disclosure'},
    {'disclosure_apr_basis':None},
    {'disclosure_apr_basis':'Computed legal lender disclosure from source finance charges.'},
    {'disclosure_apr_basis':'Owner-specified fictional scenario input; a computed legal lender disclosure or real offer.'},
    {'apr':'5.25'},
    {'disclosure_apr':None,'annual_percentage_rate':'5.25'},
]
REPLACEMENT_APR_BAD_FIELDS=[
    {'disclosure_apr':'4.25'},
    {'disclosure_apr_status':'owner_specified_fictional_input','disclosure_apr':'4.25','disclosure_apr_basis':'Owner-specified fictional scenario input; not a computed legal lender disclosure or real offer.'},
    {'disclosure_apr_status':'computed_legal_disclosure','disclosure_apr':'4.25'},
    {'apr':'4.25'},
    {'annual_percentage_rate':'4.25'},
]


def changed_fields(facts,changes):
    for key,value in changes.items():
        if value is None:
            facts.pop(key,None)
        else:
            facts[key]=value


def test_original_apr_successor_is_accepted_with_independent_note_rates(complete_source):
    assert oracle.verify_ledger(complete_source)['documents']==794
    old=[d for d in complete_source['documents'] if d['family']=='mortgage' and d['account_ref']=='LOAN-A']
    replacement=[d for d in complete_source['documents'] if d['account_ref']=='LOAN-B' and d['family'] in {'mortgage','refinance'}]
    assert len(old)==24 and len(replacement)==37
    assert all(d['facts']['disclosure_apr']=='5.25' and d['facts']['nominal_note_rate']=='5.25' for d in old)
    assert all(d['facts']['disclosure_apr_status']=='unavailable' and 'disclosure_apr' not in d['facts'] and d['facts']['nominal_note_rate']=='4.25' for d in replacement)


@pytest.mark.parametrize('changes',ORIGINAL_APR_BAD_FIELDS)
def test_original_apr_critical_source_fields_are_closed(complete_source,changes):
    bad=deepcopy(complete_source)
    for d in bad['documents']:
        if d['family']=='mortgage' and d['account_ref']=='LOAN-A':
            changed_fields(d['facts'],changes)
    with pytest.raises(oracle.VerificationError):
        oracle.verify_source_completeness(bad)


@pytest.mark.parametrize('changes',REPLACEMENT_APR_BAD_FIELDS)
def test_replacement_apr_cannot_be_inferred_or_misassigned(complete_source,changes):
    bad=deepcopy(complete_source)
    for d in bad['documents']:
        if d['account_ref']=='LOAN-B' and d['family'] in {'mortgage','refinance'}:
            changed_fields(d['facts'],changes)
    with pytest.raises(oracle.VerificationError):
        oracle.verify_source_completeness(bad)


@pytest.fixture(scope='module')
def actual_mortgage_texts():
    import subprocess
    path=os.environ.get('SYNTHETIC_LIFE_LEDGER');root=os.environ.get('SYNTHETIC_LIFE_PDF_ROOT');executable=os.environ.get('ORACLE_PDF_PYTHON')
    if not path or not root or not executable:
        pytest.skip('Set source, PDF root and extraction runtime for actual mortgage controls')
    source=json.loads(Path(path).read_text())
    requests=[dict(id=d['id'],file=str(Path(root)/d['file'])) for d in source['documents'] if d['family'] in {'mortgage','refinance'}]
    program='''import sys,json,fitz
result={}
for item in json.load(sys.stdin):
    with fitz.open(item['file']) as pdf:
        result[item['id']]='\\n'.join(p.get_text() for p in pdf)
print(json.dumps(result))
'''
    result=subprocess.run([executable,'-c',program],input=json.dumps(requests),capture_output=True,text=True,check=True)
    return json.loads(result.stdout)


def mutate_printed_scalar_fields(text,doc,changes):
    compact=oracle.compact_source_text(text)
    altered=deepcopy(doc)
    for key,value in changes.items():
        label=key.replace('_',' ').capitalize()+': '
        if key in altered['facts']:
            target=label+str(altered['facts'][key]);assert target in compact
            compact=compact.replace(target,'' if value is None else label+value,1)
        elif value is not None:
            compact=compact.replace('Opening:',label+value+' Opening:',1)
        changed_fields(altered['facts'],{key:value})
    return compact,altered


@pytest.mark.parametrize('changes',ORIGINAL_APR_BAD_FIELDS)
def test_actual_original_apr_text_cannot_match_a_false_ledger(complete_source,actual_mortgage_texts,changes):
    events={e['id']:e for e in complete_source['events']}
    for d in complete_source['documents']:
        if d['family']!='mortgage' or d['account_ref']!='LOAN-A':continue
        evidence=[events[e] for e in d['events']]
        oracle.verify_printed_text(actual_mortgage_texts[d['id']],d,evidence)
        text,altered=mutate_printed_scalar_fields(actual_mortgage_texts[d['id']],d,changes)
        with pytest.raises(oracle.VerificationError):
            oracle.verify_printed_text(text,altered,evidence)


@pytest.mark.parametrize('changes',REPLACEMENT_APR_BAD_FIELDS)
def test_actual_replacement_apr_text_cannot_match_a_false_ledger(complete_source,actual_mortgage_texts,changes):
    events={e['id']:e for e in complete_source['events']}
    for d in complete_source['documents']:
        if d['account_ref']!='LOAN-B' or d['family'] not in {'mortgage','refinance'}:continue
        evidence=[events[e] for e in d['events']]
        oracle.verify_printed_text(actual_mortgage_texts[d['id']],d,evidence)
        text,altered=mutate_printed_scalar_fields(actual_mortgage_texts[d['id']],d,changes)
        with pytest.raises(oracle.VerificationError):
            oracle.verify_printed_text(text,altered,evidence)


def test_apr_successor_preserves_entire_source_after_only_authorized_normalization(complete_source):
    path=os.environ.get('SYNTHETIC_LIFE_APR_PREVIOUS_LEDGER')
    if not path:
        pytest.skip('Set SYNTHETIC_LIFE_APR_PREVIOUS_LEDGER for exact APR successor comparison')
    previous=json.loads(Path(path).read_text())
    result=oracle.compare_apr_successor(previous,complete_source)
    assert result['complete_source_equal_after_authorized_normalization'] is True
    assert result['original_apr_documents_corrected']==24
    assert result['events_preserved']==3531
    assert result['primary_identities_preserved']==22
    assert result['document_identities_preserved']==794
    altered=deepcopy(complete_source)
    altered['events'][0]['description']+=' changed without authority'
    with pytest.raises(oracle.VerificationError,match='beyond the two authorized fields'):
        oracle.compare_apr_successor(previous,altered)
    with pytest.raises(oracle.VerificationError):
        oracle.verify_source_completeness(previous)


def test_mortgage_arithmetic_uses_note_rate_separately_from_supplied_apr(complete_source):
    altered=deepcopy(complete_source)
    for d in altered['documents']:
        if d['family']=='mortgage' and d['account_ref']=='LOAN-A':
            d['facts']['disclosure_apr']='9.99'
    # Changing the source APR must not alter the independently replayed note-rate
    # amortization; the separate owner-input source assertion rejects that APR.
    oracle.verify_loans(altered['documents'],altered['events'],True)
    with pytest.raises(oracle.VerificationError,match='owner-specified original APR'):
        oracle.verify_source_completeness(altered)
    loan=next(d for d in altered['documents'] if d['family']=='mortgage')
    loan['facts']['nominal_note_rate']='5.26'
    with pytest.raises(oracle.VerificationError,match='note rate'):
        oracle.verify_loans(altered['documents'],altered['events'],True)
