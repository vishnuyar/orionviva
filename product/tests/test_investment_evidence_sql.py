import sqlite3
from dataclasses import replace
import pytest
from test_investment_evidence_contracts import fixture,resolve,ACCOUNT
from viva.ledger.ledger import Ledger
from viva.investment.events import append_statement,committed_statements,prefix
from viva.investment.authority import read
from viva.investment.contracts import Request,EvidenceError,ResourceLimit
from viva.investment.sql import materialize,read_sql


def test_sql_matches_committed_event_read_and_frontier(tmp_path):
 events,s=fixture();l=Ledger.open(tmp_path/'test.jsonl','synthetic-only')
 for e in events:l.append(e)
 append_statement(l,s,resolve)
 committed=tuple(l.events());c=sqlite3.connect(':memory:');frontier=materialize(c,committed,resolve)
 r=Request('activity_totals',ACCOUNT,'USD',start='2025-01-01',end='2025-12-31',grouping='year')
 assert read_sql(c,r,frontier)==read(committed_statements(committed,resolve),r)
 with pytest.raises(EvidenceError,match='frontier'):read_sql(c,r,replace(frontier,prefix_digest='0'*64))
 assert any('investment_evidence_account_period' in str(row) for row in c.execute("EXPLAIN QUERY PLAN SELECT record_json FROM investment_evidence_statements WHERE account=? AND currency=? AND facet='activity' AND effective_from<=? AND effective_to>=? AND start<=? AND end>=? ORDER BY start,end,observation_id LIMIT 121",(ACCOUNT,'USD','2025-12-31','2025-12-31','2025-12-31','2025-01-01')))

@pytest.mark.parametrize('payload',['{' ,' '*262145,'é'*140000])
def test_bad_sql_source_refuses_before_answer(tmp_path,payload):
 events,s=fixture();l=Ledger.open(tmp_path/'test.jsonl','synthetic-only')
 for e in events:l.append(e)
 append_statement(l,s,resolve);c=sqlite3.connect(':memory:');frontier=materialize(c,tuple(l.events()),resolve)
 c.execute('UPDATE investment_evidence_statements SET record_json=?',(payload,))
 with pytest.raises(EvidenceError):read_sql(c,Request('positions',ACCOUNT,'USD',as_of='2025-12-31'),frontier)


def test_valid_json_cent_mutation_is_withheld_by_record_dependency(tmp_path):
 import json
 events,s=fixture();l=Ledger.open(tmp_path/'test.jsonl','synthetic-only')
 for e in events:l.append(e)
 append_statement(l,s,resolve);c=sqlite3.connect(':memory:');frontier=materialize(c,tuple(l.events()),resolve)
 source=json.loads(c.execute('SELECT record_json FROM investment_evidence_statements').fetchone()[0]);source['positions'][0]['basis']['value']='20.01'
 c.execute('UPDATE investment_evidence_statements SET record_json=?',(json.dumps(source),))
 with pytest.raises(EvidenceError,match='digest'):read_sql(c,Request('positions',ACCOUNT,'USD',as_of='2025-12-31'),frontier)
