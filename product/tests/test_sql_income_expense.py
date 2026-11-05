"""Admitted income and expenses come from the current native SQL postings."""
from decimal import Decimal as D
import hashlib
import secrets

import pytest

from viva.sql_authority import SQLAuthority
from viva.sql_authority.store import canonical
from test_sql_authority_bank import ingest
from test_sql_investment import _investment

pytestmark = pytest.mark.production_kdf


def test_admitted_bank_expense_and_investment_income_use_native_sql(tmp_path,record_property):
    bank_original=b'synthetic B1 bank expense original'
    investment_original=b'synthetic B1 investment interest original'
    with SQLAuthority.create(tmp_path.resolve()/'income-expense',secrets.token_urlsafe(48),
                             verification='complete') as store:
        bank=ingest(store,bank_original)
        assert bank.status=='accepted'
        assert store.account(bank.account_id)['running_balance']=='90'
        bank_transactions=store.transactions(bank.account_id)
        bank_postings=store.postings(bank.doc_id)
        assert len(bank_transactions)==1
        assert [(p['account'],p['amount'],p['grade']) for p in bank_postings]==[
            (bank.account_id,'-10','verified'),('Expenses:Uncategorized','10','unverified')]
        assert store.original(bank.doc_id)==bank_original
        investment=_investment(store,investment_original)
        assert investment.status=='accepted' and investment.account_id!=bank.account_id
        snapshot=store.investment_snapshot(investment.account_id,as_of='2026-01-31')
        assert (snapshot['cash'],snapshot['total'])==('10','30')
        period=store.investment_cash_period(investment.doc_id)
        assert (period['opening_cash'],period['closing_cash'],period['state'])==('9','10','accepted')
        activity=store.investment_activity(investment.doc_id)
        assert len(activity)==1 and (activity[0]['kind'],activity[0]['amount'])==('interest','1')
        investment_postings=store.investment_postings(investment.doc_id)
        assert [(p['account'],p['amount'],p['currency'],p['grade']) for p in investment_postings]==[
            (investment.account_id,'1','USD','verified'),('Income:Interest','-1','USD','verified')]
        assert sum((D(p['amount']) for p in investment_postings),D(0))==0
        assert all(p['provenance']['doc_id']==investment.doc_id for p in investment_postings)
        assert store.original(investment.doc_id)==investment_original
        assert store.account(bank.account_id)['running_balance']=='90'
        assert store.transactions(bank.account_id)==bank_transactions
        assert store.postings(bank.doc_id)==bank_postings
        assert store.verify()['verified']
        head=store.head
        record_property('positive_complete_bank_and_native_investment','passed')

        report=store.income_expense()

        assert set(report)=={'schema','period','frontier','scope','lines','suppressed','by_currency','held_sources'}
        assert report['schema']=='sql-native-income-expense-v1' and report['frontier']==head
        assert report['period']=={'start':'','end':max(bank_transactions[0]['date'],activity[0]['date'])}
        assert report['scope']['families']==['bank','card','payroll','investment']
        assert report['scope']['amount_basis']=='admitted_named_effects'
        assert report['scope']['classification_basis']=='current_native_head'
        assert report['scope']['coverage_complete'] is True
        assert report['held_sources']==report['suppressed']==[]
        assert report['by_currency']=={'USD':{'admitted_income':'1','admitted_expenses':'10','admitted_net':'-9',
            'provisional_income':'0','provisional_expenses':'10','unavailable':[]}}
        assert len(report['lines'])==len({line['line_id'] for line in report['lines']})==2
        by_domain={line['domain']:line for line in report['lines']}
        assert set(by_domain)=={'bank','investment'}
        expense,income=by_domain['bank'],by_domain['investment']
        assert (expense['root'],expense['category'],expense['amount'],expense['provisional'])==('expenses','Expenses:Uncategorized','10',True)
        assert (income['root'],income['category'],income['amount'],income['provisional'])==('income','Income:Interest','1',False)
        assert expense['account_id']==bank.account_id and income['account_id']==investment.account_id
        assert expense['amount_evidence']['source_doc']==bank.doc_id
        assert income['amount_evidence']['source_doc']==investment.doc_id
        assert expense['amount_evidence']['source_occurrence'] is None
        assert income['amount_evidence']['source_occurrence'] is None
        assert report['lines']==sorted(report['lines'],key=lambda line:(line['date'],line['domain'],line['effect_id'],line['leg']))
        for line in report['lines']:
            assert line['currency']=='USD'
            identity=['sql-income-expense-line-v1',line['domain'],line['effect_id'],line['leg']]
            assert line['line_id']==hashlib.sha256(canonical(identity).encode()).hexdigest()
        assert store.head==head and store.verify(expected_head=head)['verified']


@pytest.fixture
def accounting_store(tmp_path):
    with SQLAuthority.create(tmp_path.resolve()/'admitted-report',secrets.token_urlsafe(48),verification='complete') as store:
        yield store


