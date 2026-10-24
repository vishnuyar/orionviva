"""Bounded same-run numerical receipts, without recalculation or event replay."""
from __future__ import annotations

import copy
import json
from decimal import Decimal, InvalidOperation

MAX_FIGURES=100
MAX_RECEIPTS=32
MAX_RECORDS=500
MAX_SCALAR=4096
MAX_MOVEMENTS=10000
MAX_GOALS=200
MAX_GOAL_EVENTS=2000
MAX_RECEIPT_BYTES=262144
MAX_ANSWER_RECEIPT_BYTES=524288
TYPED=('value','quantity','kind','currency','dated','grade','boundary','subject','record_ids')


def scalar(value, *, optional=False):
    if value is None and optional:return None
    if isinstance(value,(str,int)) and not isinstance(value,bool):
        result=str(value)
        if len(result.encode())<=MAX_SCALAR:return result
    raise ValueError('receipt scalar unavailable')


def strings(values, limit=MAX_RECORDS):
    if not isinstance(values,list) or len(values)>limit or any(not isinstance(v,str) or len(v.encode())>MAX_SCALAR for v in values):
        raise ValueError('receipt identities unavailable')
    return list(values)


def typed_figure(figure):
    """Retain only declared numerical fields; legacy figures remain readable."""
    out={}
    for name in ('value','quantity','kind','currency','dated'):
        if name in figure:out[name]=scalar(figure[name])
    if 'value' in out:
        try:value=Decimal(out['value'])
        except InvalidOperation:raise ValueError('invalid numerical value') from None
        if not value.is_finite():raise ValueError('non-finite figure')
    if 'kind' in out and out['kind'] not in ('financial','computed','activity','hypothetical'):raise ValueError('unknown figure kind')
    out['grade']=scalar(figure.get('grade','') or '')
    if out['grade'] not in ('','verified','corroborated','unverified','conflicted'):raise ValueError('unknown figure grade')
    if figure.get('kind') in ('activity','hypothetical') and out['grade']:
        raise ValueError('ungraded figure carries a grade')
    boundary=figure.get('boundary')
    if isinstance(boundary,dict):
        if set(boundary)-{'whole','accounts','selected','cut','unmeasured','unposted'}:raise ValueError('unknown boundary')
        if boundary:
            from ..tools.envelope import bounded
            if type(boundary.get('whole')) is not bool:raise ValueError('invalid boundary')
            accounts=boundary.get('accounts',{})
            if accounts and (set(accounts)!={'counted','held'} or any(type(value) is not int or not 0<=value<=10000 for value in accounts.values())):
                raise ValueError('invalid population bound')
            for name in ('selected','cut','unmeasured'):
                rows=boundary.get(name,[])
                if not isinstance(rows,list) or len(rows)>MAX_RECORDS:raise ValueError('invalid boundary rows')
                for row in rows:
                    allowed={'account','reason','settled_by'} if name=='unmeasured' else {'kind','value','to'}
                    if not isinstance(row,dict) or set(row)-allowed:raise ValueError('invalid boundary axis')
                    for value in row.values():scalar(value)
            if type(boundary.get('unposted',0)) is not int:raise ValueError('invalid document count')
            bounded(whole=boundary['whole'],counted=accounts.get('counted',0),held=accounts.get('held',0),
                selected=boundary.get('selected',[]),cut=boundary.get('cut',[]),
                unmeasured=boundary.get('unmeasured',[]),unposted=boundary.get('unposted',0))
        out['boundary']=copy.deepcopy(boundary)
    subject=figure.get('subject')
    if subject is not None:
        allowed=({'kind','value'},{'grouping'},{'account_id'},{'merchant'},{'goal_id'})
        if not isinstance(subject,dict) or set(subject) not in allowed:raise ValueError('unknown subject')
        if set(subject)=={'grouping'} and subject['grouping'] not in ('category','merchant','account'):raise ValueError('unknown grouping')
        if set(subject)=={'kind','value'}:
            from ..tools.envelope import SELECTED_KINDS
            if subject['kind'] not in SELECTED_KINDS:raise ValueError('unknown subject kind')
        out['subject']={name:scalar(value) for name,value in subject.items()}
    return out


