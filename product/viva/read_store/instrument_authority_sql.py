"""Account-scoped bounded SQL reads for immutable instrument authority."""
from dataclasses import dataclass
from time import monotonic
import json
from ..ledger.instruments import decode_change, fold_change, observation_event, current_observations, decode
from ..ingest.instrument_effects import InstrumentComponentState


class AuthorityReadError(ValueError):
    pass


def check_deadline(deadline):
    if monotonic() > deadline:
        raise AuthorityReadError('resource_limit')


def _query(revision, sql, parameters, limit, deadline):
    if getattr(revision,'_closed',False):
        raise AuthorityReadError('closed read revision')
    check_deadline(deadline)
    try:
        rows = revision.connection.execute(sql,(*parameters,limit+1)).fetchall()
    except Exception as error:
        if monotonic()>deadline:raise AuthorityReadError('resource_limit') from error
        raise AuthorityReadError('invalid bounded instrument SQL source') from error
    check_deadline(deadline)
    if len(rows) > limit:
        raise AuthorityReadError('resource_limit')
    return rows


def _json(encoded):
    if type(encoded) is not str or len(encoded.encode('utf-8')) > 262144:
        raise AuthorityReadError('resource_limit')
    try:
        return json.loads(encoded)
    except (ValueError,TypeError) as error:
        raise AuthorityReadError('invalid instrument SQL record') from error


@dataclass(frozen=True)
class AuthoritySourceSnapshot:
    observations: tuple
    component_states: tuple
    references: tuple
    known_allocations: tuple = ()


def account_currency(revision, account, deadline):
    rows = _query(revision,'SELECT CASE WHEN length(CAST(currency AS BLOB))=3 THEN currency END FROM accounts WHERE account_id=? AND currency IS NOT NULL LIMIT ?',
        (account,),120,deadline)
    values = {row[0] for row in rows}
    if len(values) != 1:
        raise AuthorityReadError('unavailable canonical account currency')
    return next(iter(values))


