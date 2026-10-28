"""Scenario prompt guidance preserves the existing numeric/proof boundary."""
import copy
import hashlib
import json

import pytest

from vivacore import versions
from viva.answer_program.intents import SemanticFamilyRegistry
from viva.answer_program.eval import load_supplement_cases
from viva.tools.registry import PACKAGE
from viva.tools.scenarios import validate_premises
from viva.ledger.scenarios import ScenarioError


PREDECESSORS = {
    'semantic-request-v14': 'a3f33ea3486ad3a9',
    'semantic-request-retry-v12': '48fe3dc619c33c37',
    'semantic-request-schema-v11': 'ba07c67a43845903',
}


def assert_numeric_guidance(text):
    normalized = ' '.join(text.split())
    for clause in (
        'Numeric scenario parameter values contain only the exact numeric token',
        'conventionally grouped commas removed',
        'exclude currency, percent signs and unit words',
        'Preserve sign and percentage scale without conversion',
        'Their source quotes retain the complete role clause, including currency or unit',
    ):
        assert clause in normalized, clause


@pytest.mark.parametrize('family', ['semantic_request', 'semantic_request_retry'])
def test_active_prompts_separate_numeric_tokens_from_unit_bearing_quotes(family):
    text = versions.path_of(PACKAGE, versions.active(PACKAGE, family)).read_text()
    assert_numeric_guidance(text)
    assert 'verbatim' in text and 'calendar_month_start/calendar_month_end' in text
    assert 'Never use decimal_numeric for' in text


@pytest.mark.parametrize('version', list(PREDECESSORS)[:2])
def test_predecessor_guidance_lacks_explicit_numeric_unit_separation(version):
    with pytest.raises(AssertionError):
        assert_numeric_guidance(versions.path_of(PACKAGE, version).read_text())


def test_schema_successor_and_predecessors_preserve_the_contract():
    for version, digest in PREDECESSORS.items():
        assert hashlib.sha256(versions.path_of(PACKAGE, version).read_bytes()).hexdigest()[:16] == digest
        assert versions.pin(PACKAGE, version) == digest
    previous = versions.path_of(PACKAGE, 'semantic-request-schema-v11').read_bytes()
    current = versions.path_of(PACKAGE, 'semantic-request-schema-v12').read_bytes()
    assert previous.count(b'semantic-request-v14') == 27
    assert current == previous.replace(b'semantic-request-v14', b'semantic-request-v15')
    active = json.loads(versions.path_of(PACKAGE, versions.active(PACKAGE, 'semantic_request_schema')).read_text())
    expected = json.loads(current)
    for branch in expected['oneOf']:
        branch['properties']['request_version']['enum'] = ['semantic-request-v21']
        if 'catalog_digest' in branch['properties']:
            branch['properties']['catalog_digest']['enum'] = [SemanticFamilyRegistry().catalog_digest]
        if branch['properties']['outcome']['enum'] == ['clarify']:
            branch['properties'].pop('scenario_family')
    # Original family contracts remain exact; dedicated source families are
    # additive, with their finite names checked independently below.
    def source_family(branch):
        return branch['properties'].get('family',{}).get('enum',[''])[0]
    selected = [branch for branch in active['oneOf']
                if source_family(branch) == 'selected_account_balances']
    assert len(selected) == 1
    assert selected[0]['properties']['family']['enum'] == ['selected_account_balances']
    assert selected[0]['properties']['parameters'] == {
        'type': 'object',
        'properties': {f'account_phrase_{i}': {'type': 'string', 'minLength': 1}
                       for i in range(1, 8)},
        'required': ['account_phrase_1', 'account_phrase_2'],
        'additionalProperties': False,
    }
    legacy=[branch for branch in active['oneOf']
            if not source_family(branch).startswith(('instrument_','investment_','retirement_'))
            and source_family(branch) != 'selected_account_balances']
    assert {**active,'oneOf':legacy} == expected
    added={branch['properties']['family']['enum'][0] for branch in active['oneOf'] if branch['properties'].get('family',{}).get('enum',[''])[0].startswith('instrument_')}
    assert added=={'instrument_terms','instrument_period_components','instrument_maturities','instrument_refinances','instrument_tax_payments','instrument_allocation','instrument_allocation_target','instrument_monthly_loan_principal','instrument_monthly_payment_escrow','instrument_annual_summary','instrument_deposit_annual_components','instrument_deposit_transactions','instrument_monthly_loan_payments'}
    assert {source_family(branch) for branch in active['oneOf'] if source_family(branch).startswith('investment_')} == {'investment_positions','investment_activity_totals','investment_account_report','investment_account_report_first_years','investment_account_report_remaining_years'}
    assert {source_family(branch) for branch in active['oneOf'] if source_family(branch).startswith('retirement_')} == {'retirement_annual_employee_contributions','retirement_direct_rollovers','retirement_funding_report'}
    assert active == SemanticFamilyRegistry().output_schema()


@pytest.mark.parametrize('fragment', [
    'savings_monthly_one_percent', 'loan_partial_final_payment', 'cash_flow_one_off',
])
def test_numeric_tokens_pass_and_unit_suffixes_fail_for_each_scenario_family(fragment):
    case, = [c for c in load_supplement_cases() if c.id == "fc-v1:" + fragment]
    parameters = copy.deepcopy(case.expected_parameters)
    proofs = copy.deepcopy(case.parameter_sources)
    receipt = validate_premises(case.expected_family, parameters, proofs, case.question)
    assert receipt['hypothetical_grades_empty']
    for name, proof in proofs.items():
        if proof['derivation'] != 'decimal_numeric':
            continue
        bad = copy.deepcopy(parameters)
        bad[name] = proof['quote']
        with pytest.raises(ScenarioError):
            validate_premises(case.expected_family, bad, proofs, case.question)


@pytest.mark.parametrize('mutation', [
    'percent_suffix', 'money_unit', 'months_unit', 'fractional_scale',
    'partial_quote', 'wrong_currency', 'date_value_clause', 'date_quote_token',
    'prior_turn', 'negated', 'quoted',
])
def test_numeric_clarification_retains_source_rejections(mutation):
    case, = [c for c in load_supplement_cases() if 'savings_monthly_one_percent' in c.id]
    parameters = copy.deepcopy(case.expected_parameters)
    proofs = copy.deepcopy(case.parameter_sources)
    question = case.question
    if mutation == 'percent_suffix': parameters['nominal_annual_rate_percent'] += '%'
    elif mutation == 'money_unit': parameters['initial_amount'] = 'USD ' + parameters['initial_amount']
    elif mutation == 'months_unit': parameters['months'] += ' months'
    elif mutation == 'fractional_scale': parameters['nominal_annual_rate_percent'] = '0.12'
    elif mutation == 'partial_quote': proofs['initial_amount']['quote'] = 'USD ' + parameters['initial_amount']
    elif mutation == 'wrong_currency': parameters['currency'] = 'EUR'
    elif mutation == 'date_value_clause': parameters['start_date'] = proofs['start_date']['quote']
    elif mutation == 'date_quote_token': proofs['start_date']['quote'] = parameters['start_date']
    elif mutation == 'prior_turn': proofs['initial_amount'].update(source='prior_turn', turn=1)
    elif mutation == 'negated': question = question.replace('initial amount', 'not initial amount')
    elif mutation == 'quoted': question = '"' + question + '"'
    with pytest.raises(ScenarioError):
        validate_premises(case.expected_family, parameters, proofs, question)
