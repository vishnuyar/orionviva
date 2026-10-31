"""Stage-owned healing reuse never borrows caller-mutated read state."""
from decimal import Decimal
import pytest

from viva.investment import healing
from viva.investment.lifecycle import SourceIndex
from viva.ledger import Ledger
from viva.ledger.events import account_opened, closing_balance_observed
from viva.ledger.ledger import _StagedLedger
from test_bank_witness_preference import prepared


def test_staged_read_mutation_never_changes_events_or_later_decisions(tmp_path):
    ledger = Ledger.open(tmp_path / 'stage', 'public-test-passphrase')
    ledger.append(account_opened('public', 'depository', 'Public', 'USD', '2026-01-01'))
    ledger.append(closing_balance_observed('public', '100', '2026-01-01'))
    def operation(staged):
        view = staged.projection()
        view.core._acct['public'].closing = Decimal('999')
        view._source_events[0].body['name'] = 'Poisoned'
        assert next(staged.events()).body['name'] == 'Public'
        def decide(projection):
            assert projection.balance('public').amount == Decimal('100')
            assert projection._source_events[0].body['name'] == 'Public'
            return [closing_balance_observed('public', '120', '2026-01-02')]
        staged.append_atomically(decide)
        assert staged.projection().balance('public').amount == Decimal('120')
    ledger.stage_atomically(operation)
    assert ledger.projection().balance('public').amount == Decimal('120')


def test_unchanged_roots_share_one_private_plan_and_skip_nested_decisions(tmp_path, monkeypatch):
    ledger, _, _, _ = prepared(tmp_path)
    events = tuple(ledger.events())
    root = healing.source_index(events, healing.resolver(events)).select('activity', '9999-12-31')[0].root
    counts = {'index': 0, 'nested': 0}
    source_index = SourceIndex._initialize
    nested = _StagedLedger.append_atomically
    def indexed(*args, **kwargs):
        counts['index'] += 1
        return source_index(*args, **kwargs)
    def decided(self, *args, **kwargs):
        counts['nested'] += 1
        return nested(self, *args, **kwargs)
    monkeypatch.setattr(SourceIndex, '_initialize', indexed)
    monkeypatch.setattr(_StagedLedger, 'append_atomically', decided)
    def operation(staged):
        before = len(staged)
        assert not healing.heal_root(staged, root)
        assert not healing.heal_root(staged, root)
        assert not healing.heal_root(staged, 'absent-root')
        assert len(staged) == before
        assert counts == {'index': 1, 'nested': 0}
    ledger.stage_atomically(operation)


