"""Indexed payroll intake and deposit explanation inside the causal SQL writer."""
from datetime import date
from decimal import Decimal, localcontext, Inexact
import hashlib
import json

from ..ingest.paystub import PayStubFacts, Deduction, CATEGORIES
from ..ledger.identity import normalize_name
from ..ledger.postings import paystub_decomposition
from ..ingest.cash_source_pages import payroll_decomposition_page
from vivacore.verify.arithmetic import check_paystub_identity
from .schema import supported_amount
from .store import canonical, AuthorityError, MAX_RECEIPT_BYTES
from .bank import amount_key

CAUSE_TABLES = {'interpretations','transactions','transfer_bindings','transfer_members'}


def capture_types(facts):
    from ..investment.payroll_extraction import PayrollSourceExtraction
    from ..retirement_funding.payroll_v2 import PayrollSourceExtractionV2
    deductions = (type(facts) is PayStubFacts and type(facts.deductions) is list
                  and all(type(d) is Deduction for d in facts.deductions))
    decimals = (deductions and type(facts.gross) is Decimal and type(facts.net) is Decimal
                and all(type(d.amount) is Decimal for d in facts.deductions))
    source = type(facts) is PayStubFacts and (facts.payroll_source is None or type(facts.payroll_source) in {PayrollSourceExtraction, PayrollSourceExtractionV2})
    names = type(facts.employee_names) is list and all(type(n) is str for n in facts.employee_names)
    acquisition = facts.acquisition is None or type(facts.acquisition) is dict
    return {'payroll': type(facts) is PayStubFacts and source and names and acquisition,
            'deductions': deductions, 'decimals': decimals}


def decode(value, tags=None):
    """Validate retained scalar shapes before reconstructing exact typed facts."""
    fields = {'doc_id','doc_type','doc_type_confidence','employer','currency','pay_date',
              'period_start','period_end','gross','net','deductions','employee_names','gross_page','net_page'}
    if type(value) is not dict or set(value)-fields-{'acquisition','payroll_source','validated_source_page_count'} or not fields <= set(value):
        raise ValueError('closed payroll facts required')
    if tags is not None and (type(tags) is not dict or set(tags)!={'payroll','deductions','decimals','read_context_id'} or any(tags[k] is not True for k in ('payroll','deductions','decimals'))):
        raise ValueError('exact payroll capture types required')
    for key in ('doc_id','doc_type','employer','currency','pay_date','period_start','period_end','gross','net'):
        if type(value[key]) is not str or len(value[key].encode())>4096:
            raise ValueError('typed payroll text required')
    if len(value['doc_id'])!=64 or any(c not in '0123456789abcdef' for c in value['doc_id']):
        raise ValueError('payroll source address required')
    if value['doc_type']!='pay_stub':
        raise ValueError('payroll classification differs')
    confidence=value['doc_type_confidence']
    if confidence is not None and (type(confidence) not in {int,float} or not 0 <= confidence <= 1):
        raise ValueError('payroll classification confidence invalid')
    if len(value['currency'])!=3 or not value['currency'].isascii() or not value['currency'].isalpha():
        raise ValueError('payroll currency invalid')
    for key in ('pay_date','period_start','period_end'):
        if key!='pay_date' and value[key]=='':
            continue
        if date.fromisoformat(value[key]).isoformat()!=value[key]:
            raise ValueError('payroll date invalid')
    if value['period_start'] and value['period_end'] and value['period_start']>value['period_end']:
        raise ValueError('payroll period reversed')
    count=value.get('validated_source_page_count')
    if count is not None and (type(count) is not int or not 1 <= count <= 200):
        raise ValueError('validated payroll source page count invalid')
    for key in ('gross_page','net_page'):
        if value[key] is not None and (type(value[key]) is not int or not 1 <= value[key] <= 200):
            raise ValueError('payroll page invalid')
    if type(value['employee_names']) is not list or len(value['employee_names'])>100 or any(type(n) is not str or len(n.encode())>4096 for n in value['employee_names']):
        raise ValueError('payroll employee names invalid')
    if type(value['deductions']) is not list or len(value['deductions'])>10000:
        raise ValueError('payroll deductions invalid')
    amounts=[value['gross'],value['net']]
    for deduction in value['deductions']:
        if type(deduction) is not dict or set(deduction)!={'label','amount','category'}:
            raise ValueError('payroll deduction shape invalid')
        if type(deduction['label']) is not str or len(deduction['label'].encode())>4096 or type(deduction['category']) is not str or deduction['category'] not in CATEGORIES or type(deduction['amount']) is not str:
            raise ValueError('payroll deduction scalar invalid')
        if Decimal(deduction['amount']) < 0:
            raise ValueError('payroll deductions are positive magnitudes')
        amounts.append(deduction['amount'])
    for raw in amounts:
        if len(raw)>128 or not raw.isascii() or raw!=raw.strip() or not supported_amount(Decimal(raw)):
            raise ValueError('payroll amount invalid')
    from ..investment.payroll_extraction import parse
    source=parse(value.get('payroll_source'))
    facts=PayStubFacts(value['doc_id'],value['doc_type'],confidence,value['employer'],value['currency'],
        value['pay_date'],value['period_start'],value['period_end'],Decimal(value['gross']),Decimal(value['net']),
        [Deduction(d['label'],Decimal(d['amount']),d['category']) for d in value['deductions']],
        list(value['employee_names']),value['gross_page'],value['net_page'],source,value.get('acquisition'),count)
    if len(canonical(facts.to_dict()).encode())>MAX_RECEIPT_BYTES:
        raise ValueError('payroll facts exceed receipt bound')
    return facts


