"""New cash provenance follows bounded matching printed fields."""
from decimal import Decimal
import json
import pytest
from viva.ingest.brokerage import from_brokerage_json
from viva.ingest.brokerage_projector import post_brokerage
from viva.ingest.paystub import Deduction, PayStubFacts
from viva.ingest.paystub_projector import post_paystub
from viva.investment.extraction import HEADERS, ROW, SourceField
from viva.investment.payroll_extraction import PayrollSourceExtraction, HEADERS as PAYROLL_HEADERS, DEDUCTION
from viva.ledger import Ledger
from viva.ledger.events import Provenance, account_opened
from viva.ledger.postings import simple_transaction


# An unmasked synthetic full number keeps the numeric resolution path.
SYNTHETIC_BROKER_NUMBER = '12341234'


def brokerage_facts(*, source_page=2, count=2):
    def field(raw):return {'raw':raw,'page':source_page}
    headers={name:None for name in HEADERS}
    headers.update(account_reference=field('BROKER-REF'),currency=field('USD'),
        period_start=field('2025-01-01'),period_end=field('2025-01-31'),as_of=field('2025-01-31'),
        opening_cash=field('0.00'),closing_cash=field('100.00'))
    row={name:None for name in ROW}
    row.update(date=field('2025-01-15'),kind=field('contribution'),amount=field('100.00'))
    packet={'doc_type':'brokerage_statement','doc_type_confidence':0.98,
        'account_ref':'Test investment','institution':'Synthetic issuer','account_number':SYNTHETIC_BROKER_NUMBER,
        'as_of_raw':'2025-01-31','cash_raw':'100.00','total_raw':'100.00','opening_cash_raw':'0.00',
        'positions':[],'activity':[{'date_raw':'2025-01-15','kind':'contribution','amount_raw':'100.00','description':'Synthetic contribution'}],
        'investment_source':{'schema':'investment-source-v1','headers':headers,'positions':[],'rows':[row]}}
    facts,error=from_brokerage_json(json.dumps(packet),'a'*64,'en-US','USD')
    assert error is None,error
    facts.validated_source_page_count=count
    return facts


def payroll_facts(*, count=2):
    values={'source_reference':'PAY-PRINTED','currency':'USD','pay_date':'2025-01-31','gross':'100.00','net':'80.00'}
    row={'label':'Synthetic withholding','category':'tax','amount':'20.00'}
    source=PayrollSourceExtraction(tuple((name,SourceField(values[name],2)) for name in PAYROLL_HEADERS),
        (tuple((name,SourceField(row[name],2) if name in row else None) for name in DEDUCTION),))
    facts=PayStubFacts('b'*64,'pay_stub',0.98,'Synthetic employer','USD','2025-01-31','2025-01-01','2025-01-31',
        Decimal('100.00'),Decimal('80.00'),[Deduction('Synthetic withholding',Decimal('20.00'),'tax')],payroll_source=source)
    facts.validated_source_page_count=count
    return facts


def cash_events(ledger,doc):
    return [event for event in ledger.events() if event.event_type=='TransactionRecorded' and event.provenance.doc_id==doc]


def test_brokerage_cash_writer_uses_matching_validated_amount_page(tmp_path):
    ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
    facts=brokerage_facts();out=post_brokerage(ledger,facts)
    assert out.action=='posted'
    cash=cash_events(ledger,facts.doc_id);assert len(cash)==1
    assert sum(Decimal(p['amount']) for p in cash[0].body['postings'])==0
    assert cash[0].provenance.page==2
    before=[event.to_dict() for event in cash]
    assert post_brokerage(ledger,facts).action=='duplicate'
    assert [event.to_dict() for event in cash_events(ledger,facts.doc_id)]==before


def test_payroll_cash_writer_uses_matching_validated_gross_page(tmp_path):
    ledger=Ledger.open(tmp_path/'events.jsonl','synthetic-only')
    ledger.append(account_opened('bank','depository','Synthetic checking','USD','2025-01-01'))
    ledger.append(simple_transaction('bank','80.00','Synthetic net pay','2025-01-31',provenance=Provenance('deposit',1)))
    facts=payroll_facts();out=post_paystub(ledger,facts)
    assert out.action=='posted'
    cash=cash_events(ledger,facts.doc_id);assert len(cash)==1
    assert cash[0].body['matched_movement_key']
    assert cash[0].body['matched_currency']=='USD'
    assert cash[0].provenance.page==2
    before=[event.to_dict() for event in cash]
    assert post_paystub(ledger,facts).action=='duplicate'
    assert [event.to_dict() for event in cash_events(ledger,facts.doc_id)]==before
