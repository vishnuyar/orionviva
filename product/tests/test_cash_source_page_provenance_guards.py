"""Printed page custody must not be invented from matching money alone."""
from dataclasses import replace
from decimal import Decimal
import json
import pytest
from test_cash_source_page_provenance import brokerage_facts, payroll_facts, cash_events
from viva.ingest.cash_source_pages import brokerage_activity_pages, payroll_decomposition_page
from viva.investment.extraction import SourceField


def change_header(facts,name,value):
    source=facts.investment_source
    facts.investment_source=replace(source,headers=tuple((k,value if k==name else v) for k,v in source.headers))


def change_row(facts,name,value):
    source=facts.investment_source
    row=tuple((k,value if k==name else v) for k,v in source.rows[0])
    facts.investment_source=replace(source,rows=(row,))


@pytest.mark.parametrize('count',[None,True,0,-1,201,'2'])
def test_brokerage_requires_actual_supported_page_bound(count):
    facts=brokerage_facts();facts.validated_source_page_count=count
    assert brokerage_activity_pages(facts)==(None,)


@pytest.mark.parametrize(('name','raw'),[('date','2025-01-14'),('kind','withdrawal'),('amount','100.01'),('security_identifier','OTHER'),('reported_realized_gain','1.00')])
def test_mismatched_cash_source_row_cannot_mint_a_page(name,raw):
    facts=brokerage_facts();change_row(facts,name,SourceField(raw,2))
    assert brokerage_activity_pages(facts)==(None,)


@pytest.mark.parametrize(('name','raw'),[('currency','EUR'),('as_of','2025-01-30'),('period_end','2025-01-30'),('opening_cash','1.00'),('closing_cash','99.00'),('period_start','2025-02-01')])
def test_mismatched_source_context_cannot_mint_a_page(name,raw):
    facts=brokerage_facts();change_header(facts,name,SourceField(raw,2))
    assert brokerage_activity_pages(facts)==(None,)


def test_missing_out_of_bounds_and_incomplete_rows_remain_unanchored():
    for field in (None,SourceField('100.00',None),SourceField('100.00',3)):
        facts=brokerage_facts();change_row(facts,'amount',field)
        assert brokerage_activity_pages(facts)==(None,)
    facts=brokerage_facts();facts.investment_source=replace(facts.investment_source,rows=())
    assert brokerage_activity_pages(facts)==(None,)
    facts.investment_source=None
    assert brokerage_activity_pages(facts)==(None,)


@pytest.mark.parametrize(('other_page','expected'),[(1,(None,None)),(2,(2,2))])
def test_identical_rows_require_an_unambiguous_page(other_page,expected):
    facts=brokerage_facts();facts.activity*=2;facts.cash=Decimal('200.00');facts.total=facts.cash
    change_header(facts,'closing_cash',SourceField('200.00',2))
    row=facts.investment_source.rows[0]
    other=tuple((k,SourceField(v.raw,other_page) if k=='amount' else v) for k,v in row)
    facts.investment_source=replace(facts.investment_source,rows=(row,other))
    assert brokerage_activity_pages(facts)==expected


@pytest.mark.parametrize(('name','raw'),[('gross','100.01'),('net','80.01'),('currency','EUR'),('pay_date','2025-01-30')])
def test_payroll_requires_matching_printed_context(name,raw):
    facts=payroll_facts();source=facts.payroll_source
    facts.payroll_source=replace(source,headers=tuple((k,SourceField(raw,2) if k==name else v) for k,v in source.headers))
    assert payroll_decomposition_page(facts) is None


def test_payroll_missing_source_page_and_deduction_mismatch_do_not_anchor():
    facts=payroll_facts();assert payroll_decomposition_page(facts)==2
    facts.validated_source_page_count=None;assert payroll_decomposition_page(facts) is None
    facts=payroll_facts();facts.deductions=[replace(facts.deductions[0],amount=Decimal('21.00'))]
    assert payroll_decomposition_page(facts) is None
    facts=payroll_facts();facts.payroll_source=None;facts.gross_page=2
    assert payroll_decomposition_page(facts) is None


def test_payroll_private_serialization_and_sql_decoder_preserve_optional_bound():
    from viva.ingest.paystub import PayStubFacts
    from viva.sql_authority.payroll import decode
    facts=payroll_facts();data=facts.to_dict()
    assert data['validated_source_page_count']==2
    assert PayStubFacts.from_dict(data).to_dict()==data
    assert decode(data).to_dict()==data
    old=dict(data);old.pop('validated_source_page_count')
    assert decode(old).validated_source_page_count is None
    assert 'validated_source_page_count' not in decode(old).to_dict()
    for value in (True,0,-1,201,'2'):
        with pytest.raises(ValueError):decode({**data,'validated_source_page_count':value})


def test_legacy_positional_payroll_constructor_keeps_acquisition_slot():
    from viva.ingest.paystub import PayStubFacts
    f=payroll_facts();acquisition=None
    old=PayStubFacts(f.doc_id,f.doc_type,f.doc_type_confidence,f.employer,f.currency,f.pay_date,
        f.period_start,f.period_end,f.gross,f.net,f.deductions,f.employee_names,f.gross_page,f.net_page,f.payroll_source,acquisition)
    assert old.acquisition is acquisition and old.payroll_source is f.payroll_source
    assert old.validated_source_page_count is None


def test_raw_model_json_cannot_mint_validated_payroll_page_count():
    from viva.ingest.paystub import from_paystub_json
    packet={'doc_type':'pay_stub','employer':'Synthetic employer','currency':'USD','pay_date_raw':'2025-01-31',
        'period_start_raw':'2025-01-01','period_end_raw':'2025-01-31','gross_raw':'100.00','net_raw':'80.00',
        'deductions':[{'label':'Synthetic withholding','amount_raw':'20.00','category':'tax'}],
        'payroll_source':payroll_facts().payroll_source.to_dict(),'validated_source_page_count':2}
    facts,error=from_paystub_json(json.dumps(packet),'c'*64,'en-US','USD')
    assert error is None,error
    assert facts.validated_source_page_count is None and payroll_decomposition_page(facts) is None


def test_source_page_changes_leave_posting_bodies_unchanged(tmp_path):
    from viva.ingest.brokerage_projector import post_brokerage
    from viva.ledger import Ledger
    bodies=[]
    for page in (1,2):
        ledger=Ledger.open(tmp_path/str(page)/'events.jsonl','synthetic-only');facts=brokerage_facts(source_page=page)
        assert post_brokerage(ledger,facts).action=='posted'
        event=cash_events(ledger,facts.doc_id)[0];assert event.provenance.page==page;bodies.append(event.body)
    assert bodies[0]==bodies[1]


def test_corrected_held_brokerage_activity_uses_source_page_without_reposting(tmp_path):
    from viva.ledger import Ledger
    from viva.ingest.brokerage_projector import post_brokerage,apply_brokerage_activity_correction
    ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only');facts=brokerage_facts();correct=facts.activity[0]
    facts.activity=[replace(correct,amount=Decimal('99.00'))]
    assert post_brokerage(ledger,facts).action=='posted'
    assert cash_events(ledger,facts.doc_id)==[]
    assert apply_brokerage_activity_correction(ledger,facts.doc_id,[correct],opening_cash=Decimal('0.00')).action=='posted'
    cash=cash_events(ledger,facts.doc_id);assert len(cash)==1 and cash[0].provenance.page==2
    with pytest.raises(ValueError):apply_brokerage_activity_correction(ledger,facts.doc_id,[correct],opening_cash=Decimal('0.00'))
    assert len(cash_events(ledger,facts.doc_id))==1