@pytest.mark.parametrize('values,expected',[
    ([], '0'),(['-0.00','0E+99999'],'0'),(['1.00','2.50','-0.50'],'3'),
    (['1e100000'],'1e100000'),(['1e100000','-1e100000','1'],'1'),
    (['1e100000','-9e99999','-1e99999'],'0'),
    (['1e100000','1'],None),(['-1e100000','-1'],None),
    (['1e100000','-1e100000','-1e-100000'],'-1e-100000'),
    (['1','9','-10'],'0'),(['0.1','0.2','-0.3'],'0'),
])
def test_sparse_accounting_numbers_cancel_before_span_budget(values,expected):
    from viva.sql_authority.accounting_numbers import total
    import decimal,sys
    before=str(decimal.getcontext());guard=sys.get_int_max_str_digits()
    assert total(values)==expected
    assert str(decimal.getcontext())==before and sys.get_int_max_str_digits()==guard


@pytest.mark.parametrize('value',[True,1,1.5,None,'NaN','Infinity','-Infinity'])
def test_accounting_numbers_refuse_nonfinite_and_nonstrings(value):
    from viva.sql_authority.accounting_numbers import total
    with pytest.raises(ValueError):total([value])


def test_large_coefficients_do_not_disable_python_integer_guard():
    from viva.sql_authority.accounting_numbers import total
    import sys
    digits='1'+'2'*5000;guard=sys.get_int_max_str_digits()
    expected=digits+'e0'
    assert total([digits])==expected
    assert total([digits,'-'+digits])=='0'
    assert sys.get_int_max_str_digits()==guard


@pytest.mark.parametrize('start,end',[(True,''),('',None),('20260101',''),('2026-1-01',''),('2026-02-30',''),('2026-02-01','2026-01-31')])
def test_report_refuses_noncanonical_or_reversed_period(accounting_store,start,end):
    from viva.sql_authority import AuthorityError
    with pytest.raises((ValueError,AuthorityError)):accounting_store.income_expense(start=start,end=end)


def test_report_keeps_only_source_dates_inclusive_at_current_head(accounting_store):
    store=accounting_store
    bank=ingest(store,b'inclusive bank expense')
    investment=_investment(store,b'inclusive interest')
    head=store.head
    report=store.income_expense(start='2026-01-15',end='2026-01-15')
    assert report['frontier']==head
    assert report['period']=={'start':'2026-01-15','end':'2026-01-15'}
    assert len(report['lines'])==1 and report['lines'][0]['domain']=='investment'
    assert report['by_currency']['USD']['admitted_net']=='1'
    assert store.income_expense(end='2026-01-01')['by_currency']['USD']['admitted_net']=='-10'
    assert store.income_expense(start='2026-01-16',end='2026-01-20')['lines']==[]
    assert store.account(bank.account_id)['running_balance']=='90' and store.investment_snapshot(investment.account_id,as_of='2026-01-31')['total']=='30'


def test_card_charge_payment_and_opening_are_not_reinterpreted_as_income(accounting_store):
    store=accounting_store
    first=ingest(store,b'card charge',doc_type='credit_card_statement',movement='10',opening='100',closing='110')
    second=ingest(store,b'card payment',doc_type='credit_card_statement',movement='-10',opening='110',closing='100',start='2026-01-31',end='2026-02-28')
    assert first.status==second.status=='accepted'
    report=store.income_expense()
    assert len(report['lines'])==1
    assert (report['lines'][0]['category'],report['lines'][0]['amount'])==('Expenses:Uncategorized','10')
    assert report['by_currency']['USD']['admitted_income']=='0'
    assert report['by_currency']['USD']['admitted_expenses']=='10'
    line=report['lines'][0];txn=next(t for t in store.transactions(first.account_id) if t['doc_id']==first.doc_id)
    assert txn['amount']=='10' and txn['account_id']==first.account_id==second.account_id
    assert store.account(first.account_id)['kind']=='liability'
    assert line['account_id']==first.account_id and line['effect_id']==txn['txn_id']
    assert line['amount_evidence']['native_posting']==store._row('postings','txn_id=? AND leg=?',(txn['txn_id'],line['leg']))
    assert line['amount_evidence']['native_posting']['amount']=='-10'
    assert line['amount_evidence']['source_doc']==txn['doc_id']==first.doc_id
    assert report['by_currency']['USD']['admitted_net']=='-10'
    assert report['by_currency']['USD']['provisional_expenses']=='10'
    assert store.account(first.account_id)['running_balance']=='100'


def test_currencies_have_admitted_subtotals_without_cross_currency_total(accounting_store):
    store=accounting_store
    ingest(store,b'USD expense')
    ingest(store,b'EUR expense',currency='EUR',number='7654321',institution='Synthetic Other Currency Issuer')
    report=store.income_expense()
    assert set(report['by_currency'])=={'USD','EUR'}
    assert all(v['admitted_net']=='-10' for v in report['by_currency'].values())
    assert 'grand_total' not in report


@pytest.mark.parametrize('gain,expected',[('-2','-2'),('0',None),(None,None)])
def test_sourced_capital_gain_sign_and_unknown_gain_disclosure(accounting_store,gain,expected):
    from viva.ingest.brokerage import BrokerageActivity
    store=accounting_store
    result=_investment(store,b'sell with explicit gain '+str(gain).encode(),activity=[BrokerageActivity('2026-01-15','sell',D('1'),realized_gain=None if gain is None else D(gain))])
    assert result.status=='accepted'
    report=store.income_expense()
    if expected is not None:
        assert report['by_currency']['USD']['admitted_income']==expected
        assert report['lines'][0]['category'].startswith('Income:')
    else:assert report['lines']==[]
    assert report['held_sources']==([{'doc_id':result.doc_id,'facet':'realized_gain','reason':'unavailable:0'}] if gain is None else [])
    assert report['scope']['coverage_complete'] is (gain is not None)


