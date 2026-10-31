"""Independent full-context transfer comparison rejects altered evidence."""
from copy import deepcopy
from decimal import Decimal
import importlib.util
from pathlib import Path
from types import SimpleNamespace as N

import pytest

_path = Path(__file__).resolve().parents[2] / "scripts/validate_sql_authority.py"
_spec = importlib.util.spec_from_file_location("transfer_comparison_harness", _path)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)


def context(*, owner=False, destinations=1):
    def movement(key, account, amount, day="2024-02-17"):
        return N(key=key, account=account, amount=Decimal(amount), date=day,
                 description="payment to 2222", currency="USD", kind="depository", linked=False)
    movements = [movement("s1", "a", "-10"), movement("s2", "c", "-10")]
    movements += [movement("d"+str(i), "b", "10", "2024-02-"+str(17+i)) for i in range(destinations)]
    infos = {a: N(kind="depository", currency="USD", institution="", number="2222" if a=="b" else "", name="")
             for a in ("a", "b", "c")}
    if owner:
        infos["outside"] = N(kind="", currency="EUR", institution="", number="2222", name="")
    return N(movements=lambda: movements, accounts=lambda: sorted(infos), account_info=lambda a: infos[a],
             transfer_suggestions=lambda: [])


def decision(projection):
    result = harness.transfer_full_context(projection)
    result["assertions"] = []
    return result


def test_omitted_reciprocal_rival_rejects_false_uniqueness():
    expected = decision(context())
    reduced = context()
    original = reduced.movements()
    reduced.movements = lambda: [m for m in original if m.key != "s2"]
    actual = decision(reduced)
    assert not expected["verdicts"] and actual["verdicts"] == {"s1": "d0"}
    with pytest.raises(harness.HarnessFailure):
        harness.compare_transfer_decision(expected, actual)


def test_omitted_global_owner_outside_graph_currency_and_kind_fails():
    expected = decision(context(owner=True))
    actual = decision(context())
    assert all(row["score"] == 0 for row in expected["strength"])
    assert all(row["score"] == 2 for row in actual["strength"])
    with pytest.raises(harness.HarnessFailure):
        harness.compare_transfer_decision(expected, actual)


def test_reversed_candidate_order_fails_even_when_pairs_and_scores_agree():
    expected = decision(context(destinations=2))
    actual = deepcopy(expected)
    actual["graph"]["s1"].reverse()
    with pytest.raises(harness.HarnessFailure, match="graph"):
        harness.compare_transfer_decision(expected, actual)


@pytest.mark.parametrize("dimension", ["movements", "assertions", "links", "suggestions", "stored", "as_of"])
def test_each_transfer_snapshot_dimension_is_required(dimension):
    expected = {key: [{"key": key}] for key in ("movements", "assertions", "links", "suggestions", "stored", "as_of")}
    actual = deepcopy(expected); actual[dimension] = []
    with pytest.raises(harness.HarnessFailure, match=dimension):
        harness.compare_transfer_snapshot(expected, actual)


def test_metadata_wakeup_missing_assertion_cannot_pass_snapshot_gate():
    expected = {"assertions": [{"event_type": "TransferLinked", "body": {"a": "s1", "b": "d"}}]}
    with pytest.raises(harness.HarnessFailure, match="assertions"):
        harness.compare_transfer_snapshot(expected, {"assertions": []})


@pytest.mark.parametrize("field", ["amount", "currency", "date", "occurrence", "account", "source_order", "provenance", "grade", "effective_date", "evidence"])
def test_exact_transport_and_binding_mutations_fail(field):
    expected = {"assertions": [{field: "original"}]}
    actual = deepcopy(expected); actual["assertions"][0][field] = "changed"
    with pytest.raises(harness.HarnessFailure):
        harness.compare_transfer_snapshot(expected, actual)


def test_assertion_and_duplicate_occurrence_order_are_not_sets():
    expected = {"assertions": [{"occurrence": 0}, {"occurrence": 1}]}
    with pytest.raises(harness.HarnessFailure):
        harness.compare_transfer_snapshot(expected, {"assertions": list(reversed(expected["assertions"]))})


@pytest.mark.production_kdf
def test_actual_sql_selector_mutations_fail_independent_legacy_comparison(tmp_path):
    rows = harness.run_transfer_selection_controls(tmp_path)
    assert [row["control"] for row in rows] == ["omit-rival", "omit-global-owner", "candidate-order", "metadata-wakeup"]
    assert all(row["rejected"] and row["hits"] and row["source_count"] >= 3 for row in rows)


@pytest.mark.production_kdf
def test_actual_sql_transitive_disconnected_and_genuine_growth_match_full_context(tmp_path):
    rows = harness.run_transfer_graph_correctness(tmp_path)
    by_name = {row["scenario"]: row for row in rows}
    assert by_name["transitive-bridge-chain"]["endpoints"] == 6
    assert by_name["disconnected-global-source-order"]["edges"] == 2
    assert by_name["genuine-component-growth-8"]["endpoints"] > by_name["genuine-component-growth-4"]["endpoints"]
    assert by_name["genuine-token-growth-3"]["owners"] > by_name["genuine-token-growth-1"]["owners"]


