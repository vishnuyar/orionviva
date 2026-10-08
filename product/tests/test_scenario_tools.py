"""Scenarios preserve quoted premises and reconcile actual modeled cents."""
from decimal import Decimal
import copy
import json
from dataclasses import replace
from types import SimpleNamespace
import pytest


def test_savings_reconciles_rounded_interest_and_endpoint_contributions():
    from viva.ledger.scenarios import savings
    result = savings('1000','50','12','2','2026-01-31')
    assert result['final_balance'] == '1120.60'
    assert result['contributed_principal'] == '1100.00'
    assert result['growth'] == '20.60'
    assert [r['date'] for r in result['trajectory']] == ['2026-02-28','2026-03-31']


def test_partial_final_payment_and_zero_opening_have_honest_payoff():
    from viva.ledger.scenarios import loan_payoff
    result = loan_payoff('1000','600','12','3','2026-01-31')
    assert (result['remaining_debt'],result['interest_paid'],result['repayments_paid'],result['payment_count'],result['payoff_date']) == ('0.00','14.10','1014.10',2,'2026-02-28')
    zero = loan_payoff('0','0','12','3','2026-01-31')
    assert zero['payment_count'] == 0 and zero['payoff_date'] == ''


def test_renderer_preserves_valid_large_cent_amount_without_ambient_rounding():
    from viva.render import money
    assert str(money('1234567890123456789012345678901234567.89','USD',locale='en-US')) == 'USD 1,234,567,890,123,456,789,012,345,678,901,234,567.89'


def test_recorded_owed_has_accepted_source_authority():
    from test_measurement_tools import _measure_registry
    result = _measure_registry().call('read_account_measurements',{'view':'recorded_owed','account':'loan'})
    assert result.ok, result.refusal
    assert [(f['value'],f['quantity'],f['dated'],f['record_ids']) for f in result.figures] == [('30','owed','2026-01-31',['loan-doc'])]


def test_default_expanded_admission_keeps_canonical_and_requires_all_new_cases():
    from viva.answer_program.eval import load_cases, load_canonical_cases
    canonical=load_canonical_cases()
    combined=load_cases()
    assert len(canonical)==73 and len(combined)==123
    assert combined[:73]==canonical
    assert len({case.id for case in combined})==123


def test_independent_capability_contracts_all_have_executable_paths():
    from viva.answer_program.eval import load_supplement_cases, resolve_case_fixture, derive_semantic_oracle
    from viva.answer_program.capability import CapabilityManifest
    from viva.answer_program.schema import AnswerResourcePolicy
    failures=[]
    for case in load_supplement_cases():
        try:
            factory,day=resolve_case_fixture(case)
            assert day=='2026-02-01'
            registry=factory()
            oracle=derive_semantic_oracle(case,registry,CapabilityManifest.from_registry(registry),AnswerResourcePolicy(),locale='en-US')
            assert oracle['figures']==case.supplement_contract['expected_figures']
        except Exception as error:
            failures.append((case.id,type(error).__name__,str(error)))
    assert not failures, "\n".join(str(item) for item in failures)


def _case(fragment='savings_monthly_one_percent'):
    from viva.answer_program.eval import load_supplement_cases
    cases=[c for c in load_supplement_cases() if fragment in c.id]
    assert len(cases)==1, [c.id for c in cases]
    return cases[0]


def _scenario_args(case):
    return {'view':case.expected_family,'parameters':copy.deepcopy(case.expected_parameters),
            'parameter_sources':copy.deepcopy(case.parameter_sources)}


@pytest.mark.parametrize('bad', ['-0','-1','1e3','NaN','Infinity','1000000000000000','0.1234567'])
def test_money_domain_rejects_nonfinite_sign_notation_and_excess_precision(bad):
    from viva.ledger.scenarios import savings, ScenarioError
    with pytest.raises(ScenarioError): savings(bad,'1','1','2','2026-01-31')


