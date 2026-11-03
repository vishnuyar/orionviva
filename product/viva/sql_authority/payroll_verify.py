"""Independent complete payroll verification at every authenticated audit prefix."""
from decimal import Decimal, localcontext, Inexact, InvalidOperation
from datetime import date
import hashlib
import json

from ..crypto import open_sealed
from ..ingest.paystub import from_paystub_json
from ..ledger.identity import normalize_name
from ..ledger.postings import paystub_decomposition
from vivacore.verify.arithmetic import check_paystub_identity
from vivacore.verify import normalize
from .store import canonical, IntegrityError
from .schema import KEYS, TABLES, FORMAT, SCHEMA_VERSION
from .bank import amount_key
from .payroll import decode


def _fail(message):
    raise IntegrityError('payroll semantic mismatch: '+message)


def _signature(facts,movement):
    value={'version':1,'movement':movement,'employer':normalize_name(facts.employer),
        'employee_names':sorted(normalize_name(n) for n in facts.employee_names),
        'pay_date':facts.pay_date,'period_start':facts.period_start,'period_end':facts.period_end,
        'currency':facts.currency,'gross':amount_key(facts.gross),'net':amount_key(facts.net),
        'deductions':[{'label':d.label,'category':d.category,'amount':amount_key(d.amount)} for d in facts.deductions]}
    return canonical(value)


def _arithmetic(facts):
    with localcontext() as arithmetic:
        arithmetic.prec=28;arithmetic.traps[Inexact]=True
        return check_paystub_identity(facts.gross,[d.amount for d in facts.deductions],facts.net).passed


def _source(store,prefix,doc,interpretation):
    receipt=prefix['receipts'].get((doc,))
    if receipt is None:
        _fail('payroll interpretation has no receipt')
    reading=json.loads(receipt['body']);tags=json.loads(receipt['capture_types'])
    context_id=tags.get('read_context_id') if type(tags) is dict else None
    captured=prefix['read_contexts'].get((context_id,))
    if captured is None or hashlib.sha256(captured['body'].encode()).hexdigest()!=context_id:
        _fail('payroll read context missing')
    context=json.loads(captured['body'])
    from .reading import profile_descriptor
    from ..ingest.registry import profile_for
    profile=profile_for(reading['doc_type']) if type(reading.get('doc_type')) is str else None
    valid_context=(context.get('format')==FORMAT and type(context.get('schema_version')) is int
        and context['schema_version']==SCHEMA_VERSION and context.get('implementation')==store._implementation_identity
        and context.get('normalization_rules_version')==normalize.RULES_VERSION
        and context.get('profiles',{}).get('pay_stub')==profile_descriptor(profile))
    metadata_valid=(all(type(reading.get(k)) is str for k in ('doc_type','raw_text','source_locale'))
        and (reading.get('error') is None or type(reading.get('error')) is str))
    normalized=None
    try:
        if receipt['facts_type']=='curated':
            from .curated import derive
            facts,occurrences=derive(store,receipt,reading)
            if facts is not None and facts.doc_type=='pay_stub' and not occurrences:
                normalized=decode(facts.to_dict())
        else:
            raw_facts=json.loads(receipt['facts'])
            if canonical(raw_facts)!=canonical(reading.get('facts')):
                raise ValueError('retained payroll wire facts differ')
            normalized=decode(raw_facts,tags)
            if normalized.doc_id!=doc or reading.get('doc_type')!='pay_stub' or reading.get('error'):
                normalized=None
            elif reading.get('raw_text'):
                facts,error=from_paystub_json(reading['raw_text'],doc,reading['source_locale'],normalized.currency)
                if facts is None or error:
                    normalized=None
                else:
                    expected,actual=normalized.to_dict(),facts.to_dict()
                    for key in ('doc_type_confidence','acquisition'):
                        expected.pop(key,None);actual.pop(key,None)
                    if expected!=actual:
                        normalized=None
    except (ValueError,TypeError,KeyError,OverflowError,InvalidOperation):
        normalized=None
    if not valid_context or not metadata_valid:
        normalized=None
    if normalized is not None:
        old_profile=context['profiles']['pay_stub']
        expected_context={'format':context.get('format'),'schema_version':context.get('schema_version'),
            'implementation':context.get('implementation'),'normalization_rules_version':context.get('normalization_rules_version'),
            'profile_version':old_profile.get('profile_version'),'profile_identity':old_profile.get('identity'),
            'profile_kind':old_profile.get('account_kind'),'profile_descriptor':old_profile}
        if interpretation['context']!=canonical(expected_context):
            _fail('payroll interpretation context differs from captured contract')
        if interpretation['facts_type']!='payroll' or interpretation['facts']!=canonical(normalized.to_dict()):
            _fail('valid retained payroll interpretation omitted or changed')
    elif interpretation['facts_type']=='payroll':
        _fail('payroll source not independently admitted')
    return normalized,context_id


