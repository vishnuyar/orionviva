"""Literal-source date-only admission regressions, without model calls."""
import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from viva.answer_program.eval import derive_semantic_oracle, load_cases, resolve_case_fixture, score
from viva.answer_program.capability import CapabilityManifest
from viva.answer_program.compiler import CompilationResult
from viva.answer_program.intents import SemanticFamilyRegistry, SemanticOutcome, SemanticRequest
from viva.answer_program.schema import AnswerResourcePolicy
from viva.answer_program.validate import ProgramValidator
from viva.session import Session


def sample(claims=('measurement_date',)):
    case = next(c for c in load_cases() if c.id == 'follow-up-account-date')
    case = replace(case, expected_claims=claims, allowed_claims=claims)
    factory, day = resolve_case_fixture(case)
    registry = factory()
    manifest = CapabilityManifest.from_registry(registry)
    policy = AnswerResourcePolicy()
    families = SemanticFamilyRegistry(registry.semantic_entities())
    semantic = SemanticOutcome('request', SemanticRequest(
        case.expected_family, dict(case.expected_parameters), claims, families.catalog_digest))
    program = families.lower(semantic, manifest)
    checked = ProgramValidator(manifest, policy).validate(program)
    exchanges = (SimpleNamespace(defect={}),)
    compiler = SimpleNamespace(compile=lambda context: CompilationResult(program, checked, exchanges, semantic))
    turn = Session(registry, lambda *args: compiler, today=lambda: day,
                   locale='en-US', prior_turns=case.prior_turns).ask(case.question)
    oracle = derive_semantic_oracle(case, factory(), manifest, policy, locale='en-US')
    facade = SimpleNamespace(result=turn.result, compilation=SimpleNamespace(
        program=program, semantic_outcome=semantic, exchanges=exchanges))
    return replace(case, oracle=oracle), facade


def test_supported_date_only_passes_complete_scorer():
    case, actual = sample()
    assert actual.result.written == {'date': '2026-01-31'}
    assert actual.result.figures == []
    assert score(case, actual).passed


@pytest.mark.parametrize('claims', [('balance',), ('balance', 'measurement_date')])
def test_amount_contract_stays_exact(claims):
    case, actual = sample(claims)
    assert score(case, actual).passed
    assert case.oracle['figures'] == [{'value': '2400.00', 'currency': 'USD',
        'quantity': 'balance', 'dated': '2026-01-31',
        'record_ids_exact': ['Assets:Admission:Investment', 'admission-investment-2026-01']}]
    for change in ('missing', 'undated', 'amount', 'source'):
        bad = copy.deepcopy(actual)
        if change == 'missing': bad.result.figures.clear()
        elif change == 'undated': bad.result.figures[0]['dated'] = ''
        elif change == 'amount': bad.result.figures[0]['value'] = '2401.00'
        else: bad.result.figures[0]['record_ids'] = ['forged']
        verdict = score(case, bad)
        assert not verdict.passed
        if change in ('missing', 'undated'):
            assert 'wrong_named_account_result' in verdict.defects
        else: assert 'missing_keyed_figure' in verdict.defects


MUTATIONS = [
    'wrong_date', 'missing_date', 'wrong_account', 'wrong_boundary', 'whole_boundary',
    'wrong_document', 'missing_document', 'wrong_page', 'missing_page',
    'wrong_region', 'missing_region', 'missing_support', 'duplicate_support',
    'undated_support', 'forged_support', 'orphan_binding', 'other_read',
    'wrong_quantity', 'wrong_kind', 'wrong_grade', 'missing_grade',
    'wrong_result_grade', 'missing_disclosure', 'wrong_disclosure', 'coverage_disclosure',
    'money_figures', 'money_written', 'money_binding', 'money_slot', 'money_text',
    'missing_clause', 'extra_clause', 'missing_read', 'extra_read', 'wrong_selector',
    'extra_selector', 'missing_binding', 'extra_binding', 'ordinary_date',
    'non_answered', 'answered_false', 'extra_effect', 'missing_read_ok',
    'forged_data', 'forged_read_id', 'incompatible_currency', 'wrong_support_value',
]