def test_accepted_snapshot_unproved_empty_activity_remains_a_global_gap(accounting_store):
    store=accounting_store
    result=_investment(store,b'accepted snapshot without complete cash',opening=None,activity=[])
    component=store.investment_component(result.doc_id)
    assert result.status=='accepted' and component['snapshot_state']=='accepted'
    assert (component['activity_state'],component['reason'])==('unavailable','empty_activity_unproved')
    report=store.income_expense(start='2027-01-01',end='2027-01-31')
    assert report['lines']==[] and report['scope']['coverage_complete'] is False
    assert report['held_sources']==[{'doc_id':result.doc_id,'facet':'activity','reason':'unavailable:empty_activity_unproved'}]


def test_genuine_empty_period_is_covered_without_invented_income(accounting_store):
    store=accounting_store
    _investment(store,b'genuine root for empty report period')
    def source(wire):wire['headers']['no_activity']={'raw':'true','page':1}
    child=_investment(store,b'genuine explicit empty report period',opening='10',cash='10',total='30',start='2026-02-01',end='2026-02-28',activity=[],mutate_source=source)
    assert store.investment_component(child.doc_id)['activity_state']=='accepted'
    report=store.income_expense(start='2026-02-01',end='2026-02-28')
    assert report['lines']==report['held_sources']==[] and report['scope']['coverage_complete'] is True


def test_unsupported_recorded_source_is_disclosed_even_outside_period(accounting_store):
    from viva.ingest.pipeline_models import ReadResult
    store=accounting_store
    result=store.ingest(b'synthetic unsupported recorded source',lambda _b,_d:ReadResult('synthetic_unsupported',0.0),contract='synthetic-unsupported-v1')
    item=store.item(result.doc_id);assert item['state']!='accepted'
    report=store.income_expense(start='2027-01-01',end='2027-12-31')
    assert report['held_sources']==[{'doc_id':result.doc_id,'facet':'item','reason':item['state']+':'+item['reason']}]
    assert report['scope']['coverage_complete'] is False


def test_payroll_explains_deposit_once_and_duplicate_stubs_keep_source_identity(accounting_store):
    from test_sql_payroll import _payroll,_deposit
    store=accounting_store
    deposit=_deposit(store)
    first=_payroll(store,b'first payroll source for report')
    copy=_payroll(store,b'whole payroll source copy for report')
    assert first.status==copy.status=='accepted'
    report=store.income_expense()
    assert report['by_currency']['USD']==dict(admitted_income='100',admitted_expenses='20',admitted_net='80',provisional_income='0',provisional_expenses='0',unavailable=[])
    assert len(report['lines'])==2 and {r['domain'] for r in report['lines']}=={'payroll'}
    explanation=store._row('payroll_explanations','source_doc=?',(first.doc_id,))
    txn=store.transactions(deposit.account_id)[0]
    assert report['suppressed']==[dict(txn_id=txn['txn_id'],doc_id=deposit.doc_id,reason='payroll_decomposition',relationship=explanation['explanation_id'])]
    for line in report['lines']:
        assert line['amount_evidence']['source_doc']==first.doc_id
        assert line['amount_evidence']['source_occurrence'] is None and line['amount_evidence']['source_fields']==[]
        assert line['classification_evidence']==dict(by='document',reason='native_payroll_decomposition',related_effects=[dict(domain='bank',effect_id=txn['txn_id']),dict(domain='payroll',effect_id=explanation['explanation_id'])])
        assert line['provisional'] is False
    assert store.income_expense()==report


def test_two_equal_deposits_do_not_guess_which_payroll_to_suppress(accounting_store):
    from test_sql_payroll import _payroll,_deposit
    store=accounting_store
    _deposit(store,b'first equal deposit')
    payroll=_payroll(store)
    assert store.income_expense()['by_currency']['USD']['admitted_income']=='100'
    _deposit(store,b'second equal deposit',number='7654321')
    report=store.income_expense()
    assert store.payroll_component(payroll.doc_id)['state']=='ambiguous'
    assert len(report['lines'])==2 and all(r['domain']=='bank' for r in report['lines'])
    assert report['by_currency']['USD']['admitted_income']=='160' and report['suppressed']==[]
    assert report['scope']['coverage_complete'] is False


def test_payroll_uses_pay_date_while_suppression_uses_actual_bank_date(accounting_store):
    from test_sql_payroll import _payroll,_deposit
    store=accounting_store
    deposit=_deposit(store,day='2026-01-20')
    payroll=_payroll(store)
    assert payroll.status=='accepted'
    pay_day=store.income_expense(start='2026-01-15',end='2026-01-15')
    assert len(pay_day['lines'])==2 and pay_day['suppressed']==[]
    assert pay_day['by_currency']['USD']['admitted_income']=='100'
    deposit_day=store.income_expense(start='2026-01-20',end='2026-01-20')
    assert deposit_day['lines']==[] and len(deposit_day['suppressed'])==1
    assert deposit_day['suppressed'][0]['doc_id']==deposit.doc_id


