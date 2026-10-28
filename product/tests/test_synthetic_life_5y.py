"""Generator contract tests; the campaign oracle is independently implemented."""
from collections import Counter
from decimal import Decimal, Inexact, ROUND_DOWN, getcontext, localcontext
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.generate_synthetic_life_5y import build_life, generate, payment


GENERATOR_PATH=Path(__file__).resolve().parents[2]/'scripts/generate_synthetic_life_5y.py'


@pytest.mark.parametrize('precision',[9,28,57])
def test_import_preserves_caller_decimal_context(precision):
    with localcontext() as caller:
        caller.prec=precision
        caller.rounding=ROUND_DOWN
        caller.clear_flags()
        caller.flags[Inexact]=True
        caller.traps[Inexact]=True
        before=repr(caller)
        spec=importlib.util.spec_from_file_location('isolated_generator_import',GENERATOR_PATH)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert repr(getcontext())==before


@pytest.mark.parametrize('precision',[9,17,28,57])
@pytest.mark.parametrize('operation',['payment','build_life','generate'])
def test_financial_generation_preserves_context_and_frozen_source(precision,operation,tmp_path):
    with localcontext() as caller:
        caller.prec=precision
        caller.rounding=ROUND_DOWN
        caller.Emin=-99
        caller.Emax=99
        caller.capitals=0
        caller.clamp=1
        caller.clear_flags()
        caller.traps[Inexact]=True
        before=repr(caller)
        if operation=='payment':
            assert payment('630000','5.25',360)==Decimal('3478.88')
        elif operation=='build_life':
            raw=(json.dumps(build_life(),indent=2,sort_keys=True)+'\n').encode()
            assert hashlib.sha256(raw).hexdigest()=='e4f805f47717d99262a720a8c7e284180f2b157b3713b40ea41efc682a84fb54'
        else:
            manifest=generate(tmp_path)
            assert manifest['document_count']==794
            assert hashlib.sha256((tmp_path/'source-ledger.json').read_bytes()).hexdigest()=='e4f805f47717d99262a720a8c7e284180f2b157b3713b40ea41efc682a84fb54'
            assert not list(tmp_path.glob('*.pdf'))
        assert repr(getcontext())==before


def test_frozen_corpus_count_and_family_schedule():
    ledger = build_life()
    counts = Counter(doc['family'] for doc in ledger['documents'])
    assert counts == {
        'checking':60,'savings':60,'credit-card':300,'brokerage':120,
        'retirement':60,'payroll':60,'mortgage':60,'cd':60,
        'cd-opening':4,'cd-maturity':4,'refinance':1,'property-tax':5,
    }
    assert len({doc['id'] for doc in ledger['documents']}) == 794
    assert len({doc['file'] for doc in ledger['documents']}) == 794


def test_employment_boundaries_and_cent_exact_salary():
    payroll = [d for d in build_life()['documents'] if d['family']=='payroll']
    totals = {}
    for doc in payroll:
        employer=doc['facts']['employer']
        totals[employer]=totals.get(employer,Decimal(0))+Decimal(doc['facts']['gross'])
    assert totals == {'Microsoft':Decimal('440000'),'Amazon':Decimal('375000'),
                      'Salesforce':Decimal('427500')}
    assert payroll[23]['facts']['employer']=='Microsoft'
    assert payroll[24]['facts']['employer']=='Amazon'
    assert payroll[41]['facts']['employer']=='Amazon'
    assert payroll[42]['facts']['employer']=='Salesforce'


def test_closed_retirement_plans_have_matched_direct_rollover_witnesses():
    ledger=build_life()
    transfers={}
    for event in ledger['events']:
        if event['transfer_ref'].startswith('ROLLOVER-'):
            transfers.setdefault(event['transfer_ref'],[]).append(event)
    assert len(transfers)==2
    for events in transfers.values():
        assert len(events)==2
        assert events[0]['date']==events[1]['date']
        assert sum((Decimal(e['amount']) for e in events),Decimal(0))==0
        assert {e['kind'] for e in events}=={'contribution','withdrawal'}
        assert all(e['account_ref'].startswith('RET-') for e in events)
    closed=[d for d in ledger['documents'] if d['family']=='retirement' and d['as_of'] in ('2022-12-31','2024-06-30')]
    assert len(closed)==2
    assert all(d['facts']['total']=='0.00' and not d['facts']['positions'] for d in closed)