def source_snapshot(revision, request, deadline):
    """Select effective rows only after current-knowledge frontier resolution.

    The materializer validates every correction against its authenticated live
    predecessor. An indexed successor anti-join can therefore select the live
    frontier without transferring or replaying an account's lifetime history.
    """
    references = _query(revision,"SELECT CASE WHEN length(CAST(reference AS BLOB))<=256 THEN reference END,scope,CASE WHEN length(CAST(doc_id AS BLOB))<=256 THEN doc_id END,page "
        'FROM instrument_account_references WHERE account_id=? LIMIT ?',
        (request.account,),120,deadline)
    if any(type(row[0]) is not str for row in references):
        raise AuthorityReadError('resource_limit')
    refs = tuple(sorted({r[0] for r in references}))
    predicates = ['o.subject_id=?','substr(o.subject_id,1,?)=?']
    parameters = [request.account,len(request.account)+1,request.account+'|']
    if refs:
        placeholders = ','.join('?' for _ in refs)
        predicates += [f"json_extract(o.record_json,'$.payload.source_account_reference.value') IN ({placeholders})",
            f"json_extract(o.record_json,'$.payload.escrow.identity.account_reference.value') IN ({placeholders})",
            f"json_extract(o.record_json,'$.payload.escrow.continuity_reference.value') IN ({placeholders})"]
        parameters += list(refs)*3
    active = ('WITH active AS (SELECT o.* FROM instrument_observation_history o WHERE ('+' OR '.join(predicates)+") "
        "AND o.operation!='retract' AND NOT EXISTS (SELECT 1 FROM instrument_observation_history successor "
        "WHERE successor.prior_id=o.observation_id)) ")
    if request.view in {'terms','maturities'}:
        active=active.rstrip()+", numeric AS (SELECT a.observation_id FROM active a WHERE a.subject_id=? AND a.effective<=? "            "AND a.kind IN ('deposit_components','mortgage_components','refinance') AND (json_extract(a.record_json,'$.payload.terms') IS NOT NULL "            "OR json_extract(a.record_json,'$.payload.new_terms') IS NOT NULL) "            "AND a.effective=(SELECT MAX(b.effective) FROM active b WHERE b.subject_id=a.subject_id AND b.kind=a.kind AND b.effective<=? "            "AND (json_extract(b.record_json,'$.payload.terms') IS NOT NULL OR json_extract(b.record_json,'$.payload.new_terms') IS NOT NULL))) "
        parameters += [request.account,request.as_of,request.as_of]
        condition="(observation_id IN (SELECT observation_id FROM numeric) OR (kind='apr_context_v1' AND json_extract(record_json,'$.payload.numeric_terms_observation_id') IN (SELECT observation_id FROM numeric)) OR (kind='availability' AND effective<=?) OR (kind='deposit_components' AND effective<=? AND json_extract(record_json,'$.payload.subtype')='maturity') OR (kind IN ('deposit_components','mortgage_components') AND effective=(SELECT MAX(effective) FROM active x WHERE x.kind=active.kind AND x.effective<=?)))"
        parameters += [request.as_of]*3
    elif request.view=='allocation':
        condition="kind='position_classification' AND effective=(SELECT MAX(dated) FROM (SELECT occurred_at dated FROM positions WHERE account_id=? AND occurred_at<=? UNION ALL SELECT occurred_at FROM balance_observations WHERE account_id=? AND occurred_at<=? AND event_type='ClosingBalanceObserved'))"
        parameters += [request.account,request.as_of,request.account,request.as_of]
    elif request.view=='refinances':
        condition="kind='refinance' AND effective>=? AND effective<=?"
        parameters += [request.start,request.end]
    else:
        kinds="('mortgage_components','tax_receipt')" if request.view=='tax_payments' else "('deposit_components','mortgage_components')"
        condition=f"kind IN {kinds} AND ((json_extract(record_json,'$.payload.end.value')>=? AND json_extract(record_json,'$.payload.start.value')<=?) OR (kind='tax_receipt' AND effective>=? AND effective<=?))"
        parameters += [request.start,request.end,request.start,request.end]
    rows=_query(revision,active+"SELECT CASE WHEN length(CAST(event_id AS BLOB))<=256 THEN event_id END,CASE WHEN length(CAST(record_json AS BLOB))<=262144 THEN record_json END "
        'FROM active WHERE '+condition+' ORDER BY source_sequence LIMIT ?',parameters,120,deadline)
    observations=[]
    for event_id,encoded in rows:
        if type(event_id) is not str or not event_id:raise AuthorityReadError('resource_limit')
        check_deadline(deadline)
        change=decode_change(_json(encoded))
        observations.append({'change':change,'event_id':event_id,'superseded':False})
    identifiers=tuple(row['change'].observation_id for row in observations)
    states=()
    if identifiers:
        placeholders=','.join('?' for _ in identifiers)
        rows=_query(revision,"SELECT CASE WHEN length(CAST(s.state_json AS BLOB))<=262144 THEN s.state_json END "
            f'FROM instrument_component_states s WHERE s.observation_id IN ({placeholders}) '
            'AND s.source_sequence=(SELECT MAX(newer.source_sequence) FROM instrument_component_states newer '
            'WHERE newer.observation_id=s.observation_id) LIMIT ?',identifiers,120,deadline)
        states=tuple(decode(_json(encoded),InstrumentComponentState) for (encoded,) in rows)
        changes={row['change'].observation_id:row['change'] for row in observations}
        for state in states:
            change=changes.get(state.observation_id)
            if (change is None or state.doc_id!=change.source.doc_id or state.effective.value!=change.effective.value
                    or len({part.component for part in state.components})!=len(state.components)):
                raise AuthorityReadError('invalid bounded component source binding')
    allocations=()
    if request.view=='period_components':
        rows=_query(revision,"SELECT CASE WHEN length(CAST(allocation_json AS BLOB))<=262144 THEN allocation_json END "
            "FROM instrument_allocations WHERE json_extract(allocation_json,'$.receipt.loan_account')=? AND effective>=? AND effective<=? ORDER BY source_sequence LIMIT ?",
            (request.account,request.start,request.end),120,deadline)
        from ..ingest.mortgage_known_allocation import decode_allocation, KnownPaymentAllocation
        decoded=tuple(decode_allocation(_json(encoded)) for (encoded,) in rows)
        from .instrument_sql import validate_known_sql
        accepted=[]
        for value in decoded:
            try:
                accepted.append(validate_known_sql(revision.connection,value))
            except ValueError:
                continue
        allocations=tuple(accepted)
        if any(type(value) is not KnownPaymentAllocation for value in allocations):
            raise AuthorityReadError('invalid known allocation variant')
    return AuthoritySourceSnapshot(tuple(observations),states,tuple(references),allocations)


