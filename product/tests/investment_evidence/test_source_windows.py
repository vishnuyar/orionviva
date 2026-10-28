"""Source-shaped date-boundary regression; no model/extraction claim."""
from dataclasses import replace
from pathlib import Path
from decimal import Decimal
import json,os
import pytest
from test_draft import fixture,f,ACCOUNT
from viva.investment.authority import read
from viva.investment.contracts import Request,EvidenceError
from viva.investment.lineage import expand_fields

SOURCE=Path(os.environ.get('INVESTMENT_PUBLIC_SOURCE_LEDGER','/Users/vishnu/.codex/worktrees/five-year-persona/orionviva/output/pdf/synthetic_life_5y/source-ledger.json'))

def first_plan(ref):
 docs=json.loads(SOURCE.read_text())['documents']
 return next(doc for doc in docs if doc['account_ref']==ref and doc['family']=='retirement')

@pytest.mark.parametrize('ref,start,end',[('RET-B','2023-01-01','2023-01-31'),('RET-C','2024-07-01','2024-07-31')])
def test_actual_printed_boundary_does_not_reject_contained_requested_window(ref,start,end):
 doc=first_plan(ref)
 assert doc['period_start']<start and doc['period_end']==end
 rollover=next(row for row in doc['facts']['activity'] if row['counterpart_ref'].startswith('RET-'))
 employee=next(row for row in doc['facts']['activity'] if row['counterpart_ref'].startswith('PAY-'))
 # The typed fixture preserves actual printed period and dates; funding validation
 # has separate committed-source tests. This specifically isolates read selection.
 _,s=fixture(start=doc['period_start'],end=end)
 base=s.rows[0]
 outside=replace(base,observation_id='outside-rollover',local_id='outside',ordinal=0,date=f(rollover['date']),amount=f(rollover['amount']))
 inside=replace(base,observation_id='inside-employee',local_id='inside',ordinal=1,date=f(employee['date']),amount=f(employee['amount']))
 s=replace(s,rows=(outside,inside),closing_cash=f(str(sum(Decimal(row['amount']) for row in (rollover,employee)))))
 result=read((s,),Request('activity_totals',ACCOUNT,'USD',start=start,end=end,grouping='year'))
 contribution=next(v for v in result['figures'] if v['claim']=='investment_contribution')
 assert contribution['value']=='1000.00'
 assert result['source_identities']['rows'][contribution['row_ids'][0]]=='inside-employee'
 assert 'outside-rollover' not in result['source_identities']['rows'].values()
 assert doc['period_start'] in {field['value'] for field in expand_fields(result).values()}


def test_cross_year_statement_assigns_each_exact_dated_row_only_once():
 _,s=fixture(start='2023-12-31',end='2024-01-31')
 a=replace(s.rows[1],observation_id='prior-dividend',local_id='prior',ordinal=0,date=f('2023-12-31'),amount=f('2'))
 b=replace(s.rows[1],observation_id='next-dividend',local_id='next',ordinal=1,date=f('2024-01-01'),amount=f('3'))
 s=replace(s,rows=(a,b))
 result=read((s,),Request('activity_totals',ACCOUNT,'USD',start='2023-12-31',end='2024-01-31',grouping='year'))
 assert [(v['from'],v['value']) for v in result['figures'] if v['claim']=='investment_dividend']==[('2023-12-31','2'),('2024-01-01','3')]


def test_no_preopening_zero_or_missing_tail_or_ambiguous_overlap():
 doc=first_plan('RET-C');_,s=fixture(start=doc['period_start'],end=doc['period_end'])
 for start,end in [('2024-01-01','2024-07-31'),('2024-07-01','2024-08-01')]:
  with pytest.raises(EvidenceError):read((s,),Request('activity_totals',ACCOUNT,'USD',start=start,end=end,grouping='year'))
 overlap=replace(s,observation_id='overlap',start=f('2024-07-01'))
 with pytest.raises(EvidenceError):read((s,overlap),Request('activity_totals',ACCOUNT,'USD',start='2024-07-01',end='2024-07-31',grouping='year'))