def test_fractional_cent_reconciliation_and_calendar_edges_are_independent():
    from viva.ledger.scenarios import savings,loan_payoff,cash_flow,ScenarioError
    result=savings('1.005','0.015','0','3','2024-01-31')
    assert (result['final_balance'],result['contributed_principal'],result['growth'])==('1.06','1.06','0.00')
    assert [r['date'] for r in result['trajectory']]==['2024-02-29','2024-03-31','2024-04-30']
    loan=loan_payoff('1000','100','12','2','2026-01-31')
    assert (loan['remaining_debt'],loan['interest_paid'],loan['repayments_paid'],loan['payment_count'],loan['payoff_date'])==('819.10','19.10','200.00',2,'')
    assert Decimal('1000')+Decimal(loan['interest_paid'])==Decimal(loan['remaining_debt'])+Decimal(loan['repayments_paid'])
    cash=cash_flow('100','0','60','0','1','3','2024-01-31')
    assert (cash['minimum_cash'],cash['minimum_date'],cash['first_negative_date'])==('-80.00','2024-04-30','2024-03-31')
    with pytest.raises(ScenarioError,match='scenario_calendar_range_unavailable'):
        savings('1','1','0','2','9999-12-31')
    with pytest.raises(ScenarioError,match='scenario_payment_rounds_to_zero'):
        loan_payoff('1','0.004','0','2','2026-01-31')


def test_maximum_money_rate_horizon_is_renderable_with_sampled_landmarks():
    from viva.ledger.scenarios import savings
    from viva.render import money
    result=savings('999999999999999','999999999999999','100','600','2026-01-31')
    assert len(result['trajectory'])<=24 and result['trajectory_sampled']
    assert result['trajectory'][-1]['date']==result['horizon_date']=='2076-01-31'
    rendered=str(money(result['final_balance'],'USD',locale='en-US'))
    assert rendered.startswith('USD ') and rendered.endswith(result['final_balance'][-3:])


@pytest.mark.parametrize('mutation', ['swap_role','wrong_sign','rate_scale','prior','fragment','missing_proof','duplicate_role','negated','quoted','unrelated','date_fragment','wrong_date_role','unsupported_rate','mismatched_currency','duration_ordinal'])
def test_current_question_complete_roles_are_required_even_for_direct_calls(mutation):
    from viva.tools.scenarios import simulate_scenario
    case=_case(); args=_scenario_args(case); question=case.question
    parameters=args['parameters']; proofs=args['parameter_sources']
    if mutation=='swap_role': proofs['initial_amount']=copy.deepcopy(proofs['monthly_contribution'])
    elif mutation=='wrong_sign': parameters['initial_amount']='-'+parameters['initial_amount']
    elif mutation=='rate_scale': parameters['nominal_annual_rate_percent']='0.12'
    elif mutation=='prior': proofs['initial_amount']['source']='prior_assistant';proofs['initial_amount']['turn']=0
    elif mutation=='fragment': proofs['initial_amount']['quote']='USD '+parameters['initial_amount']
    elif mutation=='missing_proof': proofs.pop('initial_amount')
    elif mutation=='duplicate_role': question+='; '+proofs['initial_amount']['quote']
    elif mutation=='negated': question=question.replace('initial amount','not initial amount')
    elif mutation=='quoted': question='"'+question+'"'
    elif mutation=='unrelated': question+='; unrelated amount USD 1000'
    elif mutation=='date_fragment': proofs['start_date']['quote']=parameters['start_date']
    elif mutation=='wrong_date_role': question=question.replace('opening date','measurement date')
    elif mutation=='unsupported_rate': question=question.replace('nominal annual rate','APY')
    elif mutation=='mismatched_currency': question=question.replace('initial amount USD','initial amount EUR')
    elif mutation=='duration_ordinal': proofs['months']['quote']='one-off at month '+parameters['months']
    result=simulate_scenario(args,{},question)
    assert not result.ok and not result.figures, mutation
    assert result.text and 'Resubmit the whole scenario.' in result.text, (mutation,result.to_dict())


def test_current_question_semantics_still_ground_with_require_grounding_false():
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.eval import resolve_case_fixture
    from viva.answer_program.schema import QuestionContext
    case=_case();factory,_=resolve_case_fixture(case);families=SemanticFamilyRegistry(factory().semantic_entities())
    raw={'request_version':families.output_schema()['oneOf'][0]['properties']['request_version']['enum'][0],
         'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,
         'family':case.expected_family,'parameters':copy.deepcopy(case.expected_parameters),
         'parameter_sources':copy.deepcopy(case.parameter_sources),'requested_claims':list(case.required_claims)}
    assert families.parse(raw,QuestionContext(question=case.question),require_grounding=False).kind=='request'
    for question in ('',case.question.replace('initial amount','monthly income')):
        outcome=families.parse(raw,QuestionContext(question=question),require_grounding=False)
        assert outcome.kind=='needs_assumption' and outcome.detail['scenario_family']==case.expected_family