def allocation_snapshot(revision, request, deadline):
    """Select complete equal snapshots and retain every independent witness."""
    kinds=_query(revision,'SELECT DISTINCT kind FROM accounts WHERE account_id=? AND kind IS NOT NULL LIMIT ?',
        (request.account,),2,deadline)
    if kinds!=[('investment',)]:raise AuthorityReadError('unavailable investment snapshot scope')
    dates=_query(revision,"SELECT MAX(dated) FROM (SELECT occurred_at dated FROM positions WHERE account_id=? AND occurred_at<=? "
        "UNION ALL SELECT occurred_at FROM balance_observations WHERE account_id=? AND occurred_at<=? AND event_type='ClosingBalanceObserved') LIMIT ?",
        (request.account,request.as_of,request.account,request.as_of),1,deadline)
    dated=dates[0][0] if dates else None
    if not dated:raise AuthorityReadError('unavailable allocation snapshot')
    rows=_query(revision,'SELECT source_sequence,CASE WHEN length(CAST(instrument_id AS BLOB))<=256 THEN instrument_id END,CASE WHEN length(CAST(value_text AS BLOB))<=64 THEN value_text END,CASE WHEN length(CAST(currency AS BLOB))=3 THEN currency END,CASE WHEN length(CAST(grade AS BLOB))<=16 THEN grade END,CASE WHEN length(CAST(provenance_doc_id AS BLOB))<=256 THEN provenance_doc_id END,provenance_page '
        'FROM positions WHERE account_id=? AND occurred_at=? ORDER BY source_sequence LIMIT ?',
        (request.account,dated),1000,deadline)
    cash=_query(revision,"SELECT source_sequence,CASE WHEN length(CAST(amount_text AS BLOB))<=64 THEN amount_text END,CASE WHEN length(CAST(confirmed_by AS BLOB))<=16 THEN confirmed_by END,CASE WHEN length(CAST(provenance_doc_id AS BLOB))<=256 THEN provenance_doc_id END,provenance_page FROM balance_observations "
        "WHERE account_id=? AND occurred_at=? AND event_type='ClosingBalanceObserved' ORDER BY source_sequence LIMIT ?",
        (request.account,dated),120,deadline)
    if not cash:raise AuthorityReadError('unavailable coherent snapshot cash')
    by_doc={record[3]:[] for record in cash}
    for row in rows:
        if row[5] not in by_doc or row[3]!=request.currency:raise AuthorityReadError('conflicted snapshot currency or cash witness')
        by_doc[row[5]].append(row)
    if len(rows)+len(cash)>1000:raise AuthorityReadError('resource_limit')
    fingerprints=[]
    from .instrument_math import decimal_fraction
    for doc,positions in by_doc.items():
        if len(positions)>20:raise AuthorityReadError('resource_limit')
        if len({row[1] for row in positions})!=len(positions):raise AuthorityReadError('conflicted repeated position identity')
        cash_rows=[r for r in cash if r[3]==doc]
        if len(cash_rows)!=1:raise AuthorityReadError('conflicted duplicate snapshot cash')
        fingerprints.append((tuple(sorted((row[1],decimal_fraction(row[2])) for row in positions)),decimal_fraction(cash_rows[0][1])))
    if len(set(fingerprints))!=1:raise AuthorityReadError('conflicted complete allocation witnesses')
    selected_doc=sorted(by_doc)[0]
    selected_cash=next(row for row in cash if row[3]==selected_doc)
    return dated,tuple(by_doc[selected_doc]),selected_cash,tuple(rows),tuple(cash)


