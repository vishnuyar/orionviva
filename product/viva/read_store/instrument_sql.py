"""Normalized instrument histories and source-frontier effect retirement."""
from __future__ import annotations

import json
from types import SimpleNamespace

from ..ledger.instruments import (
    decode_change, family_event, fold_change, observation_event,
)

MAX_INSTRUMENT_HISTORY = 10000
MAX_INSTRUMENT_RECORD_BYTES = 1000000


def create_tables(connection):
    connection.execute('''CREATE TABLE instrument_family_history (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        event_id TEXT NOT NULL, account_id TEXT NOT NULL, family TEXT NOT NULL,
        effective TEXT NOT NULL, doc_id TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_observation_history (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        event_id TEXT NOT NULL, observation_id TEXT NOT NULL UNIQUE, subject_id TEXT NOT NULL,
        kind TEXT NOT NULL, operation TEXT NOT NULL, prior_id TEXT,
        effective TEXT NOT NULL, record_json TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_effects (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        observation_id TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_effect_dependencies (
        source_sequence INTEGER NOT NULL REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        dependency_id TEXT NOT NULL, PRIMARY KEY(source_sequence,dependency_id))''')
    connection.execute('''CREATE TABLE financial_references (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        event_id TEXT NOT NULL, reference TEXT NOT NULL, counterparty_reference TEXT NOT NULL)''')
    connection.execute("""CREATE TABLE instrument_source_reads (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        doc_id TEXT NOT NULL, event_id TEXT NOT NULL, occurred_at TEXT NOT NULL, body_json TEXT NOT NULL)""")
    connection.execute("""CREATE TABLE instrument_cash_dependencies (
        source_sequence INTEGER PRIMARY KEY REFERENCES transactions(source_sequence) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
        event_id TEXT NOT NULL UNIQUE, body_digest TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER NOT NULL)""")
    connection.execute('''CREATE TABLE instrument_allocations (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        movement_key TEXT NOT NULL, effective TEXT NOT NULL, allocation_json TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_component_states (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        observation_id TEXT NOT NULL, effective TEXT NOT NULL, state_json TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_cash_roles (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        role TEXT NOT NULL)''')
    connection.execute('''CREATE TABLE instrument_account_references (
        source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,
        account_id TEXT NOT NULL, reference TEXT NOT NULL, scope TEXT NOT NULL,
        effective TEXT NOT NULL, doc_id TEXT NOT NULL, page INTEGER NOT NULL,
        identity_page_count INTEGER)''')
    connection.execute('CREATE INDEX instrument_families_by_account ON instrument_family_history(account_id,effective,source_sequence)')
    connection.execute('CREATE INDEX instrument_observations_by_subject ON instrument_observation_history(subject_id,kind,effective,source_sequence)')
    connection.execute('CREATE INDEX instrument_effects_by_observation ON instrument_effects(observation_id,source_sequence)')


def _text_columns(columns):
    from .scalar_bounds import selected
    return selected(columns)


def _text_rows(rows, columns, label):
    from .scalar_bounds import refuse
    from .store import ReadStoreError
    refuse(rows, columns, label=label)
    if any(type(value) is not str or not value for row in rows for value in row):
        raise ReadStoreError(f"{label} has invalid text")


def _rows(connection, sql, parameters, label):
    from .store import ReadStoreError
    rows = connection.execute(sql, parameters).fetchall()
    if len(rows) > MAX_INSTRUMENT_HISTORY:
        raise ReadStoreError(f"{label} exceeds its row read bound")
    return rows


def _json(value, label):
    from .store import ReadStoreError
    if type(value) is not str or len(value.encode("utf-8")) > MAX_INSTRUMENT_RECORD_BYTES:
        raise ReadStoreError(f"{label} exceeds its UTF-8 byte bound")
    try:
        return json.loads(value)
    except (TypeError, ValueError) as error:
        raise ReadStoreError(f"{label} is invalid JSON") from error