def _candidates(prefix,facts):
    found=[]
    if facts.net<=0:
        return found
    when=date.fromisoformat(facts.pay_date)
    for binding in prefix['transfer_bindings'].values():
        account=prefix['accounts'].get((binding['physical_account'],))
        transaction=prefix['transactions'].get((binding['txn_id'],))
        member=prefix['transfer_members'].get((binding['movement'],))
        if account is None or transaction is None:
            _fail('deposit ownership missing')
        if (transaction['doc_id'],transaction['account_id'],transaction['amount'],transaction['date'])!=(binding['doc_id'],binding['physical_account'],binding['amount'],binding['date']):
            _fail('deposit binding differs from financial transaction')
        if (account['kind']=='depository' and account['currency']==facts.currency
                and Decimal(binding['amount'])==facts.net and (member is None or member['active']==0)
                and abs((date.fromisoformat(binding['date'])-when).days)<=10):
            found.append(binding)
    return sorted(found,key=lambda r:r['movement'])


def _causes(ops,prefix):
    values={}
    for operation in ops:
        table,row=operation['table'],operation['row']
        if table not in {'interpretations','transactions','transfer_bindings','transfer_members'}:
            continue
        key=row[KEYS[table][0]]
        if table=='interpretations':
            source=key
        elif table=='transfer_members':
            binding=prefix['transfer_bindings'].get((row['movement'],))
            if binding is None:
                _fail('causal movement missing')
            source=binding['doc_id']
        else:
            source=row['doc_id']
        values[(table,key)]={'table':table,'key':key,'source_doc_id':source}
    return [values[k] for k in sorted(values)]


