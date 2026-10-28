"""Finite instrument ToolResult adapter; financial authority stays in local code."""
from dataclasses import asdict
import json
from time import monotonic
from .envelope import ToolResult,figure,refusal,bounded,weakest,HYPOTHETICAL,FINANCIAL
from ..instrument_claims import CLAIMS,CLAIM_RELATIONSHIPS
from ..instrument_evidence import _attest_figure,_attest_assertion,_attest_premise

TOOL='read_instrument_details'
_STRING={'type':'string','minLength':1}
_DATE={'type':'string','format':'date'}
_FIELDS={'account':_STRING,'currency':_STRING,'as_of':_DATE,'from':_DATE,'to':_DATE,
    'grouping':{'type':'string','enum':['none','month','year']},
    'component_set':{'type':'string','enum':['deposit','loan_principal','payment_escrow','annual_summary']},
    'axis':{'type':'string','enum':['exposure','vehicle']},'target_premise_ref':_STRING}
_VARIANTS={'terms':('as_of',),'maturities':('as_of',),'allocation':('as_of','axis'),
 'period_components':('from','to','grouping','component_set'),'refinances':('from','to'),
 'tax_payments':('from','to','grouping')}
INSTRUMENT_PARAMS={'oneOf':[{'type':'object','additionalProperties':False,
    'properties':{'view':{'type':'string','enum':[view]},**{name:_FIELDS[name] for name in ('account','currency',*fields)},
        **({'target_premise_ref':_STRING} if view=='allocation' else {})},
    'required':['view','account','currency',*fields]} for view,fields in _VARIANTS.items()]}


def read_instrument_details(runtime,args):
    from ..read_store.instrument_authority_contracts import InstrumentRequest
    from ..read_store.instrument_authority import read_instrument_authority
    try:request=InstrumentRequest.from_dict(args)
    except (ValueError,TypeError) as error:return refusal(TOOL,'invalid_arguments',str(error))
    if runtime is None or runtime.revision is None:
        return refusal(TOOL,'current_data_unavailable','The current authenticated instrument records are unavailable.')
    revision=runtime.revision;deadline=min(runtime.deadline,(runtime.started+2) if runtime.read_count==0 else monotonic()+2)
    runtime.read_count+=1;runtime.read_deadline=deadline
    try:
        revision._store.authenticated_source_identity(revision)
        premise=runtime.resolve_target(request.target_premise_ref,request) if request.target_premise_ref else None
        authority=read_instrument_authority(revision,request,deadline=deadline,target_premise=premise)
        return _instrument_authority_result(runtime,request,authority,deadline=deadline,premise=premise)
    except (ValueError,TypeError,KeyError) as error:return refusal(TOOL,'instrument_evidence_unavailable',str(error))


