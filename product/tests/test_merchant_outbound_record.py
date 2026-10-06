"""Synthetic merchant calls must remain visible in the vault's Trust record."""

import copy
import json
import socket
from decimal import Decimal

import httpx
import pytest

from viva.enrich import enrich_live_merchants, recorded_model_extractor
from viva.ingest import ReadResult, StatementFacts, TxnFact, capture_and_ingest
from viva.surface.outbound import outbound
from viva.vault import Vault
from vivacore.models import ModelSpec
from vivacore.models.base import AdapterError, ModelResult
from vivacore.errors import ConfigError


REPLY = '{"purple harbor kiosk":{"canonical_name":"Purple Harbor Kiosk","category":"shopping"}}'


@pytest.fixture
def subject(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('network access forbidden in synthetic merchant tests')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket, 'create_connection', denied)
    monkeypatch.setattr(ModelSpec, 'api_key', lambda self: None)
    monkeypatch.setenv('VIVA_MODEL_ADAPTER', 'openai-compatible')
    monkeypatch.setenv('VIVA_MODEL', 'synthetic-route')
    monkeypatch.setenv('VIVA_MODEL_BASE_URL', 'http://synthetic.invalid/v1')
    monkeypatch.setenv('VIVA_CATALOG', str(tmp_path/'catalog.json'))
    monkeypatch.setenv('MERCHANTCORE_HOME', str(tmp_path/'merchant-home'))
    vault = Vault.open(tmp_path/'vault', 'synthetic-passphrase')
    facts = StatementFacts(doc_id='', doc_type='credit_card_statement',
        doc_type_confidence=.98, account_ref='Synthetic Card', currency='USD',
        opening_amount=Decimal(0), opening_date='2026-01-01',
        closing_amount=Decimal('50.00'), closing_date='2026-01-31',
        transactions=[TxnFact('2026-01-05', 'PURPLE HARBOR KIOSK #1234', Decimal('50.00'))],
        account_number='000000007799', institution='Synthetic Bank')
    def read(data, doc_id):
        facts.doc_id = doc_id
        return ReadResult(facts.doc_type, .98, facts)
    capture_and_ingest(vault.raw, vault.ledger, b'synthetic statement', read,
                       captured_at='2026-02-01')
    return vault


def response(text=REPLY, finish='stop', usage=None):
    body = {'model':'synthetic-reported-model', 'choices':[{
        'message':{'content':text}, 'finish_reason':finish}]}
    if usage is not None:
        body['usage'] = usage
    return httpx.Response(200, json=body)


def calls(vault):
    return [event for event in vault.ledger.events()
            if event.event_type == 'ReadRecorded' and event.body.get('phase') == 'merchant_enrich']


def test_automatic_merchant_call_is_recorded_without_changing_financial_facts(subject, monkeypatch):
    before = copy.deepcopy(subject.ledger.projection().movements())
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return response(usage={'prompt_tokens':11, 'completion_tokens':4, 'cost':.002})
    monkeypatch.setattr(httpx, 'post', post)
    result = enrich_live_merchants(subject)
    assert result['enriched'] == 1
    assert len(sent) == len(calls(subject)) == 1
    record = calls(subject)[0].body
    assert record['model'] == 'synthetic-route'
    assert record['resolved_model'] == 'synthetic-reported-model'
    assert record['cost_usd'] == .002
    assert record['input_tokens'] == 11 and record['output_tokens'] == 4
    assert subject.ledger.projection().movements() == before
    for value in ['50.00', '000000007799', '2026-01-05', 'Synthetic Bank']:
        assert value not in json.dumps(sent)
    reopened = Vault.open(subject.directory, 'synthetic-passphrase')
    assert len(calls(reopened)) == 1
    assert outbound(reopened.ledger.events())['call_count'] == 1


@pytest.mark.parametrize('usage, expected', [
    (None, None), ({}, None), ({'cost': None}, None),
    ({'cost': True}, None), ({'cost': -1}, None),
    ({'cost': 'NaN'}, None), ({'cost': 'Infinity'}, None),
    ({'cost': '1e999'}, None), ({'cost': '1e-999'}, None),
    ({'cost': 'not a price'}, None), ({'cost': 0}, 0),
    ({'cost': '0.003'}, .003),
])
def test_only_explicit_valid_provider_prices_are_measured(subject, monkeypatch, usage, expected):
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: response(usage=usage))
    enrich_live_merchants(subject)
    assert calls(subject)[0].body['cost_usd'] == expected
    cost = outbound(subject.ledger.events())['cost']
    if expected is None:
        assert cost is None
    else:
        assert Decimal(cost['exact_value']) == Decimal(str(expected))
        assert cost['measured_calls'] == 1
        assert 'subtotal' in cost['sentence']


