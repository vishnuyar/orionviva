"""Bounded same-run numerical receipts, without recalculation or event replay."""
from __future__ import annotations

import copy
import json
from decimal import Decimal, InvalidOperation

MAX_FIGURES=128
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
        allowed=({'kind','value'},{'grouping'},{'account_id'},{'account_id','security_id'},{'merchant'},{'goal_id'})
        retirement=isinstance(subject,dict) and 'account_set_id' in subject
        if retirement:
            from ..retirement_funding.contracts import valid_subject
            valid_subject(subject)
        elif not isinstance(subject,dict) or set(subject) not in allowed:raise ValueError('unknown subject')
        if set(subject)=={'account_id','security_id'} and any(not isinstance(value,str) or not value.strip() or len(value)>256 for value in subject.values()):raise ValueError('invalid account-local security subject')
        if set(subject)=={'grouping'} and subject['grouping'] not in ('category','merchant','account'):raise ValueError('unknown grouping')
        if set(subject)=={'kind','value'}:
            from ..tools.envelope import SELECTED_KINDS
            if subject['kind'] not in SELECTED_KINDS:raise ValueError('unknown subject kind')
        out['subject']={name:(strings(value,3) if name=='member_ids' and retirement else scalar(value)) for name,value in subject.items()}
    return out



def _investment_anchors(data):
    if data.get('source_fields',{}).get('schema')=='investment-source-fields-v2':
        from ..investment.lineage import expand_anchors
        return expand_anchors(data)
    return data.get('anchors')


def _investment_provenance(data,figures):
    if 'figure_sources' in data:
        from ..investment.lineage import lineage_digest
        expected=lineage_digest(data)
        if any(fig.get('source_lineage_digest')!=expected for fig in figures):raise ValueError('investment source field lineage changed')
    anchors=_investment_anchors(data)
    if not isinstance(anchors,dict) or len(anchors)>5000:raise ValueError('investment anchors unavailable')
    pairs=set();out={}
    for anchor in anchors.values():
        if not isinstance(anchor,dict) or set(anchor)!={'document','page','anchor'}:raise ValueError('invalid investment source anchor')
        document=scalar(anchor['document']);scalar(anchor['anchor'])
        if not document or type(anchor['page']) is not int or not 1<=anchor['page']<=200:raise ValueError('invalid investment source page')
        pairs.add((document,anchor['page']))
    if len(pairs)>512:raise ValueError('investment source page bound')
    for fig in figures:
        identities=strings(fig.get('anchor_ids'),5000)
        if not identities or any(identity not in anchors for identity in identities):raise ValueError('missing investment figure anchor')
        selected=sorted({(anchors[identity]['document'],anchors[identity]['page']) for identity in identities})
        if {document for document,page in selected}!=set(strings(fig.get('record_ids'))):raise ValueError('investment source records mismatch')
        subject=fig.get('subject',{})
        if subject.get('account_id')!=data.get('account'):raise ValueError('investment selected account mismatch')
        out[scalar(fig['id'])]=[dict(document_id=document,page=page) for document,page in selected]
    return out