def test_reserved_figure_export_cannot_be_forged_before_stamp_or_on_failed_plural_results():
    from viva.answer_program.execute import ProgramExecutor
    from viva.tools.envelope import ToolResult
    figure={'value':'1','quantity':'balance','kind':'financial'}
    for result in (ToolResult(tool='test',ok=True,data={'unique_figure_id':'forged'}),
                   ToolResult(tool='test',ok=True,figures=[figure],data={'unique_figure_id':'forged'}),
                   ToolResult(tool='test',ok=False,figures=[{**figure,'id':'stamped'}],data={'unique_figure_id':'forged'}),
                   ToolResult(tool='test',ok=True,figures=[{**figure,'id':'a'},{**figure,'id':'b'}],data={'unique_figure_id':'forged'})):
        assert 'unique_figure_id' not in ProgramExecutor._values(result)
    result=ToolResult(tool='test',ok=True,figures=[{**figure,'id':'stamped'}],data={'unique_figure_id':'forged','other':2})
    assert ProgramExecutor._values(result)['unique_figure_id']=='stamped'
    assert ProgramExecutor._values(result)['other']==2


@pytest.mark.parametrize('field,value', [('read_day','2026-03-01'),('fixture_selector','financial-capability-fixture-v1:empty'),('case_marker',''),('question','Easier question')])
def test_supplement_fixture_selector_day_and_identity_cannot_be_substituted(field,value):
    from viva.answer_program.eval import resolve_case_fixture
    with pytest.raises(ValueError): resolve_case_fixture(replace(_case(),**{field:value}))


@pytest.mark.parametrize('field,value', [('what','hypothetical contributed principal — 2026-03-31'),('kind','financial'),('quantity','income'),('dated','2026-01-31'),('currency','EUR'),('grade','verified'),('record_ids',['forged']),('value','0')])
def test_independent_figure_oracle_rejects_role_kind_quantity_date_currency_grade_source_and_value(field,value):
    from viva.answer_program.eval import _supplement_figure_matches
    expected=copy.deepcopy(_case().supplement_contract['expected_figures'][0])
    actual={'value':expected['value'],'what':expected['what_exact'],'kind':expected['kind'],'quantity':expected['quantity'],
            'dated':expected['dated'],'currency':expected['currency'],'grade':expected['required_grade'],
            'record_ids':expected['required_sources']['record_ids'],
            'boundary':{'whole':expected['required_boundary']['whole'],
                        'selected':expected['required_boundary']['selected_exact'],'cut':expected['required_boundary']['cut_exact']}}
    assert _supplement_figure_matches(actual,expected)
    actual[field]=value
    assert not _supplement_figure_matches(actual,expected)


def _parsed_scenario(case):
    from viva.answer_program.eval import resolve_case_fixture
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.capability import CapabilityManifest
    from viva.answer_program.schema import QuestionContext
    factory,day=resolve_case_fixture(case); registry=factory()
    families=SemanticFamilyRegistry(registry.semantic_entities())
    raw={'request_version':families.output_schema()['oneOf'][0]['properties']['request_version']['enum'][0],
         'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,
         'family':case.expected_family,'parameters':copy.deepcopy(case.expected_parameters),
         'parameter_sources':copy.deepcopy(case.parameter_sources),'requested_claims':list(case.required_claims)}
    for key,proof in raw['parameter_sources'].items():
        if key=='account_phrase' and proof['derivation']=='catalog_selection':
            candidates=families._account_role_candidates(raw['parameters'][key]); assert len(candidates)==1
            raw['parameters'][key]=candidates[0]['id']
    semantic=families.parse(raw,QuestionContext(question=case.question,today=day))
    return registry,raw,semantic,families.lower(semantic,CapabilityManifest.from_registry(registry))


def test_measured_scenario_exports_stamped_id_and_memoization_keeps_identity():
    from viva.answer_program.execute import ProgramExecutor
    from viva.answer_program.schema import AnswerResourcePolicy
    case=_case('checking_savings_zero_rate'); registry,raw,semantic,program=_parsed_scenario(case)
    original=program.nodes[0]
    extra=replace(original,id='same_measurement')
    program=replace(program,nodes=(original,extra,*program.nodes[1:]))
    execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,case.question)
    measured=execution.nodes['starting_measurement']; alias=execution.nodes['same_measurement']
    assert measured.status=='completed' and alias.status=='memoized'
    fid=measured.values['unique_figure_id']
    assert alias.values['unique_figure_id']==fid
    assert fid in execution.graph.book and execution.graph.book[fid]['quantity']=='balance'
    scenario=next(row for row in execution.transcript if row.tool=='simulate_scenario')
    assert scenario.ok and scenario.data['assumption_receipt']['observed_start']['id']==fid
    assert scenario.data['assumption_receipt']['exact_proofs']['account_phrase']['quote']=='Example Checking'


