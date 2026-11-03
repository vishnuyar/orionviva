"""Native dated investment populations and indexed cash-history settlement."""
from collections import Counter, deque
from dataclasses import replace
from datetime import date
from decimal import Decimal, Inexact, localcontext, MAX_EMAX, MIN_EMIN
import hashlib
import json
import secrets

from ..ingest.brokerage import BrokerageFacts, PositionFact, BrokerageActivity, is_cash_row
from ..ingest.registry import BROKERAGE_IDENTITY, profile_for
from ..investment.extraction import InvestmentSource, HEADERS, POSITION, ROW
from ..ledger.identity import (usable_full_number, conflicting_number_signals, canonical_institution,
                               preferred_account_key, normalize_name, SourceAccountIdentity)
from ..ledger.postings import BROKERAGE_ACTIVITY_KINDS, brokerage_activity_transaction
from .investment_numbers import key, display, scalar, zero_sum, negate, exact_sum, posting_precision
from .store import canonical, AuthorityError, IntegrityError
from .schema import TABLES, KEYS

CAUSE_TABLES = {'interpretations','accounts','account_keys','holder_index','reference_claims','reference_views','identity_decisions'}


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def capture_types(facts):
    positions = type(facts.positions) is list and all(type(p) is PositionFact for p in facts.positions)
    activity = type(facts.activity) is list and all(type(a) is BrokerageActivity for a in facts.activity)
    decimals = (positions and activity and type(facts.cash) is Decimal and type(facts.total) is Decimal
        and (facts.opening_cash is None or type(facts.opening_cash) is Decimal)
        and all(type(p.units) is Decimal and type(p.market_value) is Decimal and (p.cost_basis is None or type(p.cost_basis) is Decimal) for p in facts.positions)
        and all(type(a.amount) is Decimal and (a.realized_gain is None or type(a.realized_gain) is Decimal) for a in facts.activity))
    return {'investment': type(facts) is BrokerageFacts and (facts.investment_source is None or type(facts.investment_source) is InvestmentSource),
            'positions': positions, 'activity': activity, 'decimals': decimals}


def _text(value):
    return type(value) is str and len(value.encode()) <= 16384 and not any(ord(c)<32 or ord(c)==127 for c in value)


def _date(value):
    return type(value) is str and date.fromisoformat(value).isoformat() == value


def decode(value, tags=None):
    """Close the custom wire before constructing legacy-compatible typed facts."""
    required = {'doc_id','doc_type','doc_type_confidence','account_ref','currency','as_of','cash','total','positions',
                'account_number','institution','account_names','opening_cash','activity','investment_source'}
    if type(value) is not dict or set(value)-required-{'acquisition','validated_source_page_count'} or not required <= set(value):
        raise ValueError('closed investment facts required')
    if tags is not None and (type(tags) is not dict or set(tags) != {'investment','positions','activity','decimals','read_context_id'} or any(tags[k] is not True for k in ('investment','positions','activity','decimals'))):
        raise ValueError('exact investment capture types required')
    for name in required - {'doc_type_confidence','positions','account_names','activity','investment_source','cash','total','opening_cash'}:
        if not _text(value[name]):
            raise ValueError('investment wire scalar differs')
    if len(value['doc_id']) != 64 or any(c not in '0123456789abcdef' for c in value['doc_id']):
        raise ValueError('investment source address differs')
    profile = profile_for(value['doc_type'])
    if profile is None or profile.identity != BROKERAGE_IDENTITY or profile.account_kind != 'investment':
        raise ValueError('investment registered profile differs')
    confidence = value['doc_type_confidence']
    if confidence is not None and (type(confidence) not in {int,float} or not 0 <= confidence <= 1):
        raise ValueError('investment classification confidence differs')
    if not _date(value['as_of']) or len(value['currency']) != 3 or not value['currency'].isascii() or not value['currency'].isalpha() or not value['currency'].isupper():
        raise ValueError('investment date or currency differs')
    if any(len(value[n].encode())>4096 for n in ('doc_type','account_ref','account_number','institution')):
        raise ValueError('shared account metadata bound differs')
    if type(value['account_names']) is not list or len(value['account_names'])>100 or any(not _text(n) or len(n.encode())>4096 for n in value['account_names']):
        raise ValueError('investment holder shapes differ')
    if type(value['positions']) is not list or type(value['activity']) is not list:
        raise ValueError('investment complete population shape differs')
    if type(value['opening_cash']) is not str:
        raise ValueError('typed optional investment opening required')
    money = [value['cash'],value['total']] + ([] if value['opening_cash']=='' else [value['opening_cash']])
    pages = []
    for position in value['positions']:
        if type(position) is not dict or set(position) != {'instrument','units','market_value','cost_basis','page','classification'}:
            raise ValueError('closed investment position required')
        if not _text(position['instrument']) or any(type(position[n]) is not str for n in ('units','market_value','cost_basis')):
            raise ValueError('investment position scalars differ')
        money += [position['units'],position['market_value']] + ([] if position['cost_basis']=='' else [position['cost_basis']])
        pages.append(position['page'])
    for activity in value['activity']:
        if type(activity) is not dict or set(activity) != {'date','kind','amount','description','instrument','realized_gain'}:
            raise ValueError('closed investment activity required')
        if any(not _text(activity[n]) for n in ('date','kind','description','instrument')) or any(type(activity[n]) is not str for n in ('amount','realized_gain')) or activity['kind'] not in BROKERAGE_ACTIVITY_KINDS or (activity['date'] and not _date(activity['date'])):
            raise ValueError('investment activity scalars differ')
        money += [activity['amount']] + ([] if activity['realized_gain']=='' else [activity['realized_gain']])
        if Decimal(activity['amount']) <= 0:
            raise ValueError('investment activity magnitude differs')
    for amount in money:
        if type(amount) is not str or not amount.isascii() or amount!=amount.strip() or len(amount.encode())>8*1024*1024 or not Decimal(amount).is_finite():
            raise ValueError('investment finite Decimal required')
    extent = value.get('validated_source_page_count')
    if extent is not None and (type(extent) is not int or not 1 <= extent <= 200):
        raise ValueError('investment source extent differs')
    facts = BrokerageFacts.from_dict(value)
    if facts.investment_source is not None:
        source = facts.investment_source
        pages += [field.page for record in (source.headers, *source.positions, *source.rows) for _,field in record if field is not None]
        if len(source.positions) != len(facts.positions) or len(source.rows) != len(facts.activity):
            raise ValueError('investment source occurrence population differs')
    if any(p is not None and (type(p) is not int or not 1 <= p <= (extent or 200)) for p in pages):
        raise ValueError('investment source page differs')
    if canonical(facts.to_dict()) != canonical(value):
        raise ValueError('investment custom wire roundtrip differs')
    return facts


