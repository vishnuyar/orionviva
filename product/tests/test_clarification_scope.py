"""Only grounded scenario requests derive scenario account clarifications."""
import json
from types import SimpleNamespace

import pytest

from viva.answer_program import AnswerProgramCompiler, QuestionContext
from viva.answer_program.intents import SemanticFamilyRegistry, SEMANTIC_REQUEST_VERSION
from viva.answer_program.schema import ContractError
from viva.session import Session
from test_semantic_answering import _registry, _turn

QUESTION = ('Simulate cash flow in USD: starting account Checking; monthly income USD 100; '
            'monthly outflow USD 50; one-off outflow USD 0; one-off at month 1; '
            'horizon 2 months; opening date 2026-01-01.')


def catalog():
    return {'accounts': [{'id': 'first', 'name': 'First Checking', 'kind': 'depository'},
                         {'id': 'second', 'name': 'Second Checking', 'kind': 'depository'}],
            'coverage': {'accounts': {'complete': True}}}


def scenario(families):
    values = {'account_phrase': {'grounded_phrase': True}, 'monthly_income': '100',
              'monthly_outflow': '50', 'one_off_outflow': '0', 'one_off_month': '1',
              'months': '2', 'start_date': '2026-01-01', 'currency': 'USD'}
    quotes = {'account_phrase': 'Checking', 'monthly_income': 'monthly income USD 100',
              'monthly_outflow': 'monthly outflow USD 50', 'one_off_outflow': 'one-off outflow USD 0',
              'one_off_month': 'one-off at month 1', 'months': 'horizon 2 months',
              'start_date': 'opening date 2026-01-01', 'currency': 'USD'}
    return {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'request',
            'family': 'cash_flow_scenario', 'catalog_digest': families.catalog_digest,
            'entity_catalog_digest': families.entity_catalog_digest, 'parameters': values,
            'requested_claims': list(families.get('cash_flow_scenario').claims),
            'parameter_sources': {key: {'source': 'question', 'quote': quote,
                'derivation': 'verbatim' if key in {'account_phrase', 'start_date', 'currency'} else 'decimal_numeric'}
                for key, quote in quotes.items()}}


def ordinary(marker=None):
    raw = {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'clarify',
           'tag': 'ambiguous_account', 'question': 'Which Checking account?',
           'options': [{'id': 'first', 'label': 'First Checking'}, {'id': 'second', 'label': 'Second Checking'}]}
    if marker is not None:
        raw['scenario_family'] = marker
    return raw


def session_result(replies, question, modality='native-structured', entities=None):
    registry = _registry()
    registry.semantic_entities = lambda: entities or catalog()
    registry.call = lambda *args, **kwargs: pytest.fail('financial execution before account resolution')
    families = SemanticFamilyRegistry(registry.semantic_entities())
    held = list(replies)
    class Adapter:
        calls = 0
        def next(self):
            raw = held[min(self.calls, len(held)-1)]
            self.calls += 1
            return raw
        def converse(self, messages, tools):
            raw = self.next()
            if raw['outcome'] == 'request':
                return _turn('select_' + raw['family'], {k: raw[k] for k in ('parameters', 'parameter_sources', 'requested_claims')})
            return _turn('semantic_clarification', {k:v for k,v in raw.items() if k not in {'outcome','request_version'}})
        def extract(self, pages, prompt):
            return SimpleNamespace(text=json.dumps(self.next()), request={}, response={})
    adapter = Adapter()
    session = Session(registry, lambda validator, manifest, policy: AnswerProgramCompiler(
        adapter, validator, manifest, policy, modality=modality), today=lambda:'2026-03-01')
    return session.ask(question), adapter


@pytest.mark.parametrize('modality', ['native-structured', 'text-json'])
def test_raw_marker_is_rejected_and_valid_ordinary_reply_recovers(modality):
    turn, adapter = session_result([ordinary('cash_flow_scenario'), ordinary()], 'Show Checking balances', modality)
    assert adapter.calls == 2
    assert turn.exchanges[0].parse_error
    assert turn.program['clarification']['question'] == ordinary()['question']
    assert turn.program['clarification']['options'] == ordinary()['options']
    assert not turn.result.figures


@pytest.mark.parametrize('modality', ['native-structured', 'text-json'])
@pytest.mark.parametrize('marker', ['cash_flow_scenario', 'unknown'])
def test_repeated_raw_markers_terminate_without_scenario_instructions(modality, marker):
    turn, adapter = session_result([ordinary(marker)], 'Show Checking balances', modality)
    assert adapter.calls == 2
    assert all(exchange.parse_error for exchange in turn.exchanges)
    assert not turn.result.figures and 'Simulate cash flow' not in turn.said
    assert not turn.program