@pytest.mark.parametrize('mutation',['investment_total','owed','wrong_account','wrong_currency','missing_source','missing_date','hypothetical','negative','unresolved_symbolic','missing_view','history_view','prior_identity'])
def test_direct_measured_start_requires_same_run_compatible_sourced_stock(mutation):
    from viva.answer_program.execute import ProgramExecutor
    from viva.answer_program.schema import AnswerResourcePolicy
    from viva.tools.scenarios import simulate_scenario
    case=_case('checking_savings_zero_rate');registry,raw,semantic,program=_parsed_scenario(case)
    execution=ProgramExecutor(registry,AnswerResourcePolicy()).execute(program,case.question)
    fid=execution.nodes['starting_measurement'].values['unique_figure_id']
    figure=copy.deepcopy(execution.graph.book[fid]);args=copy.deepcopy(program.nodes[-1].args);args['starting_figure']=fid
    if mutation=='investment_total': figure['quantity']='invested_value'
    elif mutation=='owed': figure['quantity']='owed'
    elif mutation=='wrong_account': figure['boundary']['selected'][0]['value']='other'
    elif mutation=='wrong_currency': figure['currency']='EUR'
    elif mutation=='missing_source': figure['record_ids']=[]
    elif mutation=='missing_date': figure['dated']=''
    elif mutation=='hypothetical': figure['kind']='hypothetical'
    elif mutation=='negative': figure['value']='-1'
    elif mutation=='missing_view': figure.pop('measurement_view')
    elif mutation=='history_view': figure['measurement_view']='account_value_history'
    elif mutation=='prior_identity': figure['id']='prior-run-figure'
    elif mutation=='unresolved_symbolic': args['starting_figure']={'ref':{'node':'starting_measurement','value':'unique_figure_id'}}
    result=registry.call('simulate_scenario',args,figures={fid:figure},question=case.question)
    assert not result.ok and not result.figures


@pytest.mark.parametrize('mutation',['missing_question','altered_amount','wrong_date','prior_assistant'])
def test_captured_scenario_replay_refuses_changed_current_question_before_any_reads(mutation):
    from viva.answer_program.replay import replay_capture
    case=_case();registry,raw,semantic,program=_parsed_scenario(case)
    payload={'question':case.question,'semantic_request':raw,'program':program.to_dict()}
    assert replay_capture(payload,registry,locale='en-US')['replayed']
    if mutation=='missing_question': payload.pop('question')
    elif mutation=='altered_amount': payload['question']=case.question.replace('initial amount USD 1000','initial amount USD 1001')
    elif mutation=='wrong_date': payload['question']=case.question.replace('2026-01-31','2026-01-30')
    else:
        payload['semantic_request']['parameter_sources']['initial_amount']={'source':'prior_assistant','quote':'1000','derivation':'verbatim','turn':0}
    registry.call=lambda *a,**k:pytest.fail('a rejected captured premise must not read')
    assert not replay_capture(payload,registry,locale='en-US')['replayed']


@pytest.mark.parametrize('key',['scenario_calculators','scenario_tools','capability_fixture','admission_fixture','admission_gate','admission_evaluation','movement_identity','typed_events','posting_construction'])
@pytest.mark.parametrize('mutation',['changed','missing'])
def test_each_new_or_reused_source_authority_is_exact_bytes_and_missing_bytes_fail_closed(monkeypatch,key,mutation):
    import hashlib
    from pathlib import Path
    from viva.answer_program.intents import SemanticFamilyRegistry
    families=SemanticFamilyRegistry(); before=families._admitted_implementation_digests()
    original=Path.read_bytes
    def altered(path):
        data=original(path)
        if hashlib.sha256(data).hexdigest()[:16]==before[key]:
            if mutation=='missing': raise FileNotFoundError(str(path))
            return data+b'\n# controlled numerical-source counterfactual\n'
        return data
    monkeypatch.setattr(Path,'read_bytes',altered)
    if mutation=='missing':
        with pytest.raises(FileNotFoundError): families._admitted_implementation_digests()
    else:
        after=families._admitted_implementation_digests()
        assert after[key]!=before[key]
        assert {k:v for k,v in before.items() if k!=key}=={k:v for k,v in after.items() if k!=key}