def wire_equal(left, right):
    """Compare numeric meaning while retaining exact custom source extensions."""
    def normalized(facts):
        body=facts.to_dict()
        for name in ('doc_type_confidence','acquisition','validated_source_page_count'):
            body.pop(name,None)
        for name in ('cash','total','opening_cash'):
            if body[name]!='':
                body[name]=key(Decimal(body[name]))
        for position in body['positions']:
            for name in ('units','market_value','cost_basis'):
                if position[name]!='':
                    position[name]=key(Decimal(position[name]))
        for activity in body['activity']:
            for name in ('amount','realized_gain'):
                if activity[name]!='':
                    activity[name]=key(Decimal(activity[name]))
        return body
    return canonical(normalized(left))==canonical(normalized(right))


def headers(facts):
    return dict(facts.investment_source.headers) if facts.investment_source else {}


def field_value(field, kind='text', locale='en-US', currency=''):
    """Available source values retain independent page and bounded-view status."""
    if field is None or field.page is None or not field.raw.strip():
        return ['unavailable',None]
    raw = field.raw.strip()
    try:
        if kind == 'number':
            from vivacore.verify.normalize import parse_amount
            from ..investment.contracts import decimal
            parsed = parse_amount(raw, locale, currency)
            if not parsed.ok:
                return ['unavailable',None]
            return ['accepted',display(decimal(str(parsed.decimal()), signed=True))]
        if kind == 'date':
            from vivacore.verify.normalize import parse_date
            parsed = parse_date(raw, locale)
            return ['accepted',parsed.value] if parsed.ok else ['unavailable',None]
        if kind == 'flag':
            return ['accepted',raw.lower()] if raw.lower() in {'true','false','yes','no'} else ['unavailable',None]
        return ['accepted',field.raw]
    except (ValueError,TypeError):
        return ['unavailable',None]


def source_claim(facts):
    field = headers(facts).get('account_reference')
    return SourceAccountIdentity(field.raw if field is not None else '',facts.doc_id,
        field.page if field else None,facts.validated_source_page_count)


def source_start(facts, locale='en-US'):
    field = field_value(headers(facts).get('period_start'),'date',locale,facts.currency)
    return field[1] if field[0]=='accepted' else None


def source_digest(facts):
    return digest(facts.investment_source.to_dict()['headers'] if facts.investment_source else None)


def row_signature(facts, ordinal, account_id):
    line = facts.activity[ordinal]
    record = dict(facts.investment_source.rows[ordinal]) if facts.investment_source else {}
    def tag(name):
        field = record.get(name)
        if name == 'funding_role' and field is not None and hasattr(field,'role'):
            return ['accepted',field.role] if field.page is not None else ['unavailable',None]
        return field_value(field)
    printed = tag('printed_row_reference')
    return {'date':line.date or facts.as_of,'kind':line.kind,'amount':key(line.amount),
        'instrument':['accepted',line.instrument] if line.instrument else ['unavailable',None],
        'signedgain':['accepted',key(line.realized_gain)] if line.realized_gain is not None else ['unavailable',None],
        'funding_role':'unknown','reported_role_source':tag('funding_role'),
        'funding_reference':tag('printed_reference'),'counterpart_reference':tag('counterpart_reference'),
        'printed_row_reference':printed,'namespace':['accepted',account_id] if printed[0]=='accepted' else ['unavailable',None]}


def normalize_snapshot(facts):
    """Use exact two-reading sweep reconciliation, retaining signed holdings."""
    sweep = [p for p in facts.positions if is_cash_row(p.instrument)]
    positions = [p for p in facts.positions if not is_cash_row(p.instrument)]
    if not sweep:
        return facts
    included = zero_sum([p.market_value for p in positions]+[facts.cash,negate(facts.total)])
    separate = zero_sum([p.market_value for p in positions+sweep]+[facts.cash,negate(facts.total)])
    if not included and not separate:
        return facts
    cash = facts.cash if included and not separate else exact_sum([facts.cash]+[p.market_value for p in sweep])
    return replace(facts,cash=cash,positions=positions)


def source_fields(facts, locale='en-US'):
    """Intrinsic field status remains separate from complete PDF-token proof."""
    source = facts.investment_source
    records = [('header',-1,dict(source.headers) if source else {},HEADERS)]
    records += [('position',i,dict(source.positions[i]) if source else {},POSITION) for i in range(len(facts.positions))]
    records += [('activity',i,dict(source.rows[i]) if source else {},ROW) for i in range(len(facts.activity))]
    for scope, ordinal, record, names in records:
        for name in names:
            field = record.get(name)
            kind = ('number' if name in {'units','market_value','cost_basis','opening_cash','closing_cash','amount','reported_realized_gain'}
                    else 'date' if name in {'date','as_of','period_start','period_end'} else 'text')
            state,value = field_value(field,kind,locale,facts.currency)
            reason = 'missing_source' if field is None else 'invalid_page' if field.page is None else 'unreadable_source' if state != 'accepted' else ''
            if scope=='position' and name=='units' and state=='accepted':
                from ..investment.units import units
                try:
                    units(value,group_separator='')
                except ValueError:
                    state,value,reason='unavailable',None,'unsupported_field'
            if scope=='activity' and name=='amount' and state=='accepted':
                value = display(scalar(value).copy_abs())
            expected = None
            compare = False
            if scope=='header':
                known = {'currency':facts.currency,'as_of':facts.as_of,'period_end':facts.as_of,
                         'opening_cash':None if facts.opening_cash is None else display(facts.opening_cash),'closing_cash':display(facts.cash)}
                if name in known and (name!='opening_cash' or facts.opening_cash is not None):
                    compare,expected = True,known[name]
            elif scope=='position':
                position = facts.positions[ordinal]
                known = {'identifier':position.instrument,'units':display(position.units),'market_value':display(position.market_value),
                         'cost_basis':None if position.cost_basis is None else display(position.cost_basis)}
                if name in known:
                    compare,expected = True,known[name]
            else:
                activity = facts.activity[ordinal]
                known = {'date':activity.date or facts.as_of,'kind':activity.kind,'amount':display(activity.amount),
                         'security_identifier':activity.instrument,'reported_realized_gain':None if activity.realized_gain is None else display(activity.realized_gain)}
                if name in known:
                    compare,expected = True,known[name]
            if scope=='position' and name=='identifier' and state=='accepted':
                label=field_value(record.get('label'))
                if label==['accepted',facts.positions[ordinal].instrument]:
                    compare=False
            if state=='accepted' and compare and value != expected:
                state,value,reason = 'conflicted',None,'source_disagrees'
            yield dict(doc_id=facts.doc_id,scope=scope,ordinal=ordinal,name=name,
                raw=None if field is None else field.raw,page=None if field is None else field.page,
                value=value,status=state,grade='conflicted' if state=='conflicted' else 'unverified',reason=reason)


