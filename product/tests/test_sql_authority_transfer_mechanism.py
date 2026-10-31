"""Whole-operation transfer counting retains fixed gates and handler semantics."""
import ast
import hashlib
import importlib.util
from pathlib import Path
import sqlite3

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts/validate_sql_authority.py"
_spec = importlib.util.spec_from_file_location("transfer_mechanism_harness", _path)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def test_original_seven_fixture_and_gate_functions_have_unchanged_asts():
    root = _path.parents[1]
    frozen = root / "runs/sqlite-authority/frozen-accepted-v2-source/scripts/validate_sql_authority.py"
    if not frozen.is_file():
        pytest.skip("accepted local evidence snapshot is not distributed")
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == "972235b4f32c085d2b5e18ef541afba2a61edbad57477290cfe9fc9c56e4b54e"
    def functions(path):
        return {node.name: ast.dump(node, include_attributes=False) for node in ast.parse(path.read_text()).body
                if isinstance(node, ast.FunctionDef)}
    old, new = functions(frozen), functions(_path)
    for name in harness.TRANSFER_FROZEN_FUNCTIONS:
        assert old[name] == new[name]


def test_frozen_populations_have_exactly_four_raw_endpoint_token_owners():
    from viva.ledger.identity import account_tokens
    for population in (100, 1000):
        cases, extra = harness.transfer_fixed_cases(population)
        assert len(cases) == population+3
        def tokens(case):
            p = case["payload"]
            return account_tokens(p["institution"], p["account_number"], p["account_ref"])
        raw = set().union(*(tokens(case) for case in cases[:3]))
        assert len([case for case in cases+[extra] if tokens(case) & raw]) == 4
        assert extra["currency"] == "EUR" and extra["payload"]["transactions"] == []


def test_growth_gate_requires_twenty_positive_samples_at_both_frozen_populations():
    assert harness.transfer_growth_gate({100: [10]*20, 1000: [20]*20})["gates_passed"]
    assert not harness.transfer_growth_gate({100: [10]*20, 1000: [21]*20})["gates_passed"]
    for invalid in ({100: [10]*19, 1000: [20]*20}, {100: [0]*20, 1000: [20]*20}, {100: [10]*20, 5000: [20]*20}):
        with pytest.raises(harness.HarnessFailure):
            harness.transfer_growth_gate(invalid)


def test_interval_one_meter_preserves_nested_callback_cadence_and_cancellation():
    class Connection:
        def set_progress_handler(self, callback, interval):
            self.callback, self.interval = callback, interval
    connection = Connection(); meter = harness.TransferVM(connection)
    calls = []
    meter.set_progress_handler(lambda: calls.append(True) or 1, 3)
    assert connection.interval == 1
    assert [connection.callback() for _ in range(6)] == [0, 0, 1, 0, 0, 1]
    assert meter.steps == 6 and len(calls) == 2
    meter.set_progress_handler(None, 0)
    assert connection.callback() == 0 and meter.steps == 7


def test_real_sql_meter_counts_queries_before_and_after_nested_handler_reset_and_restores():
    from types import SimpleNamespace
    connection = sqlite3.connect(":memory:")
    store = SimpleNamespace(_db=connection)
    with harness.transfer_vm(store) as meter:
        store._db.execute("CREATE TABLE synthetic(value INTEGER)")
        store._db.set_progress_handler(lambda: 0, 100)
        store._db.execute("INSERT INTO synthetic VALUES(1)")
        first = meter.steps
        store._db.set_progress_handler(None, 0)
        assert store._db.execute("SELECT value FROM synthetic").fetchall() == [(1,)]
        assert meter.steps > first > 0
    assert store._db is connection
    assert connection.execute("SELECT value FROM synthetic").fetchall() == [(1,)]
    connection.close()


@pytest.mark.production_kdf
def test_whole_operation_meter_preserves_actual_sql_actions_and_durable_state(tmp_path):
    import secrets
    from viva.sql_authority import SQLAuthority
    cases, extra = harness.transfer_fixed_cases()
    snapshots = []
    for index in range(2):
        root = tmp_path / ("measured" if index else "ordinary")
        passphrase = secrets.token_urlsafe(48)
        with SQLAuthority.create(root, passphrase) as store:
            for case in cases:
                assert store.ingest(case["original"], harness.transfer_reader(case, []), contract=harness.CONTRACT).status == "accepted"
            if index:
                with harness.transfer_vm(store) as meter:
                    result = store.ingest(extra["original"], harness.transfer_reader(extra, []), contract=harness.CONTRACT)
                assert meter.steps > store.last_vm_steps > 0
            else:
                result = store.ingest(extra["original"], harness.transfer_reader(extra, []), contract=harness.CONTRACT)
            assert result.status == "accepted"
            snapshots.append(harness.transfer_sql_snapshot(store))
            head = store.head
            assert store.verify(expected_head=head)["verified"]
        with SQLAuthority.open(root, passphrase) as reopened:
            assert harness.transfer_sql_snapshot(reopened) == snapshots[-1]
            assert reopened.verify(expected_head=head)["verified"]
    assert snapshots[0] == snapshots[1]
