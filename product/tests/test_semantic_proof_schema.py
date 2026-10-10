"""Model-facing proofs retain valid paths and exclude impossible derivations."""
import copy
import json
import re

import pytest

from viva.answer_program.eval import load_cases, resolve_case_fixture
from viva.answer_program.intents import SemanticFamilyRegistry, SEMANTIC_REQUEST_VERSION
from viva.answer_program.schema import ContractError, QuestionContext
from viva.tools.registry import _validate


@pytest.mark.parametrize('role', ('semantic_request', 'semantic_request_retry'))
def test_native_prompt_example_instantiates_and_parses_against_supplied_catalog(role):
    from vivacore import promptstore, versions
    from viva.tools.registry import PACKAGE, PROMPTS

    case = _case(SCENARIO_CASES[0])
    families = _families(case)
    text = promptstore.load(PROMPTS, versions.active(PACKAGE, role))
    rendered = text.format(**{name: '' for name in (
        'context', 'catalog', 'catalog_digest', 'entity_catalog',
        'entity_catalog_digest', 'schema', 'defects', 'accepted')})
    match = re.search(r'Generic native request example.*?```json\n(.*?)\n```',
                      rendered, re.DOTALL)
    assert match, 'active prompt must provide an executable native argument example'
    arguments = json.loads(match.group(1))
    quote = case.parameter_sources['account_phrase']['quote']
    question = 'What is the balance and measurement date of ' + quote + '?'
    candidates = families._catalog_candidates('account_phrase', quote)
    assert len(candidates) == 1
    assert arguments['parameters']['account_phrase'] == {'catalog_id': '<catalog-account-id>'}
    assert arguments['parameter_sources']['account_phrase']['quote'] == '<question-account-reference>'
    arguments['parameters']['account_phrase']['catalog_id'] = candidates[0]['id']
    arguments['parameter_sources']['account_phrase']['quote'] = quote
    schema = next(tool['parameters'] for tool in families.model_tools()
                  if tool['name'] == 'select_named_account_balance')
    assert not _validate(schema, arguments)
    raw = {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'request',
           'family': 'named_account_balance', 'catalog_digest': families.catalog_digest,
           'entity_catalog_digest': families.entity_catalog_digest}
    raw.update(arguments)
    outcome = families.parse(families.materialize_model_output(raw),
                             QuestionContext(question=question))
    assert outcome.kind == 'request'
    assert outcome.request.family == 'named_account_balance'
    for field in ('parameter_sources', 'requested_claims'):
        nested = copy.deepcopy(arguments)
        nested['parameters'][field] = nested.pop(field)
        assert _validate(schema, nested)
        malformed = copy.deepcopy(raw)
        for sibling in ('parameters', 'parameter_sources', 'requested_claims'):
            malformed.pop(sibling)
        malformed.update(nested)
        with pytest.raises(ContractError):
            families.parse(families.materialize_model_output(malformed),
                           QuestionContext(question=question))


SCENARIO_CASES = (
    'fc-v1:checking_savings_zero_rate',
    'fc-v1:loan_measured_owed_partial_final',
    'fc-v1:checking_cash_flow_one_off',
)


def _case(case_id):
    return next(case for case in load_cases() if case.id == case_id)


def _families(case):
    factory, _ = resolve_case_fixture(case)
    return SemanticFamilyRegistry(factory().semantic_entities())


def _proofs(families, family, mode):
    if mode == 'native':
        schema = next(tool['parameters'] for tool in families.model_tools()
                      if tool['name'] == 'select_' + family)
    else:
        schema = next(branch for branch in families.model_output_schema()['oneOf']
                      if branch['properties'].get('family', {}).get('enum') == [family])
    return schema['properties']['parameter_sources']['properties']


def _raw(families, case):
    parameters = copy.deepcopy(case.expected_parameters)
    proofs = copy.deepcopy(case.parameter_sources)
    if 'account_phrase' in parameters:
        parameters['account_phrase'] = {'grounded_phrase': True}
        proofs['account_phrase']['derivation'] = 'verbatim'
    return {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'request',
            'family': case.expected_family, 'catalog_digest': families.catalog_digest,
            'entity_catalog_digest': families.entity_catalog_digest,
            'parameters': parameters, 'parameter_sources': proofs,
            'requested_claims': list(case.required_claims)}


@pytest.mark.parametrize('case_id', SCENARIO_CASES)
@pytest.mark.parametrize('mode', ('native', 'text'))
def test_scenario_proof_derivations_follow_parameter_roles(case_id, mode):
    case = _case(case_id)
    proofs = _proofs(_families(case), case.expected_family, mode)
    for name, schema in proofs.items():
        expected = (['verbatim', 'calendar_month_start', 'calendar_month_end']
                    if name == 'start_date' else ['verbatim'] if name == 'currency'
                    else ['catalog_selection', 'verbatim'] if name == 'account_phrase'
                    else ['decimal_numeric'])
        assert schema['properties']['derivation']['enum'] == expected
        assert schema['properties']['source']['enum'] == ['question']
        assert 'turn' not in schema['properties']
    for name in ('start_date', 'currency'):
        proof = dict(case.parameter_sources[name], derivation='decimal_numeric')
        assert _validate(proofs[name], proof)