def root_capable(facts):
    """The existing first-seed printed opening/period rule, without a projector."""
    from vivacore.verify.normalize import parse_amount, parse_date
    h = headers(facts)
    extent = facts.validated_source_page_count
    if facts.opening_cash is None or not facts.activity or type(extent) is not int:
        return False
    names = ('period_start','period_end','as_of','currency','opening_cash')
    fields = [h.get(name) for name in names]
    if any(f is None or type(f.page) is not int or not 1 <= f.page <= extent or not f.raw.strip() for f in fields):
        return False
    start,end,as_of = [parse_date(h[name].raw) for name in names[:3]]
    if not all(v.ok for v in (start,end,as_of)) or end.value != facts.as_of or as_of.value != facts.as_of or start.value > end.value or h['currency'].raw.strip() != facts.currency:
        return False
    amount = parse_amount(h['opening_cash'].raw,currency=facts.currency)
    if not amount.ok or amount.decimal() != facts.opening_cash:
        return False
    return all(_date(a.date or facts.as_of) and start.value <= (a.date or facts.as_of) <= end.value for a in facts.activity)


def explicit_empty(facts):
    field = field_value(headers(facts).get('no_activity'))
    return 'true' if field[0]=='accepted' and field[1].lower() in {'true','yes'} else 'false' if field[0]=='accepted' else 'unavailable'


def source_consistency(facts, locale='en-US'):
    fields = list(source_fields(facts,locale))
    snapshot = not any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'}) for f in fields)
    activity = not any(f['status']=='conflicted' and f['scope']=='activity' and f['name'] in {'date','kind','amount','reported_realized_gain','security_identifier'} for f in fields)
    return snapshot,activity


def _locale(store,doc):
    receipt=store._row('receipts','doc_id=?',(doc,))
    return json.loads(receipt['body'])['source_locale'] or 'en-US'


def rows(store, table, where='1', parameters=(), order=None):
    columns = TABLES[table]
    result = store._read('SELECT '+','.join(columns)+' FROM '+table+' WHERE '+where+' ORDER BY '+(order or ','.join(KEYS[table])),parameters)
    return [dict(zip(columns,row)) for row in result]


def signals(facts):
    result = {('preferred',preferred_account_key(facts.institution,facts.account_number,facts.account_ref))}
    result.update(('holder',normalize_name(name)) for name in facts.account_names if normalize_name(name))
    claim = source_claim(facts)
    if claim.eligible():
        result.add(('reference',claim.reference))
    number = usable_full_number(facts.account_number)
    if number:
        result.add(('number',canonical(['investment',number])))
    return sorted((kind,value) for kind,value in result if value)


def intake(store, interpretation):
    facts = decode(json.loads(interpretation['facts']))
    existing=store._row('investment_facts','doc_id=?',(facts.doc_id,))
    if existing is not None:
        if existing['body']!=canonical(facts.to_dict()):
            raise IntegrityError('immutable investment capture differs')
        return
    if not any(op['table']=='interpretations' and op['row']['doc_id']==facts.doc_id and op['row']['facts_type']=='investment' for op in store._operations):
        raise IntegrityError('investment facts require their actual first interpretation transaction')
    receipt = store._row('receipts','doc_id=?',(facts.doc_id,))
    tags = json.loads(receipt['capture_types'])
    store._put('investment_facts',dict(doc_id=facts.doc_id,currency=facts.currency,as_of=facts.as_of,
        body=canonical(facts.to_dict()),context_id=tags['read_context_id'],
        source_kind='curated' if receipt['facts_type']=='curated' else 'typed',created_revision=store._revision))
    locale=json.loads(receipt['body'])['source_locale'] or 'en-US'
    for field in source_fields(facts,locale):
        store._put('investment_fields',field)
    for kind,value in signals(facts):
        store._put('investment_dependencies',dict(doc_id=facts.doc_id,signal_kind=kind,signal=value,
            currency=facts.currency,account_id=None,active=1))
    store._item(facts.doc_id,'pending','identity_requires_review')


def _component(store, facts, **changes):
    prior = store._row('investment_components','doc_id=?',(facts.doc_id,))
    row = prior or dict(doc_id=facts.doc_id,account_id=None,snapshot_state='held',activity_state='held',
        source_state='unavailable',reason='identity_requires_review',snapshot_id=None,group_id=None,basis_id=None,revision=store._revision)
    result = {**row,**changes}
    if any(result[name] != row[name] for name in result if name!='revision') or prior is None:
        store._put('investment_components',{**result,'revision':store._revision})
    return result


def _bind(store, facts):
    from .bank import _identity
    from .identity import map_account, maintain_claim, resolve_source, record_decision
    component = store._row('investment_components','doc_id=?',(facts.doc_id,))
    if component is not None and component['account_id']:
        return store._row('accounts','account_id=?',(component['account_id'],))
    identity = _identity(facts,'investment')
    decision = None
    if identity:
        candidates = rows(store,'accounts','kind=? AND normalized_number=?',('investment',usable_full_number(facts.account_number)))
        if any(a['identity'] != identity for a in candidates):
            return None
        account = store._row('accounts','identity=?',(identity,))
    else:
        from ..ledger.identity import identity_number_key
        if not source_claim(facts).eligible() or identity_number_key(facts.account_number,facts.account_ref):
            return None
        known_operation=len(store._operations)
        decision = resolve_source(store,facts)
        if decision['resolution']['verdict']=='ambiguous':
            record_decision(store,facts,decision,'',known_operation=known_operation)
            return None
        physical = decision['logical_to_physical'].get(decision['resolution']['account_id'])
        account = store._row('accounts','account_id=?',(physical,)) if physical else None
        identity = account['identity'] if account else secrets.token_hex(32)
    if account is not None and (account['kind']!='investment' or account['currency']!=facts.currency):
        if decision is not None:
            record_decision(store,facts,decision,account['account_id'],known_operation=known_operation)
        return None
    if account is None:
        if any(op['table']=='accounts' and store._investment_prior_accounts.get(op['row']['account_id']) is None for op in store._operations):
            raise IntegrityError('a second physical account would violate the actual writer creation order')
        account = dict(account_id='acct:sql:'+secrets.token_hex(16),identity=identity,kind='investment',currency=facts.currency,
            number=facts.account_number,normalized_number=usable_full_number(facts.account_number),institution=facts.institution,
            label=facts.account_ref,names=canonical(facts.account_names),earliest_amount=display(facts.cash),earliest_date=facts.as_of,
            current_amount=display(facts.cash),current_date=facts.as_of)
        store._put('accounts',account)
        map_account(store,account,facts)
    if decision is not None:
        record_decision(store,facts,decision,account['account_id'],promoted=True,known_operation=known_operation)
    claim = source_claim(facts)
    if claim.eligible():
        maintain_claim(store,dict(claim_id=facts.doc_id+':account',account_id=account['account_id'],reference=claim.reference,
            doc_id=facts.doc_id,scope='account',page=claim.page,identity_page_count=claim.page_count,claim_order=store._revision))
    return account