def test_retirement_deduction_is_not_expense_or_a_second_physical_asset(accounting_store):
    from test_sql_payroll import _payroll,_deposit
    from viva.ingest.paystub import Deduction
    store=accounting_store
    deposit=_deposit(store)
    _payroll(store,deductions=[Deduction('Synthetic retirement',D('20'),'retirement')])
    report=store.income_expense()
    assert len(report['lines'])==1 and report['lines'][0]['category']=='Income:Salary'
    assert report['by_currency']['USD']['admitted_expenses']=='0'
    assert store._read('SELECT count(*) FROM accounts')==[(1,)] and store.account(deposit.account_id)['running_balance']=='80'
    retirement=next(p for p in store.payroll_postings() if p['account']=='Assets:Retirement')
    assert retirement['grade']=='unverified' and all(r['amount_evidence']['native_posting']['account_id']!='Assets:Retirement' for r in report['lines'])


def test_manual_transfer_changes_current_treatment_without_changing_source_cash(accounting_store):
    from test_sql_authority_transfers import fixed_initial
    store=accounting_store
    fixed_initial(store)
    before_accounts=store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id');before=store.income_expense()
    initial_suggestions=store.transfer_suggestions()
    suggestion=initial_suggestions[0];a,b=suggestion['a'],suggestion['candidates'][0]
    assert store.confirm_transfer(a,b,today='2024-03-01')
    linked=store.income_expense(start='2024-02-01',end='2024-02-29')
    assert len(linked['suppressed'])==2 and all(r['reason']=='live_transfer' and r['relationship']==sorted([a,b]) for r in linked['suppressed'])
    assert len(linked['lines'])==len(before['lines'])-2
    assert store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id')==before_accounts
    assert store.unlink_transfer(a,b,today='2024-03-02')
    unlinked=store.income_expense()
    assert unlinked['lines']==before['lines'] and unlinked['suppressed']==[]
    remaining_suggestions=store.transfer_suggestions()
    expected_rivals=[row for row in initial_suggestions if row['a'] not in {a,b}]
    assert expected_rivals and remaining_suggestions==expected_rivals
    assert all(row['a']!=a for row in remaining_suggestions)
    assert not store.confirm_transfer(a,b,today='2024-03-03')
    assert store.income_expense()==unlinked
    from test_sql_authority_transfers import admit
    background=admit(store,'income expense genuine March boundary',number='900000100000',institution='Background',
        opening='10000',amount='1000',description='background',day='2024-03-03',start='2024-03-01',end='2024-03-31')
    assert store.account(background.account_id)['running_balance']=='11000'
    boundary_accounts=store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id')
    assert [row for row in boundary_accounts if row[0]!=background.account_id]==before_accounts
    february=store.income_expense(start='2024-02-01',end='2024-02-29')
    assert february['lines']==before['lines'] and february['suppressed']==[]
    assert all(row['amount_evidence']['source_doc']!=background.doc_id for row in february['lines'])
    assert any(row['a']==a and b in row['candidates'] for row in store.transfer_suggestions())
    assertions=store.transfer_assertions()
    assert store.confirm_transfer(a,b,today='2024-03-03')
    relinked=store.income_expense(start='2024-02-01',end='2024-02-29')
    assert relinked['lines']==linked['lines'] and relinked['suppressed']==linked['suppressed']
    assert store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id')==boundary_accounts
    assert store.transfer_assertions()[:-1]==assertions and len(store.transfer_assertions())==len(assertions)+1
    assert len(store.transfer_as_of('2024-03-01')['links'])==1


def test_payroll_transfer_reservation_retires_and_restores_named_income(accounting_store):
    from test_sql_authority_transfers import fixed_initial
    from test_sql_payroll import _payroll
    store=accounting_store
    fixed_initial(store)
    _payroll(store,gross='30',net='10',change=lambda f:setattr(f,'pay_date','2024-02-17'))
    before=store.income_expense()
    assert any(r['domain']=='payroll' for r in before['lines'])
    suggestion=store.transfer_suggestions()[0];a,b=suggestion['a'],suggestion['candidates'][0]
    assert store.confirm_transfer(a,b,today='2024-03-01')
    assert all(r['domain']!='payroll' for r in store.income_expense()['lines'])
    assert store.unlink_transfer(a,b,today='2024-03-02')
    assert store.income_expense()['lines']==before['lines']


def test_investment_copies_and_equal_occurrences_are_not_collapsed_or_doubled(accounting_store):
    from viva.ingest.brokerage import BrokerageActivity
    store=accounting_store
    kwargs=dict(opening='8',activity=[BrokerageActivity('2026-01-15','interest',D('1')) for _ in range(2)])
    first=_investment(store,b'first repeated interest source',**kwargs)
    before=store.income_expense()
    copy=_investment(store,b'whole repeated interest copy',**kwargs)
    report=store.income_expense()
    assert first.status==copy.status=='accepted' and report['lines']==before['lines']
    assert len(report['lines'])==2 and len({r['effect_id'] for r in report['lines']})==2
    assert report['by_currency']['USD']['admitted_income']=='2'
    assert all(r['amount_evidence']['source_doc']==first.doc_id for r in report['lines'])