def mutate(actual, change):
    result = actual.result
    raw = actual.compilation.program.to_dict()
    read = result.transcript[0]
    support = read['figures'][0]
    provenance = read['data']['balances'][0]['provenance']
    if change == 'wrong_date': result.written['date'] = '2026-02-01'
    elif change == 'missing_date': result.written.clear()
    elif change == 'wrong_account': read['data']['balances'][0]['account'] = 'other'
    elif change == 'wrong_boundary': support['boundary']['selected'][0]['value'] = 'other'
    elif change == 'whole_boundary': support['boundary']['whole'] = True
    elif change == 'wrong_document': support['record_ids'][1] = 'other'
    elif change == 'missing_document': support['record_ids'].pop()
    elif change in {'wrong_page', 'wrong_region'}: provenance[change[6:]] = 'wrong'
    elif change in {'missing_page', 'missing_region'}: provenance.pop(change[8:])
    elif change == 'missing_support': read['figures'].pop(0)
    elif change == 'duplicate_support': read['figures'].append(copy.deepcopy(support))
    elif change == 'undated_support': support['dated'] = ''
    elif change == 'forged_support': support['id'] = 'foreign-f1'; result.bindings['date']['measurement_date_of'] = 'foreign-f1'
    elif change == 'orphan_binding': result.bindings['date']['measurement_date_of'] = 'absent'
    elif change == 'other_read': read['tool'] = 'other'
    elif change == 'wrong_quantity': support['quantity'] = 'owed'
    elif change == 'wrong_kind': support['kind'] = 'hypothetical'
    elif change == 'wrong_grade': support['grade'] = 'inferred'
    elif change == 'missing_grade': support.pop('grade')
    elif change == 'wrong_result_grade': result.grade = 'inferred'
    elif change == 'missing_disclosure': result.disclosures.clear()
    elif change == 'wrong_disclosure': result.disclosures = ['evidence_grade:inferred']
    elif change == 'coverage_disclosure': result.disclosures.append('account_total:partial')
    elif change == 'money_figures': result.figures.append(copy.deepcopy(support))
    elif change == 'money_written': result.written['balance'] = '2400.00'
    elif change == 'money_binding': result.bindings['balance'] = {'figure': support['id']}
    elif change == 'money_slot': raw['shape']['clauses'][0]['slots'].append({'name': 'balance', 'type': 'money'})
    elif change == 'money_text': result.text += ' USD 2400.00'
    elif change == 'missing_clause': raw['shape']['clauses'].clear()
    elif change == 'extra_clause': raw['shape']['clauses'].append(copy.deepcopy(raw['shape']['clauses'][0]))
    elif change == 'missing_read': raw['nodes'].clear()
    elif change == 'extra_read': raw['nodes'].append({**raw['nodes'][0], 'id': 'extra'})
    elif change == 'wrong_selector': raw['bindings'][0]['selector']['cardinality'] = 'many'
    elif change == 'extra_selector': raw['bindings'][0]['selector']['order'] = 'latest'
    elif change == 'missing_binding': raw['bindings'].clear()
    elif change == 'extra_binding': raw['bindings'].append({**raw['bindings'][0], 'hole': 'extra'})
    elif change == 'ordinary_date': raw['bindings'][0]['reference_kind'] = 'date_of'
    elif change == 'non_answered': result.status = 'partial'
    elif change == 'answered_false': result.answered = False
    elif change == 'extra_effect': actual.compilation.semantic_outcome = replace(actual.compilation.semantic_outcome, request=replace(actual.compilation.semantic_outcome.request, requested_claims=('measurement_date', 'balance')))
    elif change == 'missing_read_ok': read['ok'] = False
    elif change == 'forged_data': read['data']['balances'][0]['provenance']['doc_id'] = 'forged'
    elif change == 'forged_read_id': read['id'] = 'other-run-r1'
    elif change == 'incompatible_currency': support['currency'] = 'EUR'
    elif change == 'wrong_support_value': support['value'] = '2401.00'
    else: raise AssertionError(change)
    # Preserve malformed serialized programs to exercise the scorer itself.
    from viva.answer_program.schema import AnswerProgram
    try: actual.compilation.program = AnswerProgram.from_dict(raw)
    except ValueError:
        actual.compilation.program = SimpleNamespace(**{
            **actual.compilation.program.__dict__,
            'shape': SimpleNamespace(to_dict=lambda: raw['shape']),
            'bindings': raw['bindings'], 'nodes': raw['nodes']})


@pytest.mark.parametrize('change', MUTATIONS)
def test_complete_scorer_rejects_one_change_counterfactual(change):
    case, actual = sample()
    mutate(actual, change)
    verdict = score(case, actual)
    assert not verdict.passed
    assert 'invalid_date_only_contract' in verdict.defects
    assert verdict.financial_integrity_errors >= 1


def test_empty_legacy_oracle_is_insufficient():
    case, actual = sample()
    case = replace(case, oracle={'oracle_key': case.oracle_key, 'figures': [], 'exact_figures': True})
    assert not score(case, actual).passed