def security_name(facts, instrument):
    if facts.investment_source is None:
        return instrument
    matches=[]
    for record in facts.investment_source.positions:
        values=dict(record)
        identifier=field_value(values.get('identifier'))
        label=field_value(values.get('label'))
        if identifier[0]=='accepted' and (identifier[1]==instrument or label==['accepted',instrument]):
            matches.append(identifier[1])
    return matches[0] if len(matches)==1 else instrument


def snapshot_signature(facts, account_id):
    return {'version':1,'logical_account':account_id,'currency':facts.currency,'as_of':facts.as_of,
        'cash':key(facts.cash),'total':key(facts.total),'positions':sorted(
            [[security_name(facts,p.instrument),key(p.market_value)] for p in facts.positions],key=canonical)}


def _source_state(facts, locale='en-US'):
    if facts.investment_source is None:
        return 'unavailable'
    fields = list(source_fields(facts,locale))
    if not all(source_consistency(facts,locale)):
        return 'conflicted'
    required = {'header':{'account_reference','currency','period_start','period_end','as_of','opening_cash','closing_cash'},
                'position':{'identifier','market_value'},'activity':{'date','kind','amount'}}
    return 'held' if any(f['status']!='accepted' and f['name'] in required[f['scope']] for f in fields) else 'accepted'


def _register(store, facts):
    component = store._row('investment_components','doc_id=?',(facts.doc_id,))
    if component is not None and component['snapshot_id']:
        return component
    locale=_locale(store,facts.doc_id)
    source_state = _source_state(facts,locale)
    try:
        normalized = normalize_snapshot(facts)
        amounts = [normalized.cash,normalized.total]+[v for p in normalized.positions for v in (p.units,p.market_value)]+[p.cost_basis for p in normalized.positions if p.cost_basis is not None]
        if any(len(display(v).encode())>16384 for v in amounts):
            reason = 'resource_limit'
        elif not zero_sum([p.market_value for p in normalized.positions]+[normalized.cash,negate(normalized.total)]):
            reason = 'snapshot_arithmetic'
        elif len({security_name(facts,p.instrument) for p in normalized.positions})!=len(normalized.positions) or any(not p.instrument.strip() for p in normalized.positions):
            reason = 'population_identity_requires_review'
        elif not source_consistency(facts,locale)[0]:
            reason = 'source_value_conflict'
        else:
            reason = ''
    except (ValueError,OverflowError):
        reason = 'resource_limit'
    if reason:
        store._item(facts.doc_id,'pending',reason)
        return _component(store,facts,snapshot_state='conflicted' if reason=='source_value_conflict' else 'held',source_state=source_state,reason=reason)
    account = _bind(store,facts)
    if account is None:
        return _component(store,facts,source_state=source_state,reason='identity_requires_review')
    account_id = account['account_id']
    snapshot_id = digest(['sql-investment-snapshot-v1',facts.doc_id])
    store._put('investment_snapshots',dict(snapshot_id=snapshot_id,doc_id=facts.doc_id,account_id=account_id,currency=facts.currency,
        as_of=facts.as_of,cash=display(normalized.cash),total=display(normalized.total),position_count=len(normalized.positions),
        signature=canonical(snapshot_signature(normalized,account_id)),created_revision=store._revision))
    for ordinal,position in enumerate(normalized.positions):
        original_ordinal = next(i for i,p in enumerate(facts.positions) if p.instrument==position.instrument)
        fields = [f for f in source_fields(facts,locale) if f['scope']=='position' and f['ordinal']==original_ordinal]
        state = 'conflicted' if any(f['status']=='conflicted' for f in fields) else 'accepted' if facts.investment_source else 'unavailable'
        store._put('investment_positions',dict(snapshot_id=snapshot_id,ordinal=ordinal,
            security_id=digest(['investment-security-v1',account_id,security_name(facts,position.instrument)]),instrument=position.instrument,
            units=display(position.units),market_value=display(position.market_value),cost_basis=None if position.cost_basis is None else display(position.cost_basis),
            page=position.page,source_state=state))
    store._put('investment_cash_inputs',dict(doc_id=facts.doc_id,period_start=source_start(facts,locale),period_end=facts.as_of,
        printed_opening=None if facts.opening_cash is None else display(facts.opening_cash),closing=display(normalized.cash),explicit_empty=explicit_empty(facts)))
    for ordinal,line in enumerate(facts.activity):
        occurrence = store._row('source_occurrences','doc_id=? AND line_index=?',(facts.doc_id,ordinal))
        field = dict(facts.investment_source.rows[ordinal]).get('amount') if facts.investment_source else None
        page = occurrence['page'] if occurrence else field.page if field else None
        fields = [f for f in source_fields(facts,locale) if f['scope']=='activity' and f['ordinal']==ordinal]
        state = 'conflicted' if any(f['status']=='conflicted' for f in fields) else 'accepted' if facts.investment_source else 'unavailable'
        store._put('investment_rows',dict(doc_id=facts.doc_id,ordinal=ordinal,date=line.date or facts.as_of,kind=line.kind,
            amount=display(line.amount),description=line.description,instrument=line.instrument,realized_gain=None if line.realized_gain is None else display(line.realized_gain),
            page=page,source_event_id=occurrence['event_id'] if occurrence else None,row_signature=canonical(row_signature(facts,ordinal,account_id)),source_state=state))
    for dependency in rows(store,'investment_dependencies','doc_id=?',(facts.doc_id,)):
        store._put('investment_dependencies',{**dependency,'account_id':account_id,'active':0})
    store._item(facts.doc_id,'accepted','',account_id)
    return _component(store,facts,account_id=account_id,snapshot_id=snapshot_id,snapshot_state='accepted',source_state=source_state,reason='')


