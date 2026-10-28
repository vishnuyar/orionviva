"""Closed scratch investment read adapter; no provider or mutable financial input."""
from time import monotonic
import json
import copy
from viva.tools.envelope import ToolResult,figure,bounded,refusal,entity
from viva.tools.registry import ToolSpec
from viva.instrument_evidence import _attest_figure
from .contracts import Request,EvidenceError,ResourceLimit,day,digest
from .sql import read_sql
from .authority import check

class InvestmentToolResult(ToolResult):
 def to_dict(self):
  out=super().to_dict()
  # Investment-only public reference; the complete sealed source pool is sent
  # once and private ToolResult provenance remains the ordinary full records.
  out['provenance']=[{'source_anchor_pool':'data.anchors'}]
  for emitted,source in zip(out['figures'],self.figures):
   emitted['subject']=copy.deepcopy(source.get('subject'))
   emitted['currency']=source.get('currency','')
   emitted['boundary']=copy.deepcopy(source.get('boundary',{}))
   emitted['authority_record_id']=source.get('authority_record_id','')
   emitted['source_lineage_digest']=source.get('source_lineage_digest','')
  return out

TOOL='read_investment_evidence'
_STRING={'type':'string','minLength':1}
_DATE={'type':'string','format':'date'}
PARAMS={'oneOf':[{'type':'object','additionalProperties':False,'properties':{'view':{'type':'string','enum':[view]},'account':_STRING,'currency':_STRING,**fields},'required':['view','account','currency',*fields]} for view,fields in [('positions',{'as_of':_DATE}),('activity_totals',{'from':_DATE,'to':_DATE,'grouping':{'type':'string','enum':['none','year']}})]]}
CLAIMS={'security_units':'security_units','holding_cost_basis':'holding_cost_basis','investment_contribution':'investment_contribution','investment_dividend':'investment_dividend','sale_proceeds':'sale_proceeds','disposed_cost_basis':'disposed_cost_basis','realized_gain':'realized_gain','investment_market_value':'balance','investment_holdings_count':'count'}

def result(connection,frontier,args,run_token,today,*,read_evidence=None,deadline=None):
 deadline=min(deadline,monotonic()+2) if deadline is not None else monotonic()+2
 try:
  request=Request.from_dict(args);day(today)
  if (request.as_of or request.end)>today:raise EvidenceError('requested date exceeds runtime horizon')
  raw=read_evidence(request,deadline) if read_evidence is not None else read_sql(connection,request,frontier,deadline=deadline)
  from .lineage import expand_anchors
  resolved_anchors=expand_anchors(raw)
  figures=[];securities={}
  for item in raw['figures']:
   check(deadline)
   claim={'balance':'investment_market_value','count':'investment_holdings_count'}.get(item['claim'],item['claim'])
   selected=[{'kind':'account','value':request.account}];cut=list(selected)
   if item['security']:cut.append({'kind':'security','value':item['security']})
   if item['from']:cut.append({'kind':'period','value':item['from'],'to':item['to']})
   sources=sorted({resolved_anchors[key]['document'] for key in item['anchor_ids']})
   plain=figure(item['value'],item['label'],quantity=item['quantity'],currency=item['currency'] or '',grade=item['grade'],dated=item['as_of'] or '',record_ids=sources,boundary=bounded(whole=False,selected=selected,cut=cut),subject={'account_id':request.account,**({'security_id':item['security']} if item['security'] else {})})
   if item['security']:
    securities[item['security']]=entity('security',account=request.account,security_id=item['security'],name=item['security_label'])
   plain.update(security_label=item['security_label'],authority_record_id=item['id'],anchor_ids=item['anchor_ids'],source_field_groups=item['source_field_groups'],observation_ids=item['observation_ids'],row_ids=item['row_ids'],funding_roles=item['funding_roles'],funding_dependency_ids=item['funding_dependency_ids'],operands=item['operands'])
   figures.append(_attest_figure(plain,claim,run_token=run_token))
  source_data={'view':request.view,'account':request.account,'currency':request.currency,'revision':raw.get('authenticated_revision',''),'anchors':raw['anchors'],'anchor_defaults':raw['anchor_defaults'],'source_fields':raw['source_fields'],'source_field_groups':raw['source_field_groups'],'source_identities':raw['source_identities'],'funding_dependencies':raw['funding_dependencies'],'dispositions':raw['dispositions'],'coverage':raw['coverage']}
  source_data['figure_source_columns']=['anchor_ids','source_field_groups','observation_ids','row_ids','funding_roles','funding_dependency_ids','operands']
  source_data['figure_sources']={item['authority_record_id']:[item[key] for key in source_data['figure_source_columns']] for item in figures}
  from .lineage import validate_result,lineage_digest
  validate_result({**raw,'figures':[dict(item) for item in figures]})
  source_digest=lineage_digest(source_data)
  figures=[_attest_figure({**dict(item),'source_lineage_digest':source_digest},item['claim'],run_token=run_token) for item in figures]
  output=InvestmentToolResult(TOOL,True,figures=figures,identifiers=list(securities.values()),data=source_data,record_ids=sorted({a['document'] for a in resolved_anchors.values()}),provenance=[{'doc_id':a['document'],'page':a['page']} for key,a in sorted(resolved_anchors.items())])
  if len(json.dumps(output.to_dict(),separators=(',',':'),ensure_ascii=False).encode())>32000:raise ResourceLimit('complete tool envelope byte bound')
  check(deadline);return output
 except ResourceLimit:return refusal(TOOL,'resource_limit','Complete investment evidence exceeds its read bound.')
 except (EvidenceError,ValueError,KeyError,TypeError):return refusal(TOOL,'investment_evidence_unavailable','The requested complete source evidence is unavailable.')

def spec(connection,frontier,run_token,today):
 return ToolSpec(TOOL,PARAMS,lambda args:result(connection,frontier,args,run_token,today),emits={'reference_kinds':['figure','read_figures'],'quantities':list(CLAIMS.values()),'entity_kinds':['account','security']},bounds={'max_payload_bytes':32000,'max_figures':64,'max_execution_ms':2000,'max_statements':120,'max_rows':1000,'max_positions':20,'max_groups':10,'max_anchors':512})


def runtime_result(runtime,args,today):
 from .authenticated import read as authenticated_read
 if runtime is None or runtime.revision is None:
  return refusal(TOOL,'current_data_unavailable','Current authenticated investment records are unavailable.')
 revision=runtime.revision
 deadline=min(runtime.deadline,runtime.started+2 if runtime.read_count==0 else monotonic()+2)
 runtime.read_count+=1
 try:
  return result(None,None,args,runtime.run_token,today,read_evidence=lambda request,cutoff:authenticated_read(revision._store,revision,request,deadline=cutoff),deadline=deadline)
 except Exception:
  return refusal(TOOL,'current_data_unavailable','Current authenticated investment records are unavailable.')

def runtime_spec(runtime,today):
 item=spec(None,None,None,today)
 item.fn=lambda args:runtime_result(runtime,args,today)
 return item
