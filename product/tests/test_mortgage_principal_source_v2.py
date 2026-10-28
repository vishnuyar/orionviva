"""Public signed mortgage proposals keep source text and canonical direction apart."""
import base64
import copy
import json
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest

from viva.ingest import instrument_contracts as c
from viva.ingest.instrument_parser import parse_instrument_json
from viva.ingest.instrument_read import parser_for
from viva.normalization_context import (
    ExtractionNormalizationContext as Context, MORTGAGE_SOURCE_CONTRACT,
    decode_context, encode_context, source_contract_for_claim,
)
from test_instrument_reader_b import _proposal, _raw

VERSION = 'extract:mortgage-base-v2+mortgage-v2'
CONTEXT = Context(2, 'nv1', 'en-US', 'USD', MORTGAGE_SOURCE_CONTRACT)
KINDS = ['advance', 'principal_reduction', 'payoff', 'increase_adjustment', 'decrease_adjustment']


def proposal(kind='principal_reduction', amount='-100', page=1, kind_page=1):
    value = _proposal('mortgage_statement')
    row = value['principal_movements'][0]
    row.pop('amount')
    row.update(kind=kind, signed_effect=_raw(amount, page),
               effect_basis='principal_balance_effect-v1', kind_source={'page': kind_page})
    return value


def parse(value, **kwargs):
    return parse_instrument_json(json.dumps(value), 'mortgage_statement', 'public-source',
                                 source_contract=MORTGAGE_SOURCE_CONTRACT, **kwargs)


def claim(value, **changes):
    body = {'response_text': json.dumps(value), 'prompt_version': VERSION,
            'normalization_context': encode_context(CONTEXT), 'parse_ok': True}
    body.update(changes)
    return body


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('amount', ['-100', '100'])
def test_every_kind_sign_pair_requires_agreement(kind, amount):
    decreasing = kind in {'principal_reduction', 'payoff', 'decrease_adjustment'}
    if decreasing != amount.startswith('-'):
        with pytest.raises(ValueError, match='contradicts'):
            parse(proposal(kind, amount))
    else:
        row = parse(proposal(kind, amount)).principal_movements[0]
        assert row.kind.value == kind and row.amount.value == Decimal('100')
        assert row.amount.source == c.Source('public-source', 1)


@pytest.mark.parametrize('amount', ['0', '-0', '0.00', 'NaN', 'Infinity', 'not printed'])
def test_zero_unreadable_and_nonfinite_effects_reject(amount):
    with pytest.raises(ValueError):
        parse(proposal(amount=amount))


@pytest.mark.parametrize('mutation', [
    'amount-too', 'missing-basis', 'unknown-basis', 'missing-kind', 'null-kind',
    'unknown-kind', 'missing-kind-source', 'zero-kind-page', 'bool-kind-page',
    'unknown-source-field', 'null-kind-source', 'missing-signed-effect',
])
def test_closed_signed_variant_never_infers_missing_parts(mutation):
    value = proposal(); row = value['principal_movements'][0]
    if mutation == 'amount-too': row['amount'] = _raw('100')
    elif mutation == 'missing-basis': row.pop('effect_basis')
    elif mutation == 'unknown-basis': row['effect_basis'] = 'cash_effect'
    elif mutation == 'missing-kind': row.pop('kind')
    elif mutation == 'null-kind': row['kind'] = None
    elif mutation == 'unknown-kind': row['kind'] = 'reversal'
    elif mutation == 'missing-kind-source': row.pop('kind_source')
    elif mutation == 'zero-kind-page': row['kind_source']['page'] = 0
    elif mutation == 'bool-kind-page': row['kind_source']['page'] = True
    elif mutation == 'unknown-source-field': row['kind_source']['doc_id'] = 'invented'
    elif mutation == 'null-kind-source': row['kind_source'] = None
    elif mutation == 'missing-signed-effect': row.pop('signed_effect')
    with pytest.raises(ValueError): parse(value)


def test_exact_raw_source_kind_and_pages_survive_without_mutating_claim():
    value = proposal(amount='($100.00)', page=2, kind_page=3)
    before = copy.deepcopy(value)
    row = parse(value, page_count=3).principal_movements[0]
    assert row.amount.value == Decimal('100.00')
    assert row.amount.source.page == 2
    assert value == before
    assert value['principal_movements'][0]['signed_effect']['raw'] == '($100.00)'
    with pytest.raises(ValueError, match='outside'): parse(value, page_count=2)