@pytest.mark.production_kdf
def test_genuine_empty_source_baseline_matches_activity_manual_writers_and_history(tmp_path):
    report = harness.run_transfer_manual_correctness(tmp_path)
    assert [row["completed"] for row in report["actions"]] == [True, False, True, False, True, False]
    assert report["genuine_empty_legacy_classification"] and report["sql_classification_family_absent"]
    assert report["invalid_classification_rejected"] and report["historical_source_order_relink"]
    assert report["finalized_pipeline_categories_retained"]


@pytest.mark.production_kdf
def test_actual_preferred_key_collisions_reuse_only_predeclared_helper_entropy(tmp_path):
    report = harness.run_transfer_collision_correctness(tmp_path)
    assert report["legacy_entropy"]["calls"] == report["sql_entropy"]["calls"]
    assert len(report["sql_entropy"]["calls"]) == 2
    assert report["independent_source_bijections"] and report["exact_assertion_candidate_order"]


def test_opaque_entropy_controls_reject_unexpected_size_over_or_under_consumption():
    from viva.ledger import identity
    original = identity.opaque_account_key
    values = ["a"*32]
    for operation, message in ((lambda: identity.opaque_account_key("depository"), "expected consumption"),):
        with pytest.raises(harness.HarnessFailure, match=message):
            with harness.transfer_opaque_entropy(values, 2):
                operation()
    with pytest.raises(harness.HarnessFailure, match="unexpected opaque"):
        with harness.transfer_opaque_entropy(values, 1):
            identity.opaque_account_key("depository")
            identity.opaque_account_key("depository")
    with pytest.raises(harness.HarnessFailure, match="entropy size"):
        harness.TransferOpaqueEntropy(values).token_hex(32)
    assert identity.opaque_account_key is original


@pytest.mark.production_kdf
def test_different_actual_collision_entropy_is_rejected_without_reordering_assertions(tmp_path):
    with pytest.raises(harness.HarnessFailure, match="financial parity"):
        harness.run_transfer_collision_correctness(tmp_path, reverse_sql_entropy=True)


def test_opaque_entropy_installation_failure_restores_all_aliases(monkeypatch):
    from viva.ledger import identity
    from viva.sql_authority import identity as sql_identity
    import secrets
    original, actual_random = identity.opaque_account_key, secrets.token_hex
    def fail(_data):
        raise RuntimeError("synthetic helper hash failure")
    monkeypatch.setattr(harness,"digest",fail)
    with pytest.raises(RuntimeError, match="helper hash failure"):
        with harness.transfer_opaque_entropy(["a"*32],1):
            pytest.fail("failed construction cannot yield")
    assert identity.opaque_account_key is original
    assert sql_identity.opaque_account_key is original
    assert secrets.token_hex is actual_random


def test_opaque_entropy_partial_alias_install_failure_restores_prior_aliases(monkeypatch):
    import sys
    from types import ModuleType
    from viva.ledger import identity
    from viva.sql_authority import identity as sql_identity
    original = identity.opaque_account_key
    class FailingAlias(ModuleType):
        def __setattr__(self, name, value):
            if name == "helper" and value is not original:
                raise RuntimeError("synthetic alias installation failure")
            return super().__setattr__(name,value)
    module = FailingAlias("synthetic_opaque_alias_failure")
    module.helper = original
    monkeypatch.setitem(sys.modules,module.__name__,module)
    with pytest.raises(RuntimeError, match="alias installation failure"):
        with harness.transfer_opaque_entropy(["a"*32],1):
            pytest.fail("partial installation cannot yield")
    assert identity.opaque_account_key is original
    assert sql_identity.opaque_account_key is original and module.helper is original


def test_opaque_entropy_body_failure_restores_newly_imported_aliases(monkeypatch):
    import sys
    from types import ModuleType
    from viva.ledger import identity
    from viva import crypto
    import secrets
    original, real_entropy = identity.opaque_account_key, secrets.token_hex
    actual_crypto = (crypto.os.urandom,crypto.seal,crypto.new_vault_header)
    imported = ModuleType("synthetic_opaque_new_alias")
    with pytest.raises(RuntimeError, match="body failure"):
        with harness.transfer_opaque_entropy(["a"*32],1):
            imported.helper = identity.opaque_account_key
            monkeypatch.setitem(sys.modules,imported.__name__,imported)
            assert imported.helper("depository") == "acct:depository:"+"a"*32
            assert secrets.token_hex is real_entropy
            assert (crypto.os.urandom,crypto.seal,crypto.new_vault_header) == actual_crypto
            raise RuntimeError("synthetic body failure")
    assert imported.helper is original and identity.opaque_account_key is original
    assert secrets.token_hex is real_entropy
