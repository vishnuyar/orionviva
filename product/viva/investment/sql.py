"""Scratch SQL projection of committed investment source lifecycle segments."""
from time import monotonic
import json
from .contracts import *
from .events import source_index,decode_statement,prefix
from .authority import read,check

SCHEMA='''CREATE TABLE IF NOT EXISTS investment_evidence_frontier(singleton INTEGER PRIMARY KEY CHECK(singleton=1),event_count INTEGER NOT NULL,last_event_id TEXT NOT NULL,prefix_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS investment_evidence_statements(segment_id TEXT PRIMARY KEY,observation_id TEXT NOT NULL,root_id TEXT NOT NULL,facet TEXT NOT NULL,account TEXT NOT NULL,currency TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,snapshot_complete INTEGER NOT NULL,effective_from TEXT NOT NULL,effective_to TEXT NOT NULL,status TEXT NOT NULL,record_json TEXT NOT NULL,record_digest TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS investment_evidence_account_period ON investment_evidence_statements(account,currency,facet,start,end,effective_from,effective_to);
CREATE INDEX IF NOT EXISTS investment_evidence_account_snapshot ON investment_evidence_statements(account,currency,facet,snapshot_complete,end,effective_from,effective_to);'''


def materialize(connection,events,resolve_reference=lambda field:None):
 """Materialize one authenticated input frontier; source history stays append-only."""
 if type(events) is not tuple:raise EvidenceError('immutable committed event tuple required')
 segments=source_index(events,resolve_reference).segments(resolve_reference);frontier=prefix(events)
 for command in SCHEMA.split(';'):
  if command.strip():connection.execute(command)
 connection.execute('DELETE FROM investment_evidence_statements')
 for item in segments:
  statement=item['statement'];encoded=canonical(statement).decode()
  if len(encoded.encode())>262144:raise ResourceLimit('source statement storage limit')
  identifier=digest((item['facet'],item['root'],item['from'],item['to'],statement.observation_id,item['status']))
  connection.execute('INSERT INTO investment_evidence_statements VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identifier,statement.observation_id,item['root'],item['facet'],statement.account.value,statement.currency.value,statement.start.value,statement.end.value,int(statement.snapshot_complete),item['from'],item['to'],item['status'],encoded,digest(statement)))
 connection.execute('INSERT OR REPLACE INTO investment_evidence_frontier VALUES(1,?,?,?)',(frontier.event_count,frontier.last_event_id,frontier.prefix_digest))
 from viva.retirement_funding.sql import materialize as retirement_materialize
 retirement_materialize(connection,events)
 return frontier


def read_sql(connection,request,expected_frontier,deadline=None):
 """Select at most one effective segment per source root before decoding."""
 deadline=min(deadline,monotonic()+2) if deadline is not None else monotonic()+2
 check(deadline)
 row=connection.execute('SELECT event_count,last_event_id,prefix_digest FROM investment_evidence_frontier WHERE singleton=1').fetchone()
 if row!=tuple(encode(expected_frontier).values()):raise EvidenceError('SQL source frontier mismatch')
 bounded='CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END'
 if request.view=='positions':
  rows=connection.execute('SELECT '+bounded+',record_digest,status FROM investment_evidence_statements WHERE account=? AND currency=? AND facet=\'positions\' AND snapshot_complete=1 AND effective_from<=? AND effective_to>=? AND end=(SELECT MAX(end) FROM investment_evidence_statements WHERE account=? AND currency=? AND facet=\'positions\' AND snapshot_complete=1 AND effective_from<=? AND effective_to>=? AND end<=?) ORDER BY observation_id LIMIT 121',(request.account,request.currency,request.as_of,request.as_of,request.account,request.currency,request.as_of,request.as_of,request.as_of)).fetchall()
 else:
  rows=connection.execute('SELECT '+bounded+',record_digest,status FROM investment_evidence_statements WHERE account=? AND currency=? AND facet=\'activity\' AND effective_from<=? AND effective_to>=? AND start<=? AND end>=? ORDER BY start,end,observation_id LIMIT 121',(request.account,request.currency,request.end,request.end,request.end,request.start)).fetchall()
 check(deadline)
 if len(rows)>120 or any(type(row[0]) is not str for row in rows):raise ResourceLimit('bounded SQL source refusal')
 statements=[];ids=set()
 for row in rows:
  check(deadline)
  if row[2]!='accepted':raise EvidenceError('selected source change is unresolved')
  try:statement=decode_statement(json.loads(row[0]))
  except (ValueError,TypeError,KeyError) as error:raise EvidenceError('invalid SQL source observation') from error
  if digest(statement)!=row[1]:raise EvidenceError('SQL source observation digest mismatch')
  if statement.account.value!=request.account or statement.currency.value!=request.currency:raise EvidenceError('SQL account/currency mismatch')
  if statement.observation_id in ids:raise EvidenceError('overlapping source lifecycle segments')
  ids.add(statement.observation_id);statements.append(statement)
 return read(tuple(statements),request,deadline)
