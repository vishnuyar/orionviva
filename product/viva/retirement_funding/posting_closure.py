"""Complete current interpretation of each selected rollover cash event."""
from decimal import Decimal, localcontext
from viva.investment.contracts import EvidenceError, ResourceLimit, digest, encode
from viva.investment.events import ROW, prefix
from viva.ledger.projection import LedgerProjection
from viva.ledger.projection.movements import _enumerated
from viva.ledger.accounting import financial_statements

# These are the causal selectors used by the ledger's interpretation contracts.
_MOVEMENT_FIELDS = ('movement', 'movement_key', 'matched_movement_key', 'anchor', 'subject', 'movement_a', 'movement_b','a','b')
_EVENT_FIELDS = ('transaction_id', 'cash_event_id', 'source_event_id', 'event_id')


def materialize_closures(events):
    candidates = set()
    for event in events:
        if event.event_type == ROW:
            row = event.body.get('row', {})
            witness = row.get('funding_witness') or {}
            if row.get('funding_role') == 'retirement_rollover' and witness:
                candidates.update((row['cash_event_id'], witness['transaction_id']))
    if not candidates:
        return {}
    from copy import deepcopy
    projection = LedgerProjection(deepcopy(events))
    by_id = {event.event_id: event for event in events}
    enumerated = tuple(_enumerated(projection.core))
    movements = {movement.key: movement for movement in projection.movements()}
    report = financial_statements(projection)
    postings = projection.accounting_postings() if hasattr(projection,'accounting_postings') else [(account,line) for account in projection.accounts() for line in projection.transactions(account)]
    frontier = encode(prefix(events))
    output = {}
    for identifier in sorted(candidates):
        event = by_id.get(identifier)
        if event is None or event.event_type != 'TransactionRecorded':
            continue
        keys = {key for key, account, state, line in enumerated if line.transaction_id == identifier}
        if not keys:
            continue
        # Only the projection's currently active, authenticated transfer links
        # extend the selected paired-cash effect closure. Revoked links cannot
        # keep unrelated bank activity inside the relationship's source scope.
        expanded=True
        while expanded:
            expanded=False
            for link in projection.transfer_links():
                pair={link['a'],link['b']}
                if pair & keys and not pair<=keys:
                    if any(key not in movements for key in pair):raise EvidenceError('linked effect movement unavailable')
                    keys.update(pair);expanded=True
            if len(keys)>1000:raise ResourceLimit('retirement paired effect bound')
        effect_ids={line.transaction_id for key,account,state,line in enumerated if key in keys}
        if not effect_ids or any(cash not in by_id or by_id[cash].event_type!='TransactionRecorded' for cash in effect_ids):raise EvidenceError('linked effect cash unavailable')
        merchants = {key for movement_key in keys for key in projection.merchant_keys_of(movements[movement_key])}
        dependencies = {cash:by_id[cash] for cash in effect_ids}
        correction_ids = set(); rule_ids = set()
        for dependency in events:
            body = dependency.body
            selected = (any(body.get(key) in keys for key in _MOVEMENT_FIELDS if type(body.get(key)) is str)
                        or any(body.get(key) in effect_ids for key in _EVENT_FIELDS if type(body.get(key)) is str)
                        or any(key in keys for key in body.get('movements', []) if type(key) is str)
                        or (dependency.event_type in ('RulingRecorded', 'MerchantCategorized', 'MerchantEnriched') and (body.get('subject') in merchants or body.get('merchant') in merchants)))
            if selected:
                dependencies[dependency.event_id] = dependency
                if body.get('correction_id'):
                    correction_ids.add(body['correction_id'])
                if body.get('rule_id'):
                    rule_ids.add(body['rule_id'])
        for dependency in events:
            if dependency.body.get('correction_id') in correction_ids or dependency.body.get('rule_id') in rule_ids:
                dependencies[dependency.event_id] = dependency
        current_postings = []
        complete = True
        with localcontext() as context:
            context.prec = 128
            for posting_ordinal,(account, line) in enumerate(postings):
                if line.transaction_id not in effect_ids:
                    continue
                info = projection.account_info(account)
                role = info.kind
                # Universal bookkeeping paths have their established meanings;
                # a depository subtype is never inferred from its display name.
                if account.startswith('Income:') and role not in ('investment','depository','liability'):
                    role = 'income_unattributed' if account == 'Income:Uncategorized' else 'income'
                elif account.startswith('Transfers:') and role not in ('investment','depository','liability'):
                    role = 'transfer'
                elif account.startswith('Expenses:') and role not in ('investment','depository','liability'):
                    role = 'expense'
                elif role not in ('investment', 'depository', 'liability'):
                    complete = False
                # Ordinary current accounting below owns whether a raw default
                # income counter-leg remains provisional after an accepted link.
                if role in ('investment','depository','liability'):
                    identities=[source for source in events if source.event_type=='AccountOpened' and source.body.get('account_id')==account]
                    if not identities or identities[-1].body.get('kind')!=role:complete=False
                    for identity in identities:dependencies[identity.event_id]=identity
                current_postings.append({'effect_id':digest(('posting',posting_ordinal,line.transaction_id,account,str(line.amount))),'account': account, 'role': role, 'amount': str(line.amount), 'grade': line.grade,
                                         'transaction_id': line.transaction_id, 'source': line.provenance.to_dict()})
            if not current_postings or sum((Decimal(p['amount']) for p in event.body.get('postings', [])), Decimal(0)) != 0:
                complete = False
        related_income = [{**row,'effect_id':digest(('ordinary_income',ordinal,row))} for ordinal,row in enumerate(report['profit_loss']['lines']) if row.get('movement_key') in keys and row.get('root') == 'income']
        unresolved = [row for row in report['profit_loss'].get('unresolved_components', []) if row.get('movement_key') in keys]
        if unresolved or any(row.get('provisional') or row.get('currency') in ('', '?') for row in related_income):
            complete = False
        # Source-specific instrument allocations need their own authenticated
        # component closure; ordinary transfer cash does not acquire that proof.
        if any(key in projection.instrument_allocations() for key in keys):
            complete = False
        if len(dependencies) + len(current_postings) + len(related_income) > 1000:
            complete = False
        output[identifier] = {'schema': 'retirement-posting-closure-v1', 'frontier': frontier,
                              'cash_event_id': identifier, 'cash_digest': digest(event.body),
                              'movement_keys': sorted(keys), 'effect_cash_ids':sorted(effect_ids),'complete': complete,
                              'postings': current_postings, 'income': related_income,
                              'dependencies': [{'id': item.event_id, 'type': item.event_type, 'digest': digest(item.body), 'body': item.body, 'source': item.provenance.to_dict()} for item in dependencies.values()]}
    return output


def totals(closures, expected):
    """Compute source-scoped effects; an unknown bank subtype is unavailable."""
    if set(closures) != set(expected):
        raise EvidenceError('paired posting closure is incomplete')
    frontiers = {digest(value['frontier']) for value in closures.values()}
    if len(frontiers) != 1:
        raise EvidenceError('paired posting frontiers differ')
    income = Decimal(0); checking = Decimal(0);seen_postings=set();seen_income=set()
    with localcontext() as context:
        context.prec = 128
        for identifier, closure in closures.items():
            if not closure.get('complete') or closure.get('cash_event_id') != identifier or closure.get('cash_digest') != expected[identifier]:
                raise EvidenceError('paired posting closure dependency unavailable')
            for posting in closure['postings']:
                effect=posting['effect_id']
                if effect in seen_postings:continue
                seen_postings.add(effect)
                if posting['role'] == 'depository':
                    checking=None
                if posting['role'] == 'checking' and checking is not None and Decimal(posting['amount']) > 0:
                    checking += Decimal(posting['amount'])
            # The ordinary accounting report owns correction/ruling meaning.
            for row in closure['income']:
                if row['effect_id'] in seen_income:continue
                seen_income.add(row['effect_id']);income+=Decimal(row['amount'])
    return checking, income