def identity_passes(facts):
    with localcontext() as context:
        context.prec=28
        context.traps[Inexact]=True
        return check_paystub_identity(facts.gross,[d.amount for d in facts.deductions],facts.net).passed


def signature(facts, movement):
    return canonical({'version':1,'movement':movement,'employer':normalize_name(facts.employer),
        'employee_names':sorted(normalize_name(n) for n in facts.employee_names),
        'pay_date':facts.pay_date,'period_start':facts.period_start,'period_end':facts.period_end,
        'currency':facts.currency,'gross':amount_key(facts.gross),'net':amount_key(facts.net),
        'deductions':[{'label':d.label,'category':d.category,'amount':amount_key(d.amount)} for d in facts.deductions]})


def bounds(day):
    value=date.fromisoformat(day)
    low=date.fromordinal(max(date.min.toordinal(),value.toordinal()-10))
    high=date.fromordinal(min(date.max.toordinal(),value.toordinal()+10))
    return low.isoformat(),high.isoformat()


def rows(store, table, where='1', parameters=(), order=None):
    from .schema import TABLES
    columns=TABLES[table]
    suffix=(' ORDER BY '+order) if order else ''
    return [dict(zip(columns,r)) for r in store._read('SELECT '+','.join(columns)+' FROM '+table+' WHERE '+where+suffix,parameters)]


def candidates(store, facts):
    if facts.net<=0:
        return []
    low,high=bounds(facts.pay_date)
    return [dict(zip(('movement','txn_id','physical_account','doc_id','date'),row)) for row in store._read(
        "SELECT b.movement,b.txn_id,b.physical_account,b.doc_id,b.date FROM transfer_endpoints e JOIN transfer_bindings b ON b.movement=e.movement JOIN accounts a ON a.account_id=b.physical_account LEFT JOIN transfer_members m ON m.movement=b.movement WHERE e.currency=? AND e.magnitude=? AND e.flow='destination' AND e.date>=? AND e.date<=? AND a.kind='depository' AND (m.movement IS NULL OR m.active=0) ORDER BY b.movement",
        (facts.currency,amount_key(facts.net),low,high))]


def intake(store, interpretation):
    facts=decode(json.loads(interpretation['facts']))
    doc=facts.doc_id
    receipt=store._row('receipts','doc_id=?',(doc,))
    tags=json.loads(receipt['capture_types'])
    context_id=tags['read_context_id']
    store._put('payroll_facts',dict(doc_id=doc,currency=facts.currency,pay_date=facts.pay_date,
        period_start=facts.period_start,period_end=facts.period_end,gross=str(facts.gross),net=str(facts.net),
        net_key=amount_key(facts.net),body=canonical(facts.to_dict()),context_id=context_id,
        source_kind='curated' if receipt['facts_type']=='curated' else 'typed'))
    store._put('payroll_dependencies',dict(doc_id=doc,currency=facts.currency,net_key=amount_key(facts.net),pay_date=facts.pay_date,active=int(identity_passes(facts))))
    # The writer's closure supplies accepted/ambiguous state after all transfer
    # changes in this same transaction are visible.
    if store._row('payroll_components','doc_id=?',(doc,)) is None:
        store._item(doc,'pending','awaiting_deposit')