@pytest.mark.parametrize('field', ['principal', 'interest', 'escrow', 'total'])
def test_negative_payment_components_keep_their_prior_semantics(field):
    value = proposal(); value['payments'][0][field] = _raw('-100')
    legacy = copy.deepcopy(value); legacy['principal_movements'] = []
    old = parse_instrument_json(json.dumps(legacy), 'mortgage_statement', 'public-source')
    new = parse(value)
    assert getattr(new.payments[0], field) == getattr(old.payments[0], field)
    assert getattr(new.payments[0], field).value == Decimal('-100')


def test_negative_escrow_movement_stays_rejected_and_legacy_magnitude_stays_compatible():
    value = proposal(); value['escrow']['movements'][0]['amount'] = _raw('-100')
    with pytest.raises(ValueError, match='positive magnitude'): parse(value)
    magnitude = _proposal('mortgage_statement')
    assert parse(magnitude) == parse_instrument_json(json.dumps(magnitude), 'mortgage_statement', 'public-source')
    magnitude['principal_movements'][0]['amount'] = _raw('-100')
    with pytest.raises(ValueError, match='positive magnitude'): parse(magnitude)


def test_context_two_is_closed_while_context_one_encoding_is_byte_compatible():
    old = Context(1, 'nv1', 'en-US', 'USD')
    assert encode_context(old) == {'schema_version': 1, 'normalization_rules_version': 'nv1',
                                  'parser_locale': 'en-US', 'parser_currency': 'USD'}
    assert decode_context(encode_context(CONTEXT)) == CONTEXT
    for delta in ({'instrument_source_contract': None}, {'instrument_source_contract': 'other'},
                  {'schema_version': 1}, {'unknown': 'field'}):
        body = {**encode_context(CONTEXT), **delta}
        with pytest.raises(ValueError): decode_context(body)
    body = encode_context(CONTEXT); body.pop('instrument_source_contract')
    with pytest.raises(ValueError): decode_context(body)
    with pytest.raises(ValueError): Context(1, 'nv1', 'en-US', 'USD', MORTGAGE_SOURCE_CONTRACT)


@pytest.mark.parametrize('context,version,kind', [
    (None, VERSION, 'mortgage_statement'),
    (Context(1, 'nv1', 'en-US', 'USD'), VERSION, 'mortgage_statement'),
    (CONTEXT, 'extract:mortgage-base-v1+mortgage-v1', 'mortgage_statement'),
    (CONTEXT, 'extract:mortgage-base-v2+mortgage-v1', 'mortgage_statement'),
    (CONTEXT, VERSION, 'term_deposit_statement'),
    (CONTEXT, VERSION + '+mortgage-v1', 'mortgage_statement'),
    (CONTEXT, VERSION + '+unknown-retry', 'mortgage_statement'),
])
def test_context_profile_prompt_mismatch_rejects(context, version, kind):
    with pytest.raises(ValueError): source_contract_for_claim(context, kind, version)


def test_legacy_negative_failure_is_not_reinterpreted_under_current_profile():
    from viva.rebuild import _parse_claim
    value = _proposal('mortgage_statement'); value['principal_movements'][0]['amount'] = _raw('-100')
    for context in (None, Context(1, 'nv1', 'en-US', 'USD')):
        body = {'response_text': json.dumps(value), 'prompt_version': 'extract:mortgage-base-v1+mortgage-v1', 'parse_ok': False}
        if context is not None: body['normalization_context'] = encode_context(context)
        facts, error, retained = _parse_claim('mortgage_statement', body, 'public-source', 'en-US', 'USD')
        assert facts is None and 'positive magnitude' in error and retained == context
    facts, error, context = _parse_claim('mortgage_statement', claim(proposal()), 'public-source', 'fr-FR', 'EUR')
    assert error is None and context == CONTEXT and facts.payload.principal_movements[0].amount.value == 100


def response(text):
    from vivacore.models.base import ModelResult
    return ModelResult(text, 'offline-resolved', 3, 2, 0.01, 0, {}, {})


def test_retry_retains_both_contexts_original_failed_text_and_exact_copy_prompt():
    from viva.ingest.reader import read_with_retry
    first = json.dumps(proposal(amount='100')); second = json.dumps(proposal())
    calls = []; phases = []
    def extract(prompt):
        calls.append(prompt)
        if len(calls) == 2: assert len(phases) == 1 and phases[0].raw_text == first
        return response(first if len(calls) == 1 else second)
    result = read_with_retry(extract, 'public source prompt', 'public-source', 'en-US', 'USD',
        prompt_version=VERSION, parse_fn=parser_for('mortgage_statement', source_contract=MORTGAGE_SOURCE_CONTRACT),
        phase_sink=phases.append, extraction_context=CONTEXT, source_doc_type="mortgage_statement")
    assert result.facts is not None and len(calls) == len(phases) == 2
    assert not phases[0].parse_ok and phases[1].parse_ok
    assert all(p.normalization_context == CONTEXT for p in phases)
    assert phases[1].raw_text == second and phases[1].prompt_version.startswith(VERSION + '+')
    assert first == json.dumps(proposal(amount='100'))


