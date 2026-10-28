"""Retirement source population within the native authenticated read publication."""
import json
from viva.investment.contracts import EvidenceError, ResourceLimit, canonical, digest, encode
from viva.investment.events import prefix
from viva.investment.payroll import _records, change_dates
from .population import records

SCHEMA = '''CREATE TABLE IF NOT EXISTS retirement_plan_members(account TEXT PRIMARY KEY,currency TEXT NOT NULL,source_json TEXT NOT NULL,source_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retirement_payroll_population(document TEXT NOT NULL,effective_from TEXT NOT NULL,effective_to TEXT NOT NULL,record_json TEXT NOT NULL,record_digest TEXT NOT NULL,PRIMARY KEY(document,effective_from));
CREATE TABLE IF NOT EXISTS retirement_payroll_witnesses(source_id TEXT NOT NULL,effective_from TEXT NOT NULL,effective_to TEXT NOT NULL,source_digest TEXT NOT NULL,pending INTEGER NOT NULL,PRIMARY KEY(source_id,effective_from));
CREATE TABLE IF NOT EXISTS retirement_rollover_closures(cash_event_id TEXT PRIMARY KEY,record_json TEXT NOT NULL,record_digest TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retirement_funding_frontier(singleton INTEGER PRIMARY KEY CHECK(singleton=1),event_count INTEGER NOT NULL,last_event_id TEXT NOT NULL,prefix_digest TEXT NOT NULL);'''


def materialize(connection, events):
    from .posting_closure import materialize_closures
    for command in SCHEMA.split(';'):
        if command.strip():
            connection.execute(command)
    for table in ('retirement_payroll_population', 'retirement_payroll_witnesses', 'retirement_rollover_closures','retirement_plan_members'):
        connection.execute('DELETE FROM ' + table)
    from .population import change_dates as population_dates
    from datetime import date,timedelta
    population_edges=sorted(set(('0001-01-01',*population_dates(events))))
    for index,start in enumerate(population_edges):
        end=(date.fromisoformat(population_edges[index+1])-timedelta(days=1)).isoformat() if index+1<len(population_edges) else '9999-12-31'
        for record in records(events,start):
            payload=canonical(record).decode()
            if len(payload.encode())>262144:raise ResourceLimit('payroll population source storage bound')
            connection.execute('INSERT INTO retirement_payroll_population VALUES(?,?,?,?,?)',(record['document'],start,end,payload,digest(record)))
    edges = sorted(set(('0001-01-01', *change_dates(events))))
    from datetime import date, timedelta
    for index, start in enumerate(edges):
        end = (date.fromisoformat(edges[index + 1]) - timedelta(days=1)).isoformat() if index + 1 < len(edges) else '9999-12-31'
        for event, source, pending in _records(events, start):
            connection.execute('INSERT INTO retirement_payroll_witnesses VALUES(?,?,?,?,?)', (event.event_id, start, end, digest(event.body), int(pending)))
    # Membership is a normalized source role with a current exact payroll witness.
    current={event.event_id:(digest(event.body),pending) for event,source,pending in _records(events)}
    from viva.investment.events import decode_statement
    candidates=connection.execute("SELECT record_json,record_digest FROM investment_evidence_statements WHERE status='accepted' AND facet='activity' AND effective_to='9999-12-31' ORDER BY observation_id").fetchall()
    known=set()
    for payload,body_digest in candidates:
        source=decode_statement(json.loads(payload))
        if digest(source)!=body_digest:raise EvidenceError('retirement membership normalized source differs')
        if source.account.value in known:continue
        for row in source.rows:
            dependency=getattr(row.funding_witness,'payroll_dependency',None)
            if row.funding_status=='accepted' and dependency is not None and current.get(dependency.source_event_id)==(dependency.source_body_digest,False):
                connection.execute('INSERT INTO retirement_plan_members VALUES(?,?,?,?)',(source.account.value,source.currency.value,payload,body_digest));known.add(source.account.value);break
    for cash_id, record in materialize_closures(events).items():
        payload = canonical(record).decode()
        if len(payload.encode()) > 262144:
            raise ResourceLimit('rollover posting closure storage bound')
        connection.execute('INSERT INTO retirement_rollover_closures VALUES(?,?,?)', (cash_id, payload, digest(record)))
    frontier = prefix(events)
    connection.execute('INSERT OR REPLACE INTO retirement_funding_frontier VALUES(1,?,?,?)', tuple(encode(frontier).values()))


