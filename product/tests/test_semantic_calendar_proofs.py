"""Ordinary period proofs retain the bounded calendar contract in both protocols."""
import copy
import hashlib
import json

import pytest

from viva.answer_program.intents import SemanticFamilyRegistry, SEMANTIC_REQUEST_VERSION
from viva.answer_program.schema import ContractError, QuestionContext
from viva.tools.registry import PACKAGE, _validate
from vivacore import versions


PREDECESSOR_HASHES = {
    'semantic-request-v13': '8e57e8c2804e1859fd3a3ff0d20615008ad834cb2c224c3892c71e4874eabf6d',
    'semantic-request-retry-v11': '5d7986d0711a57b90773b8d8c56bae8a61a29a5bd88190927a606af3fe39ee90',
    'semantic-request-schema-v10': '950b9d05a85bbd88fea32683e5e81d9f13aafc629f0b2169f15d0a29beea2e87',
}


def _check_predecessors(read):
    for version, expected in PREDECESSOR_HASHES.items():
        assert hashlib.sha256(read(version)).hexdigest() == expected


def test_predecessor_bytes_and_released_fingerprints_remain_pinned(tmp_path):
    _check_predecessors(lambda version: versions.path_of(PACKAGE, version).read_bytes())
    released = versions.manifest(PACKAGE)['released']
    for version, expected in PREDECESSOR_HASHES.items():
        assert released[version] == expected[:16]
    for version in PREDECESSOR_HASHES:
        (tmp_path / version).write_bytes(versions.path_of(PACKAGE, version).read_bytes())
    changed = tmp_path / 'semantic-request-v13'
    changed.write_bytes(changed.read_bytes() + b'\n')
    with pytest.raises(AssertionError):
        _check_predecessors(lambda version: (tmp_path / version).read_bytes())


def test_schema_successor_has_exactly_27_version_label_changes():
    previous = json.loads(versions.path_of(PACKAGE, 'semantic-request-schema-v10').read_text())
    current = json.loads(versions.path_of(PACKAGE, 'semantic-request-schema-v11').read_text())
    assert len(previous['oneOf']) == 27
    for branch in previous['oneOf']:
        version = branch['properties']['request_version']
        assert version['enum'] == ['semantic-request-v13']
        version['enum'] = ['semantic-request-v14']
    assert current == previous
    assert json.loads(versions.path_of(PACKAGE, versions.active(PACKAGE,
        'semantic_request_schema')).read_text()) == SemanticFamilyRegistry().output_schema()


def _request(parameters, proofs, comparison=False):
    families = SemanticFamilyRegistry()
    raw = {'request_version': SEMANTIC_REQUEST_VERSION, 'outcome': 'request',
           'family': 'spending_comparison' if comparison else 'spending_by_category',
           'catalog_digest': families.catalog_digest,
           'entity_catalog_digest': families.entity_catalog_digest,
           'parameters': parameters, 'parameter_sources': proofs,
           'requested_claims': ['comparison'] if comparison else ['spending']}
    return families, raw


def _parse(families, raw, context, mode):
    if mode == 'native':
        schema = next(tool['parameters'] for tool in families.model_tools()
                      if tool['name'] == 'select_' + raw['family'])
        arguments = {key: raw[key] for key in ('parameters', 'parameter_sources', 'requested_claims')}
        assert not _validate(schema, arguments)
        envelope = {key: value for key, value in raw.items() if key not in arguments}
        output = dict(envelope, **arguments)
    else:
        schema = next(branch for branch in families.model_output_schema()['oneOf']
                      if branch['properties'].get('family', {}).get('enum') == [raw['family']])
        assert not _validate(schema, raw)
        output = json.loads(json.dumps(raw))
    return families.parse(families.materialize_model_output(output), context)


def _month(quote, start, end, prefix='', source='question', turn=None):
    parameters = {prefix + 'from': start, prefix + 'to': end}
    proofs = {prefix + name: {'source': source, 'quote': quote,
                            'derivation': 'calendar_month_' + edge}
              for name, edge in [('from', 'start'), ('to', 'end')]}
    if turn is not None:
        for proof in proofs.values():
            proof['turn'] = turn
    return parameters, proofs