def _history(rows):
    from .store import ReadStoreError
    _text_rows([(row[0],) for row in rows], ("event_id",), "Instrument observation identity")
    history = {}
    try:
        for event_id, encoded in rows:
            change = decode_change(_json(encoded, "Instrument observation record"))
            event = observation_event(change)
            event.event_id = event_id
            fold_change(history, event)
    except (TypeError, ValueError) as error:
        raise ReadStoreError("Instrument observation history is invalid") from error
    return history


def observation_history(connection):
    selected, bounds = _text_columns(("event_id",))
    rows = _rows(connection, f"SELECT {selected},"
        "CASE WHEN length(CAST(record_json AS BLOB))<=? THEN record_json END "
        "FROM instrument_observation_history ORDER BY source_sequence LIMIT ?",
        (*bounds, MAX_INSTRUMENT_RECORD_BYTES, MAX_INSTRUMENT_HISTORY + 1), "Instrument observation history")
    return _history(rows)


def materialize(connection, entry):
    from ..ingest.instrument_contracts import Source
    from ..ledger.events import Event
    event = Event.from_dict(entry.event.to_dict())
    body = event.body
    if event.event_type == 'ReadRecorded' and body.get('phase','extract')=='extract' and body.get('doc_id'):
        encoded=json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        if len(encoded.encode('utf-8'))>MAX_INSTRUMENT_RECORD_BYTES:
            encoded='{}'
        connection.execute('INSERT INTO instrument_source_reads VALUES(?,?,?,?,?)',
            (entry.sequence,body['doc_id'],event.event_id,event.occurred_at,encoded))
        connection.execute("DELETE FROM instrument_allocations WHERE json_extract(allocation_json,'$.receipt.payment.reference.source.doc_id')=? "
            "AND json_extract(allocation_json,'$.receipt.source_read_event_id')!=?",(body['doc_id'],event.event_id))
    if event.event_type == 'InstrumentFamilyDeclared':
        family_event(body.get('account_id'), body.get('family'), event.occurred_at,
                     Source(event.provenance.doc_id, event.provenance.page))
        if set(body) - {'account_id', 'family', 'instrument_declaration_key'}:
            raise ValueError('unknown instrument family fields')
        connection.execute('INSERT INTO instrument_family_history VALUES(?,?,?,?,?,?)',
            (entry.sequence, event.event_id, body['account_id'], body['family'], event.occurred_at, event.provenance.doc_id))
    if event.event_type == 'FinancialAccountReferenceObserved':
        from ..ledger.instruments import reference_event
        reference_event(body.get('account_id'), body.get('reference'), event.occurred_at,
                        Source(event.provenance.doc_id, event.provenance.page), scope=body.get('scope'),
                        identity_page_count=body.get('identity_page_count'))
        connection.execute('INSERT INTO instrument_account_references VALUES(?,?,?,?,?,?,?,?)',
            (entry.sequence, body['account_id'], body['reference'], body['scope'], event.occurred_at,
             event.provenance.doc_id, event.provenance.page, body.get('identity_page_count')))
    if event.event_type in {'InstrumentPaymentAllocated','InstrumentKnownPaymentAllocated'}:
        from ..ingest.instrument_effects import allocation_from_event
        from ..ingest.mortgage_known_allocation import known_allocation_from_event
        allocation = known_allocation_from_event(event) if event.event_type=='InstrumentKnownPaymentAllocated' else allocation_from_event(event)
        if event.event_type=='InstrumentKnownPaymentAllocated':
            from ..ingest.mortgage_known_allocation import validate_source_binding
            row=connection.execute('SELECT body_digest,doc_id,page FROM instrument_cash_dependencies WHERE event_id=?',
                (allocation.receipt.cash_event_id,)).fetchone()
            cash=None if row is None else (row[0],Source(row[1],row[2]))
            source=connection.execute('SELECT event_id,occurred_at,body_json FROM instrument_source_reads WHERE doc_id=? ORDER BY source_sequence DESC LIMIT 1',
                (allocation.payment.reference.source.doc_id,)).fetchone()
            reading=None
            if source is not None:
                reading=Event('ReadRecorded',source[1],_json(source[2],'Instrument retained reading'))
                reading.event_id=source[0]
            validate_source_binding(allocation,observation_history(connection),cash,reading)
            validate_known_sql(connection,allocation)
        connection.execute('INSERT INTO instrument_allocations VALUES(?,?,?,?)',
            (entry.sequence, allocation.movement_key, event.occurred_at,
             json.dumps(body['allocation'], sort_keys=True, separators=(',', ':'))))
    if event.event_type == 'InstrumentComponentStateRecorded':
        from ..ingest.instrument_effects import component_state_from_event
        state = component_state_from_event(event)
        connection.execute('INSERT INTO instrument_component_states VALUES(?,?,?,?)',
            (entry.sequence, state.observation_id, event.occurred_at,
             json.dumps(body['state'], sort_keys=True, separators=(',', ':'))))
    if event.event_type == 'InstrumentObservationRecorded':
        history = observation_history(connection)
        change = fold_change(history, event)
        if change.prior_id is not None:
            # Disposable movement indexes reference postings immediately. Clear
            # them inside this unpublished generation before retiring source
            # effects; the normal refresh rebuilds them from surviving rows.
            connection.execute('DELETE FROM account_ledger_component_index')
            connection.execute('DELETE FROM movement_tags')
            connection.execute('DELETE FROM movements')
            # These are disposable derived rows, not deletions from the event log.
            for table in ('transaction_tags', 'postings', 'document_account_history', 'positions',
                          'balance_observations', 'statement_periods', 'posted_document_events',
                          'category_history', 'transfer_history', 'transactions', 'financial_references',
                          'instrument_allocations', 'instrument_component_states', 'instrument_cash_roles'):
                connection.execute(f'DELETE FROM {table} WHERE source_sequence IN '
                    '(SELECT source_sequence FROM instrument_effects WHERE observation_id=? UNION '
                    'SELECT source_sequence FROM instrument_effect_dependencies WHERE dependency_id=?)',
                    (change.prior_id, change.prior_id))
            retired = connection.execute('SELECT source_sequence FROM instrument_effects WHERE observation_id=? UNION '
                'SELECT source_sequence FROM instrument_effect_dependencies WHERE dependency_id=? LIMIT ?',
                (change.prior_id, change.prior_id, MAX_INSTRUMENT_HISTORY + 1)).fetchall()
            if len(retired) > MAX_INSTRUMENT_HISTORY:
                from .store import ReadStoreError
                raise ReadStoreError('Instrument retired effects exceed their row read bound')
            for (sequence,) in retired:
                connection.execute('DELETE FROM instrument_effects WHERE source_sequence=?', (sequence,))
                connection.execute('DELETE FROM instrument_effect_dependencies WHERE source_sequence=?', (sequence,))
        encoded = json.dumps(body['record'], sort_keys=True, separators=(',', ':'))
        if len(encoded.encode('utf-8')) > MAX_INSTRUMENT_RECORD_BYTES:
            raise ValueError('instrument observation record exceeds its bound')
        connection.execute('INSERT INTO instrument_observation_history VALUES(?,?,?,?,?,?,?,?,?)',
            (entry.sequence, event.event_id, change.observation_id, change.subject_id, change.kind.value,
             change.operation.value, change.prior_id, change.effective.value, encoded))
    origin = body.get('instrument_observation_id')
    if origin is not None:
        history = observation_history(connection)
        if type(origin) is not str or origin not in history or history[origin]['superseded']:
            raise ValueError('financial effect has no live instrument observation')
        dependencies = body.get('instrument_dependencies', [])
        if (type(dependencies) is not list or len(dependencies) > 1000
                or any(type(value) is not str or value not in history or history[value]['superseded'] for value in dependencies)):
            raise ValueError('invalid closed financial effect dependencies')
        connection.execute('INSERT INTO instrument_effects VALUES(?,?)', (entry.sequence, origin))
        for dependency in set(dependencies):
            connection.execute('INSERT INTO instrument_effect_dependencies VALUES(?,?)', (entry.sequence, dependency))
    if event.event_type == 'TransactionRecorded':
        role = body.get('instrument_role')
        if role is not None:
            from ..ledger.instruments import INSTRUMENT_ROLES
            if role not in INSTRUMENT_ROLES:
                raise ValueError('unknown financial instrument movement role')
            connection.execute('INSERT INTO instrument_cash_roles VALUES(?,?)', (entry.sequence, role))
        reference, counterparty = body.get('source_reference', ''), body.get('counterparty_reference', '')
        if type(reference) is not str or type(counterparty) is not str:
            raise ValueError('financial references must be text')
        if reference and counterparty and event.provenance.doc_id and type(event.provenance.page) is int and event.provenance.page >= 1:
            from ..ingest.mortgage_known_allocation import body_digest
            connection.execute('INSERT INTO instrument_cash_dependencies VALUES(?,?,?,?,?)',
                (entry.sequence,event.event_id,body_digest(body),event.provenance.doc_id,event.provenance.page))
        if reference or counterparty:
            connection.execute('INSERT INTO financial_references VALUES(?,?,?,?)',
                               (entry.sequence, event.event_id, reference, counterparty))