def _source_registry(projection, requested):
    sources={record:dict(record_id=record,kind='unavailable',document_id=None) for record in requested}
    local={}
    if projection is None:return sources,local
    captured=projection.captured_docs()
    if len(captured)>10000:return sources,local
    documents=set(captured)
    for record in requested:
        if record in documents:sources[record]=dict(record_id=record,kind='document',document_id=record)
    core=getattr(projection,'core',getattr(projection,'_core',None))
    if core is None:return sources,local
    accounts=getattr(core,'_acct',{})
    # Check collection sizes before materializing the movement registry.
    if len(accounts)<=MAX_MOVEMENTS and sum(len(state.lines) for state in accounts.values())<=MAX_MOVEMENTS:
        for movement in projection.movements():
            if movement.key in requested and movement.provenance.doc_id in documents:
                sources[movement.key]=dict(record_id=movement.key,kind='movement',document_id=movement.provenance.doc_id)
    goals=getattr(core,'_goals',{})
    if len(goals)>MAX_GOALS or sum(len(row.get('event_ids',[])) for row in goals.values())>MAX_GOAL_EVENTS:
        return sources,local
    for goal in goals.values():
        ids=goal.get('event_ids',[])
        for event in ids:
            if event in requested:sources[event]=dict(record_id=event,kind='local_activity',document_id=None)
        history=goal.get('reservation_history',[])
        # Current state preserves original created terms only without intervening
        # term/state edits; never relabel later terms as the historical creation.
        if ids and len(ids)==len(history)+1 and ids[0] in requested:
            fields=[]
            for name,label in [('title','Goal title'),('currency','Currency'),('target_amount','Target amount'),('target_date','Target date'),('monthly_contribution','Monthly contribution'),('contribution_day','Contribution day'),('created_at','Recorded date')]:
                value=goal.get(name)
                if value is not None:fields.append(dict(label=label,value=scalar(value)))
            local[ids[0]]=dict(event_id=ids[0],event_type='GoalCreated',fields=fields)
        for row in history:
            event=row.get('event_id')
            if event not in requested:continue
            fields=[dict(label=label,value=scalar(row[name])) for name,label in [('account_id','Account'),('amount','Amount'),('occurred_at','Recorded date')] if row.get(name) is not None]
            local[event]=dict(event_id=event,event_type='GoalFundsReserved' if row['kind']=='reserved' else 'GoalFundsReleased',fields=fields)
    return sources,local


def _premises(data, question):
    receipt=data.get('assumption_receipt')
    if receipt is None:return [],[]
    if not isinstance(receipt,dict) or receipt.get('current_question_only') is not True:
        raise ValueError('assumption receipt unavailable')
    parameters=receipt.get('exact_parameters');proofs=receipt.get('exact_proofs');numeric=receipt.get('exact_numeric_inputs');modeled=receipt.get('modeled_inputs')
    if not all(isinstance(value,dict) for value in (parameters,proofs,numeric,modeled)) or len(parameters)>32:
        raise ValueError('assumption proof unavailable')
    out=[]
    for name,value in parameters.items():
        proof=proofs.get(name)
        if not isinstance(proof,dict) or proof.get('source')!='question' or not isinstance(proof.get('quote'),str) or not proof['quote'] or proof['quote'] not in question:
            raise ValueError('current question proof unavailable')
        exact=numeric.get(name,{})
        role=exact.get('role') or {'currency':'currency convention','start_date':'opening or first payment date','account_phrase':'accepted starting account'}.get(name)
        if not role:raise ValueError('unknown premise role')
        unit=exact.get('unit') or ('money' if 'modeled_cents' in exact else {'currency':'currency','start_date':'ISO date','account_phrase':'account'}.get(name))
        out.append(dict(parameter=scalar(name),role=scalar(role),raw=scalar(exact.get('raw',value)),
                        modeled=scalar(exact.get('modeled_cents',modeled.get(name)),optional=True),
                        unit=scalar(unit,optional=True),currency=scalar(exact.get('currency'),optional=True),
                        source='current_question',quote=scalar(proof['quote']),derivation=scalar(proof.get('derivation'),optional=True)))
    observed=[]
    accepted=receipt.get('recorded_start')
    if accepted is not None:
        if not isinstance(accepted,dict) or accepted.get('origin')!='same_run_accepted_measurement' or receipt.get('carry_forward_hypothetical') is not True:
            raise ValueError('accepted measurement unavailable')
        observed.append(dict(account_id=scalar(accepted.get('account_id')),value=scalar(accepted.get('raw_observed')),
            modeled_value=scalar(accepted.get('modeled_cents')),quantity=scalar(accepted.get('quantity')),kind=scalar(accepted.get('kind')),
            currency=scalar(accepted.get('currency')),dated=scalar(accepted.get('dated')),grade=scalar(accepted.get('grade')),
            measurement_view=scalar(accepted.get('measurement_view')),record_ids=strings(accepted.get('record_ids')),
            carry_forward_hypothetical=True))
    elif receipt.get('observed_start') is not None:
        raise ValueError('accepted measurement receipt incomplete')
    return out,observed


