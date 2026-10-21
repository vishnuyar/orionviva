"""Ordinary local transport configuration binds measured and runtime endpoints."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from vivacore.models import ModelSpec
from viva import speak


def _spec(**fields):
    return ModelSpec(name='synthetic', adapter='openai-compatible',
                     model='synthetic-model', base_url='http://model.invalid/v1',
                     api_key_env=None, **fields)


@pytest.mark.parametrize('voice,reader,expected', [
    ('/private/tmp/voice.sock', '/private/tmp/reader.sock', '/private/tmp/voice.sock'),
    (None, '/private/tmp/reader.sock', '/private/tmp/reader.sock'),
    (None, None, None),
])
def test_speak_socket_configuration_uses_ordinary_per_field_fallback(monkeypatch, voice, reader, expected):
    for key in ('VIVA_SPEAK_MODEL', 'VIVA_SPEAK_ADAPTER', 'VIVA_MODEL_ADAPTER',
                'VIVA_SPEAK_BASE_URL', 'VIVA_SPEAK_UNIX_SOCKET_PATH', 'VIVA_MODEL_UNIX_SOCKET_PATH'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('VIVA_MODEL', 'synthetic-model')
    monkeypatch.setenv('VIVA_MODEL_BASE_URL', 'http://model.invalid/v1')
    monkeypatch.setenv('VIVA_MODEL_KEY_ENV', 'none')
    if voice:
        monkeypatch.setenv('VIVA_SPEAK_UNIX_SOCKET_PATH', voice)
    if reader:
        monkeypatch.setenv('VIVA_MODEL_UNIX_SOCKET_PATH', reader)
    assert speak.speak_spec().unix_socket_path == expected


@pytest.mark.parametrize('socket', [None, '/private/tmp/gateway.sock'])
def test_factory_measurement_uses_the_same_versioned_identity(socket, monkeypatch):
    monkeypatch.delenv('VIVA_SPEAK_PROTOCOL', raising=False)
    spec = _spec(unix_socket_path=socket)
    factory = speak.compiler_factory(spec, purpose='admission')
    assert factory.admission_identity['endpoint'] == spec.endpoint_identity()
    assert socket is None or socket not in factory.admission_identity['endpoint']


@pytest.mark.parametrize('change', [
    {'unix_socket_path': '/private/tmp/other.sock'},
    {'unix_socket_path': None},
    {'base_url': 'http://other.invalid/v1'},
    {'base_url': 'http://model.invalid/v1/'},
    {'adapter': 'synthetic-other', 'unix_socket_path': None},
])
def test_runtime_rejects_endpoint_changes_before_any_provider_request(monkeypatch, change):
    from viva import answer_program
    spec = _spec(unix_socket_path='/private/tmp/gateway.sock')
    monkeypatch.delenv('VIVA_SPEAK_PROTOCOL', raising=False)
    requests = []
    monkeypatch.setattr('vivacore.models.adapter_for', lambda spec: SimpleNamespace(
        converse=lambda *args: requests.append(args)))
    monkeypatch.setattr(answer_program, 'admission_report_digest', lambda report: 'synthetic-report')
    monkeypatch.setattr(answer_program, 'validate_admission_report', lambda *args: ())
    profile = SimpleNamespace(admission_report_digest='synthetic-report',
        provider=spec.adapter, requested_model=spec.model, endpoint=spec.endpoint_identity(),
        modality='native-structured', locale_family='en')
    measured = speak.compiler_factory(spec, purpose='admission')
    runtime = speak.compiler_factory(spec, profile=profile, report={}, locale='en-US')
    assert runtime.admission_identity == measured.admission_identity
    changed = replace(spec, **change)
    # Match provider when exercising adapter identity, isolating the endpoint comparison.
    profile.provider = changed.adapter
    with pytest.raises(ValueError, match='differs from admitted endpoint'):
        speak.compiler_factory(changed, profile=profile, report={})
    assert not requests