def test_conflicted_investment_cash_is_not_historical_adjustment_income(accounting_store):
    from viva.ingest.brokerage import BrokerageActivity
    store=accounting_store
    first=_investment(store,b'original active investment cash')
    assert store.income_expense()['by_currency']['USD']['admitted_income']=='1'
    second=_investment(store,b'changed complete investment cash',opening='8',activity=[BrokerageActivity('2026-01-15','interest',D('2'))])
    assert first.status==second.status=='accepted'
    assert store.investment_history(first.doc_id)['decisions'][-1]['action']=='deactivate'
    report=store.income_expense()
    assert report['lines']==[] and report['scope']['coverage_complete'] is False
    assert all(r['facet']=='activity' for r in report['held_sources'])


def test_rebind_report_uses_immutable_effects_once_and_reopens_at_trusted_head(tmp_path):
    from test_sql_investment import _genuine_native_rebind
    root=tmp_path.resolve()/'report-rebind';passphrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(root,passphrase,verification='complete') as store:
        a,child,b,d,before,after=_genuine_native_rebind(store)
        report=store.income_expense()
        assert [r['amount_evidence']['source_doc'] for r in report['lines']].count(child.doc_id)==1
        assert report['by_currency']['USD']['admitted_income']=='2'
        assert after['postings']==before['postings']
        assert a.doc_id not in {r['amount_evidence']['source_doc'] for r in report['lines']}
        head=store.head
    with SQLAuthority.open(root,passphrase,verification='complete') as reopened:
        assert reopened.verify(expected_head=head)['verified']
        assert reopened.income_expense()==report


def test_report_outputs_are_detached_and_use_indexed_native_paths(accounting_store,monkeypatch):
    store=accounting_store
    ingest(store,b'detached bank')
    _investment(store,b'detached investment')
    baseline=store.income_expense();seen=[];read=store._read
    def observe(sql,parameters=()):
        seen.append((sql,parameters));return read(sql,parameters)
    monkeypatch.setattr(store,'_read',observe)
    changed=store.income_expense()
    changed['scope']['limitations'].clear();changed['lines'][0]['amount_evidence']['native_posting']['grade']='fabricated'
    changed['by_currency']['USD']['admitted_net']='999'
    assert store.income_expense()==baseline
    sql='\n'.join(q for q,_ in seen)
    assert 'FROM transactions WHERE account_id=? AND date>=? AND date<=?' in sql
    assert 'FROM investment_groups WHERE account_id=?' in sql
    assert 'FROM investment_effects WHERE group_id=?' in sql
    assert any('transactions_account_date' in str(row) for row in read('EXPLAIN QUERY PLAN SELECT * FROM transactions WHERE account_id=? AND date>=? AND date<=?',('synthetic','2026-01-01','2026-12-31')))


def test_indexed_profile_cannot_serve_the_complete_report(tmp_path):
    from viva.sql_authority import AuthorityError
    with SQLAuthority.create(tmp_path.resolve()/'indexed-only',secrets.token_urlsafe(48)) as store:
        ingest(store)
        with pytest.raises(AuthorityError,match='income/expense requires complete verification'):store.income_expense()


@pytest.mark.parametrize('corruption',['amount','omit','duplicate','suppressed','income_total','net','frontier','grade','related','provisional','coverage','source_fields','tuple_lines'])
def test_independent_oracle_rejects_changed_actual_reader_output(accounting_store,monkeypatch,corruption):
    from viva.sql_authority import accounting
    from viva.sql_authority.store import IntegrityError
    store=accounting_store
    ingest(store,b'output verifier bank')
    _investment(store,b'output verifier investment')
    baseline=store.income_expense();assert len(baseline['lines'])==2
    reader=accounting.read;entered=[]
    def changed(owner,**kwargs):
        result=reader(owner,**kwargs);assert result==baseline;entered.append(True)
        if corruption=='amount':result['lines'][0]['amount']='999'
        elif corruption=='omit':result['lines'].pop()
        elif corruption=='duplicate':result['lines'].append(result['lines'][0])
        elif corruption=='suppressed':result['suppressed'].append(dict(txn_id='0'*64,doc_id='0'*64,reason='live_transfer',relationship=['a','b']))
        elif corruption=='income_total':result['by_currency']['USD']['admitted_income']='999'
        elif corruption=='net':result['by_currency']['USD']['admitted_net']='999'
        elif corruption=='frontier':result['frontier']['head']='0'*64
        elif corruption=='grade':result['lines'][0]['amount_evidence']['native_posting']['grade']='verified'
        elif corruption=='related':result['lines'][0]['classification_evidence']['related_effects']=[]
        elif corruption=='provisional':result['lines'][0]['provisional']=1
        elif corruption=='coverage':result['scope']['coverage_complete']=False
        elif corruption=='source_fields':result['lines'][-1]['amount_evidence']['source_fields']=[]
        elif corruption=='tuple_lines':result['lines']=tuple(result['lines'])
        return result
    monkeypatch.setattr(accounting,'read',changed)
    expected='income/expense output has invalid JSON protocol' if corruption=='tuple_lines' else 'income/expense output differs from authenticated native state'
    with pytest.raises(IntegrityError,match=expected):store.income_expense()
    assert entered==[True]