def _context(data):
    result=[]
    def put(label,value):
        if value is not None:result.append(dict(label=label,value=scalar(value)))
    for key,label in [('horizon_start','Read day'),('horizon_end','Projection horizon end'),('horizon_date','Scenario horizon end'),('from','Period from'),('to','Period to'),('limit','Result limit'),('total_periods','Modeled periods')]:
        if key in data:put(label,data[key])
    receipt=data.get('assumption_receipt')
    if isinstance(receipt,dict):
        if receipt.get('current_question_only') is True:put('Premise source','Current question only')
        put('Original monthly anchor',receipt.get('declared_start_date'))
        put('Horizon in months',receipt.get('declared_months'))
        put('Scenario currency',receipt.get('currency_header'))
    if data.get('trajectory_sampled') is True:put('Trajectory','Sampled monthly endpoints')
    return result


def numerical_receipts(turn, projection, turn_id):
    """One receipt per genuine producer, referenced by emitted answer figures."""
    answer=getattr(getattr(turn,'result',None),'figures',[])
    transcript=getattr(getattr(turn,'result',None),'transcript',[])
    if (not turn_id or not isinstance(answer,list) or not isinstance(transcript,list)
            or len(answer)>MAX_FIGURES or len(transcript)>MAX_RECEIPTS):return [],{}
    producers=[];index={}
    for position,item in enumerate(transcript):
        if isinstance(item,dict):row=item
        elif all(hasattr(item,key) for key in ('tool','ok','data','figures','caveats')):
            row={key:getattr(item,key) for key in ('tool','ok','data','figures','caveats')}
        else:continue
        figures=row.get('figures',[])
        if row.get('ok') is not True or not isinstance(figures,list) or len(figures)>MAX_FIGURES:continue
        producers.append((position,row))
        for fig in figures:
            if isinstance(fig,dict) and fig.get('id'):index.setdefault(fig['id'],[]).append((position,fig))
    participating={}
    for fig in answer:
        if not isinstance(fig,dict):continue
        try:typed_figure(fig)
        except (ValueError,TypeError,KeyError,AttributeError):continue
        matches=index.get(fig.get('id'),[])
        if (len(matches)==1 and all(fig.get(key)==matches[0][1].get(key) for key in TYPED if key in matches[0][1])
                and type(matches[0][1].get('records',len(fig.get('record_ids',[])))) is int
                and matches[0][1].get('records',len(fig.get('record_ids',[])))==len(fig.get('record_ids',[]))):
            participating.setdefault(matches[0][0],[]).append(fig)
    receipts=[];refs={};receipt_bytes=0
    for position,row in producers:
        figures=participating.get(position,[])
        if not figures:continue
        try:
            records=sorted({record for figure in figures for record in strings(figure.get('record_ids',[]))})
            if len(records)>MAX_RECORDS:continue
            sources,local=_source_registry(projection,set(records))
            data=row.get('data') or {}
            if not isinstance(data,dict):continue
            premises,observed=_premises(data,str(getattr(turn,'question','')))
            caveats=strings([item['text'] if isinstance(item,dict) and set(item)=={'text'} else item for item in row.get('caveats',[])],100)
            identity=f'conversation:{turn_id}:numerical:{position}'
            context=_context(data)
            if any(source['kind']=='unavailable' for source in sources.values()):
                context.append(dict(label='Source receipt limit',value='Some source identities are not captured originals or resolvable local records. Movement lookup is limited to 10000 held transaction lines.'))
            if any(source['kind']=='local_activity' and event not in local for event,source in sources.items()):
                context.append(dict(label='Local receipt limit',value='Some participating historical local terms are unavailable; later terms have not been substituted.'))
            receipt=dict(schema_version=1,id=identity,figure_ids=[fig['id'] for fig in figures],
                source_records=[sources[record] for record in records],premises=premises,observed_inputs=observed,
                local_inputs=[local[event] for event in sorted(local)],context=context,caveats=caveats)
            size=len(json.dumps(receipt,ensure_ascii=False).encode())
            if size>MAX_RECEIPT_BYTES or receipt_bytes+size>MAX_ANSWER_RECEIPT_BYTES:continue
            receipt_bytes+=size
            receipts.append(receipt)
            for fig in figures:refs.setdefault(fig['id'],[]).append(identity)
        except (ValueError,TypeError,KeyError,AttributeError,InvalidOperation):
            continue
    return receipts,refs