def causes(operations, binding_lookup):
    found={}
    from .schema import KEYS
    for operation in operations:
        table,row=operation['table'],operation['row']
        if table not in CAUSE_TABLES:
            continue
        key=row[KEYS[table][0]]
        if table=='interpretations':
            source=key
        elif table=='transfer_members':
            binding=binding_lookup(row['movement'])
            if binding is None:
                raise AuthorityError('payroll cause has no authenticated movement')
            source=binding['doc_id']
        else:
            source=row['doc_id']
        found[(table,key)]={'table':table,'key':key,'source_doc_id':source}
    return [found[key] for key in sorted(found)]


def _affected(store, operations):
    from .transfers import immutable_row, remember
    by_transaction={}; conflicts=set()
    cached=store._transfer_facts
    bindings=[] if cached is None else [row for row in cached['transfer_bindings'].values() if row is not None]
    bindings.extend(op['row'] for op in store._operations or () if op['table']=='transfer_bindings')
    for binding in bindings:
        txn=binding['txn_id']
        if txn in by_transaction and by_transaction[txn] != binding:
            conflicts.add(txn)
        else:
            by_transaction[txn]=dict(binding)
    affected=set(); movements=set(); queue=[]
    for operation in operations:
        table,row=operation['table'],operation['row']
        if table=='interpretations' and row['facts_type']=='payroll':
            affected.add(row['doc_id']);queue.append(row['doc_id'])
        elif table=='transfer_bindings':
            movements.add(row['movement'])
        elif table=='transfer_members':
            movements.add(row['movement'])
        elif table=='transactions':
            txn=row['txn_id']
            binding=by_transaction.get(txn) if txn not in conflicts else None
            selected=[binding] if binding is not None else rows(store,'transfer_bindings','txn_id=?',(txn,))
            for binding in selected:
                remember(store,'transfer_bindings',binding['movement'],dict(binding))
                movements.add(binding['movement'])
    def add_near(binding):
        info=immutable_row(store,'transfer_inventory',binding['account'])
        if info is None or info['kind']!='depository' or Decimal(binding['amount'])<=0:
            return
        low,high=bounds(binding['date'])
        for (doc,) in store._read('SELECT doc_id FROM payroll_dependencies WHERE currency=? AND net_key=? AND pay_date>=? AND pay_date<=? AND active=1 ORDER BY doc_id',(info['currency'],amount_key(binding['amount']),low,high)):
            if doc not in affected:
                affected.add(doc);queue.append(doc)
    for movement in sorted(movements):
        binding=immutable_row(store,'transfer_bindings',movement)
        if binding is not None:
            add_near(binding)
    seen=set()
    while queue:
        doc=queue.pop()
        if doc in seen:
            continue
        seen.add(doc)
        fact=store._row('payroll_facts','doc_id=?',(doc,))
        if fact is None:
            continue
        typed=decode(json.loads(fact['body']))
        for candidate in candidates(store,typed):
            add_near(immutable_row(store,'transfer_bindings',candidate['movement']))
    return sorted(affected)