def _root_seeds(store, account_id, currency):
    candidates = store._read("SELECT g.group_id,min(d.revision),min(d.ordinal) FROM investment_groups g JOIN investment_decisions d ON d.group_id=g.group_id JOIN investment_witnesses w ON w.group_id=g.group_id JOIN investment_bases b ON b.basis_id=w.basis_id WHERE g.account_id=? AND g.currency=? AND d.action='activate' AND b.seed_group IS NULL AND b.predecessor_snapshot IS NULL AND b.prior_basis IS NULL GROUP BY g.group_id ORDER BY min(d.revision),min(d.ordinal),g.group_id",(account_id,currency))
    roots = []
    for group_id,_,_ in candidates:
        witnesses = rows(store,'investment_bases','basis_id IN (SELECT basis_id FROM investment_witnesses WHERE group_id=?) AND seed_group IS NULL AND predecessor_snapshot IS NULL AND prior_basis IS NULL',(group_id,),order='created_revision,known_operation,basis_id')
        for basis in witnesses:
            facts = decode(json.loads(store._row('investment_facts','doc_id=?',(basis['doc_id'],))['body']))
            if not root_capable(facts):
                continue
            rivals = store._read('SELECT b.opening FROM investment_bases b JOIN investment_witnesses w ON w.basis_id=b.basis_id JOIN investment_groups g ON g.group_id=w.group_id WHERE g.account_id=? AND g.currency=? AND b.seed_group IS NULL AND b.period_start=?',(account_id,currency,basis['period_start']))
            if any(key(scalar(value)) != key(scalar(basis['opening'])) for (value,) in rivals):
                continue
            roots.append((group_id,basis))
            break
    return roots


def _basis_valid(store, basis, account_id, currency):
    fact_row = store._row('investment_facts','doc_id=?',(basis['doc_id'],))
    component = store._row('investment_components','doc_id=?',(basis['doc_id'],))
    if fact_row is None or component is None or component['account_id']!=account_id:
        return False
    facts = decode(json.loads(fact_row['body']))
    if fact_row['currency']!=currency or basis['source_header_digest']!=source_digest(facts):
        return False
    if basis['predecessor_snapshot']:
        predecessor = store._row('investment_snapshots','snapshot_id=?',(basis['predecessor_snapshot'],))
        if predecessor is None or predecessor['account_id']!=account_id or predecessor['currency']!=currency or key(scalar(predecessor['cash']))!=key(scalar(basis['opening'])):
            return False
        same = rows(store,'investment_snapshots','account_id=? AND as_of=?',(account_id,predecessor['as_of']))
        if len({s['cash'] for s in same})!=1:
            return False
    if basis['seed_group']:
        return basis['seed_group'] in {group for group,_ in _root_seeds(store,account_id,currency)}
    if not root_capable(facts):
        return False
    rivals = store._read('SELECT b.opening FROM investment_bases b JOIN investment_witnesses w ON w.basis_id=b.basis_id JOIN investment_groups g ON g.group_id=w.group_id WHERE g.account_id=? AND g.currency=? AND b.seed_group IS NULL AND b.period_start=?',(account_id,currency,basis['period_start']))
    return all(key(scalar(opening))==key(scalar(basis['opening'])) for (opening,) in rivals)


def _basis(store, facts, account_id):
    existing = rows(store,'investment_bases','doc_id=?',(facts.doc_id,),order='created_revision,known_operation,basis_id')
    valid = [b for b in existing if _basis_valid(store,b,account_id,facts.currency)]
    if valid:
        return valid[0],''
    roots = _root_seeds(store,account_id,facts.currency)
    seed = predecessor = prior = None
    opening = facts.opening_cash
    start = source_start(facts,_locale(store,facts.doc_id))
    opening_kind,start_kind = 'printed','printed' if start else 'unavailable'
    if root_capable(facts):
        if existing:
            return None,'basis_unavailable'
    else:
        if not roots:
            return None,'seed_unavailable'
        seed = roots[0][0]
        if existing:
            old = existing[0]
            predecessor_ok=True
            if old['predecessor_snapshot']:
                previous=store._row('investment_snapshots','snapshot_id=?',(old['predecessor_snapshot'],))
                predecessor_ok=(previous is not None and previous['account_id']==account_id and previous['currency']==facts.currency and previous['cash']==old['opening'])
                if predecessor_ok:
                    same=rows(store,'investment_snapshots','account_id=? AND as_of=?',(account_id,previous['as_of']))
                    predecessor_ok=len({s['cash'] for s in same})==1
            if old['seed_group'] and old['source_header_digest']==source_digest(facts) and predecessor_ok:
                opening,opening_kind,start,start_kind,predecessor,prior = scalar(old['opening']),old['opening_kind'],old['period_start'],old['start_kind'],old['predecessor_snapshot'],old['basis_id']
            else:
                return None,'basis_unavailable'
        elif opening is None:
            snapshots = rows(store,'investment_snapshots','account_id=? AND currency=? AND doc_id<>?',(account_id,facts.currency,facts.doc_id),order='as_of DESC,created_revision,doc_id')
            if not snapshots or snapshots[0]['as_of']>=facts.as_of:
                return None,'carry_unavailable'
            latest = [s for s in snapshots if s['as_of']==snapshots[0]['as_of']]
            if len({s['cash'] for s in latest})!=1:
                return None,'carry_unavailable'
            predecessor = latest[0]['snapshot_id']
            opening,opening_kind = scalar(latest[0]['cash']),'carried'
            if not start:
                start,start_kind = latest[0]['as_of'],'derived'
    if opening is None:
        return None,'opening_source_unavailable'
    known = len(store._operations)
    basis = dict(doc_id=facts.doc_id,opening=display(opening),opening_kind=opening_kind,period_start=start,start_kind=start_kind,
        seed_group=seed,predecessor_snapshot=predecessor,prior_basis=prior,created_revision=store._revision,known_operation=known,source_header_digest=source_digest(facts))
    basis['basis_id'] = digest(['sql-investment-basis-v1',facts.doc_id,key(opening),opening_kind,start,start_kind,seed,predecessor,prior,store._revision,known,basis['source_header_digest']])
    return basis,''


def _templates(facts, account_id):
    from ..ledger.events import Provenance
    templates = []
    for ordinal,line in enumerate(facts.activity):
        precision = posting_precision(line.amount,line.realized_gain)
        source = dict(facts.investment_source.rows[ordinal]).get('amount') if facts.investment_source else None
        page = source.page if source else None
        with localcontext() as arithmetic:
            arithmetic.Emax, arithmetic.Emin = MAX_EMAX, MIN_EMIN
            arithmetic.prec = precision
            arithmetic.traps[Inexact] = True
            event = brokerage_activity_transaction(account_id,line.kind,line.amount,line.description,line.date or facts.as_of,
                instrument=line.instrument,realized_gain=line.realized_gain,provenance=Provenance(facts.doc_id,page))
        legs = event.body['postings']
        if not zero_sum([Decimal(leg['amount']) for leg in legs]) or any(len(display(Decimal(leg['amount'])).encode())>16384 for leg in legs):
            raise ValueError('investment activity resource_limit')
        templates.append(legs)
    return templates


