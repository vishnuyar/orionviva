"""Closed, sourced measurement and statement-coverage read boundaries."""
import datetime
import json
from .registry import _validate
from .envelope import ToolResult, figure, refusal, bounded, ACTIVITY, weakest
from .ledger_common import _identifiers
from .. import quantity
from ..ledger.projection.measurements import measurements
from ..ledger.statements import register

_STRING = {'type':'string','minLength':1}
_DATE = {'type':'string','format':'date'}
MEASUREMENT_PARAMS = {'type':'object','additionalProperties':False,
    'properties':{'view':{'type':'string','enum':['recorded_cash','account_value_history','recorded_owed']},
                  'account':_STRING,'currency':_STRING,'from':_DATE,'to':_DATE},
    'required':['view','account']}
COVERAGE_PARAMS = {'type':'object','additionalProperties':False,
    'properties':{'account':_STRING,'from':_DATE,'to':_DATE},'required':['account','from','to']}


def validate_boundary(proj,args,schema,tool,*,period=False):
    errors = _validate(schema,args) if isinstance(args,dict) else ['Arguments must be an object.']
    if errors: return refusal(tool,'invalid_arguments','; '.join(errors))
    if any(isinstance(value,str) and not value.strip() for value in args.values()):
        return refusal(tool,'invalid_arguments','Arguments cannot be blank.')
    if args.get('account') not in proj.accounts():
        return refusal(tool,'unknown_account','Select a canonical held account.')
    if period:
        if not {'from','to'} <= set(args):
            return refusal(tool,'invalid_arguments','History requires both period edges.')
        try:
            dates = [datetime.date.fromisoformat(args[key]) for key in ('from','to')]
            if any(date.isoformat() != args[key] for date,key in zip(dates,('from','to'))) or dates[0] > dates[1]: raise ValueError
        except (ValueError,TypeError): return refusal(tool,'bad_date','Use ordered ISO period edges.')
    elif {'from','to'} & set(args):
        return refusal(tool,'invalid_arguments','A cash stock does not accept a period.')
    return None


def read_account_measurements(proj,args,locale='',today=''):
    tool = 'read_account_measurements'
    history = isinstance(args,dict) and args.get('view') == 'account_value_history'
    problem = validate_boundary(proj,args,MEASUREMENT_PARAMS,tool,period=history)
    if problem: return problem
    account = args['account']; info = proj.account_info(account)
    owed = args['view'] == 'recorded_owed'
    if owed and info.kind != 'liability':
        return refusal(tool,'owed_account_ineligible','Select a held liability account.')
    if (not history and not owed and info.kind not in {'depository','investment'}) or (history and info.kind not in {'depository','investment','liability'}):
        return refusal(tool,'cash_account_ineligible','Select a supported financial account.')
    rows, incomplete = measurements(proj.core,account,cash=not history,locale=locale or 'en-US')
    currency = args.get('currency')
    if currency: rows=[row for row in rows if row.currency == currency]; incomplete=tuple(row for row in incomplete if row.currency == currency)
    if history:
        rows=[row for row in rows if args['from'] <= row.dated <= args['to']]
        incomplete=tuple(row for row in incomplete if args['from'] <= row.dated <= args['to'])
        if incomplete: return refusal(tool,'incomplete_investment_snapshot','A common accepted statement snapshot is incomplete.')
        if len(rows)>50: return refusal(tool,'history_row_limit','Narrow the measurement period.')
    else:
        rows=[row for row in rows if row.kind in ({'liability'} if owed else {'depository','investment'})]
        if rows:
            rows=[rows[-1]]
    if not rows: return refusal(tool,'account_history_unavailable' if history else 'owed_measurement_unavailable' if owed else 'cash_measurement_unavailable','No sourced measurement is held in this scope.')
    if any(row.context_conflict for row in rows):
        return refusal(tool,'measurement_source_context_conflict','Source measurement currency or kind conflicts.')
    if any(row.kind == 'liability' and row.amount < 0 for row in rows):
        return refusal(tool,'owed_value_not_debt','The liability is a credit, not debt.')
    selected=[{'kind':'account','value':account}]
    boundary=bounded(whole=True,selected=selected,cut=selected)
    figures=[figure(row.amount,('recorded account value' if history else 'recorded amount owed' if owed else 'recorded cash')+' — '+(info.name or account)+' — measured '+row.dated,
                    quantity=quantity.OWED if row.kind == 'liability' else quantity.BALANCE,grade=row.grade,currency=row.currency,dated=row.dated,
                    record_ids=row.component_sources,boundary=boundary) for row in rows]
    for emitted in figures:
        emitted['measurement_view']=args['view']
    result=ToolResult(tool=tool,ok=True,data={'view':args['view'],'account':account,
        'measurements':[{'amount':str(row.amount),'currency':row.currency,'dated':row.dated,'grade':row.grade,'kind':row.kind,'record_ids':list(row.component_sources)} for row in rows]},
        figures=figures,identifiers=_identifiers(proj,[account]),record_ids=sorted({doc for row in rows for doc in row.component_sources}),
        grade=weakest(row.grade for row in rows),dated=rows[0].dated if len(rows)==1 else '',
        caveats=['These are recorded measurement dates; there is no interpolation or later-value backfill.']+(['Brokerage cash is the cash component, not invested value, buying power or available withdrawal.'] if not history and info.kind=='investment' else []),
        text='Dated, sourced account measurements.')
    if len(json.dumps(result.to_dict()).encode())>50_000:
        return refusal(tool,'history_payload_limit' if history else 'owed_payload_limit' if owed else 'cash_payload_limit',
                       'This debt measurement and its source details exceed the display limit. The complete sourced amount owed cannot be shown.' if owed else 'The complete sourced measurement details exceed the display limit.')
    return result