def test_json_dryrun_is_deterministic_and_never_creates_pdfs(tmp_path):
    first=generate(tmp_path)
    raw=(tmp_path/'source-ledger.json').read_bytes()
    second=generate(tmp_path)
    assert first==second
    assert raw==(tmp_path/'source-ledger.json').read_bytes()
    assert first['source_ledger_sha256']==hashlib.sha256(raw).hexdigest()
    assert not list(tmp_path.glob('*.pdf'))
    assert json.loads(raw)['schema_version']=='synthetic-life-v1'


def test_complete_stock_trading_and_printable_source_ids():
    ledger=build_life()
    ids={e['id'] for e in ledger['events']}
    assert len(ids)==len(ledger['events'])
    for doc in ledger['documents']:
        assert set(doc['events'])<=ids
        if doc['family']=='brokerage':
            trades=[e for e in doc['facts']['activity'] if e['kind'] in ('buy','sell') and e['security'] in ('AAPL','MSFT')]
            assert len(trades)>=4
            assert any(e['kind']=='buy' and e['security'] in ('VTSAX','SWPPX') for e in doc['facts']['activity'])


def test_loan_original_terms_are_explicit_and_replacement_principal_is_funded_amount():
    ledger=build_life()
    refi=next(d for d in ledger['documents'] if d['family']=='refinance')
    replacement=[d for d in ledger['documents'] if d['family']=='mortgage' and d['account_ref']=='LOAN-B']
    assert len(replacement)==36
    for doc in [d for d in ledger['documents'] if d['family'] in ('mortgage','refinance')]:
        facts=doc['facts']
        assert 'apr' not in facts
        assert facts['rate_type']=='fixed'
        assert facts['rate_basis']=='nominal_annual'
        if doc['account_ref']=='LOAN-A':
            assert facts['disclosure_apr_status']=='owner_specified_fictional_input'
            assert facts['disclosure_apr']=='5.25'
        else:
            assert facts['disclosure_apr_status']=='unavailable'
            assert 'disclosure_apr' not in facts
        assert facts['origination_date_basis']=='declared_synthetic'
        expected=('2021-01-01','360','630000.00','5.25') if doc['account_ref']=='LOAN-A' else ('2022-12-31','336',refi['facts']['funded_principal'],'4.25')
        assert (facts['origination_date'],facts['original_term_months'],facts['original_principal'],facts['nominal_note_rate'])==expected


def test_cd_terms_and_restriction_are_source_fields_for_every_lifecycle_witness():
    ledger=build_life()
    for doc in ledger['documents']:
        if doc['family'] not in ('cd','cd-opening','cd-maturity'):
            continue
        facts=doc['facts']
        assert 'apr' not in facts
        assert facts['opened']<facts['maturity_date']
        assert facts['rate_basis']=='simple_nominal'
        assert facts['day_count']=='equal_monthly_12'
        assert facts['compounding']=='none'
        assert facts['interest_crediting']=='monthly'
        assert facts['restriction']=='restricted_until_redemption'
        assert 'only whole-month schedules supported' in facts['convention_definition']
        assert facts['receiving_account_ref']=='SAVE-A'
        assert facts['funding_ref']==f"CD-FUND-{doc['account_ref']}"
        if doc['family']=='cd-maturity':
            assert facts['redemption_ref']==f"CD-MATURE-{doc['account_ref']}"


def test_continuous_restricted_escrow_components_corroborate_existing_cash_without_new_events():
    ledger=build_life()
    assert len(ledger['accounts'])==22
    assert len(ledger['events'])==3531
    assert ledger['source_subaccounts']==[dict(ref='ESCROW-A',kind='restricted_escrow',restriction='restricted_for_property_tax',initial_balance='0.00',property_ref='PROPERTY-A',loan_refs=['LOAN-A','LOAN-B'],continuity='one_continuous_synthetic_subaccount')]
    events={e['id']:e for e in ledger['events']}
    for doc in ledger['documents']:
        if doc['family']!='mortgage':
            continue
        facts=doc['facts']
        rows=facts['escrow_components']
        assert len(rows)==(2 if doc['as_of'].endswith('12-31') else 1)
        assert facts['escrow_account_ref']=='ESCROW-A'
        assert facts['escrow_continuity']=='one_continuous_synthetic_subaccount'
        assert Decimal(facts['escrow_opening'])+sum((Decimal(r['amount']) for r in rows),Decimal(0))==Decimal(facts['escrow_closing'])
        deposit=rows[0]
        event=events[deposit['source_event_id']]
        assert event['kind']=='mortgage_payment'
        assert event['transfer_ref']==deposit['reference']==facts['payment_reference']
        assert event['date']==deposit['date']==facts['payment_date']
        assert Decimal(facts['payment'])==-Decimal(event['amount'])
        assert Decimal(facts['payment'])==Decimal(facts['principal'])+Decimal(facts['interest'])+Decimal(deposit['amount'])