@pytest.mark.parametrize('mode', ['native', 'text'])
@pytest.mark.parametrize('source', ['question', 'prior_turn'])
@pytest.mark.parametrize('quote,start,end', [
    ('February 2024', '2024-02-01', '2024-02-29'),
    ('Feb 2025', '2025-02-01', '2025-02-28'),
    ('2024-02', '2024-02-01', '2024-02-29'),
    ('December 2025', '2025-12-01', '2025-12-31'),
    ('Jan 2026', '2026-01-01', '2026-01-31'),
])
def test_minimal_calendar_month_proofs_use_current_or_numbered_prior_source(mode, source, quote, start, end):
    question = 'Show spending between the first and last day of ' + quote + '.'
    values, proofs = _month(quote, start, end, source=source,
                            turn=1 if source == 'prior_turn' else None)
    families, raw = _request(values, proofs)
    context = (QuestionContext(question=question) if source == 'question' else
               QuestionContext(question='Break that period down by category.',
                               prior_turns=(('Earlier unrelated context.', 'Recorded.'), (question, 'Recorded.'))))
    outcome = _parse(families, raw, context, mode)
    assert outcome.kind == 'request'
    assert outcome.request.parameters == values


@pytest.mark.parametrize('mode', ['native', 'text'])
def test_current_and_baseline_months_and_explicit_iso_edges(mode):
    values, proofs = _month('January 2026', '2026-01-01', '2026-01-31')
    baseline, support = _month('December 2025', '2025-12-01', '2025-12-31', 'baseline_')
    values.update(baseline); proofs.update(support)
    families, raw = _request(values, proofs, comparison=True)
    context = QuestionContext(question='Compare spending during January 2026 with December 2025.')
    assert _parse(families, raw, context, mode).kind == 'request'
    for name in ('from', 'to'):
        raw['parameter_sources'][name].update(quote=values[name], derivation='verbatim')
    context = QuestionContext(question='Compare spending from 2026-01-01 through 2026-01-31 with December 2025.')
    assert _parse(families, raw, context, mode).kind == 'request'


@pytest.mark.parametrize('mode', ['native', 'text'])
@pytest.mark.parametrize('defect,error', [
    ('ellipsis', 'quotes text not in its source'),
    ('discontinuous', 'quotes text not in its source'),
    ('long_clause', 'needs a month and year'),
    ('absent_quote', 'quotes text not in its source'),
    ('wrong_edge', 'does not match its derived month'),
    ('absent_prior', 'names no prior turn'),
    ('wrong_turn', 'quotes text not in its source'),
    ('wrong_attribution', 'quotes text not in its source'),
])
def test_invalid_ordinary_period_sources_retain_rejection_reasons(mode, defect, error):
    values, proofs = _month('February 2024', '2024-02-01', '2024-02-29')
    families, raw = _request(values, proofs)
    context = QuestionContext(question='Show spending between the first and last day of February 2024.',
                              prior_turns=(('Show spending for January 2024.', 'Recorded.'),))
    proof = raw['parameter_sources']['from']
    if defect == 'ellipsis': proof['quote'] = 'first and last day … February 2024'
    elif defect == 'discontinuous': proof['quote'] = 'spending February 2024'
    elif defect == 'long_clause': proof['quote'] = 'the first and last day of February 2024'
    elif defect == 'absent_quote': proof['quote'] = 'March 2024'
    elif defect == 'wrong_edge': raw['parameters']['from'] = '2024-02-29'
    elif defect == 'absent_prior': proof.update(source='prior_turn', turn=1)
    elif defect == 'wrong_turn': proof.update(source='prior_turn', turn=0)
    else:
        proof['quote'] = 'January 2024'
        raw['parameters']['from'] = '2024-01-01'
    with pytest.raises(ContractError, match=error):
        _parse(families, raw, context, mode)