def resolve_account_reference(revision,reference,currency,deadline):
    rows=_query(revision,'SELECT DISTINCT r.account_id FROM instrument_account_references r '
        'JOIN accounts a ON a.account_id=r.account_id WHERE r.reference=? AND a.currency=? LIMIT ?',
        (reference,currency),20,deadline)
    if len(rows)!=1:raise AuthorityReadError('unavailable canonical account relationship')
    return rows[0][0]


def receiving_relationship(revision,request,movement,deadline):
    rows=_query(revision,"SELECT other.account_id,other.provenance_doc_id,other.provenance_page,own.movement_key,other.movement_key "
        "FROM movements own JOIN transfer_links link ON (link.movement_a=own.movement_key OR link.movement_b=own.movement_key) "
        "JOIN movements other ON other.movement_key=CASE WHEN link.movement_a=own.movement_key THEN link.movement_b ELSE link.movement_a END "
        "WHERE own.account_id=? AND own.occurred_at=? AND own.description=? AND own.currency=? AND other.currency=? "
        "AND link.grade IN ('verified','corroborated') AND other.grade IN ('verified','corroborated') LIMIT ?",
        (request.account,movement.dated.value,movement.reference.value,request.currency,request.currency),20,deadline)
    if len(rows)!=1:raise AuthorityReadError('unavailable accepted receiving-account relationship')
    return rows[0]


def witnessed_loan_zero(revision,account,dated,deadline):
    rows=_query(revision,"SELECT b.amount_text,b.provenance_doc_id,b.provenance_page,e.observation_id,b.confirmed_by "
        "FROM balance_observations b JOIN instrument_effects e ON e.source_sequence=b.source_sequence "
        "WHERE b.account_id=? AND b.occurred_at=? AND b.event_type='ClosingBalanceObserved' LIMIT ?",
        (account,dated),120,deadline)
    from .instrument_math import decimal_fraction
    selected=[]
    for amount,doc,page,observation,confirmed in rows:
        if decimal_fraction(amount)[0]:continue
        states=_query(revision,"SELECT CASE WHEN length(CAST(state_json AS BLOB))<=262144 THEN state_json END "
            "FROM instrument_component_states WHERE observation_id=? AND source_sequence=(SELECT MAX(source_sequence) FROM instrument_component_states WHERE observation_id=?) LIMIT ?",
            (observation,observation),1,deadline)
        if states:
            state=decode(_json(states[0][0]),InstrumentComponentState)
            if any(part.component=='principal_balance' and part.disposition.value=='accepted' for part in state.components):
                selected.append((doc,page,observation,'verified' if confirmed=='human' else 'corroborated'))
    return tuple(selected)


def restriction_status(revision,request,observations,deadline):
    rows=_query(revision,'SELECT DISTINCT family FROM instrument_family_history WHERE account_id=? AND effective<=? LIMIT ?',
        (request.account,request.as_of),120,deadline)
    families={row[0] for row in rows}
    if not families<={'term_deposit','escrow'}:raise AuthorityReadError('invalid closed instrument family')
    families.update(row.payload.family.value for row in observations if row.payload.family.value!='ordinary')
    if len(families)>1 or len(observations)>1:return 'conflicted'
    if families and not observations:return 'unavailable'
    return 'accepted'