def test_original_cohort_scores_cannot_qualify_expanded_catalog():
    from viva.answer_program.eval import load_canonical_cases,CaseScore
    from viva.answer_program import evaluate_admission,AdmissionThresholds,validate_admission_report
    cases=load_canonical_cases()
    report=evaluate_admission([CaseScore(c.id,True,True,(),0,0) for c in cases],
        attempts=[1]*73,first_attempt_valid=[True]*73,thresholds=AdmissionThresholds(1,1,1))
    assert 'incomplete_keyed_corpus' in validate_admission_report(report)


def test_recorded_owed_zero_corrected_source_and_complete_byte_bound():
    from _tool_test_support import account_opened,closing_balance_observed,document_captured,LedgerProjection,Provenance
    from viva.tools import default_registry
    from test_measurement_tools import _measure_registry
    zero=_measure_registry([closing_balance_observed('loan','0','2026-01-30',Provenance('loan-doc'),confirmed_by='human')]).call('read_account_measurements',{'view':'recorded_owed','account':'loan'})
    assert zero.ok and zero.figures[0]['value']=='0' and zero.figures[0]['dated']=='2026-01-30'
    reg=default_registry(LedgerProjection([
        account_opened('loan','liability','L'*60000,'USD','2026-01-01'),
        document_captured('debt-source','debt.pdf',100,'loan_statement',1,'2026-02-01'),
        closing_balance_observed('loan','1','2026-01-31',Provenance('debt-source'))]))
    result=reg.call('read_account_measurements',{'view':'recorded_owed','account':'loan'})
    assert not result.ok and result.refusal=='owed_payload_limit' and not result.figures
    assert 'debt measurement' in result.text


def test_registry_failed_scenario_validation_preserves_strict_schema_and_does_not_dispatch():
    from viva.answer_program.eval import resolve_case_fixture
    from viva.tools.registry import _validate
    from viva.tools.scenarios import SCENARIO_PARAMS,scenario_request
    case=_case();factory,_=resolve_case_fixture(case);registry=factory()
    args=_scenario_args(case);args['parameter_sources']['initial_amount']['turn']=0
    assert _validate(SCENARIO_PARAMS,args) and registry.validate('simulate_scenario',args)
    registry._specs['simulate_scenario']=replace(registry._specs['simulate_scenario'],fn=lambda *a:pytest.fail('invalid source must not dispatch'))
    result=registry.call('simulate_scenario',args,question=case.question)
    assert not result.ok and not result.figures and result.refusal=='scenario_premise_source_mismatch'
    assert result.text==scenario_request(result.refusal,case.expected_family)
    for args in ({'parameters':{}},{'view':'unknown'}):
        result=registry.call('simulate_scenario',args)
        assert result.refusal=='invalid_arguments' and result.data['schema']==SCENARIO_PARAMS
    result=registry.call('query_ledger',{'unexpected':True})
    assert result.refusal=='invalid_arguments' and "unknown field 'unexpected'" in result.text
    assert result.data['schema']==registry._specs['query_ledger'].params


def test_maximum_supported_scenario_has_useful_complete_bounded_payload():
    from viva.tools.scenarios import simulate_scenario
    case=_case();args=_scenario_args(case);question=case.question
    for key,value in {'initial_amount':'999999999999999','monthly_contribution':'999999999999999','months':'600','nominal_annual_rate_percent':'100'}.items():
        old=args['parameter_sources'][key]['quote']
        new=old.replace(args['parameters'][key],value)
        args['parameters'][key]=value;args['parameter_sources'][key]['quote']=new;question=question.replace(old,new)
    result=simulate_scenario(args,{},question)
    assert result.ok,result.to_dict()
    assert len(json.dumps(result.to_dict()).encode())<=10000
    assert len(result.figures)==3 and len(result.data['trajectory'])<=24


def test_whole_investment_value_cannot_replace_recorded_cash_with_identical_axes():
    from viva.answer_program.evidence import EvidenceGraph
    from viva.tools.scenarios import simulate_scenario
    case=_case('brokerage_cash_savings_monthly_rate');registry,raw,semantic,program=_parsed_scenario(case)
    history=registry.call('read_account_measurements',{'view':'account_value_history','account':'cap-investment','from':'2026-01-31','to':'2026-01-31'})
    assert history.ok and history.figures[0]['quantity']=='balance' and history.figures[0]['value']=='200'
    graph=EvidenceGraph(case.question);graph.stamp('whole_value',history)
    args=copy.deepcopy(program.nodes[-1].args);args['starting_figure']=history.figures[0]['id']
    result=registry.call('simulate_scenario',args,figures=graph.book,question=case.question)
    assert not result.ok and result.refusal=='scenario_premise_source_mismatch' and not result.figures


