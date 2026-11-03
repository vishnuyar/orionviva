"""Current admitted native income/expense selected through indexed SQL paths."""
import hashlib
import copy
from decimal import localcontext,Inexact

from viva.ledger.streams import money_effect

from .accounting_numbers import SCHEMA,LIMITATIONS,TOTALS,amount,total,period
from .investment_numbers import display
from .store import canonical,IntegrityError
from .schema import TABLES


def _rows(store,table,where='1',parameters=(),order=''):
    columns=TABLES[table]
    sql='SELECT '+','.join('"'+name+'"' for name in columns)+' FROM '+table+' WHERE '+where
    if order:sql+=' ORDER BY '+order
    return [dict(zip(columns,row)) for row in store._read(sql,parameters)]


def _line(domain,effect,leg,day,physical,currency,posting,doc,occurrence,fields,related,economic=None):
    category=posting['account_id']
    root='income' if category.startswith('Income:') else 'expenses' if category.startswith('Expenses:') else None
    if root is None:return None
    value=amount(posting['amount'])
    if not value:return None
    if domain=='bank':
        if economic is None:raise IntegrityError('income/expense bank economic amount unavailable')
        value=economic if root=='income' else economic.copy_negate()
    else:value=value.copy_negate() if root=='income' else value
    identity=['sql-income-expense-line-v1',domain,effect,leg]
    return dict(line_id=hashlib.sha256(canonical(identity).encode()).hexdigest(),domain=domain,effect_id=effect,
        leg=leg,date=day,account_id=physical,currency=currency,root=root,category=category,amount=display(value),
        provisional=domain=='bank',amount_evidence=dict(native_posting=posting,source_doc=doc,
            source_occurrence=occurrence,source_fields=fields),classification_evidence=dict(
            by='provisional' if domain=='bank' else 'document',reason='native_default' if domain=='bank' else
            'native_payroll_decomposition' if domain=='payroll' else 'native_investment_posting',
            related_effects=[dict(domain=d,effect_id=e) for d,e in sorted(set(related))]))


def _live_transfer(store,movement):
    member=store._row('transfer_members','movement=?',(movement,))
    if not member or not member['active']:return None
    pair=store._row('transfer_pairs','a=? AND b=?',(member['a'],member['b']))
    members=_rows(store,'transfer_members','a=? AND b=? AND active=1',(member['a'],member['b']))
    if not pair or pair['status']!='linked' or {m['movement'] for m in members}!={pair['a'],pair['b']}:
        raise IntegrityError('income/expense live transfer ownership differs')
    return [pair['a'],pair['b']]


def _held(store):
    gaps=set()
    for document in _rows(store,'documents',order='doc_id'):
        doc=document['doc_id'];item=store._row('items','doc_id=?',(doc,))
        if item is None:gaps.add((doc,'item','item_unavailable'));continue
        if item['state']!='accepted':gaps.add((doc,'item',item['state']+':'+item['reason']));continue
        interpretation=store._row('interpretations','doc_id=?',(doc,))
        if not interpretation or interpretation['facts_type']!='investment':continue
        component=store._row('investment_components','doc_id=?',(doc,))
        if component is None:gaps.add((doc,'activity','component_unavailable'))
        elif component['activity_state'] in {'held','conflicted','unavailable'}:
            gaps.add((doc,'activity',component['activity_state']+':'+component['reason']))
        for row in _rows(store,'investment_rows','doc_id=?',(doc,),order='ordinal'):
            if row['kind']=='sell' and row['realized_gain'] is None:gaps.add((doc,'realized_gain','unavailable:'+str(row['ordinal'])))
    return [dict(doc_id=d,facet=f,reason=r) for d,f,r in sorted(gaps)]