def test_planning_generation_rejects_view_poison_and_every_intervening_addition(tmp_path, monkeypatch):
    from viva.ledger.ledger import _stage_capability
    ledger, _, _, _ = prepared(tmp_path)
    events = tuple(ledger.events())
    root = healing.source_index(events, healing.resolver(events)).select('activity', '9999-12-31')[0].root
    original = SourceIndex._initialize
    calls = []
    def indexed(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(SourceIndex, '_initialize', indexed)
    retained = []
    def operation(staged):
        retained.append(staged)
        stamp = _stage_capability(staged)
        assert stamp is not None
        assert not healing.heal_root(staged, root)
        view = staged.projection()
        view._source_events[0].body['caller_poison'] = True
        assert not healing.heal_root(staged, root)
        assert len(calls) == 1
        assert not any('caller_poison' in event.body for event in staged.events())
        staged.append(account_opened('other', 'depository', 'Other public', 'USD', '2026-01-01'))
        assert _stage_capability(staged) != stamp
        assert staged not in healing._planning
        assert not healing.heal_root(staged, root)
        assert len(calls) == 2
        def mutate(projection):
            projection._source_events[0].body['callback_poison'] = True
            return ()
        staged.append_atomically(mutate)
        assert not healing.heal_root(staged, root)
        assert len(calls) == 2
        assert not any('callback_poison' in event.body for event in staged.events())
    ledger.stage_atomically(operation)
    assert _stage_capability(retained[0]) is None
    assert retained[0] not in healing._planning


def test_capability_requires_real_operation_owner_thread_and_exact_stage(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from copy import copy
    from viva.ledger.ledger import _stage_capability
    ledger = Ledger.open(tmp_path / 'capability', 'public-test-passphrase')
    forged = _StagedLedger(ledger.projection(), None)
    assert _stage_capability(forged) is None
    retained = []
    def operation(staged):
        retained.append(staged)
        assert _stage_capability(staged) is not None
        with pytest.raises(TypeError, match="cannot be copied"):
            copy(staged)
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(_stage_capability, staged).result() is None
            future = pool.submit(staged.events)
            with pytest.raises(RuntimeError, match='owning thread'):
                future.result()
    ledger.stage_atomically(operation)
    assert _stage_capability(retained[0]) is None


def test_failure_and_throwing_cleanup_revoke_all_planning_state(tmp_path):
    import pytest
    from viva.ledger.ledger import _stage_capability, _stage_on_invalidation
    ledger, _, _, _ = prepared(tmp_path)
    retained = []
    before = len(ledger)
    def operation(staged):
        retained.append(staged)
        assert not healing.heal_root(staged, 'absent')
        assert staged in healing._planning
        def broken_cleanup():
            raise RuntimeError('public injected cleanup fault')
        assert _stage_on_invalidation(staged, broken_cleanup)
        invalid = closing_balance_observed('missing', '1', '2026-01-01')
        invalid.body['amount'] = 'invalid-decimal'
        with pytest.raises(Exception):
            staged.append(invalid)
        assert _stage_capability(staged) is None
        assert staged not in healing._planning
    with pytest.raises(RuntimeError, match='failed'):
        ledger.stage_atomically(operation)
    assert len(ledger) == before
    assert _stage_capability(retained[0]) is None
    assert retained[0] not in healing._planning
    # A cleanup exception also cannot turn a successful canonical closure into failure.
    ledger.stage_atomically(lambda staged: _stage_on_invalidation(staged, lambda: 1 / 0))


def test_public_calls_keep_fresh_per_root_decisions_and_notice_other_writer(tmp_path, monkeypatch):
    ledger, _, _, _ = prepared(tmp_path)
    other = ledger.fork()
    captured = []
    actual = healing.source_index
    def indexed(events, *args):
        captured.append(tuple(event.event_id for event in events))
        return actual(events, *args)
    monkeypatch.setattr(healing, 'source_index', indexed)
    assert not healing.heal_root(ledger, 'absent')
    addition = account_opened('external', 'depository', 'External public', 'USD', '2026-01-01')
    other.append(addition)
    assert not healing.heal_root(ledger, 'absent')
    assert len(captured) == 2
    assert addition.event_id not in captured[0]
    assert addition.event_id in captured[1]


def test_shared_preview_preserves_root_errors_and_copy_error_refusal(tmp_path, monkeypatch):
    import pytest
    from viva.investment.contracts import EvidenceError
    ledger = Ledger.open(tmp_path / 'errors', 'public-test-passphrase')
    def invalid(*args):
        raise EvidenceError('public invalid evidence')
    monkeypatch.setattr(SourceIndex, '_initialize', invalid)
    with pytest.raises(EvidenceError, match='public invalid evidence'):
        healing.heal_root(ledger, 'absent')
    assert not healing.heal_copy_root(ledger, 'absent')
    def operation(staged):
        with pytest.raises(EvidenceError, match='public invalid evidence'):
            healing.heal_root(staged, 'absent')
        assert not healing.heal_copy_root(staged, 'absent')
    ledger.stage_atomically(operation)


def test_actual_healing_change_stays_strict_and_matches_public_result(tmp_path, monkeypatch):
    from test_source_projector import contribution_facts
    from viva.ingest.brokerage_projector import post_brokerage
    from viva.ingest.instrument_contracts import Source
    from viva.investment.contracts import encode
    from viva.ledger.events import Provenance
    from viva.ledger.instruments import reference_event
    from viva.ledger.postings import simple_transaction
    initial = Ledger.open(tmp_path / 'initial', 'public-test-passphrase')
    post_brokerage(initial, contribution_facts())
    initial.append(account_opened('Assets:BankTest', 'depository', 'Test bank', 'USD', '2025-01-01'))
    initial.append(reference_event('Assets:BankTest', 'BANK-REF', '2025-01-01', Source('bank-source', 1)))
    initial.append(simple_transaction('Assets:BankTest', '-100.00', 'Bank funding', '2025-01-25',
        provenance=Provenance(doc_id='bank-source', page=1), source_reference='PRINTED-X',
        counterparty_reference='BROKER-REF'))
    staged_ledger = Ledger.open(tmp_path / 'staged', 'public-test-passphrase')
    staged_ledger.append_many(tuple(initial.events()))
    assert healing.heal_after_source(initial, 'bank-source') == 1
    strict = healing.append_from_source
    strict_calls = []
    def recorded(*args, **kwargs):
        strict_calls.append(1)
        return strict(*args, **kwargs)
    monkeypatch.setattr(healing, 'append_from_source', recorded)
    assert staged_ledger.stage_atomically(lambda staged: healing.heal_after_source(staged, 'bank-source')) == 1
    assert strict_calls
    from viva.investment.events import committed_statements
    def selected(ledger):
        events = tuple(ledger.events())
        return encode(committed_statements(events, healing.resolver(events)))
    assert selected(staged_ledger) == selected(initial)
    assert staged_ledger.stage_atomically(lambda staged: healing.heal_after_source(staged, 'bank-source')) == 0


def test_copy_arrival_and_successor_healing_keep_existing_financial_outcomes(tmp_path, monkeypatch):
    from test_source_projector import test_copy_before_bank_arrival_heals_after_parent_first_without_reposting
    original_root = healing.heal_root
    original_after = healing.heal_after_source
    def root(ledger, selected):
        if isinstance(ledger, Ledger):
            return ledger.stage_atomically(lambda staged: original_root(staged, selected))
        return original_root(ledger, selected)
    def after(ledger, document):
        if isinstance(ledger, Ledger):
            return ledger.stage_atomically(lambda staged: original_after(staged, document))
        return original_after(ledger, document)
    monkeypatch.setattr(healing, 'heal_root', root)
    monkeypatch.setattr(healing, 'heal_after_source', after)
    test_copy_before_bank_arrival_heals_after_parent_first_without_reposting(tmp_path)


def test_retraction_inside_stage_invalidates_prior_noop_and_matches_fresh(tmp_path):
    from viva.investment.events import retract_source, committed_statements
    from viva.investment.lifecycle import SourceChange
    ledger, statement, _, _ = prepared(tmp_path)
    initial = tuple(ledger.events())
    selected = healing.source_index(initial, healing.resolver(initial)).select('activity', '9999-12-31')[0]
    other = Ledger.open(tmp_path / 'retracted', 'public-test-passphrase')
    other.append_many(initial)
    change = SourceChange('staged-retraction', 'activity', statement.observation_id,
                          statement.account.document, statement.end.value, 'source_retraction')
    retract_source(ledger, change, healing.resolver(initial))
    assert not healing.heal_root(ledger, selected.root)
    def operation(staged):
        assert not healing.heal_root(staged, selected.root)
        assert staged in healing._planning
        retract_source(staged, change, healing.resolver(tuple(staged.events())))
        assert staged not in healing._planning
        assert not healing.heal_root(staged, selected.root)
    other.stage_atomically(operation)
    assert committed_statements(tuple(ledger.events()), healing.resolver(tuple(ledger.events()))) == ()
    assert committed_statements(tuple(other.events()), healing.resolver(tuple(other.events()))) == ()


def test_later_funding_ambiguity_cannot_reuse_an_earlier_noop(tmp_path):
    from dataclasses import replace
    ledger, _, row, _ = prepared(tmp_path)
    initial = tuple(ledger.events())
    root = healing.source_index(initial, healing.resolver(initial)).select('activity', '9999-12-31')[0].root
    cash = next(event for event in initial if event.event_id == row.funding_witness.transaction_id)
    public = Ledger.open(tmp_path / 'public-ambiguity', 'public-test-passphrase')
    public.append_many(initial)
    public.append(replace(cash, event_id='new-matching-cash'))
    assert not healing.heal_root(public, root)
    expected_events = tuple(public.events())
    expected = healing.source_index(expected_events, healing.resolver(expected_events)).project(
        'activity', '9999-12-31', healing.resolver(expected_events))
    def operation(staged):
        assert not healing.heal_root(staged, root)
        staged.append(replace(cash, event_id='new-matching-cash'))
        assert staged not in healing._planning
        assert not healing.heal_root(staged, root)
        events = tuple(staged.events())
        index = healing.source_index(events, healing.resolver(events))
        current = index.project('activity', '9999-12-31', healing.resolver(events))
        assert current == expected
    ledger.stage_atomically(operation)


def test_copy_cannot_partially_mutate_real_stage_before_a_failed_fold(tmp_path):
    from copy import copy
    from decimal import InvalidOperation
    import pytest
    ledger = Ledger.open(tmp_path / 'copied-stage', 'public-test-passphrase')
    ledger.append(account_opened('public', 'depository', 'Public', 'USD', '2026-01-01'))
    ledger.append(closing_balance_observed('public', '100', '2026-01-01'))
    def operation(staged):
        try:
            forged = copy(staged)
        except TypeError:
            forged = None
        if forged is not None:
            invalid = closing_balance_observed('public', '130', '2026-01-03')
            invalid.body['amount'] = 'invalid-decimal'
            with pytest.raises((RuntimeError, InvalidOperation)):
                forged.append_many([closing_balance_observed('public', '120', '2026-01-02'), invalid])
        # No successful first event may leak out of the copied handle's failure.
        assert staged.projection().balance('public').amount == Decimal('100')
        assert len(staged) == 2
        def decide(projection):
            assert projection.balance('public').amount == Decimal('100')
            return [closing_balance_observed('public', '140', '2026-01-04')]
        staged.append_atomically(decide)
    ledger.stage_atomically(operation)
    assert ledger.projection().balance('public').amount == Decimal('140')
    assert len(ledger) == 3


@pytest.mark.parametrize("route", ["shallow", "deep"])
def test_stage_copy_routes_reject_without_lending_state_or_authority(tmp_path, route):
    from copy import copy, deepcopy
    from viva.ledger.ledger import _stage_capability
    ledger = Ledger.open(tmp_path / route, 'public-test-passphrase')
    retained = []
    def operation(staged):
        retained.append(staged)
        copier = copy if route == 'shallow' else deepcopy
        with pytest.raises(TypeError, match='cannot be copied'):
            copier(staged)
        forged = _StagedLedger(staged.projection(), None)
        assert _stage_capability(forged) is None
        for action in (forged.projection, forged.events, lambda: len(forged),
                       lambda: forged.append(account_opened('forged', 'depository', 'Forged', 'USD', '2026-01-01')),
                       lambda: forged.append_many(()), lambda: forged.append_atomically(lambda _: ())):
            with pytest.raises(RuntimeError, match='closed'):
                action()
        staged.append(account_opened('public', 'depository', 'Public', 'USD', '2026-01-01'))
        borrowed = []
        def decide(projection):
            borrowed.append(projection)
            return [closing_balance_observed('public', '100', '2026-01-02')]
        staged.append_atomically(decide)
        borrowed[0]._source_events[0].body['name'] = 'Poisoned'
        assert next(staged.events()).body['name'] == 'Public'
        assert len(staged) == 2
    ledger.stage_atomically(operation)
    assert ledger.projection().balance('public').amount == Decimal('100')
    with pytest.raises(RuntimeError, match='closed'):
        retained[0].projection()