def _empty_activity_reason(facts, basis=None, locale='en-US'):
    """An empty list is complete only with actual compatible source fields."""
    if explicit_empty(facts)!='true':
        return 'empty_activity_unproved'
    fields={f['name']:f for f in source_fields(facts,locale) if f['scope']=='header'}
    amounts=[fields[name] for name in ('opening_cash','closing_cash')]
    if any(f['status']=='conflicted' and f['reason']=='source_disagrees' for f in amounts):
        return 'source_activity_conflict'
    if any(f['status']!='accepted' for f in amounts):
        return 'empty_activity_unproved'
    if key(scalar(fields['closing_cash']['value']))!=key(normalize_snapshot(facts).cash):
        return 'source_activity_conflict'
    if basis is not None and key(scalar(fields['opening_cash']['value']))!=key(scalar(basis['opening'])):
        return 'source_activity_conflict'
    return ''


def _admit_cash(store, facts, boundary):
    component = store._row('investment_components','doc_id=?',(facts.doc_id,))
    if component is None or component['snapshot_state']!='accepted':
        return
    if not source_consistency(facts,_locale(store,facts.doc_id))[1]:
        _component(store,facts,activity_state='conflicted',reason='source_activity_conflict')
        return
    account_id = component['account_id']
    try:
        _templates(facts,account_id)
    except (ValueError,OverflowError,Inexact):
        _component(store,facts,activity_state='held',reason='resource_limit')
        return
    if not facts.activity:
        empty_reason=_empty_activity_reason(facts,locale=_locale(store,facts.doc_id))
        if empty_reason:
            _component(store,facts,activity_state='conflicted' if empty_reason=='source_activity_conflict' else 'unavailable',reason=empty_reason)
            return
    basis,reason = _basis(store,facts,account_id)
    if basis is None:
        _component(store,facts,activity_state='held',reason=reason)
        return
    if not facts.activity:
        empty_reason=_empty_activity_reason(facts,basis,_locale(store,facts.doc_id))
        if empty_reason:
            _component(store,facts,activity_state='conflicted' if empty_reason=='source_activity_conflict' else 'unavailable',reason=empty_reason)
            return
    normalized = normalize_snapshot(facts)
    signed = [a.amount if a.kind in {'contribution','dividend','interest','sell'} else negate(a.amount) for a in facts.activity]
    if not zero_sum([scalar(basis['opening']),*signed,negate(normalized.cash)]):
        _component(store,facts,activity_state='held',reason='activity_arithmetic')
        return
    store._put('investment_bases',basis)
    source_start_value = source_start(facts,_locale(store,facts.doc_id))
    signature = canonical({'version':1,'logical_account':account_id,'currency':facts.currency,
        'start':['accepted',source_start_value] if source_start_value else ['unavailable',None],
        'end':facts.as_of,'opening':key(scalar(basis['opening'])),'closing':key(normalized.cash),
        'disposition':'accepted_complete_nonempty' if facts.activity else 'accepted_complete_empty',
        'explicit_empty':['accepted',True] if not facts.activity else ['unavailable',None],
        'rows':sorted([row_signature(facts,i,account_id) for i in range(len(facts.activity))],key=canonical)})
    group_id = digest(['sql-investment-cash-group-v1',signature])
    group = store._row('investment_groups','group_id=?',(group_id,))
    if group is None:
        group = dict(group_id=group_id,account_id=account_id,currency=facts.currency,period_start=source_start_value,period_end=facts.as_of,
            opening=basis['opening'],closing=display(normalized.cash),signature=signature,origin_doc=facts.doc_id,created_revision=store._revision)
        store._put('investment_groups',group)
    store._put('investment_witnesses',dict(doc_id=facts.doc_id,group_id=group_id,basis_id=basis['basis_id']))
    _component(store,facts,group_id=group_id,basis_id=basis['basis_id'])
    _close_bucket(store,account_id,facts.as_of,boundary)


def _activate_effects(store, group, basis):
    if rows(store,'investment_effects','group_id=?',(group['group_id'],)):
        return
    fact_row = store._row('investment_facts','doc_id=?',(basis['doc_id'],))
    facts = decode(json.loads(fact_row['body']))
    templates = _templates(facts,group['account_id'])
    occurrences = Counter()
    for ordinal,(line,legs) in enumerate(zip(facts.activity,templates)):
        signature = canonical(row_signature(facts,ordinal,group['account_id']))
        rank = occurrences[signature]
        occurrences[signature] += 1
        effect_id = digest(['sql-investment-effect-v1',group['group_id'],signature,rank])
        source_row = store._row('investment_rows','doc_id=? AND ordinal=?',(facts.doc_id,ordinal))
        store._put('investment_effects',dict(effect_id=effect_id,group_id=group['group_id'],occurrence_rank=rank,row_signature=signature,
            date=line.date or facts.as_of,kind=line.kind,amount=display(line.amount),instrument=line.instrument,
            realized_gain=None if line.realized_gain is None else display(line.realized_gain),owner_doc=facts.doc_id,owner_ordinal=ordinal))
        for leg,posting in enumerate(legs):
            store._put('investment_legs',dict(effect_id=effect_id,leg=leg,account_id=posting['account'],amount=display(Decimal(posting['amount'])),
                currency=facts.currency,grade=posting['grade'],doc_id=facts.doc_id,page=source_row['page']))


def _decision(store, group, action, basis_id, boundary):
    prior = store._row('investment_active','group_id=?',(group['group_id'],))
    ordinal = store._read('SELECT coalesce(max(ordinal),0)+1 FROM investment_decisions')[0][0]
    decision = dict(ordinal=ordinal,group_id=group['group_id'],action=action,basis_id=basis_id,
        previous_ordinal=prior['decision_ordinal'] if prior else None,revision=store._revision,boundary=boundary)
    if action=='activate':
        _activate_effects(store,group,store._row('investment_bases','basis_id=?',(basis_id,)))
    store._put('investment_decisions',decision)
    if action!='rebind':
        for effect in rows(store,'investment_effects','group_id=?',(group['group_id'],)):
            for leg in rows(store,'investment_legs','effect_id=?',(effect['effect_id'],)):
                amount = scalar(leg['amount'])
                store._put('investment_adjustments',{**leg,'decision_ordinal':ordinal,
                    'amount':display(negate(amount) if action=='deactivate' else amount),'date':effect['date']})
    store._put('investment_active',dict(group_id=group['group_id'],active=int(action!='deactivate'),decision_ordinal=ordinal,
        basis_id=None if action=='deactivate' else basis_id,revision=store._revision))