def read(store,*,start,end):
    period(start,end)
    latest=[value for table,column in [('transactions','date'),('payroll_explanations','pay_date'),('investment_effects','date')]
            for (value,) in store._read('SELECT max('+column+') FROM '+table) if value]
    end=end or max(latest,default='')
    period(start,end)
    inside=lambda day:(not start or day>=start) and (not end or day<=end)
    lines=[];suppressed=[]
    for source_account in _rows(store,'accounts',order='account_id'):
        account=source_account['account_id']
        for txn in _rows(store,'transactions','account_id=? AND date>=? AND date<=?',(account,start,end or '9999-12-31'),order='date,txn_id'):
            binding=store._row('transfer_bindings','txn_id=?',(txn['txn_id'],))
            source=store._row('staged_statements','doc_id=?',(txn['doc_id'],))
            if (source_account['kind'] not in {'depository','liability'} or source is None or
                source['kind']!=source_account['kind'] or source['currency']!=source_account['currency'] or
                txn['account_id']!=account or binding is None or binding['physical_account']!=account or
                binding['doc_id']!=txn['doc_id'] or binding['date']!=txn['date'] or binding['amount']!=txn['amount']):
                raise IntegrityError('income/expense bank source kind or association differs')
            movement=binding['movement'];pair=_live_transfer(store,movement)
            payroll=_rows(store,'payroll_active','active=1 AND movement=?',(movement,))
            if pair and payroll:raise IntegrityError('income/expense incompatible live reservations')
            if pair or payroll:
                relationship=pair if pair else payroll[0]['explanation_id']
                suppressed.append(dict(txn_id=txn['txn_id'],doc_id=txn['doc_id'],reason='live_transfer' if pair else 'payroll_decomposition',relationship=relationship))
                continue
            with localcontext() as arithmetic:
                arithmetic.prec=28;arithmetic.Emax=999999;arithmetic.Emin=-999999;arithmetic.traps[Inexact]=True
                economic=money_effect(source_account['kind'],amount(txn['amount']))
            occurrence=store._row('source_occurrences','doc_id=? AND line_index=?',(txn['doc_id'],txn['line_index']))
            for posting in _rows(store,'postings','txn_id=?',(txn['txn_id'],),order='leg'):
                if posting['doc_id']!=txn['doc_id'] or posting['currency']!=source_account['currency']:
                    raise IntegrityError('income/expense bank source differs')
                line=_line('bank',txn['txn_id'],posting['leg'],txn['date'],account,posting['currency'],posting,txn['doc_id'],occurrence,[],[('bank',txn['txn_id'])],economic)
                if line:lines.append(line)
    for active in _rows(store,'payroll_active','active=1',order='explanation_id'):
        explanation=store._row('payroll_explanations','explanation_id=?',(active['explanation_id'],))
        if explanation is None:raise IntegrityError('income/expense payroll explanation unavailable')
        binding=store._row('transfer_bindings','movement=?',(active['movement'],))
        if binding is None or explanation['movement']!=binding['movement'] or explanation['txn_id']!=binding['txn_id'] or _live_transfer(store,binding['movement']):
            raise IntegrityError('income/expense payroll source ownership differs')
        if not inside(explanation['pay_date']):continue
        for posting in _rows(store,'payroll_legs','explanation_id=?',(explanation['explanation_id'],),order='leg'):
            if posting['account_id']=='Income:Uncategorized':continue
            if posting['doc_id']!=explanation['source_doc']:raise IntegrityError('income/expense payroll source differs')
            line=_line('payroll',explanation['explanation_id'],posting['leg'],explanation['pay_date'],binding['physical_account'],posting['currency'],posting,explanation['source_doc'],None,[],[('payroll',explanation['explanation_id']),('bank',binding['txn_id'])])
            if line:lines.append(line)
    for (account,) in store._read("SELECT account_id FROM accounts WHERE kind='investment' ORDER BY account_id"):
        for group in _rows(store,'investment_groups','account_id=?',(account,),order='period_end,group_id'):
            active=store._row('investment_active','group_id=?',(group['group_id'],))
            if not active or not active['active']:continue
            for effect in _rows(store,'investment_effects','group_id=?',(group['group_id'],),order='effect_id'):
                if not inside(effect['date']):continue
                doc=effect['owner_doc'];ordinal=effect['owner_ordinal']
                occurrence=store._row('source_occurrences','doc_id=? AND line_index=?',(doc,ordinal))
                fields=_rows(store,'investment_fields','doc_id=? AND scope=? AND ordinal=?',(doc,'activity',ordinal),order='doc_id,scope,ordinal,name')
                for posting in _rows(store,'investment_legs','effect_id=?',(effect['effect_id'],),order='leg'):
                    if posting['doc_id']!=doc:raise IntegrityError('income/expense investment source differs')
                    line=_line('investment',effect['effect_id'],posting['leg'],effect['date'],account,posting['currency'],posting,doc,occurrence,fields,[('investment',effect['effect_id'])])
                    if line:lines.append(line)
    lines.sort(key=lambda line:(line['date'],line['domain'],line['effect_id'],line['leg']))
    currencies={}
    for currency in sorted({line['currency'] for line in lines}):
        income=[l['amount'] for l in lines if l['currency']==currency and l['root']=='income']
        expenses=[l['amount'] for l in lines if l['currency']==currency and l['root']=='expenses']
        values=[total(income),total(expenses),total(income+[str(amount(v).copy_negate()) for v in expenses]),
            total([l['amount'] for l in lines if l['currency']==currency and l['root']=='income' and l['provisional']]),
            total([l['amount'] for l in lines if l['currency']==currency and l['root']=='expenses' and l['provisional']])]
        currencies[currency]=dict(zip(TOTALS,values));currencies[currency]['unavailable']=[name for name,value in zip(TOTALS,values) if value is None]
    revision,head=store._check_terminal();gaps=_held(store)
    return copy.deepcopy(dict(schema=SCHEMA,period=dict(start=start,end=end),frontier=dict(revision=revision,head=head),
        scope=dict(families=['bank','card','payroll','investment'],amount_basis='admitted_named_effects',classification_basis='current_native_head',coverage_complete=not gaps,limitations=LIMITATIONS),
        lines=lines,suppressed=sorted(suppressed,key=lambda row:(row['txn_id'],row['reason'])),by_currency=currencies,held_sources=gaps))
