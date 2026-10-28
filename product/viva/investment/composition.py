"""Finite independent dispatches; no stale-result merge or generic arithmetic."""
from datetime import date
from copy import deepcopy
from .contracts import EvidenceError,day

REPORT_CLAIMS=('holdings','annual_activity','recorded_cash','account_value','allocation_exposure')
REPORTS=('investment_account_report','investment_account_report_first_years','investment_account_report_remaining_years')


def families():
 from viva.answer_program.intents import SemanticFamily,_object,_STRING,_DATE
 output={}
 for name in REPORTS:
  remaining=name.endswith('remaining_years')
  fields={'account_phrase':_STRING,'from':_DATE,'to':_DATE}
  if not remaining:fields['as_of']=_DATE
  output[name]=SemanticFamily(name,_object(fields,tuple(fields)),('annual_activity',) if remaining else REPORT_CLAIMS,build,
   user_label='investment report: '+('remaining one to three complete years' if remaining else 'holdings and first one or two complete years' if name.endswith('first_years') else 'whole requested period with holdings'),
   user_example='Select one held investment account and explicit inclusive calendar-year dates. Holdings and exposure use their explicit snapshot date; recorded cash retains its own measurement date. First-years and remaining-years reports are separate complete answers, never a hidden partial page.')
 return output


def samples():
 return {name:{'account_phrase':'account-investment','from':'2000-01-01','to':'2002-12-31' if name.endswith('remaining_years') else '2001-12-31',**({} if name.endswith('remaining_years') else {'as_of':'2004-12-31'})} for name in REPORTS}


def build(request,manifest):
 from viva.answer_program.intents import _program,_read,SemanticRequest
 from viva.answer_program.instrument_families import _build as instrument_build
 from .semantic import lower,VIEW_CLAIMS
 p=request.parameters;account=p['account_phrase'];currency=p['currency'];start=day(p['from']);end=day(p['to'])
 if request.family not in REPORTS or start>end or not start.endswith('-01-01') or not end.endswith('-12-31') or (date.fromisoformat(end)-date.fromisoformat(start)).days+1>3660:raise EvidenceError('complete bounded calendar years required')
 years=tuple(range(int(start[:4]),int(end[:4])+1));remaining=request.family.endswith('remaining_years');split=request.family!='investment_account_report'
 if remaining and len(years)>3 or request.family.endswith('first_years') and len(years)>2:raise EvidenceError('requested year set exceeds this independent dispatch')
 if not remaining and day(p['as_of'])<end:raise EvidenceError('snapshot precedes requested report period')
 claims=request.requested_claims;permitted=('annual_activity',) if remaining else REPORT_CLAIMS
 if not claims or len(set(claims))!=len(claims) or any(claim not in permitted for claim in claims):raise EvidenceError('unsupported composed investment claim')
 clauses=[];nodes=[];bindings=[]
 def add(program,prefix):
  data=deepcopy(program.to_dict())
  packed=[]
  for clause in data['shape']['clauses']:
   clause['id']=prefix+clause['id']
   for slot in clause['slots']:
    old=slot['name'];slot['name']=prefix+old;clause['text']=clause['text'].replace('{'+old+'}','{'+slot['name']+'}')
   if packed and len(packed[-1]['text'])+1+len(clause['text'])<=400:
    packed[-1]['text']+=' '+clause['text'];packed[-1]['slots'].extend(clause['slots'])
   else:packed.append(clause)
  clauses.extend(packed)
  for node in data['nodes']:
   node['id']=prefix+node['id'];node['depends_on']=[prefix+key for key in node['depends_on']];nodes.append(node)
  for binding in data['bindings']:
   binding['hole']=prefix+binding['hole'];binding['source']=prefix+binding['source'];bindings.append(binding)
 if 'holdings' in claims:add(lower(manifest,{'view':'positions','account':account,'currency':currency,'as_of':p['as_of']},VIEW_CLAIMS['positions']),'holdings_')
 if 'annual_activity' in claims:
  periods=[(str(year)+'-01-01',str(year)+'-12-31') for year in years] if split else [(start,end)]
  for index,(left,right) in enumerate(periods):add(lower(manifest,{'view':'activity_totals','account':account,'currency':currency,'from':left,'to':right,'grouping':'year'},VIEW_CLAIMS['activity_totals']),'annual'+chr(97+index)+'_')
 for claim,view in (('recorded_cash','recorded_cash'),('account_value','account_value_history')):
  if claim not in claims:continue
  args={'view':view,'account':account,'currency':currency}
  if claim=='account_value':args.update({'from':p['as_of'],'to':p['as_of']})
  hole=claim+'_rows';node=claim+'_read'
  clauses.append({'id':claim,'text':('Recorded cash at its own measured date: ' if claim=='recorded_cash' else 'Source account value at the requested snapshot date: ')+'{'+hole+'}.','slots':[{'name':hole,'type':'rows'}]})
  nodes.append(_read(node,'read_account_measurements',args))
  bindings.append({'hole':hole,'source':node,'reference_kind':'read_figures','selector':{'cardinality':'all','quantity':'balance','scope':['account'],'entity_ref':{'id':account},'currency':currency}})
 if 'allocation_exposure' in claims:
  allocation_claims=('allocation_total_value','allocation_unclassified_value')+tuple('allocation_exposure_'+kind+'_'+measure for kind in ('bond','equity','cash','other','unknown') for measure in ('value','weight'))
  child=SemanticRequest('instrument_allocation',{'account_phrase':account,'currency':currency,'as_of':p['as_of'],'axis':'exposure'},allocation_claims,request.catalog_digest)
  add(instrument_build(child,manifest),'exposure_')
 return _program(manifest,request.family,clauses,nodes,bindings,required=[clause['id'] for clause in clauses])