def _runtime_scenario(case):
    from viva.answer_program.runtime import AnswerProgramRuntime
    from viva.answer_program.execute import ProgramExecutor
    from viva.answer_program.bind import DeterministicBinder
    from viva.answer_program.schema import AnswerResourcePolicy,QuestionContext
    registry,raw,semantic,program=_parsed_scenario(case)
    policy=AnswerResourcePolicy()
    compilation=SimpleNamespace(ok=True,program=program,semantic_outcome=semantic,validation=None,exchanges=[SimpleNamespace(defect={})])
    runtime=AnswerProgramRuntime(SimpleNamespace(compile=lambda context:compilation),
        ProgramExecutor(registry,policy),DeterministicBinder(registry,'en-US'))
    return runtime.answer(QuestionContext(question=case.question,today=case.read_day)),semantic


@pytest.mark.parametrize('mutation',['raw','role','unit','origin','quote','proof_source','proof_date','flags','missing_receipt','summary_role','trajectory','zero_kind'])
def test_supplement_scoring_requires_complete_literal_receipts_and_output_semantics(mutation):
    from viva.answer_program.eval import score
    case=_case();actual,semantic=_runtime_scenario(case)
    case=replace(case,oracle={'supplement_contract':copy.deepcopy(case.supplement_contract)})
    assert score(case,actual).passed
    data=next(row for row in actual.result.transcript if row['tool']=='simulate_scenario')['data']
    receipt=data['assumption_receipt'];numeric=receipt['exact_numeric_inputs']['initial_amount']
    if mutation=='raw': numeric['raw']='999'
    elif mutation=='role': numeric['role']='monthly contribution'
    elif mutation=='unit': numeric['currency']='EUR'
    elif mutation=='origin': numeric['origin']='prior_assistant'
    elif mutation=='quote': numeric['quote']='monthly contribution USD 50'
    elif mutation=='proof_source': receipt['exact_proofs']['initial_amount']['source']='prior_assistant'
    elif mutation=='proof_date': receipt['exact_proofs']['start_date']['quote']='opening date 2026-01-30'
    elif mutation=='flags': receipt['current_question_only']=False
    elif mutation=='missing_receipt': data.pop('assumption_receipt')
    elif mutation=='summary_role': actual.result.figures[0]['what']=actual.result.figures[1]['what']
    elif mutation=='trajectory': data['growth']='999'
    else:
        actual.result.figures[0].update(value='0',kind='financial',grade='verified',record_ids=[])
    scored=score(case,actual)
    assert not scored.passed and scored.financial_integrity_errors>0,(mutation,scored)


def test_grouping_plus_sign_and_calendar_edge_keep_exact_supported_premises():
    from viva.tools.scenarios import simulate_scenario
    case=_case();args=_scenario_args(case);question=case.question
    old=args['parameter_sources']['initial_amount']['quote'];new='initial amount USD +1,000'
    question=question.replace(old,new);args['parameters']['initial_amount']='+1000';args['parameter_sources']['initial_amount']['quote']=new
    old=args['parameter_sources']['start_date']['quote'];new='opening date at end of January 2026'
    question=question.replace(old,new);args['parameter_sources']['start_date'].update(quote=new,derivation='calendar_month_end')
    result=simulate_scenario(args,{},question)
    assert result.ok,result.to_dict()
    receipt=result.data['assumption_receipt']
    assert receipt['exact_numeric_inputs']['initial_amount']['raw']=='+1000'
    assert receipt['exact_numeric_inputs']['initial_amount']['quote']=='initial amount USD +1,000'
    assert receipt['declared_start_date']=='2026-01-31'
    for malformed in ('initial amount USD +100,0','opening date January 2026'):
        changed=question.replace('initial amount USD +1,000' if malformed.startswith('initial') else new,malformed)
        assert not simulate_scenario(args,{},changed).ok


def test_packaged_schemas_include_all_reviewed_scenario_contracts_and_repayment():
    from vivacore import versions
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.schema import _generated_program_json_schema,program_json_schema
    from viva.tools.registry import PACKAGE
    assert json.loads(versions.path_of(PACKAGE,versions.active(PACKAGE,'semantic_request_schema')).read_text())==SemanticFamilyRegistry().output_schema()
    assert program_json_schema()==_generated_program_json_schema()
    assert 'repayment' in json.dumps(program_json_schema())
    assert versions.path_of(PACKAGE,'answer-program-schema-v2').is_file()
    assert versions.path_of(PACKAGE,'semantic-request-retry-v8').is_file()