def test_parameter_proof_definitions_are_independent():
    case = _case(SCENARIO_CASES[0])
    proofs = _proofs(_families(case), case.expected_family, 'native')
    original = copy.deepcopy(proofs)
    proofs['currency']['properties']['derivation']['enum'].append('synthetic')
    for name in set(proofs) - {'currency'}:
        assert proofs[name] == original[name]


@pytest.mark.parametrize('family', ('known_remainder', 'upcoming_obligations'))
@pytest.mark.parametrize('mode', ('native', 'text'))
def test_projection_horizon_schema_only_offers_verbatim(family, mode):
    schema = _proofs(SemanticFamilyRegistry(), family, mode)['horizon_days']
    assert schema['properties']['derivation']['enum'] == ['verbatim']
    assert schema['properties']['source']['enum'] == ['question', 'prior_turn']
    for derivation in ('catalog_selection', 'calendar_month_start', 'calendar_month_end'):
        assert _validate(schema, {'source': 'question', 'quote': '30', 'derivation': derivation})


@pytest.mark.parametrize('case_id', SCENARIO_CASES)
@pytest.mark.parametrize('mode', ('native', 'text'))
@pytest.mark.parametrize('representation', ('grounded', 'catalog', 'alias'))
def test_scenario_account_reference_paths_remain_expressible(case_id, mode, representation):
    case = _case(case_id)
    families = _families(case)
    raw = _raw(families, case)
    question = case.question
    proof = raw['parameter_sources']['account_phrase']
    if representation in ('catalog', 'alias'):
        candidates = families._catalog_candidates('account_phrase', proof['quote'])
        assert len(candidates) == 1
        raw['parameters']['account_phrase'] = {'catalog_id': candidates[0]['id']}
        proof['derivation'] = 'catalog_selection'
    if representation == 'alias':
        quote = proof['quote'].split()[-1]
        question = question.replace('starting account ' + proof['quote'], 'starting account ' + quote)
        proof['quote'] = quote
    schema = _proofs(families, case.expected_family, mode)['account_phrase']
    assert not _validate(schema, proof)
    materialized = families.materialize_model_output(raw)
    assert materialized['parameter_sources']['account_phrase']['derivation'] == 'catalog_selection'
    assert families.parse(materialized, QuestionContext(question=question)).kind == 'request'


@pytest.mark.parametrize('case_id', SCENARIO_CASES)
@pytest.mark.parametrize('edge', ('iso', 'start', 'end'))
def test_scenario_date_and_currency_proofs_keep_complete_role_quotes(case_id, edge):
    case = _case(case_id)
    families = _families(case)
    raw = _raw(families, case)
    question = case.question
    if edge != 'iso':
        proof = raw['parameter_sources']['start_date']
        role = 'first payment date' if case.expected_family == 'loan_payoff_scenario' else 'opening date'
        clause = role + ' at ' + edge + ' of February 2028'
        question = question.replace(proof['quote'], clause)
        raw['parameters']['start_date'] = '2028-02-01' if edge == 'start' else '2028-02-29'
        proof.update(quote=clause, derivation='calendar_month_' + edge)
    assert families.parse(families.materialize_model_output(raw), QuestionContext(question=question)).kind == 'request'
    for name in ('start_date', 'currency'):
        broken = copy.deepcopy(raw)
        broken['parameter_sources'][name]['derivation'] = 'decimal_numeric'
        outcome = families.parse(families.materialize_model_output(broken), QuestionContext(question=question))
        assert outcome.kind == 'needs_assumption'
        assert outcome.detail['tag'] == 'scenario_premise_source_mismatch'
    broken = copy.deepcopy(raw)
    broken['parameter_sources']['currency']['quote'] = question.partition(':')[0]
    assert families.parse(families.materialize_model_output(broken), QuestionContext(question=question)).kind == 'needs_assumption'


@pytest.mark.parametrize('family', ('known_remainder', 'upcoming_obligations'))
def test_projection_sources_keep_current_and_supplied_prior_digit_proofs(family):
    families = SemanticFamilyRegistry()
    schema = _proofs(families, family, 'native')['horizon_days']
    values = {'horizon_days': '30'}
    question = 'Show the next 30 days.'
    proof = {'source': 'question', 'quote': '30', 'derivation': 'verbatim'}
    assert not _validate(schema, proof)
    families._validate_parameter_sources(values, {'horizon_days': proof}, QuestionContext(question=question), require_grounding=True)
    with pytest.raises(ContractError, match='differs from its source quote'):
        families._validate_parameter_sources(values, {'horizon_days': dict(proof, quote='30 days')}, QuestionContext(question=question), require_grounding=True)
    prior = dict(proof, source='prior_turn', turn=0)
    assert not _validate(schema, prior)
    families._validate_parameter_sources(values, {'horizon_days': prior}, QuestionContext(question='Use that horizon.', prior_turns=((question, 'Recorded.'),)), require_grounding=True)
    with pytest.raises(ContractError, match='names no prior turn'):
        families._validate_parameter_sources(values, {'horizon_days': prior}, QuestionContext(question='Use that horizon.'), require_grounding=True)
    assert _validate(schema, dict(proof, quote=30))
    assert _validate(schema, dict(prior, turn='0'))