def _close_bucket(store, account_id, end, boundary):
    groups = rows(store,'investment_groups','account_id=? AND period_end=?',(account_id,end))
    conflict = len(groups)>1
    for group in groups:
        valid = []
        for witness in rows(store,'investment_witnesses','group_id=?',(group['group_id'],)):
            basis = store._row('investment_bases','basis_id=?',(witness['basis_id'],))
            if _basis_valid(store,basis,account_id,group['currency']):
                valid.append(basis)
        valid.sort(key=lambda b:(b['created_revision'],b['known_operation'],b['basis_id']))
        prior = store._row('investment_active','group_id=?',(group['group_id'],))
        prior_basis = next((b for b in valid if prior and b['basis_id']==prior['basis_id']),None)
        selected = prior_basis or (valid[0] if valid else None)
        eligible = not conflict and selected is not None
        if eligible and (prior is None or not prior['active']):
            _decision(store,group,'activate',selected['basis_id'],boundary)
        elif not eligible and prior is not None and prior['active']:
            _decision(store,group,'deactivate',prior['basis_id'],boundary)
        elif eligible and prior is not None and prior['active'] and prior['basis_id']!=selected['basis_id']:
            _decision(store,group,'rebind',selected['basis_id'],boundary)
        for witness in rows(store,'investment_witnesses','group_id=?',(group['group_id'],)):
            facts = decode(json.loads(store._row('investment_facts','doc_id=?',(witness['doc_id'],))['body']))
            _component(store,facts,activity_state='conflicted' if conflict else 'accepted' if eligible else 'held',
                reason='period_conflict' if conflict else '' if eligible else 'basis_unavailable',
                basis_id=witness['basis_id'])


def _cash_metadata(store, account_id):
    account = store._row('accounts','account_id=?',(account_id,))
    snapshots = rows(store,'investment_snapshots','account_id=?',(account_id,),order='as_of,created_revision,doc_id')
    observations = [(s['as_of'],s['cash']) for s in snapshots]
    for group,basis in _root_seeds(store,account_id,account['currency']):
        if basis['period_start']:
            observations.append((basis['period_start'],basis['opening']))
    if not observations:
        return
    observations.sort()
    earliest = [value for day,value in observations if day==observations[0][0]]
    latest = [value for day,value in observations if day==observations[-1][0]]
    changes = {}
    if len(set(earliest))==1:
        changes.update(earliest_date=observations[0][0],earliest_amount=earliest[0])
    if len(set(latest))==1:
        changes.update(current_date=observations[-1][0],current_amount=latest[0])
    store._put('accounts',{**account,**changes})


def causes(operations, store):
    result = []
    for op in operations:
        table,row = op['table'],op['row']
        if table not in CAUSE_TABLES:
            continue
        if table=='accounts':
            prior=store._investment_prior_accounts.get(row['account_id'])
            if prior is not None and all(prior[k]==row[k] for k in ('identity','kind','currency','number','normalized_number','institution','label','names')):
                continue
        source = row.get('doc_id')
        if source is None:
            account_id = row.get('account_id')
            snapshots = rows(store,'investment_snapshots','account_id=?',(account_id,),order='created_revision,doc_id') if account_id else []
            if snapshots:
                source = snapshots[0]['doc_id']
            elif account_id:
                periods = rows(store,'periods','account_id=?',(account_id,),order='period_end,doc_id')
                source = periods[0]['doc_id'] if periods else None
        if source is not None:
            result.append(dict(table=table,key=[row[k] for k in KEYS[table]],source_doc_id=source))
    return canonical({'version':1,'causes':sorted({canonical(v):v for v in result}.values(),key=canonical)})


def _wake_signals(store, operations):
    found = set()
    for op in operations:
        table,row = op['table'],op['row']
        if table=='interpretations' and row['facts_type']=='investment':
            found.update(signals(decode(json.loads(row['facts']))))
        elif table in {'reference_claims','reference_views'}:
            found.add(('reference',row['reference']))
        elif table=='holder_index':
            found.add(('holder',row['normalized_name']))
        elif table=='identity_decisions':
            body=json.loads(row['body'])
            if body['policy']=='investment_source_reference':
                found.update(signals(decode(body['input'])))
            else:
                from ..ingest.statement import StatementFacts
                facts=StatementFacts.from_dict(body['input'])
                found.add(('preferred',preferred_account_key(facts.institution,facts.account_number,facts.account_ref)))
                found.update(('holder',normalize_name(name)) for name in facts.account_names if normalize_name(name))
                if facts.source_account_ref:
                    found.add(('reference',facts.source_account_ref))
        elif table=='account_keys':
            found.add(('preferred',row['logical_key']))
        elif table=='accounts':
            found.add(('preferred',preferred_account_key(row['institution'],row['number'],row['label'])))
            if row['kind']=='investment' and row['normalized_number']:
                found.add(('number',canonical(['investment',row['normalized_number']])))
    return found


def close_writer(store):
    original = tuple(store._operations)
    input_docs = [op['row']['doc_id'] for op in original if op['table']=='interpretations' and op['row']['facts_type']=='investment']
    pending = set()
    for kind,signal in _wake_signals(store,original):
        pending.update(doc for (doc,) in store._read('SELECT doc_id FROM investment_dependencies WHERE signal_kind=? AND signal=? AND active=1',(kind,signal)))
    ordered = list(dict.fromkeys(input_docs))
    ordered += sorted(pending-set(ordered),key=lambda doc:(store._row('investment_facts','doc_id=?',(doc,))['created_revision'],doc))
    if not ordered:
        return
    queue = deque(ordered)
    seen = set()
    accounts = set()
    last = len(store._operations)
    generation=0
    while queue:
        doc = queue.popleft()
        token = (doc,generation)
        if token in seen:
            continue
        seen.add(token)
        fact_row = store._row('investment_facts','doc_id=?',(doc,))
        if fact_row is None:
            continue
        facts = decode(json.loads(fact_row['body']))
        component = _register(store,facts)
        if component['account_id']:
            accounts.add(component['account_id'])
        operations = tuple(store._operations[last:])
        last = len(store._operations)
        if any(op['table'] in {'accounts','account_keys','holder_index','reference_views'} for op in operations):
            generation+=1
        wake=set()
        for kind,signal in sorted(_wake_signals(store,operations)):
            wake.update(other for (other,) in store._read('SELECT doc_id FROM investment_dependencies WHERE signal_kind=? AND signal=? AND active=1',(kind,signal)) if other!=doc)
        queue.extend(sorted(wake,key=lambda other:(store._row('investment_facts','doc_id=?',(other,))['created_revision'],other)))
    boundary = causes(original,store)
    if not json.loads(boundary)['causes']:
        return
    # Registration is complete before cash; every admission may change a seed
    # or bucket and therefore revisits only its indexed physical-account set.
    for account_id in sorted(accounts):
        docs = rows(store,'investment_components','account_id=?',(account_id,))
        rank={doc:i for i,doc in enumerate(input_docs)}
        docs.sort(key=lambda c:(0,rank[c['doc_id']]) if c['doc_id'] in rank else (1,store._row('investment_facts','doc_id=?',(c['doc_id'],))['created_revision'],c['doc_id']))
        changed=True
        while changed:
            frontier=len(store._operations)
            for component in docs:
                facts = decode(json.loads(store._row('investment_facts','doc_id=?',(component['doc_id'],))['body']))
                _admit_cash(store,facts,boundary)
            for (end,) in store._read('SELECT DISTINCT period_end FROM investment_groups WHERE account_id=? ORDER BY period_end',(account_id,)):
                _close_bucket(store,account_id,end,boundary)
            changed=any(op['table'] in {'investment_groups','investment_witnesses','investment_bases','investment_decisions'} for op in store._operations[frontier:])
        _cash_metadata(store,account_id)