def _restrictions(family_rows, history, as_of):
    from datetime import date
    from ..ledger.instruments import account_restrictions, observations_as_of
    from .store import ReadStoreError
    columns = ("account_id", "family", "event_id", "doc_id", "effective")
    _text_rows(family_rows, columns, "Instrument family identity")
    families = {}
    try:
        for account, family, event_id, doc_id, effective in family_rows:
            if family not in {"term_deposit", "escrow"}:
                raise ValueError("invalid closed instrument family")
            if date.fromisoformat(effective).isoformat() != effective:
                raise ValueError("invalid instrument family date")
            families.setdefault(account, []).append(dict(family=family, event_id=event_id, doc_id=doc_id, effective=effective))
        history = observations_as_of(history, as_of)
        return account_restrictions(SimpleNamespace(_instrument_families=families, _instrument_observations=history))
    except (TypeError, ValueError) as error:
        raise ReadStoreError("Instrument restriction history is invalid") from error


def restrictions(connection, as_of):
    selected, bounds = _text_columns(("account_id", "family", "event_id", "doc_id", "effective"))
    rows = _rows(connection, f"SELECT {selected} FROM instrument_family_history "
        "WHERE effective<=? ORDER BY source_sequence LIMIT ?",
        (*bounds, as_of, MAX_INSTRUMENT_HISTORY + 1), "Instrument family history")
    return _restrictions(rows, observation_history(connection), as_of)


