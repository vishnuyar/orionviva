"""Sample readiness compares incremental financial state to cold authenticated replay."""
from decimal import Decimal

import pytest

from viva.ledger import Ledger
from viva.ledger.events import account_opened, closing_balance_observed
from viva.sample.instances import SampleBuildError, verify_replay_agreement


def ledger_fixture(tmp_path):
    ledger = Ledger.open(tmp_path/'events.jsonl', 'synthetic-replay-test-passphrase')
    ledger.append(account_opened('synthetic', 'depository', 'Synthetic', 'USD', '2025-01-01'))
    ledger.append(closing_balance_observed('synthetic', '10', '2025-01-01'))
    ledger.append(closing_balance_observed('synthetic', '12', '2025-02-01'))
    return ledger


def test_agreement_uses_cold_authenticated_events_and_reports_no_values(tmp_path, monkeypatch):
    from viva.ledger import store
    ledger = ledger_fixture(tmp_path)
    decryptions = []
    original = store.open_sealed
    def decrypt(*args, **kwargs):
        decryptions.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(store, 'open_sealed', decrypt)
    result = verify_replay_agreement(ledger)
    assert result['state'] == 'equal'
    assert result['event_identity'] == list(ledger.store.authenticated_identity())
    assert len(decryptions) == 3
    assert result['family_count'] == len(result['families'])
    assert {'balances', 'movements', 'positions', 'core_acct',
            'core_instrument_effect_records', 'core_instrument_effect_keys',
            'core_instrument_observations', 'measurement_source_accepted'} <= set(result['families'])
    assert set(result) == {'state', 'families', 'family_count', 'event_identity', 'seconds'}


def test_agreement_rejects_changed_incremental_financial_fold(tmp_path):
    ledger = ledger_fixture(tmp_path)
    ledger.projection().core._acct['synthetic'].balance += Decimal('1')
    with pytest.raises(SampleBuildError, match='replay disagrees'):
        verify_replay_agreement(ledger)


def test_ephemeral_query_caches_are_not_financial_comparison_state(tmp_path):
    ledger = ledger_fixture(tmp_path)
    ledger.projection().core._mkeys_of['synthetic-cache-entry'] = object()
    assert verify_replay_agreement(ledger)['state'] == 'equal'


def test_callable_cannot_hide_a_canonical_financial_state_family(tmp_path):
    ledger = ledger_fixture(tmp_path)
    ledger.projection().core._classification_responses = lambda:None
    with pytest.raises(SampleBuildError, match='replay disagrees: core_classification_responses'):
        verify_replay_agreement(ledger)


@pytest.mark.parametrize('family', ['_instrument_account_refs',
                                    '_instrument_bank_references',
                                    '_instrument_cash_dependencies'])
def test_event_folded_dependency_indexes_cannot_escape_replay_comparison(tmp_path, family):
    ledger = ledger_fixture(tmp_path)
    getattr(ledger.projection().core, family)['synthetic-poison'] = {'synthetic-dependency'}
    with pytest.raises(SampleBuildError, match='replay disagrees: core'+family):
        verify_replay_agreement(ledger)