def read_statement_coverage(proj,args,locale='',today=''):
    tool='read_statement_coverage'
    problem=validate_boundary(proj,args,COVERAGE_PARAMS,tool,period=True)
    if problem: return problem
    held=register(proj.core,locale or 'en-US').get(args['account']); start=args['from']; end=args['to']
    records=[r for r in held.records if r.opening_date <= end and r.closing_date >= start] if held else []
    if not records: return refusal(tool,'statement_coverage_unavailable','No held statement declares coverage in this period.')
    intervals=sorted((max(start,r.opening_date),min(end,r.closing_date)) for r in records)
    merged=[]
    for a,b in intervals:
        if merged and (datetime.date.fromisoformat(a)-datetime.date.fromisoformat(merged[-1][1])).days <= 1:
            merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else: merged.append((a,b))
    uncovered=[]; cursor=datetime.date.fromisoformat(start)
    for a,b in merged:
        left=datetime.date.fromisoformat(a)
        if cursor < left: uncovered.append({'from':cursor.isoformat(),'to':(left-datetime.timedelta(days=1)).isoformat()})
        if b == end:
            cursor=None
            break
        cursor=datetime.date.fromisoformat(b)+datetime.timedelta(days=1)
    if cursor is not None and cursor <= datetime.date.fromisoformat(end): uncovered.append({'from':cursor.isoformat(),'to':end})
    sources=sorted({r.doc_id for r in records}); account=args['account']
    caveats=['Statement snapshots and movement dates do not attest transaction periods. Uncovered intervals mean held records do not attest those days; this does not prove an issued statement is missing.',
             'Held statement coverage: '+ '; '.join(a+' to '+b for a,b in merged)+'.']
    if uncovered: caveats.append('Uncovered intervals: '+'; '.join(r['from']+' to '+r['to'] for r in uncovered)+'.')
    result=ToolResult(tool=tool,ok=True,data={'account':account,'uncovered':uncovered,'statements':[{'doc_id':r.doc_id,'from':r.opening_date,'to':r.closing_date} for r in records]},
        record_ids=sources,identifiers=_identifiers(proj,[account]),covers=[{'account':account,'from':a,'to':b} for a,b in merged],
        figures=[figure(len(records),'held statements declaring coverage',quantity=quantity.COUNT,kind=ACTIVITY,record_ids=sources,
                        boundary=bounded(whole=not uncovered,selected=[{'kind':'account','value':account}],cut=[{'kind':'account','value':account}]))],
        caveats=caveats,text='Coverage declared by held statements, clipped to the requested period.')
    if len(json.dumps(result.to_dict()).encode())>5000:
        return refusal(tool,'coverage_payload_limit','Narrow the requested statement period.')
    return result