def _instrument_authority_result(runtime,request,authority,*,deadline,premise=None):
    """Format source authority in the current execution, preserving its complete envelope."""
    try:
        if not authority.figures and not authority.assertions:
            why='resource_limit' if any(d.disposition=='resource_limit' for d in authority.dispositions) else 'instrument_evidence_unavailable'
            return refusal(TOOL,why,'The selected instrument evidence is unavailable or incomplete.',dispositions=[asdict(d) for d in authority.dispositions])
        if len(authority.assertions)>80:return refusal(TOOL,"resource_limit","The complete sourced assertion set exceeds its row bound.")
        anchors={a.anchor_id:a for a in authority.anchors};figures=[];assertions=[]
        for record in authority.figures:
            role=CLAIM_RELATIONSHIPS.get(record.claim)
            relation=next((v for v in authority.relationships if v.role==role and v.account==record.account),None) if role else None
            if record.account!=request.account and relation is None:raise ValueError('instrument subject mismatch')
            contract=CLAIMS[record.claim]
            if contract.render_type=='money' and record.currency!=request.currency:raise ValueError('instrument currency mismatch')
            if request.start is not None:
                if record.start is not None and not request.start<=record.start<=record.end<=request.end:raise ValueError("instrument period mismatch")
                if record.as_of is not None and not request.start<=record.as_of<=request.end:raise ValueError("instrument value date mismatch")
            elif record.as_of is not None and record.as_of>request.as_of:raise ValueError("instrument future value date mismatch")
            source_ids=sorted({anchors[a].document_id for a in record.anchor_ids})
            cuts=[{'kind':'account','value':record.account}]
            if record.start is not None:cuts.append({'kind':'period','value':record.start,'to':record.end})
            label=record.claim.replace('_',' ')+((' · '+record.start+' through '+record.end) if record.start is not None else (' · '+record.as_of) if record.as_of else '')
            plain=figure(record.value,label,quantity=record.quantity,
                kind=HYPOTHETICAL if record.claim=='allocation_percentage_points' else FINANCIAL,
                grade=record.grade or '',dated=record.as_of or '',currency=record.currency or '',
                record_ids=source_ids,exactness='exact' if record.exact else 'rounded',
                boundary=bounded(whole=False,counted=1,held=1,selected=[cuts[0]],cut=cuts),subject={'account_id':record.account})
            plain.update(authority_record_id=record.record_id,anchor_ids=list(record.anchor_ids),
                observation_ids=list(record.observation_ids),component_ids=list(record.component_ids),
                direction=record.direction,premise_ref=record.premise_ref,operand_ids=list(record.operand_ids),
                record_association=record.record_association,calculation_context=record.calculation_context,
                selected_request_account=request.account,instrument_relationship=role)
            figures.append(_attest_figure(plain,record.claim,run_token=runtime.run_token))
        for record in authority.assertions:
            role=CLAIM_RELATIONSHIPS.get(record.claim)
            relation=next((v for v in authority.relationships if v.role==role and v.account==record.account),None) if role else None
            if record.account!=request.account and relation is None:raise ValueError('assertion subject mismatch')
            contract=CLAIMS[record.claim]
            value=asdict(record);value.update(value_type=contract.value_type,disposition='accepted',id='',
                anchors=[asdict(anchors[a]) for a in record.anchor_ids],
                selected_request_account=request.account,instrument_relationship=role)
            assertions.append(_attest_assertion(value,run_token=runtime.run_token))
        data={'view':request.view,'account':request.account,'currency':request.currency,'revision':authority.revision,
            'fields':[{'claim':f['claim'],'record_id':f['authority_record_id']} for f in figures],
            'assertions':[{'claim':a['claim'],'receipt_id':a['receipt_id']} for a in assertions],
            'anchors':[asdict(a) for a in authority.anchors],
            'dispositions':[asdict(d) for d in authority.dispositions],
            'coverage':[asdict(c) for c in authority.coverage],
            'relationships':[asdict(v) for v in authority.relationships]}
        empty_tax=[record for record in authority.figures if record.calculation_context=='accepted_empty_tax_event_set_v1']
        if empty_tax:
            data["tax_absence_rules"]=[{"record_id":record.record_id,"from":record.start,"to":record.end,
                "rule":record.calculation_context} for record in empty_tax]
        if premise is not None:
            point=next((v for v in authority.figures if v.claim=="allocation_percentage_points"),None)
            by_id={v.record_id:v for v in authority.figures}
            if point is None or len(point.operand_ids)!=3:raise ValueError("allocation comparison operand closure unavailable")
            numerator,total,weight=(by_id[key] for key in point.operand_ids)
            data["allocation_comparison"]={"operation":"100*(exposure_market_value/cash_inclusive_market_value-user_target_fraction)",
                "numerator_record_id":numerator.record_id,"numerator_value":numerator.value,
                "denominator_record_id":total.record_id,"denominator_value":total.value,
                "display_weight_record_id":weight.record_id,"premise_ref":premise.receipt_id,
                "target_numerator":str(premise.target_numerator),"target_denominator":str(premise.target_denominator),
                "exposure":premise.exposure,"account":premise.account,"currency":premise.currency,"snapshot_date":premise.as_of,
                "rounding":"Exact rational rounded directly to eight fractional percentage-point digits, HALF_EVEN",
                "exact":point.exact}
        result=ToolResult(TOOL,True,data=data,figures=figures,instrument_assertions=assertions,
            grade=weakest(f.get('grade','') for f in figures),dated=request.as_of or '',
            covers=[{'account':request.account,'from':request.start,'to':request.end}] if request.start else [],
            record_ids=sorted({a.document_id for a in authority.anchors}),
            provenance=[{'doc_id':a.document_id,'page':a.page} for a in authority.anchors],
            instrument_selection=authority if authority.focus is not None else None,
            instrument_premises=[_attest_premise(premise,runtime.question,run_token=runtime.run_token)] if premise is not None else [])
        if len(json.dumps({**result.to_dict(),'complete_figures':[dict(f) for f in result.figures]},ensure_ascii=False,separators=(',',':')).encode())>50000 or monotonic()>deadline:
            return refusal(TOOL,'resource_limit','The complete sourced instrument answer exceeds its read bound.')
        return result
    except (ValueError,TypeError,KeyError) as error:return refusal(TOOL,'instrument_evidence_unavailable',str(error))