@pytest.mark.parametrize('target',['source','audit','physical_sql'])
def test_complete_report_refuses_native_source_audit_and_table_tamper(accounting_store,target):
    from viva.sql_authority import AuthorityError
    from sqlcipher3 import dbapi2 as sql
    from viva.crypto import CryptoError
    store=accounting_store
    result=ingest(store,b'actual tamper report source')
    baseline=store.income_expense();assert baseline['lines']
    if target=='source':
        import json,base64
        blob=store.root/'originals'/(result.doc_id+'.blob')
        envelope=json.loads(blob.read_text());ciphertext=bytearray(base64.b64decode(envelope['ct']))
        ciphertext[-1]^=1;envelope['ct']=base64.b64encode(ciphertext).decode('ascii')
        blob.write_text(json.dumps(envelope))
    elif target=='audit':store._db.execute("UPDATE audit SET envelope='{}' WHERE sequence=(SELECT max(sequence) FROM audit)")
    else:store._db.execute("UPDATE postings SET amount='999' WHERE leg=1")
    with pytest.raises((AuthorityError,sql.DatabaseError,CryptoError)):store.income_expense()


def test_native_encrypted_page_tamper_refuses_complete_reopen_for_report(tmp_path):
    from viva.sql_authority import AuthorityError
    from sqlcipher3 import dbapi2 as sql
    root=tmp_path.resolve()/'encrypted-report';phrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(root,phrase,verification='complete') as store:
        ingest(store,b'encrypted page positive report')
        assert store.income_expense()['lines']
        page=int(store._db.execute('PRAGMA cipher_page_size').fetchone()[0])
    path=root/'authority.db';data=bytearray(path.read_bytes());assert len(data)>=2*page
    data[len(data)-page+100]^=1;path.write_bytes(data)
    with pytest.raises((AuthorityError,sql.DatabaseError)):SQLAuthority.open(root,phrase,verification='complete')


def test_report_net_cancels_huge_native_income_and_expenses_independently(accounting_store):
    from viva.ingest.brokerage import BrokerageActivity
    store=accounting_store
    movements=[BrokerageActivity('2026-01-15',kind,D(value)) for kind,value in [
        ('interest','1e20000'),('interest','1'),('fee','1e20000'),('fee','1')]]
    result=_investment(store,b'compact native amounts with unavailable subtotals',opening='9',cash='9',total='29',activity=movements)
    assert result.status=='accepted' and store.investment_component(result.doc_id)['activity_state']=='accepted'
    report=store.income_expense()
    assert len(report['lines'])==4
    assert report['by_currency']['USD']==dict(admitted_income=None,admitted_expenses=None,admitted_net='0',provisional_income='0',provisional_expenses='0',unavailable=['admitted_income','admitted_expenses'])
    assert {r['amount'] for r in report['lines']}=={'1','1e20000'}
    assert all(r['amount_evidence']['source_fields'] for r in report['lines'])