def _investment_derivations(data,figures):
    anchors=_investment_anchors(data);out=[]
    for fig in figures:
        if fig.get('quantity')!='disposed_cost_basis':continue
        operands=fig.get('operands')
        if not isinstance(operands,list) or len(operands)>1000:raise ValueError('investment operands unavailable')
        rows=[]
        for operand in operands:
            if not isinstance(operand,dict) or set(operand)!={'row','operation','proceeds','reported_realized_gain','anchor_ids'} or operand['operation']!='proceeds_minus_reported_realized_gain':raise ValueError('unsupported investment derivation')
            values={name:scalar(operand[name]) for name in ('proceeds','reported_realized_gain')}
            if any(not Decimal(value).is_finite() for value in values.values()):raise ValueError('nonfinite investment operand')
            identities=strings(operand['anchor_ids'],2)
            if len(identities)!=2 or any(identity not in anchors or identity not in fig.get('anchor_ids',[]) for identity in identities):raise ValueError('investment operand source unavailable')
            pages=sorted({(anchors[identity]['document'],anchors[identity]['page']) for identity in identities})
            row_id=scalar(operand['row'])
            if 'source_identities' in data:
                row_id=scalar(data['source_identities']['rows'][row_id])
            rows.append(dict(row_id=row_id,**values,source_pages=[dict(document_id=document,page=page) for document,page in pages]))
        out.append(dict(figure_id=scalar(fig['id']),operation='proceeds_minus_reported_realized_gain',rows=rows))
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
            investment_provenance=None
            investment_derivations=None
            if row.get('tool')=='read_account_balance_report':
                from ..tools.account_balances import receipt_provenance
                execution = getattr(turn, 'instrument_execution', None)
                original_reads = getattr(execution, 'transcript', ())
                original = original_reads[position] if position < len(original_reads) else None
                token = getattr(getattr(getattr(execution, 'graph', None), 'ground', None),
                                'instrument_token', None)
                if (original is None or original.tool != row.get('tool')
                        or original.id != row.get('id')):
                    raise ValueError('selected account receipt lacks its actual execution producer')
                investment_provenance = receipt_provenance(data, figures,
                    producer=original, run_token=token,
                    origin=getattr(getattr(turn, 'result', None), '_selected_report_origin', None))
                investment_derivations = []
                context.append(dict(label='Read day', value=scalar(data.get('read_day'))))
                for disposition in data.get('rows', []):
                    if disposition.get('account') not in data.get('source_fields', {}).get('selected_accounts', []):
                        raise ValueError('selected account disposition membership changed')
                    if any(disposition.get(field) not in {'accepted', 'unavailable', 'conflicted'}
                            for field in ('amount', 'date', 'source', 'restriction', 'closure')):
                        raise ValueError('selected account disposition changed')
            if row.get('tool')=='read_investment_evidence':
                investment_provenance=_investment_provenance(data,figures)
                investment_derivations=_investment_derivations(data,figures)
                dispositions=data.get('dispositions',[])
                if not isinstance(dispositions,list) or len(dispositions)>64:raise ValueError('investment dispositions unavailable')
                allowed_claims={'security_units','holding_cost_basis','investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain','balance','count'}
                for disposition in dispositions:
                    if not isinstance(disposition,dict) or disposition.get('claim') not in allowed_claims or disposition.get('status') not in {'unavailable','conflicted','incomplete','unsupported_units'}:raise ValueError('invalid investment disposition')
                    context.append(dict(label='Investment evidence limit',value=disposition['claim'].replace('_',' ')+': '+disposition['status'].replace('_',' ')+'.'))
                for label,key in (('Investment view','view'),('Selected account','account'),('Valuation currency','currency'),('Authenticated read revision','revision')):
                    context.append(dict(label=label,value=scalar(data.get(key))))
                if any(fig.get('quantity')=='disposed_cost_basis' for fig in figures):
                    context.append(dict(label='Disposed-basis derivation',value='Source sale proceeds minus source reported realized gain; no lot method is asserted.'))
            if row.get('tool')=='read_retirement_funding':
                from ..retirement_funding.lineage import public_provenance
                investment_provenance=public_provenance(data,figures)
                investment_derivations=[]
                context.append(dict(label='Retirement funding source scope',value=scalar(data.get('source_scope'))))
                context.append(dict(label='Selected retirement plans',value=', '.join(strings(data['subject']['member_ids'],3))))
                context.append(dict(label='Retirement funding view',value=scalar(data['view'])))
                relationships=set()
                for fig in figures:
                    relationship=(fig.get('subject') or {}).get('relationship_id')
                    if relationship and relationship not in relationships:
                        relationships.add(relationship)
                        context.append(dict(label='Documented rollover relationship',value=relationship))
                        context.append(dict(label='Canonical rollover source',value=scalar(fig['subject']['source_account_id'])))
                        context.append(dict(label='Canonical rollover destination',value=scalar(fig['subject']['destination_account_id'])))
            if row.get("tool")=="read_instrument_details":
                for label,key in (("Instrument view","view"),("Selected account","account"),("Valuation currency","currency"),("Authenticated read revision","revision")):
                    context.append(dict(label=label,value=scalar(data.get(key))))
                rules=data.get("tax_absence_rules",[])
                if not isinstance(rules,list) or len(rules)>80:raise ValueError("tax absence receipt unavailable")
                active_ids={f.get("authority_record_id") for f in figures}
                for rule in rules:
                    if rule.get("record_id") not in active_ids:continue
                    if set(rule)!={"record_id","from","to","rule"} or rule["rule"]!="accepted_empty_tax_event_set_v1":raise ValueError("tax absence receipt unavailable")
                    from datetime import date
                    start=date.fromisoformat(rule["from"]);end=date.fromisoformat(rule["to"])
                    if start>end:raise ValueError("tax absence receipt period unavailable")
                    context.append(dict(label="Tax absence rule",value="For "+start.isoformat()+" through "+end.isoformat()+", sum of the complete accepted tax event set (no events)."))
                comparison=data.get("allocation_comparison")
                if comparison is not None:
                    if not isinstance(comparison,dict):raise ValueError("allocation receipt unavailable")
                    current=[p for p in getattr(turn.result,"target_premises",[]) if p.get("receipt_id")==comparison.get("premise_ref")]
                    if len(current)!=1 or current[0].get("kind")!="user_stated" or current[0].get("target_role_text") not in turn.question:raise ValueError("current target receipt unavailable")
                    target=current[0]
                    premises.append(dict(parameter="allocation_target",role="user-stated allocation target",raw=target["target_role_text"],
                        modeled=scalar(comparison["target_numerator"])+"/"+scalar(comparison["target_denominator"]),unit="fraction",currency="",
                        source="current_question",quote=target["target_role_text"],derivation="exact positive target-role grammar"))
                    for label,key in (("Allocation comparison operation","operation"),("Accepted exposure market-value numerator","numerator_value"),
                        ("Numerator source figure","numerator_record_id"),("Accepted cash-inclusive market-value denominator","denominator_value"),
                        ("Denominator source figure","denominator_record_id"),("Display-only rounded allocation weight","display_weight_record_id"),
                        ("Current target receipt","premise_ref"),("Exposure","exposure"),("Snapshot date","snapshot_date"),("Arithmetic convention","rounding")):
                        context.append(dict(label=label,value=scalar(comparison[key])))
            if any(source['kind']=='unavailable' for source in sources.values()):
                context.append(dict(label='Source receipt limit',value='Some source identities are not captured originals or resolvable local records. Movement lookup is limited to 10000 held transaction lines.'))
            if any(source['kind']=='local_activity' and event not in local for event,source in sources.items()):
                context.append(dict(label='Local receipt limit',value='Some participating historical local terms are unavailable; later terms have not been substituted.'))
            receipt=dict(schema_version=1,id=identity,figure_ids=[fig['id'] for fig in figures],
                source_records=[sources[record] for record in records],premises=premises,observed_inputs=observed,
                local_inputs=[local[event] for event in sorted(local)],context=context,caveats=caveats)
            if investment_provenance is not None:
                receipt['figure_provenance']=investment_provenance
                receipt['investment_derivations']=investment_derivations
            size=len(json.dumps(receipt,ensure_ascii=False).encode())
            if size>MAX_RECEIPT_BYTES or receipt_bytes+size>MAX_ANSWER_RECEIPT_BYTES:continue
            receipt_bytes+=size
            receipts.append(receipt)
            for fig in figures:refs.setdefault(fig['id'],[]).append(identity)
        except (ValueError,TypeError,KeyError,AttributeError,InvalidOperation):
            continue
    return receipts,refs