def test_all_combined_cases_preflight_authenticate_independent_supplement_before_provider():
    from viva.answer_program.eval import load_cases
    from viva.answer_program import preflight_live_suite,AnswerResourcePolicy
    cases=load_cases()
    oracles,manifests=preflight_live_suite(cases=cases,policy=AnswerResourcePolicy(),locale='en-US')
    assert len(manifests)==123 and len(oracles.entries)==123
    for case in cases[73:]:
        assert oracles.oracle_for(case.id)['supplement_contract']==case.supplement_contract


def test_live_partial_supplement_uses_trusted_read_day_before_compiler_and_canonical_keeps_caller_day():
    from viva.answer_program import run_live_suite,AdmissionThresholds
    from viva.answer_program.eval import load_canonical_cases
    observed=[]
    class StopAfterContext(Exception): pass
    def factory(*args):
        return SimpleNamespace(compile=lambda context:stop(context))
    def stop(context):
        observed.append((context.question,context.today))
        raise StopAfterContext()
    for case,requested,expected in [(_case(),'2026-03-01','2026-02-01'),(load_canonical_cases()[0],'2026-04-01','2026-04-01')]:
        with pytest.raises(StopAfterContext):
            run_live_suite(cases=[case],compiler_factory=factory,thresholds=AdmissionThresholds(1,1,1),today=requested,locale='en-US')
        assert observed[-1]==(case.question,expected)


def test_zero_rate_and_genuine_zero_payment_preserve_positive_debt_without_payoff():
    from viva.ledger.scenarios import loan_payoff
    from viva.tools.scenarios import simulate_scenario
    result=loan_payoff('1000','0','0','2','2026-01-31')
    assert (result['remaining_debt'],result['interest_paid'],result['repayments_paid'],result['payment_count'],result['payoff_date'])==('1000.00','0.00','0.00',0,'')
    case=_case('loan_partial_final_payment');args=_scenario_args(case);question=case.question
    for key,value in {'monthly_payment':'0','nominal_annual_rate_percent':'0'}.items():
        old=args['parameter_sources'][key]['quote'];new=old.replace(args['parameters'][key],value)
        args['parameters'][key]=value;args['parameter_sources'][key]['quote']=new;question=question.replace(old,new)
    delivered=simulate_scenario(args,{},question)
    assert delivered.ok and all(f['kind']=='hypothetical' and not f['grade'] for f in delivered.figures)
    assert delivered.data['repayments_paid']=='0.00' and delivered.data['payment_count']==0 and not delivered.data['payoff_date']


def _measured_scenario_setup(registry, name='Example Checking', account='cash'):
    from viva.answer_program.evidence import EvidenceGraph
    case=_case('checking_savings_zero_rate')
    args=_scenario_args(case)
    args['parameters']['account_phrase']=account
    args['parameter_sources']['account_phrase']['quote']=name
    question=case.question.replace('Example Checking',name)
    read=registry.call('read_account_measurements',{'view':'recorded_cash','account':account})
    assert read.ok
    graph=EvidenceGraph(question);graph.stamp('starting',read)
    args['starting_figure']=read.figures[0]['id']
    return args,question,read,graph


def test_direct_measured_quote_cannot_select_another_compatible_account():
    from viva.answer_program.eval import resolve_case_fixture
    case=_case('checking_savings_zero_rate'); factory,_=resolve_case_fixture(case);registry=factory()
    args,question,read,graph=_measured_scenario_setup(registry,account='cap-reserve')
    assert read.figures[0]['value']=='500'
    result=registry.call('simulate_scenario',args,figures=graph.book,question=question)
    assert not result.ok and result.refusal=='scenario_premise_source_mismatch' and not result.figures


def test_complete_long_scenario_receipt_refuses_without_figures_when_other_bounds_fit():
    from test_measurement_tools import _measure_registry
    from _tool_test_support import account_opened
    name='Recorded '+('x'*3500)
    registry=_measure_registry([account_opened('cash','depository',name,'USD','2026-01-01')])
    args,question,read,graph=_measured_scenario_setup(registry,name=name)
    assert len(json.dumps(registry.semantic_entities()).encode())<60000
    assert len(json.dumps(read.to_dict()).encode())<50000
    result=registry.call('simulate_scenario',args,figures=graph.book,question=question)
    assert not result.ok and result.refusal=='scenario_payload_limit' and not result.figures
    assert 'stated opening amount' in result.text and 'Resubmit the whole scenario' in result.text