def verify(store,state,export):
    prefix={table:{} for table in TABLES}
    expected={table:{} for table in TABLES if table.startswith('payroll_')}
    effective=set();ordinal=0
    for revision,previous,envelope,_digest in export['records']:
        payload=json.loads(open_sealed(store._audit_key,json.loads(envelope),aad=canonical([revision,previous]).encode()))
        operations=payload['operations']
        for operation in operations:
            table,row=operation['table'],operation['row']
            prefix[table][tuple(row[k] for k in KEYS[table])]=row
        facts_by_doc={}
        for (doc,),interpretation in prefix['interpretations'].items():
            receipt=prefix['receipts'].get((doc,))
            if receipt is None:
                continue
            reading=json.loads(receipt['body'])
            is_payroll=(receipt['facts_type']=='payroll' or receipt['facts_type']=='curated' and reading.get('doc_type')=='pay_stub')
            if not is_payroll:
                if interpretation['facts_type']=='payroll':
                    _fail('foreign payroll interpretation')
                continue
            facts,context_id=_source(store,prefix,doc,interpretation)
            if facts is None:
                continue
            facts_by_doc[doc]=facts
            row=dict(doc_id=doc,currency=facts.currency,pay_date=facts.pay_date,period_start=facts.period_start,
                period_end=facts.period_end,gross=str(facts.gross),net=str(facts.net),net_key=amount_key(facts.net),
                body=canonical(facts.to_dict()),context_id=context_id,source_kind='curated' if receipt['facts_type']=='curated' else 'typed')
            expected['payroll_facts'][(doc,)]=row
            expected['payroll_dependencies'][(doc,)]=dict(doc_id=doc,currency=facts.currency,net_key=amount_key(facts.net),pay_date=facts.pay_date,active=int(_arithmetic(facts)))
        choices={doc:_candidates(prefix,facts) if _arithmetic(facts) else [] for doc,facts in facts_by_doc.items()}
        signatures={}
        for doc,found in choices.items():
            for binding in found:
                signatures.setdefault(binding['movement'],set()).add(_signature(facts_by_doc[doc],binding['movement']))
        desired=set();components={}
        for doc in sorted(facts_by_doc):
            facts=facts_by_doc[doc];found=choices[doc]
            status='arithmetic_conflict' if not _arithmetic(facts) else 'awaiting_deposit' if not found else 'ambiguous'
            eid=None;physical=None
            if len(found)==1:
                binding=found[0];body=_signature(facts,binding['movement']);candidate=hashlib.sha256(body.encode()).hexdigest()
                if (candidate,) not in expected['payroll_explanations']:
                    explanation=dict(explanation_id=candidate,movement=binding['movement'],txn_id=binding['txn_id'],source_doc=doc,
                        currency=facts.currency,pay_date=facts.pay_date,gross=str(facts.gross),net=str(facts.net),signature=body)
                    expected['payroll_explanations'][(candidate,)]=explanation
                    event=paystub_decomposition(facts.gross,facts.net,facts.deductions,'',facts.pay_date)
                    if sum((Decimal(p['amount']) for p in event.body['postings']),Decimal(0))!=0:
                        _fail('unbalanced payroll decomposition')
                    for leg,posting in enumerate(event.body['postings']):
                        expected['payroll_legs'][(candidate,leg)]=dict(explanation_id=candidate,leg=leg,account_id=posting['account'],amount=posting['amount'],currency=facts.currency,grade=posting['grade'],doc_id=doc,page=facts.gross_page if leg==0 else facts.net_page if leg==1 else None)
                expected['payroll_witnesses'][(doc,candidate)]=dict(doc_id=doc,explanation_id=candidate)
                if len(signatures[binding['movement']])==1:
                    eid=candidate;physical=binding['physical_account'];desired.add(eid)
                    owner=expected['payroll_explanations'][(eid,)]['source_doc']
                    status='accepted' if owner==doc else 'duplicate'
            prior=expected['payroll_components'].get((doc,))
            row=dict(doc_id=doc,state=status,reason='' if eid else status,explanation_id=eid,account_id=physical,revision=revision)
            if prior is not None and all(prior[k]==row[k] for k in row if k!='revision'):
                row=prior
            components[(doc,)]=row
        transitions=[(eid in desired,eid) for eid in effective.symmetric_difference(desired)]
        boundary=canonical({'version':1,'causes':_causes(operations,prefix)})
        for activation,eid in sorted(transitions):
            if not json.loads(boundary)['causes']:
                _fail('financial change without authenticated causal input')
            ordinal+=1
            explanation=expected['payroll_explanations'][(eid,)]
            expected['payroll_decisions'][(ordinal,)]=dict(ordinal=ordinal,explanation_id=eid,action='activate' if activation else 'deactivate',revision=revision,boundary=boundary)
            expected['payroll_active'][(eid,)]=dict(explanation_id=eid,movement=explanation['movement'],active=int(activation),decision_ordinal=ordinal,revision=revision)
        expected['payroll_components']=components
        effective=desired
        for table,rows in expected.items():
            if prefix[table]!=rows:
                _fail('authenticated prefix differs: '+table+' at revision '+str(revision))
        for (doc,),component in components.items():
            item=prefix['items'].get((doc,))
            if item is None or item['state']!=('accepted' if component['explanation_id'] else 'pending') or item['account_id']!=(component['account_id'] or '') or item['reason']!=component['reason'] or item['revision']!=component['revision']:
                _fail('payroll item does not match effective component')
    for table,rows in expected.items():
        if state[table]!=rows:
            _fail('current payroll view differs: '+table)