def component_view(store, doc_id):
    component = store._row('investment_components','doc_id=?',(doc_id,))
    if component is None:
        item = store._row('items','doc_id=?',(doc_id,))
        receipt=store._row('receipts','doc_id=?',(doc_id,))
        profile=profile_for(json.loads(receipt['body'])['doc_type']) if receipt else None
        if item is None or profile is None or profile.identity!=BROKERAGE_IDENTITY or profile.account_kind!='investment':
            raise AuthorityError('unknown investment document')
        return dict(doc_id=doc_id,snapshot_state='unavailable',activity_state='unavailable',source_state='unavailable',
                    funding_state='unavailable',reason=item['reason'],account_id=None)
    return {**component,'funding_state':'unavailable','fields':rows(store,'investment_fields','doc_id=?',(doc_id,))}


def snapshot_view(store, account_id, as_of):
    if not _date(as_of):
        raise AuthorityError('canonical investment date required')
    snapshots = rows(store,'investment_snapshots','account_id=? AND as_of<=?',(account_id,as_of),order='as_of DESC,created_revision,doc_id')
    if not snapshots:
        return None
    selected = [s for s in snapshots if s['as_of']==snapshots[0]['as_of']]
    if len({s['signature'] for s in selected})!=1:
        raise AuthorityError('latest investment valuation is conflicted')
    snapshot = selected[0]
    positions = []
    for position in rows(store,'investment_positions','snapshot_id=?',(snapshot['snapshot_id'],),order='ordinal'):
        optional = {}
        for name in ('units','cost_basis'):
            copies = []
            states = []
            for witness in selected:
                matches = rows(store,'investment_positions','snapshot_id=? AND security_id=?',(witness['snapshot_id'],position['security_id']))
                copies += [p[name] for p in matches if p[name] is not None]
                facts=decode(json.loads(store._row('investment_facts','doc_id=?',(witness['doc_id'],))['body']))
                original=next((i for i,p in enumerate(facts.positions) if security_name(facts,p.instrument)==security_name(facts,position['instrument'])),None)
                field=store._row('investment_fields','doc_id=? AND scope=? AND ordinal=? AND name=?',(witness['doc_id'],'position',original,name)) if original is not None else None
                states.append(field['status'] if field else 'unavailable')
            optional[name] = 'conflicted' if len(set(copies))>1 or 'conflicted' in states else 'accepted' if copies and 'accepted' in states else 'unavailable'
        positions.append(dict(instrument=position['instrument'],units=None if optional['units']=='conflicted' else position['units'],
            market_value=position['market_value'],cost_basis=None if optional['cost_basis']=='conflicted' else position['cost_basis'],
            page=position['page'],grade='corroborated',field_statuses=optional,
            provenance={'doc_id':snapshot['doc_id'],'page':position['page']}))
    return dict(account_id=account_id,currency=snapshot['currency'],as_of=snapshot['as_of'],doc_id=snapshot['doc_id'],
        cash=snapshot['cash'],total=snapshot['total'],positions=positions,grade='corroborated',source_docs=[s['doc_id'] for s in selected])


def cash_period_view(store, doc_id):
    component = component_view(store,doc_id)
    basis = store._row('investment_bases','basis_id=?',(component.get('basis_id'),)) if component.get('basis_id') else None
    cash = store._row('investment_cash_inputs','doc_id=?',(doc_id,))
    if cash is None:
        return None
    return dict(doc_id=doc_id,account_id=component['account_id'],period_start=basis['period_start'] if basis else cash['period_start'],
        period_end=cash['period_end'],opening_cash=basis['opening'] if basis else cash['printed_opening'],closing_cash=cash['closing'],
        state=component['activity_state'],opening_kind=basis['opening_kind'] if basis else 'unavailable',basis_id=basis['basis_id'] if basis else None,
        start_kind=basis['start_kind'] if basis else 'unavailable',source_completeness=component['source_state'])


def activity_view(store, doc_id):
    component = component_view(store,doc_id)
    result = []
    rank = Counter()
    for row in rows(store,'investment_rows','doc_id=?',(doc_id,),order='ordinal'):
        occurrence = rank[row['row_signature']]
        rank[row['row_signature']] += 1
        effect_id = digest(['sql-investment-effect-v1',component['group_id'],row['row_signature'],occurrence]) if component.get('group_id') else None
        effect = store._row('investment_effects','effect_id=?',(effect_id,)) if effect_id else None
        result.append({**row,'effect_id':effect_id if effect else None,'state':component['activity_state'],
            'source_owner':{'doc_id':effect['owner_doc'],'ordinal':effect['owner_ordinal']} if effect else None})
    return result


def postings_view(store, doc_id):
    component_view(store,doc_id)
    return [dict(account=r['account_id'],amount=r['amount'],currency=r['currency'],grade=r['grade'],date=r['date'],
                 effect_id=r['effect_id'],decision_ordinal=r['decision_ordinal'],leg=r['leg'],provenance={'doc_id':r['doc_id'],'page':r['page']})
            for r in rows(store,'investment_adjustments','doc_id=?',(doc_id,),order='decision_ordinal,effect_id,leg')]


def history_view(store, doc_id):
    component_view(store,doc_id)
    witnesses = rows(store,'investment_witnesses','doc_id=?',(doc_id,))
    groups = sorted({w['group_id'] for w in witnesses})
    return dict(doc_id=doc_id,bases=rows(store,'investment_bases','doc_id=?',(doc_id,),order='created_revision,known_operation,basis_id'),
        witnesses=witnesses,decisions=sorted([d for group in groups for d in rows(store,'investment_decisions','group_id=?',(group,))],key=lambda d:d['ordinal']),
        effects=[e for group in groups for e in rows(store,'investment_effects','group_id=?',(group,))],postings=postings_view(store,doc_id))


def cash_account_guard(store, account):
    observations = rows(store,'investment_snapshots','account_id=?',(account['account_id'],),order='as_of DESC,created_revision,doc_id')
    if observations and len({s['cash'] for s in observations if s['as_of']==observations[0]['as_of']})>1:
        raise AuthorityError('latest investment cash observation is conflicted')