@pytest.mark.parametrize('scoped', [False, True])
def test_ordinary_and_bulk_prepared_paths_select_same_backend_contract(monkeypatch, scoped):
    from viva.ingest import reader
    calls = []; phases = []
    class Adapter:
        def extract(self, pages, prompt):
            calls.append(prompt)
            return response(json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': .8})
                            if len(calls) == 1 else json.dumps(proposal()))
    monkeypatch.setattr(reader, 'adapter_for', lambda _: Adapter())
    monkeypatch.setattr(reader, '_render_and_read_text', lambda _: ([object()], 'public printed text'))
    spec = SimpleNamespace(model='offline-configured', json_mode=True)
    if scoped:
        result = reader.read_prepared_statement((object(),), 'public printed text', 'public-source', spec,
            'en-US', 'USD', phase_sink=lambda phase, *_: phases.append(phase), permit=lambda: True)
    else:
        result = reader.read_statement(b'public original', 'public-source', spec, 'en-US', 'USD')
        phases = result.phases
    assert result.facts is not None, result.error
    assert result.facts.payload.principal_movements[0].amount.value == 100
    assert phases[0].normalization_context is None and phases[1].normalization_context == CONTEXT
    assert result.normalization_context == CONTEXT
    assert 'signed_effect' in calls[1] and 'principal_balance_effect-v1' in calls[1]