@pytest.mark.parametrize('usage, expected', [
    ({}, {}), ({'prompt_tokens': 0}, {'input_tokens': 0}),
    ({'completion_tokens': 3}, {'output_tokens': 3}),
    ({'prompt_tokens': True, 'completion_tokens': -1}, {}),
    ({'input_tokens': 7, 'output_tokens': 0}, {'input_tokens': 7, 'output_tokens': 0}),
])
def test_partial_usage_is_not_filled_with_invented_zeroes(subject, monkeypatch, usage, expected):
    monkeypatch.setattr(httpx, 'post', lambda *a, **kw: response(usage=usage))
    enrich_live_merchants(subject)
    body = calls(subject)[0].body
    assert {key: body[key] for key in ('input_tokens', 'output_tokens') if key in body} == expected
    assert body.get('usage_reported', False) == bool(expected)


def test_continuations_record_each_receipt_and_preserve_request_behavior(subject, monkeypatch):
    cut = len(REPLY) // 2
    replies = [response(REPLY[:cut], 'length', {'cost': .001}),
               response(REPLY[cut:], 'stop')]
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return replies[len(sent)-1]
    monkeypatch.setattr(httpx, 'post', post)
    assert enrich_live_merchants(subject)['enriched'] == 1
    assert len(sent) == len(calls(subject)) == 2
    assert sent[1]['messages'][1]['content'] == REPLY[:cut]
    assert 'response_format' in sent[0] and 'response_format' not in sent[1]
    envelopes = [json.loads(c.body['response_text']) for c in calls(subject)]
    assert [e['attempt'] for e in envelopes] == [0, 1]
    assert [e['text'] for e in envelopes] == [REPLY[:cut], REPLY[cut:]]
    assert [c.body['cost_usd'] for c in calls(subject)] == [.001, None]
    panel = outbound(subject.ledger.events())
    assert panel['call_count'] == 2 and panel['cost']['measured_calls'] == 1


@pytest.mark.parametrize('failure', ['timeout', 'http', 'malformed'])
@pytest.mark.parametrize('first_succeeded', [False, True])
def test_failed_attempt_is_visible_without_claiming_delivery_or_charge(subject, monkeypatch, failure, first_succeeded):
    before = copy.deepcopy(subject.ledger.projection().movements())
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        if first_succeeded and len(sent) == 1:
            return response(REPLY[:10], 'length', {'cost': .001})
        if failure == 'timeout':
            raise httpx.ReadTimeout('PRIVATE_ERROR_BODY synthetic credential')
        if failure == 'http':
            return httpx.Response(503, text='PRIVATE_ERROR_BODY synthetic credential')
        return httpx.Response(200, text='PRIVATE_ERROR_BODY synthetic credential')
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises((AdapterError, ValueError)):
        enrich_live_merchants(subject)
    assert len(sent) == len(calls(subject)) == (2 if first_succeeded else 1)
    body = calls(subject)[-1].body
    envelope = json.loads(body['response_text'])
    assert envelope['transport_status'] == 'failed'
    assert envelope['delivery_status'] == 'unknown'
    assert envelope['attempt'] == int(first_succeeded)
    assert 'PRIVATE_ERROR_BODY' not in body['response_text']
    assert body['cost_usd'] is None and 'input_tokens' not in body and 'output_tokens' not in body
    assert not body.get('resolved_model')
    assert subject.ledger.projection().movements() == before
    reopened = Vault.open(subject.directory, 'synthetic-passphrase')
    assert len(calls(reopened)) == len(sent)


@pytest.mark.parametrize('adapter', ['openai-compatible', 'anthropic'])
@pytest.mark.parametrize('configuration', ['missing_model', 'missing_key', 'unknown_adapter'])
def test_configuration_failure_before_extraction_creates_no_outbound_entry(subject, monkeypatch, configuration, adapter):
    monkeypatch.setenv('VIVA_MODEL_ADAPTER', adapter)
    def forbidden(*args, **kwargs):
        raise AssertionError('a configuration failure must not invoke transport')
    monkeypatch.setattr(httpx, 'post', forbidden)
    if configuration == 'missing_model':
        monkeypatch.delenv('VIVA_MODEL')
        assert enrich_live_merchants(subject)['submitted'] == 0
    else:
        if configuration == 'missing_key':
            def missing(self):
                raise ConfigError('synthetic missing key')
            monkeypatch.setattr(ModelSpec, 'api_key', missing)
        else:
            monkeypatch.setenv('VIVA_MODEL_ADAPTER', 'synthetic-unknown')
        with pytest.raises((ConfigError, AdapterError)):
            enrich_live_merchants(subject)
    assert calls(subject) == []


def test_repeat_with_installed_catalog_makes_no_request(subject, monkeypatch):
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return response()
    monkeypatch.setattr(httpx, 'post', post)
    enrich_live_merchants(subject)
    assert enrich_live_merchants(subject)['enriched'] == 0
    assert len(sent) == len(calls(subject)) == 1


def test_cli_uses_the_same_recorder(subject, monkeypatch, capsys):
    import viva.enrich
    monkeypatch.setenv('VIVA_VAULT_DIR', str(subject.directory))
    monkeypatch.setenv('VIVA_PASSPHRASE', 'synthetic-passphrase')
    monkeypatch.setattr(viva.enrich.sys, 'argv', ['viva.enrich'])
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return response()
    monkeypatch.setattr(httpx, 'post', post)
    viva.enrich.main()
    reopened = Vault.open(subject.directory, 'synthetic-passphrase')
    assert len(sent) == len(calls(reopened)) == 1
    assert 'enriched 1' in capsys.readouterr().out


