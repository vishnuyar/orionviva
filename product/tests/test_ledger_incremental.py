"""Owned incremental folds retain full canonical authentication and isolation."""
from decimal import Decimal

import pytest

from viva.ledger import EventStore, Ledger
from viva.ledger.events import account_opened, closing_balance_observed
from viva.ledger.ledger import _owned_projection_identity
from viva.ledger.projection import LedgerProjection


def _ledger(tmp_path):
    ledger = Ledger(EventStore.open(tmp_path / "events", "public-test-passphrase"))
    ledger.append(account_opened("public", "depository", "Public", "USD", "2026-01-01"))
    ledger.append(closing_balance_observed("public", "100", "2026-01-01"))
    return ledger


def test_warm_append_never_reconstructs_the_owned_prefix(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    ledger.projection()
    def no_replay(*args, **kwargs):
        raise AssertionError("warm append reconstructed the complete projection")
    monkeypatch.setattr(LedgerProjection, "__init__", no_replay)
    for day in range(2, 8):
        ledger.append(closing_balance_observed("public", str(100 + day), f"2026-01-{day:02}"))
        assert ledger.projection().balance("public").amount == Decimal(100 + day)


def test_warm_snapshot_decrypts_only_new_records_and_detaches_inputs(tmp_path, monkeypatch):
    import viva.ledger.store as store_module
    ledger = _ledger(tmp_path)
    before = ledger.store.snapshot_events()
    sealed = store_module.open_sealed
    decryptions = []
    def counted(*args, **kwargs):
        decryptions.append(1)
        return sealed(*args, **kwargs)
    monkeypatch.setattr(store_module, "open_sealed", counted)
    # Header validation decrypts its separate check token in crypto, not here.
    ledger.store.snapshot_events()
    assert decryptions == []
    before[-1].body["amount"] = "900"
    assert ledger.store.snapshot_events()[-1].body["amount"] == "100"
    retained = []
    def decide(events):
        retained.extend(events)
        events[-1].body["amount"] = "800"
        return (closing_balance_observed("public", "120", "2026-01-02"),)
    ledger.store.append_atomically(decide)
    retained[-1].body["amount"] = "700"
    events = ledger.store.snapshot_events()
    assert [event.body["amount"] for event in events[1:]] == ["100", "120"]
    assert len(decryptions) == 1


def test_retained_projection_preserves_its_view_after_owned_transfer(tmp_path):
    ledger = _ledger(tmp_path)
    old = ledger.projection()
    ledger.append(closing_balance_observed("public", "120", "2026-01-02"))
    current = ledger.projection()
    assert current is not old
    assert _owned_projection_identity(old) is None
    assert old.balance("public").amount == Decimal("100")
    old._source_events[-1].body["amount"] = "900"
    assert current.balance("public").amount == Decimal("120")
    assert _owned_projection_identity(current) is not None


def test_retained_core_mutation_cannot_change_successor_fold(tmp_path):
    ledger = _ledger(tmp_path)
    old = ledger.projection()
    old_core = old.core
    ledger.append(closing_balance_observed("public", "120", "2026-01-02"))
    current = ledger.projection()
    old_core.apply(closing_balance_observed("public", "900", "2026-01-03"))
    assert _owned_projection_identity(current) is not None
    repaired = ledger.projection()
    assert repaired.balance("public").amount == Decimal("120")
    assert _owned_projection_identity(repaired) is not None
    assert old.balance("public").amount == Decimal("900")


def test_failed_incremental_fold_revokes_then_recovers_committed_event(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    old = ledger.projection()
    def fail(*args):
        assert _owned_projection_identity(old) is None
        raise RuntimeError("public fold fault")
    with monkeypatch.context() as patch:
        patch.setattr(LedgerProjection, "apply", fail)
        with pytest.raises(RuntimeError, match="public fold fault"):
            ledger.append(closing_balance_observed("public", "120", "2026-01-02"))
    assert _owned_projection_identity(old) is None
    assert ledger.projection().balance("public").amount == Decimal("120")
    assert ledger.fresh_projection().balance("public").amount == Decimal("120")


def test_staged_financial_settlement_commits_one_batch_and_returns_result(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    before = len(ledger)
    calls = []
    append = ledger.store.append_atomically
    def counted(decide):
        calls.append(1)
        return append(decide)
    monkeypatch.setattr(ledger.store, "append_atomically", counted)
    retained = []
    output = closing_balance_observed("public", "130", "2026-01-03")
    def settle(staged):
        assert not hasattr(staged, "store")
        retained.append(staged)
        prior = staged.projection()
        staged.append(closing_balance_observed("public", "120", "2026-01-02"))
        assert prior.balance("public").amount == Decimal("100")
        assert staged.projection().balance("public").amount == Decimal("120")
        def nested(projection):
            retained.append(projection)
            projection._source_events[-1].body["amount"] = "900"
            return [output]
        staged.append_atomically(nested)
        assert staged.projection().balance("public").amount == Decimal("130")
        assert len(tuple(staged.events())) == before + 2
        return {"action": "posted", "amount": staged.projection().balance("public").amount}
    assert ledger.stage_atomically(settle) == {"action": "posted", "amount": Decimal("130")}
    assert calls == [1]
    assert len(ledger) == before + 2
    output.body["amount"] = "900"
    retained[1].apply(closing_balance_observed("public", "800", "2026-01-04"))
    assert ledger.projection().balance("public").amount == Decimal("130")
    assert ledger.fresh_projection().balance("public").amount == Decimal("130")
    with pytest.raises(RuntimeError, match="closed"):
        retained[0].append(output)


@pytest.mark.parametrize("failure", ["operation", "fold", "caught_fold"])
def test_staged_financial_failure_never_commits_partial_work(tmp_path, failure):
    ledger = _ledger(tmp_path)
    before = ledger.store.path.read_bytes()
    def settle(staged):
        staged.append(closing_balance_observed("public", "120", "2026-01-02"))
        if failure == "operation":
            raise ValueError("public settlement fault")
        invalid = closing_balance_observed("public", "130", "2026-01-03")
        invalid.body["amount"] = "invalid-decimal"
        if failure == "caught_fold":
            try:
                staged.append(invalid)
            except Exception:
                pass
        else:
            staged.append(invalid)
    with pytest.raises(Exception):
        ledger.stage_atomically(settle)
    assert ledger.store.path.read_bytes() == before
    assert ledger.projection().balance("public").amount == Decimal("100")


def test_staged_settlement_sees_external_writer_before_deciding(tmp_path):
    ledger = _ledger(tmp_path)
    other = ledger.fork()
    other.append(closing_balance_observed("public", "120", "2026-01-02"))
    def settle(staged):
        assert staged.projection().balance("public").amount == Decimal("120")
        staged.append(closing_balance_observed("public", "130", "2026-01-03"))
    ledger.stage_atomically(settle)
    from viva.ledger.projection import LedgerProjection
    reopened = Ledger(EventStore.open(ledger.store.path, "public-test-passphrase"))
    assert reopened.projection().balance("public") == ledger.projection().balance("public")
    assert LedgerProjection(reopened.events()).balance("public").amount == Decimal("130")


@pytest.mark.parametrize("borrow", ["core", "state", "posted", "merchant_tags", "attribute_history"])
def test_retained_mutable_read_state_never_aliases_successor(tmp_path, borrow):
    ledger = _ledger(tmp_path)
    old = ledger.projection()
    if borrow == "core":
        retained = old.core
    elif borrow == "state":
        retained = old._state("public")
    else:
        retained = getattr(old, "_" + borrow)
    ledger.append(closing_balance_observed("public", "120", "2026-01-02"))
    current = ledger.projection()
    if borrow == "core":
        retained._acct["public"].closing = Decimal("999")
    elif borrow == "state":
        retained.closing = Decimal("999")
    elif borrow == "posted":
        retained.add("forged-document")
    elif borrow == "merchant_tags":
        retained["forged"] = ["private"]
    else:
        retained.append({"forged": True})
    assert current.balance("public").amount == Decimal("120")
    assert "forged-document" not in current._posted
    assert "forged" not in current._merchant_tags
    assert {"forged": True} not in current._attribute_history
    assert _owned_projection_identity(current) is not None
    assert ledger.fresh_projection().balance("public") == current.balance("public")


def test_staged_unexposed_fold_updates_without_repeated_state_copies(tmp_path, monkeypatch):
    import viva.ledger.ledger as owner_module
    ledger = _ledger(tmp_path)
    actual_copy = owner_module.deepcopy
    state_copies = []
    def counted(value):
        if isinstance(value, LedgerProjection):
            state_copies.append(1)
        return actual_copy(value)
    monkeypatch.setattr(owner_module, "deepcopy", counted)
    def settle(staged):
        state_copies.clear()
        for day in range(2, 8):
            staged.append(closing_balance_observed("public", str(100 + day), f"2026-01-{day:02}"))
        assert state_copies == []
        retained = staged.projection()
        retained_state = retained._state("public")
        staged.append(closing_balance_observed("public", "120", "2026-01-08"))
        assert len(state_copies) == 1
        retained_state.closing = Decimal("999")
        assert staged.projection().balance("public").amount == Decimal("120")
    ledger.stage_atomically(settle)
    assert ledger.projection().balance("public").amount == Decimal("120")


def test_staged_event_snapshot_does_not_expose_the_live_fold(tmp_path):
    ledger = _ledger(tmp_path)
    retained = []
    def settle(staged):
        events = tuple(staged.events())
        events[-1].body["amount"] = "999"
        staged.append(closing_balance_observed("public", "120", "2026-01-02"))
        def nested(projection):
            retained.append(projection._state("public"))
            return [closing_balance_observed("public", "130", "2026-01-03")]
        staged.append_atomically(nested)
        retained[-1].closing = Decimal("999")
        assert staged.projection().balance("public").amount == Decimal("130")
    ledger.stage_atomically(settle)
    assert ledger.projection().balance("public").amount == Decimal("130")


@pytest.mark.parametrize("borrow", ["core", "state", "posted", "merchant_tags", "attribute_history"])
def test_mutating_current_public_view_cannot_poison_a_later_canonical_append(tmp_path, borrow):
    ledger = _ledger(tmp_path)
    current = ledger.projection()
    if borrow == "core":
        current.core._acct["public"].closing = Decimal("999")
    elif borrow == "state":
        current._state("public").closing = Decimal("999")
    elif borrow == "posted":
        current._posted.add("forged-document")
    elif borrow == "merchant_tags":
        current._merchant_tags["forged"] = ["private"]
    else:
        current._attribute_history.append({"forged": True})
    ledger.append(account_opened("other", "depository", "Other public", "USD", "2026-01-03"))
    successor = ledger.projection()
    assert successor.balance("public").amount == Decimal("100")
    assert "forged-document" not in successor._posted
    assert "forged" not in successor._merchant_tags
    assert {"forged": True} not in successor._attribute_history
    assert _owned_projection_identity(successor) is not None
    assert successor.balance("public") == ledger.fresh_projection().balance("public")