def test_recorded_cash_meaning_keeps_liability_refusal_without_figures():
    from viva.answer_program import AnswerResourcePolicy, CapabilityManifest, ProgramValidator
    from viva.answer_program.execute import ProgramExecutor

    case = _case('fc-v1:liability-cash')
    factory, _ = resolve_case_fixture(case)
    registry = factory()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    raw = _raw(families, case)
    outcome = families.parse(families.materialize_model_output(raw),
                             QuestionContext(question=case.question))
    assert outcome.kind == 'request'
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    program = families.lower(outcome, manifest)
    assert ProgramValidator(manifest, policy).validate(program).ok
    execution = ProgramExecutor(registry, policy).execute(program, case.question)
    assert execution.transcript[0].refusal == 'cash_account_ineligible'
    assert all(not item.figures for item in execution.transcript)


def test_unresolved_account_clarification_is_representable_without_prior_subject():
    case = _case('ambiguous-account')
    families = _families(case)
    assert not case.prior_turns
    arguments = {'tag': 'ambiguous_account', 'question': 'Which account do you mean?',
                 'options': []}
    schema = next(tool['parameters'] for tool in families.model_tools()
                  if tool['name'] == 'semantic_clarification')
    assert not _validate(schema, arguments)
    raw = {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'clarify',
           **arguments}
    outcome = families.parse(raw, QuestionContext(question=case.question))
    assert outcome.kind == 'clarify'
    assert outcome.detail['tag'] == 'ambiguous_account'


def test_recorded_start_reference_proof_reaches_missing_measurement_and_rejects_hostile_sources():
    from viva.answer_program import AnswerResourcePolicy, CapabilityManifest, ProgramValidator
    from viva.answer_program.execute import ProgramExecutor

    case = _case('fc-v1:missing-measured-start')
    factory, _ = resolve_case_fixture(case)
    registry = factory()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    raw = _raw(families, case)
    raw['parameters']['account_phrase'] = {'catalog_id': 'cap-unmeasured'}
    proof = raw['parameter_sources']['account_phrase']
    proof.update(quote='Example Unmeasured', derivation='catalog_selection')
    context = QuestionContext(question=case.question)
    outcome = families.parse(families.materialize_model_output(raw), context)
    assert outcome.kind == 'request'
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    program = families.lower(outcome, manifest)
    assert ProgramValidator(manifest, policy).validate(program).ok
    execution = ProgramExecutor(registry, policy).execute(program, case.question)
    assert len(execution.transcript) == 1
    assert execution.transcript[0].refusal == 'cash_measurement_unavailable'
    assert all(not item.figures for item in execution.transcript)
    for changes in (
            {'quote': 'starting account Example Unmeasured'},
            {'source': 'prior_turn', 'turn': 0},
            {'quote': 'Example Foreign'}):
        broken = copy.deepcopy(raw)
        broken['parameter_sources']['account_phrase'].update(changes)
        rejected = families.parse(families.materialize_model_output(broken), context)
        assert rejected.kind == 'needs_assumption'
        assert rejected.detail['tag'] == 'scenario_premise_source_mismatch'


@pytest.mark.parametrize('case_id', SCENARIO_CASES)
@pytest.mark.parametrize('mode', ('native', 'text'))
@pytest.mark.parametrize('edge', ('iso', 'start', 'end'))
def test_scenario_date_role_clause_cannot_be_replaced_by_ordinary_period_quote(case_id, mode, edge):
    case = _case(case_id)
    families = _families(case)
    raw = _raw(families, case)
    proof = raw['parameter_sources']['start_date']
    question = case.question
    if edge == 'iso':
        minimal = raw['parameters']['start_date']
    else:
        role = 'first payment date' if case.expected_family == 'loan_payoff_scenario' else 'opening date'
        clause = role + ' at ' + edge + ' of February 2028'
        question = question.replace(proof['quote'], clause)
        raw['parameters']['start_date'] = '2028-02-01' if edge == 'start' else '2028-02-29'
        proof.update(quote=clause, derivation='calendar_month_' + edge)
        minimal = 'February 2028'
    schema = _proofs(families, case.expected_family, mode)['start_date']
    assert not _validate(schema, proof)
    context = QuestionContext(question=question)
    assert families.parse(families.materialize_model_output(raw), context).kind == 'request'
    proof['quote'] = minimal
    assert not _validate(schema, proof)
    outcome = families.parse(families.materialize_model_output(raw), context)
    assert outcome.kind == 'needs_assumption'
    assert outcome.detail['tag'] == 'scenario_premise_source_mismatch'