def test_materialize_parse_and_session_preserve_grounded_ambiguity():
    families = SemanticFamilyRegistry(catalog())
    raw = scenario(families)
    canonical = families.materialize_model_output(raw)
    outcome = families.parse(canonical, QuestionContext(question=QUESTION))
    assert outcome.kind == 'clarify'
    assert outcome.detail['scenario_family'] == 'cash_flow_scenario'
    with pytest.raises(ContractError):
        families.parse({'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'clarify', **outcome.detail})
    for modality in ('native-structured', 'text-json'):
        turn, adapter = session_result([raw], QUESTION, modality)
        assert adapter.calls == 1
        assert 'Simulate cash flow' in turn.program['clarification']['question']
        assert [o['id'] for o in turn.program['clarification']['options']] == ['first', 'second']
        assert not turn.result.figures


@pytest.mark.parametrize('mutation', ['missing_role', 'altered_role', 'missing_quote', 'changed_quote',
    'mismatched_question', 'prior_turn', 'wrong_derivation', 'malformed_proof', 'unknown', 'incomplete', 'unique_incomplete', 'unsupported_kind'])
def test_grounded_account_controls_fail_closed(mutation):
    entities = catalog()
    question = QUESTION
    if mutation in {'incomplete', 'unique_incomplete'}:
        entities['coverage']['accounts']['complete'] = False
    if mutation == 'unique_incomplete': entities['accounts'] = entities['accounts'][:1]
    if mutation == 'unsupported_kind':
        entities['accounts'] = [dict(entities['accounts'][0], kind='unknown')]
    families = SemanticFamilyRegistry(entities)
    raw = scenario(families)
    proof = raw['parameter_sources']['account_phrase']
    if mutation == 'missing_role': question = question.replace('starting account Checking; ', '')
    elif mutation == 'altered_role': question = question.replace('starting account', 'account')
    elif mutation == 'missing_quote': proof.pop('quote')
    elif mutation == 'changed_quote': proof['quote'] = 'First Checking'
    elif mutation == 'mismatched_question': question = question.replace('Checking', 'Savings')
    elif mutation == 'prior_turn': proof.update(source='prior_turn', turn=0)
    elif mutation == 'wrong_derivation': proof['derivation'] = 'decimal_numeric'
    elif mutation == 'malformed_proof': proof['extra'] = True
    elif mutation == 'unknown':
        question = question.replace('Checking', 'Unlisted')
        proof['quote'] = 'Unlisted'
    try:
        outcome = families.parse(families.materialize_model_output(raw), QuestionContext(question=question))
    except ContractError:
        return
    assert outcome.kind in {'unsupported', 'needs_assumption'}


@pytest.mark.parametrize('selection', ['exact', 'unique'])
def test_exact_and_unique_account_references_still_materialize(selection):
    entities = catalog()
    if selection == 'unique': entities['accounts'] = entities['accounts'][:1]
    families = SemanticFamilyRegistry(entities)
    raw = scenario(families)
    if selection == 'exact':
        raw['parameters']['account_phrase'] = {'catalog_id': 'first'}
        raw['parameter_sources']['account_phrase']['derivation'] = 'catalog_selection'
    canonical = families.materialize_model_output(raw)
    assert canonical['parameters']['account_phrase'] == 'first'
    assert canonical['parameter_sources']['account_phrase']['derivation'] == 'catalog_selection'
    outcome = families.parse(canonical, QuestionContext(question=QUESTION))
    assert outcome.kind == 'request'
    assert outcome.request.parameters['account_phrase'] == 'first'


@pytest.mark.parametrize('mutation', ['missing_options', 'malformed_options', 'unknown_tag'])
def test_malformed_ordinary_outcomes_remain_rejected(mutation):
    raw = ordinary()
    if mutation == 'missing_options': raw.pop('options')
    elif mutation == 'malformed_options': raw['options'] = [{'id': 'first'}]
    else: raw['tag'] = 'unknown'
    with pytest.raises(ContractError): SemanticFamilyRegistry().parse(raw)


def test_unmarked_ordinary_ambiguity_is_unchanged():
    turn, adapter = session_result([ordinary()], 'Show Checking balances')
    assert adapter.calls == 1
    assert turn.program['clarification'] == {k:v for k,v in ordinary().items() if k not in {'outcome','request_version'}}
    assert not turn.result.figures


def test_native_and_text_contracts_exclude_raw_clarification_marker():
    families = SemanticFamilyRegistry()
    native = next(t for t in families.model_tools() if t['name'] == 'semantic_clarification')['parameters']
    for schema in (families.output_schema(), families.model_output_schema()):
        branch = next(b for b in schema['oneOf'] if b['properties']['outcome']['enum'] == ['clarify'])
        assert 'scenario_family' not in branch['properties']
        assert branch['additionalProperties'] is False
        assert {k:v for k,v in branch['properties'].items() if k not in {'outcome','request_version'}} == native['properties']
    assert 'scenario_family' not in native['properties']


def test_exact_id_with_incomplete_catalog_retains_exact_selection():
    entities = catalog()
    entities['coverage']['accounts']['complete'] = False
    families = SemanticFamilyRegistry(entities)
    raw = scenario(families)
    raw['parameters']['account_phrase'] = {'catalog_id': 'first'}
    raw['parameter_sources']['account_phrase'].update(quote='first', derivation='catalog_selection')
    outcome = families.parse(families.materialize_model_output(raw), QuestionContext(question=QUESTION.replace('Checking', 'first')))
    assert outcome.kind == 'request' and outcome.request.parameters['account_phrase'] == 'first'
