"""Finite deterministic lowering of source investment report claims."""
from viva.answer_program.intents import _program,_read
from .tool import CLAIMS
from .contracts import EvidenceError,Request


def lower(manifest,args,claims):
 request=Request.from_dict(args)
 permitted=('security_units','investment_market_value','holding_cost_basis','investment_holdings_count') if request.view=='positions' else ('investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain')
 if type(claims) is not tuple or not claims or len(set(claims))!=len(claims) or any(c not in permitted for c in claims):raise EvidenceError('unsupported investment report claim')
 clauses=[];bindings=[]
 for index,claim in enumerate(claims):
  hole='field'+chr(97+index);scope=['account']+(['security'] if request.view=='positions' and claim!='investment_holdings_count' else ['period'] if request.view=='activity_totals' else [])
  selector={'cardinality':'all','claim':claim,'quantity':CLAIMS[claim],'scope':scope,'entity_ref':{'id':request.account}}
  if CLAIMS[claim] not in ('security_units','count'):selector['currency']=request.currency
  caption='Derived disposed cost basis' if claim=='disposed_cost_basis' else claim.replace('_',' ')
  clauses.append({'id':hole,'text':caption+': {'+hole+'}.','slots':[{'name':hole,'type':'rows'}]})
  bindings.append({'hole':hole,'source':'investment','reference_kind':'read_figures','selector':selector})
 return _program(manifest,'investment_'+request.view,clauses,[_read('investment','read_investment_evidence',args)],bindings,required=[c['id'] for c in clauses])

VIEW_CLAIMS={'positions':('security_units','investment_market_value','holding_cost_basis','investment_holdings_count'),'activity_totals':('investment_contribution','investment_dividend','sale_proceeds','disposed_cost_basis','realized_gain')}

def families():
 from viva.answer_program.intents import SemanticFamily,_object,_STRING,_DATE
 output={}
 for view,claims in VIEW_CLAIMS.items():
  fields={'account_phrase':_STRING}
  if view=='positions':fields['as_of']=_DATE
  else:fields.update({'from':_DATE,'to':_DATE,'grouping':{'type':'string','enum':['none','year']}})
  name='investment_'+view
  output[name]=SemanticFamily(name,_object(fields,tuple(fields)),claims,_build,user_label='source-backed investment '+view.replace('_',' '),user_example='read one selected investment account over explicit dates; preserve security units, basis and activity field identities')
 from .composition import families as report_families
 output.update(report_families())
 return output

def _build(request,manifest):
 p=request.parameters;view=request.family.removeprefix('investment_')
 args={'view':view,'account':p['account_phrase'],'currency':p['currency']}
 for key in ('as_of','from','to','grouping'):
  if key in p:args[key]=p[key]
 return lower(manifest,args,request.requested_claims)


def samples():
 from .composition import samples as report_samples
 return {'investment_positions':{'account_phrase':'account-investment','as_of':'2000-12-31'},'investment_activity_totals':{'account_phrase':'account-investment','from':'2000-01-01','to':'2000-12-31','grouping':'year'},**report_samples()}