def test_stop_denies_retry_after_durable_failed_raw_and_phase(monkeypatch):
    from test_extraction_responses import install, spec, wire
    from viva.ingest.reader import read_prepared_statement
    from vivacore.models import PageImage
    calls = []; raws = []; phases = []; stopped = False
    def post(body):
        calls.append(copy.deepcopy(body))
        if len(calls) == 1: return wire('openai-compatible', json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': 1}))
        return wire('openai-compatible', json.dumps(proposal(amount='100')))
    install(monkeypatch, 'openai-compatible', post)
    def phase_sink(phase, *_):
        nonlocal stopped
        phases.append(copy.deepcopy(phase))
        if phase.phase == 'extract': stopped = True
    def raw_sink(body):
        raws.append(copy.deepcopy(body)); return 'public-receipt-' + str(len(raws))
    result = read_prepared_statement((PageImage(1, b'public image', 'public-sha'),), 'public text',
        'public-source', spec(), 'en-US', 'USD', phase_sink=phase_sink,
        permit=lambda: not stopped, response_sink=raw_sink)
    assert len(calls) == len(raws) == len(phases) == 2
    assert result.facts is None and result.error == 'read stopped'
    assert phases[1].normalization_context == CONTEXT and not phases[1].parse_ok
    raw = json.loads(base64.b64decode(raws[1]['response_bytes_base64']))
    assert raw['choices'][0]['message']['content'] == phases[1].raw_text
    assert phases[1].transport_receipt_ids == ['public-receipt-2']


def test_replay_validates_kind_page_against_existing_render_and_keeps_source_prefix(tmp_path, monkeypatch):
    from viva.vault import Vault
    from viva.ingest import capture_and_ingest
    from viva.ingest.reader import read_with_retry
    from viva.rebuild import rebuild, _parse_claim
    value = proposal(kind_page=2); original_text = json.dumps(value)
    preliminary, error, _ = _parse_claim('mortgage_statement', claim(value, parse_ok=False), 'public-source', 'en-US', 'USD')
    assert preliminary is not None and error is None  # Preliminary parse has no rendered-page assertion.
    vault = Vault.open(tmp_path / 'source', 'public-only-test-phrase', start_read_store_worker=False)
    def read(data, doc_id):
        return read_with_retry(lambda _: response(original_text), 'public prompt', doc_id, 'en-US', 'USD',
            prompt_version=VERSION, max_retries=0, extraction_context=CONTEXT, source_doc_type="mortgage_statement",
            parse_fn=parser_for('mortgage_statement', source_contract=MORTGAGE_SOURCE_CONTRACT, page_count=1))
    capture_and_ingest(vault.raw, vault.ledger, b'public captured PDF fixture', read)
    prefix = copy.deepcopy([e.to_dict() for e in vault.ledger.events()])
    vault.ledger.projection()
    assert [e.to_dict() for e in vault.ledger.events()] == prefix
    vault.close()
    rendered = []
    def render(data): rendered.append(data); return [object()], 'public text'
    monkeypatch.setattr('viva.ingest.reader._render_and_read_text', render)
    rebuild(tmp_path / 'source', tmp_path / 'destination', 'public-only-test-phrase', log=lambda _: None)
    assert rendered == [b'public captured PDF fixture']
    destination = Vault.open(tmp_path / 'destination', 'public-only-test-phrase', start_read_store_worker=False)
    try:
        reads = [e.body for e in destination.ledger.events() if e.event_type == 'ReadRecorded']
        assert reads and reads[-1]['parse_ok'] is False
        assert reads[-1]['response_text'] == original_text
        assert reads[-1]['normalization_context'] == encode_context(CONTEXT)
        assert not [e for e in destination.ledger.events() if e.event_type == 'ClosingBalanceObserved']
    finally:
        destination.close()


@pytest.mark.parametrize('context,version,kind,locale', [
    (CONTEXT, 'extract:mortgage-base-v1+mortgage-v1', 'mortgage_statement', 'en-US'),
    (CONTEXT, VERSION, 'term_deposit_statement', 'en-US'),
    (CONTEXT, VERSION, 'mortgage_statement', 'de-DE'),
    (Context(1, 'nv1', 'en-US', 'USD'), VERSION, 'mortgage_statement', 'en-US'),
])
def test_mismatched_live_context_stops_before_new_extraction(context, version, kind, locale):
    from viva.ingest.reader import read_with_retry
    calls = []
    with pytest.raises(ValueError):
        read_with_retry(lambda _: calls.append(True), 'public prompt', 'public-source', locale, 'USD',
            prompt_version=version, extraction_context=context, source_doc_type=kind)
    assert calls == []


def test_incomplete_signed_extract_retains_backend_context_and_raw_prefix(monkeypatch):
    from test_extraction_responses import install, spec, wire
    from viva.ingest.reader import read_prepared_statement
    from vivacore.models import PageImage
    calls = []; raws = []; phases = []; stopped = False
    def post(body):
        nonlocal stopped
        calls.append(body)
        if len(calls) == 1:
            return wire('openai-compatible', json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': 1}))
        stopped = True
        return wire('openai-compatible', '{"principal_movements":[', truncated=True)
    install(monkeypatch, 'openai-compatible', post)
    def retain(body): raws.append(copy.deepcopy(body)); return 'prefix-' + str(len(raws))
    result = read_prepared_statement((PageImage(1, b'image', 'sha'),), 'public text', 'public-source',
        spec(), 'en-US', 'USD', phase_sink=lambda phase, *_: phases.append(copy.deepcopy(phase)),
        response_sink=retain, permit=lambda: not stopped)
    assert len(calls) == len(raws) == len(phases) == 2 and result.facts is None
    assert phases[1].normalization_context == CONTEXT
    assert phases[1].transport_complete is False and phases[1].transport_receipt_ids == ['prefix-2']
    assert phases[1].raw_text == '{"principal_movements":['


from test_bulk_upload import setup_bulk


def test_actual_bulk_coordinator_retains_new_contract_for_each_worker(setup_bulk, monkeypatch):
    from viva.ingest import reader
    from viva.desktop_bridge.bulk_documents import BulkDocuments
    from viva.desktop_bridge.jobs import JobRegistry
    sample = setup_bulk
    class Adapter:
        def __init__(self): self.calls = 0
        def extract(self, pages, prompt):
            self.calls += 1
            return response(json.dumps({'doc_type': 'mortgage_statement', 'doc_type_confidence': 1})
                            if self.calls == 1 else json.dumps(proposal()))
    monkeypatch.setattr(reader, 'adapter_for', lambda _: Adapter())
    result = BulkDocuments(sample.vault, JobRegistry()).run({'paths': sample.paths})
    assert len(result['rows']) == 3
    extracts = [e.body for e in sample.vault.ledger.events()
                if e.event_type == 'ReadRecorded' and e.body['phase'] == 'extract']
    assert len(extracts) == 3 and all(e['parse_ok'] for e in extracts), result
    assert all(e['normalization_context'] == encode_context(CONTEXT) for e in extracts)
    assert all(e['prompt_version'].startswith('extract:mortgage-base-v2+mortgage-v3+') for e in extracts)
    assert all(json.loads(e['response_text'])['principal_movements'][0]['signed_effect']['raw'] == '-100'
               for e in extracts)