@pytest.mark.parametrize('catalog_state',['incomplete','duplicate','absent'])
def test_measured_account_names_require_unique_complete_held_catalog(catalog_state):
    from test_measurement_tools import _measure_registry
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.schema import QuestionContext
    registry=_measure_registry();args,question,read,graph=_measured_scenario_setup(registry)
    catalog=registry.semantic_entities()
    if catalog_state=='incomplete': catalog['coverage']['accounts']['complete']=False
    elif catalog_state=='duplicate': catalog['accounts'].append({**catalog['accounts'][0],'id':'other','name':'Example Checking'})
    else: catalog['accounts']=[row for row in catalog['accounts'] if row['id']!='cash']
    registry.set_semantic_entity_provider(lambda:catalog)
    result=registry.call('simulate_scenario',args,figures=graph.book,question=question)
    assert not result.ok and result.refusal=='scenario_premise_source_mismatch' and not result.figures
    families=SemanticFamilyRegistry(catalog)
    raw={'request_version':families.output_schema()['oneOf'][0]['properties']['request_version']['enum'][0],
         'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,
         'family':args['view'],'parameters':args['parameters'],'parameter_sources':args['parameter_sources'],
         'requested_claims':['final_balance','contributed_principal','growth']}
    if catalog_state=='incomplete':
        outcome=families.parse(raw,QuestionContext(question=question))
        assert outcome.kind=='needs_assumption' and outcome.detail['tag']=='scenario_premise_source_mismatch'


def test_measured_wrapper_without_trusted_resolver_refuses_but_exact_identity_survives_truncation():
    from test_measurement_tools import _measure_registry
    from viva.tools.scenarios import simulate_scenario
    registry=_measure_registry();args,question,read,graph=_measured_scenario_setup(registry,name='cash')
    assert not simulate_scenario(args,graph.book,question).ok
    catalog=registry.semantic_entities();catalog['coverage']['accounts']['complete']=False
    registry.set_semantic_entity_provider(lambda:catalog)
    assert registry.call('simulate_scenario',args,figures=graph.book,question=question).ok


def test_required_scenario_payload_refusal_delivers_human_request_without_figures():
    from test_measurement_tools import _measure_registry
    from _tool_test_support import account_opened
    from viva.answer_program.intents import SemanticFamilyRegistry
    from viva.answer_program.runtime import AnswerProgramRuntime
    from viva.answer_program.execute import ProgramExecutor
    from viva.answer_program.bind import DeterministicBinder
    from viva.answer_program.capability import CapabilityManifest
    from viva.answer_program.schema import AnswerResourcePolicy,QuestionContext
    name='Recorded '+('x'*3500)
    registry=_measure_registry([account_opened('cash','depository',name,'USD','2026-01-01')])
    args,question,read,graph=_measured_scenario_setup(registry,name=name)
    families=SemanticFamilyRegistry(registry.semantic_entities());case=_case('checking_savings_zero_rate')
    raw={'request_version':families.output_schema()['oneOf'][0]['properties']['request_version']['enum'][0],
         'outcome':'request','catalog_digest':families.catalog_digest,'entity_catalog_digest':families.entity_catalog_digest,
         'family':args['view'],'parameters':args['parameters'],'parameter_sources':args['parameter_sources'],
         'requested_claims':list(case.required_claims)}
    semantic=families.parse(raw,QuestionContext(question=question,today='2026-02-01'))
    program=families.lower(semantic,CapabilityManifest.from_registry(registry));policy=AnswerResourcePolicy()
    compilation=SimpleNamespace(ok=True,program=program,semantic_outcome=semantic,validation=None,exchanges=[SimpleNamespace(defect={})])
    outcome=AnswerProgramRuntime(SimpleNamespace(compile=lambda context:compilation),
        ProgramExecutor(registry,policy),DeterministicBinder(registry,'en-US')).answer(QuestionContext(question=question,today='2026-02-01'))
    assert not outcome.result.answered and not outcome.result.figures
    assert outcome.result.refusal=='scenario_payload_limit'
    assert outcome.outcome.text==outcome.result.text and 'Resubmit the whole scenario' in outcome.outcome.text
    assert outcome.result.missing[0]['label']==outcome.outcome.text
