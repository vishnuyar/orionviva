"""Scoped observation must preserve extraction behavior and unwind reliably."""

import pytest

from vivacore.models.base import Turn, observe_extractions, run_to_completion
from vivacore.errors import ConfigError


def test_observer_sees_every_continuation_without_changing_result():
    seen = []
    def call(accumulated, attempt):
        assert accumulated == ('' if attempt == 0 else 'first')
        return Turn('first' if attempt == 0 else 'last',
                    'length' if attempt == 0 else 'stop', cost_usd=.01)
    with observe_extractions(lambda *args: seen.append(args)):
        result = run_to_completion(call)
    assert result.text == 'firstlast' and result.cost_usd == .02
    assert [(turn.text, error, attempt) for turn, error, attempt in seen] == [
        ('first', None, 0), ('last', None, 1)]


def test_failed_attempt_is_observed_and_original_exception_is_raised():
    seen = []
    error = RuntimeError('synthetic failure')
    def fail(*args):
        raise error
    with observe_extractions(lambda *args: seen.append(args)):
        with pytest.raises(RuntimeError) as caught:
            run_to_completion(fail)
    assert caught.value is error
    assert seen == [(None, error, 0)]


def test_configuration_failure_inside_driver_is_not_a_transport_attempt():
    seen = []
    def missing_key(*args):
        raise ConfigError('synthetic missing configuration')
    with observe_extractions(lambda *args: seen.append(args)):
        with pytest.raises(ConfigError):
            run_to_completion(missing_key)
    assert seen == []


def test_nested_observers_restore_outer_and_leave_no_global_observer():
    outer, inner = [], []
    call = lambda *args: Turn('complete')
    with observe_extractions(lambda *args: outer.append(args)):
        run_to_completion(call)
        with observe_extractions(lambda *args: inner.append(args)):
            run_to_completion(call)
        run_to_completion(call)
    run_to_completion(call)
    assert len(outer) == 2 and len(inner) == 1


def test_persistence_failure_stops_continuation_without_second_transport_record():
    requests, observations = [], []
    def call(*args):
        requests.append(args)
        return Turn('partial', 'length')
    def record(*args):
        observations.append(args)
        raise OSError('synthetic ledger unavailable')
    with pytest.raises(OSError), observe_extractions(record):
        run_to_completion(call)
    assert len(requests) == len(observations) == 1
    assert observations[0][1] is None
    assert run_to_completion(lambda *args: Turn('complete')).text == 'complete'