def _allocations(rows, connection=None):
    from ..ingest.mortgage_known_allocation import decode_allocation
    from .store import ReadStoreError
    result = {}
    try:
        for (encoded,) in rows:
            allocation = decode_allocation(_json(encoded, "Instrument allocation"))
            from ..ingest.mortgage_known_allocation import KnownPaymentAllocation
            if type(allocation) is KnownPaymentAllocation and connection is not None:
                try:
                    validate_known_sql(connection,allocation)
                except ValueError:
                    continue
            if allocation.movement_key in result and result[allocation.movement_key] != allocation:
                raise ReadStoreError("Conflicting live instrument allocations")
            result[allocation.movement_key] = allocation
    except (TypeError, ValueError) as error:
        raise ReadStoreError("Instrument allocation is invalid") from error
    return result


def allocations(connection, as_of):
    rows = _rows(connection, "SELECT CASE WHEN length(CAST(allocation_json AS BLOB))<=? THEN allocation_json END "
        "FROM instrument_allocations WHERE effective<=? ORDER BY source_sequence LIMIT ?",
        (MAX_INSTRUMENT_RECORD_BYTES, as_of, MAX_INSTRUMENT_HISTORY + 1), "Instrument allocations")
    return _allocations(rows,connection)


def _roles(rows):
    from ..ledger.instruments import INSTRUMENT_ROLES
    from .store import ReadStoreError
    _text_rows(rows, ("movement_key", "role"), "Instrument cash role")
    if any(role not in INSTRUMENT_ROLES for _, role in rows):
        raise ReadStoreError("Instrument cash role is invalid")
    return dict(rows)


def cash_roles(connection):
    selected, bounds = _text_columns(("m.movement_key", "r.role"))
    rows = _rows(connection, f"SELECT {selected} FROM movements m "
        "JOIN instrument_cash_roles r ON r.source_sequence=m.source_sequence LIMIT ?",
        (*bounds, MAX_INSTRUMENT_HISTORY + 1), "Instrument cash roles")
    return _roles(rows)