@pytest.mark.parametrize('field,value', [
    ('date', '2026-02-01'), ('account', 'other'), ('quantity', 'owed'),
    ('kind', 'computed'), ('grade', 'inferred'), ('support_cardinality', 2),
    ('value', '2401.00'), ('currency', 'EUR'),
    ('record_ids', ['other']), ('provenance', {'doc_id': 'other', 'page': 3,
                                             'region': 'other', 'note': ''})])
def test_independent_literal_expectation_is_enforced_by_complete_scorer(monkeypatch, field, value):
    from viva.answer_program import date_contract
    case, actual = sample()
    expected = copy.deepcopy(case.oracle['date_contract'])
    expected[field] = value
    monkeypatch.setattr(date_contract, 'independent_expectation', lambda case: expected)
    case.oracle['date_contract'] = copy.deepcopy(expected)
    assert not score(case, actual).passed


def test_corpus_identity_binds_independent_date_expectation(monkeypatch, tmp_path):
    from viva.answer_program import eval as evaluator
    baseline = evaluator.combined_corpus_digest()
    original = evaluator.versions.path_of
    changed = tmp_path / 'changed.json'
    changed.write_text('{"changed": true}')
    monkeypatch.setattr(evaluator.versions, 'path_of', lambda package, version:
                        changed if version == 'date-only-expectations-v040'
                        else original(package, version))
    assert evaluator.combined_corpus_digest() != baseline


def test_resource_hash_mismatch_fails_oracle_and_complete_scorer(monkeypatch, tmp_path):
    from viva.answer_program import date_contract
    case, actual = sample()
    package = date_contract.Path(date_contract.__file__).resolve().parent.parent
    version = date_contract.versions.active(package, 'date_only_expectations')
    original = date_contract.versions.path_of
    mutated = tmp_path / 'mutated.json'
    mutated.write_bytes(original(package, version).read_bytes() + b'\n')
    monkeypatch.setattr(date_contract.versions, 'path_of', lambda package, name:
                        mutated if name == version else original(package, name))
    with pytest.raises(ValueError, match='fingerprint differs'):
        date_contract.independent_expectation(case)
    assert not score(case, actual).passed


@pytest.mark.parametrize('mutation', ['stale_literal_date', 'fresh_fixture_date'])
def test_date_preflight_blocks_inconsistent_source_before_compiler(monkeypatch, mutation):
    from viva.answer_program import admission_fixture, date_contract
    from viva.answer_program.admission import (
        AdmissionPreflightError, AdmissionThresholds, preflight_live_suite, run_live_suite)
    case = next(c for c in load_cases() if c.id == 'follow-up-account-date')
    if mutation == 'stale_literal_date':
        literal = date_contract.independent_expectation(case)
        literal['date'] = '2026-02-01'
        monkeypatch.setattr(date_contract, 'independent_expectation', lambda case: copy.deepcopy(literal))
    else:
        original = admission_fixture.closing_balance_observed
        def changed(account, amount, date, *args, **kwargs):
            if account == 'Assets:Admission:Investment': date = '2026-02-01'
            return original(account, amount, date, *args, **kwargs)
        monkeypatch.setattr(admission_fixture, 'closing_balance_observed', changed)
    entries = []
    def forbidden_compiler(*args, **kwargs):
        entries.append('compiler')
        raise AssertionError('compiler must not be constructed')
    with pytest.raises(AdmissionPreflightError):
        preflight_live_suite(cases=(case,), locale='en-US')
    with pytest.raises(AdmissionPreflightError):
        run_live_suite(cases=(case,), compiler_factory=forbidden_compiler,
                       thresholds=AdmissionThresholds(1, 1, 1), locale='en-US')
    assert entries == []


def test_date_oracle_preflight_checks_expected_selection_without_a_compiler():
    from viva.answer_program.admission import preflight_live_suite
    case, actual = sample()
    oracle_set, _ = preflight_live_suite(cases=(replace(case, oracle=None),), locale='en-US')
    prepared = replace(case, oracle=oracle_set.oracle_for(case.id))
    assert score(prepared, actual).passed


def test_preflight_treats_binder_delivery_as_test_subject(monkeypatch):
    from viva.answer_program.admission import AdmissionPreflightError, preflight_live_suite
    from viva.answer_program.bind import DeterministicBinder
    case = next(c for c in load_cases() if c.id == 'follow-up-account-date')
    original = DeterministicBinder.bind
    def wrong_date(self, program, execution):
        bound = original(self, program, execution)
        bound.result.written['date'] = '2026-02-01'
        return bound
    monkeypatch.setattr(DeterministicBinder, 'bind', wrong_date)
    with pytest.raises(AdmissionPreflightError):
        preflight_live_suite(cases=(case,), locale='en-US')
