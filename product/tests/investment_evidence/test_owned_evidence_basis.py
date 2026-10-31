"""Private history reuse preserves validation and detaches all external values."""
from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from dataclasses import replace

import pytest

from test_owned_funding_runner import prepared
from viva.investment import events as observations, lifecycle, payroll, prefix_proofs
from viva.investment.contracts import encode
from viva.investment.funding import resolver


def test_internal_runner_encodes_each_owned_event_once_across_all_validators(tmp_path, monkeypatch):
    _, events, resolve, statement, row = prepared(tmp_path)
    calls = []
    original = prefix_proofs._encode_event
    def counted(event):
        calls.append(event.event_id)
        return original(event)
    monkeypatch.setattr(prefix_proofs, '_encode_event', counted)
    runner = payroll._OwnedFundingRunner(events, resolve)
    fields = {'printed_reference': row.funding_reference,
              'counterpart_reference': row.counterpart_reference,
              'date': row.date, 'amount': row.amount,
              'funding_role': row.funding_role_source}
    for _ in range(2):
        assert runner.bind_funding(fields, destination_account=statement.account.value,
            destination_reference=replace(statement.account, value=statement.account.raw),
            currency=statement.currency.value)['funding_witness'] == row.funding_witness
        assert runner.validate_funding(statement, row, resolve) is None
    assert calls == [event.event_id for event in events]
    for _ in range(2):
        assert runner._healing_plan('absent-root') is None
    assert calls == [event.event_id for event in events]


def outcome(operation):
    try:
        return ('value', encode(operation()))
    except Exception as error:
        return ('error', type(error), str(error))


@pytest.mark.parametrize('mutation', ['none', 'body', 'order', 'prefix', 'schema', 'row', 'duplicate'])
def test_private_and_copied_paths_preserve_results_and_exceptions(tmp_path, mutation):
    _, events, resolve, _, _ = prepared(tmp_path)
    source = list(deepcopy(events))
    statement = next(event for event in source if event.event_type == observations.STATEMENT)
    if mutation == 'body':source[0].body['name'] = 'changed body with same identity'
    elif mutation == 'order':source[:2] = source[1::-1]
    elif mutation == 'prefix':statement.body['prefix']['prefix_digest'] = '0' * 64
    elif mutation == 'schema':statement.body['schema_version'] = 'future-unknown'
    elif mutation == 'row':statement.body['row_event_ids'] = []
    elif mutation == 'duplicate':source.append(source[-1])
    owned = prefix_proofs._OwnedEvidence(source)
    assert outcome(lambda: owned._statements(resolve)) == outcome(lambda: observations._validated_statements(source, resolve))
    assert outcome(lambda: owned._records('9999-12-31')) == outcome(lambda: payroll._records(source))
    def copied_index():
        return lifecycle.SourceIndex(source, observations._validated_statements(source, resolve)).project('activity', '9999-12-31', resolve)
    def owned_index():
        return owned._source_index(owned._statements(resolve)).project('activity', '9999-12-31', resolve)
    assert outcome(owned_index) == outcome(copied_index)


def test_input_public_maps_and_returned_proposals_cannot_change_private_basis(tmp_path):
    _, source, resolve, statement, row = prepared(tmp_path)
    owned = prefix_proofs._OwnedEvidence(source)
    runner = payroll._OwnedFundingRunner._from_owned(owned, resolve)
    public = observations.source_index(source, resolve)
    expected = owned.proof(len(source))
    source[0].body['name'] = 'source poisoned'
    public.events[0].body['name'] = 'returned events poisoned'
    public.statements.clear();public.heads.clear();public.root_for.clear()
    returned = owned.events
    returned[0].body['name'] = 'returned owner snapshot poisoned'
    assert owned.proof(len(source)) == expected
    assert runner.validate_funding(statement, row, resolve) is None
    assert not any(hasattr(runner, name) for name in ('events', 'records', 'source_index', 'destinations'))


def test_owner_forgery_foreign_handles_and_copies_are_refused(tmp_path):
    _, events, resolve, _, _ = prepared(tmp_path)
    genuine = prefix_proofs._OwnedEvidence(events)
    class Foreign:
        def _configure_runner(self, *args):
            pytest.fail('foreign ownership must be rejected before invoking its methods')
    for foreign in (Foreign(), prefix_proofs.PrefixProofIndex(events), object.__new__(prefix_proofs._OwnedEvidence)):
        with pytest.raises(TypeError, match='genuine private evidence'):
            payroll._OwnedFundingRunner._from_owned(foreign, resolve)
    for duplicate in (copy, deepcopy):
        with pytest.raises(TypeError, match='cannot be copied'):
            duplicate(genuine)
    class Receiver:
        def _initialize(self, *args):
            pytest.fail('no arbitrary initializer may receive private history')
    with pytest.raises(TypeError, match='private funding runner'):
        genuine._configure_runner(Receiver(), resolve)
    with pytest.raises(TypeError, match='private healing runner'):
        genuine._plan_healing(Receiver(), 'absent')
    foreign_runner = payroll._OwnedFundingRunner(events, resolve)
    with pytest.raises(TypeError, match='private healing runner'):
        genuine._plan_healing(foreign_runner, 'absent')


def test_retained_mutating_resolver_fields_are_detached_from_owned_state(tmp_path):
    from test_bank_witness_preference import prepared as bank_prepared
    ledger, statement, row, _ = bank_prepared(tmp_path)
    source = tuple(ledger.events())
    retained = []
    def malicious(field):
        original = resolver(source)(field)
        retained.append(field)
        object.__setattr__(field, 'value', 'mutated during callback')
        return original
    runner = payroll._OwnedFundingRunner(source, malicious)
    for _ in range(2):
        assert runner.validate_funding(statement, row, malicious) is None
    for field in retained:object.__setattr__(field, 'raw', 'mutated after callback')
    assert runner.validate_funding(statement, row, resolver(source)) is None
    assert statement.rows[0].counterpart_reference.value != 'mutated during callback'


def test_independent_concurrent_owners_do_not_share_mutable_results(tmp_path):
    _, events, resolve, statement, row = prepared(tmp_path)
    def validate(poison):
        source = deepcopy(events)
        runner = payroll._OwnedFundingRunner(source, resolve)
        if poison:source[0].body['name'] = 'other context changed'
        return runner.validate_funding(statement, row, resolve)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(validate, (False, True))) == [None, None]


def test_stage_addition_and_closure_release_private_owners_without_collection(tmp_path):
    from weakref import ref
    from viva.investment import healing
    from viva.ledger.events import account_opened
    ledger, _, _, _, _ = prepared(tmp_path)
    previous = {id(owner) for owner in prefix_proofs._issued_evidence}
    retained = []
    def current_owners():
        return [ref(owner) for owner in prefix_proofs._issued_evidence if id(owner) not in previous]
    def operation(staged):
        assert not healing.heal_root(staged, 'absent-root')
        first = current_owners()
        assert first and all(owner() is not None for owner in first)
        staged.append(account_opened('new-synthetic', 'depository', 'New synthetic', 'USD', '2021-01-01'))
        assert all(owner() is None for owner in first)
        assert not healing.heal_root(staged, 'absent-root')
        retained.extend(current_owners())
        assert retained and all(owner() is not None for owner in retained)
    ledger.stage_atomically(operation)
    assert all(owner() is None for owner in retained)