def _split(rows, kinds):
    from .store import ReadStoreError
    out = {kind: [] for kind in kinds}
    for row in rows:
        if row[0] not in out or type(row[1]) is not int or row[1] < 1:
            raise ReadStoreError("Instrument snapshot has invalid source identity")
        out[row[0]].append(row[1:])
    if any(len(values) > MAX_INSTRUMENT_HISTORY for values in out.values()):
        raise ReadStoreError("Instrument snapshot exceeds its row read bound")
    return out


def restriction_snapshot(connection, as_of):
    """One bounded crossing for source families and the complete typed frontier."""
    columns = ("account_id", "family", "event_id", "doc_id", "effective")
    family, family_bounds = _text_columns(columns)
    event, event_bounds = _text_columns(("event_id",))
    rows = connection.execute(
        f"WITH families(source_sequence,account_id,family,event_id,doc_id,effective) AS (SELECT source_sequence,{family} "
        "FROM instrument_family_history WHERE effective<=? ORDER BY source_sequence LIMIT ?),"
        f"observations(source_sequence,event_id,record_json) AS (SELECT source_sequence,{event},"
        "CASE WHEN length(CAST(record_json AS BLOB))<=? THEN record_json END "
        "FROM instrument_observation_history ORDER BY source_sequence LIMIT ?) "
        "SELECT 'family',source_sequence,account_id,family,event_id,doc_id,effective FROM families "
        "UNION ALL SELECT 'observation',source_sequence,event_id,record_json,NULL,NULL,NULL FROM observations",
        (*family_bounds, as_of, MAX_INSTRUMENT_HISTORY + 1, *event_bounds,
         MAX_INSTRUMENT_RECORD_BYTES, MAX_INSTRUMENT_HISTORY + 1)).fetchall()
    split = _split(rows, ("family", "observation"))
    families = [row[1:] for row in split["family"]]
    observations = [(row[1], row[2]) for row in sorted(split["observation"], key=lambda value: value[0])]
    return _restrictions(families, _history(observations), as_of)


def financial_overlay_snapshot(connection, as_of):
    """One bounded crossing for exact allocations and movement-role overlays."""
    selected, bounds = _text_columns(("m.movement_key", "r.role"))
    rows = connection.execute(
        "WITH allocated(source_sequence,allocation_json) AS (SELECT source_sequence,"
        "CASE WHEN length(CAST(allocation_json AS BLOB))<=? THEN allocation_json END "
        "FROM instrument_allocations WHERE effective<=? ORDER BY source_sequence LIMIT ?),"
        f"roles(source_sequence,movement_key,role) AS (SELECT m.source_sequence,{selected} FROM movements m "
        "JOIN instrument_cash_roles r ON r.source_sequence=m.source_sequence "
        "WHERE m.occurred_at<=? ORDER BY m.source_sequence,m.posting_index LIMIT ?) "
        "SELECT 'allocation',source_sequence,NULL,allocation_json FROM allocated "
        "UNION ALL SELECT 'role',source_sequence,movement_key,role FROM roles",
        (MAX_INSTRUMENT_RECORD_BYTES, as_of, MAX_INSTRUMENT_HISTORY + 1, *bounds,
         as_of, MAX_INSTRUMENT_HISTORY + 1)).fetchall()
    split = _split(rows, ("allocation", "role"))
    return (_allocations([(row[2],) for row in split["allocation"]],connection),
            _roles([(row[1], row[2]) for row in split["role"]]))


