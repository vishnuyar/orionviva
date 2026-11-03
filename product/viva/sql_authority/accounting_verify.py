"""Independent income/expense composition from authenticated native state."""
import hashlib
from decimal import localcontext,Inexact

from viva.ledger.streams import money_effect

from .accounting_numbers import SCHEMA,LIMITATIONS,TOTALS,amount,total,period,json_value
from .investment_numbers import display
from .store import IntegrityError,canonical


def verify(store,report,*,start,end):
    if not store._db.in_transaction or not store._verified_operation or store._verification!='complete':
        raise IntegrityError('income/expense oracle requires the held complete decision')
    period(start,end)
    export=store._export_current()
    state=store._reconstruct(export,{'revision':export['revision'],'head':export['head']})
    latest=[r['date'] for r in state['transactions'].values()]+[r['pay_date'] for r in state['payroll_explanations'].values()]+[r['date'] for r in state['investment_effects'].values()]
    end=end or max(latest,default='')
    period(start,end)
    def included(day):return (not start or day>=start) and (not end or day<=end)
    lines=[];suppressed=[]
    bindings={row['txn_id']:row for row in state['transfer_bindings'].values()}
    reservations={}
    for active in state['payroll_active'].values():
        if not active['active']:continue
        if active['movement'] in reservations:raise IntegrityError('income/expense payroll reservation duplicated')
        reservations[active['movement']]=active['explanation_id']
    live={}
    for pair in state['transfer_pairs'].values():
        if pair['status']!='linked':continue
        endpoints={row['movement'] for row in state['transfer_members'].values() if row['active'] and (row['a'],row['b'])==(pair['a'],pair['b'])}
        if endpoints!={pair['a'],pair['b']}:raise IntegrityError('income/expense authenticated pair ownership differs')
        for endpoint in endpoints:
            if endpoint in reservations:raise IntegrityError('income/expense authenticated reservations overlap')
            live[endpoint]=[pair['a'],pair['b']]
    def append(domain,identity,posting,day,physical,doc,occurrence,fields,relations,economic=None):
        category=posting['account_id'];root=None
        if category.startswith('Income:'):root='income'
        if category.startswith('Expenses:'):root='expenses'
        if root is None:return
        value=amount(posting['amount'])
        if value.is_zero():return
        if domain=='bank':
            if economic is None:raise IntegrityError('income/expense authenticated bank economic amount unavailable')
            value=economic if root=='income' else economic.copy_negate()
        elif root=='income':value=value.copy_negate()
        if (doc,) not in state['documents'] or (physical,) not in state['accounts']:
            raise IntegrityError('income/expense authenticated source ownership unavailable')
        line_id=hashlib.sha256(canonical(['sql-income-expense-line-v1',domain,identity,posting['leg']]).encode()).hexdigest()
        lines.append(dict(line_id=line_id,domain=domain,effect_id=identity,leg=posting['leg'],date=day,account_id=physical,
            currency=posting['currency'],root=root,category=category,amount=display(value),provisional=domain=='bank',
            amount_evidence={'native_posting':dict(posting),'source_doc':doc,'source_occurrence':occurrence,'source_fields':fields},
            classification_evidence={'by':'provisional' if domain=='bank' else 'document',
                'reason':{'bank':'native_default','payroll':'native_payroll_decomposition','investment':'native_investment_posting'}[domain],
                'related_effects':[{'domain':d,'effect_id':e} for d,e in sorted(set(relations))]}))
    for transaction in state['transactions'].values():
        if not included(transaction['date']):continue
        binding=bindings.get(transaction['txn_id'])
        account=state['accounts'].get((transaction['account_id'],))
        source=state['staged_statements'].get((transaction['doc_id'],))
        if (account is None or account['kind'] not in {'depository','liability'} or source is None or
            source['kind']!=account['kind'] or source['currency']!=account['currency'] or
            binding is None or binding['physical_account']!=transaction['account_id'] or
            binding['doc_id']!=transaction['doc_id'] or binding['date']!=transaction['date'] or binding['amount']!=transaction['amount']):
            raise IntegrityError('income/expense authenticated bank source kind or association differs')
        movement=binding['movement']
        if movement in live or movement in reservations:
            suppressed.append({'txn_id':transaction['txn_id'],'doc_id':transaction['doc_id'],
                'reason':'live_transfer' if movement in live else 'payroll_decomposition',
                'relationship':live[movement] if movement in live else reservations[movement]})
            continue
        with localcontext() as arithmetic:
            arithmetic.prec=28;arithmetic.Emax=999999;arithmetic.Emin=-999999;arithmetic.traps[Inexact]=True
            economic=money_effect(account['kind'],amount(transaction['amount']))
        for posting in state['postings'].values():
            if posting['txn_id']!=transaction['txn_id']:continue
            if posting['doc_id']!=transaction['doc_id'] or posting['currency']!=account['currency']:
                raise IntegrityError('income/expense authenticated bank source differs')
            occurrence=state['source_occurrences'].get((transaction['doc_id'],transaction['line_index']))
            append('bank',transaction['txn_id'],posting,transaction['date'],transaction['account_id'],transaction['doc_id'],occurrence,[],[('bank',transaction['txn_id'])],economic)
    for movement,explanation_id in reservations.items():
        explanation=state['payroll_explanations'].get((explanation_id,))
        binding=state['transfer_bindings'].get((movement,))
        if explanation is None or binding is None or explanation['movement']!=movement or explanation['txn_id']!=binding['txn_id']:
            raise IntegrityError('income/expense authenticated payroll association differs')
        if not included(explanation['pay_date']):continue
        for posting in state['payroll_legs'].values():
            if posting['explanation_id']!=explanation_id or posting['account_id']=='Income:Uncategorized':continue
            if posting['doc_id']!=explanation['source_doc']:raise IntegrityError('income/expense authenticated payroll source differs')
            append('payroll',explanation_id,posting,explanation['pay_date'],binding['physical_account'],explanation['source_doc'],None,[],[('payroll',explanation_id),('bank',binding['txn_id'])])
    active_groups={row['group_id'] for row in state['investment_active'].values() if row['active']}
    for effect in state['investment_effects'].values():
        if effect['group_id'] not in active_groups or not included(effect['date']):continue
        group=state['investment_groups'].get((effect['group_id'],))
        if group is None:raise IntegrityError('income/expense authenticated investment group unavailable')
        doc,ordinal=effect['owner_doc'],effect['owner_ordinal']
        occurrence=state['source_occurrences'].get((doc,ordinal))
        fields=sorted([dict(row) for row in state['investment_fields'].values() if (row['doc_id'],row['scope'],row['ordinal'])==(doc,'activity',ordinal)],key=lambda row:(row['doc_id'],row['scope'],row['ordinal'],row['name']))
        for posting in state['investment_legs'].values():
            if posting['effect_id']!=effect['effect_id']:continue
            if posting['doc_id']!=doc:raise IntegrityError('income/expense authenticated investment source differs')
            append('investment',effect['effect_id'],posting,effect['date'],group['account_id'],doc,occurrence,fields,[('investment',effect['effect_id'])])
    lines.sort(key=lambda row:(row['date'],row['domain'],row['effect_id'],row['leg']))
    gaps=set()
    for (doc,),document in state['documents'].items():
        item=state['items'].get((doc,))
        if item is None:gaps.add((doc,'item','item_unavailable'));continue
        if item['state']!='accepted':gaps.add((doc,'item',item['state']+':'+item['reason']));continue
        interpretation=state['interpretations'].get((doc,))
        if not interpretation or interpretation['facts_type']!='investment':continue
        component=state['investment_components'].get((doc,))
        if component is None:gaps.add((doc,'activity','component_unavailable'))
        elif component['activity_state'] in {'held','conflicted','unavailable'}:gaps.add((doc,'activity',component['activity_state']+':'+component['reason']))
        for row in state['investment_rows'].values():
            if row['doc_id']==doc and row['kind']=='sell' and row['realized_gain'] is None:gaps.add((doc,'realized_gain','unavailable:'+str(row['ordinal'])))
    currencies={}
    for currency in sorted({row['currency'] for row in lines}):
        earnings=[];costs=[];provisional_earnings=[];provisional_costs=[]
        for line in lines:
            if line['currency']!=currency:continue
            if line['root']=='income':
                earnings.append(line['amount'])
                if line['provisional']:provisional_earnings.append(line['amount'])
            else:
                costs.append(line['amount'])
                if line['provisional']:provisional_costs.append(line['amount'])
        values=(total(earnings),total(costs),total(earnings+[str(amount(v).copy_negate()) for v in costs]),total(provisional_earnings),total(provisional_costs))
        currencies[currency]={name:value for name,value in zip(TOTALS,values)}
        currencies[currency]['unavailable']=[name for name in TOTALS if currencies[currency][name] is None]
    expected=dict(schema=SCHEMA,period=dict(start=start,end=end),frontier=dict(revision=export['revision'],head=export['head']),
        scope=dict(families=['bank','card','payroll','investment'],amount_basis='admitted_named_effects',classification_basis='current_native_head',coverage_complete=not gaps,limitations=LIMITATIONS),
        lines=lines,suppressed=sorted(suppressed,key=lambda row:(row['txn_id'],row['reason'])),by_currency=currencies,
        held_sources=[dict(doc_id=d,facet=f,reason=reason) for d,f,reason in sorted(gaps)])
    if not json_value(report):
        raise IntegrityError('income/expense output has invalid JSON protocol')
    try:
        equal=canonical(report)==canonical(expected)
    except (TypeError,ValueError) as error:
        raise IntegrityError('income/expense output has invalid JSON protocol') from error
    if not equal:raise IntegrityError('income/expense output differs from authenticated native state')