def test_complete_report_reader_and_oracle_share_one_real_snapshot(accounting_store,monkeypatch):
    from viva.sql_authority import accounting,accounting_verify
    store=accounting_store
    ingest(store,b'held snapshot report baseline')
    baseline=store.income_expense();seen=[];trace=[]
    reader=accounting.read;oracle=accounting_verify.verify
    def read(owner,**kwargs):
        assert owner._db.in_transaction and owner._verified_operation and not owner._verifying
        seen.append(('read',owner._check_terminal()));return reader(owner,**kwargs)
    def verify(owner,result,**kwargs):
        assert owner._db.in_transaction and owner._verified_operation and not owner._verifying
        seen.append(('oracle',owner._check_terminal()));return oracle(owner,result,**kwargs)
    monkeypatch.setattr(accounting,'read',read);monkeypatch.setattr(accounting_verify,'verify',verify)
    store._db.set_trace_callback(trace.append)
    try:assert store.income_expense()==baseline
    finally:store._db.set_trace_callback(None)
    assert [kind for kind,head in seen]==['read','oracle'] and seen[0][1]==seen[1][1]
    assert [s for s in trace if s.strip().upper().startswith('BEGIN')]==['BEGIN']
    assert [s for s in trace if s.strip().upper()=='COMMIT']==['COMMIT']
    assert all('ROLLBACK' not in s.upper() for s in trace)
    upper='\n'.join(trace).upper()
    assert all(pragma in upper for pragma in ('CIPHER_INTEGRITY_CHECK','INTEGRITY_CHECK','FOREIGN_KEY_CHECK'))
    assert not any(sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')) for sql in trace)


def test_report_context_binds_all_three_new_module_sources(accounting_store):
    store=accounting_store
    result=ingest(store,b'accounting implementation closure source')
    receipt=store.receipt(result.doc_id)
    implementation=receipt['reading']['authority_context']['implementation']
    assert all('viva.sql_authority.'+name in implementation['files'] for name in ('accounting','accounting_verify','accounting_numbers'))
    assert store.income_expense()['frontier']==store.head


def test_payroll_named_expenses_keep_tax_insurance_other_and_retirement_separate(accounting_store):
    from test_sql_payroll import _deposit,_payroll
    from viva.ingest.paystub import Deduction
    store=accounting_store
    _deposit(store)
    payroll=_payroll(store,deductions=[Deduction('Synthetic '+category,D('5'),category) for category in ['tax','insurance','other','retirement']])
    assert payroll.status=='accepted'
    report=store.income_expense()
    assert {r['category'] for r in report['lines']}=={'Income:Salary','Expenses:Tax','Expenses:Insurance','Expenses:Other'}
    assert report['by_currency']['USD']['admitted_expenses']=='15'
    assert report['by_currency']['USD']['admitted_net']=='85'
    assert all(r['amount_evidence']['source_occurrence'] is None and r['amount_evidence']['source_fields']==[] for r in report['lines'])
    expenses=[r for r in report['lines'] if r['root']=='expenses']
    assert expenses and all(r['amount_evidence']['native_posting']['grade']=='unverified' and not r['provisional'] for r in expenses)


def test_captured_reader_failure_is_a_retained_item_gap_without_income(accounting_store):
    store=accounting_store
    original=b'synthetic reader interruption remains a captured source'
    def reader(_original,_doc):raise RuntimeError('synthetic external reader interruption')
    with pytest.raises(RuntimeError,match='synthetic external reader interruption'):
        store.ingest(original,reader,contract='synthetic-interrupted-v1')
    doc=hashlib.sha256(original).hexdigest();item=store.item(doc)
    assert item['state']=='read_uncertain' and store.original(doc)==original
    report=store.income_expense()
    assert report['lines']==[] and report['scope']['coverage_complete'] is False
    assert report['held_sources']==[dict(doc_id=doc,facet='item',reason=item['state']+':'+item['reason'])]


def test_curated_payroll_source_without_cells_is_not_new_pdf_field_proof(accounting_store):
    from viva.sql_authority import CuratedSource
    store=accounting_store;source=CuratedSource.open()
    document=next(d for d in source.documents if d['doc_type']=='pay_stub')
    result=store.ingest_curated(source.original(document['sha256']),source)
    assert store.source_occurrences(result.doc_id)==[]
    report=store.income_expense()
    assert report['lines']==[] and report['scope']['coverage_complete'] is False
    assert any(g['doc_id']==result.doc_id and g['facet']=='item' for g in report['held_sources'])
    assert report['scope']['limitations'][-1]=='No new PDF-field verification.'
    assert store.original(result.doc_id)==source.original(document['sha256'])
    assert store.receipt(result.doc_id)['raw_reading']['facts'] is None


def test_payroll_report_reopen_preserves_exact_net_deposit_relationship(tmp_path):
    from test_sql_payroll import _deposit,_payroll
    root=tmp_path.resolve()/'payroll-report-reopen';phrase=secrets.token_urlsafe(48)
    with SQLAuthority.create(root,phrase,verification='complete') as store:
        deposit=_deposit(store)
        payroll=_payroll(store)
        report=store.income_expense();head=store.head
        txn=store.transactions(deposit.account_id)[0]['txn_id']
        assert report['suppressed'][0]['txn_id']==txn
        assert all(dict(domain='bank',effect_id=txn) in row['classification_evidence']['related_effects'] for row in report['lines'])
        assert all(row['amount_evidence']['source_doc']==payroll.doc_id for row in report['lines'])
    with SQLAuthority.open(root,phrase,verification='complete') as reopened:
        assert reopened.verify(expected_head=head)['verified']
        assert reopened.income_expense()==report


@pytest.mark.parametrize('corruption',['omit_suppression','change_relationship','bank_doc_as_payroll_source'])
def test_oracle_checks_real_payroll_suppression_and_owning_source(accounting_store,monkeypatch,corruption):
    from test_sql_payroll import _deposit,_payroll
    from viva.sql_authority import accounting
    from viva.sql_authority.store import IntegrityError
    store=accounting_store
    deposit=_deposit(store);_payroll(store)
    baseline=store.income_expense();assert len(baseline['suppressed'])==1 and len(baseline['lines'])==2
    original=accounting.read;changed=[]
    def reader(owner,**kwargs):
        report=original(owner,**kwargs);assert report==baseline;changed.append(True)
        if corruption=='omit_suppression':report['suppressed']=[]
        elif corruption=='change_relationship':report['suppressed'][0]['relationship']='0'*64
        else:report['lines'][0]['amount_evidence']['source_doc']=deposit.doc_id
        return report
    monkeypatch.setattr(accounting,'read',reader)
    with pytest.raises(IntegrityError,match='income/expense output differs from authenticated native state'):store.income_expense()
    assert changed==[True]


def test_oracle_independently_retains_real_unavailable_activity_coverage(accounting_store,monkeypatch):
    from viva.sql_authority import accounting
    from viva.sql_authority.store import IntegrityError
    store=accounting_store
    _investment(store,b'real held activity for output coverage proof',opening=None,activity=[])
    baseline=store.income_expense();assert baseline['held_sources'] and not baseline['scope']['coverage_complete']
    original=accounting.read;changed=[]
    def reader(owner,**kwargs):
        report=original(owner,**kwargs);assert report==baseline;changed.append(True)
        report['held_sources']=[];report['scope']['coverage_complete']=True
        return report
    monkeypatch.setattr(accounting,'read',reader)
    with pytest.raises(IntegrityError,match='income/expense output differs from authenticated native state'):store.income_expense()
    assert changed==[True]


def test_empty_root_report_does_not_invent_currency_income(accounting_store):
    report=accounting_store.income_expense()
    assert report['period']=={'start':'','end':''}
    assert report['lines']==report['held_sources']==report['suppressed']==[]
    assert report['by_currency']=={} and report['scope']['coverage_complete'] is True
    assert report['frontier']==accounting_store.head


def test_coefficient_carry_cannot_escape_output_resource_budget():
    from viva.sql_authority.accounting_numbers import total
    digits='9'*16384
    assert total([digits,'9e1']) is None
    assert total([digits,'1'])=='1e16384'



def test_native_mixed_cash_and_card_report_uses_economic_direction():
    from tempfile import TemporaryDirectory
    from pathlib import Path
    with TemporaryDirectory() as directory:
        with SQLAuthority.create(Path(directory).resolve()/'mixed-economic',secrets.token_urlsafe(48),verification='complete') as store:
            income=ingest(store,b'mixed checking income',number='800000000001',movement='300',opening='100',closing='400',start='2026-02-01',end='2026-02-15')
            purchase=ingest(store,b'mixed checking purchase',number='800000000001',movement='-40',opening='400',closing='360',start='2026-02-15',end='2026-02-28')
            charge=ingest(store,b'mixed liability charge',number='800000000002',doc_type='credit_card_statement',movement='25',opening='100',closing='125',start='2026-02-01',end='2026-02-15')
            payment=ingest(store,b'mixed liability payment',number='800000000002',doc_type='credit_card_statement',movement='-25',opening='125',closing='100',start='2026-02-15',end='2026-02-28')
            assert income.status==purchase.status==charge.status==payment.status=='accepted'
            assert income.account_id==purchase.account_id and charge.account_id==payment.account_id!=income.account_id
            report=store.income_expense(start='2026-02-01',end='2026-02-28')
            assert report['by_currency']=={'USD':dict(admitted_income='300',admitted_expenses='65',admitted_net='235',provisional_income='300',provisional_expenses='65',unavailable=[])}
            assert len(report['lines'])==3 and report['suppressed']==[]
            assert {line['amount_evidence']['source_doc'] for line in report['lines']}=={income.doc_id,purchase.doc_id,charge.doc_id}
            card=next(line for line in report['lines'] if line['account_id']==charge.account_id)
            transaction=next(row for row in store.transactions(charge.account_id) if row['doc_id']==charge.doc_id)
            assert store.account(charge.account_id)['kind']=='liability' and transaction['amount']=='25'
            assert card['effect_id']==transaction['txn_id'] and card['amount']=='25'
            assert card['amount_evidence']['native_posting']==store._row('postings','txn_id=? AND leg=?',(transaction['txn_id'],card['leg']))
            assert card['amount_evidence']['native_posting']['amount']=='-25'
            assert store.account(income.account_id)['running_balance']=='360' and store.account(charge.account_id)['running_balance']=='100'


def test_independent_oracle_refuses_coherent_old_card_sign_output():
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from viva.sql_authority import accounting
    from viva.sql_authority.store import IntegrityError
    with TemporaryDirectory() as directory:
        with SQLAuthority.create(Path(directory).resolve()/'old-sign-adversary',secrets.token_urlsafe(48),verification='complete') as store:
            card=ingest(store,b'coherent old sign card source',doc_type='credit_card_statement',movement='10',opening='100',closing='110',start='2026-02-01',end='2026-02-28')
            assert card.status=='accepted' and store.account(card.account_id)['kind']=='liability'
            baseline=store.income_expense();head=store.head
            cash=store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id')
            assert len(baseline['lines'])==1 and baseline['lines'][0]['amount']=='10'
            assert baseline['lines'][0]['amount_evidence']['native_posting']['amount']=='-10'
            original=accounting.read;changed=[]
            def reader(owner,**kwargs):
                report=original(owner,**kwargs);assert report==baseline;changed.append(True)
                report['lines'][0]['amount']='-10'
                report['by_currency']['USD'].update(admitted_expenses='-10',admitted_net='10',provisional_expenses='-10')
                assert report['lines'][0]['amount_evidence']==baseline['lines'][0]['amount_evidence']
                assert report['lines'][0]['line_id']==baseline['lines'][0]['line_id']
                return report
            with pytest.MonkeyPatch.context() as patch:
                patch.setattr(accounting,'read',reader)
                with pytest.raises(IntegrityError,match='income/expense output differs from authenticated native state'):
                    store.income_expense()
            assert changed==[True]
            assert store.income_expense()==baseline and store.head==head
            assert store._read('SELECT account_id,current_amount,earliest_amount FROM accounts ORDER BY account_id')==cash
            assert store.verify(expected_head=head)['verified']