def validate_known_sql(connection,allocation):
    """Revalidate the closed association against current native financial rows."""
    from ..ingest.mortgage_known_allocation import validate_source_binding,validate_identities
    from ..ingest.instrument_contracts import Source, ContractError
    from ..ledger.events import Event
    from ..ledger.movement_identity import movement_key
    from decimal import Decimal
    from datetime import date
    receipt=allocation.receipt
    if connection.execute('SELECT 1 FROM documents WHERE doc_id=? LIMIT 1',(receipt.bank_source.doc_id,)).fetchone() is None:
        raise ContractError('retained cash source document required')
    history=observation_history(connection)
    cash=connection.execute('SELECT body_digest,doc_id,page FROM instrument_cash_dependencies WHERE event_id=?',
        (receipt.cash_event_id,)).fetchone()
    source=connection.execute('SELECT event_id,occurred_at,body_json FROM instrument_source_reads WHERE doc_id=? ORDER BY source_sequence DESC LIMIT 1',
        (allocation.payment.reference.source.doc_id,)).fetchone()
    reading=None
    if source is not None:
        reading=Event('ReadRecorded',source[1],_json(source[2],'Instrument retained reading'));reading.event_id=source[0]
    docs=tuple(sorted({row['change'].source.doc_id for row in history.values()
        if not row['superseded'] and row['change'].subject_id==receipt.loan_account}))
    if len(docs)>120:
        raise ContractError('known allocation source-reading resource limit')
    readings={}
    if docs:
        marks=','.join('?' for _ in docs)
        rows=connection.execute(f'SELECT r.doc_id,r.event_id,r.occurred_at,r.body_json FROM instrument_source_reads r WHERE r.doc_id IN ({marks}) '
            'AND r.source_sequence=(SELECT MAX(n.source_sequence) FROM instrument_source_reads n WHERE n.doc_id=r.doc_id) LIMIT 121',docs).fetchall()
        if len(rows)>120:
            raise ContractError('known allocation source-reading resource limit')
        for doc,event_id,dated,encoded in rows:
            retained=Event('ReadRecorded',dated,_json(encoded,'Instrument retained reading'));retained.event_id=event_id
            readings[doc]=retained
    validate_source_binding(allocation,history,None if cash is None else (cash[0],Source(cash[1],cash[2])),reading,readings)
    accounts=tuple(dict.fromkeys((receipt.loan_account,receipt.escrow_account,receipt.funding_account)))
    marks=','.join('?' for _ in accounts)
    rows=connection.execute(f'SELECT account_id,reference,scope FROM instrument_account_references WHERE account_id IN ({marks}) LIMIT 121',accounts).fetchall()
    if len(rows)>120:
        raise ContractError('known allocation identity resource limit')
    references={account:tuple((reference,scope) for owner,reference,scope in rows if owner==account) for account in accounts}
    rows=connection.execute(f'SELECT account_id,kind,currency FROM accounts a WHERE account_id IN ({marks}) '
        'AND kind IS NOT NULL AND source_sequence=(SELECT MAX(b.source_sequence) FROM accounts b WHERE b.account_id=a.account_id AND b.kind IS NOT NULL) LIMIT 4',accounts).fetchall()
    kinds={account:(kind,currency) for account,kind,currency in rows}
    change=history[receipt.observation_id]['change']
    validate_identities(receipt,change,references,kinds)
    rows=connection.execute('SELECT a.event_id,t.occurred_at,p.amount_text,t.description,t.provenance_doc_id,t.provenance_page '
        'FROM financial_references r JOIN transactions t ON t.source_sequence=r.source_sequence '
        'JOIN postings p ON p.source_sequence=t.source_sequence JOIN applied_events a ON a.sequence=t.source_sequence '
        'WHERE p.account_id=? AND r.reference=? AND r.counterparty_reference=? ORDER BY t.source_sequence,p.posting_index LIMIT 121',
        (receipt.funding_account,receipt.payment.reference.value,change.payload.identity.account_reference.value)).fetchall()
    if len(rows)>120:
        raise ContractError('known allocation counterpart resource limit')
    matches=[]
    for event_id,dated,amount,description,doc,page in rows:
        if type(amount) is not str or len(amount)>64:
            raise ContractError('known allocation cash scalar resource limit')
        value=Decimal(amount)
        if (value==receipt.payment.total.value.copy_negate() and page is not None
                and abs((date.fromisoformat(dated)-date.fromisoformat(receipt.payment.dated.value)).days)<=10):
            # Uniqueness rejects identical siblings; the only valid occurrence is zero.
            matches.append((movement_key(doc,receipt.funding_account,dated,value,description,0),event_id))
    if matches!=[(allocation.movement_key,receipt.cash_event_id)]:
        raise ContractError('known allocation cash match is not unique and exact')
    return allocation
