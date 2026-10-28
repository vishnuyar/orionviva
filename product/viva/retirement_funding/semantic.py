"""Finite retirement-funding family with source and relationship-scoped bindings."""
from viva.answer_program.intents import _program, _read
from viva.investment.contracts import EvidenceError
from .contracts import Request, TOOL, ANNUAL, ROLLOVERS, NUMERIC_CLAIMS, ASSERTION_CLAIMS


def lower(manifest, args, claims):
    request = Request.from_dict(args)
    allowed = ('employee_retirement_contributions',) if request.view == ANNUAL else tuple(claim for claim in (*NUMERIC_CLAIMS, *ASSERTION_CLAIMS) if claim != 'employee_retirement_contributions')
    if type(claims) is not tuple or not claims or len(set(claims)) != len(claims) or any(claim not in allowed for claim in claims):
        raise EvidenceError('unsupported retirement funding claim')
    clauses = []; bindings = []
    for index, claim in enumerate(claims):
        hole = 'field' + chr(97 + index)
        text = ('Employee deductions in the accepted recorded annual payroll population paid into these selected plans' if claim == 'employee_retirement_contributions' else 'For each documented direct rollover, ' + claim.replace('_', ' '))
        clauses.append({'id': hole, 'text': text + ': {' + hole + '}.', 'slots': [{'name': hole, 'type': 'rows'}]})
        selector = {'cardinality': 'all', 'claim': claim, 'entity_ref': {'account_set_id': request.subject_id, 'set_type': 'retirement_plans', 'member_ids': sorted(request.plans)}}
        if claim in NUMERIC_CLAIMS:
            selector.update(quantity=NUMERIC_CLAIMS[claim], currency=request.currency, scope=['account_set', 'period'])
        bindings.append({'hole': hole, 'source': 'retirement', 'reference_kind': 'read_figures' if claim in NUMERIC_CLAIMS else ASSERTION_CLAIMS[claim], 'selector': selector})
    return _program(manifest, 'retirement_' + request.view, clauses, [_read('retirement', TOOL, args)], bindings, required=[clause['id'] for clause in clauses])


def families():
    from viva.answer_program.intents import SemanticFamily, _object, _STRING, _DATE
    from pathlib import Path
    from vivacore.promptstore import load
    from vivacore import versions
    package=Path(__file__).resolve().parent.parent
    label,_,example=load(package/'prompts',versions.active(package,'retirement_funding_semantic')).partition('\n')
    output = {}
    for view in (ANNUAL, ROLLOVERS):
        properties = {'plans_phrase':_STRING}
        properties.update({'year':_STRING} if view == ANNUAL else {'from': _DATE, 'to': _DATE})
        claims = ('employee_retirement_contributions',) if view == ANNUAL else tuple(claim for claim in (*NUMERIC_CLAIMS, *ASSERTION_CLAIMS) if claim != 'employee_retirement_contributions')
        name = 'retirement_' + view
        output[name] = SemanticFamily(name, _object(properties, tuple(properties)), claims, _build, user_label=label,user_example=example.strip())
    properties={'plans_phrase':_STRING,'from_year':_STRING,'to_year':_STRING}
    output['retirement_funding_report']=SemanticFamily('retirement_funding_report',_object(properties,tuple(properties)),tuple((*NUMERIC_CLAIMS,*ASSERTION_CLAIMS)),build_report,user_label=label,user_example=example.strip())
    return output


def _build(request, manifest):
    parameters = request.parameters
    args = {'view': request.family.removeprefix('retirement_'), 'plans': parameters['plans'], 'currency': parameters['currency']}
    args.update({key: parameters[key] for key in ('from', 'to') if key in parameters})
    if 'year' in parameters:args['year']=int(parameters['year'])
    return lower(manifest, args, request.requested_claims)


def samples():
    return {'retirement_funding_report':{'plans_phrase':'retirement-set-example','from_year':'2000','to_year':'2004'},'retirement_' + ANNUAL: {'plans_phrase':'retirement-set-example','year':'2000'}, 'retirement_' + ROLLOVERS: {'plans_phrase':'retirement-set-example','from': '2000-01-01', 'to': '2000-12-31'}}


def build_report(request,manifest):
    from copy import deepcopy
    from viva.answer_program.intents import _program
    from viva.investment.contracts import EvidenceError
    import re
    parameters=request.parameters
    first,last=parameters['from_year'],parameters['to_year']
    if any(type(value) is not str or re.fullmatch(r'[0-9]{4}',value) is None for value in (first,last)):
        raise EvidenceError('quoted complete calendar-year bounds required')
    first,last=int(first),int(last)
    if not 1<=first<=last<=9998 or last-first>=5:raise EvidenceError('retirement report requires one to five complete years')
    claims=request.requested_claims
    if not claims or len(set(claims))!=len(claims) or any(claim not in (*NUMERIC_CLAIMS,*ASSERTION_CLAIMS) for claim in claims):raise EvidenceError('unsupported retirement report claim')
    programs=[]
    if 'employee_retirement_contributions' in claims:
        for year in range(first,last+1):
            programs.append(lower(manifest,{'view':ANNUAL,'plans':parameters['plans'],'currency':parameters['currency'],'year':year},('employee_retirement_contributions',)))
    rollover_claims=tuple(claim for claim in claims if claim!='employee_retirement_contributions')
    if rollover_claims:
        programs.append(lower(manifest,{'view':ROLLOVERS,'plans':parameters['plans'],'currency':parameters['currency'],'from':f'{first:04d}-01-01','to':f'{last:04d}-12-31'},rollover_claims))
    clauses=[];nodes=[];bindings=[];annual_clauses=[]
    for index,program in enumerate(programs):
        prefix='part'+chr(97+index)+'_';data=deepcopy(program.to_dict())
        for clause in data['shape']['clauses']:
            clause['id']=prefix+clause['id']
            for slot in clause['slots']:
                previous=slot['name'];slot['name']=prefix+previous;clause['text']=clause['text'].replace('{'+previous+'}','{'+slot['name']+'}')
            if data['question_kind']=='retirement_'+ANNUAL:annual_clauses.append(clause)
            else:clauses.append(clause)
        for node in data['nodes']:
            node['id']=prefix+node['id'];node['depends_on']=[nodes[-1]['id']] if nodes else [];nodes.append(node)
        for binding in data['bindings']:
            binding['hole']=prefix+binding['hole'];binding['source']=prefix+binding['source'];bindings.append(binding)
    if annual_clauses:
        slots=[slot for clause in annual_clauses for slot in clause['slots']]
        clauses.insert(0,{'id':annual_clauses[0]['id'],'text':'Recorded annual employee contributions for the selected plans: '+ ' '.join('{'+slot['name']+'}' for slot in slots)+'.','slots':slots})
    return _program(manifest,'retirement_funding_report',clauses,nodes,bindings,required=[clause['id'] for clause in clauses])
