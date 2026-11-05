"""Independent native investment proof over every authenticated SQL prefix."""
from collections import Counter
from datetime import date
from decimal import Decimal, Inexact, localcontext, MAX_EMAX, MIN_EMIN
import hashlib
import json

from ..crypto import open_sealed
from ..ingest.brokerage import BrokerageFacts, from_brokerage_json, is_cash_row
from ..ingest.registry import profile_for
from ..ledger.events import Provenance
from ..ledger.identity import usable_full_number, preferred_account_key, normalize_name, SourceAccountIdentity
from ..ledger.postings import brokerage_activity_transaction
from .schema import TABLES, KEYS, FORMAT, SCHEMA_VERSION
from .store import canonical, IntegrityError
from .investment_numbers import key, display, scalar, zero_sum, negate, exact_sum, posting_precision
from .investment import decode


def fail(message):
    raise IntegrityError('investment semantic mismatch: '+message)


def h(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _source(store, prefix, doc, interpretation):
    receipt = prefix['receipts'].get((doc,))
    if receipt is None:
        fail('interpretation without retained receipt')
    reading = json.loads(receipt['body'])
    profile = profile_for(reading['doc_type'])
    if profile is None or profile.identity!='brokerage' or profile.account_kind!='investment':
        fail('foreign registered profile')
    tags = json.loads(receipt['capture_types'])
    context_id = tags.get('read_context_id')
    context_row = prefix['read_contexts'].get((context_id,))
    if context_row is None or h(json.loads(context_row['body']))!=context_id:
        fail('captured implementation context missing')
    context = json.loads(context_row['body'])
    from .reading import profile_descriptor
    from vivacore.verify import normalize
    if (context.get('format')!=FORMAT or type(context.get('schema_version')) is not int or context['schema_version']!=SCHEMA_VERSION
            or context.get('implementation')!=store._implementation_identity or context.get('normalization_rules_version')!=normalize.RULES_VERSION
            or context.get('profiles',{}).get(reading['doc_type'].strip().lower())!=profile_descriptor(profile)):
        fail('source normalization context differs')
    if receipt['facts_type']=='curated':
        from .curated import derive
        facts,occurrences = derive(store,receipt,reading)
        if type(facts) is not BrokerageFacts:
            fail('curated source family differs')
        expected = {(doc,r['line_index']):r for r in occurrences}
        actual = {k:r for k,r in prefix['source_occurrences'].items() if k[0]==doc}
        if expected!=actual:
            fail('source occurrence association/multiplicity differs')
    else:
        if receipt['facts_type']!='investment' or canonical(json.loads(receipt['facts']))!=canonical(reading.get('facts')):
            fail('raw custom wire association differs')
        facts = decode(json.loads(receipt['facts']),tags)
        if reading.get('raw_text'):
            raw=json.loads(reading['raw_text'])
            if type(raw) is not dict or ('doc_type' in raw and raw['doc_type']!=reading['doc_type']):
                fail('raw classification differs')
            raw.setdefault('doc_type',reading['doc_type'])
            parsed,error=from_brokerage_json(canonical(raw),doc,reading['source_locale'],facts.currency)
            if parsed is None or error:
                fail('retained raw source cannot normalize')
            comparison=[]
            for candidate in (facts,parsed):
                body=candidate.to_dict()
                for name in ('acquisition','doc_type_confidence','validated_source_page_count'):
                    body.pop(name,None)
                for name in ('cash','total','opening_cash'):
                    if body[name]!='':body[name]=key(Decimal(body[name]))
                for row in body['positions']:
                    for name in ('units','market_value','cost_basis'):
                        if row[name]!='':row[name]=key(Decimal(row[name]))
                for row in body['activity']:
                    for name in ('amount','realized_gain'):
                        if row[name]!='':row[name]=key(Decimal(row[name]))
                comparison.append(canonical(body))
            if comparison[0]!=comparison[1]:
                fail('raw source and typed values differ')
        if any(k[0]==doc for k in prefix['source_occurrences']):
            fail('typed source invented PDF occurrence')
    if facts.doc_id!=doc or facts.doc_type!=reading['doc_type'] or reading.get('error'):
        fail('source document/classification differs')
    if interpretation['facts']!=canonical(facts.to_dict()):
        fail('normalized facts differ from captured source')
    if hashlib.sha256(store._original(doc)).hexdigest()!=doc:
        fail('actual retained original address differs')
    expected_context = {'format':FORMAT,'schema_version':SCHEMA_VERSION,'implementation':store._implementation_identity,
        'normalization_rules_version':normalize.RULES_VERSION,'profile_version':profile.profile_version,
        'profile_identity':profile.identity,'profile_kind':profile.account_kind,'profile_descriptor':profile_descriptor(profile)}
    if json.loads(interpretation['context'])!=expected_context:
        fail('interpretation context association differs')
    return facts,context_id


def _security(facts, instrument):
    if facts.investment_source is None:
        return instrument
    candidates=[]
    for record in facts.investment_source.positions:
        fields=dict(record)
        identifier=_tag(fields.get('identifier'))
        label=_tag(fields.get('label'))
        if identifier[0]=='accepted' and (identifier[1]==instrument or label==['accepted',instrument]):
            candidates.append(identifier[1])
    return candidates[0] if len(candidates)==1 else instrument


def _locale(prefix,doc):
    return json.loads(prefix['receipts'][(doc,)]['body'])['source_locale'] or 'en-US'


def _normalized(facts):
    positions = facts.positions
    sweeps = [p for p in positions if is_cash_row(p.instrument)]
    others = [p for p in positions if not is_cash_row(p.instrument)]
    if not sweeps:
        return facts.cash,positions
    included = zero_sum([p.market_value for p in others]+[facts.cash,negate(facts.total)])
    separate = zero_sum([p.market_value for p in positions]+[facts.cash,negate(facts.total)])
    if not included and not separate:
        return facts.cash,positions
    return (facts.cash if included and not separate else exact_sum([facts.cash]+[p.market_value for p in sweeps])),others


def _field(field, kind, currency, locale='en-US'):
    from vivacore.verify.normalize import parse_amount,parse_date
    from ..investment.contracts import decimal
    if field is None:
        return None,'unavailable','missing_source'
    if field.page is None:
        return None,'unavailable','invalid_page'
    if not field.raw.strip():
        return None,'unavailable','unreadable_source'
    raw=field.raw.strip()
    try:
        if kind=='number':
            parsed=parse_amount(raw,locale,currency)
            if not parsed.ok:
                return None,'unavailable','unreadable_source'
            return display(decimal(str(parsed.decimal()),signed=True)),'accepted',''
        if kind=='date':
            parsed=parse_date(raw,locale)
            return (parsed.value,'accepted','') if parsed.ok else (None,'unavailable','unreadable_source')
        return field.raw,'accepted',''
    except (ValueError,TypeError):
        return None,'unavailable','unreadable_source'


def _fields(facts, locale='en-US'):
    from ..investment.extraction import HEADERS,POSITION,ROW
    source=facts.investment_source
    records=[('header',-1,dict(source.headers) if source else {},HEADERS)]
    records += [('position',i,dict(source.positions[i]) if source else {},POSITION) for i in range(len(facts.positions))]
    records += [('activity',i,dict(source.rows[i]) if source else {},ROW) for i in range(len(facts.activity))]
    result={}
    for scope,ordinal,record,names in records:
        for name in names:
            field=record.get(name)
            kind='number' if name in {'units','market_value','cost_basis','opening_cash','closing_cash','amount','reported_realized_gain'} else 'date' if name in {'date','as_of','period_start','period_end'} else 'text'
            value,status,reason=_field(field,kind,facts.currency,locale)
            if scope=='position' and name=='units' and status=='accepted':
                from ..investment.units import units
                try:
                    units(value,group_separator='')
                except ValueError:
                    value,status,reason=None,'unavailable','unsupported_field'
            if scope=='activity' and name=='amount' and status=='accepted':
                value=display(scalar(value).copy_abs())
            expected={}
            if scope=='header':
                expected={'currency':facts.currency,'as_of':facts.as_of,'period_end':facts.as_of,'closing_cash':display(facts.cash)}
                if facts.opening_cash is not None:
                    expected['opening_cash']=display(facts.opening_cash)
            elif scope=='position':
                p=facts.positions[ordinal]
                expected={'identifier':p.instrument,'units':display(p.units),'market_value':display(p.market_value),'cost_basis':None if p.cost_basis is None else display(p.cost_basis)}
            else:
                a=facts.activity[ordinal]
                expected={'date':a.date or facts.as_of,'kind':a.kind,'amount':display(a.amount),'security_identifier':a.instrument,'reported_realized_gain':None if a.realized_gain is None else display(a.realized_gain)}
            if scope=='position' and name=='identifier' and status=='accepted':
                label,ls,_=_field(record.get('label'),'text',facts.currency)
                if ls=='accepted' and label==facts.positions[ordinal].instrument:
                    expected.pop('identifier',None)
            if status=='accepted' and name in expected and value!=expected[name]:
                value,status,reason=None,'conflicted','source_disagrees'
            row=dict(doc_id=facts.doc_id,scope=scope,ordinal=ordinal,name=name,raw=None if field is None else field.raw,
                page=None if field is None else field.page,value=value,status=status,grade='conflicted' if status=='conflicted' else 'unverified',reason=reason)
            result[(facts.doc_id,scope,ordinal,name)]=row
    return result


def _tag(field,kind='text',locale='en-US'):
    value,status,_=_field(field,kind,'',locale)
    return [status,value]


def _row_signature(facts,ordinal,account):
    a=facts.activity[ordinal]
    source=dict(facts.investment_source.rows[ordinal]) if facts.investment_source else {}
    printed=_tag(source.get('printed_row_reference'))
    role=source.get('funding_role')
    normalized=['accepted',role.role] if role is not None and hasattr(role,'role') and role.page is not None else _tag(role)
    return dict(date=a.date or facts.as_of,kind=a.kind,amount=key(a.amount),
        instrument=['accepted',a.instrument] if a.instrument else ['unavailable',None],signedgain=['accepted',key(a.realized_gain)] if a.realized_gain is not None else ['unavailable',None],
        funding_role='unknown',reported_role_source=normalized,funding_reference=_tag(source.get('printed_reference')),
        counterpart_reference=_tag(source.get('counterpart_reference')),printed_row_reference=printed,
        namespace=['accepted',account] if printed[0]=='accepted' else ['unavailable',None])


def _root(facts):
    from vivacore.verify.normalize import parse_date,parse_amount
    if facts.investment_source is None or facts.opening_cash is None or not facts.activity or type(facts.validated_source_page_count) is not int:
        return False
    headers=dict(facts.investment_source.headers)
    names=('period_start','period_end','as_of','currency','opening_cash')
    if any(headers[n] is None or type(headers[n].page) is not int or not 1<=headers[n].page<=facts.validated_source_page_count or not headers[n].raw.strip() for n in names):
        return False
    start,end,asof=[parse_date(headers[n].raw) for n in names[:3]]
    amount=parse_amount(headers['opening_cash'].raw,currency=facts.currency)
    return (all(v.ok for v in (start,end,asof)) and end.value==facts.as_of and asof.value==facts.as_of and start.value<=end.value
        and headers['currency'].raw.strip()==facts.currency and amount.ok and amount.decimal()==facts.opening_cash
        and all(start.value <= (a.date or facts.as_of) <= end.value for a in facts.activity))


def _roots(prefix,facts_by_doc,account,currency):
    result=[]
    for (group_id,),group in prefix['investment_groups'].items():
        if group['account_id']!=account or group['currency']!=currency:
            continue
        activated=[d for d in prefix['investment_decisions'].values() if d['group_id']==group_id and d['action']=='activate']
        if not activated:
            continue
        bases=[prefix['investment_bases'][(w['basis_id'],)] for w in prefix['investment_witnesses'].values() if w['group_id']==group_id]
        for basis in sorted(bases,key=lambda b:(b['created_revision'],b['known_operation'],b['basis_id'])):
            facts=facts_by_doc[basis['doc_id']]
            if basis['seed_group'] is not None or basis['predecessor_snapshot'] is not None or basis['prior_basis'] is not None or not _root(facts):
                continue
            rivals=[]
            for other in prefix['investment_bases'].values():
                if other['seed_group'] is not None or other['period_start']!=basis['period_start']:
                    continue
                admitted=[w for w in prefix['investment_witnesses'].values() if w['basis_id']==other['basis_id']]
                if any(prefix['investment_groups'][(w['group_id'],)]['account_id']==account and prefix['investment_groups'][(w['group_id'],)]['currency']==currency for w in admitted):
                    rivals.append(other['opening'])
            if any(v!=basis['opening'] for v in rivals):
                continue
            first=min(activated,key=lambda d:d['ordinal'])
            result.append((first['revision'],first['ordinal'],group_id,basis))
            break
    return sorted(result,key=lambda v:v[:3])


def _basis_valid(prefix,facts_by_doc,basis,account,currency):
    component=prefix['investment_components'].get((basis['doc_id'],))
    facts=facts_by_doc.get(basis['doc_id'])
    if facts is None or facts.currency!=currency or component is None or component['account_id']!=account:
        return False
    header=facts.investment_source.to_dict()['headers'] if facts.investment_source else None
    if basis['source_header_digest']!=h(header):
        return False
    if basis['predecessor_snapshot'] is not None:
        predecessor=prefix['investment_snapshots'].get((basis['predecessor_snapshot'],))
        if predecessor is None or predecessor['account_id']!=account or predecessor['currency']!=currency or predecessor['cash']!=basis['opening']:
            return False
        observations=[s for s in prefix['investment_snapshots'].values() if s['account_id']==account and s['as_of']==predecessor['as_of']]
        if len({s['cash'] for s in observations})!=1:
            return False
    if basis['seed_group'] is not None:
        return basis['seed_group'] in {r[2] for r in _roots(prefix,facts_by_doc,account,currency)}
    if not _root(facts):
        return False
    for rival in prefix['investment_bases'].values():
        if rival['seed_group'] is None and rival['period_start']==basis['period_start'] and rival['opening']!=basis['opening']:
            for witness in prefix['investment_witnesses'].values():
                if witness['basis_id']==rival['basis_id'] and prefix['investment_groups'][(witness['group_id'],)]['account_id']==account:
                    return False
    return True


def _basis_creation(prefix, facts_by_doc, basis, revision, operation_index):
    if basis['created_revision']!=revision or basis['known_operation']!=operation_index:
        fail('basis actual creation frontier differs')
    facts=facts_by_doc.get(basis['doc_id'])
    component=prefix['investment_components'].get((basis['doc_id'],))
    if facts is None or component is None or component['snapshot_state']!='accepted':
        fail('basis has no admitted earlier source population')
    account=component['account_id']
    prior=prefix['investment_bases'].get((basis['prior_basis'],)) if basis['prior_basis'] else None
    if basis['prior_basis'] and prior is None:
        fail('basis cites a future prior basis')
    if prior is not None:
        unchanged={'doc_id','opening','opening_kind','period_start','start_kind','predecessor_snapshot','source_header_digest'}
        if any(prior[k]!=basis[k] for k in unchanged) or prior['seed_group'] is None or _basis_valid(prefix,facts_by_doc,prior,account,facts.currency):
            fail('rebind changed economic opening or replaced a usable basis')
    elif any(b['doc_id']==facts.doc_id and _basis_valid(prefix,facts_by_doc,b,account,facts.currency) for b in prefix['investment_bases'].values()):
        fail('new basis replaced an earlier usable basis')
    source_headers=facts.investment_source.to_dict()['headers'] if facts.investment_source else None
    if basis['source_header_digest']!=h(source_headers):
        fail('basis raw header digest differs')
    start=_tag(dict(facts.investment_source.headers).get('period_start'),'date',_locale(prefix,facts.doc_id))[1] if facts.investment_source else None
    if prior is None and _root(facts):
        if basis['seed_group'] is not None or basis['predecessor_snapshot'] is not None or basis['opening_kind']!='printed' or basis['opening']!=display(facts.opening_cash) or basis['period_start']!=start or basis['start_kind']!='printed':
            fail('printed root basis differs from source')
    else:
        roots=_roots(prefix,facts_by_doc,account,facts.currency)
        if not roots or basis['seed_group']!=roots[0][2]:
            fail('basis lacks canonical actual earlier root activation')
        if prior is None and facts.opening_cash is not None:
            if basis['opening']!=display(facts.opening_cash) or basis['opening_kind']!='printed' or basis['predecessor_snapshot'] is not None or basis['period_start']!=start or basis['start_kind']!=('printed' if start else 'unavailable'):
                fail('already-seeded printed basis differs')
        elif prior is None:
            snapshots=sorted([s for s in prefix['investment_snapshots'].values() if s['account_id']==account and s['currency']==facts.currency and s['doc_id']!=facts.doc_id],key=lambda s:(s['as_of'], -s['created_revision'],s['doc_id']),reverse=True)
            if not snapshots or snapshots[0]['as_of']>=facts.as_of:
                fail('carry searched beyond a known future observation')
            latest=sorted([s for s in snapshots if s['as_of']==snapshots[0]['as_of']],key=lambda s:(s['created_revision'],s['doc_id']))
            if len({s['cash'] for s in latest})!=1 or basis['predecessor_snapshot']!=latest[0]['snapshot_id'] or basis['opening']!=latest[0]['cash'] or basis['opening_kind']!='carried':
                fail('carry predecessor frontier/equality differs')
            if basis['period_start']!=(start or latest[0]['as_of']) or basis['start_kind']!=('printed' if start else 'derived'):
                fail('carried boundary labelled as printed')
    if not facts.activity and _empty_proof(facts,_locale(prefix,facts.doc_id),scalar(basis['opening'])):
        fail('empty basis lacks accepted compatible source opening/closing')
    expected=['sql-investment-basis-v1',basis['doc_id'],key(scalar(basis['opening'])),basis['opening_kind'],basis['period_start'],basis['start_kind'],basis['seed_group'],basis['predecessor_snapshot'],basis['prior_basis'],revision,operation_index,basis['source_header_digest']]
    if basis['basis_id']!=h(expected):
        fail('basis digest differs')


def _empty_proof(facts, locale, opening=None):
    """Re-derive required evidence from captured source, never derived fields."""
    headers=dict(facts.investment_source.headers) if facts.investment_source else {}
    assertion=_tag(headers.get('no_activity'))
    if assertion[0]!='accepted' or assertion[1].lower() not in {'true','yes'}:
        return 'empty_activity_unproved'
    normalized={name:_field(headers.get(name),'number',facts.currency,locale)
                for name in ('opening_cash','closing_cash')}
    for name,typed in (('opening_cash',facts.opening_cash),('closing_cash',facts.cash)):
        value,status,_reason=normalized[name]
        if status=='accepted' and typed is not None and key(scalar(value))!=key(typed):
            return 'source_activity_conflict'
    if any(status!='accepted' for value,status,reason in normalized.values()):
        return 'empty_activity_unproved'
    values={name:scalar(result[0]) for name,result in normalized.items()}
    cash,_population=_normalized(facts)
    if key(values['closing_cash'])!=key(cash):
        return 'source_activity_conflict'
    if opening is not None and key(values['opening_cash'])!=key(opening):
        return 'source_activity_conflict'
    return ''


def _group(prefix, facts_by_doc, group):
    facts=facts_by_doc.get(group['origin_doc'])
    component=prefix['investment_components'].get((group['origin_doc'],))
    if facts is None or component is None or component['account_id']!=group['account_id']:
        fail('group source origin differs')
    bases=[b for b in prefix['investment_bases'].values() if b['doc_id']==facts.doc_id and b['opening']==group['opening']]
    if not bases:
        fail('cash group has no earlier genuine basis')
    fields=_fields(facts,_locale(prefix,facts.doc_id))
    if any(f['status']=='conflicted' and f['scope']=='activity' and f['name'] in {'date','kind','amount','reported_realized_gain','security_identifier'} for f in fields.values()):
        fail('ineligible source activity became a competing complete group')
    try:
        _effect_templates(prefix,facts_by_doc,group,bases[0])
    except (ValueError,OverflowError,Inexact):
        fail('resource-held activity became a competing complete group')
    cash,_positions=_normalized(facts)
    signed=[a.amount if a.kind in {'contribution','dividend','interest','sell'} else negate(a.amount) for a in facts.activity]
    if not zero_sum([scalar(group['opening']),*signed,negate(cash)]):
        fail('cash flow arithmetic differs')
    empty=not facts.activity
    assertion=dict(facts.investment_source.headers).get('no_activity') if facts.investment_source else None
    if empty and _empty_proof(facts,_locale(prefix,facts.doc_id),scalar(group['opening'])):
        fail('empty group lacks accepted compatible source opening/closing')
    start=_tag(dict(facts.investment_source.headers).get('period_start'),'date',_locale(prefix,facts.doc_id))[1] if facts.investment_source else None
    signature=canonical(dict(version=1,logical_account=group['account_id'],currency=facts.currency,
        start=['accepted',start] if start else ['unavailable',None],end=facts.as_of,opening=key(scalar(group['opening'])),closing=key(cash),
        disposition='accepted_complete_empty' if empty else 'accepted_complete_nonempty',explicit_empty=['accepted',True] if empty else ['unavailable',None],
        rows=sorted([_row_signature(facts,i,group['account_id']) for i in range(len(facts.activity))],key=canonical)))
    if group['signature']!=signature or group['group_id']!=h(['sql-investment-cash-group-v1',signature]) or group['closing']!=display(cash) or group['currency']!=facts.currency or group['period_end']!=facts.as_of or group['period_start']!=start:
        fail('cash economic signature/source differs')


def _desired(prefix, facts_by_doc, group, active):
    siblings=[g for g in prefix['investment_groups'].values() if g['account_id']==group['account_id'] and g['period_end']==group['period_end']]
    valid=[]
    for witness in prefix['investment_witnesses'].values():
        if witness['group_id']!=group['group_id']:
            continue
        basis=prefix['investment_bases'].get((witness['basis_id'],))
        if basis is None:
            fail('witness cites a future basis')
        if _basis_valid(prefix,facts_by_doc,basis,group['account_id'],group['currency']):
            valid.append(basis)
    valid.sort(key=lambda b:(b['created_revision'],b['known_operation'],b['basis_id']))
    selected=next((b for b in valid if active and b['basis_id']==active['basis_id']),None) or (valid[0] if valid else None)
    return len(siblings)==1 and selected is not None,selected


def _registration_start(operations,prefix):
    for index,op in enumerate(operations):
        table,row=op['table'],op['row']
        if (table in {'investment_snapshots','investment_components'}
                or table=='accounts' and row['kind']=='investment'
                or table=='identity_decisions' and json.loads(row['body']).get('policy')=='investment_source_reference'
                or table=='reference_claims' and (row['doc_id'],) in prefix['investment_facts']):
            return index
    return len(operations)


def _cause_boundary(operations, before, prefix):
    # Input facts/fields are staged before native registration. The first native
    # account/measurement/component operation starts the derived close phase.
    end=_registration_start(operations,prefix)
    causes=[]
    eligible={'interpretations','accounts','account_keys','holder_index','reference_claims','reference_views','identity_decisions'}
    for op in operations[:end]:
        table,row=op['table'],op['row']
        if table not in eligible:
            continue
        if table=='accounts':
            old=before['accounts'].get((row['account_id'],))
            if old is not None and all(old[k]==row[k] for k in ('identity','kind','currency','number','normalized_number','institution','label','names')):
                continue
        doc=row.get('doc_id')
        if doc is None:
            account=row.get('account_id')
            snapshots=sorted([s for s in prefix['investment_snapshots'].values() if s['account_id']==account],key=lambda s:(s['created_revision'],s['doc_id']))
            if snapshots:
                doc=snapshots[0]['doc_id']
            else:
                periods=sorted([p for p in prefix['periods'].values() if p['account_id']==account],key=lambda p:(p['period_end'],p['doc_id']))
                doc=periods[0]['doc_id'] if periods else None
        if doc:
            causes.append(dict(table=table,key=[row[k] for k in KEYS[table]],source_doc_id=doc))
    return canonical(dict(version=1,causes=sorted({canonical(v):v for v in causes}.values(),key=canonical)))


def _static(prefix, facts_by_doc, contexts, creation_revisions):
    expected_facts={}
    expected_fields={}
    for doc,facts in facts_by_doc.items():
        receipt=prefix['receipts'][(doc,)]
        expected_facts[(doc,)]=dict(doc_id=doc,currency=facts.currency,as_of=facts.as_of,body=canonical(facts.to_dict()),
            context_id=contexts[doc],source_kind='curated' if receipt['facts_type']=='curated' else 'typed',created_revision=creation_revisions[doc])
        expected_fields.update(_fields(facts,_locale(prefix,facts.doc_id)))
    if prefix['investment_facts']!=expected_facts or prefix['investment_fields']!=expected_fields:
        fail('facts/field completeness or source statuses differ')
    for snapshot in prefix['investment_snapshots'].values():
        facts=facts_by_doc.get(snapshot['doc_id'])
        if facts is None:
            fail('snapshot without a genuine source')
        try:
            cash,positions=_normalized(facts)
        except (ValueError,OverflowError):
            fail('resource-held measurement admitted as a complete population')
        if not zero_sum([p.market_value for p in positions]+[cash,negate(facts.total)]):
            fail('snapshot rounded or unbalanced')
        if len({_security(facts,p.instrument) for p in positions})!=len(positions) or any(not p.instrument.strip() for p in positions):
            fail('ambiguous position population admitted')
        fields=_fields(facts,_locale(prefix,facts.doc_id))
        if any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'}) for f in fields.values()):
            fail('snapshot source contradiction admitted')
        signature=canonical(dict(version=1,logical_account=snapshot['account_id'],currency=facts.currency,as_of=facts.as_of,cash=key(cash),total=key(facts.total),positions=sorted([[_security(facts,p.instrument),key(p.market_value)] for p in positions],key=canonical)))
        if snapshot['snapshot_id']!=h(['sql-investment-snapshot-v1',facts.doc_id]) or snapshot['signature']!=signature or snapshot['cash']!=display(cash) or snapshot['total']!=display(facts.total) or snapshot['position_count']!=len(positions) or snapshot['currency']!=facts.currency or snapshot['as_of']!=facts.as_of:
            fail('complete snapshot body differs')
        actual=[r for r in prefix['investment_positions'].values() if r['snapshot_id']==snapshot['snapshot_id']]
        if len(actual)!=len(positions):
            fail('complete position occurrence count differs')
        for ordinal,p in enumerate(positions):
            row=prefix['investment_positions'].get((snapshot['snapshot_id'],ordinal))
            original=next(i for i,v in enumerate(facts.positions) if v.instrument==p.instrument)
            source_fields=[f for f in fields.values() if f['scope']=='position' and f['ordinal']==original]
            source_state='conflicted' if any(f['status']=='conflicted' for f in source_fields) else 'accepted' if facts.investment_source else 'unavailable'
            expected=dict(snapshot_id=snapshot['snapshot_id'],ordinal=ordinal,security_id=h(['investment-security-v1',snapshot['account_id'],_security(facts,p.instrument)]),instrument=p.instrument,
                units=display(p.units),market_value=display(p.market_value),cost_basis=None if p.cost_basis is None else display(p.cost_basis),page=p.page,source_state=source_state)
            if row!=expected:
                fail('signed position measurement or ownership differs')
        component=prefix['investment_components'].get((facts.doc_id,))
        item=prefix['items'].get((facts.doc_id,))
        if component is None or component['snapshot_id']!=snapshot['snapshot_id'] or component['snapshot_state']!='accepted' or component['account_id']!=snapshot['account_id'] or item is None or item['state']!='accepted' or item['account_id']!=snapshot['account_id']:
            fail('snapshot/account/item ownership differs')
        account=prefix['accounts'].get((snapshot['account_id'],))
        if account is None or account['kind']!='investment' or account['currency']!=facts.currency:
            fail('snapshot has a foreign physical account')
        from ..ledger.identity import canonical_institution,conflicting_number_signals
        number=usable_full_number(facts.account_number)
        if number and number.isascii() and canonical_institution(facts.institution) and not conflicting_number_signals(facts.account_number,facts.account_ref):
            if account['identity']!=h(['investment',canonical_institution(facts.institution),number]):
                fail('full-number account identity differs from its source')
        cash_row=prefix['investment_cash_inputs'].get((facts.doc_id,))
        start=_tag(dict(facts.investment_source.headers).get('period_start'),'date',_locale(prefix,facts.doc_id))[1] if facts.investment_source else None
        empty=_tag(dict(facts.investment_source.headers).get('no_activity')) if facts.investment_source else ['unavailable',None]
        empty_value='true' if empty[0]=='accepted' and empty[1].lower() in {'true','yes'} else 'false' if empty[0]=='accepted' else 'unavailable'
        if cash_row!=dict(doc_id=facts.doc_id,period_start=start,period_end=facts.as_of,printed_opening=None if facts.opening_cash is None else display(facts.opening_cash),closing=display(cash),explicit_empty=empty_value):
            fail('cash input differs from retained observations')
        activity_rows=[r for r in prefix['investment_rows'].values() if r['doc_id']==facts.doc_id]
        if len(activity_rows)!=len(facts.activity):
            fail('observed activity occurrence omitted')
        for ordinal,a in enumerate(facts.activity):
            source=dict(facts.investment_source.rows[ordinal]).get('amount') if facts.investment_source else None
            occurrence=prefix['source_occurrences'].get((facts.doc_id,ordinal))
            local_fields=[f for f in fields.values() if f['scope']=='activity' and f['ordinal']==ordinal]
            source_state='conflicted' if any(f['status']=='conflicted' for f in local_fields) else 'accepted' if facts.investment_source else 'unavailable'
            expected=dict(doc_id=facts.doc_id,ordinal=ordinal,date=a.date or facts.as_of,kind=a.kind,amount=display(a.amount),description=a.description,instrument=a.instrument,
                realized_gain=None if a.realized_gain is None else display(a.realized_gain),page=occurrence['page'] if occurrence else source.page if source else None,
                source_event_id=occurrence['event_id'] if occurrence else None,row_signature=canonical(_row_signature(facts,ordinal,snapshot['account_id'])),source_state=source_state)
            if prefix['investment_rows'].get((facts.doc_id,ordinal))!=expected:
                fail('observed activity identity/source differs')
    owned_snapshots={s['snapshot_id'] for s in prefix['investment_snapshots'].values()}
    if any(r['snapshot_id'] not in owned_snapshots for r in prefix['investment_positions'].values()):
        fail('orphan position population')
    snapshot_docs={s['doc_id'] for s in prefix['investment_snapshots'].values()}
    if any(r['doc_id'] not in snapshot_docs for name in ('investment_rows','investment_cash_inputs') for r in prefix[name].values()):
        fail('invented activity without an admitted population')


def _effect_templates(prefix, facts_by_doc, group, basis):
    facts=facts_by_doc[basis['doc_id']]
    counts=Counter()
    effects={}
    legs={}
    for ordinal,a in enumerate(facts.activity):
        signature=canonical(_row_signature(facts,ordinal,group['account_id']))
        rank=counts[signature];counts[signature]+=1
        effect_id=h(['sql-investment-effect-v1',group['group_id'],signature,rank])
        effect=dict(effect_id=effect_id,group_id=group['group_id'],occurrence_rank=rank,row_signature=signature,date=a.date or facts.as_of,
            kind=a.kind,amount=display(a.amount),instrument=a.instrument,realized_gain=None if a.realized_gain is None else display(a.realized_gain),owner_doc=facts.doc_id,owner_ordinal=ordinal)
        effects[(effect_id,)]=effect
        precision=posting_precision(a.amount,a.realized_gain)
        source=prefix['investment_rows'][(facts.doc_id,ordinal)]
        with localcontext() as context:
            context.Emax,context.Emin=MAX_EMAX,MIN_EMIN
            context.prec=precision
            context.traps[Inexact]=True
            event=brokerage_activity_transaction(group['account_id'],a.kind,a.amount,a.description,a.date or facts.as_of,
                instrument=a.instrument,realized_gain=a.realized_gain,provenance=Provenance(facts.doc_id,source['page']))
        if not zero_sum([Decimal(p['amount']) for p in event.body['postings']]):
            fail('constructor legs do not balance exactly')
        for leg,p in enumerate(event.body['postings']):
            amount=display(Decimal(p['amount']))
            if len(amount.encode())>16384:
                fail('constructor leg exceeds scalar allocation limit')
            legs[(effect_id,leg)]=dict(effect_id=effect_id,leg=leg,account_id=p['account'],amount=amount,currency=facts.currency,
                grade=p['grade'],doc_id=facts.doc_id,page=source['page'])
    return effects,legs


def _source_status(facts,fields):
    if facts.investment_source is None:
        return 'unavailable'
    conflict=any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'} or f['scope']=='activity' and f['name'] in {'date','kind','amount','reported_realized_gain','security_identifier'}) for f in fields.values())
    if conflict:
        return 'conflicted'
    required={'header':{'account_reference','currency','period_start','period_end','as_of','opening_cash','closing_cash'},'position':{'identifier','market_value'},'activity':{'date','kind','amount'}}
    return 'held' if any(f['name'] in required[f['scope']] and f['status']!='accepted' for f in fields.values()) else 'accepted'


def _final_eligibility(prefix, facts_by_doc, expected_active):
    for group in prefix['investment_groups'].values():
        active=expected_active.get((group['group_id'],))
        eligible,basis=_desired(prefix,facts_by_doc,group,active)
        if eligible != bool(active and active['active']):
            fail('required activation/reversal omitted')
        if eligible and active['basis_id']!=basis['basis_id']:
            fail('required basis rebind omitted')
    for doc,facts in facts_by_doc.items():
        component=prefix['investment_components'].get((doc,))
        if component is None:
            fail('recognized typed investment component omitted')
        intrinsic=_fields(facts,_locale(prefix,doc))
        if component['source_state']!=_source_status(facts,intrinsic):
            fail('intrinsic source state is not its genuine fields')
        snapshot=prefix['investment_snapshots'].get((component['snapshot_id'],)) if component['snapshot_id'] else None
        if snapshot is None:
            try:
                cash,positions=_normalized(facts)
            except (ValueError,OverflowError):
                if component['snapshot_state']!='held' or component['reason']!='resource_limit':
                    fail('snapshot resource disposition differs')
                continue
            fields=_fields(facts,_locale(prefix,facts.doc_id))
            source_conflict=any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'}) for f in fields.values())
            bounded=all(len(display(v).encode())<=16384 for v in [cash,facts.total,*[x for p in positions for x in (p.units,p.market_value)],*[p.cost_basis for p in positions if p.cost_basis is not None]])
            valid=(bounded and zero_sum([p.market_value for p in positions]+[cash,negate(facts.total)]) and len({_security(facts,p.instrument) for p in positions})==len(positions)
                   and all(p.instrument.strip() for p in positions) and not source_conflict)
            snapshot_reason=('resource_limit' if not bounded else 'snapshot_arithmetic' if not zero_sum([p.market_value for p in positions]+[cash,negate(facts.total)]) else 'population_identity_requires_review' if len({_security(facts,p.instrument) for p in positions})!=len(positions) or any(not p.instrument.strip() for p in positions) else 'source_value_conflict' if source_conflict else 'identity_requires_review')
            if component['snapshot_state']!=('conflicted' if snapshot_reason=='source_value_conflict' else 'held') or component['reason']!=snapshot_reason or component['activity_state']!='held' or component['snapshot_id'] is not None or component['account_id'] is not None or component['group_id'] is not None or component['basis_id'] is not None:
                fail('held snapshot state/reason or ownership differs')
            number=usable_full_number(facts.account_number)
            from ..ledger.identity import canonical_institution,conflicting_number_signals
            strong=bool(number and number.isascii() and canonical_institution(facts.institution) and not conflicting_number_signals(facts.account_number,facts.account_ref))
            if valid and strong:
                identity=h(['investment',canonical_institution(facts.institution),number])
                rivals=[a for a in prefix['accounts'].values() if a['kind']=='investment' and a['normalized_number']==number]
                if not rivals or all(a['identity']==identity and a['currency']==facts.currency for a in rivals):
                    fail('eligible complete native population omitted')
            if valid and not strong:
                from ..ledger.identity import identity_number_key
                from ..ledger.projection.accounts import resolve
                from .identity import detached_state
                field=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
                claim=SourceAccountIdentity(field.raw if field else '',doc,field.page if field else None,facts.validated_source_page_count)
                if claim.eligible() and not identity_number_key(facts.account_number,facts.account_ref):
                    metadata=[{**a,**prefix['account_keys'][(a['account_id'],)]} for a in prefix['accounts'].values()]
                    logical={a['account_id']:a['logical_key'] for a in metadata}
                    claims=[{**c,'logical_key':logical[c['account_id']]} for c in prefix['reference_claims'].values()]
                    captured={d['doc_id'] for d in prefix['documents'].values()}
                    decision=resolve(detached_state(metadata,claims,captured),facts.institution,facts.account_number,facts.account_ref,facts.account_names,kind='investment',doc_id=doc,currency=facts.currency,source_identity=claim)
                    physical=next((a for a in metadata if a['logical_key']==decision.account_id),None)
                    if decision.verdict=='new' and physical is None or decision.verdict=='same' and physical is not None and physical['currency']==facts.currency and physical['kind']=='investment':
                        fail('eligible source-reference pending registration omitted')
            continue
        fields=_fields(facts,_locale(prefix,facts.doc_id))
        required={'header':{'account_reference','currency','period_start','period_end','as_of','opening_cash','closing_cash'},'position':{'identifier','market_value'},'activity':{'date','kind','amount'}}
        source_conflict=any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'} or f['scope']=='activity' and f['name'] in {'date','kind','amount','reported_realized_gain','security_identifier'}) for f in fields.values())
        source_state='unavailable' if facts.investment_source is None else 'conflicted' if source_conflict else 'held' if any(f['name'] in required[f['scope']] and f['status']!='accepted' for f in fields.values()) else 'accepted'
        if component['source_state']!=source_state:
            fail('source facet state differs')
        witnesses=[w for w in prefix['investment_witnesses'].values() if w['doc_id']==doc]
        for witness in witnesses:
            group=prefix['investment_groups'][(witness['group_id'],)]
            basis=prefix['investment_bases'][(witness['basis_id'],)]
            if basis['doc_id']!=doc or group['account_id']!=component['account_id'] or group['currency']!=facts.currency:
                fail('full-copy witness ownership differs')
            # Recreate the complete economic key for this witness, including
            # every repeated row, instead of accepting a group label as proof.
            body=json.loads(group['signature'])
            if (body['rows']!=sorted([_row_signature(facts,i,component['account_id']) for i in range(len(facts.activity))],key=canonical)
                    or body['opening']!=key(scalar(basis['opening'])) or body['closing']!=key(scalar(snapshot['cash']))):
                fail('partial/changed source reused full-copy effects')
        if not facts.activity and witnesses and any(_empty_proof(facts,_locale(prefix,doc),scalar(prefix['investment_bases'][(w['basis_id'],)]['opening'])) for w in witnesses):
            fail('empty witness lacks accepted compatible source opening/closing')
        if component['group_id']:
            group=prefix['investment_groups'].get((component['group_id'],))
            if group is None or not any(w['group_id']==group['group_id'] and w['basis_id']==component['basis_id'] for w in witnesses):
                fail('component group/basis association differs')
            active=expected_active.get((group['group_id'],))
            siblings=[g for g in prefix['investment_groups'].values() if g['account_id']==group['account_id'] and g['period_end']==group['period_end']]
            expected='conflicted' if len(siblings)>1 else 'accepted' if active and active['active'] else 'held'
            if component['activity_state']!=expected or component['reason']!=('period_conflict' if len(siblings)>1 else '' if active and active['active'] else 'basis_unavailable'):
                fail('activity state hides required held/reversal outcome')
        else:
            bad_activity=any(f['status']=='conflicted' and f['scope']=='activity' and f['name'] in {'date','kind','amount','reported_realized_gain','security_identifier'} for f in fields.values())
            resource=False
            try:
                for a in facts.activity:
                    posting_precision(a.amount,a.realized_gain)
            except ValueError:
                resource=True
            roots=_roots(prefix,facts_by_doc,component['account_id'],facts.currency)
            opening=facts.opening_cash
            if opening is None and roots:
                candidates=sorted([s for s in prefix['investment_snapshots'].values() if s['account_id']==component['account_id'] and s['currency']==facts.currency and s['doc_id']!=doc],key=lambda s:s['as_of'],reverse=True)
                if candidates and candidates[0]['as_of']<facts.as_of and len({s['cash'] for s in candidates if s['as_of']==candidates[0]['as_of']})==1:
                    opening=scalar(candidates[0]['cash'])
            empty=not facts.activity
            if empty:
                historical=sorted([b for b in prefix['investment_bases'].values() if b['doc_id']==doc
                    and _basis_valid(prefix,facts_by_doc,b,component['account_id'],facts.currency)],
                    key=lambda b:(b['created_revision'],b['known_operation'],b['basis_id']))
                if historical:
                    opening=scalar(historical[0]['opening'])
            empty_reason=_empty_proof(facts,_locale(prefix,doc),opening) if empty else ''
            proved_empty=not empty_reason
            signed=[a.amount if a.kind in {'contribution','dividend','interest','sell'} else negate(a.amount) for a in facts.activity]
            if not bad_activity and not resource and (not empty or proved_empty) and (_root(facts) or roots) and opening is not None and zero_sum([opening,*signed,negate(scalar(snapshot['cash']))]):
                fail('eligible cash group/witness omitted')
            expected_reason=('source_activity_conflict' if bad_activity else 'resource_limit' if resource else empty_reason if empty and not proved_empty else 'seed_unavailable' if not _root(facts) and not roots else 'carry_unavailable' if opening is None else 'activity_arithmetic')
            expected_state='conflicted' if bad_activity or empty_reason=='source_activity_conflict' else 'unavailable' if empty and not proved_empty and not resource else 'held'
            if component['activity_state']!=expected_state or component['reason']!=expected_reason:
                fail('held activity state/reason differs')
    expected_dependencies={}
    for doc,facts in facts_by_doc.items():
        claim_field=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
        claim=SourceAccountIdentity(claim_field.raw if claim_field else '',doc,claim_field.page if claim_field else None,facts.validated_source_page_count)
        signals={('preferred',preferred_account_key(facts.institution,facts.account_number,facts.account_ref))}
        signals.update(('holder',normalize_name(n)) for n in facts.account_names if normalize_name(n))
        if claim.eligible():
            signals.add(('reference',claim.reference))
        number=usable_full_number(facts.account_number)
        if number:
            signals.add(('number',canonical(['investment',number])))
        component=prefix['investment_components'][(doc,)]
        for kind,signal in signals:
            if signal:
                expected_dependencies[(doc,kind,signal)]=dict(doc_id=doc,signal_kind=kind,signal=signal,currency=facts.currency,
                    account_id=component['account_id'] if component['snapshot_id'] else None,active=int(component['snapshot_id'] is None))
    if expected_dependencies!=prefix['investment_dependencies']:
        fail('indexed pending identity closure differs')


def _cash_accounts(prefix,facts_by_doc,before):
    for (account_id,),account in prefix['accounts'].items():
        if account['kind']!='investment':
            continue
        snapshots=[s for s in prefix['investment_snapshots'].values() if s['account_id']==account_id]
        if not snapshots:
            fail('investment account without any genuine population')
        observations=[(s['as_of'],s['cash']) for s in snapshots]
        for _,_,_,basis in _roots(prefix,facts_by_doc,account_id,account['currency']):
            if basis['period_start']:
                observations.append((basis['period_start'],basis['opening']))
        observations.sort()
        first=[v for day,v in observations if day==observations[0][0]]
        last=[v for day,v in observations if day==observations[-1][0]]
        old=before['accounts'].get((account_id,))
        for amount_name,date_name,values,when in [('earliest_amount','earliest_date',first,observations[0][0]),('current_amount','current_date',last,observations[-1][0])]:
            if len(set(values))==1:
                if account[amount_name]!=values[0] or account[date_name]!=when:
                    fail('account contains value instead of independently observed cash')
            elif old is not None and (account[amount_name]!=old[amount_name] or account[date_name]!=old[date_name]):
                fail('conflicted cash replaced its prior measurement')


def _input_signals(operations, facts_by_doc):
    result=set()
    for op in operations:
        table,row=op['table'],op['row']
        if table=='interpretations' and row['facts_type']=='investment':
            facts=facts_by_doc[row['doc_id']]
            result.add(('preferred',preferred_account_key(facts.institution,facts.account_number,facts.account_ref)))
            result.update(('holder',normalize_name(n)) for n in facts.account_names if normalize_name(n))
            number=usable_full_number(facts.account_number)
            if number:result.add(('number',canonical(['investment',number])))
            field=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
            claim=SourceAccountIdentity(field.raw if field else '',facts.doc_id,field.page if field else None,facts.validated_source_page_count)
            if claim.eligible():result.add(('reference',claim.reference))
        elif table=='accounts':
            result.add(('preferred',preferred_account_key(row['institution'],row['number'],row['label'])))
            if row['kind']=='investment' and row['normalized_number']:
                result.add(('number',canonical(['investment',row['normalized_number']])))
        elif table=='account_keys':result.add(('preferred',row['logical_key']))
        elif table=='holder_index':result.add(('holder',row['normalized_name']))
        elif table in {'reference_claims','reference_views'}:result.add(('reference',row['reference']))
        elif table=='identity_decisions':
            body=json.loads(row['body']);raw=body['input']
            result.add(('preferred',preferred_account_key(raw['institution'],raw['account_number'],raw['account_ref'])))
            result.update(('holder',normalize_name(n)) for n in raw['account_names'] if normalize_name(n))
            if body['policy']=='investment_source_reference':
                facts=facts_by_doc[row['doc_id']]
                field=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
                claim=SourceAccountIdentity(field.raw if field else '',facts.doc_id,field.page if field else None,facts.validated_source_page_count)
                if claim.eligible():result.add(('reference',claim.reference))
            elif raw['source_account_ref']:
                result.add(('reference',raw['source_account_ref']))
    return result


def _needs_native_resolver(prefix,facts):
    from ..ledger.identity import canonical_institution,conflicting_number_signals,identity_number_key
    component=prefix['investment_components'].get((facts.doc_id,))
    if component is not None and component['snapshot_id']:
        return False
    number=usable_full_number(facts.account_number)
    if number and number.isascii() and canonical_institution(facts.institution) and not conflicting_number_signals(facts.account_number,facts.account_ref):
        return False
    field=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
    claim=SourceAccountIdentity(field.raw if field else '',facts.doc_id,field.page if field else None,facts.validated_source_page_count)
    if not claim.eligible() or identity_number_key(facts.account_number,facts.account_ref):
        return False
    try:
        cash,positions=_normalized(facts)
        values=[cash,facts.total,*[n for p in positions for n in (p.units,p.market_value)],*[p.cost_basis for p in positions if p.cost_basis is not None]]
        if any(len(display(v).encode())>16384 for v in values) or not zero_sum([p.market_value for p in positions]+[cash,negate(facts.total)]) or len({_security(facts,p.instrument) for p in positions})!=len(positions) or any(not p.instrument.strip() for p in positions):
            return False
    except (ValueError,OverflowError):
        return False
    fields=_fields(facts,_locale(prefix,facts.doc_id))
    return not any(f['status']=='conflicted' and (f['scope']=='header' and f['name'] in {'currency','as_of','period_end','closing_cash'} or f['scope']=='position' and f['name'] in {'identifier','market_value'}) for f in fields.values())


def _required_resolver_attempt(prefix,before,operations,index,doc,facts_by_doc,attempted):
    end=_registration_start(operations,prefix)
    original=operations[:end]
    inputs=[op['row']['doc_id'] for op in original if op['table']=='interpretations' and op['row']['facts_type']=='investment']
    if len(set(inputs))>1:
        fail('one public writer contains multiple first investment inputs')
    signals=_input_signals(original,facts_by_doc)
    # Genuine earlier registrations can expose additional exact indexed signals.
    # Their source is already independently admitted at this operation prefix;
    # an untriggered decision cannot manufacture its own wake-up.
    earlier=[]
    admitted={r['doc_id'] for r in prefix['investment_snapshots'].values()}
    for op in operations[end:index]:
        row=op['row'];table=op['table']
        if table in {'reference_claims','reference_views'} and row.get('doc_id') in admitted:
            earlier.append(op)
        elif table in {'accounts','account_keys','holder_index'}:
            account=row.get('account_id')
            if any(s['account_id']==account and s['doc_id'] in admitted for s in prefix['investment_snapshots'].values()):
                earlier.append(op)
    signals.update(_input_signals(earlier,facts_by_doc))
    pending={r['doc_id'] for r in before['investment_dependencies'].values() if r['active']==1 and (r['signal_kind'],r['signal']) in signals}
    ordered=list(dict.fromkeys(inputs))
    ordered+=sorted(pending-set(ordered),key=lambda d:(prefix['investment_facts'][(d,)]['created_revision'],d))
    needed=[d for d in ordered if d not in attempted and d in facts_by_doc and _needs_native_resolver(prefix,facts_by_doc[d])]
    if not needed or needed[0]!=doc:
        fail('native resolver attempt is unrelated or out of deterministic pending order')
    attempted.add(doc)
    return doc in inputs


def _identity_decision(frontier, operations, index, row, facts_by_doc, revision):
    from dataclasses import asdict
    from ..ledger.projection.accounts import resolve
    from .identity import detached_state
    body=json.loads(row['body'])
    doc=row['doc_id']
    facts=facts_by_doc.get(doc)
    if facts is None or row['created_revision']!=revision or body['input']!=facts.to_dict():
        fail('native resolver input/source/revision differs')
    source=dict(facts.investment_source.headers).get('account_reference') if facts.investment_source else None
    claim=SourceAccountIdentity(source.raw if source else '',doc,source.page if source else None,facts.validated_source_page_count)
    from ..ledger.identity import identity_number_key
    if not claim.eligible() or identity_number_key(facts.account_number,facts.account_ref):
        fail('native source-reference policy has no eligible own source')
    preferred=preferred_account_key(facts.institution,facts.account_number,facts.account_ref)
    holders={normalize_name(name) for name in facts.account_names if name.strip()}
    captured={r['doc_id'] for r in frontier['documents'].values()}
    metadata=[]
    for (account_id,),account in frontier['accounts'].items():
        mapped=frontier['account_keys'].get((account_id,))
        if mapped is None:
            fail('resolver frontier omitted an earlier account key')
        metadata.append({**account,**mapped})
    metadata.sort(key=lambda a:a['creation_order'])
    selected=[]
    for account in metadata:
        positive=any(c['account_id']==account['account_id'] and c['reference']==claim.reference and c['scope']=='account'
            and c['doc_id'] in captured and SourceAccountIdentity(c['reference'],c['doc_id'],c['page'],c['identity_page_count']).eligible()
            for c in frontier['reference_claims'].values())
        overlap=holders.intersection(normalize_name(name) for name in json.loads(account['names']))
        number=usable_full_number(facts.account_number)
        if account['logical_key']==preferred or account['kind']=='investment' and (positive or overlap or number and account['normalized_number']==number):
            selected.append(account)
    mapping={a['logical_key']:a['account_id'] for a in selected}
    logical={a['account_id']:a['logical_key'] for a in selected}
    claims=[{**c,'logical_key':logical[c['account_id']]} for c in frontier['reference_claims'].values() if c['account_id'] in logical]
    detached=detached_state(selected,claims,captured)
    expected=asdict(resolve(detached,facts.institution,facts.account_number,facts.account_ref,facts.account_names,
        kind='investment',doc_id=doc,currency=facts.currency,source_identity=claim))
    if canonical(expected)!=canonical(body['resolution']) or body['logical_to_physical']!=mapping or body['account_order']!=[a['logical_key'] for a in selected]:
        fail('native resolver omitted a rival or used a favorable frontier')
    suffix=operations[body['known_operation']:index]
    physical=body['physical_account']
    if body['promoted'] and expected['verdict']=='new':
        if (physical,) in frontier['accounts'] or not physical or not suffix or suffix[0]['table']!='accounts' or suffix[0]['row']['account_id']!=physical:
            fail('new identity did not create its actual absent physical account')
        account=suffix[0]['row']
        immutable=dict(kind='investment',currency=facts.currency,number=facts.account_number,normalized_number=usable_full_number(facts.account_number),
            institution=facts.institution,label=facts.account_ref,names=canonical(facts.account_names),earliest_amount=display(facts.cash),earliest_date=facts.as_of,current_amount=display(facts.cash),current_date=facts.as_of)
        if any(account[k]!=v for k,v in immutable.items()):
            fail('new identity account metadata differs from genuine source')
        if len(suffix)<2 or suffix[1]['table']!='account_keys':
            fail('new identity lacks its exact registration key suffix')
        key_row=suffix[1]['row']
        occupied=any(k['logical_key']==preferred for k in frontier['account_keys'].values())
        if key_row['account_id']!=physical or key_row['creation_order']!=revision or (not occupied and key_row['logical_key']!=preferred) or (occupied and not key_row['logical_key'].startswith('acct:investment:')):
            fail('new identity logical key/creation order differs')
        expected_holders=[dict(table='holder_index',row=dict(account_id=physical,normalized_name=name)) for name in sorted(holders)]
        if suffix[2:]!=expected_holders:
            fail('native registration suffix is interleaved or has altered holders')
        if len(suffix)!=2+len(expected_holders):
            fail('native registration suffix is not uniquely determined')
    else:
        if suffix or body['known_operation']!=index:
            fail('existing/held resolver used a false earlier frontier')
        if body['promoted']:
            if expected['verdict']!='same' or physical!=mapping.get(expected['account_id']) or (physical,) not in frontier['accounts']:
                fail('same identity promoted a foreign physical account')
        else:
            chosen='' if expected['verdict']=='ambiguous' else mapping.get(expected['account_id'],'')
            if physical!=chosen:
                fail('held identity mapping differs from actual resolution')


def _bootstrap():
    prefix={table:{} for table in TABLES}
    facts_by_doc={};contexts={};source_cache={}
    expected_active={};expected_effects={};expected_legs={};expected_adjustments={}
    previous_decisions={};next_ordinal=1
    interpretation_revisions={}
    return dict(prefix=prefix,facts_by_doc=facts_by_doc,contexts=contexts,source_cache=source_cache,expected_active=expected_active,expected_effects=expected_effects,expected_legs=expected_legs,expected_adjustments=expected_adjustments,previous_decisions=previous_decisions,next_ordinal=next_ordinal,interpretation_revisions=interpretation_revisions)


def _advance(store,checkpoint,revision,operations):
    """Check one authenticated prefix with the full verifier's operation frontiers."""
    prefix=checkpoint['prefix']
    facts_by_doc=checkpoint['facts_by_doc']
    contexts=checkpoint['contexts']
    source_cache=checkpoint['source_cache']
    expected_active=checkpoint['expected_active']
    expected_effects=checkpoint['expected_effects']
    expected_legs=checkpoint['expected_legs']
    expected_adjustments=checkpoint['expected_adjustments']
    previous_decisions=checkpoint['previous_decisions']
    next_ordinal=checkpoint['next_ordinal']
    interpretation_revisions=checkpoint['interpretation_revisions']
    if sum(op['table']=='interpretations' and op['row']['facts_type']=='investment' for op in operations)>1:
        fail('one public writer contains multiple first investment interpretations')
    before={table:dict(values) for table,values in prefix.items()}
    final={table:dict(values) for table,values in prefix.items()}
    for op in operations:
        row=op['row'];table=op['table'];final[table][tuple(row[k] for k in KEYS[table])]=row
    boundary=_cause_boundary(operations,before,final)
    needed={json.loads(op['row']['body'])['known_operation'] for op in operations if op['table']=='identity_decisions' and json.loads(op['row']['body']).get('policy')=='investment_source_reference'}
    frontiers={}
    new_accounts=set();native_creation=False;attempted_native=set()
    for index,op in enumerate(operations):
        if index in needed:
            frontiers[index]={name:dict(values) for name,values in prefix.items()}
        table,row=op['table'],op['row']
        if table=='interpretations' and row['facts_type']=='investment':
            doc=row['doc_id']
            receipt=prefix['receipts'].get((doc,))
            cache_key=(doc,canonical(receipt),row['facts'],row['context'])
            if cache_key not in source_cache:
                source_cache[cache_key]=_source(store,prefix,doc,row)
            facts,context=source_cache[cache_key]
            facts_by_doc[doc]=facts;contexts[doc]=context
            interpretation_revisions.setdefault(doc,revision)
        if table=='investment_facts':
            doc=row['doc_id']
            if (doc,) in prefix['investment_facts'] or interpretation_revisions.get(doc)!=revision or row['created_revision']!=revision or (doc,) not in prefix['interpretations']:
                fail('facts creation revision is not its genuine first interpretation writer')
        if table=='accounts' and (row['account_id'],) not in prefix['accounts']:
            new_accounts.add(row['account_id'])
            native_creation=native_creation or row['kind']=='investment'
            if native_creation and len(new_accounts)>1:
                fail('second physical creation violates actual writer revision uniqueness')
        if table=='identity_decisions' and json.loads(row['body']).get('policy')=='investment_source_reference':
            known=json.loads(row['body'])['known_operation']
            if type(known) is not int or known not in frontiers or known>index:
                fail('native resolver frontier is not actual earlier operation')
            initial=_required_resolver_attempt(frontiers[known],before,operations,known,row['doc_id'],facts_by_doc,attempted_native)
            body=json.loads(row['body'])
            if body['promoted'] and body['resolution']['verdict']=='new' and not initial:
                fail('an already pending source created a second independent physical origin')
            _identity_decision(frontiers[known],operations,index,row,facts_by_doc,revision)
        if table=='investment_bases':
            _basis_creation(prefix,facts_by_doc,row,revision,index)
        elif table=='investment_groups':
            _group(prefix,facts_by_doc,row)
            if row['created_revision']!=revision:
                fail('cash group backdated revision')
        elif table=='investment_decisions':
            if row['ordinal']!=next_ordinal or row['revision']!=revision or row['boundary']!=boundary or not json.loads(boundary)['causes']:
                fail('decision order/revision/input boundary differs')
            group=prefix['investment_groups'].get((row['group_id'],))
            if group is None:
                fail('decision cites a future cash group')
            prior=expected_active.get((row['group_id'],))
            eligible,basis=_desired(prefix,facts_by_doc,group,prior)
            expected_action='activate' if eligible and (prior is None or not prior['active']) else 'deactivate' if not eligible and prior and prior['active'] else 'rebind' if eligible and prior and prior['basis_id']!=basis['basis_id'] else None
            expected_basis=prior['basis_id'] if expected_action=='deactivate' else basis['basis_id'] if basis else None
            if row['action']!=expected_action or row['basis_id']!=expected_basis or row['previous_ordinal']!=previous_decisions.get(row['group_id']):
                fail('activation/reversal/rebind eligibility or prior basis differs')
            if row['action']=='activate' and not any(e['group_id']==row['group_id'] for e in expected_effects.values()):
                effects,legs=_effect_templates(prefix,facts_by_doc,group,basis)
                expected_effects.update(effects);expected_legs.update(legs)
            if row['action']!='rebind':
                for effect in expected_effects.values():
                    if effect['group_id']!=row['group_id']:
                        continue
                    for (effect_id,leg),template in expected_legs.items():
                        if effect_id==effect['effect_id']:
                            value=dict(decision_ordinal=row['ordinal'],**template,date=effect['date'])
                            if row['action']=='deactivate':
                                value['amount']=display(negate(scalar(template['amount'])))
                            expected_adjustments[(row['ordinal'],effect_id,leg)]=value
            expected_active[(row['group_id'],)]=dict(group_id=row['group_id'],active=int(row['action']!='deactivate'),decision_ordinal=row['ordinal'],basis_id=None if row['action']=='deactivate' else row['basis_id'],revision=revision)
            previous_decisions[row['group_id']]=row['ordinal'];next_ordinal+=1
        prefix[table][tuple(row[k] for k in KEYS[table])]=row
    _static(prefix,facts_by_doc,contexts,interpretation_revisions)
    _final_eligibility(prefix,facts_by_doc,expected_active)
    _cash_accounts(prefix,facts_by_doc,before)
    for account_id in new_accounts:
        account=prefix['accounts'][(account_id,)]
        if account['kind']!='investment':
            continue
        first=next((op['row'] for op in operations if op['table']=='investment_snapshots' and op['row']['account_id']==account_id),None)
        if first is None or prefix['investment_facts'][(first['doc_id'],)]['created_revision']!=revision:
            fail('pending or foreign source created an independent new account')
        facts=facts_by_doc[first['doc_id']]
        inserted=next(op['row'] for op in operations if op['table']=='accounts' and op['row']['account_id']==account_id)
        expected=dict(kind='investment',currency=facts.currency,number=facts.account_number,normalized_number=usable_full_number(facts.account_number),institution=facts.institution,label=facts.account_ref,names=canonical(facts.account_names),earliest_amount=display(facts.cash),earliest_date=facts.as_of,current_amount=display(facts.cash),current_date=facts.as_of)
        if any(inserted[k]!=v for k,v in expected.items()):
            fail('native account creation metadata is not source-owned')
    if prefix['investment_active']!=expected_active or prefix['investment_effects']!=expected_effects or prefix['investment_legs']!=expected_legs or prefix['investment_adjustments']!=expected_adjustments:
        fail('immutable effect multiplicity/current pointers/signed history differs')
    checkpoint['next_ordinal']=next_ordinal
    return checkpoint


def _finish(checkpoint,state):
    prefix=checkpoint['prefix']
    if any(prefix[table]!=state[table] for table in TABLES if table.startswith('investment_')):
        fail('final investment representation differs from audited prefixes')


def _verify_prefixes(store,state,export):
    checkpoint=_bootstrap()
    for revision,previous,envelope,_digest in export['records']:
        payload=json.loads(open_sealed(store._audit_key,json.loads(envelope),aad=canonical([revision,previous]).encode()))
        _advance(store,checkpoint,revision,payload['operations'])
    _finish(checkpoint,state)
    return checkpoint


def verify(store,state,export):
    checkpoint=_verify_prefixes(store,state,export)
    collector=getattr(store,'_semantic_collection',None)
    if collector is not None:collector['investment']=checkpoint