def test_tax_receipts_match_escrow_and_refinance_sources_equal_uses():
    ledger=build_life()
    for doc in ledger['documents']:
        if doc['family']=='property-tax':
            facts=doc['facts']
            month=next(d for d in ledger['documents'] if d['family']=='mortgage' and d['as_of']==doc['as_of'])
            row=month['facts']['escrow_components'][1]
            assert facts['paid_status']=='paid'
            assert facts['payment_reference']==row['reference']
            assert facts['payment_date']==row['date']
            assert facts['source_escrow_account_ref']==row['source_account_ref']=='ESCROW-A'
            assert facts['property_ref']==row['property_ref']=='PROPERTY-A'
            assert Decimal(facts['tax_paid'])==-Decimal(row['amount'])==Decimal('11000')
    facts=next(d['facts'] for d in ledger['documents'] if d['family']=='refinance')
    fee_total=sum((Decimal(r['amount']) for r in facts['fee_items']),Decimal(0))
    assert fee_total==Decimal(facts['borrower_contribution'])==Decimal('3000')
    assert Decimal(facts['sources_total'])==Decimal(facts['funded_principal'])+Decimal(facts['borrower_contribution'])
    assert Decimal(facts['uses_total'])==Decimal(facts['prior_loan_payoff'])+fee_total+Decimal(facts['cash_out'])
    assert facts['sources_total']==facts['uses_total']
    assert facts['financed_fees']==facts['cash_out']=='0.00'


def test_paystub_retirement_deduction_prints_the_plan_witness_reference():
    ledger=build_life()
    for doc in ledger['documents']:
        if doc['family']!='payroll':
            continue
        facts=doc['facts']
        deduction=next(r for r in facts['deductions'] if r['category']=='retirement')
        assert deduction['contribution_ref']==facts['retirement_contribution_ref']
        assert deduction['retirement_account_ref']==facts['retirement_account_ref']
        witness=next(e for e in ledger['events'] if e['transfer_ref']==deduction['contribution_ref'])
        assert witness['account_ref']==deduction['retirement_account_ref']
        assert witness['amount']==deduction['amount']


def test_original_mortgage_retains_owner_apr_without_inventing_replacement_apr():
    ledger=build_life()
    originals=[d for d in ledger['documents'] if d['family']=='mortgage' and d['account_ref']=='LOAN-A']
    replacements=[d for d in ledger['documents'] if d['family'] in ('mortgage','refinance') and d['account_ref']=='LOAN-B']
    assert len(originals)==24 and len(replacements)==37
    for doc in originals:
        facts=doc['facts']
        assert facts['nominal_note_rate']=='5.25'
        assert facts['disclosure_apr']=='5.25'
        assert facts['disclosure_apr_status']=='owner_specified_fictional_input'
        assert facts['disclosure_apr_basis']=='Owner-specified fictional scenario input; not a computed legal lender disclosure or real offer.'
    for doc in replacements:
        assert doc['facts']['nominal_note_rate']=='4.25'
        assert doc['facts']['disclosure_apr_status']=='unavailable'
        assert 'disclosure_apr' not in doc['facts']
    for doc in originals:
        doc['facts'].pop('disclosure_apr')
        doc['facts'].pop('disclosure_apr_basis')
        doc['facts']['disclosure_apr_status']='unavailable'
    prior_bytes=(json.dumps(ledger,indent=2,sort_keys=True)+'\n').encode()
    assert hashlib.sha256(prior_bytes).hexdigest()=='1ec04a449329becca9025735b4645f03e2fa2ea6be10c0d9498e5cbadc83cc5d'