def test_successful_legacy_adapter_records_unknown_receipt_without_route_as_provider(subject, monkeypatch):
    class LegacyAdapter:
        def extract(self, pages, prompt):
            return ModelResult(text=REPLY, resolved_model='configured fallback',
                input_tokens=0, output_tokens=0, cost_usd=0, latency_s=0,
                request={'synthetic': True}, response={})
    import vivacore.models
    monkeypatch.setattr(vivacore.models, 'adapter_for', lambda spec: LegacyAdapter())
    enrich_live_merchants(subject)
    body = calls(subject)[0].body
    assert body['cost_usd'] is None and not body.get('resolved_model')
    assert 'input_tokens' not in body and 'output_tokens' not in body


def test_enrichment_chunks_have_separate_recorded_calls(subject, monkeypatch):
    from merchantcore.enrich import Enricher
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        return response('{}')
    monkeypatch.setattr(httpx, 'post', post)
    spec = ModelSpec('synthetic', 'openai-compatible', 'synthetic-route',
                     base_url='http://synthetic.invalid/v1', api_key_env=None)
    extractor = recorded_model_extractor(subject.ledger, spec)
    Enricher(extractor, chunk_size=1).enrich({'purple harbor kiosk': 'purple harbor kiosk',
                                          'amber lantern market': 'amber lantern market'})
    assert len(sent) == len(calls(subject)) == 2
    assert len({c.body['doc_id'] for c in calls(subject)}) == 2


def test_sql_trust_projection_includes_failed_continuation_and_partial_cost(subject, monkeypatch):
    from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
    sent = []
    def post(url, **kwargs):
        sent.append(kwargs['json'])
        if len(sent) == 1:
            return response(REPLY[:10], 'length', {'prompt_tokens': 9, 'cost': .003})
        raise httpx.ReadTimeout('synthetic transport failure')
    monkeypatch.setattr(httpx, 'post', post)
    with pytest.raises(AdapterError):
        enrich_live_merchants(subject)
    subject.synchronize_read_store()
    read = OpenedVaultSurfaceProvider(subject).read_surface('trust', {})['outbound']
    assert read['call_count'] == 2
    assert read['phases'][0]['id'] == 'merchant_enrich'
    assert read['phases'][0]['count'] == 2
    assert read['cost']['exact_value'] == '0.003'
    assert read['cost']['measured_calls'] == 1
    assert 'tokens' not in read
    assert calls(subject)[0].body['input_tokens'] == 9
    assert 'output_tokens' not in calls(subject)[0].body
    assert read['reported_models'] == [{'name': 'synthetic-reported-model', 'count': 1}]


@pytest.mark.parametrize('keyless', [False, True])
def test_settings_confirmation_does_not_promise_to_stop_an_explicit_route(tmp_path, monkeypatch, keyless):
    from viva import configuration
    from viva.desktop_bridge.settings_actions import SettingsActions
    monkeypatch.setattr(configuration, 'CONFIG_HOME', tmp_path)
    monkeypatch.setattr(configuration, 'SETTINGS_FILE', tmp_path / 'settings.json')
    monkeypatch.setattr(configuration, 'SECRETS_FILE', tmp_path / '.env')
    monkeypatch.setattr(configuration, 'key_store',
                        lambda *a, **kw: configuration.KeyRecord('SYNTHETIC_NO_KEY', True))
    explicit = {configuration.ADAPTER_VAR, configuration.MODEL_VAR, configuration.BASE_URL_VAR}
    monkeypatch.setattr(configuration, '_EXPLICIT_ENVIRONMENT', explicit)
    monkeypatch.setenv(configuration.ADAPTER_VAR, 'openai-compatible')
    monkeypatch.setenv(configuration.MODEL_VAR, 'synthetic-explicit-route-1')
    monkeypatch.setenv(configuration.BASE_URL_VAR, 'http://synthetic.invalid/v1')
    def forbidden(*args, **kwargs):
        raise AssertionError('settings confirmation must not call a provider')
    monkeypatch.setattr(httpx, 'post', forbidden)
    payload = {'kind': 'model', 'adapter': 'openai-compatible' if keyless else '',
               'model': 'synthetic-requested-route-1' if keyless else '',
               'base_url': 'http://synthetic.invalid/v1' if keyless else '',
               'key_action': 'none' if keyless else ''}
    actions = SettingsActions()
    proposal = actions.propose(payload)
    result = actions.confirm({**payload, 'digest': proposal['state']['digest']})
    assert result['kind'] == 'completed'
    assert result['state']['can_send'] is True
    assert result['state']['model'] == 'synthetic-explicit-route-1'
    assert 'stops future requests' not in result['message']
    assert 'cannot undo information already sent' in result['message']


def test_keyless_confirmation_does_not_promise_automatic_merchant_model_support():
    from viva.persona import moment
    sentence = moment('settings_model_keyless_confirmed')
    assert 'merchant learning' not in sentence
    assert 'saved without a key' in sentence