def close_writer(store):
    operations=tuple(store._operations)
    if not any(op['table'] in CAUSE_TABLES for op in operations):
        return
    docs=_affected(store,operations)
    if not docs:
        return
    boundary=canonical({'version':1,'causes':causes(operations,lambda key:store._row('transfer_bindings','movement=?',(key,)))})
    wanted={}; selections={}; facts_by_doc={}
    for doc in docs:
        fact=store._row('payroll_facts','doc_id=?',(doc,));typed=decode(json.loads(fact['body']));facts_by_doc[doc]=typed
        choices=candidates(store,typed) if identity_passes(typed) else []
        selections[doc]=choices
        if len(choices)==1:
            body=signature(typed,choices[0]['movement']);eid=hashlib.sha256(body.encode()).hexdigest()
            wanted[doc]=(eid,body,choices[0])
    movement_signatures={}
    # The affected closure includes every competing claim of every selected
    # movement. Multiple candidates never choose an arbitrary first deposit.
    for doc,choices in selections.items():
        for choice in choices:
            body=signature(facts_by_doc[doc],choice['movement'])
            movement_signatures.setdefault(choice['movement'],set()).add(body)
    desired=set(); components={}
    for doc in docs:
        facts=facts_by_doc[doc];choices=selections[doc]
        state='arithmetic_conflict' if not identity_passes(facts) else 'awaiting_deposit' if not choices else 'ambiguous'
        eid=None;physical=None
        if doc in wanted:
            candidate_id,body,choice=wanted[doc]
            explanation=store._row('payroll_explanations','explanation_id=?',(candidate_id,))
            if explanation is None:
                explanation=dict(explanation_id=candidate_id,movement=choice['movement'],txn_id=choice['txn_id'],source_doc=doc,
                    currency=facts.currency,pay_date=facts.pay_date,gross=str(facts.gross),net=str(facts.net),signature=body)
                store._put('payroll_explanations',explanation)
                event=paystub_decomposition(facts.gross,facts.net,facts.deductions,'',facts.pay_date)
                source_page=payroll_decomposition_page(facts) if facts.validated_source_page_count is not None else None
                for leg,posting in enumerate(event.body['postings']):
                    store._put('payroll_legs',dict(explanation_id=candidate_id,leg=leg,account_id=posting['account'],amount=posting['amount'],currency=facts.currency,grade=posting['grade'],doc_id=doc,page=(source_page if facts.validated_source_page_count is not None else facts.gross_page if leg==0 else facts.net_page if leg==1 else None)))
            store._put('payroll_witnesses',dict(doc_id=doc,explanation_id=candidate_id))
            if len(movement_signatures[choice['movement']])==1:
                eid=candidate_id;physical=choice['physical_account'];desired.add(eid)
                state='accepted' if explanation['source_doc']==doc else 'duplicate'
        components[doc]=(state,eid,physical)
    relevant=set(desired)
    for doc in docs:
        prior=store._row('payroll_components','doc_id=?',(doc,))
        if prior is not None and prior['explanation_id']:
            relevant.add(prior['explanation_id'])
        for witness in rows(store,'payroll_witnesses','doc_id=?',(doc,)):
            relevant.add(witness['explanation_id'])
    transitions=[]
    for eid in sorted(relevant):
        active=store._row('payroll_active','explanation_id=?',(eid,))
        if bool(active and active['active']) != (eid in desired):
            transitions.append((eid in desired,eid))
    # Retire first so the partial unique movement constraint also holds while
    # replacing the effective explanation inside this transaction.
    for activation,eid in sorted(transitions):
        ordinal=store._read('SELECT COALESCE(MAX(ordinal),0)+1 FROM payroll_decisions')[0][0]
        explanation=store._row('payroll_explanations','explanation_id=?',(eid,))
        store._put('payroll_decisions',dict(ordinal=ordinal,explanation_id=eid,action='activate' if activation else 'deactivate',revision=store._revision,boundary=boundary))
        store._put('payroll_active',dict(explanation_id=eid,movement=explanation['movement'],active=int(activation),decision_ordinal=ordinal,revision=store._revision))
    for doc,(state,eid,physical) in components.items():
        reason='' if state in {'accepted','duplicate'} else state
        prior=store._row('payroll_components','doc_id=?',(doc,))
        row=dict(doc_id=doc,state=state,reason=reason,explanation_id=eid,account_id=physical,revision=store._revision)
        if prior is not None and all(prior[k]==row[k] for k in row if k!='revision'):
            continue
        store._put('payroll_components',row)
        store._item(doc,'accepted' if eid else 'pending',reason,physical or '')


def fact_view(store,doc_id):
    row=store._row('payroll_facts','doc_id=?',(doc_id,))
    return json.loads(row['body']) if row else None


def component_view(store,doc_id):
    return store._row('payroll_components','doc_id=?',(doc_id,))


def decisions_view(store,doc_id):
    return [dict(row,boundary=json.loads(row['boundary'])) for row in rows(store,'payroll_decisions',
        'explanation_id IN (SELECT explanation_id FROM payroll_witnesses WHERE doc_id=?)',(doc_id,),order='ordinal')]


def posting_view(store,doc_id):
    if doc_id is None:
        selected=[r[0] for r in store._read('SELECT explanation_id FROM payroll_active WHERE active=1 ORDER BY explanation_id')]
    else:
        component=component_view(store,doc_id)
        selected=[component['explanation_id']] if component and component['state'] in {'accepted','duplicate'} else []
    result=[]
    for eid in selected:
        for row in rows(store,'payroll_legs','explanation_id=?',(eid,),order='leg'):
            result.append(dict(row,account=row['account_id'],provenance={'doc_id':row['doc_id'],'page':row['page'],'region':'','note':''}))
    return result