def decode_record(row):
    if row is None or type(row[0]) is not str:
        raise EvidenceError('bounded retirement source unavailable')
    result = json.loads(row[0])
    if digest(result) != row[1]:
        raise EvidenceError('retirement normalized record digest differs')
    return result


def read_sql(connection, frontier, request, deadline):
    from .authority import read
    from viva.investment.events import decode_statement
    from viva.investment.authority import check
    check(deadline)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='retirement_funding_frontier'").fetchone() is None:raise EvidenceError('retirement native projection unavailable')
    actual = connection.execute('SELECT event_count,last_event_id,prefix_digest FROM retirement_funding_frontier WHERE singleton=1').fetchone()
    if actual != tuple(encode(frontier).values()):
        raise EvidenceError('retirement source frontier differs')
    population_rows = connection.execute('SELECT CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END,record_digest FROM retirement_payroll_population WHERE effective_from<=? AND effective_to>=? ORDER BY document LIMIT 121',(request.ending,request.ending)).fetchall() if request.view=='annual_employee_contributions' else []
    if len(population_rows) > 120:
        raise ResourceLimit('recorded payroll population exceeds enumeration bound')
    population = [decode_record(row) for row in population_rows]
    placeholders = ','.join('?' for _ in request.plans)
    if request.view=='annual_employee_contributions':
        bounded="CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END"
        statement_rows=connection.execute("SELECT "+bounded+",record_digest,status FROM investment_evidence_statements WHERE currency=? AND facet='activity' AND effective_from<=? AND effective_to>=? AND start<=? AND end>=? AND EXISTS(SELECT 1 FROM json_each("+bounded+",'$.rows') AS row WHERE json_type(row.value,'$.funding_witness.payroll_dependency')='object') ORDER BY observation_id LIMIT 121",(request.currency,request.ending,request.ending,request.ending,request.beginning)).fetchall()
    else:
        statement_rows = connection.execute("SELECT CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END,record_digest,status FROM investment_evidence_statements WHERE account IN (" + placeholders + ") AND currency=? AND facet='activity' AND effective_from<=? AND effective_to>=? AND start<=? AND end>=? ORDER BY observation_id LIMIT 121", (*request.plans, request.currency, request.ending, request.ending, request.ending, request.beginning)).fetchall()
    if len(statement_rows) > 120:
        raise ResourceLimit('retirement statement bound')
    statements = []
    # Membership needs a sourced employee-retirement destination, rather than
    # a generic investment kind or account display label.
    membership=[]
    for plan in request.plans:
        candidate=connection.execute('SELECT CASE WHEN length(CAST(source_json AS BLOB))<=262144 THEN source_json END,source_digest FROM retirement_plan_members WHERE account=? AND currency=?',(plan,request.currency)).fetchone()
        if candidate is None:raise EvidenceError('accepted retirement-plan membership unavailable')
        membership.append(decode_statement(decode_record(candidate)))
    for row in statement_rows:
        check(deadline)
        if row[2] != 'accepted':
            raise EvidenceError('selected retirement source revision unresolved')
        statements.append(decode_statement(decode_record(row[:2])))
    witnesses = {row[0]: (row[1], bool(row[2])) for row in connection.execute('SELECT source_id,source_digest,pending FROM retirement_payroll_witnesses WHERE effective_from<=? AND effective_to>=?', (request.ending, request.ending)).fetchall()}
    closure = {}
    for statement in statements:
        for row in statement.rows:
            if row.kind.value == 'contribution' and row.funding_role == 'retirement_rollover' and row.funding_witness is not None:
                for cash_id in (row.cash_event_id, row.funding_witness.transaction_id):
                    closure[cash_id] = decode_record(connection.execute('SELECT CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END,record_digest FROM retirement_rollover_closures WHERE cash_event_id=?', (cash_id,)).fetchone())
    observations={source.observation_id for source in (*statements,*membership)}|{record['id'] for record in population}
    if len(observations)>120:raise ResourceLimit('combined retirement source observation bound')
    occurrences=sum(len(source.rows) for source in {source.observation_id:source for source in (*statements,*membership)}.values())+sum(len(record['population']['source']['deductions']) if record.get('population') else 1 for record in population)
    if occurrences>1000:raise ResourceLimit('combined retirement source occurrence bound')
    result = read(tuple(statements), tuple(population), witnesses, closure, request, deadline, membership=tuple(membership))
    check(deadline)
    return result
